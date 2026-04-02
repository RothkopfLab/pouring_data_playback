import cv2
from PyQt5 import QtWidgets, QtGui

from tobii_reader import TobiiRecordingData


display_width  = 640
display_height = 360


class VideoWindow(QtWidgets.QWidget):
    def __init__(self, root_dir, project_id, recording_id):
        super().__init__()
        layout = QtWidgets.QVBoxLayout()
        self.setGeometry(50, 50, display_width, display_height)
        self.setWindowTitle("Gaze Video")
        self.video_frame = QtWidgets.QLabel()
        self.video_frame.resize(display_width, display_height)
        layout.addWidget(self.video_frame)
        self.setLayout(layout)

        self.record_player = TobiiRecordingData(root_dir, project_id, recording_id)
        self.cap = cv2.VideoCapture(self.record_player.video_path)
        self.record_player.init_video(self.cap)  # sets fps, builds gaze map

    def get_time_range(self):
        return self.record_player.get_time_range()

    def set_valid_time_range(self, start, end):
        self.record_player.set_valid_time_range(start, end)

    def display_frame(self, rostime):
        self.record_player.update_data(rostime)
        frame_index = self.record_player.curr_vid_frame_index

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = self.cap.read()
        if not ret:
            return

        vid_h, vid_w = frame.shape[:2]
        gx_norm, gy_norm = self.record_player.get_gaze_norm_for_frame(frame_index)
        if gx_norm >= 0 and gy_norm >= 0:
            gx_px = int(gx_norm * vid_w)
            gy_px = int(gy_norm * vid_h)
            cv2.circle(frame, (gx_px, gy_px), 10, (0, 0, 255), 2)

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = cv2.resize(frame, (display_width, display_height))
        img = QtGui.QImage(frame, frame.shape[1], frame.shape[0], QtGui.QImage.Format_RGB888)
        self.video_frame.setPixmap(QtGui.QPixmap.fromImage(img))

    def closeEvent(self, event):
        self.cap.release()
        super().closeEvent(event)
