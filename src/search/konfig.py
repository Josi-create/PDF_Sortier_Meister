"""Konfiguration der Dokumentensuche (Qt-frei).

``SearchConfig`` ist die eine Konfigurations-Dataclass des Moduls. PDF Sortier
Meister haelt sie im Block ``"suche"`` seiner ``config.json``
(``Config.get_search_config()``). Die ``config.toml`` des frueheren, eigenstaendigen
Programms PDFsuche wird fuer die Uebernahme gelesen (``lade_config_toml``).

Keine persoenlichen Pfade: alle Standardwerte werden aus der Plattform bzw. aus
der PDFSM-Konfiguration (Scan- und Zielordner) abgeleitet.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from src.utils.platform_paths import get_app_data_dir

# Stufen fuer „OCR-Text als Textebene in die PDF schreiben“ (Phase 5b):
# aus | nur neue Scans im ersten Vorrang-Ordner | alle (Altbestand, nur auf Wunsch)
TEXTEBENE_STUFEN = ("aus", "neue_scans", "alle")

STANDARD_ENDUNGEN = (
    ".pdf", ".md", ".eml", ".msg", ".docx", ".docm", ".doc", ".xlsx", ".xlsm", ".xls", ".odt",
)

# Ordnernamen, die ueberall uebersprungen werden (Gross-/Kleinschreibung egal).
# Windows- und macOS-Systemordner stehen gemeinsam in der Liste; was es auf der
# jeweiligen Plattform nicht gibt, stoert nicht.
STANDARD_ORDNER_AUSSCHLIESSEN = (
    "$Recycle.Bin", "System Volume Information", "$WinREAgent", "Recovery",
    "Windows", "WindowsApps", "AppData", "ProgramData",
    "Program Files", "Program Files (x86)",
    "Library", ".Trash", ".Trashes", ".Spotlight-V100", ".fseventsd",
    "node_modules", ".git", ".svn", ".hg", ".venv", "venv", "site-packages",
    "__pycache__", ".cache", ".npm", ".cargo", ".rustup", ".gradle", ".m2",
    ".nuget", ".vscode", ".idea", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
)


def norm_pfad(p: str) -> str:
    """Pfad in Betriebssystemschreibweise ohne abschliessenden Trenner.

    Laufwerkswurzeln unter Windows behalten den Backslash (``E:\\``), damit
    ``os.scandir`` das Laufwerk und nicht das aktuelle Verzeichnis liest.
    """
    p = os.path.normpath(str(p).strip())
    if sys.platform == "win32" and len(p) == 2 and p[1] == ":":
        p += "\\"
    return p


def _endung(e: str) -> str:
    e = str(e).strip().lower()
    return e if e.startswith(".") else "." + e


@dataclass
class SearchConfig:
    """Alle Einstellungen der Dokumentensuche.

    Attributes:
        aktiv: Suche eingerichtet (Assistent oder Uebernahme durchlaufen)?
        db_pfad: Datenbankdatei; leer = ``get_app_data_dir()/suche/suche.db``.
            Bei der Uebernahme einer PDFsuche zeigt der Wert auf die bisherige Datei.
        wurzeln: Ordner bzw. Laufwerke, die vollstaendig durchsucht werden.
        prioritaet: Vorrang-Ordner, bei jedem Lauf zuerst; neue Scans im ersten
            Ordner werden sofort texterkannt.
        endungen: Dateiendungen, die aufgenommen werden.
        ordner_ausschliessen: Ordnernamen, die ueberall uebersprungen werden.
        pfade_ausschliessen: vollstaendige Pfade, die uebersprungen werden.
        cloud_herunterladen: Nur in der Cloud liegende Dateien (OneDrive, iCloud)
            herunterladen? Sonst nur mit Namen aufnehmen.
        max_dateigroesse_mb: groessere Dateien werden nur mit Namen aufgenommen.
        mails_aktiv / mail_ordner: Thunderbird-Postfaecher (mbox).
        ocr_*: Texterkennung; ``ocr_tesseract`` leer = automatisch suchen.
        prozesse: Arbeitsprozesse (0 = halbe Kernzahl, hoechstens 8).
        hintergrund_*: taegliche Hintergrundindexierung (Aufgabenplanung / LaunchAgent).
        web_*: Browser-Oberflaeche (nur 127.0.0.1).
        textebene: OCR-Text als unsichtbare Textebene in die PDF schreiben
            (``TEXTEBENE_STUFEN``: ``aus``, ``neue_scans`` = nur Scans, die im
            ersten Vorrang-Ordner erkannt werden, ``alle`` = auch der
            Altbestand); ``textebene_sicherung_tage``: Aufbewahrung der
            Sicherungskopien (0 = unbegrenzt); ``textebene_sicherung_ordner``:
            leer = ``get_app_data_dir()/suche/textebene_sicherung``.
            Umsetzung in ``textebene.py`` (Phase 5b).
    """

    aktiv: bool = False
    db_pfad: str = ""
    wurzeln: list[str] = field(default_factory=list)
    prioritaet: list[str] = field(default_factory=list)
    endungen: set[str] = field(default_factory=lambda: set(STANDARD_ENDUNGEN))
    ordner_ausschliessen: set[str] = field(
        default_factory=lambda: {n.lower() for n in STANDARD_ORDNER_AUSSCHLIESSEN}
    )
    pfade_ausschliessen: set[str] = field(default_factory=set)
    cloud_herunterladen: bool = False
    max_dateigroesse_mb: int = 500
    mails_aktiv: bool = False
    mail_ordner: list[str] = field(default_factory=list)
    ocr_aktiv: bool = True
    ocr_tesseract: str = ""
    ocr_tessdata: str = ""
    ocr_sprachen: str = "deu+eng"
    ocr_dpi: int = 300
    ocr_min_zeichen: int = 25
    ocr_max_seiten: int = 1000
    prozesse: int = 0
    hintergrund_aktiv: bool = False
    hintergrund_uhrzeit: str = "03:00"
    web_aktiv: bool = False
    web_bei_anmeldung: bool = False
    web_host: str = "127.0.0.1"
    web_port: int = 18425
    textebene: str = "aus"
    textebene_sicherung_tage: int = 30
    textebene_sicherung_ordner: str = ""

    def __post_init__(self) -> None:
        if self.textebene not in TEXTEBENE_STUFEN:
            self.textebene = "aus"
        self.textebene_sicherung_tage = max(0, int(self.textebene_sicherung_tage))
        self.wurzeln = [norm_pfad(p) for p in self.wurzeln if str(p).strip()]
        self.prioritaet = [norm_pfad(p) for p in self.prioritaet if str(p).strip()]
        self.mail_ordner = [norm_pfad(p) for p in self.mail_ordner if str(p).strip()]
        self.endungen = {_endung(e) for e in self.endungen if str(e).strip()}
        self.ordner_ausschliessen = {str(n).strip().lower() for n in self.ordner_ausschliessen}
        self.pfade_ausschliessen = {
            norm_pfad(p).lower() for p in self.pfade_ausschliessen if str(p).strip()
        }
        self.db_pfad = norm_pfad(self.db_pfad) if str(self.db_pfad).strip() else ""
        self.textebene_sicherung_ordner = (norm_pfad(self.textebene_sicherung_ordner)
                                           if str(self.textebene_sicherung_ordner).strip() else "")

    # ------------------------------------------------------------------ Ableitungen

    @property
    def db_datei(self) -> Path:
        """Datenbankdatei (``suche.db``)."""
        if self.db_pfad:
            return Path(self.db_pfad)
        return get_app_data_dir() / "suche" / "suche.db"

    @property
    def daten_ordner(self) -> Path:
        """Ordner der Datenbank; dort liegt auch die Sperrdatei ``indexer.lock``."""
        return self.db_datei.parent

    @property
    def sicherung_ordner(self) -> Path:
        """Ordner der Sicherungskopien, bevor die Textebene eine PDF aendert (Phase 5b)."""
        if self.textebene_sicherung_ordner:
            return Path(self.textebene_sicherung_ordner)
        return get_app_data_dir() / "suche" / "textebene_sicherung"

    def textebene_erzeugen(self, pfad: str) -> bool:
        """Soll die OCR dieser Datei die Textebene gleich mitliefern (``extract.pdf_ocr``, ``cfg["textebene"]``)?

        ``alle``: jede PDF. ``neue_scans``: nur Dateien im ersten Vorrang-Ordner
        (dort landen frische Scans). ``aus``: nie.
        """
        if self.textebene == "alle":
            return True
        if self.textebene != "neue_scans" or not self.prioritaet:
            return False
        ordner = os.path.normcase(self.prioritaet[0]).rstrip("\\/")
        datei = os.path.normcase(norm_pfad(pfad))
        return datei.startswith(ordner + os.sep) or datei.startswith(ordner + "/")

    @property
    def log_ordner(self) -> Path:
        return get_app_data_dir() / "logs"

    @property
    def max_dateigroesse(self) -> int:
        """Obergrenze in Bytes."""
        return int(self.max_dateigroesse_mb) * 1024 * 1024

    @property
    def anzahl_prozesse(self) -> int:
        if self.prozesse > 0:
            return int(self.prozesse)
        return max(1, min(8, (os.cpu_count() or 2) // 2))

    def mail_ordner_effektiv(self) -> list[str]:
        """Postfach-Ordner fuer den Lauf: die konfigurierten, sonst ``Mail/`` und
        ``ImapMail/`` des Thunderbird-Standardprofils (``plattform.thunderbird_mail_ordner``)."""
        if self.mail_ordner:
            return list(self.mail_ordner)
        from src.search.plattform import thunderbird_mail_ordner

        return [norm_pfad(p) for p in thunderbird_mail_ordner()]

    def ocr_einstellungen(self) -> dict:
        """Einstellungen fuer ``extract.pdf_ocr`` (picklebar, fuer die Arbeitsprozesse).

        Ohne auffindbares Tesseract oder ohne die Sprachdaten (``deu+eng``) ist
        ``aktiv`` False und ``grund`` nennt die Ursache (Protokoll, Status); der
        Lauf laesst die Seiten dann auf ``ohne_text`` stehen und holt die OCR
        spaeter nach.
        """
        from src.utils.tesseract import fehlende_sprachen, find_tesseract, tessdata_dir

        tesseract = self.ocr_tesseract or find_tesseract()
        tessdata = self.ocr_tessdata or tessdata_dir(tesseract)
        sprachen = self.ocr_sprachen or "deu+eng"
        fehlend = fehlende_sprachen(tessdata, sprachen) if tesseract else []
        if not self.ocr_aktiv:
            grund = "in den Einstellungen ausgeschaltet"
        elif not tesseract:
            grund = "Tesseract nicht gefunden"
        elif fehlend:
            grund = "Sprachdaten fehlen: " + ", ".join(fehlend)
        else:
            grund = None
        return {
            "aktiv": grund is None,
            "grund": grund,
            "tesseract": tesseract,
            "tessdata": tessdata or None,
            "sprachen": sprachen,
            "dpi": int(self.ocr_dpi),
            "min_zeichen": int(self.ocr_min_zeichen),
            "max_seiten": int(self.ocr_max_seiten),
        }

    # ------------------------------------------------------------------ JSON

    def als_dict(self) -> dict:
        """JSON-faehige Darstellung fuer ``config.json`` (Mengen als sortierte Listen)."""
        d = asdict(self)
        for k in ("endungen", "ordner_ausschliessen", "pfade_ausschliessen"):
            d[k] = sorted(d[k])
        return d

    @classmethod
    def aus_dict(cls, d: dict | None) -> SearchConfig:
        """Aus dem ``"suche"``-Block der ``config.json``; unbekannte Schluessel werden ignoriert."""
        d = d or {}
        vorlage = cls()
        werte = {}
        for f in fields(cls):
            if f.name not in d or d[f.name] is None:
                continue
            werte[f.name] = _umwandeln(d[f.name], type(getattr(vorlage, f.name)))
        return cls(**werte)


def _umwandeln(wert, ziel: type):
    if ziel is bool:
        if isinstance(wert, str):
            return wert.strip().lower() in ("1", "true", "ja", "yes", "wahr")
        return bool(wert)
    if ziel is int:
        return int(wert)
    if ziel is list:
        return [str(x) for x in ([wert] if isinstance(wert, str) else wert)]
    if ziel is set:
        return {str(x) for x in ([wert] if isinstance(wert, str) else wert)}
    return str(wert)


# ---------------------------------------------------------------------- Laden

def lade_config_toml(pfad: str | Path) -> SearchConfig:
    """``config.toml`` des frueheren Programms PDFsuche in eine ``SearchConfig`` ueberfuehren."""
    import tomllib

    with open(pfad, "rb") as f:
        raw = tomllib.load(f)
    s = raw.get("suche", {})
    o = raw.get("ocr", {})
    w = raw.get("web", {})
    mail_ordner = list(raw.get("thunderbird", {}).get("mail_ordner", []))
    return SearchConfig(
        aktiv=True,
        db_pfad=str(raw.get("datenbank", {}).get("pfad", "")),
        prioritaet=list(s.get("prioritaet", [])),
        wurzeln=list(s.get("wurzeln", [])),
        endungen=set(s.get("endungen", STANDARD_ENDUNGEN)),
        ordner_ausschliessen=set(s.get("ordner_ausschliessen", STANDARD_ORDNER_AUSSCHLIESSEN)),
        pfade_ausschliessen=set(s.get("pfade_ausschliessen", [])),
        cloud_herunterladen=bool(s.get("cloud_dateien_herunterladen", False)),
        max_dateigroesse_mb=int(s.get("max_dateigroesse_mb", 500)),
        mails_aktiv=bool(mail_ordner),
        mail_ordner=mail_ordner,
        ocr_aktiv=bool(o.get("aktiv", True)),
        ocr_tesseract=str(o.get("tesseract", "")),
        ocr_tessdata=str(o.get("tessdata", "")),
        ocr_sprachen=str(o.get("sprachen", "deu+eng")),
        ocr_dpi=int(o.get("dpi", 300)),
        ocr_min_zeichen=int(o.get("min_zeichen_pro_seite", 25)),
        ocr_max_seiten=int(o.get("max_seiten", 1000)),
        prozesse=int(raw.get("leistung", {}).get("prozesse", 0)),
        web_host=str(w.get("host", "127.0.0.1")),
        web_port=int(w.get("port", 18425)),
    )


def lade(pfad: str | None = None) -> SearchConfig:
    """Konfiguration fuer Dienst, MCP und Web laden.

    ``pfad`` endet auf ``.toml``: alte PDFsuche-Konfiguration. Sonst die
    ``config.json`` von PDF Sortier Meister (``pfad`` = andere Datei, leer =
    Standardort), Block ``"suche"``.
    """
    if pfad and str(pfad).lower().endswith(".toml"):
        return lade_config_toml(pfad)
    from src.utils.config import Config, get_config

    cfg = Config(pfad) if pfad else get_config()
    return cfg.get_search_config()
