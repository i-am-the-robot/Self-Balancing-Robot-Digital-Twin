import sys
import math
import re
import threading
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QSlider, QLabel, QGroupBox, QGridLayout,
                             QDoubleSpinBox, QPushButton, QFrame, QComboBox,
                             QCheckBox, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, QRectF, pyqtSignal, QObject
from PyQt5.QtGui import (QPainter, QColor, QPen, QBrush, QFont, QPainterPath)


#  constants 
KP_DEFAULT    = 30.0
KI_DEFAULT    = 0.0
KD_DEFAULT    = 6.0
DESIRED_ANGLE = 0.0
MAX_ANGLE     = 45.0
MIN_PWM       = 30.0
MAX_PWM       = 255.0
DT            = 0.02          # 20 ms animation tick


#  serial worker (background thread) 
class SerialSignals(QObject):
    data_received = pyqtSignal(float, float, float)   # angle, error, U
    status        = pyqtSignal(str)

class SerialWorker:
    # Arduino prints:  "Angle: X\tError: Y\tU: Z"
    PATTERN = re.compile(
        r"Angle:\s*([-\d.]+)\s*\tError:\s*([-\d.]+)\s*\tU:\s*([-\d.]+)"
    )

    def __init__(self):
        self.signals  = SerialSignals()
        self._running = False
        self._port    = None
        self._thread  = None

    def connect(self, port, baud=9600):
        self.disconnect()
        try:
            self._port    = serial.Serial(port, baud, timeout=1)
            self._running = True
            self._thread  = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            self.signals.status.emit(f"Connected to {port} @ {baud} baud")
        except Exception as e:
            self.signals.status.emit(f"Error: {e}")

    def disconnect(self):
        self._running = False
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None

    def _read_loop(self):
        while self._running:
            try:
                line = self._port.readline().decode("utf-8", errors="ignore").strip()
                m = self.PATTERN.search(line)
                if m:
                    angle = float(m.group(1))
                    error = float(m.group(2))
                    U     = float(m.group(3))
                    self.signals.data_received.emit(angle, error, U)
            except Exception:
                pass


#  side wheel widget ─
class WheelWidget(QWidget):
    def __init__(self, label="Motor", parent=None):
        super().__init__(parent)
        self.label    = label
        self.spin_deg = 0.0
        self.pwm      = 0.0
        self.setMinimumSize(120, 120)

    def set_pwm(self, pwm):
        self.pwm = max(-MAX_PWM, min(MAX_PWM, pwm))

    def advance(self, dt):
        self.spin_deg += (self.pwm / MAX_PWM) * 360 * dt * 3
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 10

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        p.setBrush(QBrush(QColor(90, 82, 85)))
        p.setPen(QPen(QColor(55, 50, 52), 2))
        p.drawEllipse(QRectF(cx-r, cy-r, 2*r, 2*r))

        p.save()
        p.translate(cx, cy)
        p.rotate(self.spin_deg)
        p.setPen(QPen(QColor(30, 28, 29), 2))
        for i in range(8):
            a = math.radians(i * 45)
            p.drawLine(0, 0, int(r*math.cos(a)), int(r*math.sin(a)))
        p.setBrush(QBrush(QColor(60, 55, 58)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(-4, -4, 8, 8))
        p.restore()

        p.setPen(QPen(QColor(40, 40, 40)))
        p.setFont(QFont("Courier New", 9, QFont.Bold))
        p.drawText(QRectF(0, cy+r+4,  w, 18), Qt.AlignHCenter, self.label)
        p.drawText(QRectF(0, cy+r+20, w, 16), Qt.AlignHCenter, f"PWM: {int(self.pwm)}")


#  central balance view 
class BalanceWidget(QWidget):
    """
    The plank rotates about its own centre (cx, cy).
    The wheel is also centred at (cx, cy) — wheel axis == plank centre.
    Result: the assembly looks exactly like Image 1.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle_deg      = 0.0
        self.wheel_spin_deg = 0.0
        self.pwm            = 0.0
        self.setMinimumSize(480, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_state(self, angle_deg, pwm):
        self.angle_deg = angle_deg
        self.pwm       = pwm

    def advance_wheel(self, dt):
        self.wheel_spin_deg += (self.pwm / MAX_PWM) * 360 * dt * 3
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # vertical reference line
        p.setPen(QPen(QColor(210, 210, 210), 1, Qt.DashLine))
        p.drawLine(int(cx), 10, int(cx), h - 10)

        #  everything rotates around (cx, cy) ─
        p.save()
        p.translate(cx, cy)
        p.rotate(self.angle_deg)

        plank_half_w = min(w // 2 - 20, 220)
        plank_h      = 12
        wr           = 130         # wheel radius

        # plank — centred at origin  →  wheel axis is at origin
        p.setBrush(QBrush(QColor(160, 102, 30)))
        p.setPen(QPen(QColor(100, 60, 10), 2))
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(-plank_half_w, -plank_h / 2, plank_half_w * 2, plank_h), 5, 5
        )
        p.drawPath(path)

        # wheel — also centred at origin (on top of plank in Z order)
        p.setBrush(QBrush(QColor(90, 82, 85)))
        p.setPen(QPen(QColor(55, 50, 52), 2))
        p.drawEllipse(QRectF(-wr, -wr, 2*wr, 2*wr))

        # spokes inside wheel
        p.save()
        p.rotate(self.wheel_spin_deg)
        p.setPen(QPen(QColor(30, 28, 29), 2))
        for i in range(8):
            a = math.radians(i * 45)
            p.drawLine(0, 0, int(wr * math.cos(a)), int(wr * math.sin(a)))
        p.setBrush(QBrush(QColor(60, 55, 58)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(-4, -4, 8, 8))
        p.restore()

        p.restore()   # undo tilt

        #  angle arc indicator (fixed to screen) ─
        arc_r = 55
        p.setPen(QPen(QColor(160, 160, 160), 1))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx-arc_r, cy-arc_r, 2*arc_r, 2*arc_r),
                  int((-90)*16), int(-self.angle_deg*16))

        p.setPen(QPen(QColor(60, 60, 60)))
        p.setFont(QFont("Courier New", 11, QFont.Bold))
        p.drawText(QRectF(cx-70, cy+arc_r+6, 140, 24),
                   Qt.AlignHCenter, f"theta = {self.angle_deg:.1f} deg")


#  main window ─
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Self-Balancing Robot — Digital Twin")
        self.setStyleSheet("background-color: white; color: #222;")

        # simulation state
        self.kp = KP_DEFAULT; self.ki = KI_DEFAULT; self.kd = KD_DEFAULT
        self.error_sum = 0.0; self.prev_error = 0.0
        self.error = 0.0;     self.U = 0.0;  self.angle = 0.0

        # serial state
        self.serial_worker = SerialWorker()
        self.serial_worker.signals.data_received.connect(self._on_serial_data)
        self.serial_worker.signals.status.connect(self._on_serial_status)
        self.use_serial    = False
        self._s_angle = 0.0; self._s_error = 0.0; self._s_U = 0.0

        self._build_ui()
        self._refresh_ports()

        self.timer = QTimer()
        self.timer.timeout.connect(self._step)
        self.timer.start(int(DT * 1000))

    #  UI 
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # title
        title = QLabel("Self-Balancing Robot  ·  Digital Twin")
        title.setFont(QFont("Courier New", 15, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color:#333; border-bottom:2px solid #bbb; padding-bottom:6px;")
        root.addWidget(title)

        # visual row
        top = QHBoxLayout(); top.setSpacing(10)
        self.left_wheel   = WheelWidget("Left Motor")
        self.balance_view = BalanceWidget()
        self.right_wheel  = WheelWidget("Right Motor")
        top.addWidget(self._frame(self.left_wheel))
        top.addWidget(self._frame(self.balance_view), stretch=4)
        top.addWidget(self._frame(self.right_wheel))
        root.addLayout(top)

        #  serial panel 
        ser_box = QGroupBox("Serial Port  (Arduino @ 9600 baud)")
        ser_box.setFont(QFont("Courier New", 10))
        ser_lay = QHBoxLayout(ser_box)

        self.port_combo = QComboBox()
        self.port_combo.setFont(QFont("Courier New", 10))
        self.port_combo.setMinimumWidth(150)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600","19200","38400","57600","115200"])
        self.baud_combo.setCurrentText("9600")
        self.baud_combo.setFont(QFont("Courier New", 10))

        ref_btn = QPushButton("Refresh")
        ref_btn.setFont(QFont("Courier New", 9))
        ref_btn.clicked.connect(self._refresh_ports)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setFont(QFont("Courier New", 9))
        self.connect_btn.clicked.connect(self._toggle_serial)

        self.use_serial_chk = QCheckBox("Use live data")
        self.use_serial_chk.setFont(QFont("Courier New", 10))
        self.use_serial_chk.stateChanged.connect(self._on_use_serial_toggle)

        self.serial_status = QLabel("Not connected")
        self.serial_status.setFont(QFont("Courier New", 9))
        self.serial_status.setStyleSheet("color:#888;")

        ser_lay.addWidget(QLabel("Port:"))
        ser_lay.addWidget(self.port_combo)
        ser_lay.addWidget(QLabel("Baud:"))
        ser_lay.addWidget(self.baud_combo)
        ser_lay.addWidget(ref_btn)
        ser_lay.addWidget(self.connect_btn)
        ser_lay.addSpacing(12)
        ser_lay.addWidget(self.use_serial_chk)
        ser_lay.addWidget(self.serial_status, stretch=1)
        root.addWidget(ser_box)

        #  manual angle 
        self.manual_box = QGroupBox("Manual Angle Input  (simulates IMU tilt)")
        self.manual_box.setFont(QFont("Courier New", 10))
        man_lay = QVBoxLayout(self.manual_box)

        sl_row = QHBoxLayout()
        self.angle_slider = QSlider(Qt.Horizontal)
        self.angle_slider.setRange(-450, 450)
        self.angle_slider.setValue(0)
        self.angle_slider.setTickInterval(90)
        self.angle_slider.setTickPosition(QSlider.TicksBelow)
        self.angle_slider.valueChanged.connect(self._on_slider)

        self.angle_label = QLabel("0.0 deg")
        self.angle_label.setFont(QFont("Courier New", 13, QFont.Bold))
        self.angle_label.setFixedWidth(90)
        self.angle_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        sl_row.addWidget(QLabel("-45 deg"))
        sl_row.addWidget(self.angle_slider)
        sl_row.addWidget(QLabel("+45 deg"))
        sl_row.addWidget(self.angle_label)
        man_lay.addLayout(sl_row)

        rst = QPushButton("Reset to 0")
        rst.setFont(QFont("Courier New", 9))
        rst.clicked.connect(lambda: self.angle_slider.setValue(0))
        man_lay.addWidget(rst, alignment=Qt.AlignLeft)
        root.addWidget(self.manual_box)

        #  PID
        pid_box = QGroupBox("PID Parameters  (simulation only — does not write to Arduino)")
        pid_box.setFont(QFont("Courier New", 10))
        pid_grid = QGridLayout(pid_box)
        self.pid_spins = []
        for i, (lbl, val) in enumerate(zip(["Kp","Ki","Kd"],
                                            [KP_DEFAULT,KI_DEFAULT,KD_DEFAULT])):
            pid_grid.addWidget(QLabel(lbl), 0, i*2)
            sp = QDoubleSpinBox()
            sp.setRange(0, 300); sp.setSingleStep(0.5)
            sp.setDecimals(1);   sp.setValue(val)
            sp.setFont(QFont("Courier New", 10))
            sp.valueChanged.connect(self._on_pid_change)
            pid_grid.addWidget(sp, 0, i*2+1)
            self.pid_spins.append(sp)
        root.addWidget(pid_box)

        #  telemetry
        tele_box = QGroupBox("Telemetry")
        tele_box.setFont(QFont("Courier New", 10))
        tele_grid = QGridLayout(tele_box)
        self.tele_labels = {}
        for i, name in enumerate(["Angle", "Error", "U (PWM)", "ErrorSum"]):
            tele_grid.addWidget(QLabel(name+":"), 0, i*2)
            lbl = QLabel("0.00")
            lbl.setFont(QFont("Courier New", 10))
            lbl.setStyleSheet("color:#b84a00; font-weight:bold;")
            tele_grid.addWidget(lbl, 0, i*2+1)
            self.tele_labels[name] = lbl
        root.addWidget(tele_box)

        self.setMinimumSize(860, 680)

    def _frame(self, widget):
        f = QFrame()
        f.setFrameShape(QFrame.StyledPanel)
        f.setStyleSheet("background:#fafafa; border:1px solid #ddd; border-radius:6px;")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(widget)
        return f

    #  serial callbacks 
    def _refresh_ports(self):
        self.port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            self.port_combo.addItems(ports)
            if "COM16" in ports:
                self.port_combo.setCurrentText("COM16")
        else:
            self.port_combo.addItem("(no ports found)")

    def _toggle_serial(self):
        if self.serial_worker._running:
            self.serial_worker.disconnect()
            self.connect_btn.setText("Connect")
            self.serial_status.setText("Disconnected")
            self.serial_status.setStyleSheet("color:#888;")
        else:
            port = self.port_combo.currentText()
            baud = int(self.baud_combo.currentText())
            self.serial_worker.connect(port, baud)
            self.connect_btn.setText("Disconnect")

    def _on_serial_status(self, msg):
        self.serial_status.setText(msg)
        col = "#2a7a2a" if "Connected" in msg else "#cc0000"
        self.serial_status.setStyleSheet(f"color:{col};")

    def _on_serial_data(self, angle, error, U):
        self._s_angle = angle
        self._s_error = error
        self._s_U     = U

    def _on_use_serial_toggle(self, state):
        self.use_serial = bool(state)
        self.manual_box.setVisible(not self.use_serial)

    #  other callbacks
    def _on_slider(self, v):
        self.angle = v / 10.0
        self.angle_label.setText(f"{self.angle:.1f} deg")

    def _on_pid_change(self):
        self.kp = self.pid_spins[0].value()
        self.ki = self.pid_spins[1].value()
        self.kd = self.pid_spins[2].value()

    #  animation / simulation tick
    def _step(self):
        if self.use_serial and self.serial_worker._running:
            angle      = self._s_angle
            self.error = self._s_error
            self.U     = self._s_U
            pwm        = -self.U
            es_text    = "n/a (live)"
        else:
            angle = self.angle
            if abs(angle) > MAX_ANGLE:
                self.U = 0; self.error_sum = 0
                self.prev_error = 0; self.error = 0
            else:
                self.prev_error = self.error
                self.error      = DESIRED_ANGLE - angle
                self.error_sum  = max(-300, min(300, self.error_sum + self.error))
                self.U = (self.kp * self.error
                        + self.ki * self.error_sum
                        + self.kd * (self.error - self.prev_error))
                self.U = max(-MAX_PWM, min(MAX_PWM, self.U))
            pwm     = -self.U
            es_text = f"{self.error_sum:.1f}"

        self.left_wheel.set_pwm(pwm);   self.left_wheel.advance(DT)
        self.right_wheel.set_pwm(pwm);  self.right_wheel.advance(DT)
        self.balance_view.set_state(angle, pwm)
        self.balance_view.advance_wheel(DT)

        self.tele_labels["Angle"].setText(f"{angle:.2f}")
        self.tele_labels["Error"].setText(f"{self.error:.2f}")
        self.tele_labels["U (PWM)"].setText(f"{self.U:.1f}")
        self.tele_labels["ErrorSum"].setText(es_text)

    def closeEvent(self, event):
        self.serial_worker.disconnect()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
