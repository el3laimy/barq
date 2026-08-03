import sys
import os
import shutil
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                             QStackedWidget, QLabel, QVBoxLayout, QFrame,
                             QSystemTrayIcon, QMenu, QToolBar, QStatusBar, QPushButton)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PyQt6.QtCore import Qt, QSettings, QTimer

current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, '..')
if src_path not in sys.path:
    sys.path.append(src_path)

from ui.styles import STYLESHEET
from ui.sidebar import Sidebar
from core.ipc_server import IPCServer
from core.constants import APP_NAME, APP_SHORT_NAME, APP_PROSE_NAME, ORGANIZATION_NAME, IPC_PORT


class BarqMainWindow(QMainWindow):
    def __init__(self, initial_url=None):
        super().__init__()
        self.initial_url = initial_url
        self.setWindowTitle(f"{APP_PROSE_NAME} Speed Engine • High-Performance Downloader")
        self.resize(1180, 740)
        self.setMinimumSize(900, 600)
        
        logo_icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logo.png"))
        if os.path.exists(logo_icon_path):
            self.setWindowIcon(QIcon(logo_icon_path))
        
        # Restore Geometry & Migrate legacy settings safely if present
        self.settings = QSettings(ORGANIZATION_NAME, "BarqDownloadManager")
        geometry = self.settings.value("geometry")
        if not geometry:
            # Check legacy setting paths for seamless migration
            legacy_settings = QSettings("Nexar", "DownloadEngine")
            geometry = legacy_settings.value("geometry")
            if not geometry:
                legacy_settings = QSettings("Titan", "DownloadEngine")
                geometry = legacy_settings.value("geometry")
            if geometry:
                self.settings.setValue("geometry", geometry)

        if geometry:
            self.restoreGeometry(geometry)
            
        self.has_shown_tray_msg = False
        
        # System Tray
        self.setup_tray()
        
        # Apply Stylesheet
        self.setStyleSheet(STYLESHEET)
        
        # Setup Header Toolbar & Status Bar
        self.setup_header_toolbar()
        self.setup_statusbar()

        # Central Main Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Sidebar Component (Barq branded)
        self.sidebar = Sidebar()
        self.sidebar.page_changed.connect(self.switch_page)
        main_layout.addWidget(self.sidebar)

        # 2. Content Stack Area
        self.content_area = QStackedWidget()
        main_layout.addWidget(self.content_area)

        # Initialize All Page Views
        self.init_pages()

        # Start IPC Server
        self.ipc_server = IPCServer(port=IPC_PORT, parent=self)
        self.ipc_server.url_received.connect(self.handle_ipc_url)
        self.ipc_server.start()

    def handle_ipc_url(self, url: str):
        self.show_window()
        if hasattr(self, 'page_all_downloads'):
            self.page_all_downloads.add_download(url)

    def setup_header_toolbar(self):
        toolbar = QToolBar("Main Controls Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        add_act = QAction("➕ New URL (Ctrl+N)", self)
        add_act.setShortcut(QKeySequence("Ctrl+N"))
        add_act.triggered.connect(self.on_add_url_action)
        toolbar.addAction(add_act)
        
        toolbar.addSeparator()

        pause_act = QAction("⏸️ Pause All (Ctrl+P)", self)
        pause_act.setShortcut(QKeySequence("Ctrl+P"))
        pause_act.triggered.connect(self.on_pause_all)
        toolbar.addAction(pause_act)
        
        resume_act = QAction("▶️ Resume All (Ctrl+R)", self)
        resume_act.setShortcut(QKeySequence("Ctrl+R"))
        resume_act.triggered.connect(self.on_resume_all)
        toolbar.addAction(resume_act)
        
        stop_act = QAction("⏹️ Stop All", self)
        stop_act.triggered.connect(self.on_stop_all)
        toolbar.addAction(stop_act)
        
        del_shortcut = QShortcut(QKeySequence("Delete"), self)
        del_shortcut.activated.connect(self.on_delete_selected)
        
    def setup_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        
        self.status_active = QLabel("Tasks: 0 Active")
        self.status_active.setStyleSheet("color: #39FF14; font-weight: 600; padding: 0 8px;")
        
        self.status_speed = QLabel("Speed: 0.00 KB/s")
        self.status_speed.setStyleSheet("color: #00E5FF; font-weight: 600; padding: 0 8px;")
        
        self.status_disk = QLabel("Disk: Checking...")
        self.status_disk.setStyleSheet("color: #90A4AE; padding: 0 8px;")
        
        self.statusbar.addPermanentWidget(self.status_active)
        self.statusbar.addPermanentWidget(self.status_speed)
        self.statusbar.addPermanentWidget(self.status_disk)
        
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_statusbar)
        self.status_timer.start(1000)

    def update_statusbar(self):
        if hasattr(self, 'page_all_downloads'):
            active = len(self.page_all_downloads.workers)
            queued = len(self.page_all_downloads.download_queue)
            self.status_active.setText(f"Tasks: {active} Active • {queued} Queued")
            
            path = self.page_all_downloads.download_dir
            if os.path.exists(path):
                total, used, free = shutil.disk_usage(path)
                free_gb = free / (1024**3)
                self.status_disk.setText(f"Disk: {free_gb:.1f} GB Free")
                
            completed_cnt = sum(1 for i in self.page_all_downloads.downloads_info.values() if i['status'] == 'Completed')
            self.sidebar.update_badges(active, completed_cnt)

    def on_add_url_action(self):
        if hasattr(self, 'page_all_downloads'):
            self.sidebar.btn_group.button(1).click()
            self.page_all_downloads.url_input.setFocus()

    def on_pause_all(self):
        if hasattr(self, 'page_all_downloads'):
            self.page_all_downloads.pause_all()
            
    def on_resume_all(self):
        if hasattr(self, 'page_all_downloads'):
            self.page_all_downloads.resume_all()

    def on_stop_all(self):
        if hasattr(self, 'page_all_downloads'):
            self.page_all_downloads.stop_all()

    def on_delete_selected(self):
        if hasattr(self, 'page_all_downloads') and self.content_area.currentWidget() == self.page_all_downloads:
            selected = self.page_all_downloads.table.selectedItems()
            if selected:
                rows = set(item.row() for item in selected)
                for row in sorted(rows, reverse=True):
                    item = self.page_all_downloads.table.item(row, 0)
                    if item:
                        db_id = item.data(Qt.ItemDataRole.UserRole)
                        self.page_all_downloads.delete_download(db_id)

    def init_pages(self):
        from ui.downloads_page import DownloadsPage
        from ui.dashboard_page import DashboardPage
        from ui.settings_page import SettingsPage

        # Page 1: Downloads Page Hub
        self.page_all_downloads = DownloadsPage()

        # Page 0: Dashboard Telemetry
        self.page_dashboard = DashboardPage(downloads_page=self.page_all_downloads)
        self.page_dashboard.quick_download_requested.connect(self.page_all_downloads.add_download)
        self.page_all_downloads.global_speed_updated.connect(self.page_dashboard.update_speed)
        
        self.content_area.addWidget(self.page_dashboard)
        self.content_area.addWidget(self.page_all_downloads)
        
        if self.initial_url:
            self.page_all_downloads.url_input.setText(self.initial_url)
            self.sidebar.btn_group.button(1).setChecked(True)
            self.content_area.setCurrentIndex(1)
        
        # Stack slots for filter views
        self.page_downloading = QWidget()
        self.content_area.addWidget(self.page_downloading)
        
        self.page_finished = QWidget()
        self.content_area.addWidget(self.page_finished)
        
        # Page 4: Settings View
        self.page_settings = SettingsPage()
        self.content_area.addWidget(self.page_settings)

    def switch_page(self, index):
        if index in [1, 2, 3]:
            self.content_area.setCurrentIndex(1)
            if index == 2:
                self.page_all_downloads.set_status_filter("Downloading")
            elif index == 3:
                self.page_all_downloads.set_status_filter("Completed")
            else:
                self.page_all_downloads.set_status_filter(None)
        else:
            self.content_area.setCurrentIndex(index)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        logo_icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logo.png"))
        if os.path.exists(logo_icon_path):
            self.tray_icon.setIcon(QIcon(logo_icon_path))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ArrowDown))
        
        tray_menu = QMenu()
        action_show = QAction(f"Show {APP_PROSE_NAME} Engine", self)
        action_show.triggered.connect(self.show_window)
        tray_menu.addAction(action_show)
        
        action_quit = QAction("Exit App", self)
        action_quit.triggered.connect(self.quit_app)
        tray_menu.addAction(action_quit)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self.on_tray_activated)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)

    def quit_app(self):
        self.settings.setValue("geometry", self.saveGeometry())
        QApplication.quit()

    def closeEvent(self, event):
        if self.tray_icon.isVisible():
            self.hide()
            if not self.has_shown_tray_msg:
                self.tray_icon.showMessage(
                    f"{APP_PROSE_NAME} Engine",
                    "Application minimized to tray. Downloads will continue running.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )
                self.has_shown_tray_msg = True
            event.ignore()
        else:
            self.settings.setValue("geometry", self.saveGeometry())
            event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BarqMainWindow()
    
    def on_global_speed(speed):
        speed_kb = speed / 1024
        if speed_kb > 1024:
            window.status_speed.setText(f"Speed: {speed_kb/1024:.2f} MB/s")
        else:
            window.status_speed.setText(f"Speed: {speed_kb:.2f} KB/s")
            
    window.page_all_downloads.global_speed_updated.connect(on_global_speed)
    window.show()
    sys.exit(app.exec())
