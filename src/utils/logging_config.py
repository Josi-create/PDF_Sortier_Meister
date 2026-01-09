"""
Zentrales Logging-System für PDF Sortier Meister

Konfiguriert das Python logging-Modul für die gesamte Anwendung.
Logs werden sowohl in die Konsole als auch in eine Datei geschrieben.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler


# Globale Logger-Instanz
_logger: logging.Logger | None = None


def get_log_directory() -> Path:
    """Gibt das Log-Verzeichnis zurück (im AppData-Ordner)."""
    app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
    log_dir = Path(app_data) / "PDF_Sortier_Meister" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logging(
    level: int = logging.INFO,
    console_output: bool = True,
    file_output: bool = True,
    max_file_size: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 3,
) -> logging.Logger:
    """
    Konfiguriert das Logging-System.

    Args:
        level: Minimales Log-Level (default: INFO)
        console_output: Logs auch in Konsole ausgeben
        file_output: Logs in Datei schreiben
        max_file_size: Maximale Größe einer Log-Datei in Bytes
        backup_count: Anzahl der Backup-Dateien

    Returns:
        Konfigurierter Root-Logger
    """
    global _logger

    # Root-Logger für die Anwendung
    logger = logging.getLogger("pdf_sortier_meister")
    logger.setLevel(level)

    # Vorhandene Handler entfernen (für Rekonfiguration)
    logger.handlers.clear()

    # Format für Log-Nachrichten
    detailed_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    simple_format = logging.Formatter(
        "%(levelname)-8s | %(message)s"
    )

    # Konsolen-Handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(simple_format)
        logger.addHandler(console_handler)

    # Datei-Handler mit Rotation
    if file_output:
        log_dir = get_log_directory()
        log_file = log_dir / "pdf_sortier_meister.log"

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)  # Datei bekommt mehr Details
        file_handler.setFormatter(detailed_format)
        logger.addHandler(file_handler)

        # Erste Log-Nachricht mit Startzeit
        logger.info(f"=== PDF Sortier Meister gestartet ===")
        logger.debug(f"Log-Datei: {log_file}")

    _logger = logger
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    Gibt einen Logger zurück.

    Args:
        name: Name des Loggers (für Modul-spezifische Logs).
              None für den Haupt-Logger.

    Returns:
        Logger-Instanz
    """
    global _logger

    if _logger is None:
        setup_logging()

    if name:
        return logging.getLogger(f"pdf_sortier_meister.{name}")
    return _logger


def log_exception(logger: logging.Logger, exc: Exception, context: str = ""):
    """
    Loggt eine Exception mit vollständigem Traceback.

    Args:
        logger: Logger-Instanz
        exc: Die Exception
        context: Optionaler Kontext (z.B. "beim Laden der PDF")
    """
    if context:
        logger.error(f"{context}: {type(exc).__name__}: {exc}", exc_info=True)
    else:
        logger.error(f"{type(exc).__name__}: {exc}", exc_info=True)


def get_log_file_path() -> Path:
    """Gibt den Pfad zur aktuellen Log-Datei zurück."""
    return get_log_directory() / "pdf_sortier_meister.log"


def get_recent_logs(lines: int = 100) -> str:
    """
    Liest die letzten Zeilen aus der Log-Datei.

    Args:
        lines: Anzahl der Zeilen

    Returns:
        Log-Inhalt als String
    """
    log_file = get_log_file_path()
    if not log_file.exists():
        return "Keine Log-Datei gefunden."

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except Exception as e:
        return f"Fehler beim Lesen der Logs: {e}"


# Convenience-Funktionen für häufige Log-Kategorien
def log_pdf_operation(action: str, pdf_path: Path, details: str = ""):
    """Loggt eine PDF-Operation."""
    logger = get_logger("pdf")
    msg = f"{action}: {pdf_path.name}"
    if details:
        msg += f" | {details}"
    logger.info(msg)


def log_llm_request(provider: str, success: bool, details: str = ""):
    """Loggt eine LLM-Anfrage."""
    logger = get_logger("llm")
    status = "OK" if success else "FEHLER"
    msg = f"[{provider}] {status}"
    if details:
        msg += f" | {details}"
    if success:
        logger.info(msg)
    else:
        logger.warning(msg)


def log_user_action(action: str, details: str = ""):
    """Loggt eine Benutzeraktion."""
    logger = get_logger("user")
    msg = action
    if details:
        msg += f" | {details}"
    logger.info(msg)
