"""Tesseract-Suche (Qt-frei).

Wird vom PDF-Analyzer (``src/core/pdf_analyzer.py``) und von der
Dokumentensuche (``src/search``) gemeinsam genutzt. ``pdf_analyzer`` importiert
PyQt6, deshalb liegt die Suche hier, damit Hintergrunddienst, MCP-Server und
Arbeitsprozesse sie ohne Qt laden koennen.

Reihenfolge der Suche:
1. Mit der App gebuendelt (PyInstaller: ``<_internal>/tesseract/``)
2. Standard-Installationsorte (Windows: Programme / LocalAppData, macOS: Homebrew)
3. PATH

``sys.platform`` wird bewusst erst zur Aufrufzeit gelesen, damit Tests die
Plattform per monkeypatch simulieren koennen.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional
from src.i18n import tr


def _tesseract_candidates() -> list[Path]:
    """Moegliche Tesseract-Installationsorte in Prioritaetsreihenfolge."""
    exe_name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    candidates = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "tesseract" / exe_name)
    if sys.platform == "win32":
        for env_var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env_var)
            if not base:
                continue
            candidates.append(Path(base) / "Tesseract-OCR" / "tesseract.exe")
            if env_var == "LOCALAPPDATA":
                candidates.append(Path(base) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    elif sys.platform == "darwin":
        # Aus dem Finder gestartete Apps haben Homebrew nicht im PATH,
        # darum die Standardpfade explizit pruefen.
        candidates.append(Path("/opt/homebrew/bin/tesseract"))
        candidates.append(Path("/usr/local/bin/tesseract"))
    return candidates


def find_tesseract() -> Optional[str]:
    """Voller Pfad zur Tesseract-Binary oder None."""
    for candidate in _tesseract_candidates():
        if candidate.is_file():
            return str(candidate)
    return shutil.which("tesseract")


def tessdata_dir(tesseract_cmd: Optional[str]) -> Optional[str]:
    """Ordner mit den Sprachdaten zur angegebenen Binary, falls er sich finden laesst.

    Gebuendelt und bei der Windows-Standardinstallation liegt ``tessdata`` neben
    der Binary, bei Homebrew unter ``../share/tessdata``. Sonst None: Tesseract
    nutzt dann seinen eingebauten Standardpfad bzw. ``TESSDATA_PREFIX``.
    """
    if not tesseract_cmd:
        return None
    binary = Path(tesseract_cmd)
    for ordner in (binary.parent / "tessdata", binary.parent.parent / "share" / "tessdata"):
        if ordner.is_dir():
            return str(ordner)
    return None


def fehlende_sprachen(tessdata: str | None, sprachen: str) -> list[str]:
    """Sprachen aus ``deu+eng``, deren ``<sprache>.traineddata`` im Ordner fehlt.

    Leer, wenn der Ordner unbekannt ist (dann entscheidet Tesseract selbst)
    oder alle Sprachdaten vorhanden sind. Die Dokumentensuche schaltet die OCR
    bei fehlenden Daten aus und nennt den Grund im Status, statt jede Seite
    scheitern zu lassen.
    """
    if not tessdata or not os.path.isdir(tessdata):
        return []
    fehlt = []
    for s in sprachen.split("+"):
        s = s.strip()
        if s and not os.path.isfile(os.path.join(tessdata, s + ".traineddata")):
            fehlt.append(s)
    return fehlt


# --------------------------------------------------------------------------- Sprachen (Issue #47)

SPRACHNAMEN = {
    "deu": tr("Deutsch"),
    "eng": tr("Englisch"),
    "fra": tr("Französisch"),
    "ita": tr("Italienisch"),
    "spa": tr("Spanisch"),
    "nld": tr("Niederländisch"),
    "por": tr("Portugiesisch"),
    "pol": tr("Polnisch"),
    "ces": tr("Tschechisch"),
    "tur": tr("Türkisch"),
    "rus": tr("Russisch"),
    "dan": tr("Dänisch"),
    "swe": tr("Schwedisch"),
    "nor": tr("Norwegisch"),
    "fin": tr("Finnisch"),
    "hun": tr("Ungarisch"),
    "lat": tr("Latein"),
    "ell": tr("Griechisch"),
    "deu_frak": tr("Deutsch (Fraktur)"),
    "frk": tr("Fraktur (alt)"),
}
# Modelle, die keine Sprache zum Lesen sind
KEINE_SPRACHE = {"osd", "equ", "snum"}
FRAKTUR_MODELLE = ("deu_frak", "frk")
FRAKTUR_URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main/deu_frak.traineddata"


def sprachname(code: str) -> str:
    """Verstaendlicher deutscher Name zu einem Tesseract-Sprachcode (``deu_frak`` -> ``Deutsch (Fraktur)``)."""
    if code in SPRACHNAMEN:
        return SPRACHNAMEN[code]
    return " + ".join(SPRACHNAMEN.get(c, c) for c in code.split("+"))


def installierte_sprachen(tesseract_cmd: Optional[str], tessdata: Optional[str] = None) -> list[str]:
    """Installierte Sprachmodelle (``tesseract --list-langs``) ohne ``osd``/``equ``; leer ohne Tesseract.

    Antwortet Tesseract nicht, werden ersatzweise die ``*.traineddata`` im
    Ordner ``tessdata`` gelesen (falls bekannt).
    """
    import subprocess

    codes: list[str] = []
    if tesseract_cmd:
        args = [tesseract_cmd, "--list-langs"]
        if tessdata:
            args += ["--tessdata-dir", tessdata]
        kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        try:
            r = subprocess.run(args, capture_output=True, timeout=20, **kw)
            if r.returncode == 0:
                text = r.stdout.decode("utf-8", "replace")
                # Erste Zeile: 'List of available languages in "<Pfad>" (n):'
                codes = [z.strip() for z in text.splitlines()[1:] if z.strip()]
        except (OSError, subprocess.SubprocessError):
            codes = []
    if not codes and tessdata and os.path.isdir(tessdata):
        codes = sorted(f[:-len(".traineddata")] for f in os.listdir(tessdata) if f.endswith(".traineddata"))
    return [c for c in codes if c not in KEINE_SPRACHE]


def sprachwahl(installiert: list[str]) -> list[tuple[str, str]]:
    """Angebote fuer "OCR wiederholen mit ...": ``[(Sprachcode(s), Name), ...]``.

    Zuerst sinnvolle Kombinationen (``deu+eng``, Fraktur mit Deutsch), dann
    jede installierte Sprache einzeln. Nur Modelle, die wirklich da sind.
    """
    have = set(installiert)
    erg: list[tuple[str, str]] = []

    def kombi(*codes: str) -> None:
        if all(c in have for c in codes):
            code = "+".join(codes)
            erg.append((code, sprachname(code)))

    kombi("deu", "eng")
    for frak in FRAKTUR_MODELLE:
        kombi(frak, "deu")
    schon = {code for code, _ in erg}
    for c in installiert:
        if c not in schon:
            erg.append((c, sprachname(c)))
    return erg


def hat_fraktur(installiert: list[str]) -> bool:
    """Ist ein Fraktur-Modell installiert?"""
    return any(m in installiert for m in FRAKTUR_MODELLE)


def fraktur_hinweis(tessdata: Optional[str]) -> str:
    """Anleitung, das Fraktur-Modell selbst zu installieren (es wird nie automatisch geladen)."""
    ziel = tessdata or tr("dem Ordner „tessdata“ der Tesseract-Installation")
    return (
        tr(
            "Für Frakturschrift fehlt das Tesseract-Modell „deu_frak“.\n\n"
            "So installieren Sie es:\n1. Laden Sie die Datei deu_frak.traineddata herunter:\n"
            "   {FRAKTUR_URL}\n2. Legen Sie sie in diesen Ordner:\n"
            "   {ziel}\n   (unter Windows braucht das Kopieren nach „Programme“ ggf. "
            "Administratorrechte)\n3. Danach erscheint „Deutsch (Fraktur)“ im Menü „OCR "
            "wiederholen mit …“.\n\nEs wird nichts automatisch heruntergeladen."
        ).format(FRAKTUR_URL=FRAKTUR_URL, ziel=ziel)
    )
