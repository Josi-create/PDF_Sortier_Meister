"""Word-/Excel-Dateien (.docx, .odt, .xlsx) in PDF umwandeln (Issue #9) - Qt-frei.

Die Originaldatei bleibt unveraendert; das PDF entsteht daneben.

Druckdatum (Briefe)
-------------------
Viele Briefe tragen ein Datumsfeld, das sich beim Drucken aktualisiert
(``PRINTDATE``, ``DATE``, ``TIME``). Beim Umwandeln wuerde Word dort das Datum
der Umwandlung einsetzen. Deshalb wird vor der Umwandlung eine temporaere
Kopie der .docx gebaut, in der diese Felder durch festen Text ersetzt sind: das
Datum aus der Core-Property ``lastPrinted`` (docProps/core.xml), im Format des
Feldschalters (``\\@ "dddd, d. MMMM yyyy"``), deutsch ausgeschrieben. Fehlt
``lastPrinted``, gilt ersatzweise ``modified``, dann ``created``, zuletzt die
Aenderungszeit der Datei. Die Quelle steht im Ergebnis (``datum_quelle``).
Andere Felder (SEITE, SEQ, HYPERLINK, SAVEDATE, CREATEDATE ...) bleiben.

OpenDocument-Text (.odt) wird wie .docx behandelt. Gegenstueck zu den Word-Feldern
sind die ODF-Felder ``text:date``, ``text:time``, ``text:print-date`` und
``text:print-time`` in ``content.xml`` und ``styles.xml`` (Kopf-/Fusszeilen), soweit
sie nicht ``text:fixed="true"`` tragen. Sie werden in der temporaeren Kopie durch
festen Text ersetzt. Datum aus ``meta.xml``: ``meta:print-date`` (als "lastPrinted"
gemeldet), sonst ``dc:date`` ("modified"), ``meta:creation-date`` ("created"),
zuletzt die Dateizeit. Das Anzeigeformat leitet sich aus dem Datenstil des Felds
(``number:date-style`` / ``number:time-style``) ab; fehlt er, gilt ``dd.MM.yyyy``
bzw. ``HH:mm:ss``. Die Namen kommen wie bei .docx deutsch ausgeschrieben.
Bewusst nicht angefasst: ``text:modification-date``, ``text:creation-date`` und
Verwandte - sie zeigen feste Metadaten, kein "jetzt".

Umwandlung
----------
1. Microsoft Word bzw. Excel
   - Windows: per COM (pywin32), in einer eigenen unsichtbaren Programminstanz -
     ein offenes Word des Nutzers bleibt unberuehrt.
   - macOS: per AppleScript (``osascript``). Word/Excel sind dort sandboxed und
     duerfen nur ihren eigenen Container frei lesen/schreiben; die Kopie liegt
     darum unter ``~/Library/Containers/com.microsoft.<App>/Data/tmp`` und
     traegt einen eindeutigen Namen, damit nie ein gleichnamiges, vom Nutzer
     geoeffnetes Dokument getroffen wird. War das Programm vorher nicht offen,
     startet es versteckt und wird danach wieder beendet. Beim ersten Mal
     fragt macOS, ob PDF Sortier Meister Word/Excel steuern darf.
2. Rueckfall: LibreOffice headless (``soffice``).
3. Mac: Apple Pages (.docx) bzw. Numbers (.xlsx), per AppleScript wie Word,
   Arbeitskopie im Container des Programms. Zuletzt, weil sie ein Fenster
   oeffnen und kein PDF/A koennen.
4. Ist nichts davon da, gibt es ``KeinUmwandlerGefunden`` mit klarer Meldung.

PDF/A: Word per ``ExportAsFixedFormat(UseISO19005_1=True)`` (Stufe B),
LibreOffice per ``SelectPdfVersion`` (PDF/A-2b). Excel (COM) und Word/Excel auf
dem Mac koennen das nicht; dort wird bei PDF/A LibreOffice bevorzugt, sonst
gibt es ein normales PDF samt Hinweis.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape as _xml_escape
from xml.sax.saxutils import unescape as _xml_unescape
from src.i18n import tr

WORD_ENDUNGEN = (".docx", ".odt")  # .odt (OpenDocument-Text) wird wie .docx behandelt
EXCEL_ENDUNGEN = (".xlsx",)
OFFICE_ENDUNGEN = WORD_ENDUNGEN + EXCEL_ENDUNGEN

# Felder, die beim Umwandeln auf "jetzt" springen wuerden
DATUMSFELDER = ("PRINTDATE", "DATE", "TIME")

MONATE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)
WOCHENTAGE = (  # datetime.weekday(): Montag = 0
    "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag",
)
STANDARD_BILD = "dd.MM.yyyy"

LIBREOFFICE_TIMEOUT_S = 180
MAX_TEIL = 50_000_000  # groesster zu pruefender XML-Teil (Schutz gegen ZIP-Bomben)


class UmwandlungFehler(Exception):
    """Umwandlung fehlgeschlagen (Grund im Text, deutsch)."""


class KeinUmwandlerGefunden(UmwandlungFehler):
    """Weder Word/Excel (COM) noch LibreOffice sind verfuegbar."""


@dataclass
class UmwandlungsErgebnis:
    pdf: Path
    werkzeug: str  # "Word", "Excel", "LibreOffice", "Pages" oder "Numbers"
    datum: Optional[datetime] = None  # nur .docx/.odt: eingesetztes Datum der Datumsfelder
    datum_quelle: Optional[str] = None  # "lastPrinted", "modified", "created" oder "Dateizeit"
    ersetzte_felder: int = 0
    pdfa: bool = False  # PDF/A tatsaechlich erzeugt
    hinweise: list[str] = field(default_factory=list)


def ist_office_datei(pfad: Path | str) -> bool:
    """Sortierbare Nicht-PDF-Datei: .docx/.odt/.xlsx und seit Issue #184 auch Bilder.

    Sie erscheinen als eigene Kachel, tragen keine PDF-Metadaten und lassen
    sich in PDF umwandeln (Bilder: ``bild_convert``).
    """
    from src.core.bild_convert import ist_bild_datei

    return Path(pfad).suffix.lower() in OFFICE_ENDUNGEN or ist_bild_datei(pfad)


def sortierbare_endungen() -> tuple[str, ...]:
    """Endungen aller Nicht-PDF-Dateien, die als Kachel erscheinen (Office und Bilder)."""
    from src.core.bild_convert import bild_endungen

    return OFFICE_ENDUNGEN + bild_endungen()


def ist_sortierbar(pfad: Path | str) -> bool:
    """PDF, Office-Datei oder Bild: darf in Zielordner verschoben/abgelegt werden."""
    return Path(pfad).suffix.lower() == ".pdf" or ist_office_datei(pfad)


def endung_tauschen(name: str, endung: str) -> str:
    """Setzt ``endung`` (z. B. ".docx") an den Namen; ein ".pdf" oder dieselbe Endung davor entfaellt."""
    for alt in (".pdf", endung):
        if name.lower().endswith(alt.lower()):
            name = name[: -len(alt)]
            break
    return name + endung


# --- Datum aus den Dokumenteigenschaften ------------------------------------

def _parse_iso(text: str) -> Optional[datetime]:
    """'2015-05-08T20:46:00Z' -> naives datetime (Word schreibt Ortszeit mit 'Z')."""
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?)?", text or "")
    if not m:
        return None
    jahr, monat, tag, std, minute, sek = (int(g) if g else 0 for g in m.groups())
    try:
        return datetime(jahr, monat, tag, std, minute, sek)
    except ValueError:
        return None


def druckdatum(docx: Path | str) -> tuple[datetime, str]:
    """Datum fuer die Datumsfelder: lastPrinted, sonst modified, created, Dateizeit.

    Bei .odt aus ``meta.xml`` (print-date, dc:date, creation-date), gleiche Quellennamen.
    """
    docx = Path(docx)
    if docx.suffix.lower() == ".odt":
        return _odt_druckdatum(docx)
    core = ""
    try:
        with zipfile.ZipFile(docx) as z:
            core = z.read("docProps/core.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile, OSError):
        pass
    for tag, name in (
        ("cp:lastPrinted", "lastPrinted"),
        ("dcterms:modified", "modified"),
        ("dcterms:created", "created"),
    ):
        m = re.search(rf"<{tag}\b[^>]*>([^<]*)</{tag}>", core)
        if m:
            dt = _parse_iso(m.group(1))
            # Word schreibt fuer "nie gedruckt" gelegentlich 0001-01-01
            if dt and dt.year > 1900:
                return dt, name
    return datetime.fromtimestamp(docx.stat().st_mtime), "Dateizeit"


# --- Word-Datumsbild (\@ "dddd, d. MMMM yyyy") -------------------------------

_BILD_TOKEN = re.compile(
    r"'[^']*'|AM/PM|am/pm|A/P|a/p|d{1,4}|M{1,4}|y{1,4}|H{1,2}|h{1,2}|m{1,2}|s{1,2}|\\.|.",
    re.DOTALL,
)


def formatiere_datum(dt: datetime, bild: str) -> str:
    """Formatiert nach einem Word-Datumsbild, deutsch (Monats-/Wochentagsnamen)."""
    out: list[str] = []
    for tok in _BILD_TOKEN.findall(bild):
        c = tok[0]
        if tok in ("AM/PM", "am/pm", "A/P", "a/p"):
            s = "AM" if dt.hour < 12 else "PM"
            if tok.upper() == "A/P":
                s = s[0]
            out.append(s.lower() if tok.islower() else s)
        elif c == "'":
            out.append(tok[1:-1] if tok.endswith("'") and len(tok) > 1 else tok)
        elif c == "\\" and len(tok) == 2:
            out.append(tok[1])
        elif c == "d":
            out.append(
                {1: str(dt.day), 2: f"{dt.day:02d}",
                 3: WOCHENTAGE[dt.weekday()][:2], 4: WOCHENTAGE[dt.weekday()]}[len(tok)]
            )
        elif c == "M":
            out.append(
                {1: str(dt.month), 2: f"{dt.month:02d}",
                 3: MONATE[dt.month - 1][:3], 4: MONATE[dt.month - 1]}[len(tok)]
            )
        elif c == "y":
            out.append(f"{dt.year % 100:02d}" if len(tok) <= 2 else f"{dt.year:04d}")
        elif c == "H":
            out.append(f"{dt.hour:02d}" if len(tok) == 2 else str(dt.hour))
        elif c == "h":
            h12 = dt.hour % 12 or 12
            out.append(f"{h12:02d}" if len(tok) == 2 else str(h12))
        elif c == "m":
            out.append(f"{dt.minute:02d}" if len(tok) == 2 else str(dt.minute))
        elif c == "s":
            out.append(f"{dt.second:02d}" if len(tok) == 2 else str(dt.second))
        else:
            out.append(tok)
    return "".join(out)


_BILD_SCHALTER = re.compile(r'\\@\s*(?:"([^"]*)"|(\S+))')
_FELDTYP = re.compile(r"\s*([A-Za-z]+)")


def _feldtyp(instr: str) -> str:
    m = _FELDTYP.match(instr)
    return m.group(1).upper() if m else ""


def _feldtext(instr: str, dt: datetime) -> str:
    m = _BILD_SCHALTER.search(instr)
    bild = (m.group(1) if m.group(1) is not None else m.group(2)) if m else STANDARD_BILD
    return formatiere_datum(dt, bild)


# --- Felder im XML ersetzen --------------------------------------------------

_FLD_TOKEN = re.compile(
    r'<w:fldChar\b[^>]*?w:fldCharType="(begin|separate|end)"[^>]*?/>'
    r"|<w:instrText\b[^>]*?>([^<]*)</w:instrText>"
)
_W_T = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")
_FLD_SIMPLE = re.compile(
    r'<w:fldSimple\b[^>]*?\bw:instr="([^"]*)"[^>]*?>(.*?)</w:fldSimple>', re.DOTALL
)


def _text_setzen(fragment: str, text: str) -> str:
    """Erstes <w:t> im Fragment bekommt den Text, weitere werden geleert."""
    ersetzt = [False]
    neu = _xml_escape(text)

    def sub(_m):
        if ersetzt[0]:
            return "<w:t></w:t>"
        ersetzt[0] = True
        return f'<w:t xml:space="preserve">{neu}</w:t>'

    return _W_T.sub(sub, fragment)


def datumsfelder_ersetzen(xml: str, dt: datetime) -> tuple[str, int]:
    """Ersetzt PRINTDATE/DATE/TIME-Felder in einem word/*.xml-Teil durch festen Text.

    Die Feldstruktur (fldChar/instrText bzw. fldSimple) entfaellt, das
    Ergebnis bleibt als normaler Text mit seiner Zeichenformatierung stehen.
    Rueckgabe: (neues XML, Anzahl ersetzter Felder).
    """
    edits: list[tuple[int, int, str]] = []  # (start, ende, ersatz)
    anzahl = 0

    # Verschachtelte komplexe Felder: Stapel mit offenen Feldern
    stack: list[dict] = []
    for m in _FLD_TOKEN.finditer(xml):
        art = m.group(1)
        if art == "begin":
            stack.append({"begin": m, "instr": [], "instr_teile": [], "sep": None})
        elif art == "separate":
            if stack and stack[-1]["sep"] is None:
                stack[-1]["sep"] = m
        elif art == "end":
            if not stack:
                continue
            f = stack.pop()
            instr = _xml_unescape("".join(f["instr"]), {"&quot;": '"'})
            if _feldtyp(instr) not in DATUMSFELDER:
                continue
            text = _feldtext(instr, dt)
            anzahl += 1
            edits.append((f["begin"].start(), f["begin"].end(), ""))
            edits.extend((t.start(), t.end(), "") for t in f["instr_teile"])
            if f["sep"] is not None:
                edits.append((f["sep"].start(), f["sep"].end(), ""))
                erg_start, erg_ende = f["sep"].end(), m.start()
                alt = xml[erg_start:erg_ende]
                if _W_T.search(alt):
                    edits.append((erg_start, erg_ende, _text_setzen(alt, text)))
                    edits.append((m.start(), m.end(), ""))
                    continue
            edits.append((m.start(), m.end(), f'<w:t xml:space="preserve">{_xml_escape(text)}</w:t>'))
        else:  # instrText
            if stack and stack[-1]["sep"] is None:
                stack[-1]["instr"].append(m.group(2))
                stack[-1]["instr_teile"].append(m)

    # Edits koennen sich ueberlappen (Ergebnisbereich enthaelt ggf. weitere Tokens
    # verschachtelter Felder, die nicht ersetzt werden) -> nach Start sortieren,
    # sich ueberlappende innere Edits verwerfen.
    edits.sort(key=lambda e: (e[0], -e[1]))
    teile: list[str] = []
    pos = 0
    for start, ende, ersatz in edits:
        if start < pos:
            continue
        teile.append(xml[pos:start])
        teile.append(ersatz)
        pos = ende
    teile.append(xml[pos:])
    xml = "".join(teile)

    # Einfache Felder <w:fldSimple w:instr="..."> ... </w:fldSimple>
    def simple(m):
        nonlocal anzahl
        instr = _xml_unescape(m.group(1), {"&quot;": '"'})
        if _feldtyp(instr) not in DATUMSFELDER:
            return m.group(0)
        anzahl += 1
        text = _feldtext(instr, dt)
        inner = m.group(2)
        if _W_T.search(inner):
            return _text_setzen(inner, text)
        return f'<w:r><w:t xml:space="preserve">{_xml_escape(text)}</w:t></w:r>'

    xml = _FLD_SIMPLE.sub(simple, xml)
    return xml, anzahl


def hat_datumsfelder(docx: Path | str) -> bool:
    """True, wenn die .docx/.odt Datumsfelder enthaelt (Datum aendert sich beim Drucken)."""
    if Path(docx).suffix.lower() == ".odt":
        return _odt_hat_datumsfelder(docx)
    try:
        with zipfile.ZipFile(docx) as z:
            for info in z.infolist():
                if _WORD_TEILE.match(info.filename) and info.file_size < MAX_TEIL:
                    if datumsfelder_ersetzen(z.read(info).decode("utf-8", "replace"), datetime.now())[1]:
                        return True
    except (OSError, zipfile.BadZipFile):
        pass
    return False


_WORD_TEILE = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")


def docx_mit_festem_datum(quelle: Path | str, ziel: Path | str) -> tuple[datetime, str, int]:
    """Schreibt eine Kopie der .docx mit festen Datumsfeldern nach ``ziel``.

    Die Quelle wird nur gelesen. Rueckgabe: (Datum, Quelle des Datums, Anzahl Felder).
    """
    dt, quelle_name = druckdatum(quelle)
    gesamt = 0
    with zipfile.ZipFile(quelle) as zin, zipfile.ZipFile(ziel, "w") as zout:
        for info in zin.infolist():
            daten = zin.read(info)
            if _WORD_TEILE.match(info.filename):
                xml, n = datumsfelder_ersetzen(daten.decode("utf-8"), dt)
                if n:
                    daten = xml.encode("utf-8")
                    gesamt += n
            zout.writestr(info, daten, compress_type=info.compress_type)
    return dt, quelle_name, gesamt


# --- OpenDocument-Text (.odt) -----------------------------------------------

_ODT_TEILE = re.compile(r"^(content|styles)\.xml$")
_ODF_FELD = re.compile(
    r"<text:(date|time|print-date|print-time)(?=[\s/>])([^>]*?)(?:/>|>.*?</text:\1>)", re.DOTALL
)
_ODF_STILNAME = re.compile(r'\bstyle:data-style-name="([^"]*)"')
_ODF_NS_NUMBER = "{urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0}"
_ODF_NS_STYLE = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
STANDARD_ODT_DATUM = "dd.MM.yyyy"
STANDARD_ODT_ZEIT = "HH:mm:ss"


def _odt_druckdatum(odt: Path) -> tuple[datetime, str]:
    meta = ""
    try:
        with zipfile.ZipFile(odt) as z:
            info = z.getinfo("meta.xml")
            if info.file_size < MAX_TEIL:
                meta = z.read(info).decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile, OSError):
        pass
    for tag, name in (
        ("meta:print-date", "lastPrinted"),
        ("dc:date", "modified"),
        ("meta:creation-date", "created"),
    ):
        m = re.search(rf"<{tag}\b[^>]*>([^<]*)</{tag}>", meta)
        if m:
            dt = _parse_iso(m.group(1))
            if dt and dt.year > 1900:
                return dt, name
    return datetime.fromtimestamp(odt.stat().st_mtime), "Dateizeit"


def _odf_bild(stil) -> str:
    """Word-artiges Datumsbild aus einem number:date-style/number:time-style-Element."""
    teile: list[str] = []
    mit_ampm = any(k.tag == _ODF_NS_NUMBER + "am-pm" for k in stil)
    for k in stil:
        art = k.tag.removeprefix(_ODF_NS_NUMBER)
        lang = k.get(_ODF_NS_NUMBER + "style") == "long"
        if art == "day":
            teile.append("dd" if lang else "d")
        elif art == "month":
            if k.get(_ODF_NS_NUMBER + "textual") == "true":
                teile.append("MMMM" if lang else "MMM")
            else:
                teile.append("MM" if lang else "M")
        elif art == "year":
            teile.append("yyyy" if lang else "yy")
        elif art == "day-of-week":
            teile.append("dddd" if lang else "ddd")
        elif art == "hours":
            teile.append(("hh" if lang else "h") if mit_ampm else ("HH" if lang else "H"))
        elif art == "minutes":
            teile.append("mm" if lang else "m")
        elif art == "seconds":
            teile.append("ss" if lang else "s")
        elif art == "am-pm":
            teile.append("AM/PM")
        elif art == "text":
            teile.append("".join("\\" + c for c in (k.text or "")))  # Literal: jedes Zeichen maskiert
    return "".join(teile)


def _odf_stile(teile_xml: list[str]) -> dict[str, str]:
    """Name -> Datumsbild aller Datums-/Zeitstile in content.xml und styles.xml."""
    import xml.etree.ElementTree as ET

    stile: dict[str, str] = {}
    for xml in teile_xml:
        try:
            wurzel = ET.fromstring(xml)
        except ET.ParseError:
            continue
        for art in ("date-style", "time-style"):
            for e in wurzel.iter(_ODF_NS_NUMBER + art):
                name = e.get(_ODF_NS_STYLE + "name")
                bild = _odf_bild(e)
                if name and bild:
                    stile[name] = bild
    return stile


def odt_datumsfelder_ersetzen(xml: str, dt: datetime, stile: dict[str, str]) -> tuple[str, int]:
    """Ersetzt nicht fixierte ODF-Datumsfelder in einem XML-Teil durch festen Text.

    Rueckgabe: (neues XML, Anzahl ersetzter Felder).
    """
    anzahl = 0

    def sub(m):
        nonlocal anzahl
        attribute = m.group(2)
        if 'text:fixed="true"' in attribute:
            return m.group(0)
        anzahl += 1
        n = _ODF_STILNAME.search(attribute)
        bild = stile.get(_xml_unescape(n.group(1))) if n else None
        if not bild:
            bild = STANDARD_ODT_ZEIT if m.group(1).endswith("time") else STANDARD_ODT_DATUM
        return _xml_escape(formatiere_datum(dt, bild))

    return _ODF_FELD.sub(sub, xml), anzahl


def _odt_teile(z: zipfile.ZipFile) -> dict[str, str]:
    return {
        i.filename: z.read(i).decode("utf-8", "replace")
        for i in z.infolist() if _ODT_TEILE.match(i.filename) and i.file_size < MAX_TEIL
    }


def _odt_hat_datumsfelder(odt: Path | str) -> bool:
    try:
        with zipfile.ZipFile(odt) as z:
            return any(
                'text:fixed="true"' not in m.group(2)
                for xml in _odt_teile(z).values() for m in _ODF_FELD.finditer(xml)
            )
    except (OSError, zipfile.BadZipFile):
        return False


def odt_mit_festem_datum(quelle: Path | str, ziel: Path | str) -> tuple[datetime, str, int]:
    """Schreibt eine Kopie der .odt mit festen Datumsfeldern nach ``ziel`` (Quelle unveraendert).

    ``mimetype`` steht als erster Eintrag und unkomprimiert (ODF-Vorschrift).
    Rueckgabe: (Datum, Quelle des Datums, Anzahl Felder).
    """
    dt, quelle_name = druckdatum(quelle)
    gesamt = 0
    with zipfile.ZipFile(quelle) as zin, zipfile.ZipFile(ziel, "w") as zout:
        teile = _odt_teile(zin)
        stile = _odf_stile(list(teile.values()))
        infos = sorted(zin.infolist(), key=lambda i: i.filename != "mimetype")  # stabil: mimetype zuerst
        for info in infos:
            daten = zin.read(info)
            if info.filename in teile:
                xml, n = odt_datumsfelder_ersetzen(teile[info.filename], dt, stile)
                if n:
                    daten = xml.encode("utf-8")
                    gesamt += n
            art = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
            zout.writestr(info, daten, compress_type=art)
    return dt, quelle_name, gesamt


def mit_festem_datum(quelle: Path | str, ziel: Path | str) -> tuple[datetime, str, int]:
    """.docx oder .odt mit festen Datumsfeldern nach ``ziel`` schreiben."""
    if Path(quelle).suffix.lower() == ".odt":
        return odt_mit_festem_datum(quelle, ziel)
    return docx_mit_festem_datum(quelle, ziel)


# --- Umwandler ----------------------------------------------------------------

def word_com_verfuegbar() -> bool:
    return sys.platform == "win32" and _com_klasse_da("Word.Application")


def excel_com_verfuegbar() -> bool:
    return sys.platform == "win32" and _com_klasse_da("Excel.Application")


def _com_klasse_registriert(prog_id: str) -> bool:
    """True, wenn das Office-Programm in der Registry steht (unabhaengig von pywin32)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id):
            return True
    except OSError:
        return False


def pywin32_verfuegbar() -> bool:
    try:
        import win32com.client  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - pywin32 fehlt oder ist kaputt
        return False


def _com_klasse_da(prog_id: str) -> bool:
    return _com_klasse_registriert(prog_id) and pywin32_verfuegbar()


def finde_libreoffice() -> Optional[str]:
    """Pfad zu soffice oder None."""
    for name in ("soffice", "libreoffice"):
        pfad = shutil.which(name)
        if pfad:
            return pfad
    kandidaten = []
    if sys.platform == "win32":
        for var in ("ProgramFiles", "ProgramFiles(x86)"):
            basis = os.environ.get(var)
            if basis:
                kandidaten.append(Path(basis) / "LibreOffice" / "program" / "soffice.exe")
    elif sys.platform == "darwin":
        kandidaten.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    for k in kandidaten:
        if k.exists():
            return str(k)
    return None


def umwandler_verfuegbar(endung: str) -> bool:
    """Gibt es fuer diese Dateiendung (.docx/.odt/.xlsx) irgendeinen Umwandler?"""
    ist_word = endung.lower() in WORD_ENDUNGEN
    com = word_com_verfuegbar() if ist_word else excel_com_verfuegbar()
    mac = mac_office_verfuegbar("word" if ist_word else "excel")
    return com or mac or _iwork_art(endung) is not None or finde_libreoffice() is not None


# --------------------------------------------------------------- macOS: Word/Excel
MAC_OFFICE_TIMEOUT_S = 180
# Art -> (Anzeigename, Bundle-IDs). Gesucht und gesteuert wird ueber die Bundle-ID,
# nicht ueber den Namen: Pages/Numbers heissen seit 15.x "Pages Creator Studio"
# usw. und haben neue IDs (vorher com.apple.iWork.*).
_MAC_APPS = {
    "word": ("Microsoft Word", ("com.microsoft.Word",)),
    "excel": ("Microsoft Excel", ("com.microsoft.Excel",)),
    "pages": ("Pages", ("com.apple.Pages", "com.apple.iWork.Pages")),
    "numbers": ("Numbers", ("com.apple.Numbers", "com.apple.iWork.Numbers")),
}
PAGES_ENDUNGEN = (".docx",)  # Pages oeffnet kein .odt
NUMBERS_ENDUNGEN = (".xlsx",)


def _iwork_art(endung: str) -> Optional[str]:
    """"pages"/"numbers", wenn das passende iWork-Programm diese Datei umwandeln kann."""
    endung = endung.lower()
    art = "pages" if endung in PAGES_ENDUNGEN else "numbers" if endung in NUMBERS_ENDUNGEN else None
    return art if art and mac_office_verfuegbar(art) else None

# Oeffnen liefert auf dem Mac keinen Verweis zurueck (asynchron): per (eindeutigem)
# Namen warten, bis das Dokument da ist (nicht nur, bis kein Fehler kommt). ``delay`` steht bewusst ausserhalb von ``tell``: darin wird es an
# Word/Excel geschickt und kehrt sofort zurueck - dann wartete die Schleife gar nicht.
_MAC_SKRIPT_VORLAGE = """
on run argv
  set dname to item 1 of argv
  set quelle to item 2 of argv
  set ziel to item 3 of argv
  with timeout of {timeout} seconds
    tell application id "{bid}" to open (POSIX file quelle)
    set doc to missing value
    repeat {versuche} times
      try
        tell application id "{bid}" to set doc to {objekt} dname
      on error
        set doc to missing value
      end try
      -- Word liefert fuer ein (noch) unbekanntes Dokument "missing value" statt eines Fehlers
      if doc is not missing value then exit repeat
      delay 0.2
    end repeat
    if doc is missing value then error "{app} hat die Datei nicht geöffnet (vielleicht ist dort gerade ein Dialog offen)." number 9001
    tell application id "{bid}"
      try
        {speichern}
      on error m number n
        close doc saving no
        error m number n
      end try
      close doc saving no
    end tell
  end timeout
end run
"""
_MAC_OEFFNEN_WARTEN_S = 30

# Pages/Numbers: ``open`` liefert das Dokument meist direkt; sonst per Namensanfang
# suchen (importierte Dateien erscheinen teils ohne Endung).
_IWORK_SKRIPT = """
on run argv
  set dstamm to item 1 of argv
  set quelle to item 2 of argv
  set ziel to item 3 of argv
  with timeout of {timeout} seconds
    -- alles in einem tell-Block: Numbers scheitert, wenn das Dokument ausserhalb
    -- mit "missing value" verglichen wird ("... kann nicht in Typ specifier umgewandelt werden")
    tell application id "{bid}"
      set doc to missing value
      try
        set doc to open (POSIX file quelle)
      end try
      set versuche to 0
      repeat while doc is missing value and versuche < {versuche}
        set versuche to versuche + 1
        try
          repeat with d in documents
            if name of d starts with dstamm then set doc to contents of d
          end repeat
        end try
        if doc is missing value then tell current application to delay 0.2
      end repeat
      if doc is missing value then error "{app} hat die Datei nicht geöffnet (vielleicht ist dort gerade ein Dialog offen)." number 9001
      try
        export doc to (POSIX file ziel) as PDF
      on error m number n
        close doc saving no
        error m number n
      end try
      close doc saving no
    end tell
  end timeout
end run
"""
_MAC_SKRIPT = {
    "word": _MAC_SKRIPT_VORLAGE.replace("{app}", "Microsoft Word").replace("{objekt}", "document").replace(
        "{speichern}", "save as doc file name ziel file format format PDF"),
    "excel": _MAC_SKRIPT_VORLAGE.replace("{app}", "Microsoft Excel").replace("{objekt}", "workbook").replace(
        "{speichern}", "save workbook as doc filename ziel file format PDF file format"),
    "pages": _IWORK_SKRIPT.replace("{app}", "Pages"),
    "numbers": _IWORK_SKRIPT.replace("{app}", "Numbers"),
}


_BUNDLE_CACHE: dict[str, tuple[float, Optional[str]]] = {}
_BUNDLE_CACHE_S = 60.0  # Installation waehrend des Laufs wird nach spaetestens einer Minute erkannt


def _installierte_bundle_ids(basen: Optional[list[Path]] = None) -> dict[str, Path]:
    """Bundle-ID -> .app in /Applications und ~/Applications (eine Ebene tief)."""
    import plistlib

    gefunden: dict[str, Path] = {}
    for basis in basen or (Path("/Applications"), Path.home() / "Applications"):
        try:
            apps = list(basis.glob("*.app"))
        except OSError:
            continue
        for app in apps:
            try:
                with open(app / "Contents" / "Info.plist", "rb") as f:
                    bid = plistlib.load(f).get("CFBundleIdentifier")
            except Exception:  # noqa: BLE001 - fremde, kaputte Info.plist (z.B. ExpatError): ueberspringen
                continue
            if bid:
                gefunden.setdefault(bid, app)
    return gefunden


def _mac_bundle_id(art: str) -> Optional[str]:
    """Bundle-ID des installierten Programms (Word, Excel, Pages, Numbers) oder None."""
    import time

    jetzt = time.monotonic()
    zwischen = _BUNDLE_CACHE.get(art)
    if zwischen and jetzt - zwischen[0] < _BUNDLE_CACHE_S:
        return zwischen[1]
    installiert = _installierte_bundle_ids()
    bid = next((b for b in _MAC_APPS[art][1] if b in installiert), None)
    _BUNDLE_CACHE[art] = (jetzt, bid)
    return bid


def mac_office_verfuegbar(art: str) -> bool:
    """Word/Excel/Pages/Numbers (``art``) auf dem Mac installiert?"""
    return sys.platform == "darwin" and _mac_bundle_id(art) is not None


def _mac_app_laeuft(bid: str) -> bool:
    """Laeuft das Programm schon? (``is running`` startet es nicht.)"""
    try:
        r = subprocess.run(
            ["osascript", "-e", f'application id "{bid}" is running'],
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def _mac_fehlertext(programm: str, stderr: str) -> str:
    text = (stderr or "").strip()
    if "-1743" in text:
        return (
            tr(
                "PDF Sortier Meister darf {programm} nicht steuern. Bitte unter "
                "Systemeinstellungen › Datenschutz & Sicherheit › Automation „{programm}“ "
                "für PDF Sortier Meister erlauben."
            ).format(programm=programm)
        )
    # "418:454: execution error: <Meldung> (9001)" -> "<Meldung>"
    treffer = re.search(r"execution error:\s*(.*?)\s*\(-?\d+\)\s*$", text, re.DOTALL)
    if treffer:
        text = treffer.group(1)
    if text.startswith(programm):  # eigene Meldung des Skripts nennt das Programm schon
        return text[:300]
    return tr("{programm} konnte nicht umwandeln: {0}").format(text[:300], programm=programm)


def _mit_office_mac(art: str, quelle: Path, pdf: Path) -> None:
    """Word/Excel auf dem Mac per AppleScript; Arbeitskopie im Container des Programms."""
    import uuid

    programm = _MAC_APPS[art][0]
    bundle = _mac_bundle_id(art)
    if not bundle:
        raise UmwandlungFehler(tr("{programm} ist nicht (mehr) installiert.").format(programm=programm))
    container_tmp = Path.home() / "Library" / "Containers" / bundle / "Data" / "tmp"
    container_tmp.mkdir(parents=True, exist_ok=True)
    arbeit = Path(tempfile.mkdtemp(prefix="pdfsm-", dir=container_tmp))
    # eindeutiger Name: nie ein gleichnamiges offenes Dokument des Nutzers treffen
    name = f"pdfsm-{uuid.uuid4().hex[:12]}{quelle.suffix.lower()}"
    kopie = arbeit / name
    ziel = arbeit / (Path(name).stem + ".pdf")
    war_offen = _mac_app_laeuft(bundle)
    try:
        shutil.copy2(quelle, kopie)
        if not war_offen:  # versteckt und im Hintergrund starten
            subprocess.run(["open", "-g", "-j", "-b", bundle], capture_output=True, timeout=60)
        skript = (_MAC_SKRIPT[art].replace("{timeout}", str(MAC_OFFICE_TIMEOUT_S))
                  .replace("{versuche}", str(_MAC_OEFFNEN_WARTEN_S * 5)).replace("{bid}", bundle))
        try:
            lauf = subprocess.run(
                ["osascript", "-", Path(name).stem if art in ("pages", "numbers") else name, str(kopie), str(ziel)],
                input=skript, capture_output=True, text=True, timeout=MAC_OFFICE_TIMEOUT_S + 30,
            )
        except subprocess.TimeoutExpired as e:
            raise UmwandlungFehler(tr("{programm} hat nicht rechtzeitig geantwortet.").format(programm=programm)) from e
        if lauf.returncode != 0:
            raise UmwandlungFehler(_mac_fehlertext(programm, lauf.stderr))
        if not ziel.exists() or ziel.stat().st_size == 0:
            raise UmwandlungFehler(tr("{programm} hat kein PDF erzeugt.").format(programm=programm))
        shutil.move(str(ziel), str(pdf))
    finally:
        if not war_offen:
            subprocess.run(
                ["osascript", "-e", f'tell application id "{bundle}" to quit saving no'],
                capture_output=True, timeout=60,
            )
        shutil.rmtree(arbeit, ignore_errors=True)


def _mit_word(docx: Path, pdf: Path, pdfa: bool) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32com.client.DispatchEx("Word.Application")  # eigene Instanz
        word.Visible = False
        word.DisplayAlerts = 0  # wdAlertsNone
        doc = word.Documents.Open(
            str(docx), ConfirmConversions=False, ReadOnly=True,
            AddToRecentFiles=False, Visible=False,
        )
        doc.ExportAsFixedFormat(
            OutputFileName=str(pdf),
            ExportFormat=17,  # wdExportFormatPDF
            OpenAfterExport=False,
            OptimizeFor=0,  # wdExportOptimizeForPrint
            Range=0,  # wdExportAllDocument
            Item=0,  # wdExportDocumentContent
            IncludeDocProps=True,
            KeepIRM=True,
            CreateBookmarks=1,  # wdExportCreateHeadingBookmarks
            DocStructureTags=True,
            BitmapMissingFonts=True,
            UseISO19005_1=bool(pdfa),
        )
    finally:
        try:
            if doc is not None:
                doc.Close(SaveChanges=0)
        finally:
            try:
                if word is not None:
                    word.Quit(SaveChanges=0)
            finally:
                pythoncom.CoUninitialize()


def _mit_excel(xlsx: Path, pdf: Path) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    excel = None
    mappe = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        mappe = excel.Workbooks.Open(str(xlsx), UpdateLinks=0, ReadOnly=True)
        mappe.ExportAsFixedFormat(
            Type=0,  # xlTypePDF
            Filename=str(pdf),
            Quality=0,  # xlQualityStandard
            IncludeDocProperties=True,
            IgnorePrintAreas=False,
            OpenAfterPublish=False,
        )
    finally:
        try:
            if mappe is not None:
                mappe.Close(SaveChanges=False)
        finally:
            try:
                if excel is not None:
                    excel.Quit()
            finally:
                pythoncom.CoUninitialize()


def _mit_libreoffice(soffice: str, quelle: Path, pdf: Path, pdfa: bool) -> None:
    """Wandelt mit soffice um; Ergebnis landet als ``pdf`` (Name der Quelle + .pdf)."""
    ausgabe = pdf.parent
    filter_name = "calc_pdf_Export" if quelle.suffix.lower() in EXCEL_ENDUNGEN else "writer_pdf_Export"
    filt = f"pdf:{filter_name}"
    if pdfa:
        filt += ':{"SelectPdfVersion":{"type":"long","value":"2"}}'  # PDF/A-2b
    profil = Path(tempfile.mkdtemp(prefix="pdfsm-lo-"))  # eigenes Profil: stoert kein offenes LibreOffice
    try:
        cmd = [
            soffice, "--headless", "--norestore", "--nologo",
            f"-env:UserInstallation={profil.as_uri()}",
            "--convert-to", filt, "--outdir", str(ausgabe), str(quelle),
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            lauf = subprocess.run(
                cmd, capture_output=True, text=True, timeout=LIBREOFFICE_TIMEOUT_S,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired as e:
            raise UmwandlungFehler(tr("LibreOffice hat nicht rechtzeitig geantwortet.")) from e
        erzeugt = ausgabe / (quelle.stem + ".pdf")
        if lauf.returncode != 0 or not erzeugt.exists():
            raise UmwandlungFehler(
                tr("LibreOffice konnte nicht umwandeln: {0}").format((lauf.stderr or lauf.stdout).strip()[:300])
            )
        if erzeugt != pdf:
            erzeugt.replace(pdf)
    finally:
        shutil.rmtree(profil, ignore_errors=True)


def _freier_pfad(pfad: Path) -> Path:
    if not pfad.exists():
        return pfad
    n = 1
    while True:
        kandidat = pfad.with_name(f"{pfad.stem} ({n}){pfad.suffix}")
        if not kandidat.exists():
            return kandidat
        n += 1


def umwandeln(quelle: Path | str, ziel: Path | str | None = None, pdfa: bool = False) -> UmwandlungsErgebnis:
    """Wandelt eine .docx/.odt/.xlsx in PDF um; die Quelle bleibt unveraendert.

    Args:
        quelle: .docx, .odt oder .xlsx
        ziel: gewuenschter PDF-Pfad; Standard: gleicher Ordner, gleicher Name, ``.pdf``.
            Existiert er schon, wird ``Name (1).pdf`` verwendet (nichts wird ueberschrieben).
        pdfa: PDF/A erzeugen, wenn der Umwandler es kann.

    Raises:
        KeinUmwandlerGefunden: weder Word/Excel noch LibreOffice vorhanden
        UmwandlungFehler: Umwandlung fehlgeschlagen
    """
    quelle = Path(quelle)
    endung = quelle.suffix.lower()
    if endung not in OFFICE_ENDUNGEN:
        raise UmwandlungFehler(tr("Dateityp {0} wird nicht unterstützt.").format(endung or '(keiner)'))
    if not quelle.is_file():
        raise UmwandlungFehler(tr("Datei nicht gefunden: {quelle}").format(quelle=quelle))
    ist_word = endung in WORD_ENDUNGEN
    ziel = _freier_pfad(Path(ziel) if ziel else quelle.with_suffix(".pdf"))

    com = word_com_verfuegbar() if ist_word else excel_com_verfuegbar()
    mac = not com and mac_office_verfuegbar("word" if ist_word else "excel")
    soffice = finde_libreoffice()
    iwork = _iwork_art(endung)
    if not com and not mac and not soffice and not iwork:
        programm = "Microsoft Word" if ist_word else "Microsoft Excel"
        prog_id = "Word.Application" if ist_word else "Excel.Application"
        if _com_klasse_registriert(prog_id) and not pywin32_verfuegbar():
            raise KeinUmwandlerGefunden(
                tr(
                    "{programm} ist installiert, aber dem Python, mit dem PDF Sortier "
                    "Meister läuft, fehlt das Paket \"pywin32\".\n"
                    "Bitte im Programmordner ausführen: python -m pip install -r "
                    "requirements.txt"
                ).format(programm=programm)
            )
        if sys.platform == "darwin" and endung in PAGES_ENDUNGEN + NUMBERS_ENDUNGEN:
            apple = "Apple Pages" if ist_word else "Apple Numbers"
            raise KeinUmwandlerGefunden(
                tr(
                    "Zum Umwandeln wird {programm}, LibreOffice oder {apple} benötigt. "
                    "Nichts davon wurde gefunden."
                ).format(programm=programm, apple=apple)
            )
        raise KeinUmwandlerGefunden(
            tr(
                "Zum Umwandeln wird {programm} oder LibreOffice benötigt. Beides wurde nicht "
                "gefunden."
            ).format(programm=programm)
        )

    ergebnis = UmwandlungsErgebnis(pdf=ziel, werkzeug="")
    arbeit = Path(tempfile.mkdtemp(prefix="pdfsm-office-"))
    try:
        kopie = arbeit / quelle.name  # nur die Kopie wird geoeffnet, nie das Original
        if ist_word:
            ergebnis.datum, ergebnis.datum_quelle, ergebnis.ersetzte_felder = mit_festem_datum(quelle, kopie)
            if ergebnis.datum_quelle != "lastPrinted":
                ergebnis.hinweise.append(
                    f"Kein Druckdatum im Dokument - Datumsfelder zeigen ersatzweise "
                    f"{ergebnis.datum_quelle} ({ergebnis.datum:%d.%m.%Y})."
                )
        else:
            shutil.copy2(quelle, kopie)
        pdf_tmp = arbeit / "ergebnis.pdf"

        # Excel (COM) und Word/Excel auf dem Mac koennen kein PDF/A -> dann lieber LibreOffice
        if pdfa and soffice and (mac or not ist_word):
            com = mac = False
        fehler: Optional[Exception] = None
        if mac:
            try:
                _mit_office_mac("word" if ist_word else "excel", kopie, pdf_tmp)
                if pdfa:
                    ergebnis.hinweise.append(
                        tr("{0} kann auf dem Mac kein PDF/A erzeugen - normales PDF erstellt.").format('Word' if ist_word else 'Excel')
                    )
                ergebnis.werkzeug = "Word" if ist_word else "Excel"
            except UmwandlungFehler as e:
                fehler = e
                pdf_tmp.unlink(missing_ok=True)
        elif com:
            try:
                if ist_word:
                    _mit_word(kopie, pdf_tmp, pdfa)
                    ergebnis.pdfa = pdfa
                else:
                    _mit_excel(kopie, pdf_tmp)
                    if pdfa:
                        ergebnis.hinweise.append(tr("Excel kann kein PDF/A erzeugen - normales PDF erstellt."))
                ergebnis.werkzeug = "Word" if ist_word else "Excel"
            except Exception as e:  # noqa: BLE001 - COM wirft vielfaeltige Fehler; Rueckfall versuchen
                fehler = e
                pdf_tmp.unlink(missing_ok=True)
        office_name = "Word" if ist_word else "Excel"
        if not ergebnis.werkzeug and soffice:
            try:
                lo_ziel = arbeit / (kopie.stem + ".pdf")
                _mit_libreoffice(soffice, kopie, lo_ziel, pdfa)
                lo_ziel.replace(pdf_tmp)
                if fehler is not None:
                    ergebnis.hinweise.append(tr("{office_name} ging nicht ({fehler}) - LibreOffice verwendet.").format(office_name=office_name, fehler=fehler))
                ergebnis.werkzeug = "LibreOffice"
                ergebnis.pdfa = pdfa
            except UmwandlungFehler as e:
                if not iwork:
                    raise
                fehler, office_name = e, "LibreOffice"
                pdf_tmp.unlink(missing_ok=True)
        if not ergebnis.werkzeug and iwork:
            apple = _MAC_APPS[iwork][0]
            _mit_office_mac(iwork, kopie, pdf_tmp)
            if fehler is not None:
                ergebnis.hinweise.append(tr("{office_name} ging nicht ({fehler}) - {apple} verwendet.").format(office_name=office_name, fehler=fehler, apple=apple))
            if pdfa:
                ergebnis.hinweise.append(tr("{apple} kann kein PDF/A erzeugen - normales PDF erstellt.").format(apple=apple))
            ergebnis.werkzeug = apple
        if not ergebnis.werkzeug:
            raise UmwandlungFehler(tr("Umwandlung mit {office_name} fehlgeschlagen: {fehler}").format(office_name=office_name, fehler=fehler))
        if not pdf_tmp.exists() or pdf_tmp.stat().st_size == 0:
            raise UmwandlungFehler(tr("Die Umwandlung hat kein PDF erzeugt."))
        shutil.move(str(pdf_tmp), str(ziel))
    finally:
        shutil.rmtree(arbeit, ignore_errors=True)
    return ergebnis
