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

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

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

    # Konfiguration laden
    config = get_config()

    # Hauptfenster erstellen und anzeigen
    window = MainWindow()
    window.show()

    # Beim ersten Start: Scan-Ordner Dialog anzeigen
    if not config.get_scan_folder():
        window.statusbar.showMessage(
            "Willkommen! Bitte wählen Sie zunächst einen Scan-Ordner aus."
        )

    # Anwendungsschleife starten
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
