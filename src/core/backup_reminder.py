"""Backup-Erinnerung (Issue #14): Faelligkeitslogik ohne GUI-Abhaengigkeit.

Konfiguration (src/utils/config.py):
- backup_check_days: Abstand in Tagen, 0 = Erinnerung aus
- backup_last_confirmed: ISO-Datum des zuletzt bestaetigten Backups ("" = nie)
- backup_pending: True, wenn der Nutzer "Nein" geantwortet hat; der Statusleisten-
  Hinweis bleibt, bis er "Backup jetzt gemacht" bestaetigt
"""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

MACRIUM_LOG_DIR = Path(r"C:\ProgramData\Macrium\Reflect")


def macrium_last_backup(log_dir: Path = MACRIUM_LOG_DIR) -> Optional[datetime]:
    """Zeitstempel der neuesten Macrium-Reflect-Logdatei (*.html), rein lesend.

    Jeder Lauf schreibt ein Log; als grober Hinweis auf ein Backup genuegt der
    Datei-Zeitstempel. Bei jedem Fehler oder ohne Macrium: None.
    """
    try:
        newest = max(
            (p.stat().st_mtime for p in Path(log_dir).glob("*.html")),
            default=None,
        )
        return datetime.fromtimestamp(newest) if newest is not None else None
    except OSError:
        return None


def parse_date(value) -> Optional[datetime]:
    """ISO-String -> datetime, bei leer/ungueltig None."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_question_due(
    days,
    last_confirmed: Optional[datetime],
    pending: bool = False,
    macrium_last: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Soll jetzt die Frage "Backup gemacht?" gestellt werden?

    Nein bei: Erinnerung aus (days <= 0), offenem Hinweis (pending, wird per
    Statusleiste geklaert), bestaetigtem Backup oder Macrium-Log juenger als
    `days` Tage.
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        return False
    if days <= 0 or pending:
        return False
    now = now or datetime.now()
    limit = timedelta(days=days)
    for stamp in (last_confirmed, macrium_last):
        if stamp is not None and now - stamp < limit:
            return False
    return True
