import os
import re
import urllib.parse

def format_size(size_bytes):
    """Format bytes to human readable string (KB, MB, GB, TB)."""
    if size_bytes is None or size_bytes < 0:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    elif size_bytes < 1024 * 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024 * 1024):.2f} TB"

def format_speed(speed_bytes_sec):
    """Format speed to human readable string (KB/s, MB/s, GB/s)."""
    if speed_bytes_sec is None or speed_bytes_sec < 0:
        return "0 KB/s"
    if speed_bytes_sec < 1024 * 1024:
        return f"{speed_bytes_sec / 1024:.0f} KB/s"
    elif speed_bytes_sec < 1024 * 1024 * 1024:
        return f"{speed_bytes_sec / (1024 * 1024):.2f} MB/s"
    else:
        return f"{speed_bytes_sec / (1024 * 1024 * 1024):.2f} GB/s"

def sanitize_filename(filename):
    """Removes invalid OS characters and unquotes percent-encoded strings in filename."""
    if not filename:
        return "downloaded_file"
    filename = urllib.parse.unquote(filename)
    filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()
    return filename if filename else "downloaded_file"

def get_unique_filename(folder, filename):
    """Generate unique filename with (1), (2) suffix if file already exists in folder."""
    if not os.path.exists(folder):
        return filename
    
    base_name, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1
    
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{base_name} ({counter}){ext}"
        counter += 1
        
    return candidate

class FileCategorizer:
    CATEGORIES = {
        'Images': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp'],
        'Video': ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'],
        'Audio': ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'],
        'Documents': ['.pdf', '.doc', '.docx', '.txt', '.xls', '.xlsx', '.ppt', '.pptx'],
        'Archives': ['.zip', '.rar', '.7z', '.tar', '.gz', '.iso', '.deb'],
        'Executables': ['.exe', '.msi', '.bat', '.sh', '.apk', '.AppImage'],
        'Code': ['.py', '.js', '.html', '.css', '.java', '.cpp', '.json']
    }
    
    _EXT_TO_CATEGORY = {}
    for cat, exts in CATEGORIES.items():
        for ext in exts:
            _EXT_TO_CATEGORY[ext] = cat

    @staticmethod
    def get_category(filename):
        """Return the category name for a given filename."""
        if not filename:
            return 'Others'
        ext = os.path.splitext(filename)[1].lower()
        return FileCategorizer._EXT_TO_CATEGORY.get(ext, 'Others')

    @staticmethod
    def get_destination_folder(base_dir, category):
        """Return the full path for the category folder, creating it if needed."""
        path = os.path.join(base_dir, category)
        os.makedirs(path, exist_ok=True)
        return path
