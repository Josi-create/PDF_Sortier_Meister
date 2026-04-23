"""
PDF Sortier Meister - Haupteinstiegspunkt

Ein intelligentes Programm zum Sortieren und Umbenennen von gescannten PDFs.
"""

import sys
from pathlib import Path

# Nativer PyInstaller-Splash: wird bereits vom Bootloader angezeigt,
# BEVOR diese Datei ausgefuehrt wird. Wir importieren das Modul nur,
# um den Splash spaeter schliessen zu koennen. In der Dev-Umgebung
# (python main.py) existiert es nicht -> stillschweigend ignorieren.
try:
    import pyi_splash  # type: ignore
    _HAS_PYI_SPLASH = True
except ImportError:
    _HAS_PYI_SPLASH = False

# Füge src zum Pfad hinzu für relative Imports
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap

from src.gui.main_window import MainWindow
from src.utils.config import get_config
from src.utils.logging_config import setup_logging, get_logger

# Versionsnummer zentral definiert
__version__ = "0.9.0"


def main():
    """Hauptfunktion - startet die Anwendung."""
    # Logging initialisieren (vor allem anderen!)
    setup_logging()
    logger = get_logger("main")
    logger.info(f"Version {__version__}")

    # High-DPI Skalierung aktivieren
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Anwendung erstellen
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Sortier Meister")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PDF Sortier Meister")

    # SplashScreen: im gefrorenen Build zeigt PyInstaller den Splash bereits
    # vom Bootloader aus an (siehe .spec). Der Qt-Splash dient nur als
    # Fallback fuer die Dev-Umgebung (python main.py).
    splash = None
    if not _HAS_PYI_SPLASH:
        # Splashbild neben der .exe oder im Projekt-Root suchen
        candidates = [
            Path(getattr(sys, "_MEIPASS", src_path)) / "SplashScreen3.png",
            src_path / "SplashScreen3.png",
        ]
        splash_path = next((p for p in candidates if p.exists()), None)
        if splash_path is not None:
            pixmap = QPixmap(str(splash_path))
            scaled_pixmap = pixmap.scaled(
                pixmap.width() // 2,
                pixmap.height() // 2,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            splash = QSplashScreen(scaled_pixmap)
            splash.setWindowFlags(
                splash.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
            )
            splash.show()
            app.processEvents()

    # Konfiguration laden
    config = get_config()

    # Hauptfenster erstellen
    window = MainWindow()

    # Hauptfenster anzeigen (unter dem SplashScreen)
    window.show()
    app.processEvents()

    # SplashScreen schliessen wenn Thumbnails geladen sind.
    # Safety-Fallback: spaetestens nach 15s schliessen, falls z.B. kein
    # Scan-Ordner konfiguriert ist und thumbnails_loaded nicht feuert.
    _splash_closed = {"done": False}

    def close_splash():
        if _splash_closed["done"]:
            return
        _splash_closed["done"] = True
        if splash is not None:
            splash.close()
        if _HAS_PYI_SPLASH:
            try:
                pyi_splash.close()
            except Exception:
                pass
        window.raise_()
        window.activateWindow()

    window.thumbnails_loaded.connect(close_splash)
    QTimer.singleShot(15000, close_splash)

    # Beim ersten Start: Scan-Ordner Dialog anzeigen
    if not config.get_scan_folder():
        window.statusbar.showMessage(
            "Willkommen! Bitte wählen Sie zunächst einen Scan-Ordner aus."
        )

    # Anwendungsschleife starten
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
