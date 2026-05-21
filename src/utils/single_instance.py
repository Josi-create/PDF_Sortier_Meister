"""
Single-Instance-Verwaltung mit IPC ueber QLocalSocket.

Beim Start wird versucht, ein QLocalServer mit einem festen Namen zu
oeffnen. Gelingt das nicht (oder ein Verbindungsversuch auf den Namen
ist erfolgreich), laeuft bereits eine Instanz. In dem Fall wird der
uebergebene Ordnerpfad an die laufende Instanz uebertragen und der
neue Prozess beendet sich.

Die laufende Instanz emittiert ueber das Signal `folder_received` den
empfangenen Pfad, sodass das Hauptfenster ihn als neuen Scan-Ordner
laden kann.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger("pdf_sortier_meister.single_instance")

# Server-Name fuer QLocalSocket. Auf Windows wird daraus ein Named Pipe,
# der pro Benutzer eindeutig ist (das System haengt den Benutzerkontext an).
SERVER_NAME = "PDFSortierMeister_SingleInstance"

# Zeitlimits in Millisekunden.
_CONNECT_TIMEOUT_MS = 500
_WRITE_TIMEOUT_MS = 1000


def try_send_to_running_instance(folder_path: str) -> bool:
    """
    Versucht, sich mit einer laufenden Instanz zu verbinden und den
    Ordnerpfad zu uebertragen.

    Returns:
        True, wenn eine laufende Instanz erreicht wurde und der Pfad
        gesendet wurde. False, wenn keine Instanz laeuft.
    """
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
        return False

    payload = (folder_path or "").encode("utf-8") + b"\n"
    socket.write(payload)
    socket.flush()
    socket.waitForBytesWritten(_WRITE_TIMEOUT_MS)
    socket.disconnectFromServer()
    return True


class SingleInstanceServer(QObject):
    """
    Lauscht im Hintergrund auf eingehende Ordnerpfade von weiteren
    Programmaufrufen und emittiert sie ueber `folder_received`.
    """

    folder_received = pyqtSignal(str)

    def __init__(self, parent: QObject = None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    def start(self) -> bool:
        """
        Startet den Server. Falls schon ein veralteter Pipe-Eintrag
        existiert (z.B. nach hartem Crash), wird er entfernt.

        Returns:
            True bei Erfolg, sonst False.
        """
        # Aufraeumen: falls ein toter Pipe-Eintrag existiert.
        QLocalServer.removeServer(SERVER_NAME)

        if not self._server.listen(SERVER_NAME):
            logger.warning(
                f"SingleInstance-Server konnte nicht starten: "
                f"{self._server.errorString()}"
            )
            return False
        return True

    def _on_new_connection(self):
        socket = self._server.nextPendingConnection()
        if socket is None:
            return

        # Auf eingehende Daten warten und Pfad lesen.
        if not socket.waitForReadyRead(_CONNECT_TIMEOUT_MS):
            socket.disconnectFromServer()
            return

        data = bytes(socket.readAll()).decode("utf-8", errors="replace").strip()
        socket.disconnectFromServer()

        if data:
            self.folder_received.emit(data)
