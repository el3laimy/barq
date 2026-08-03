# Nexar Dark Cyber-Glass High-Contrast Premium Theme

COLORS = {
    "background": "#090D16",
    "background_gradient_start": "#0B101D",
    "background_gradient_end": "#070A10",
    "surface": "#121826",
    "surface_card": "#182030",
    "surface_card_hover": "#202A3F",
    "surface_glass": "rgba(24, 32, 48, 0.95)",
    "border": "#232F46",
    "border_bright": "#354769",
    "primary": "#00E5FF",       # Neon Cyan
    "primary_hover": "#18FFFF",
    "primary_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00E5FF, stop:1 #0099FF)",
    "accent": "#7C4DFF",        # Neon Purple
    "accent_hover": "#B388FF",
    "success": "#00E676",       # Emerald Green
    "success_bg": "rgba(0, 230, 118, 0.15)",
    "warning": "#FFAB00",       # Amber
    "warning_bg": "rgba(255, 171, 0, 0.15)",
    "danger": "#FF5252",        # Rose Red
    "danger_bg": "rgba(255, 82, 82, 0.15)",
    "text_primary": "#FFFFFF",
    "text_secondary": "#B0BEC5",  # High-contrast bright slate
    "text_muted": "#90A4AE",      # Readable muted grey
    "glow_cyan": "rgba(0, 229, 255, 0.25)"
}

STYLESHEET = f"""
QMainWindow {{
    background-color: {COLORS["background"]};
}}

QWidget {{
    color: {COLORS["text_primary"]};
    font-family: 'Inter', 'SF Pro Display', 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
}}

QWidget:focus {{
    outline: none;
}}

/* Dialog & Message Box Global Styling (Fixes low contrast dialogs) */
QDialog, QMessageBox {{
    background-color: #0E1422;
    border: 1px solid #354769;
    border-radius: 12px;
}}

QMessageBox QLabel {{
    color: #F1F5F9;
    font-size: 13px;
    font-weight: 500;
    padding: 6px;
}}

QMessageBox QPushButton {{
    background-color: #1E293B;
    border: 1px solid #3B82F6;
    border-radius: 8px;
    padding: 8px 20px;
    color: #FFFFFF;
    font-weight: 700;
    min-width: 70px;
}}

QMessageBox QPushButton:hover {{
    background-color: #00E5FF;
    border-color: #00E5FF;
    color: #050810;
}}

/* Custom Scrollbars */
QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS["border_bright"]};
    min-height: 30px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLORS["primary"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border: none;
    background: none;
}}

QScrollBar:horizontal {{
    border: none;
    background: transparent;
    height: 6px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: {COLORS["border_bright"]};
    min-width: 30px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {COLORS["primary"]};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    border: none;
    background: none;
}}

/* Standard Buttons */
QPushButton {{
    background-color: {COLORS["surface_card"]};
    border: 1px solid {COLORS["border_bright"]};
    border-radius: 8px;
    padding: 8px 16px;
    color: {COLORS["text_primary"]};
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {COLORS["surface_card_hover"]};
    border-color: {COLORS["primary"]};
    color: #FFFFFF;
}}
QPushButton:pressed {{
    background-color: {COLORS["surface"]};
}}
QPushButton:disabled {{
    background-color: {COLORS["surface"]};
    border-color: {COLORS["border"]};
    color: {COLORS["text_muted"]};
}}

/* Primary Accent Button */
QPushButton.primary {{
    background: {COLORS["primary_gradient"]};
    color: #050810;
    border: none;
    font-weight: 800;
    padding: 9px 20px;
    border-radius: 8px;
}}
QPushButton.primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #18FFFF, stop:1 #33A6FF);
    color: #000000;
}}
QPushButton.primary:pressed {{
    background-color: {COLORS["primary"]};
}}

/* Secondary Action Button */
QPushButton.secondary {{
    background-color: {COLORS["surface_card"]};
    border: 1px solid {COLORS["border_bright"]};
    color: {COLORS["text_primary"]};
}}
QPushButton.secondary:hover {{
    background-color: {COLORS["surface_card_hover"]};
    border-color: {COLORS["primary"]};
    color: {COLORS["primary"]};
}}

/* Danger Button */
QPushButton.danger {{
    background-color: {COLORS["danger_bg"]};
    border: 1px solid {COLORS["danger"]};
    color: {COLORS["danger"]};
    font-weight: 600;
}}
QPushButton.danger:hover {{
    background-color: {COLORS["danger"]};
    color: #FFFFFF;
}}

/* Inputs & Searches */
QLineEdit {{
    background-color: {COLORS["surface_card"]};
    border: 1px solid {COLORS["border_bright"]};
    border-radius: 8px;
    padding: 10px 14px;
    color: #FFFFFF;
    selection-background-color: {COLORS["primary"]};
    selection-color: #000000;
}}
QLineEdit:hover {{
    border-color: {COLORS["primary"]};
}}
QLineEdit:focus {{
    border: 1px solid {COLORS["primary"]};
    background-color: #101726;
}}

/* SpinBox & ComboBox */
QSpinBox, QComboBox {{
    background-color: {COLORS["surface_card"]};
    border: 1px solid {COLORS["border_bright"]};
    border-radius: 8px;
    padding: 8px 12px;
    color: #FFFFFF;
}}
QSpinBox:hover, QComboBox:hover {{
    border-color: {COLORS["primary"]};
}}
QSpinBox:focus, QComboBox:focus {{
    border-color: {COLORS["primary"]};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: #121826;
    border: 1px solid #354769;
    selection-background-color: #1C2B42;
    selection-color: #00E5FF;
    color: #FFFFFF;
}}

/* Sidebar Frame */
QFrame#Sidebar {{
    background-color: {COLORS["surface"]};
    border-right: 1px solid {COLORS["border"]};
}}

QPushButton.sidebar-btn {{
    text-align: left;
    padding: 12px 16px;
    border: none;
    border-radius: 8px;
    background-color: transparent;
    color: {COLORS["text_secondary"]};
    font-size: 13.5px;
    font-weight: 600;
}}
QPushButton.sidebar-btn:hover {{
    background-color: {COLORS["surface_card"]};
    color: #FFFFFF;
}}
QPushButton.sidebar-btn:checked {{
    background-color: rgba(0, 229, 255, 0.12);
    color: {COLORS["primary"]};
    font-weight: 800;
    border-left: 3px solid {COLORS["primary"]};
}}

/* Card Frame Containers */
QFrame.card {{
    background-color: {COLORS["surface_card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
}}
QFrame.card:hover {{
    border-color: {COLORS["border_bright"]};
}}

/* Telemetry KPI Cards */
QFrame.kpi-card {{
    background-color: {COLORS["surface_card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
}}
QFrame.kpi-card:hover {{
    border-color: {COLORS["primary"]};
}}

/* Table Component */
QTableWidget {{
    background-color: {COLORS["surface"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: #1C2B42;
    selection-color: {COLORS["primary"]};
    alternate-background-color: #161E2E;
    outline: none;
}}
QTableWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {COLORS["border"]};
    color: #FFFFFF;
}}
QTableWidget::item:hover {{
    background-color: #182436;
}}
QTableWidget::item:selected {{
    background-color: #1C2B42;
    color: {COLORS["primary"]};
}}
QHeaderView::section {{
    background-color: {COLORS["surface_card"]};
    padding: 10px 14px;
    border: none;
    border-bottom: 1px solid {COLORS["border_bright"]};
    font-weight: 800;
    font-size: 11px;
    color: {COLORS["text_secondary"]};
    text-transform: uppercase;
    letter-spacing: 0.8px;
}}

/* Progress Bar */
QProgressBar {{
    border: none;
    background-color: #1E293B;
    border-radius: 6px;
    text-align: center;
    color: #FFFFFF;
    font-weight: 800;
    font-size: 11px;
}}
QProgressBar::chunk {{
    background: {COLORS["primary_gradient"]};
    border-radius: 6px;
}}

/* Filter Chips */
QPushButton.chip-btn {{
    background-color: {COLORS["surface_card"]};
    border: 1px solid {COLORS["border_bright"]};
    border-radius: 16px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 600;
    color: {COLORS["text_secondary"]};
}}
QPushButton.chip-btn:hover {{
    background-color: {COLORS["surface_card_hover"]};
    color: #FFFFFF;
    border-color: {COLORS["primary"]};
}}
QPushButton.chip-btn:checked {{
    background-color: {COLORS["primary"]};
    color: #050810;
    font-weight: 800;
    border: none;
}}

/* Status Pills */
QLabel.status-pill {{
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 800;
}}

/* Context Menu */
QMenu {{
    background-color: #121826;
    border: 1px solid {COLORS["border_bright"]};
    color: #FFFFFF;
    padding: 6px;
    border-radius: 8px;
}}
QMenu::item {{
    padding: 8px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: #1C2B42;
    color: {COLORS["primary"]};
}}
QMenu::separator {{
    height: 1px;
    background: {COLORS["border"]};
    margin: 4px 6px;
}}

/* Toolbars and Status Bar */
QToolBar {{
    background-color: {COLORS["surface"]};
    border-bottom: 1px solid {COLORS["border"]};
    padding: 8px 16px;
    spacing: 10px;
}}
QToolButton {{
    background-color: {COLORS["surface_card"]};
    border: 1px solid {COLORS["border_bright"]};
    border-radius: 8px;
    padding: 6px 14px;
    color: #FFFFFF;
    font-weight: 700;
    font-size: 12px;
}}
QToolButton:hover {{
    background-color: {COLORS["surface_card_hover"]};
    border-color: {COLORS["primary"]};
    color: {COLORS["primary"]};
}}

QStatusBar {{
    background-color: {COLORS["surface"]};
    border-top: 1px solid {COLORS["border"]};
    color: {COLORS["text_secondary"]};
    padding: 4px 12px;
}}

/* ToolTips */
QToolTip {{
    background-color: #1E293B;
    color: #FFFFFF;
    border: 1px solid #354769;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
"""
