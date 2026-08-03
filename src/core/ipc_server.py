import json
import logging
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QTcpServer, QHostAddress

logger = logging.getLogger(__name__)

class IPCServer(QObject):
    """
    TCP Socket Server listening on 127.0.0.1:19375 to receive download requests
    from Chrome extension bridge script or command-line invocations.
    """
    url_received = pyqtSignal(str)
    
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
        data = client_socket.readAll().data().decode('utf-8', errors='ignore')
        lines = data.strip().split('\n')
        for line in lines:
            if not line:
                continue
            try:
                msg = json.loads(line)
                url = msg.get('url')
                if url:
                    logger.info(f"IPC Received URL: {url}")
                    self.url_received.emit(url)
            except Exception as e:
                logger.error(f"Error parsing IPC message: {e}")

    def _on_disconnected(self, client_socket):
        if client_socket in self._sockets:
            self._sockets.remove(client_socket)
        client_socket.deleteLater()
