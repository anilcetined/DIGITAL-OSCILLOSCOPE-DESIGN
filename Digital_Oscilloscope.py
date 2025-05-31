import spidev
import numpy as np
import time
from gpiozero import RotaryEncoder, Button
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore, QtGui

encoder = RotaryEncoder(a=5, b=6, max_steps=0)
scale_encoder = RotaryEncoder(a=20, b=21, max_steps=0)
cursor_encoder = RotaryEncoder(a=17, b=27, max_steps=0)
button2 = Button(16)
button = Button(13)
button3 = Button(22)  # Rotary encoder's switch button
cursor_enabled = False

trigger_mode = False
measure_mode = False
cursor_mode = True
cursor_pos = 0

offset = 0
trigger_idx = None
signal = None
fs = None
sample_step = None
sw_state = 0
y_zoom_level = 0
x_zoom_level = 0
scaling_mode = "y"

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 2000000
spi.mode = 1

N_total = 8193
trigger_threshold = 2000

def adc_to_voltage(adc_vals):
    return (adc_vals / 4095.0) * 10.0 - 5.0

def sw_pressed():
    global trigger_mode, measure_mode, sw_state, cursor_enabled
    sw_state = (sw_state + 1) % 4

    trigger_mode = False
    measure_mode = False
    if sw_state == 0:
        print("Live mode: ON")
    elif sw_state == 1:
        trigger_mode = True
        encoder.steps = 0
        print("Trigger mode: ON")
    elif sw_state == 2:
        measure_mode = True
        encoder.steps = 0
        print("Measure mode: ON")
    elif sw_state == 3:
        trigger_mode = True
        print("Trigger mode: ON")

def toggle_scaling_mode():
    global scaling_mode
    scaling_mode = "x" if scaling_mode == "y" else "y"
    print("Scaling mode:", scaling_mode.upper())

def toggle_cursor():
    global cursor_enabled
    if measure_mode:
        cursor_enabled = not cursor_enabled
        print("Cursor:", "ON" if cursor_enabled else "OFF")

def sync_fpga():
    spi.xfer2([0xAA])
    time.sleep(0.001)

def read_samples(n):
    raw = []
    max_chunk = 2048
    while n > 0:
        r = min(n, max_chunk)
        raw.extend(spi.xfer2([0, 0] * r))
        n -= r
    return [((raw[2 * i] << 8) | raw[2 * i + 1]) & 0x0FFF for i in range(len(raw) // 2)]

def apply_scaling():
    global y_zoom_level, x_zoom_level
    if scaling_mode == "y":
        y_zoom_level = scale_encoder.steps
        zoom_step = 400
        current_range = max(0.5, 10 - y_zoom_level * (10 / (4096 / zoom_step)))
        center = 0.0
        lower = center - current_range / 2
        upper = center + current_range / 2
        plot.setYRange(lower, upper)
    elif scaling_mode == "x":
        x_zoom_level = max(0, scale_encoder.steps)

def format_us(val):
    return f"{val / 1000:.2f} ms" if val >= 1000 else f"{val:.2f} us"

button.when_pressed = sw_pressed
button2.when_pressed = toggle_scaling_mode
button3.when_pressed = toggle_cursor

app = QtWidgets.QApplication([])
win = pg.GraphicsLayoutWidget(show=True, title="Oscilloscope")
title_label = pg.LabelItem(justify='center')
win.addItem(title_label, row=0, col=0)
layout = win.addLayout(row=1, col=0)
plot = layout.addPlot()
curve = plot.plot(pen='y')
cursor_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('r'))
cursor_line.setPos(-1e6)  # hide at start
plot.addItem(cursor_line)
plot.setYRange(-5, 5)
plot.showGrid(x=True, y=True)

vpp_text = pg.TextItem(text="", anchor=(0, 1), color='w')
vmax_text = pg.TextItem(text="", anchor=(0, 0), color='w')
cursor_val_text = pg.TextItem(text="", anchor=(0, 0), color='r')
plot.addItem(vpp_text)
plot.addItem(vmax_text)
plot.addItem(cursor_val_text)

try:
    while True:
        apply_scaling()
        base = 1024
        zoom_level = x_zoom_level if scaling_mode == "x" else 0
        x_window = base >> min(zoom_level, 6)
        x_window = max(16, min(x_window, 8192))

        if measure_mode:
            offset = encoder.steps * 10

        if not measure_mode:
            cursor_enabled = False
            cursor_line.setPos(-1e6)
            cursor_val_text.setText("")

        sync_fpga()
        samples = read_samples(N_total)
        sample_step = samples[0]
        signal_raw = np.array(samples[1:])
        signal = adc_to_voltage(signal_raw)
        fs = 128000000 / ((sample_step + 1) * 2)

        fft_vals = np.abs(np.fft.fft(signal))
        fft_freqs = np.fft.fftfreq(len(signal), d=1 / fs)
        dominant_idx = np.argmax(fft_vals[1:len(signal) // 2]) + 1
        dominant_freq1 = fft_freqs[dominant_idx]

        if not trigger_mode:
            curve.setData(np.arange(len(signal)), signal)
            plot.setXRange(0, len(signal))
        else:
            trigger_step = encoder.steps
            trigger_threshold = int(np.clip(2048 + trigger_step * 10, 0, 4095))
            trigger_idx = None
            for i in range(1, len(signal) - 1):
                if signal[i - 1] <= trigger_threshold / 409.5 - 5.0 < signal[i + 1]:
                    trigger_idx = i
                    break

            while trigger_idx is None:
                curve.setData([], [])
                plot.setXRange(0, x_window)
                QtWidgets.QApplication.processEvents()
                time.sleep(0.005)
                continue

            start = max(0, trigger_idx + offset)
            end = start + 1024
            if end > len(signal):
                end = len(signal)
                start = end - 1024
            segment = signal[start:end]
            relative_time = np.arange(start - trigger_idx, end - trigger_idx) / fs * 1e6
            curve.setData(relative_time, segment)
            plot.setXRange(relative_time[0], relative_time[-1])

            if cursor_enabled:
                cursor_pos = cursor_encoder.steps % len(relative_time)
                cursor_x = relative_time[cursor_pos]
                cursor_line.setPos(cursor_x)
                cursor_val = segment[cursor_pos]
                cursor_val_text.setText(f"{cursor_val:.2f} V")
                cursor_val_text.setPos(cursor_x, cursor_val)
            else:
                cursor_line.setPos(-1e6)
                cursor_val_text.setText("")

        if signal is not None and len(signal) > 0:
            vpp = np.max(signal) - np.min(signal)
            vmax = np.max(signal)
            vpp_text.setText(f"Vpp = {vpp:.2f} V")
            vmax_text.setText(f"Vmax = {vmax:.2f} V")
            vb = plot.vb
            view_rect = vb.viewRect()
            x_right = view_rect.right()
            y_top = view_rect.top()
            vpp_text.setPos(x_right - 200, y_top - 10)
            vmax_text.setPos(x_right - 200, y_top - 25)

            mode_str = "LIVE"
            if trigger_mode:
                mode_str = "TRIGGER"
            if measure_mode:
                mode_str = "MEASURE"
            title_label.setText(
                f"{dominant_freq1:.2f} Hz | Vpp: {vpp:.2f} V | Vmax: {vmax:.2f} V | Mode: {mode_str} | Scale: {scaling_mode.upper()}",
                size="10pt"
            )

        QtWidgets.QApplication.processEvents()
        time.sleep(0.005)

except KeyboardInterrupt:
    print("Stopped")
    spi.close()
