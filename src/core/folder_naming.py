"""
Dateinamen aus der Ordnerstruktur aufbauen (Issue #42).

Beim Verschieben einer PDF wird der Dateiname nach einer konfigurierbaren
Vorlage aus dem Zielordner-Pfad neu aufgebaut, z.B.
"JK 069-03-05-20260512-Rechnung.pdf" fuer die Struktur
"JK 069-Umbau/JK 069-03-Firmen/JK 069-03-05-Rohbau".

Unterstuetzte Platzhalter:
    {initialen}      Initialen aus den Einstellungen (z.B. "JK")
    {ordnernummern}  Nummernkette aus dem Zielordner-Namen (z.B. "069-03-05")
    {ordnerpfad}     Ordnernamen des relativen Pfads, mit "-" verbunden
    {datum}          Dokumentdatum als YYYYMMDD (z.B. "20260512")
    {datum_iso}      Dokumentdatum als YYYY-MM-DD
    {text}           Bisheriger Dateiname ohne Datums-Praefix und Endung

GPL-3.0-or-later - Copyright (c) 2026
"""

import re
from datetime import date, datetime
from pathlib import PurePath
from typing import Any, Optional

DEFAULT_TEMPLATE = "{initialen} {ordnernummern}-{datum}-{text}"

# Windows-verbotene Zeichen in Dateinamen
_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*]')

# Fuehrende Datumsangabe im Dateinamen: "2026-05-12_..." oder "20260512-..."
_LEADING_DATE = re.compile(
    r"^(?P<date>(?P<y1>\d{4})-(?P<m1>\d{2})-(?P<d1>\d{2})|(?P<y2>\d{4})(?P<m2>\d{2})(?P<d2>\d{2}))[-_ ]*"
)

# Nummernkette in einem Ordnernamen: erste Folge von Zahlengruppen mit "-",
# z.B. "JK 069-03-05-Rohbau" -> "069-03-05"
_NUMBER_CHAIN = re.compile(r"\d+(?:-\d+)*")


def extract_folder_numbers(folder_name: str) -> str:
    """Extrahiert die Nummernkette aus einem Ordnernamen.

    "JK 069-03-05-Rohbau" -> "069-03-05"; "" wenn keine Zahlen vorkommen.
    """
    match = _NUMBER_CHAIN.search(folder_name)
    return match.group(0) if match else ""


def coerce_date(value: Any) -> Optional[date]:
    """Wandelt datetime/date in ein date um; alles andere ergibt None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def split_leading_date(name_stem: str) -> tuple[Optional[date], str]:
    """Trennt ein fuehrendes Datum vom restlichen Dateinamen.

    "2026-05-12_Rechnung Meier" -> (date(2026,5,12), "Rechnung Meier")
    """
    match = _LEADING_DATE.match(name_stem)
    if not match:
        return None, name_stem
    y = match.group("y1") or match.group("y2")
    m = match.group("m1") or match.group("m2")
    d = match.group("d1") or match.group("d2")
    try:
        parsed = date(int(y), int(m), int(d))
    except ValueError:
        return None, name_stem
    return parsed, name_stem[match.end():]


def _collapse_separators(name: str) -> str:
    """Entfernt doppelte/haengende Trenner, die durch leere Platzhalter entstehen."""
    name = re.sub(r"-{2,}", "-", name)
    name = re.sub(r"_{2,}", "_", name)
    name = re.sub(r" {2,}", " ", name)
    name = re.sub(r"[-_ ]*-[-_ ]*", "-", name)
    return name.strip(" -_")


def build_folder_based_name(
    current_name: str,
    target_folder: PurePath,
    relative_path: str,
    template: str = DEFAULT_TEMPLATE,
    initials: str = "",
    fallback_date: Optional[date] = None,
) -> str:
    """Baut den Dateinamen nach der Vorlage aus der Ordnerstruktur auf.

    Args:
        current_name: Bisheriger Dateiname (mit oder ohne ".pdf"), liefert
            {text} und - falls vorhanden - das Datum.
        target_folder: Zielordner (der tiefste Ordner liefert {ordnernummern}).
        relative_path: Relativer Pfad des Zielordners (fuer {ordnerpfad}).
        template: Vorlage mit Platzhaltern.
        initials: Wert fuer {initialen}.
        fallback_date: Datum falls der Dateiname keins enthaelt (z.B. aus dem
            Dokument erkannt). Ohne jedes Datum bleibt {datum} leer.

    Returns:
        Der neue Dateiname mit ".pdf"-Endung.
    """
    stem = current_name[:-4] if current_name.lower().endswith(".pdf") else current_name
    doc_date, text = split_leading_date(stem)
    if doc_date is None:
        doc_date = fallback_date

    folder_numbers = extract_folder_numbers(PurePath(target_folder).name)
    path_parts = [p for p in PurePath(relative_path).parts if p not in (".", "")]
    folder_path_text = "-".join(path_parts)

    values = {
        "initialen": initials.strip(),
        "ordnernummern": folder_numbers,
        "ordnerpfad": folder_path_text,
        "datum": doc_date.strftime("%Y%m%d") if doc_date else "",
        "datum_iso": doc_date.isoformat() if doc_date else "",
        "text": text.strip(),
    }

    try:
        name = template.format(**values)
    except (KeyError, IndexError, ValueError):
        # Unbekannter Platzhalter / kaputte Vorlage: Namen unveraendert lassen
        return stem + ".pdf" if stem else current_name

    name = _FORBIDDEN_CHARS.sub("", name)
    name = _collapse_separators(name)
    if not name:
        return stem + ".pdf" if stem else current_name
    return name + ".pdf"
