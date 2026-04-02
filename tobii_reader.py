import json
import gzip
import os
from bisect import bisect_left


def _open_livedata(segment_dir):
    gz_path = os.path.join(segment_dir, "livedata.json.gz")
    json_path = os.path.join(segment_dir, "livedata.json")
    if os.path.exists(gz_path):
        return gzip.open(gz_path, "rt", encoding="utf-8")
    return open(json_path, "r", encoding="utf-8")


def parse_livedata(segment_dir):
    """
    Parse livedata.json(.gz) from a Tobii Pro Glasses 2 recording segment.

    The file is a stream of JSON objects.
    Relevant fields:
      "ts"   -- tobii timestamp in microseconds
      "s"    -- status: 0 = valid, non-zero = invalid
      "gp"   -- gaze position on scene video, normalised [x, y] in [0..1]
                 only valid when s==0
      "vts"  -- sparse video timestamp anchor (microseconds); when present,
                 tobii ts maps to this point in the video stream
      "type" -- event type string; "#sync_event#" is the rostime sync point
      "tag"  -- for sync events, contains rostime_ns as a string

    Returns
    -------
    gaze_ts    : list[float]         -- tobii ts (us) for valid gaze samples
    gaze_xy    : list[(float,float)] -- normalised gaze [0..1] matching gaze_ts
    vts_anchors: list[(ts_us, vts_us)] -- sparse video anchor pairs, sorted by ts_us
    sync_event : (ts_us, rostime_ns) | None
    """
    gaze_ts = []
    gaze_xy = []
    vts_anchors = []   # list of (tobii_ts_us, vts_us), sparse
    sync_event = None

    with _open_livedata(segment_dir) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = obj.get("ts")
            if ts is None:
                continue
            ts = float(ts)

            s = obj.get("s", 0)

            # valid gaze position on scene video
            if "gp" in obj and s == 0:
                gp = obj["gp"]
                if len(gp) == 2:
                    gaze_ts.append(ts)
                    gaze_xy.append((float(gp[0]), float(gp[1])))

            # video timestamp anchor (always s==0 in practice)
            if "vts" in obj and s == 0:
                vts_anchors.append((ts, float(obj["vts"])))

            # rostime sync event
            if obj.get("type") == "#sync_event#" and sync_event is None:
                try:
                    rostime_ns = int(obj["tag"])
                    sync_event = (ts, rostime_ns)
                except (KeyError, ValueError, TypeError):
                    pass

    vts_anchors.sort(key=lambda x: x[0])
    return gaze_ts, gaze_xy, vts_anchors, sync_event


def _bisect_closest(sorted_list, value):
    """Index of closest value in a sorted list."""
    if not sorted_list:
        return None
    pos = bisect_left(sorted_list, value)
    if pos == 0:
        return 0
    if pos >= len(sorted_list):
        return len(sorted_list) - 1
    before = sorted_list[pos - 1]
    after  = sorted_list[pos]
    return pos if (after - value) < (value - before) else pos - 1


class TobiiRecordingData:
    """
    Parsed Tobii Pro Glasses 2 recording data for one segment.

    Directory layout expected under root_dir:
        projects/<project_id>/recordings/<recording_id>/segments/<segment_id>/
            livedata.json(.gz)
            fullstream.mp4 

    The .txt file used by the player contains:
        <project_id> <recording_id> <participant_id>
    The rostime sync comes from the "#sync_event#" tag inside livedata itself.
    """

    def __init__(self, root_dir, project_id, recording_id, segment_id=1):
        seg_dir = os.path.join(
            root_dir, "projects", project_id,
            "recordings", recording_id,
            "segments", str(segment_id)
        )
        self.seg_dir = seg_dir

        self.gaze_ts, self.gaze_xy, self.vts_anchors, self.sync_event = \
            parse_livedata(seg_dir)

        if not self.vts_anchors:
            raise ValueError("No vts entries found in livedata -- cannot sync to video")
        if self.sync_event is None:
            raise ValueError("No #sync_event# found in livedata -- cannot sync to rostime")

        # video file
        for fname in ("fullstream.mp4", ):
            candidate = os.path.join(seg_dir, fname)
            if os.path.exists(candidate):
                self.video_path = candidate
                break
        else:
            raise FileNotFoundError(f"No video file found in {seg_dir}")

        # sync anchor: tobii ts (us) <-> rostime (ns)
        self.tobii_sync_ts_us, self.rostime_sync_ns = self.sync_event

        # vts_us is the position in the video stream (us) at the given tobii ts
        self._vts_ts  = [a[0] for a in self.vts_anchors]   # tobii ts axis
        self._vts_val = [a[1] for a in self.vts_anchors]   # vts value axis

        # playback state -- set properly by init_video + set_valid_time_range
        self._gaze_map = None
        self.fps = None
        self.v_period_us = None
        self.total_frames = None
        self.curr_vid_frame_index = 0
        self.vid_start_index = 0
        self.vid_end_index = 0
        self.tobii_ts_start_us = self.tobii_sync_ts_us
        self.rostime_start_ns  = self.rostime_sync_ns

    # ------------------------------------------------------------------
    # video stream position interpolation
    # ------------------------------------------------------------------

    def _tobii_ts_to_vts(self, tobii_ts_us):
        """
        Interpolate vts (video stream position, us) for an arbitrary tobii ts.
        vts_anchors are sparse so we linearly interpolate between neighbours.
        """
        ts_list = self._vts_ts
        if not ts_list:
            return 0.0
        pos = bisect_left(ts_list, tobii_ts_us)

        if pos == 0:
            # before first anchor: extrapolate backwards assuming 1:1 ts->vts
            dt = tobii_ts_us - ts_list[0]
            return self._vts_val[0] + dt
        if pos >= len(ts_list):
            # after last anchor: extrapolate forwards
            dt = tobii_ts_us - ts_list[-1]
            return self._vts_val[-1] + dt

        # interpolate between pos-1 and pos
        t0, v0 = ts_list[pos - 1], self._vts_val[pos - 1]
        t1, v1 = ts_list[pos],     self._vts_val[pos]
        frac = (tobii_ts_us - t0) / (t1 - t0)
        return v0 + frac * (v1 - v0)

    def _vts_to_frame(self, vts_us):
        """Convert video stream position (us) to frame index."""
        vts_origin = self._vts_val[0]    # vts value at the first anchor
        return max(0, int((vts_us - vts_origin) / self.v_period_us))

    def _tobii_ts_to_frame(self, tobii_ts_us):
        vts = self._tobii_ts_to_vts(tobii_ts_us)
        return self._vts_to_frame(vts)


    def init_video(self, cap):
        """open cv2.VideoCapture to finish setup."""
        import cv2
        self.fps          = cap.get(cv2.CAP_PROP_FPS)
        self.v_period_us  = (1.0 / self.fps) * 1e6
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.vid_end_index = self.total_frames - 1
        self._build_gaze_map()

    def _build_gaze_map(self):
        """
        Build list of normalised gaze (x, y) per frame index.
        For each frame, find the gaze sample whose tobii ts is closest
        to the tobii ts of that frame. (-1, -1) = no valid gaze.
        """
        self._gaze_map = [(-1.0, -1.0)] * self.total_frames
        if not self.gaze_ts:
            return

        for frame_idx in range(self.total_frames):
            vts_us = self._vts_val[0] + frame_idx * self.v_period_us
            # invert vts -> tobii ts using the anchor table
            frame_tobii_ts = self._vts_to_tobii_ts(vts_us)
            gi = _bisect_closest(self.gaze_ts, frame_tobii_ts)
            if gi is not None:
                self._gaze_map[frame_idx] = self.gaze_xy[gi]

    def _vts_to_tobii_ts(self, vts_us):
        """Inverse of _tobii_ts_to_vts: given vts find tobii ts."""
        val_list = self._vts_val
        pos = bisect_left(val_list, vts_us)
        if pos == 0:
            dt = vts_us - val_list[0]
            return self._vts_ts[0] + dt
        if pos >= len(val_list):
            dt = vts_us - val_list[-1]
            return self._vts_ts[-1] + dt
        v0, t0 = val_list[pos - 1], self._vts_ts[pos - 1]
        v1, t1 = val_list[pos],     self._vts_ts[pos]
        frac = (vts_us - v0) / (v1 - v0)
        return t0 + frac * (t1 - t0)

    def get_gaze_norm_for_frame(self, frame_index):
        """Return normalised gaze (x, y) in [0..1] or (-1, -1) if invalid."""
        if self._gaze_map is None or frame_index >= len(self._gaze_map):
            return (-1.0, -1.0)
        return self._gaze_map[frame_index]

    def get_time_range(self):
        # duration from sync event to last gaze sample
        duration_us = self.gaze_ts[-1] - self.tobii_sync_ts_us
        rostime_end_ns = self.rostime_sync_ns + int(duration_us * 1e3)
        return self.rostime_sync_ns, rostime_end_ns

    def set_valid_time_range(self, start_ns, end_ns):
        delta_us = (start_ns - self.rostime_sync_ns) * 1e-3
        self.tobii_ts_start_us = self.tobii_sync_ts_us + delta_us
        self.rostime_start_ns  = start_ns
        self.vid_start_index   = int(
            max(0, min(self.total_frames - 1,
                       self._tobii_ts_to_frame(self.tobii_ts_start_us))))
        self.curr_vid_frame_index = self.vid_start_index

        delta_us_end = (end_ns - self.rostime_sync_ns) * 1e-3
        tobii_ts_end = self.tobii_sync_ts_us + delta_us_end
        self.vid_end_index = int(
            max(0, min(self.total_frames - 1,
                       self._tobii_ts_to_frame(tobii_ts_end))))

    def update_data(self, rostime_ns):
        delta_us = (rostime_ns - self.rostime_start_ns) * 1e-3
        tobii_ts_curr = self.tobii_ts_start_us + delta_us
        frame = self._tobii_ts_to_frame(tobii_ts_curr)
        self.curr_vid_frame_index = int(
            max(self.vid_start_index, min(self.vid_end_index, frame)))

