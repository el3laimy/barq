from __future__ import annotations

import os
import sys
import threading
import imageio_ffmpeg
import yt_dlp
from PyQt6.QtCore import QThread, pyqtSignal

_ALLOWED_MEDIA_HEADERS = frozenset(
    {"cookie", "user-agent", "referer", "origin", "accept", "accept-language"}
)


def sanitize_media_request_headers(
    request_headers: dict[str, str] | None,
) -> dict[str, str]:
    if not request_headers:
        return {}

    result = {}
    for name, value in request_headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if name.lower() not in _ALLOWED_MEDIA_HEADERS:
            continue
        if "\r" in value or "\n" in value:
            continue
        result[name] = value

    return result


def build_common_ydl_options(request_headers: dict[str, str] | None = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
    }

    headers = sanitize_media_request_headers(request_headers)
    if headers:
        opts["http_headers"] = headers

    ffmpeg_bin = VideoInfoExtractor.get_ffmpeg_path()
    if ffmpeg_bin:
        opts["ffmpeg_location"] = ffmpeg_bin

    return opts


class VideoInfoExtractor:
    """Extracts video metadata, resolutions, and streaming formats using yt-dlp."""

    @staticmethod
    def get_ffmpeg_path():
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    @classmethod
    def extract_info(cls, url, request_headers=None):
        ydl_opts = build_common_ydl_options(request_headers)
        ydl_opts.update({
            'extract_flat': False,
            'skip_download': True,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info

    @classmethod
    def get_formats(cls, info_dict):
        """Parse formats into clean, user-friendly resolution options."""
        formats = []
        raw_formats = info_dict.get('formats', [])
        
        seen_res = set()
        for f in raw_formats:
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            height = f.get('height')
            fps = f.get('fps', 30)
            ext = f.get('ext', 'mp4')
            filesize = f.get('filesize') or f.get('filesize_approx') or 0
            
            if vcodec != 'none' and height:
                res_key = f"{height}p"
                if fps and fps > 30:
                    res_key += f"{int(fps)}"
                    
                if res_key not in seen_res:
                    seen_res.add(res_key)
                    formats.append({
                        'format_id': f"{f.get('format_id')}+bestaudio/best",
                        'resolution': res_key,
                        'height': height,
                        'ext': ext,
                        'filesize': filesize,
                        'note': f.get('format_note', ''),
                        'type': 'video'
                    })
                    
        # Sort by height descending
        formats.sort(key=lambda x: x['height'], reverse=True)

        # Add Audio Only option
        formats.append({
            'format_id': 'bestaudio/best',
            'resolution': 'Audio MP3 / AAC',
            'height': 0,
            'ext': 'mp3',
            'filesize': 0,
            'note': 'Best Audio Quality',
            'type': 'audio'
        })

        return formats


class VideoDownloadWorker(QThread):
    """Asynchronous worker for downloading and merging high-res streams via yt-dlp & FFmpeg."""
    
    started = pyqtSignal(str, int)                # url, total_bytes
    progress_updated = pyqtSignal(int, int, float) # current_bytes, total_bytes, speed_bytes_sec
    status_changed = pyqtSignal(str)              # status string
    task_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, url, destination, format_id='bestvideo+bestaudio/best', request_headers=None, parent=None):
        super().__init__(parent)
        self.url = url
        self.destination = destination
        self.format_id = format_id
        self.request_headers = dict(request_headers or {})
        self._is_stopped = False

    def run(self):
        try:
            self.status_changed.emit("Initializing Video Stream...")
            dest_dir = os.path.dirname(self.destination)
            dest_filename = os.path.basename(self.destination)
            
            out_template = os.path.join(dest_dir, f"{os.path.splitext(dest_filename)[0]}.%(ext)s")

            ydl_opts = build_common_ydl_options(self.request_headers)
            ydl_opts.update({
                'format': self.format_id,
                'outtmpl': out_template,
                'progress_hooks': [self._progress_hook],
            })
                
            if 'bestaudio' in self.format_id and 'bestvideo' not in self.format_id:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]

            self.status_changed.emit("Downloading Video...")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])

            if not self._is_stopped:
                self.status_changed.emit("Completed")
                self.task_finished.emit()

        except Exception as e:
            if not self._is_stopped:
                self.error_occurred.emit(str(e))

    def _progress_hook(self, d):
        if self._is_stopped:
            raise Exception("Download cancelled by user.")

        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            speed = d.get('speed') or 0.0
            
            self.progress_updated.emit(downloaded, total, float(speed))
        elif d['status'] == 'finished':
            self.status_changed.emit("Merging Streams (FFmpeg)...")

    def stop(self):
        self._is_stopped = True
