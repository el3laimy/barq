from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QFileDialog, QSpinBox, 
                             QFormLayout, QMessageBox, QWidget, QFrame)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
import os
import urllib.parse
from core.settings import settings_manager
from core.utils import FileCategorizer, format_size, sanitize_filename
from core.url_resolver import URLResolver

class NewDownloadDialog(QDialog):
    def __init__(self, initial_url="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Barq Engine • New Download Task")
        self.setMinimumWidth(540)
        self.setModal(True)
        self.download_config = None

        self.setStyleSheet("""
            QDialog {
                background-color: #090D16;
            }
            QLabel {
                font-weight: 600;
                color: #90A4AE;
            }
        """)

        self.network_manager = QNetworkAccessManager(self)
        self.network_manager.finished.connect(self.on_head_request_finished)

        self.init_ui()
        if initial_url:
            resolved = URLResolver.resolve_url(initial_url)
            self.url_input.setText(resolved)
            self.on_url_changed(resolved)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header Title
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        dlg_title = QLabel("Add New Download Task")
        dlg_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #FFFFFF;")
        dlg_sub = QLabel("Paste URL and configure save location & transfer threads")
        dlg_sub.setStyleSheet("font-size: 11.5px; color: #90A4AE; font-weight: normal;")
        title_box.addWidget(dlg_title)
        title_box.addWidget(dlg_sub)
        layout.addLayout(title_box)

        # Form Card Container
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
        self.url_input.setPlaceholderText("https://example.com/file.zip")
        self.url_input.textChanged.connect(self.on_url_changed)
        form_layout.addRow("URL Source:", self.url_input)

        # Filename Input
        self.filename_input = QLineEdit()
        form_layout.addRow("Output Filename:", self.filename_input)

        # Save Location
        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)
        self.path_input = QLineEdit()
        self.path_input.setText(settings_manager.get("download_path"))
        self.browse_btn = QPushButton("📂 Browse")
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(self.path_input, stretch=3)
        path_layout.addWidget(self.browse_btn)
        form_layout.addRow("Save Directory:", path_layout)

        # Category & Size Row
        meta_row = QHBoxLayout()
        self.category_label = QLabel("Detecting...")
        self.category_label.setStyleSheet("color: #00E5FF; font-weight: 700;")
        
        self.size_label = QLabel("Fetching size...")
        self.size_label.setStyleSheet("color: #00E676; font-weight: 700;")
        
        meta_row.addWidget(QLabel("Category:"))
        meta_row.addWidget(self.category_label)
        meta_row.addSpacing(20)
        meta_row.addWidget(QLabel("File Size:"))
        meta_row.addWidget(self.size_label)
        meta_row.addStretch()
        
        form_layout.addRow("Metadata:", meta_row)

        # Segment Threads
        self.segments_spin = QSpinBox()
        self.segments_spin.setRange(1, 32)
        self.segments_spin.setValue(16)
        form_layout.addRow("Parallel Threads:", self.segments_spin)

        # Optional Hash Verification
        self.hash_input = QLineEdit()
        self.hash_input.setPlaceholderText("Optional MD5 / SHA256 Checksum")
        form_layout.addRow("Hash Verification:", self.hash_input)

        layout.addWidget(card)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("class", "secondary")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.start_btn = QPushButton("⚡ Start Download Now")
        self.start_btn.setProperty("class", "primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.accept_download)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.start_btn)
        
        layout.addLayout(btn_layout)

    def on_url_changed(self, url):
        if not url:
            return
            
        resolved_url = URLResolver.resolve_url(url)
        parsed = urllib.parse.urlparse(resolved_url)
        path = urllib.parse.unquote(parsed.path)
        filename = os.path.basename(path.rstrip('/'))
        if not filename or filename.lower() in ['uc', 'download']:
            if 'id=' in parsed.query:
                filename = f"drive_file_{parsed.query.split('id=')[1].split('&')[0]}"
            else:
                filename = "downloaded_file"
            
        filename = sanitize_filename(filename)
        self.filename_input.setText(filename)
        
        category = FileCategorizer.get_category(filename)
        self.category_label.setText(category)
        
        base_dir = settings_manager.get("download_path")
        dest_folder = FileCategorizer.get_destination_folder(base_dir, category)
        self.path_input.setText(dest_folder)
        
        self.size_label.setText("Fetching...")
        request = QNetworkRequest(QUrl(resolved_url))
        request.setRawHeader(b"User-Agent", b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        self.network_manager.head(request)

    def on_head_request_finished(self, reply: QNetworkReply):
        if reply.error() == QNetworkReply.NetworkError.NoError:
            size_str = reply.rawHeader(b"Content-Length").data().decode('utf-8')
            if size_str and size_str.isdigit():
                size = int(size_str)
                self.size_label.setText(format_size(size))
            else:
                self.size_label.setText("Unknown Size")
                
            cd = reply.rawHeader(b"Content-Disposition").data().decode('utf-8', errors='ignore')
            if cd:
                import re
                m_utf8 = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.IGNORECASE)
                m_simple = re.search(r'filename="?([^";]+)"?', cd, re.IGNORECASE)
                real_name = None
                if m_utf8:
                    real_name = urllib.parse.unquote(m_utf8.group(1))
                elif m_simple:
                    real_name = urllib.parse.unquote(m_simple.group(1))
                
                if real_name:
                    real_name = sanitize_filename(real_name)
                    self.filename_input.setText(real_name)
                    category = FileCategorizer.get_category(real_name)
                    self.category_label.setText(category)
                    base_dir = settings_manager.get("download_path")
                    self.path_input.setText(FileCategorizer.get_destination_folder(base_dir, category))
        else:
            self.size_label.setText("Unknown Size")
        reply.deleteLater()

    def browse_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.path_input.text())
        if folder:
            self.path_input.setText(folder)

    def accept_download(self):
        raw_url = self.url_input.text().strip()
        url = URLResolver.resolve_url(raw_url)
        filename = self.filename_input.text().strip()
        path = self.path_input.text().strip()
        
        if not url or not filename or not path:
            QMessageBox.warning(self, "Validation Error", "URL Source, Filename, and Save Directory are required.")
            return
            
        full_dest = os.path.join(path, filename) if (os.path.isdir(path) or not path.endswith(filename)) else path

        self.download_config = {
            "url": url,
            "filename": filename,
            "path": full_dest,
            "category": self.category_label.text(),
            "segments": self.segments_spin.value(),
            "hash": self.hash_input.text().strip()
        }
        self.accept()
