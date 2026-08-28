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
from PyQt6.QtGui import QPixmap, QPalette, QColor, QIcon

from src.gui.main_window import MainWindow
from src.gui.setup_wizard import SetupWizard
from src.utils.config import get_config
from src.utils.logging_config import setup_logging, get_logger
from src.utils.single_instance import (
    SingleInstanceServer,
    try_send_to_running_instance,
)
from src.utils.explorer_integration import update_launcher_script

# Versionsnummer zentral definiert
__version__ = "0.18.0"


def _apply_wizard_result(window, config):
    """Aktualisiert das Hauptfenster nach dem Einrichtungs-Assistenten.

    Laedt die PDFs aus dem neu gesetzten Scan-Ordner und initialisiert den
    LLM-Provider neu, damit die Statusleiste den tatsaechlichen Zustand zeigt.
    Ohne diesen Aufruf bleibt der HybridClassifier des Hauptfensters auf dem
    Provider "none" haengen, mit dem er VOR dem Wizard gebaut wurde, und die
    Statusleiste zeigt "LLM: Aus" bis zum naechsten Neustart (Issue #65).
    Spiegelt den Ablauf von MainWindow.open_setup_wizard() fuer den
    nachtraeglichen Aufruf ueber das Menue.
    """
    if config.get_scan_folder():
        window.initial_load()
    window._on_settings_changed()


def _extract_path_arg(argv: list[str]) -> str:
    """
    Liefert das erste Argument, das auf einen existierenden Ordner ODER
    eine .pdf-Datei zeigt, oder einen leeren String. Damit kann der
    Explorer entweder einen geklickten Ordner oder eine geklickte PDF
    als positionales Argument uebergeben (siehe launcher.cmd).
    """
    for arg in argv[1:]:
        if not arg or arg.startswith("-"):
            continue
        try:
            p = Path(arg)
        except OSError:
            continue
        if not p.exists():
            continue
        if p.is_dir():
            return str(p.resolve())
        if p.is_file() and p.suffix.lower() == ".pdf":
            return str(p.resolve())
    return ""


def main():
    """Hauptfunktion - startet die Anwendung."""
    # Logging initialisieren (vor allem anderen!)
    setup_logging()
    logger = get_logger("main")
    logger.info(f"Version {__version__}")

    # Ggf. uebergebener Pfad aus Kommandozeile (Explorer-Kontextmenue):
    # entweder ein Ordner ODER eine .pdf-Datei.
    path_arg = _extract_path_arg(sys.argv)

    # Falls bereits eine Instanz laeuft, den Pfad dorthin schicken und
    # ohne UI beenden. Wenn kein Pfad uebergeben wurde, trotzdem
    # versuchen, die laufende Instanz nach vorne zu holen (leerer Pfad
    # signalisiert "nur aktivieren").
    if try_send_to_running_instance(path_arg):
        logger.info("Laufende Instanz benachrichtigt, beende Zweitstart.")
        sys.exit(0)

    # Launcher-Skript fuer das Explorer-Kontextmenue aktualisieren.
    # Das passiert bei jedem Start, damit der Registry-Eintrag stets auf
    # die aktuell verwendete .exe bzw. python-Installation zeigt.
    try:
        update_launcher_script()
    except Exception as e:
        logger.debug(f"Launcher-Skript konnte nicht aktualisiert werden: {e}")

    # High-DPI Skalierung aktivieren
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Anwendung erstellen
    app = QApplication(sys.argv)

    # App-Icon (Fenster + Taskleiste). Unter Windows zusaetzlich eine eigene
    # AppUserModelID setzen, sonst zeigt die Taskleiste im Dev-Modus das
    # Python-Icon statt unseres.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "JosiCreate.PDFSortierMeister"
            )
        except Exception:
            pass
    icon_candidates = [
        Path(getattr(sys, "_MEIPASS", src_path)) / "icon.png",
        src_path / "icon.png",
    ]
    icon_path = next((p for p in icon_candidates if p.exists()), None)
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setApplicationName("PDF Sortier Meister")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PDF Sortier Meister")

    # Helle Palette erzwingen, damit dunkle System-Themes die Lesbarkeit
    # nicht zerschiessen (siehe Issue #1). Fusion-Style sorgt fuer
    # plattformuebergreifend konsistentes Verhalten.
    app.setStyle("Fusion")
    light_palette = QPalette()
    light_palette.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
    light_palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
    light_palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    light_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
    light_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
    light_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
    light_palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
    light_palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
    light_palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
    light_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    light_palette.setColor(QPalette.ColorRole.Link, QColor(0, 102, 204))
    light_palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
    light_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    light_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 120, 120))
    app.setPalette(light_palette)

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

    # Single-Instance-Server starten: spaetere Aufrufe (Explorer-
    # Kontextmenue) kommen als folder_received-Signal hier an.
    instance_server = SingleInstanceServer(window)
    if instance_server.start():
        instance_server.folder_received.connect(window.handle_external_path)

    # Wurde ein Pfad als Argument uebergeben (Erststart aus dem
    # Explorer), den Scan-Ordner setzen. Ist das Argument eine PDF,
    # wird der enthaltende Ordner verwendet; die Auto-Selektion der
    # Datei passiert nach window.show() weiter unten.
    if path_arg:
        config = get_config()
        arg_path = Path(path_arg)
        scan_target = arg_path if arg_path.is_dir() else arg_path.parent
        config.set_scan_folder(str(scan_target))

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

        def show_startup_hints():
            # Erste-Schritte-Hinweis (Issue #51) vor dem Backup-Hinweis zeigen,
            # weil der Workflow wichtiger ist als die Backup-Erinnerung.
            window.show_first_steps_hint()
            window.show_backup_hint()

        # Hinweise erst zeigen, wenn der Splash weg ist
        QTimer.singleShot(300, show_startup_hints)

    window.thumbnails_loaded.connect(close_splash)
    QTimer.singleShot(15000, close_splash)

    # Beim ersten Start: Einrichtungs-Wizard anzeigen
    if not config.get_scan_folder():
        # Splash sofort schliessen: ohne Scan-Ordner feuert thumbnails_loaded
        # nie und der Splash laege 15s ueber dem Wizard (Issue #50)
        close_splash()
        wizard = SetupWizard(window)
        wizard.exec()
        # Nach dem Wizard: Hauptfenster mit neuem Scan-Ordner und LLM-Status
        # aktualisieren (Closes #65)
        _apply_wizard_result(window, config)

    # Update-Pruefung im Hintergrund, kurz nach dem Start (Issue #73).
    # Bewusst hier und nicht im MainWindow-Konstruktor, damit Tests und
    # Dialoge, die ein MainWindow erzeugen, keine Netzwerkzugriffe ausloesen.
    window.schedule_update_check()

    # Falls als Argument eine PDF-Datei uebergeben wurde, diese nach dem
    # initialen Laden auswaehlen und den Rename-Dialog oeffnen. Kurze
    # Verzoegerung, damit load_pdfs() die Widgets erstellt hat.
    if path_arg:
        arg_path = Path(path_arg)
        if arg_path.is_file() and arg_path.suffix.lower() == ".pdf":
            QTimer.singleShot(
                300,
                lambda p=arg_path: window.handle_external_path(str(p)),
            )

    # Anwendungsschleife starten
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
