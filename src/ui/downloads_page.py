import os
import asyncio
import platform
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QProgressBar, QMessageBox, QInputDialog, QMenu,
                             QApplication, QLabel, QFrame, QButtonGroup)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QColor
import urllib.parse

from core.worker import DownloadWorker
from core.browser_inbox_watcher import BrowserDownloadRequest
from core.video_engine import VideoDownloadWorker
from core.database import DatabaseManager
from core.utils import FileCategorizer, format_size, format_speed, sanitize_filename, get_unique_filename
from core.traffic_control import global_limiter
from ui.clipboard_monitor import ClipboardMonitor
from core.settings import settings_manager
from core.download_options import DownloadOptions
from core.task_start_queue import QueuedDownload, TaskStartQueue
from ui.new_download_dialog import NewDownloadDialog
from ui.video_dialog import VideoDownloadDialog
from core.url_resolver import URLResolver


INTERRUPTED_STARTUP_STATUSES = frozenset({"Pending", "Queued", "Initializing", "Downloading"})


def recover_startup_status(status: str) -> str:
    """Never pretend an in-memory worker or queue survived an app restart."""
    return "Paused" if status in INTERRUPTED_STARTUP_STATUSES else status


class DownloadsPage(QWidget):
    global_speed_updated = pyqtSignal(float) # total speed bytes/s

    def __init__(self):
        super().__init__()
        self.db = DatabaseManager() # Initialize DB
        
        # Queue System
        self.download_queue = TaskStartQueue()
        self.max_concurrent = settings_manager.get("max_concurrent_downloads")
        self.scheduling_suspended = False
        self.active_category_filter = "All"
        self.active_status_filter = None
        
        # Connect settings update
        settings_manager.settings_changed.connect(self.on_settings_changed)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 1. Top Bar: Add URL + Search Bar
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste URL here to start download or stream extraction...")
        self.url_input.returnPressed.connect(self.add_download_from_input)

        self.add_btn = QPushButton("➕ New Download")
        self.add_btn.setProperty("class", "primary")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self.add_download_from_input)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search downloads...")
        self.search_input.setMaximumWidth(260)
        self.search_input.textChanged.connect(self.filter_table)

        header_layout.addWidget(self.url_input, stretch=3)
        header_layout.addWidget(self.add_btn)
        header_layout.addWidget(self.search_input, stretch=1)

        layout.addLayout(header_layout)

        # 2. Category Filter Chips Bar
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(8)
        
        self.cat_group = QButtonGroup(self)
        self.cat_group.setExclusive(True)
        self.cat_group.idClicked.connect(self.on_category_chip_clicked)

        categories = [
            ("All Categories", "All", 0),
            ("🎬 Videos", "Video", 1),
            ("🎵 Audio", "Audio", 2),
            ("📄 Documents", "Documents", 3),
            ("💻 Software", "Executables", 4),
            ("📦 Archives", "Archives", 5)
        ]

        for text, cat_key, idx in categories:
            btn = QPushButton(text)
            btn.setProperty("class", "chip-btn")
            btn.setCheckable(True)
            if idx == 0: btn.setChecked(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.cat_group.addButton(btn, idx)
            chips_layout.addWidget(btn)

        chips_layout.addStretch()
        layout.addLayout(chips_layout)

        # 3. Main Downloads Table Grid
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Filename", "Size", "Progress & Speed", "Status", "Actions"])
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 100)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(3, 110)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(4, 210)
        
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        
        self.setAcceptDrops(True)
        layout.addWidget(self.table)

        # 4. Selection Detail Drawer Panel (Bottom)
        self.detail_frame = QFrame()
        self.detail_frame.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F46;
                border-radius: 10px;
                padding: 8px;
            }
        """)
        detail_layout = QHBoxLayout(self.detail_frame)
        detail_layout.setContentsMargins(12, 6, 12, 6)
        
        self.lbl_selected_url = QLabel("Select a download task to inspect details")
        self.lbl_selected_url.setStyleSheet("color: #90A4AE; font-size: 11.5px;")
        
        self.btn_copy_url = QPushButton("📋 Copy URL")
        self.btn_copy_url.setProperty("class", "secondary")
        self.btn_copy_url.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_url.clicked.connect(self.copy_selected_url)
        self.btn_copy_url.hide()

        self.btn_open_folder = QPushButton("📂 Open Folder")
        self.btn_open_folder.setProperty("class", "secondary")
        self.btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_folder.clicked.connect(self.open_selected_folder)
        self.btn_open_folder.hide()

        detail_layout.addWidget(self.lbl_selected_url)
        detail_layout.addStretch()
        detail_layout.addWidget(self.btn_copy_url)
        detail_layout.addWidget(self.btn_open_folder)

        layout.addWidget(self.detail_frame)

        # State
        self.workers = {} # db_id -> worker
        self.worker_speeds = {} # db_id -> current_speed
        self.downloads_info = {} # db_id -> metadata dict
        self.task_options = {} # db_id -> transfer options for this application session
        self.browser_request_headers = {} # db_id -> in-memory authenticated browser context
        self.browser_request_context_urls = {} # db_id -> origin that supplied browser context
        self.download_dir = settings_manager.get("download_path")
        if not os.path.exists(self.download_dir):
            try:
                os.makedirs(self.download_dir, exist_ok=True)
            except Exception:
                pass
        
        # Speed Timer
        self.speed_timer = QTimer(self)
        self.speed_timer.timeout.connect(self.emit_global_speed)
        self.speed_timer.start(500)
        
        # Clipboard Monitor
        self.clipboard_monitor = ClipboardMonitor()
        self.clipboard_monitor.url_detected.connect(self.on_clipboard_url)
        
        # Populate table from DB
        self.load_from_db()

    def is_video_stream_url(self, url):
        u = url.lower()
        video_domains = ['youtube.com', 'youtu.be', 'tiktok.com', 'vimeo.com', 'facebook.com', 'fb.watch', 'twitter.com', 'x.com', 'instagram.com', 'twitch.tv', 'dailymotion.com']
        if any(domain in u for domain in video_domains) or '.m3u8' in u or '.mpd' in u:
            return True
        return False

    def load_from_db(self):
        downloads = self.db.get_all_downloads()
        for data in downloads:
            recovered_status = recover_startup_status(data['status'])
            if recovered_status != data['status']:
                self.db.update_status(data['id'], recovered_status)
            self.add_row_to_table(
                data['id'],
                data['filename'],
                recovered_status,
                data['url'],
                data['destination'],
                size=data.get('size', 0),
            )

    def add_row_to_table(self, db_id, filename, status, url, dest, size=0):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        display_name = sanitize_filename(filename)
        category = FileCategorizer.get_category(display_name)
        icon_map = {
            'Images': '🖼️ ', 'Video': '🎬 ', 'Audio': '🎵 ',
            'Documents': '📄 ', 'Archives': '📦 ', 'Executables': '💻 ', 'Code': '⚙️ '
        }
        icon = icon_map.get(category, '📄 ')
        
        # Format Arabic / RTL text so .pdf extension remains on the right
        formatted_name = f"\u200E{icon} {display_name}"
        name_item = QTableWidgetItem(formatted_name)
        name_item.setData(Qt.ItemDataRole.UserRole, db_id)
        name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, 0, name_item)
        
        # Determine exact target file path
        full_file_path = dest
        if os.path.isdir(dest):
            full_file_path = os.path.join(dest, display_name)

        # Check real size on disk if size in DB is 0
        real_size = size
        if real_size == 0 and os.path.exists(full_file_path) and not os.path.isdir(full_file_path):
            real_size = os.path.getsize(full_file_path)
            if real_size > 0:
                self.db.update_status(db_id, status, size=real_size)

        # Metadata
        self.downloads_info[db_id] = {
            'url': url, 'dest': full_file_path, 'status': status, 'id': db_id, 'category': category, 'size': real_size,
            'progress': 100 if status == "Completed" else 0, 'speed': 0
        }
        
        # File Size formatting
        file_size_str = "--"
        if real_size and real_size > 0:
            file_size_str = format_size(real_size)
            
        size_item = QTableWidgetItem(file_size_str)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 1, size_item)
        
        # Progress Bar Widget
        pbar = QProgressBar()
        if status == "Completed":
            pbar.setValue(100)
            pbar.setFormat("Completed (100%)")
        else:
            pbar.setValue(0)
            pbar.setFormat("0%")
        self.table.setCellWidget(row, 2, pbar)
        
        # Status Item
        status_item = QTableWidgetItem(status)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.apply_status_color(status_item, status)
        self.table.setItem(row, 3, status_item)
        
        # Action Buttons Container Widget
        actions_widget = QWidget()
        act_layout = QHBoxLayout(actions_widget)
        act_layout.setContentsMargins(2, 2, 2, 2)
        act_layout.setSpacing(4)

        btn_toggle_text = "Open" if status == "Completed" else "Pause" if status in ["Downloading", "Initializing"] else "Resume"
        btn_toggle = QPushButton(btn_toggle_text)
        btn_toggle.setStyleSheet("""
            QPushButton {
                background-color: #182030;
                border: 1px solid #354769;
                border-radius: 6px;
                padding: 4px 8px;
                color: #FFFFFF;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #202A3F;
                border-color: #00E5FF;
                color: #00E5FF;
            }
        """)
        btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_toggle.clicked.connect(lambda _, did=db_id: self.on_action_toggle_clicked(did))

        btn_folder = QPushButton("📂")
        btn_folder.setFixedWidth(32)
        btn_folder.setStyleSheet("""
            QPushButton {
                background-color: #182030;
                border: 1px solid #354769;
                border-radius: 6px;
                padding: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                border-color: #00E5FF;
            }
        """)
        btn_folder.setToolTip("Open Containing Folder")
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.clicked.connect(lambda _, did=db_id: self.open_folder(did))

        btn_delete = QPushButton("✕")
        btn_delete.setFixedWidth(32)
        btn_delete.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 82, 82, 0.15);
                border: 1px solid #FF5252;
                border-radius: 6px;
                padding: 4px;
                font-size: 11px;
                color: #FF5252;
            }
            QPushButton:hover {
                background-color: #FF5252;
                color: #FFFFFF;
            }
        """)
        btn_delete.setToolTip("Remove task from list (keeps downloaded files)")
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete.clicked.connect(lambda _, did=db_id: self.delete_download(did))

        act_layout.addWidget(btn_toggle, stretch=2)
        act_layout.addWidget(btn_folder)
        act_layout.addWidget(btn_delete)

        self.table.setCellWidget(row, 4, actions_widget)

    def apply_status_color(self, item, status):
        if status == "Completed":
            item.setForeground(QColor("#00E676"))
        elif status in ["Downloading", "Initializing"]:
            item.setForeground(QColor("#00E5FF"))
        elif status in ["Error", "Expired"]:
            item.setForeground(QColor("#FF5252"))
        elif status in ["Paused", "Queued", "Stopped"]:
            item.setForeground(QColor("#FFAB00"))

    def add_download_from_input(self):
        url = self.url_input.text().strip()
        if url:
             self.add_download(url)
             self.url_input.clear()

    def add_download(self, url):
        resolved_url = URLResolver.resolve_url(url)
        
        if self.is_video_stream_url(resolved_url):
            dialog = VideoDownloadDialog(initial_url=resolved_url, parent=self)
        else:
            dialog = NewDownloadDialog(initial_url=resolved_url, parent=self)

        if dialog.exec():
            config = dialog.download_config
            if not config: return
            
            db_id = self.db.add_download(config['url'], config['filename'], config['path'], config['category'])
            if db_id is None:
                QMessageBox.warning(self, "Download Error", "Could not save the new download task.")
                return
            self.add_row_to_table(db_id, config['filename'], "Pending", config['url'], config['path'])
            
            is_video = config.get('is_video', False)
            format_id = config.get('format_id', 'bestvideo+bestaudio/best')
            options = DownloadOptions(
                parts=config.get('segments'),
                checksum=config.get('checksum'),
            )
            self.task_options[db_id] = options
            self.attempt_start_download(
                db_id,
                config['url'],
                config['path'],
                is_video=is_video,
                format_id=format_id,
                options=options,
            )

    def add_browser_download(self, browser_request: BrowserDownloadRequest) -> bool:
        if browser_request.is_media:
            return self._handle_browser_media(browser_request)
        return self._handle_browser_direct_download(browser_request)

    def _handle_browser_direct_download(self, browser_request: BrowserDownloadRequest) -> bool:
        filename = self._browser_filename(browser_request)
        category = FileCategorizer.get_category(filename)
        destination_folder = FileCategorizer.get_destination_folder(self.download_dir, category)
        filename = get_unique_filename(destination_folder, filename)
        destination = os.path.join(destination_folder, filename)

        db_id = self.db.add_download(browser_request.url, filename, destination, category)
        if db_id is None:
            return False
        self.browser_request_headers[db_id] = dict(browser_request.request_headers)
        self.browser_request_context_urls[db_id] = browser_request.context_url
        self.add_row_to_table(db_id, filename, "Pending", browser_request.url, destination, browser_request.file_size or 0)
        self.attempt_start_download(db_id, browser_request.url, destination)
        return True

    def _handle_browser_media(self, browser_request: BrowserDownloadRequest) -> bool:
        media_url = browser_request.page_url or browser_request.url

        try:
            dialog = VideoDownloadDialog(
                initial_url=media_url,
                request_headers=browser_request.request_headers,
                parent=self,
            )

            accepted = dialog.exec()
            if not accepted:
                return True  # User intentionally cancelled; acknowledge handoff

            config = dialog.download_config
            if not config:
                return True

            category = config.get("category", "Video")
            db_id = self.db.add_download(
                config["url"], config["filename"], config["path"], category
            )
            if db_id is None:
                return False

            self.browser_request_headers[db_id] = dict(browser_request.request_headers)
            self.browser_request_context_urls[db_id] = (
                browser_request.page_url or browser_request.context_url
            )

            self.add_row_to_table(
                db_id, config["filename"], "Pending", config["url"], config["path"]
            )

            is_video = config.get("is_video", True)
            format_id = config.get("format_id", "bestvideo+bestaudio/best")

            self.attempt_start_download(
                db_id,
                config["url"],
                config["path"],
                is_video=is_video,
                format_id=format_id,
            )

            return True
        except Exception:
            logger.error("Could not accept browser media request")
            return False

    @staticmethod
    def _browser_filename(browser_request: BrowserDownloadRequest) -> str:
        if browser_request.suggested_name:
            return sanitize_filename(browser_request.suggested_name)
        url_path = urllib.parse.urlparse(browser_request.url).path
        return sanitize_filename(os.path.basename(urllib.parse.unquote(url_path)) or 'downloaded_file')

    def attempt_start_download(
        self,
        db_id,
        url,
        dest,
        is_video=False,
        format_id='bestvideo+bestaudio/best',
        options=None,
    ):
        if db_id not in self.downloads_info or db_id in self.workers:
            return
        options = options or self.task_options.get(db_id, DownloadOptions())
        if self.scheduling_suspended:
            if self.download_queue.enqueue(
                QueuedDownload(db_id, url, dest, is_video, format_id, options)
            ):
                self.update_status(db_id, "Paused")
        elif len(self.workers) < self.max_concurrent:
            self.start_worker(
                db_id,
                url,
                dest,
                is_video=is_video,
                format_id=format_id,
                options=options,
            )
        elif self.download_queue.enqueue(
            QueuedDownload(db_id, url, dest, is_video, format_id, options)
        ):
            self.update_status(db_id, "Queued")

    def process_queue(self):
        if self.scheduling_suspended:
            return
        while len(self.workers) < self.max_concurrent and self.download_queue:
            item = self.download_queue.pop_next()
            if item is None:
                return
            if item.task_id not in self.downloads_info or item.task_id in self.workers:
                continue
            if self.downloads_info[item.task_id]['status'] == "Completed":
                continue
            self.start_worker(
                item.task_id,
                item.url,
                item.destination,
                is_video=item.is_video,
                format_id=item.format_id,
                options=item.options,
            )

    def get_row_by_id(self, db_id):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == db_id:
                return r
        return None

    def start_worker(
        self,
        db_id,
        url,
        dest,
        is_video=False,
        format_id='bestvideo+bestaudio/best',
        options=None,
    ):
        if db_id not in self.downloads_info or db_id in self.workers:
            return
        options = options or self.task_options.get(db_id, DownloadOptions())
        self.download_queue.discard(db_id)
        request_headers = self.browser_request_headers.get(db_id)
        browser_context_url = self.browser_request_context_urls.get(db_id)
        try:
            if is_video or (request_headers is None and self.is_video_stream_url(url)):
                worker = VideoDownloadWorker(url, dest, format_id=format_id, request_headers=request_headers)
            else:
                worker = DownloadWorker(
                    url,
                    dest,
                    request_headers=request_headers,
                    browser_context_url=browser_context_url,
                    parts=options.parts,
                    checksum=options.checksum,
                )

            worker.started.connect(lambda u, s, did=db_id: self.update_initial_size(did, s))
            worker.progress_updated.connect(lambda c, t, s, did=db_id: self.update_progress(did, c, t, s))
            worker.status_changed.connect(lambda s, did=db_id: self.update_status(did, s))
            worker.task_finished.connect(lambda did=db_id: self.download_finished(did))
            worker.finished.connect(lambda did=db_id: self.cleanup_worker(did))
            worker.error_occurred.connect(lambda e, did=db_id: self.download_error(did, e))

            self.workers[db_id] = worker
            worker.start()
        except Exception as error:
            self.workers.pop(db_id, None)
            self.worker_speeds[db_id] = 0
            self.update_status(db_id, "Error")
            print(f"Could not start download {db_id}: {error}")
        
    def on_action_toggle_clicked(self, db_id):
        if db_id in self.downloads_info:
            status = self.downloads_info[db_id]['status']
            if status == "Completed":
                self.open_folder(db_id)
            else:
                self.toggle_download(db_id)

    def toggle_download(self, db_id):
        row = self.get_row_by_id(db_id)
        if row is None: return

        if db_id not in self.workers:
            if db_id in self.downloads_info:
                info = self.downloads_info[db_id]
                self.attempt_start_download(db_id, info['url'], info['dest'])
            return

        worker = self.workers[db_id]
        if worker.isRunning():
            self.stop_download(db_id)
        else:
            info = self.downloads_info[db_id]
            self.attempt_start_download(db_id, info['url'], info['dest'])

    def update_initial_size(self, db_id, size):
        row = self.get_row_by_id(db_id)
        if row is not None and size > 0:
            self.table.item(row, 1).setText(format_size(size))
            if db_id in self.downloads_info:
                self.downloads_info[db_id]['size'] = size
            self.db.update_status(db_id, self.downloads_info.get(db_id, {}).get('status', 'Pending'), size=size)

    def update_progress(self, db_id, current, total, speed):
        self.worker_speeds[db_id] = speed
        
        progress_pct = 0
        if total > 0:
            progress_pct = int((current / total) * 100)
            
        if db_id in self.downloads_info:
            self.downloads_info[db_id]['current'] = current
            self.downloads_info[db_id]['total'] = total
            self.downloads_info[db_id]['speed'] = speed
            self.downloads_info[db_id]['progress'] = progress_pct

        row = self.get_row_by_id(db_id)
        if row is not None:
            pbar = self.table.cellWidget(row, 2)
            if hasattr(pbar, 'setValue') and total > 0:
                pbar.setValue(progress_pct)
                speed_str = format_speed(speed)
                current_str = format_size(current)
                pbar.setFormat(f"%p% • {speed_str} ({current_str})")
                pbar.setAlignment(Qt.AlignmentFlag.AlignCenter)
                
            if total > 0:
                self.table.item(row, 1).setText(format_size(total))

    def emit_global_speed(self):
        total_speed = sum(self.worker_speeds.values())
        self.global_speed_updated.emit(total_speed)

    def update_status(self, db_id, status):
        if db_id in self.downloads_info:
            self.downloads_info[db_id]['status'] = status

        row = self.get_row_by_id(db_id)
        if row is not None:
            item = self.table.item(row, 3)
            if item:
                item.setText(status)
                self.apply_status_color(item, status)
                
            act_widget = self.table.cellWidget(row, 4)
            if act_widget:
                btn_toggle = act_widget.findChild(QPushButton)
                if btn_toggle:
                    if status == "Completed": btn_toggle.setText("Open")
                    elif status in ["Downloading", "Initializing"]: btn_toggle.setText("Pause")
                    elif status in ["Paused", "Stopped", "Queued"]: btn_toggle.setText("Resume")
                    elif status == "Error": btn_toggle.setText("Retry")
        
        self.db.update_status(db_id, status)
        self.filter_table()

    def download_finished(self, db_id):
        self.update_status(db_id, "Completed")
        self.worker_speeds[db_id] = 0
        self.browser_request_headers.pop(db_id, None)
        self.browser_request_context_urls.pop(db_id, None)
        self.task_options.pop(db_id, None)
        if db_id in self.downloads_info:
            self.downloads_info[db_id]['progress'] = 100
        
        row = self.get_row_by_id(db_id)
        if row is not None and db_id in self.downloads_info:
            dest = self.downloads_info[db_id]['dest']
            if os.path.exists(dest) and not os.path.isdir(dest):
                file_size = os.path.getsize(dest)
                self.table.item(row, 1).setText(format_size(file_size))
                self.db.update_status(db_id, "Completed", size=file_size)

    def cleanup_worker(self, db_id):
        if db_id in self.workers:
             del self.workers[db_id]
             
        self.worker_speeds[db_id] = 0
        if not self.scheduling_suspended:
            self.process_queue()

    def download_error(self, db_id, error):
        self.update_status(db_id, "Error")
        self.worker_speeds[db_id] = 0

    def stop_download(self, db_id):
        if db_id in self.workers:
            worker = self.workers[db_id]
            worker.stop()
            self.worker_speeds[db_id] = 0

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        row = item.row()
        item_0 = self.table.item(row, 0)
        if not item_0: return
        
        db_id = item_0.data(Qt.ItemDataRole.UserRole)
        if db_id is None: return
        
        menu = QMenu(self)
        open_folder_action = menu.addAction("📂 Open Folder")
        copy_url_action = menu.addAction("📋 Copy URL")
        verify_action = menu.addAction("🔐 Set Hash Verification (MD5/SHA256)")
        remove_action = menu.addAction("✕ Remove from List")
        delete_files_action = menu.addAction("🗑️ Permanently Delete Download Files…")
        
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        
        if action == open_folder_action:
            self.open_folder(db_id)
        elif action == copy_url_action:
            if db_id in self.downloads_info:
                QApplication.clipboard().setText(self.downloads_info[db_id]['url'])
        elif action == verify_action:
            self.set_hash_dialog(db_id)
        elif action == remove_action:
            self.delete_download(db_id)
        elif action == delete_files_action:
            self.delete_download_files(db_id)

    def open_folder(self, db_id):
        if db_id in self.downloads_info:
            dest = self.downloads_info[db_id]['dest']
            folder = os.path.dirname(dest) if not os.path.isdir(dest) else dest
            if os.path.exists(folder):
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            else:
                QMessageBox.warning(self, "Error", "Folder does not exist.")

    def delete_download(self, db_id):
        """Remove a task from Barq while preserving all files by default."""
        self._remove_download(db_id, delete_files=False)

    def delete_download_files(self, db_id):
        """Permanently remove a task and its final, partial, and state files."""
        if db_id not in self.downloads_info:
            return
        response = QMessageBox.question(
            self,
            "Permanently delete download files?",
            "This permanently deletes the completed file, partial file, and resume state. "
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if response == QMessageBox.StandardButton.Yes:
            self._remove_download(db_id, delete_files=True)

    def _remove_download(self, db_id, delete_files):
        self.download_queue.discard(db_id)
        if db_id in self.workers:
            worker = self.workers[db_id]
            worker.stop()
            worker.wait()
            
        self.db.delete_download(db_id)
        self.browser_request_headers.pop(db_id, None)
        self.browser_request_context_urls.pop(db_id, None)
        self.task_options.pop(db_id, None)
        
        if db_id in self.downloads_info:
             dest = self.downloads_info[db_id]['dest']
             if delete_files:
                 try:
                    if os.path.exists(dest) and not os.path.isdir(dest): os.remove(dest)
                    if os.path.exists(dest + ".part"): os.remove(dest + ".part")
                    if os.path.exists(dest + ".state.json"): os.remove(dest + ".state.json")
                 except Exception as e:
                    print(f"Error deleting file: {e}")
             
             del self.downloads_info[db_id]
             
        row = self.get_row_by_id(db_id)
        if row is not None:
             self.table.removeRow(row)

    def on_selection_changed(self):
        selected = self.table.selectedItems()
        if not selected:
            self.lbl_selected_url.setText("Select a download task to inspect details")
            self.btn_copy_url.hide()
            self.btn_open_folder.hide()
            return
            
        row = selected[0].row()
        item_0 = self.table.item(row, 0)
        if item_0:
            db_id = item_0.data(Qt.ItemDataRole.UserRole)
            if db_id in self.downloads_info:
                info = self.downloads_info[db_id]
                self.lbl_selected_url.setText(f"URL: {info['url']}  •  Save Path: {info['dest']}")
                self.btn_copy_url.show()
                self.btn_open_folder.show()

    def copy_selected_url(self):
        selected = self.table.selectedItems()
        if selected:
            row = selected[0].row()
            item_0 = self.table.item(row, 0)
            if item_0:
                db_id = item_0.data(Qt.ItemDataRole.UserRole)
                if db_id in self.downloads_info:
                    QApplication.clipboard().setText(self.downloads_info[db_id]['url'])

    def open_selected_folder(self):
        selected = self.table.selectedItems()
        if selected:
            row = selected[0].row()
            item_0 = self.table.item(row, 0)
            if item_0:
                db_id = item_0.data(Qt.ItemDataRole.UserRole)
                self.open_folder(db_id)

    def on_category_chip_clicked(self, idx):
        cat_keys = ["All", "Video", "Audio", "Documents", "Executables", "Archives"]
        self.active_category_filter = cat_keys[idx]
        self.filter_table()

    def set_status_filter(self, status_filter):
        self.active_status_filter = status_filter
        self.filter_table()

    def filter_table(self):
        search_text = self.search_input.text().lower().strip()
        
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            status_item = self.table.item(row, 3)
            if not name_item or not status_item: continue
                
            db_id = name_item.data(Qt.ItemDataRole.UserRole)
            info = self.downloads_info.get(db_id, {})
            
            # 1. Search text match
            text_match = (search_text in name_item.text().lower()) or (search_text in info.get('url', '').lower())
            
            # 2. Category match
            cat_match = True
            if self.active_category_filter != "All":
                cat_match = (info.get('category') == self.active_category_filter)
                
            # 3. Status filter match
            status_match = True
            if self.active_status_filter:
                row_status = status_item.text()
                if self.active_status_filter == "Downloading":
                    status_match = (row_status != "Completed")
                elif self.active_status_filter == "Completed":
                    status_match = (row_status == "Completed")
                    
            self.table.setRowHidden(row, not (text_match and cat_match and status_match))

    def pause_all(self):
        self.scheduling_suspended = True
        for item in self.download_queue.drain():
            if item.task_id in self.downloads_info:
                self.update_status(item.task_id, "Paused")
        for db_id in list(self.workers.keys()):
            self.stop_download(db_id)

    def resume_all(self):
        self.scheduling_suspended = False
        for db_id, info in self.downloads_info.items():
            if db_id not in self.workers and info['status'] != "Completed":
                self.attempt_start_download(db_id, info['url'], info['dest'])

    def stop_all(self):
        self.pause_all()

    def set_hash_dialog(self, db_id):
        text, ok = QInputDialog.getText(self, "Set Validation Hash", 
                                        "Enter MD5 or SHA256 Hash for File Integrity Check:", 
                                        QLineEdit.EchoMode.Normal)
        if ok and text:
            algo = "sha256" if len(text) == 64 else "md5"
            if db_id in self.workers:
                self.workers[db_id].set_hash(algo, text)
                QMessageBox.information(self, "Hash Verification Configured", f"{algo.upper()} checksum set. File will be verified upon completion.")
            else:
                QMessageBox.warning(self, "Download Inactive", "Task must be active to apply hash verification.")

    def on_clipboard_url(self, url):
        if self.url_input.hasFocus(): return
        for info in self.downloads_info.values():
            if info['url'] == url: return
        
        reply = QMessageBox.question(self, "New Download Detected", 
                                     f"Do you want to download this file?\n\n{url}",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.add_download(url)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                self.add_download(url.toString())
        elif event.mimeData().text():
            self.add_download(event.mimeData().text())

    def on_settings_changed(self, new_settings):
        self.max_concurrent = new_settings.get("max_concurrent_downloads", 3)
        self.download_dir = new_settings.get("download_path")
        if not self.scheduling_suspended:
            self.process_queue()
