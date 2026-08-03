from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPen, QBrush, QPolygonF
from PyQt6.QtCore import QPointF
import collections
import time

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

class SpeedGraphWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("SpeedGraph")
        self.setFixedHeight(180)
        self.setStyleSheet("background-color: #1e1e1e; border-radius: 10px; border: 1px solid #333;")
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        
        # Data storage (Last 60 points)
        self.history_size = 60
        self.data = collections.deque([0.0] * self.history_size, maxlen=self.history_size)
        self.max_speed = 1.0 # Auto-scale
        
        if HAS_PYQTGRAPH:
            self.init_pyqtgraph()
        else:
            self.init_fallback_graph()

    def init_pyqtgraph(self):
        # Configure Look
        pg.setConfigOption('background', '#1e1e1e')
        pg.setConfigOption('foreground', '#9e9e9e')
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.showGrid(x=False, y=True, alpha=0.3)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.hideButtons()
        self.plot_widget.setFrameStyle(0) # No border
        
        # Pen (Green line)
        pen = pg.mkPen(color='#00E676', width=2)
        self.curve = self.plot_widget.plot(self.data, pen=pen)
        
        # Fill (Gradient-ish via FillBetween - simple solid for now or partial alpha)
        # pyqtgraph fill is tricky with just one curve, typically use fillLevel
        self.curve.setFillLevel(0)
        self.curve.setBrush(pg.mkBrush(color=(0, 230, 118, 50))) # Semi-transparent green
        
        self.layout.addWidget(self.plot_widget)
        
        self.speed_label = QLabel("0.00 KB/s", self)
        self.speed_label.setStyleSheet("color: #00E676; font-size: 16px; font-weight: bold; background: transparent;")
        self.speed_label.move(20, 20)
        self.speed_label.raise_()
        
    def init_fallback_graph(self):
        self.label = QLabel("Real-time Speed")
        self.label.setStyleSheet("color: #9e9e9e; font-size: 12px; font-weight: bold;")
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        
        # We will use paintEvent to draw
        self.layout.addWidget(self.label)
        self.layout.addStretch()

    def update_speed(self, speed_bps):
        """Update graph with new speed in Bytes/s"""
        speed_mb = speed_bps / (1024 * 1024)
        self.data.append(speed_mb)
        
        if speed_mb > self.max_speed:
            self.max_speed = speed_mb * 1.2 # Breathing room
        elif self.max_speed > 1.0 and max(self.data) < self.max_speed * 0.5:
            self.max_speed = max(self.data) * 1.2 # Scale down slowly
            
        if self.max_speed < 1.0: self.max_speed = 1.0 # Minimum scale
        
        speed_str = f"{speed_mb:.2f} MB/s" if speed_mb >= 1.0 else f"{speed_bps/1024:.2f} KB/s"
        
        if HAS_PYQTGRAPH:
            self.curve.setData(list(self.data))
            self.plot_widget.setYRange(0, self.max_speed)
            self.speed_label.setText(speed_str)
        else:
            self.update() # Trigger repaint
            self.label.setText(speed_str)

    def paintEvent(self, event):
        if HAS_PYQTGRAPH:
            return super().paintEvent(event)
            
        # Fallback painting
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Clip area
        margin = 10
        draw_rect = self.rect().adjusted(margin, margin, -margin, -margin)
        
        # Draw Background (already done by QSS, but lets ensure checks)
        # painter.fillRect(self.rect(), QColor("#2b2b2b"))
        
        # Calculate points
        points = []
        x_step = draw_rect.width() / (self.history_size - 1)
        
        for i, val in enumerate(self.data):
            x = draw_rect.left() + (i * x_step)
            # Y inverted (0 at bottom)
            # Normalize val (0 to max_speed) -> (height to 0)
            norm_h = (val / self.max_speed) * draw_rect.height()
            y = draw_rect.bottom() - norm_h
            points.append(QPointF(x, y))
            
        # Construct Path
        if not points: return
        
        # 1. Draw Fill
        fill_poly = QPolygonF(points)
        fill_poly.append(QPointF(draw_rect.right(), draw_rect.bottom()))
        fill_poly.append(QPointF(draw_rect.left(), draw_rect.bottom()))
        
        grad = QLinearGradient(0, draw_rect.top(), 0, draw_rect.bottom())
        grad.setColorAt(0, QColor(0, 230, 118, 100)) # Green alpha
        grad.setColorAt(1, QColor(0, 230, 118, 10))  # Fade out
        
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(fill_poly)
        
        # 2. Draw Line
        pen = QPen(QColor("#00E676"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPolyline(points)
