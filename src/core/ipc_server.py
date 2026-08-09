import json
import logging
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QTcpServer, QHostAddress

from utils.security import redact_sensitive_data

logger = logging.getLogger(__name__)

LEGACY_BROWSER_PAYLOAD_FIELDS = frozenset({
    "cookies",
    "useragent",
    "referrer",
    "filename",
    "filesize",
})

class IPCServer(QObject):
    """
    TCP Socket Server listening on 127.0.0.1:19375 to receive download requests
    from local command-line invocations and compatibility clients.
    """
    url_received = pyqtSignal(str)
    request_received = pyqtSignal(dict)
    
    def __init__(self, port=19375, parent=None):
        super().__init__(parent)
        self.port = port
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._handle_new_connection)
        self._sockets = []

    def start(self) -> bool:
        """Start listening on localhost."""
        if not self.server.listen(QHostAddress.SpecialAddress.LocalHost, self.port):
            logger.warning(f"IPC Server failed to listen on port {self.port}: {self.server.errorString()}")
            return False
        logger.info(f"IPC Server running on 127.0.0.1:{self.port}")
        return True

    def stop(self):
        """Stop listening and close connections."""
        for sock in self._sockets:
            sock.close()
        self._sockets.clear()
        self.server.close()

    def _handle_new_connection(self):
        client_socket = self.server.nextPendingConnection()
        if client_socket:
            self._sockets.append(client_socket)
            client_socket.readyRead.connect(lambda: self._read_data(client_socket))
            client_socket.disconnected.connect(lambda: self._on_disconnected(client_socket))

    def _read_data(self, client_socket):
        payload_text = client_socket.readAll().data().decode('utf-8', errors='ignore')
        for request_line in payload_text.strip().split('\n'):
            if not request_line:
                continue
            request = self.parse_request(request_line)
            if not request:
                continue

            url = request["url"]
            logger.info(f"IPC Received URL: {redact_sensitive_data(url)}")
            self.url_received.emit(url)
            self.request_received.emit(request)

    @staticmethod
    def parse_request(request_line: str) -> dict[str, str] | None:
        """Accept URL-only IPC requests and reject retired browser bridge data."""
        try:
            request = json.loads(request_line)
        except json.JSONDecodeError:
            logger.warning("Rejected malformed IPC request")
            return None

        if not isinstance(request, dict):
            return None
        if any(field.lower() in LEGACY_BROWSER_PAYLOAD_FIELDS for field in request):
            logger.warning("Rejected IPC request containing retired browser bridge fields")
            return None

        url = request.get("url")
        if not isinstance(url, str) or not url:
            return None
        return {"url": url}

    def _on_disconnected(self, client_socket):
        if client_socket in self._sockets:
            self._sockets.remove(client_socket)
        client_socket.deleteLater()
