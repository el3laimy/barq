from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QComboBox, QFileDialog, 
                             QFormLayout, QMessageBox, QFrame, QProgressBar)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
import os
import urllib.parse
from core.settings import settings_manager
from core.utils import FileCategorizer, format_size, sanitize_filename
from core.video_engine import VideoInfoExtractor

class FetchVideoInfoThread(QThread):
    info_fetched = pyqtSignal(dict)
    fetch_failed = pyqtSignal(str)

    def __init__(self, url, request_headers=None, parent=None):
        super().__init__(parent)
        self.url = url
        self.request_headers = dict(request_headers or {})

    def run(self):
        try:
            info = VideoInfoExtractor.extract_info(self.url, request_headers=self.request_headers)
            if info:
                self.info_fetched.emit(info)
            else:
                self.fetch_failed.emit("Failed to extract video information.")
        except Exception as e:
            self.fetch_failed.emit(str(e))


class VideoDownloadDialog(QDialog):
    def __init__(self, initial_url="", request_headers=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Barq Media Engine • Stream & Video Extractor")
        self.setMinimumWidth(560)
        self.setModal(True)
        self.download_config = None
        self.parsed_formats = []
        self.request_headers = dict(request_headers or {})

        self.setStyleSheet("""
            QDialog {
                background-color: #090D16;
            }
            QLabel {
                font-weight: 600;
                color: #90A4AE;
            }
        """)

        self.init_ui()
        if initial_url:
            self.url_input.setText(initial_url)
            self.fetch_video_details(initial_url)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header Title
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        dlg_title = QLabel("🎬 Video Stream Extractor")
        dlg_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #FFFFFF;")
        dlg_sub = QLabel("Select stream quality, format resolution, and save directory")
        dlg_sub.setStyleSheet("font-size: 11.5px; color: #90A4AE; font-weight: normal;")
        title_box.addWidget(dlg_title)
        title_box.addWidget(dlg_sub)
        layout.addLayout(title_box)

        # Card Form Container
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #121826;
                border: 1px solid #232F46;
                border-radius: 12px;
                padding: 16px;
            }
        """)
        form_layout = QFormLayout(card)
        form_layout.setSpacing(12)

        # URL Input
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        form_layout.addRow("Video URL:", self.url_input)

        # Video Title / Status
        self.video_title_label = QLabel("Fetching video details from stream...")
        self.video_title_label.setStyleSheet("color: #00E5FF; font-weight: bold;")
        self.video_title_label.setWordWrap(True)
        form_layout.addRow("Title:", self.video_title_label)

        # Quality Resolution ComboBox
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("Fetching resolutions...")
        form_layout.addRow("Quality / Format:", self.quality_combo)

        # Output Filename
        self.filename_input = QLineEdit()
        form_layout.addRow("Filename:", self.filename_input)

        # Save Directory
        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)
        self.path_input = QLineEdit()
        self.path_input.setText(os.path.join(settings_manager.get("download_path"), "Video"))
        self.browse_btn = QPushButton("📂 Browse")
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(self.path_input, stretch=3)
        path_layout.addWidget(self.browse_btn)
        form_layout.addRow("Save Folder:", path_layout)

        layout.addWidget(card)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("class", "secondary")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)

        self.start_btn = QPushButton("⚡ Download Video Now")
        self.start_btn.setProperty("class", "primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.accept_download)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.start_btn)

        layout.addLayout(btn_layout)

    def fetch_video_details(self, url):
        self.video_title_label.setText("⌛ Fetching video metadata and available qualities...")
        self.start_btn.setEnabled(False)

        self.fetch_thread = FetchVideoInfoThread(url, request_headers=self.request_headers, parent=self)
        self.fetch_thread.info_fetched.connect(self.on_info_fetched)
        self.fetch_thread.fetch_failed.connect(self.on_fetch_failed)
        self.fetch_thread.start()

    def on_info_fetched(self, info):
        raw_title = info.get('title', 'Downloaded_Video')
        clean_title = sanitize_filename(raw_title)
        self.video_title_label.setText(clean_title)
        self.filename_input.setText(f"{clean_title}.mp4")

        self.parsed_formats = VideoInfoExtractor.get_formats(info)
        self.quality_combo.clear()

        for fmt in self.parsed_formats:
            res_str = fmt['resolution']
            size_str = format_size(fmt['filesize']) if fmt['filesize'] > 0 else ""
            display = f"{res_str} ({fmt['ext'].upper()})  {size_str}".strip()
            self.quality_combo.addItem(display, fmt)

        self.start_btn.setEnabled(True)

    def on_fetch_failed(self, error):
        self.video_title_label.setText("⚠️ Failed to parse video stream formats.")
        self.quality_combo.clear()
        self.quality_combo.addItem("Best Available Quality (Auto)", {"format_id": "bestvideo+bestaudio/best"})
        self.start_btn.setEnabled(True)

    def browse_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Video Save Directory", self.path_input.text())
        if folder:
            self.path_input.setText(folder)

    def accept_download(self):
        url = self.url_input.text().strip()
        filename = self.filename_input.text().strip()
        path = self.path_input.text().strip()

        if not url or not filename or not path:
            QMessageBox.warning(self, "Validation Error", "URL, Filename, and Save Directory are required.")
            return

        selected_fmt = self.quality_combo.currentData() or {"format_id": "bestvideo+bestaudio/best"}
        format_id = selected_fmt.get("format_id", "bestvideo+bestaudio/best")

        full_dest = os.path.join(path, filename)

        self.download_config = {
            "url": url,
            "filename": filename,
            "path": full_dest,
            "category": "Video",
            "is_video": True,
            "format_id": format_id
        }
        self.accept()
