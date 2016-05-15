# -*- coding: utf-8 -*- 

import wx
import numpy as np
import time
import os
import threading
from epics import PV
from epics.ca import CAThread, create_context, destroy_context
import matplotlib
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas  
from matplotlib.backends.backend_wxagg import NavigationToolbar2WxAgg as NavigationToolbar  
from matplotlib.ticker import MultipleLocator, FuncFormatter
from matplotlib.figure import Figure
import scipy.constants as C

import pylab  
from matplotlib import pyplot 
from leastsq import getTWPhase

basedir = os.path.abspath(os.path.dirname(__file__))

class WorkThread(CAThread):
    def __init__(self, window, Win, first_cavity_id, last_cavity_id, first_phase, last_phase, phase_step, delay_before_scan, delay_read, num_read): 
        CAThread.__init__(self)
        self.window = window
        self.Win = Win
        self.first_cavity_id = first_cavity_id
        self.last_cavity_id = last_cavity_id
        self.first_phase = first_phase
        self.last_phase = last_phase
        self.phase_step = phase_step
        self.delay_before_scan = delay_before_scan
        self.delay_read = delay_read
        self.num_read = num_read

        self.timeToQuit = threading.Event()
        self.timeToPause = threading.Event()
        self.timeToQuit.clear()
        self.timeToPause.clear()
        self.pause = False

    def scan(self, index, cavity_pv):
        x = []
        y = []
        wx.CallAfter(self.window.clear_graph)
       
        f = open('%s.%s' % (self.window.cavityList[index], 'txt'), 'w')
        wx.CallAfter(self.window.slider.SetRange, 0, self.last_phase - self.first_phase)
        self.cavity_pv = PV(cavity_pv)
        self.bpm_pv = PV(self.window.bpm_pv[index])

        first_phase = self.first_phase

        while ((self.last_phase - first_phase) * self.phase_step > 0):
            if self.timeToQuit.isSet(): 
                break
            if self.pause:
                self.timeToPause.wait()

            wx.CallAfter(self.window.slider.SetValue, first_phase - self.first_phase)
            self.cavity_pv.put(first_phase)
            time.sleep(2)

            bpm_phases = []
            for i in range(self.num_read):
                bpm_phase = self.bpm_pv.get()
                bpm_phases.append(bpm_phase)
                self.timeToQuit.wait(self.delay_read)

            average = np.mean(bpm_phases)
            rms = np.std(bpm_phases)
            f.write('%s\t' % first_phase)
            f.write('%s\t' % average)
            f.write('%s\n' % rms)

            x.append(first_phase)
            y.append(average)
            wx.CallAfter(self.window.updateGraph, self.window.scan_line, x, y)
            first_phase += self.phase_step

        f.close()
        return x, y

    def fit(self, index, cav, x, y):
        distance = self.window.distance_cav_bpm[index]
        twPhase = self.window.synch_phases[index]
        fieldName = self.window.field_names[index]
        step = self.phase_step * C.pi / 180
        slope = self.window.slopes[index]

        rfPhase, energy_gain, amp, e, x_plot, y_plot = getTWPhase(x, y, self.Win, distance, twPhase, fieldName, step, self.first_phase, slope)
        return rfPhase, energy_gain, amp, e, x_plot, y_plot

    def prepare_for_next(self, rfPhase, energy_gain, amp, x_plot, y_plot):
        self.Win += energy_gain
        self.cavity_pv.put(rfPhase)
        wx.CallAfter(self.window.display_frame.write_line, '%s\t%s\t%s' % (rfPhase, self.Win, amp))
        wx.CallAfter(self.window.updateGraph, self.window.fit_line, x_plot, y_plot)

    def handle_error(self, index):
        wx.CallAfter(self.window.handle_error, index)

    def run(self):
        create_context()
        
        for i, cav in enumerate(self.window.cavity_set_phase[self.first_cavity_id:self.last_cavity_id + 1]):
            index = i + self.first_cavity_id
            x, y = self.scan(index, cav)
            rfPhase, energy_gain, amp, e, x_plot, y_plot = self.fit(index, cav, x, y)
            if e < self.window.TOLERANCE:
                self.prepare_for_next(rfPhase, energy_gain, amp, x_plot, y_plot)
                time.sleep(10)
            else:
                self.handle_error(index)
                break

        wx.CallAfter(self.window.reset_buttons)
        destroy_context()

class CanvasPanel(wx.Panel):
    def __init__(self, parent):
        wx.Panel.__init__(self, parent, -1)
        self.figure = Figure()
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self, -1, self.figure)
        self.canvas.mpl_connect('motion_notify_event', parent.updateStatusBar)
        self.NavigationToolbar = NavigationToolbar(self.canvas)

        self.axes.set_autoscale_on(True)
        
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.NavigationToolbar, 0, wx.ALL, 5)
        self.sizer.Add(self.canvas, 1, wx.LEFT | wx.TOP | wx.GROW, 5)
        self.SetSizer(self.sizer)

class DisplayFrame(wx.Frame):
    def __init__(self):
        wx.Frame.__init__(self, None, -1, 'Display parameters for each cavity')
        panel = wx.Panel(self, -1)
        self.text = wx.TextCtrl(panel, -1, "", style=wx.TE_MULTILINE)

        bsizer = wx.BoxSizer()
        bsizer.Add(self.text, 1, wx.EXPAND)
        panel.SetSizerAndFit(bsizer)

    def write_line(self, text):
        self.text.WriteText(text)
        self.text.WriteText('\n')

class MyFrame(wx.Frame):
    cavity_set_phase = ['LLRF:Buncher1:PHA_SET', 'LLRF:Buncher2:PHA_SET', 'SCRF:CAV1:PHASE:SETPOINT', 'SCRF:CAV2:PHASE:SETPOINT', 'SCRF:CAV3:PHASE:SETPOINT', 'SCRF:CAV4:PHASE:SETPOINT', 'SCRF:CAV5:PHASE:SETPOINT', 'SCRF:CAV6:PHASE:SETPOINT', 'LLRF:CM2_Cavity1:PHA_SET', 'LLRF:CM2_Cavity2:PHA_SET', 'LLRF:CM2_Cavity3:PHA_SET', 'LLRF:CM2_Cavity4:PHA_SET', 'LLRF:CM2_Cavity5:PHA_SET', 'LLRF:CM2_Cavity6:PHA_SET']
    bpm_pv = ['Bpm:2-P11', 'Bpm:5-P11', 'Bpm:6-P11', 'Bpm:7-P11', 'Bpm:8-P11', 'Bpm:9-P11', 'Bpm:10-P11', 'Bpm:11-P11', 'Bpm:12-P11', 'Bpm:13-P11', 'Bpm:14-P11', 'Bpm:15-P11', 'Bpm:16-P11', 'Bpm:17-P11']
    distance_cav_bpm = [0.1, 0.15, 0.1026, 0.1026, 0.1026, 0.1026, 0.1026, 0.1026, 0.1026, 0.1026, 0.1026, 0.1026, 0.1026, 0.1026]
    field_names = ['buncher_field.txt', 'buncher_field.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt', 'Exyz.txt']
    synch_phases = [-90, -90, -25, -25, -25, -20, -20, -20, -20, -20, -20, -20, -20, -20] 
    slopes = [1, 1, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 1, 1, 1, 1, 1, 1]  
    TOLERANCE = 100

    def __init__(self):
        wx.Frame.__init__(self, None, -1, "PhaseScan")
        self.panel = wx.Panel(self, -1)
        self.pltPanel = CanvasPanel(self) 
        self.cavityList = ['buncher1', 'buncher2', 'hwr1', 'hwr2', 'hwr3', 'hwr4', 'hwr5', 'hwr6', 'hwr7', 'hwr8', 'hwr9', 'hwr10', 'hwr11', 'hwr12']

        self.start_cavity_name = wx.StaticText(self.panel, -1, 'Begin Cavity')
        self.end_cavity_name = wx.StaticText(self.panel, -1, 'End Cavity')
        self.start_cavity = wx.ComboBox(self.panel, -1, 'buncher1', wx.DefaultPosition, wx.DefaultSize, self.cavityList, wx.CB_DROPDOWN)
        self.end_cavity = wx.ComboBox(self.panel, -1, 'hwr12', wx.DefaultPosition, wx.DefaultSize, self.cavityList, wx.CB_DROPDOWN)

        self.begin = wx.TextCtrl(self.panel, -1, '-180', size=(50, -1))
        self.current = wx.TextCtrl(self.panel, -1, '0', size=(50, -1))
        self.end = wx.TextCtrl(self.panel, -1, '180', size=(50, -1))
        self.slider = wx.Slider(self.panel, -1, 0, -180, 180, style=wx.SL_HORIZONTAL)

        self.stepLabel = wx.StaticText(self.panel, -1, 'SCAN with step:')
        self.step = wx.TextCtrl(self.panel, -1, '10', size=(50, -1))
        self.delayLabel = wx.StaticText(self.panel, -1, 'time delay after setting [sec]:')
        self.delay = wx.TextCtrl(self.panel, -1, '0.5', size=(50, -1))

        self.averageRadio = wx.RadioButton(self.panel, -1, 'Average for N read out with T delay')
        self.avg_num_title = wx.StaticText(self.panel, -1, 'N')
        self.avg_num = wx.TextCtrl(self.panel, -1, '5', size=(50, -1))
        self.avg_delay_title = wx.StaticText(self.panel, -1, 'T delay [sec]=')
        self.avg_delay = wx.TextCtrl(self.panel, -1, '1', size=(50, -1))
 
        self.startButton = wx.Button(self.panel, -1, "start")
        self.Bind(wx.EVT_BUTTON, self.OnStart, self.startButton)
        self.pauseButton = wx.Button(self.panel, -1, "pause")
        self.Bind(wx.EVT_BUTTON, self.OnPause, self.pauseButton)
        self.stopButton = wx.Button(self.panel, -1, "stop")
        self.Bind(wx.EVT_BUTTON, self.OnStop, self.stopButton)
        self.Bind(wx.EVT_CLOSE, self.OnCloseWindow)

        injectEnergyTitle = wx.StaticText(self.panel, -1, 'Win[MeV]')
        self.injectEnergy = wx.TextCtrl(self.panel, -1, '2.1', size=(70, -1))

        self.statusBar = self.CreateStatusBar()

        cavSizer = wx.FlexGridSizer(2, 2, 5, 5)
        cavSizer.AddGrowableCol(1)
        cavSizer.AddMany([(self.start_cavity_name, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL), (self.start_cavity, 0, wx.EXPAND), (self.end_cavity_name, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL), (self.end_cavity, 0, wx.EXPAND)])

        injectSizer = wx.BoxSizer(wx.HORIZONTAL)
        injectSizer.Add(injectEnergyTitle, 0, wx.ALIGN_CENTRE | wx.ALL, 2)
        injectSizer.Add(self.injectEnergy, 0, wx.ALL, 2)
        
        rangeSizer = wx.BoxSizer(wx.HORIZONTAL)
        rangeSizer.Add(self.begin, 1, wx.ALL, 2) 
        rangeSizer.Add(self.current, 1, wx.ALL, 2)
        rangeSizer.Add(self.end, 1, wx.ALL, 2)

        stepSizer = wx.BoxSizer(wx.HORIZONTAL)
        stepSizer.Add(self.stepLabel, 0, wx.ALIGN_CENTRE | wx.ALL, 2)
        stepSizer.Add(self.step, 0, wx.ALL, 2)

        delaySizer = wx.BoxSizer(wx.HORIZONTAL)
        delaySizer.Add(self.delayLabel, 0, wx.ALIGN_CENTRE | wx.ALL, 2)
        delaySizer.Add(self.delay, 0, wx.ALL, 2)

        avgSizer = wx.BoxSizer(wx.HORIZONTAL)
        avgSizer.Add(self.avg_num_title, 0, wx.ALIGN_CENTRE | wx.ALL, 2)
        avgSizer.Add(self.avg_num, 0, wx.ALL, 2)
        avgSizer.Add(self.avg_delay_title, 0, wx.ALIGN_CENTRE | wx.ALL, 2)
        avgSizer.Add(self.avg_delay, 0, wx.ALL, 2)
        
        btSizer = wx.BoxSizer(wx.HORIZONTAL)
        btSizer.Add(self.startButton, 0, wx.ALL, 2)
        btSizer.Add(self.pauseButton, 0, wx.ALL, 2)
        btSizer.Add(self.stopButton, 0, wx.ALL, 2)

        scanBox = wx.StaticBox(self.panel, -1, 'scan')
        sizer = wx.StaticBoxSizer(scanBox, wx.VERTICAL)
        sizer.Add(injectSizer, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(cavSizer, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(rangeSizer, 0, wx.EXPAND, wx.ALL, 5)
        sizer.Add(self.slider, 0, wx.EXPAND, wx.ALL, 5)
        sizer.Add(stepSizer, 0, wx.ALL, 5)
        sizer.Add(delaySizer, 0, wx.ALL, 5)
        sizer.Add(self.averageRadio, 0, wx.EXPAND, wx.ALL, 5)
        sizer.Add(avgSizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        sizer.Add(btSizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        self.panel.SetSizer(sizer)
        
        sz = wx.BoxSizer(wx.HORIZONTAL)
        sz.Add(self.panel, 0, wx.ALL, 5)
        sz.Add(self.pltPanel, 1, wx.ALL, 5)
        self.SetSizerAndFit(sz)

        self.pauseButton.Disable()
        self.stopButton.Disable()

        self.display_frame = DisplayFrame()

    def load_config(self):
        config_file = np.loadtxt(os.path.join(basedir, 'config.txt')
        cavity_set_phase = config_file[:, 0]
        bpm_pv = config_file[:, 1]
        distance_cav_bpm = config_file[:, 2]
        field_names = config_file[:, 3]
        synch_phases = config_file[:, 4]
        slopes = config_file[:, 5]
        return cavity_set_phase, bpm_pv, distance_cav_bpm, field_names, synch_phases, slopes

    def initiate(self):
        self.startButton.Disable()
        self.input_parameter()
        self.set_lines()
        self.display_frame.Show()

    def handle_error(self, index):
        wx.MessageBox('Some problem found', 'Error', wx.OK | wx.ICON_ERROR)
        self.injectEnergy.SetValue(self.Win)
        self.start_cavity.SetValue(self.cavityList[index])
        self.stop_thread()
        self.reset_buttons()

    def stop_thread(self):
        self.thread.timeToQuit.set()

    def reset_buttons(self):
        self.startButton.Enable()
        self.stopButton.Disable()
        self.pauseButton.Disable()
        self.pauseButton.SetLabel('pause')

    def input_parameter(self):
        self.Win = float(self.injectEnergy.GetValue())
        self.first_cavity_id = self.cavityList.index(self.start_cavity.GetValue())
        self.last_cavity_id = self.cavityList.index(self.end_cavity.GetValue())
        self.first_phase = float(self.begin.GetValue())
        self.last_phase = float(self.end.GetValue())
        self.phase_step = int(self.step.GetValue())
        self.delay_before_scan = float(self.delay.GetValue())
        self.delay_read = float(self.avg_delay.GetValue())
        self.num_read = int(self.avg_num.GetValue())
    
    def set_lines(self):
        self.scan_line, = self.pltPanel.axes.plot([], [], marker='o')
        self.fit_line, = self.pltPanel.axes.plot([], [], marker='o')

    '''
    def resetCanvas(self):
        self.scan_line.set_xdata([])
        self.scan_line.set_ydata([])
        self.fit_line.set_xdata([])
        self.fit_line.set_ydata([])
    '''

    def OnStart(self, event):
        self.initiate()

        if self.pauseButton.Enabled:
            self.thread.timeToPause.set()
            self.thread.timeToQuit.set()
        else:
            self.pauseButton.Enable()

        self.thread = WorkThread(self, self.Win, self.first_cavity_id, self.last_cavity_id, self.first_phase, self.last_phase,  self.phase_step, self.delay_before_scan, self.delay_read, self.num_read)
        self.thread.start()

        self.stopButton.Enable()
        self.pauseButton.SetLabel('pause')

    def OnStop(self, event):
        self.reset_buttons()
        self.stop_thread()

    def OnPause(self, event):
        if self.pauseButton.GetLabel() == 'pause':
            self.thread.pause = True
            self.startButton.Enable()
            self.stopButton.Disable()
            self.pauseButton.SetLabel('resume')
        else:
            self.thread.timeToPause.set()
            self.pauseButton.SetLabel('pause')
            self.startButton.Disable()
            self.stopButton.Enable()

    def changeLabel(self, label):
        self.startButton.SetLabel(label)

    def OnCloseWindow(self, event):
        if self.stopButton.Enabled:
            self.OnStop(event)
        self.Destroy()

    def getBpmPhase(self, value):
        self.bpm_phase.SetValue(str(value))

    def updateGraph(self, line, x, y):
        plotPanel = self.pltPanel
        line.set_xdata(x)
        line.set_ydata(y)
        plotPanel.axes.relim()
        plotPanel.axes.autoscale_view()
        plotPanel.canvas.draw()

    def updateStatusBar(self, event):
        if event.inaxes:
            x, y = event.xdata, event.ydata
            self.statusBar.SetStatusText(('x= ' + str(x) + ' y=' + str(y)), 0)

    def clear_graph(self):
        self.updateGraph(self.scan_line, [], [])
        self.updateGraph(self.fit_line, [], [])


if __name__ == '__main__':
    app = wx.App()
    frame = MyFrame()
    frame.Show(True)
    app.MainLoop()


