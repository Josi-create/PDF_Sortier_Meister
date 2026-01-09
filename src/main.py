"""
PDF Sortier Meister - Haupteinstiegspunkt

Ein intelligentes Programm zum Sortieren und Umbenennen von gescannten PDFs.
"""

import sys
from pathlib import Path

# Füge src zum Pfad hinzu für relative Imports
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from src.gui.main_window import MainWindow
from src.utils.config import get_config


def main():
    """Hauptfunktion - startet die Anwendung."""
    # High-DPI Skalierung aktivieren
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Anwendung erstellen
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Sortier Meister")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("PDF Sortier Meister")

    # SplashScreen anzeigen
    splash_path = src_path / "SplashScreen3.png"
    splash = None
    if splash_path.exists():
        pixmap = QPixmap(str(splash_path))
        # Bild auf halbe Größe skalieren
        scaled_pixmap = pixmap.scaled(
            pixmap.width() // 2,
            pixmap.height() // 2,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        splash = QSplashScreen(scaled_pixmap)
        # Immer im Vordergrund halten
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

    # SplashScreen schließen wenn Thumbnails geladen sind
    if splash:
        def close_splash():
            splash.close()
            window.raise_()
            window.activateWindow()
        window.thumbnails_loaded.connect(close_splash)

    # Beim ersten Start: Scan-Ordner Dialog anzeigen
    if not config.get_scan_folder():
        window.statusbar.showMessage(
            "Willkommen! Bitte wählen Sie zunächst einen Scan-Ordner aus."
        )

    # Anwendungsschleife starten
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
