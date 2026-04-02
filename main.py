#!/usr/bin/env python3

import sys
import glob
import os
import time
import argparse
import _thread
import numpy as np
import h5py
from bisect import bisect_left
from PyQt5 import QtWidgets, QtGui, QtCore

from kern_visualiser import ScaleWindow
from mocap_vis import BulletMocapWindow
from video_player import VideoWindow


def get_closest_index(_list, myNumber):
    pos = bisect_left(_list, myNumber)
    if pos == 0:
        return 0
    if pos == len(_list):
        return len(_list) - 1
    before = _list[pos - 1]
    after = _list[pos]
    if after - myNumber < myNumber - before:
        return pos
    else:
        return pos - 1


class SeekBar(QtWidgets.QWidget):

    timeChanged = QtCore.pyqtSignal(float)

    def __init__(self, time_start, time_end):
        super().__init__()
        self._start = time_start
        self._end = time_end
        self._time = time_start
        self._mouse_offset = 0
        self.setMinimumSize(1, 24)

    @QtCore.pyqtProperty(float)
    def time(self):
        return self._time

    @time.setter
    def time(self, value):
        self._time = value
        self.repaint()

    def _handle_mouse_event(self, e):
        width = self.size().width()
        pos = max(0, min(e.x() + self._mouse_offset, width - 1))
        length = float(self._end - self._start)
        self._time = (float(pos) / (width - 1)) * length + self._start
        self.timeChanged.emit(self._time)

    def mousePressEvent(self, e):
        width = self.size().width()
        pos = int((width - 1) * (self._time - self._start) / float(self._end - self._start) + 0.5)
        self._mouse_offset = pos - e.x()
        if abs(self._mouse_offset) > 10:
            self._mouse_offset = 0
        self._handle_mouse_event(e)

    def mouseReleaseEvent(self, e):
        self._handle_mouse_event(e)

    def mouseMoveEvent(self, e):
        self._handle_mouse_event(e)

    def paintEvent(self, e):
        p = QtGui.QPainter()
        p.begin(self)
        width = self.size().width()
        height = self.size().height()
        pos = int((width - 1) * (self._time - self._start) / float(self._end - self._start) + 0.5)

        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(100, 180, 255))
        p.drawRect(0, 0, pos + 1, height)
        p.setBrush(QtGui.QColor(200, 200, 200))
        p.drawRect(pos + 1, 0, width - pos, height)

        p.setPen(QtGui.QColor(0, 0, 0, 70))
        p.drawLine(pos, 0, pos, height - 1)

        p.setPen(QtGui.QColor(0, 0, 0))
        time_ms = int((self._time - self._start) / 1e6)
        time_sec = time_ms / 1000
        time_min = int(time_sec / 60)
        text = "%d:%02d.%02d" % (time_min, int(time_sec) % 60, time_ms % 1000 // 10)
        p.drawText(QtCore.QRect(0, 0, width, height), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, text)
        p.end()


class Player(QtCore.QObject):

    def __init__(self, path_mocap, scale_window=None, tobii_window=None, bullet_window=None):
        super().__init__()
        self._path_mocap = path_mocap
        self.scale_window = scale_window
        self.tobii_window = tobii_window
        self.bullet_window = bullet_window
        self.play = False
        self._cancel = False
        self.mocap_index = 0

        with h5py.File(path_mocap, 'r') as f:
            self._rostime = f['rostime'][:].flatten()
        self._rostime_list = list(self._rostime)

        self.time_start_raw = int(self._rostime[0])
        self.time_end_raw = int(self._rostime[-1])

    def get_time_range(self):
        return self.time_start_raw, self.time_end_raw

    def set_valid_time_range(self, start, end):
        self.time_start = start
        self.time_end = end
        self.time = self.time_start

    def _loop(self):
        clock_last = time.time_ns()

        while not self._cancel:
            clock_now = time.time_ns()
            if self.play:
                self.time += clock_now - clock_last
            clock_last = clock_now

            if self.time > self.time_end:
                self.time = self.time_end

            self.mocap_index = get_closest_index(self._rostime_list, self.time)

            # time.sleep(0.01)
            time.sleep(1/120)

    def run(self):
        _thread.start_new_thread(self._loop, ())

    def close(self):
        self._cancel = True


class Window(QtWidgets.QMainWindow):

    def __init__(self, path_mocap, path_scale, path_tobii=None, mocap_only=0,
                 scene_json='object_models/scene.json', prj_path=""):
        super().__init__()

        self.scale_window = ScaleWindow(path_scale)
        scale_time_range = self.scale_window.get_time_range()

        self.bullet_window = BulletMocapWindow(path_mocap, scene_json)

        if mocap_only == 0 and path_tobii is not None:
            with open(path_tobii, 'r') as f_:
                parts = f_.readline().split()
                project_id, recording_id = parts[0], parts[1]
            self.tobii_window = VideoWindow(prj_path, project_id, recording_id)
            tobii_time_range = self.tobii_window.get_time_range()

            self._player = Player(path_mocap, self.scale_window, self.tobii_window, self.bullet_window)
            qtm_time_range = self._player.get_time_range()

            synced_start, synced_end = self._set_time_range(qtm_time_range, scale_time_range, tobii_time_range)
            self.tobii_window.set_valid_time_range(synced_start, synced_end)
        else:
            self.tobii_window = None
            self._player = Player(path_mocap, self.scale_window, None, self.bullet_window)
            qtm_time_range = self._player.get_time_range()
            synced_start, synced_end = self._set_time_range(qtm_time_range, scale_time_range)

        self._player.set_valid_time_range(synced_start, synced_end)
        self.scale_window.set_valid_time_range(synced_start, synced_end)
        self.bullet_window.set_valid_time_range(synced_start, synced_end)

        widget_vbox = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout()
        vbox.setSpacing(int(10 * self.logicalDpiY() / 96))
        widget_vbox.setLayout(vbox)
        self.setCentralWidget(widget_vbox)

        hbox = QtWidgets.QHBoxLayout()
        hbox.setSpacing(int(8 * self.logicalDpiX() / 96))
        vbox.addLayout(hbox)

        self._button_play = QtWidgets.QPushButton("play")
        self._button_play.setCheckable(True)
        self._button_play.clicked.connect(self.on_button_play_clicked)
        hbox.addWidget(self._button_play)

        self._seek_bar = SeekBar(self._player.time_start, self._player.time_end)
        self._seek_bar.timeChanged.connect(self.on_seekbar_timeChanged)
        vbox.addWidget(self._seek_bar)

        self._index_label = QtWidgets.QLabel("Mocap idx: ")
        vbox.addWidget(self._index_label)

        if self.tobii_window is not None:
            self.tobii_window.setParent(widget_vbox)
            vbox.addWidget(self.tobii_window)

        self.scale_window.setParent(widget_vbox)
        vbox.addWidget(self.scale_window)

        timer = QtCore.QTimer(self)
        timer.timeout.connect(self.on_timer_timeout)
        timer.start(16)

        self.setGeometry(100, 100, int(700 * self.logicalDpiX() / 96), int(900 * self.logicalDpiY() / 96))
        self.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.setFocus()

        self._player.run()

    def _set_time_range(self, qtm, scale, tobii=[0, np.inf]):
        start = max(qtm[0], scale[0], tobii[0])
        end = min(qtm[1], scale[1], tobii[1])
        return start, end

    def closeEvent(self, event):
        self._player.close()
        try:
            import pybullet as p
            if p.isConnected():
                p.disconnect()
        except Exception:
            pass
        try:
            self.scale_window.close()
        except Exception:
            pass
        try:
            self.tobii_window.close()
        except Exception:
            pass
        QtWidgets.QApplication.quit()

    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Escape or key == QtCore.Qt.Key_Q:
            self.close()
            return
        if key == QtCore.Qt.Key_Space:
            self.on_button_play_clicked()
        elif key == QtCore.Qt.Key_Left:
            self._change_time(-(1/120)*1000)
        elif key == QtCore.Qt.Key_Right:
            self._change_time((1/120)*1000)
        elif key == QtCore.Qt.Key_Up:
            self._change_time(-100)
        elif key == QtCore.Qt.Key_Down:
            self._change_time(100)
        elif key == QtCore.Qt.Key_PageUp:
            self._change_time(-1000)
        elif key == QtCore.Qt.Key_PageDown:
            self._change_time(1000)
        elif key == QtCore.Qt.Key_Home:
            self._change_time_abs(self._player.time_start)
        elif key == QtCore.Qt.Key_End:
            self._change_time_abs(self._player.time_end)

    def _change_time(self, offset_ms):
        self._change_time_abs(self._player.time + offset_ms * 1e6)

    def _change_time_abs(self, time):
        time = max(self._player.time_start, min(self._player.time_end, time))
        self._player.time = time
        self._update_time()

    def _update_time(self):
        self._seek_bar.time = self._player.time
        self._index_label.setText("Mocap idx: " + str(self._player.mocap_index))

    def on_button_play_clicked(self):
        self._player.play = not self._player.play
        self._button_play.setChecked(self._player.play)

    def on_seekbar_timeChanged(self, value):
        self._player.time = value

    def on_timer_timeout(self):
        self._update_time()
        if self._player.scale_window:
            self._player.scale_window.ext_command(self._player.time)
        if self._player.bullet_window:
            self._player.bullet_window.ext_command(self._player.time)
        if self._player.tobii_window:
            self._player.tobii_window.display_frame(self._player.time)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rec_time_stamp", nargs="?", default="", help='File to play back. format ddmmyyyyhhmmss')
    parser.add_argument("--mocap_only", type=int, default=0, help='if 0, display RGB video from eye tracker, otherwise only mocap')
    parser.add_argument("--dataset_path", help='path to dataset', required=True)
    parser.add_argument("--scene_json", default="object_models/scene.json", help='path to scene file for rendering mocap objects')
    args = parser.parse_args()

    datapath = args.dataset_path
    if not args.rec_time_stamp:
        path_mocap = max(glob.glob(datapath + 'data/m*'), key=os.path.getctime)
        path_scale = max(glob.glob(datapath + 'data/s*'), key=os.path.getctime)
        path_tobii = max(glob.glob(datapath + 'data/t*'), key=os.path.getctime)
    else:
        ts = args.rec_time_stamp
        rec_ts = "_" + ts[:8] + "_" + ts[8:10] + "_" + ts[10:12] + "_" + ts[12:14]
        path_mocap = glob.glob(datapath + "data/m_*" + rec_ts + ".hdf5")[0]
        path_scale = glob.glob(datapath + "data/s_*" + rec_ts + ".hdf5")[0]
        path_tobii = glob.glob(datapath + "data/t_*" + rec_ts + ".txt")[0]

    app = QtWidgets.QApplication(sys.argv)
    window = Window(path_mocap, path_scale, path_tobii, 
                    args.mocap_only, scene_json=args.scene_json, prj_path=datapath)
    window.show()
    sys.exit(app.exec_())
