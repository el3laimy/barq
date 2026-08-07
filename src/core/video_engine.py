import os
import sys
import threading
import imageio_ffmpeg
import yt_dlp
from PyQt6.QtCore import QThread, pyqtSignal

class VideoInfoExtractor:
    """Extracts video metadata, resolutions, and streaming formats using yt-dlp."""
    
    @staticmethod
    def get_ffmpeg_path():
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    @classmethod
    def extract_info(cls, url):
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
        }
        
        ffmpeg_bin = cls.get_ffmpeg_path()
        if ffmpeg_bin:
            ydl_opts['ffmpeg_location'] = ffmpeg_bin

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

    def __init__(self, url, destination, format_id='bestvideo+bestaudio/best', parent=None):
        super().__init__(parent)
        self.url = url
        self.destination = destination
        self.format_id = format_id
        self._is_stopped = False

    def run(self):
        try:
            self.status_changed.emit("Initializing Video Stream...")
            dest_dir = os.path.dirname(self.destination)
            dest_filename = os.path.basename(self.destination)
            
            out_template = os.path.join(dest_dir, f"{os.path.splitext(dest_filename)[0]}.%(ext)s")

            ydl_opts = {
                'format': self.format_id,
                'outtmpl': out_template,
                'progress_hooks': [self._progress_hook],
                'quiet': True,
                'no_warnings': True,
            }

            ffmpeg_bin = VideoInfoExtractor.get_ffmpeg_path()
            if ffmpeg_bin:
                ydl_opts['ffmpeg_location'] = ffmpeg_bin
                
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
