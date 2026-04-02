
from PyQt5 import QtWidgets
import pyqtgraph as pg
import h5py
from bisect import bisect_left


def get_closest_index(_list, myNumber):
    """
    Assumes myList is sorted. Returns closest value to myNumber.

    If two numbers are equally close, return the larger number.
    """
    pos = bisect_left(_list, myNumber)
    if pos == 0:
        return 0
    if pos == len(_list):
        return len(_list)
    before = _list[pos - 1]
    after = _list[pos]
    if after - myNumber < myNumber - before:    
        return pos
    else:
        return pos - 1

class ScaleWindow(QtWidgets.QWidget):
    def __init__(self, path):
        super().__init__()
        # Use QtWidgets for layouts
        lay_1 = QtWidgets.QVBoxLayout()
        lay_2 = QtWidgets.QHBoxLayout()
        self.setLayout(lay_1)
        
        # Use QtWidgets for labels and widgets
        label_1 = QtWidgets.QLabel('time = ')
        label_2 = QtWidgets.QLabel(', weight = ')
        self.label = QtWidgets.QLabel("Scale Window")
        lay_1.addWidget(self.label)
        
        self.box_1 = QtWidgets.QDoubleSpinBox()
        self.box_1.setButtonSymbols(2)
        self.box_2 = QtWidgets.QDoubleSpinBox()
        self.box_2.setButtonSymbols(2)
        self.box_2.setReadOnly(True)
        
        # Use QtWidgets for spacers and size policies
        spacer = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.graf = pg.PlotWidget(background='#ffffff')
        self.graf.showGrid(x=True, y=True)
        pen = pg.mkPen(color=(0,0,255))
        self.plt = self.graf.plot(pen=pen)
        pen = pg.mkPen(color=(255,0,0))
        self.v_line = pg.InfiniteLine(pen=pen, angle=90, movable=True)
        lay_1.addLayout(lay_2)
        lay_1.addWidget(self.graf)
        lay_2.addWidget(label_1)
        lay_2.addWidget(self.box_1)
        lay_2.addWidget(label_2)
        lay_2.addWidget(self.box_2)
        lay_2.addItem(spacer)
        self.graf.addItem(self.v_line)
        self.read_scaledata(path)
        self.box_1.setRange(self.x.min()/1000000000, self.x.max()/1000000000)  # ns to s
        self.box_2.setRange(self.y.min()/100, self.y.max()/100)  # adjusting 100 point precesion
        self.data = [self.x/1000000000, self.y/100]
        self.plt.setData(*self.data)

    def get_time_range(self):
        return self.x_absolute[0], self.x_absolute[-1]

    def set_valid_time_range(self, start, end):
        start_index = self.get_index(start)
        end_index = self.get_index(end)
        self._index = start_index
        self._last_time = start
        self._start_index = start_index
        self._end_index = end_index

    def read_scaledata(self, path):
        with h5py.File(path, 'r') as f:
            d_time = f["rostime"][:].flatten()
            d_values = f["scale_data"][:].flatten()
        self.x_absolute = d_time
        self.x = d_time - d_time[0]
        self.y = d_values
        self.x_min = min(self.x)
        self.x_max = max(self.x)

        self._index = 0
        self._last_time = self.x_min
        self._start_index = 0
        self._end_index = len(self.x) - 1

    def get_index(self, rostime):
        index = get_closest_index(self.x_absolute, rostime)
        return index

    def ext_command(self, rostime):
        index = self.get_index(rostime)
        self.upd_v_line(index)

    def upd_v_line(self, index):
        try:
            x = self.x[index]
            y = self.y[index]
            self.v_line.setPos(x/1000000000)
            self.box_1.setValue(x/1000000000)
            self.box_2.setValue(y/100)
        except Exception as e:
            print(e)
