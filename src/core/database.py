import sqlite3
import os
import json
from datetime import datetime
import threading

class DatabaseManager:
    def __init__(self, db_path="downloads.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        try:
            with self._lock:
                self._conn.execute('PRAGMA journal_mode=WAL')
                cursor = self._conn.cursor()
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS downloads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        destination TEXT NOT NULL,
                        size INTEGER DEFAULT 0,
                        downloaded INTEGER DEFAULT 0,
                        status TEXT DEFAULT 'Pending',
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP,
                        category TEXT,
                        speed_history TEXT
                    )
                ''')
                
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON downloads(status)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON downloads(category)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_added_at ON downloads(added_at)')
                
                self._conn.commit()
        except Exception as e:
            print(f"DB Init Error: {e}")

    def add_download(self, url, filename, destination, category="Uncategorized"):
        try:
            with self._lock:
                cursor = self._conn.cursor()
                cursor.execute('''
                    INSERT INTO downloads (url, filename, destination, status, category, added_at)
                    VALUES (?, ?, ?, 'Pending', ?, ?)
                ''', (url, filename, destination, category, datetime.now().isoformat()))
                row_id = cursor.lastrowid
                self._conn.commit()
                return row_id
        except Exception as e:
            print(f"DB Add Error: {e}")
            return None

    def update_status(self, download_id, status, downloaded=0, size=0):
        try:
            with self._lock:
                cursor = self._conn.cursor()
                
                updates = ['status = ?']
                params = [status]
                
                if downloaded > 0:
                    updates.append('downloaded = ?')
                    params.append(downloaded)
                if size > 0:
                    updates.append('size = ?')
                    params.append(size)
                    
                if status == "Completed":
                    updates.append('completed_at = ?')
                    params.append(datetime.now().isoformat())
                    
                params.append(download_id)
                
                query = f"UPDATE downloads SET {', '.join(updates)} WHERE id = ?"
                cursor.execute(query, params)
                self._conn.commit()
        except Exception as e:
            print(f"DB Update Status Error: {e}")

    def get_all_downloads(self):
        try:
            with self._lock:
                cursor = self._conn.cursor()
                cursor.execute('SELECT * FROM downloads ORDER BY added_at DESC')
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"DB Get All Error: {e}")
            return []
            
    def get_downloads_by_status(self, status):
        try:
            with self._lock:
                cursor = self._conn.cursor()
                cursor.execute('SELECT * FROM downloads WHERE status = ? ORDER BY added_at DESC', (status,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"DB Get By Status Error: {e}")
            return []

    def update_url(self, download_id, new_url):
        try:
            with self._lock:
                cursor = self._conn.cursor()
                cursor.execute('UPDATE downloads SET url = ? WHERE id = ?', (new_url, download_id))
                self._conn.commit()
        except Exception as e:
            print(f"DB Update URL Error: {e}")
            
    def delete_download(self, download_id):
        try:
            with self._lock:
                cursor = self._conn.cursor()
                cursor.execute('DELETE FROM downloads WHERE id = ?', (download_id,))
                self._conn.commit()
        except Exception as e:
            print(f"DB Delete Error: {e}")
            
    def __del__(self):
        if hasattr(self, '_conn'):
            self._conn.close()
