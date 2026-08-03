from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame, QButtonGroup
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient, QPolygonF, QFont
import math

try:
    import qtawesome as qta
    HAS_ICONS = True
except ImportError:
    HAS_ICONS = False


class NexarLogoWidget(QWidget):
    """Custom High-DPI Vector Logo for Nexar: Cyber Hexagon with Converging Speed Beams."""
    def __init__(self, size=36, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        r = min(w, h) * 0.45

        # 1. Outer Hexagon
        hex_poly = QPolygonF()
        for i in range(6):
            angle_rad = math.radians(60 * i - 30)
            x = cx + r * math.cos(angle_rad)
            y = cy + r * math.sin(angle_rad)
            hex_poly.append(QPointF(x, y))

        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor("#39FF14")) # Acid Green
        grad.setColorAt(1.0, QColor("#00E5FF")) # Cyber Cyan

        pen = QPen(QBrush(grad), 2.5)
        painter.setPen(pen)
        painter.setBrush(QColor(18, 24, 38, 180)) # Semi-transparent dark background
        painter.drawPolygon(hex_poly)

        # 2. Inner Converging Beams Arrow (3 parallel speed lines merging downward)
        beam_pen = QPen(QBrush(grad), 2.0)
        beam_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(beam_pen)

        # Left beam
        painter.drawLine(QPointF(cx - r*0.4, cy - r*0.3), QPointF(cx, cy + r*0.45))
        # Center beam
        painter.drawLine(QPointF(cx, cy - r*0.5), QPointF(cx, cy + r*0.45))
        # Right beam
        painter.drawLine(QPointF(cx + r*0.4, cy - r*0.3), QPointF(cx, cy + r*0.45))

        painter.end()


class Sidebar(QFrame):
    page_changed = pyqtSignal(int) # Emits index of page to show

    def __init__(self):
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(240)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 20, 16, 20)
        main_layout.setSpacing(10)

        # 1. Title / Logo Header
        self.brand_frame = QFrame()
        brand_layout = QHBoxLayout(self.brand_frame)
        brand_layout.setContentsMargins(0, 0, 0, 12)
        brand_layout.setSpacing(10)

        # Nexar Vector Icon
        self.logo_icon = NexarLogoWidget(size=40)
        brand_layout.addWidget(self.logo_icon)

        # Brand Text Stack
        brand_text_box = QVBoxLayout()
        brand_text_box.setSpacing(0)

        self.title = QLabel("NEXAR")
        self.title.setStyleSheet("font-size: 24px; font-weight: 900; color: #39FF14; letter-spacing: 3px;")
        brand_text_box.addWidget(self.title)
        
        self.subtitle = QLabel("SPEED ENGINE")
        self.subtitle.setStyleSheet("font-size: 9px; font-weight: 800; color: #00E5FF; letter-spacing: 1.8px;")
        brand_text_box.addWidget(self.subtitle)

        brand_layout.addLayout(brand_text_box)
        brand_layout.addStretch()

        main_layout.addWidget(self.brand_frame)

        # Separator Line
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #232F46;")
        main_layout.addWidget(sep)
        main_layout.addSpacing(10)

        # 2. Navigation Buttons Layout (Order: Dashboard -> All Downloads -> Downloading -> Completed)
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(6)
        main_layout.addLayout(self.nav_layout)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)
        self.btn_group.idClicked.connect(self.emit_page_change)

        self.btn_dashboard = self.create_nav_btn("Dashboard", "fa.dashboard" if HAS_ICONS else "📊", 0, checked=True)
        self.btn_all = self.create_nav_btn("All Downloads", "fa.list" if HAS_ICONS else "📂", 1)
        self.btn_downloading = self.create_nav_btn("Downloading", "fa.download" if HAS_ICONS else "⬇️", 2)
        self.btn_finished = self.create_nav_btn("Completed", "fa.check-circle" if HAS_ICONS else "✅", 3)
        
        main_layout.addStretch()

        # 3. Bottom Settings & Collapse Box
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background-color: #232F46;")
        main_layout.addWidget(sep2)
        main_layout.addSpacing(6)

        self.btn_settings = self.create_nav_btn("Settings", "fa.cog" if HAS_ICONS else "⚙️", 4, is_bottom=True)
        
        # System Footer Info
        self.footer_box = QFrame()
        self.footer_box.setStyleSheet("""
            QFrame {
                background-color: #182030;
                border: 1px solid #232F46;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        footer_layout = QHBoxLayout(self.footer_box)
        footer_layout.setContentsMargins(8, 6, 8, 6)
        
        self.ver_label = QLabel("Nexar v3.0 Pro")
        self.ver_label.setStyleSheet("font-size: 11px; color: #39FF14; font-weight: bold;")
        footer_layout.addWidget(self.ver_label)
        footer_layout.addStretch()

        self.collapse_btn = QPushButton("◀" if not HAS_ICONS else "")
        if HAS_ICONS:
            self.collapse_btn.setIcon(qta.icon("fa.angle-double-left", color="#90A4AE"))
        self.collapse_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #90A4AE;
                font-weight: bold;
                padding: 4px;
            }
            QPushButton:hover {
                color: #39FF14;
            }
        """)
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.clicked.connect(self.toggle_collapse)
        footer_layout.addWidget(self.collapse_btn)

        main_layout.addWidget(self.footer_box)

        self.is_collapsed = False

    def create_nav_btn(self, text, icon_name, index, checked=False, is_bottom=False):
        btn = QPushButton(f"  {text}")
        btn.setProperty("class", "sidebar-btn")
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.original_text = text
        
        if HAS_ICONS and "fa." in icon_name:
            btn.setIcon(qta.icon(icon_name, color="#90A4AE"))
            btn.setIconSize(QSize(18, 18))
        elif not HAS_ICONS:
            btn.setText(f"{icon_name}  {text}")

        if is_bottom:
            self.layout().insertWidget(self.layout().count() - 2, btn)
        else:
            self.nav_layout.addWidget(btn)

        self.btn_group.addButton(btn, index)
        return btn

    def emit_page_change(self, index):
        self.page_changed.emit(index)

    def update_badges(self, active_count, finished_count):
        if self.is_collapsed:
            return
            
        active_str = f"  {self.btn_downloading.original_text}  ({active_count})" if active_count > 0 else f"  {self.btn_downloading.original_text}"
        finished_str = f"  {self.btn_finished.original_text}  ({finished_count})" if finished_count > 0 else f"  {self.btn_finished.original_text}"
        
        if not HAS_ICONS:
            active_str = f"⬇️{active_str}"
            finished_str = f"✅{finished_str}"
            
        self.btn_downloading.setText(active_str)
        self.btn_finished.setText(finished_str)

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.setFixedWidth(72)
            self.brand_frame.hide()
            self.ver_label.hide()
            for btn in [self.btn_dashboard, self.btn_all, self.btn_downloading, self.btn_finished, self.btn_settings]:
                btn.setText("")
            if HAS_ICONS:
                self.collapse_btn.setIcon(qta.icon("fa.angle-double-right", color="#90A4AE"))
            else:
                self.collapse_btn.setText("▶")
        else:
            self.setFixedWidth(240)
            self.brand_frame.show()
            self.ver_label.show()
            for btn in [self.btn_dashboard, self.btn_all, self.btn_downloading, self.btn_finished, self.btn_settings]:
                if HAS_ICONS:
                    btn.setText(f"  {btn.original_text}")
                else:
                    emoji = "📊" if btn == self.btn_dashboard else "📂" if btn == self.btn_all else "⬇️" if btn == self.btn_downloading else "✅" if btn == self.btn_finished else "⚙️"
                    btn.setText(f"{emoji}  {btn.original_text}")
            if HAS_ICONS:
                self.collapse_btn.setIcon(qta.icon("fa.angle-double-left", color="#90A4AE"))
            else:
                self.collapse_btn.setText("◀")
