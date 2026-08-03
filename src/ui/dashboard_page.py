import os
import shutil
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QFrame, QPushButton, QLineEdit, QProgressBar, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QApplication)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QColor

from ui.graph import SpeedGraphWidget
from core.utils import format_size, format_speed, FileCategorizer, sanitize_filename
from core.settings import settings_manager

class MetricCard(QFrame):
    """Modern dark glass KPI metric card with clean typography and hover glow."""
    def __init__(self, title, initial_value="0", subtitle="", icon_str="⚡", accent_color="#00E5FF", parent=None):
        super().__init__(parent)
        self.setProperty("class", "kpi-card")
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #182030;
                border: 1px solid #232F46;
                border-radius: 12px;
            }}
            QFrame:hover {{
                border-color: {accent_color};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        # Header Row (Icon + Title)
        header = QHBoxLayout()
        header.setSpacing(8)
        
        self.icon_label = QLabel(icon_str)
        self.icon_label.setStyleSheet("font-size: 18px; background: transparent;")
        
        self.title_label = QLabel(title.upper())
        self.title_label.setStyleSheet("color: #00E5FF; font-size: 11px; font-weight: 800; letter-spacing: 0.8px;")
        
        header.addWidget(self.icon_label)
        header.addWidget(self.title_label)
        header.addStretch()
        layout.addLayout(header)

        # Big Metric Value
        self.value_label = QLabel(initial_value)
        self.value_label.setStyleSheet("color: #FFFFFF; font-size: 24px; font-weight: 800;")
        layout.addWidget(self.value_label)

        # Subtitle / Details
        self.sub_label = QLabel(subtitle)
        self.sub_label.setStyleSheet("color: #B0BEC5; font-size: 11.5px; font-weight: 600;")
        layout.addWidget(self.sub_label)

    def set_value(self, val_str, sub_str=None):
        self.value_label.setText(val_str)
        if sub_str is not None:
            self.sub_label.setText(sub_str)


class DashboardPage(QWidget):
    quick_download_requested = pyqtSignal(str)

    def __init__(self, downloads_page=None, parent=None):
        super().__init__(parent)
        self.downloads_page = downloads_page
        self.peak_speed_bytes = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # 1. Header Banner & Quick Add URL Bar
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #121826, stop:1 #182030);
                border: 1px solid #232F46;
                border-radius: 12px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(20, 16, 20, 16)
        
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title_main = QLabel("System Dashboard & Telemetry")
        title_main.setStyleSheet("font-size: 20px; font-weight: 800; color: #FFFFFF;")
        title_sub = QLabel("Real-time network throughput, storage status, and active transfer queues")
        title_sub.setStyleSheet("font-size: 12px; color: #B0BEC5; font-weight: 500;")
        title_box.addWidget(title_main)
        title_box.addWidget(title_sub)
        
        header_layout.addLayout(title_box)
        header_layout.addStretch()

        # Quick Add Input Bar
        self.quick_input = QLineEdit()
        self.quick_input.setPlaceholderText("Paste URL here to quick start...")
        self.quick_input.setMinimumWidth(340)
        self.quick_input.returnPressed.connect(self.on_quick_download)
        
        self.quick_btn = QPushButton("⚡ Start Download")
        self.quick_btn.setProperty("class", "primary")
        self.quick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_btn.clicked.connect(self.on_quick_download)
        
        header_layout.addWidget(self.quick_input)
        header_layout.addWidget(self.quick_btn)
        
        layout.addWidget(header_frame)

        # 2. KPI Telemetry Cards Grid (4 Cards)
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)

        self.card_speed = MetricCard("Current Speed", "0.00 KB/s", "Peak: 0 KB/s", "⚡", "#00E5FF")
        self.card_active = MetricCard("Active Tasks", "0", "0 Queued", "📥", "#7C4DFF")
        self.card_completed = MetricCard("Completed Files", "0 Files", "0 MB Total Data", "✅", "#00E676")
        self.card_disk = MetricCard("Free Storage", "Checking...", "Total Capacity: --", "💾", "#FFAB00")

        cards_layout.addWidget(self.card_speed)
        cards_layout.addWidget(self.card_active)
        cards_layout.addWidget(self.card_completed)
        cards_layout.addWidget(self.card_disk)

        layout.addLayout(cards_layout)

        # 3. Main Split Grid Area: Bandwidth Monitor + Category Breakdown + Recent Feed
        main_grid = QHBoxLayout()
        main_grid.setSpacing(16)

        # Left Column (Bandwidth Monitor & Category Breakdown) - Stretch 3
        left_col = QVBoxLayout()
        left_col.setSpacing(16)

        # Bandwidth Graph Box
        graph_box = QFrame()
        graph_box.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F46;
                border-radius: 12px;
            }
        """)
        graph_layout = QVBoxLayout(graph_box)
        graph_layout.setContentsMargins(18, 16, 18, 16)
        
        graph_header = QHBoxLayout()
        graph_title = QLabel("Real-Time Bandwidth Traffic")
        graph_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #00E5FF;")
        
        self.graph_status = QLabel("● Live")
        self.graph_status.setStyleSheet("color: #00E676; font-size: 11px; font-weight: bold;")
        
        graph_header.addWidget(graph_title)
        graph_header.addStretch()
        graph_header.addWidget(self.graph_status)
        graph_layout.addLayout(graph_header)

        self.speed_graph = SpeedGraphWidget()
        graph_layout.addWidget(self.speed_graph)
        
        left_col.addWidget(graph_box, stretch=2)

        # Category Storage Breakdown Box
        cat_box = QFrame()
        cat_box.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F46;
                border-radius: 12px;
            }
        """)
        cat_layout = QVBoxLayout(cat_box)
        cat_layout.setContentsMargins(18, 14, 18, 14)
        
        cat_title = QLabel("File Categories Breakdown")
        cat_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #B0BEC5;")
        cat_layout.addWidget(cat_title)

        cat_grid = QHBoxLayout()
        cat_grid.setSpacing(8)
        
        self.cat_video = self.create_cat_pill("🎬 Video", "0 MB", "#FF5252")
        self.cat_audio = self.create_cat_pill("🎵 Audio", "0 MB", "#7C4DFF")
        self.cat_doc = self.create_cat_pill("📄 Doc", "0 MB", "#00E5FF")
        self.cat_app = self.create_cat_pill("💻 Soft", "0 MB", "#00E676")
        self.cat_zip = self.create_cat_pill("📦 Arch", "0 MB", "#FFAB00")

        cat_grid.addWidget(self.cat_video)
        cat_grid.addWidget(self.cat_audio)
        cat_grid.addWidget(self.cat_doc)
        cat_grid.addWidget(self.cat_app)
        cat_grid.addWidget(self.cat_zip)
        
        cat_layout.addLayout(cat_grid)
        left_col.addWidget(cat_box, stretch=1)

        main_grid.addLayout(left_col, stretch=3)

        # Right Column (Recent Active Transfers Feed) - Stretch 2
        feed_box = QFrame()
        feed_box.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F46;
                border-radius: 12px;
            }
        """)
        feed_layout = QVBoxLayout(feed_box)
        feed_layout.setContentsMargins(18, 16, 18, 16)
        feed_layout.setSpacing(10)
        
        feed_header = QHBoxLayout()
        feed_title = QLabel("Active Transfers & Queue")
        feed_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #FFFFFF;")
        
        view_all_btn = QPushButton("View All →")
        view_all_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #00E5FF;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #18FFFF;
            }
        """)
        view_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_all_btn.clicked.connect(self.on_view_all_clicked)
        
        feed_header.addWidget(feed_title)
        feed_header.addStretch()
        feed_header.addWidget(view_all_btn)
        feed_layout.addLayout(feed_header)

        # Recent Table Widget
        self.recent_table = QTableWidget()
        self.recent_table.setColumnCount(3)
        self.recent_table.setHorizontalHeaderLabels(["Filename", "Progress", "Status"])
        self.recent_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.recent_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.recent_table.setColumnWidth(1, 105)
        self.recent_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.recent_table.setColumnWidth(2, 90)
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.recent_table.setShowGrid(False)
        self.recent_table.setStyleSheet("""
            QTableWidget {
                background-color: transparent;
                border: none;
            }
            QTableWidget::item {
                padding: 6px 4px;
                border-bottom: 1px solid #182030;
                color: #FFFFFF;
            }
        """)
        
        feed_layout.addWidget(self.recent_table)
        main_grid.addWidget(feed_box, stretch=2)

        layout.addLayout(main_grid)

        # Telemetry update timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_metrics)
        self.timer.start(1000)

    def create_cat_pill(self, label, value, color_hex):
        pill = QFrame()
        pill.setStyleSheet(f"""
            QFrame {{
                background-color: #182030;
                border: 1px solid #232F46;
                border-radius: 8px;
                padding: 4px 6px;
            }}
        """)
        layout = QVBoxLayout(pill)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        
        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size: 10.5px; font-weight: 700; color: {color_hex};")
        
        val = QLabel(value)
        val.setStyleSheet("font-size: 11.5px; font-weight: bold; color: #FFFFFF;")
        
        layout.addWidget(lbl)
        layout.addWidget(val)
        pill.val_label = val
        return pill

    def on_quick_download(self):
        url = self.quick_input.text().strip()
        if url:
            self.quick_download_requested.emit(url)
            self.quick_input.clear()

    def on_view_all_clicked(self):
        main_window = self.window()
        if hasattr(main_window, 'sidebar'):
            main_window.sidebar.btn_group.button(1).click()

    def update_speed(self, speed_bytes):
        self.speed_graph.update_speed(speed_bytes)
        
        if speed_bytes > self.peak_speed_bytes:
            self.peak_speed_bytes = speed_bytes
            
        speed_str = format_speed(speed_bytes)
        peak_str = format_speed(self.peak_speed_bytes)
        self.card_speed.set_value(speed_str, f"Peak Rate: {peak_str}")

    def update_metrics(self):
        if not self.downloads_page:
            return
            
        # 1. Active count
        active_cnt = len(self.downloads_page.workers)
        queued_cnt = len(self.downloads_page.download_queue)
        self.card_active.set_value(str(active_cnt), f"{queued_cnt} Queued Tasks")

        # 2. Completed count & Total Downloaded Size
        completed_items = [info for info in self.downloads_page.downloads_info.values() if info['status'] == 'Completed']
        self.card_completed.set_value(f"{len(completed_items)} Files", f"Total: {len(self.downloads_page.downloads_info)} Tasks")

        # 3. Disk Free Space
        path = self.downloads_page.download_dir
        if os.path.exists(path):
            try:
                total, used, free = shutil.disk_usage(path)
                free_gb = free / (1024**3)
                total_gb = total / (1024**3)
                self.card_disk.set_value(f"{free_gb:.1f} GB Free", f"Total Capacity: {total_gb:.1f} GB")
            except Exception:
                pass

        # 4. Categories breakdown calculation
        cat_sizes = {'Video': 0, 'Audio': 0, 'Documents': 0, 'Executables': 0, 'Archives': 0}
        for info in self.downloads_page.downloads_info.values():
            fn = info.get('dest', '')
            cat = FileCategorizer.get_category(fn)
            if cat in cat_sizes:
                if os.path.exists(fn):
                    cat_sizes[cat] += os.path.getsize(fn)

        self.cat_video.val_label.setText(format_size(cat_sizes['Video']))
        self.cat_audio.val_label.setText(format_size(cat_sizes['Audio']))
        self.cat_doc.val_label.setText(format_size(cat_sizes['Documents']))
        self.cat_app.val_label.setText(format_size(cat_sizes['Executables']))
        self.cat_zip.val_label.setText(format_size(cat_sizes['Archives']))

        # 5. Sync Recent Table (Top 6 items)
        self.recent_table.setRowCount(0)
        items = list(self.downloads_page.downloads_info.values())[:6]
        for item_data in items:
            row = self.recent_table.rowCount()
            self.recent_table.insertRow(row)
            
            clean_name = sanitize_filename(os.path.basename(item_data.get('dest', 'File')))
            self.recent_table.setItem(row, 0, QTableWidgetItem(clean_name))
            
            pbar = QProgressBar()
            pbar.setFixedHeight(18)
            progress_pct = item_data.get('progress', 0)
            
            if item_data['status'] == "Completed":
                pbar.setValue(100)
                pbar.setFormat("100%")
            else:
                pbar.setValue(progress_pct)
                pbar.setFormat(f"{progress_pct}%")
                
            self.recent_table.setCellWidget(row, 1, pbar)
            
            status_item = QTableWidgetItem(item_data['status'])
            if item_data['status'] == "Completed":
                status_item.setForeground(QColor("#00E676"))
            elif item_data['status'] in ["Downloading", "Initializing"]:
                status_item.setForeground(QColor("#00E5FF"))
            elif item_data['status'] in ["Error", "Expired"]:
                status_item.setForeground(QColor("#FF5252"))
            else:
                status_item.setForeground(QColor("#FFAB00"))
                
            self.recent_table.setItem(row, 2, status_item)
