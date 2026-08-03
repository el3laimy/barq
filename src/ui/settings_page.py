from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QFileDialog, QSpinBox, 
                             QCheckBox, QMessageBox, QFrame, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal
from core.settings import settings_manager
from core.traffic_control import global_limiter

class SettingsCard(QFrame):
    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F46;
                border-radius: 12px;
                padding: 16px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(2)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #FFFFFF;")
        header.addWidget(lbl_title)
        
        if subtitle:
            lbl_sub = QLabel(subtitle)
            lbl_sub.setStyleSheet("font-size: 11.5px; color: #90A4AE;")
            header.addWidget(lbl_sub)

        layout.addLayout(header)
        
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #232F46;")
        layout.addWidget(sep)
        
        self.card_body = QVBoxLayout()
        self.card_body.setSpacing(10)
        layout.addLayout(self.card_body)


class SettingsPage(QWidget):
    settings_saved = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_settings()
        self.connect_changes()
        self.save_btn.hide()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header Title & Save Bar
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Engine Preferences & Controls")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #FFFFFF;")
        subtitle = QLabel("Configure network concurrency, storage directories, and app behaviors")
        subtitle.setStyleSheet("font-size: 12px; color: #90A4AE;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.save_btn = QPushButton("💾 Apply & Save Settings")
        self.save_btn.setProperty("class", "primary")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self.save_settings)

        top_bar.addLayout(title_box)
        top_bar.addStretch()
        top_bar.addWidget(self.save_btn)
        main_layout.addLayout(top_bar)

        # Scrollable Area for Settings Cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        cards_layout = QVBoxLayout(scroll_content)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(16)

        # Card 1: Storage & General Behavior
        card_gen = SettingsCard("General & File Storage", "Default saving paths, clipboard detection, and tray options")
        
        path_box = QVBoxLayout()
        path_box.setSpacing(6)
        path_lbl = QLabel("Default Download Directory")
        path_lbl.setStyleSheet("font-weight: 600; color: #90A4AE;")
        
        path_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_btn = QPushButton("📂 Browse...")
        self.path_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.path_btn.clicked.connect(self.browse_folder)
        path_row.addWidget(self.path_input, stretch=3)
        path_row.addWidget(self.path_btn)
        path_box.addLayout(path_row)

        card_gen.card_body.addLayout(path_box)

        self.clipboard_check = QCheckBox("Monitor System Clipboard for downloadable links")
        self.tray_check = QCheckBox("Minimize to System Tray on close instead of exiting")
        
        card_gen.card_body.addWidget(self.clipboard_check)
        card_gen.card_body.addWidget(self.tray_check)
        cards_layout.addWidget(card_gen)

        # Card 2: Network & Concurrency
        card_net = SettingsCard("Network & Engine Concurrency", "Control parallel download slots, connection segments, and speed caps")
        
        grid_net = QHBoxLayout()
        grid_net.setSpacing(20)

        # Max Concurrent
        box_conc = QVBoxLayout()
        lbl_conc = QLabel("Max Concurrent Downloads")
        lbl_conc.setStyleSheet("font-weight: 600; color: #90A4AE;")
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 20)
        box_conc.addWidget(lbl_conc)
        box_conc.addWidget(self.concurrent_spin)

        # Segments
        box_seg = QVBoxLayout()
        lbl_seg = QLabel("Segments Per Download (Threads)")
        lbl_seg.setStyleSheet("font-weight: 600; color: #90A4AE;")
        self.segments_spin = QSpinBox()
        self.segments_spin.setRange(1, 32)
        box_seg.addWidget(lbl_seg)
        box_seg.addWidget(self.segments_spin)

        # Global Speed Limit
        box_spd = QVBoxLayout()
        lbl_spd = QLabel("Global Speed Limit")
        lbl_spd.setStyleSheet("font-weight: 600; color: #90A4AE;")
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(0, 1048576)
        self.speed_spin.setSuffix(" KB/s")
        self.speed_spin.setSpecialValueText("Unlimited (∞)")
        box_spd.addWidget(lbl_spd)
        box_spd.addWidget(self.speed_spin)

        grid_net.addLayout(box_conc)
        grid_net.addLayout(box_seg)
        grid_net.addLayout(box_spd)
        card_net.card_body.addLayout(grid_net)

        cards_layout.addWidget(card_net)

        # Card 3: Advanced Retry & Timeouts
        card_adv = SettingsCard("Resilience & Timeout Policies", "Configure retry limits and socket connection timeouts")
        
        grid_adv = QHBoxLayout()
        grid_adv.setSpacing(20)

        box_ret = QVBoxLayout()
        lbl_ret = QLabel("Max Re-try Attempts")
        lbl_ret.setStyleSheet("font-weight: 600; color: #90A4AE;")
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 100)
        box_ret.addWidget(lbl_ret)
        box_ret.addWidget(self.retries_spin)

        box_tout = QVBoxLayout()
        lbl_tout = QLabel("Connection Socket Timeout")
        lbl_tout.setStyleSheet("font-weight: 600; color: #90A4AE;")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setSuffix(" seconds")
        box_tout.addWidget(lbl_tout)
        box_tout.addWidget(self.timeout_spin)

        grid_adv.addLayout(box_ret)
        grid_adv.addLayout(box_tout)
        card_adv.card_body.addLayout(grid_adv)

        cards_layout.addWidget(card_adv)

        # Card 4: System Information
        from core.constants import APP_NAME, APP_VERSION, IPC_PORT
        card_about = SettingsCard("About Barq Engine", "Build version & system info")
        info_lbl = QLabel(
            f"<b>{APP_NAME} v{APP_VERSION}</b><br>"
            "High-throughput resilient multi-segment HTTP/HTTPS download manager.<br>"
            f"IPC Bridge active on port {IPC_PORT} • PyQt6 Dark Glass UI System"
        )
        info_lbl.setStyleSheet("color: #90A4AE; line-height: 1.4;")
        card_about.card_body.addWidget(info_lbl)
        cards_layout.addWidget(card_about)

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.path_input.text())
        if folder:
            self.path_input.setText(folder)
            self.on_changed()

    def connect_changes(self):
        self.path_input.textChanged.connect(self.on_changed)
        self.clipboard_check.stateChanged.connect(self.on_changed)
        self.tray_check.stateChanged.connect(self.on_changed)
        self.concurrent_spin.valueChanged.connect(self.on_changed)
        self.segments_spin.valueChanged.connect(self.on_changed)
        self.speed_spin.valueChanged.connect(self.on_changed)
        self.retries_spin.valueChanged.connect(self.on_changed)
        self.timeout_spin.valueChanged.connect(self.on_changed)

    def on_changed(self):
        self.save_btn.show()

    def load_settings(self):
        self.path_input.setText(settings_manager.get("download_path", ""))
        self.clipboard_check.setChecked(settings_manager.get("monitor_clipboard", True))
        self.tray_check.setChecked(settings_manager.get("minimize_to_tray", True))
        self.concurrent_spin.setValue(settings_manager.get("max_concurrent_downloads", 3))
        self.segments_spin.setValue(settings_manager.get("segments_per_download", 16))
        
        limit_bytes = settings_manager.get("speed_limit")
        if limit_bytes is None:
            limit_bytes = 0
        self.speed_spin.setValue(int(limit_bytes / 1024))
        
        self.retries_spin.setValue(settings_manager.get("max_retries", 5))
        self.timeout_spin.setValue(settings_manager.get("connection_timeout", 30))

    def save_settings(self):
        settings_manager.set("download_path", self.path_input.text())
        settings_manager.set("monitor_clipboard", self.clipboard_check.isChecked())
        settings_manager.set("minimize_to_tray", self.tray_check.isChecked())
        settings_manager.set("max_concurrent_downloads", self.concurrent_spin.value())
        settings_manager.set("segments_per_download", self.segments_spin.value())
        
        limit_bytes = self.speed_spin.value() * 1024
        settings_manager.set("speed_limit", limit_bytes)
        
        settings_manager.set("max_retries", self.retries_spin.value())
        settings_manager.set("connection_timeout", self.timeout_spin.value())
        
        global_limiter.set_limit(limit_bytes)
        
        self.save_btn.hide()
        self.settings_saved.emit()
