"""Word-/Excel-Dateien in PDF umwandeln (Issue #9) - Qt-frei.

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

Umwandlung
----------
1. Microsoft Word bzw. Excel per COM (pywin32, nur Windows), in einer eigenen
   unsichtbaren Programminstanz - ein offenes Word des Nutzers bleibt unberuehrt.
2. Rueckfall: LibreOffice headless (``soffice``).
3. Ist keines von beiden da, gibt es ``KeinUmwandlerGefunden`` mit klarer Meldung.

PDF/A: Word per ``ExportAsFixedFormat(UseISO19005_1=True)`` (Stufe B),
LibreOffice per ``SelectPdfVersion`` (PDF/A-2b). Excel kann das per COM nicht;
dort wird bei PDF/A LibreOffice bevorzugt, sonst gibt es ein normales PDF
samt Hinweis.

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

WORD_ENDUNGEN = (".docx",)
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
    werkzeug: str  # "Word", "Excel" oder "LibreOffice"
    datum: Optional[datetime] = None  # nur .docx: eingesetztes Datum der Datumsfelder
    datum_quelle: Optional[str] = None  # "lastPrinted", "modified", "created" oder "Dateizeit"
    ersetzte_felder: int = 0
    pdfa: bool = False  # PDF/A tatsaechlich erzeugt
    hinweise: list[str] = field(default_factory=list)


def ist_office_datei(pfad: Path | str) -> bool:
    """Sortierbare Nicht-PDF-Datei: .docx/.xlsx und seit Issue #184 auch Bilder.

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
    """Datum fuer die Datumsfelder: lastPrinted, sonst modified, created, Dateizeit."""
    docx = Path(docx)
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
    """True, wenn die .docx PRINTDATE-/DATE-/TIME-Felder enthaelt (Datum aendert sich beim Drucken)."""
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
    """Gibt es fuer diese Dateiendung (.docx/.xlsx) irgendeinen Umwandler?"""
    com = word_com_verfuegbar() if endung.lower() in WORD_ENDUNGEN else excel_com_verfuegbar()
    return com or finde_libreoffice() is not None


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
            raise UmwandlungFehler("LibreOffice hat nicht rechtzeitig geantwortet.") from e
        erzeugt = ausgabe / (quelle.stem + ".pdf")
        if lauf.returncode != 0 or not erzeugt.exists():
            raise UmwandlungFehler(
                f"LibreOffice konnte nicht umwandeln: {(lauf.stderr or lauf.stdout).strip()[:300]}"
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
    """Wandelt eine .docx/.xlsx in PDF um; die Quelle bleibt unveraendert.

    Args:
        quelle: .docx oder .xlsx
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
        raise UmwandlungFehler(f"Dateityp {endung or '(keiner)'} wird nicht unterstützt.")
    if not quelle.is_file():
        raise UmwandlungFehler(f"Datei nicht gefunden: {quelle}")
    ist_word = endung in WORD_ENDUNGEN
    ziel = _freier_pfad(Path(ziel) if ziel else quelle.with_suffix(".pdf"))

    com = word_com_verfuegbar() if ist_word else excel_com_verfuegbar()
    soffice = finde_libreoffice()
    if not com and not soffice:
        programm = "Microsoft Word" if ist_word else "Microsoft Excel"
        prog_id = "Word.Application" if ist_word else "Excel.Application"
        if _com_klasse_registriert(prog_id) and not pywin32_verfuegbar():
            raise KeinUmwandlerGefunden(
                f"{programm} ist installiert, aber dem Python, mit dem PDF Sortier Meister "
                "läuft, fehlt das Paket \"pywin32\".\n"
                "Bitte im Programmordner ausführen: python -m pip install -r requirements.txt"
            )
        raise KeinUmwandlerGefunden(
            f"Zum Umwandeln wird {programm} (nur Windows) oder LibreOffice benötigt. "
            "Beides wurde nicht gefunden."
        )

    ergebnis = UmwandlungsErgebnis(pdf=ziel, werkzeug="")
    arbeit = Path(tempfile.mkdtemp(prefix="pdfsm-office-"))
    try:
        kopie = arbeit / quelle.name  # nur die Kopie wird geoeffnet, nie das Original
        if ist_word:
            ergebnis.datum, ergebnis.datum_quelle, ergebnis.ersetzte_felder = docx_mit_festem_datum(quelle, kopie)
            if ergebnis.datum_quelle != "lastPrinted":
                ergebnis.hinweise.append(
                    f"Kein Druckdatum im Dokument - Datumsfelder zeigen ersatzweise "
                    f"{ergebnis.datum_quelle} ({ergebnis.datum:%d.%m.%Y})."
                )
        else:
            shutil.copy2(quelle, kopie)
        pdf_tmp = arbeit / "ergebnis.pdf"

        # Excel kann per COM kein PDF/A -> dann lieber LibreOffice, falls da
        if pdfa and not ist_word and soffice:
            com = False
        fehler: Optional[Exception] = None
        if com:
            try:
                if ist_word:
                    _mit_word(kopie, pdf_tmp, pdfa)
                    ergebnis.pdfa = pdfa
                else:
                    _mit_excel(kopie, pdf_tmp)
                    if pdfa:
                        ergebnis.hinweise.append("Excel kann kein PDF/A erzeugen - normales PDF erstellt.")
                ergebnis.werkzeug = "Word" if ist_word else "Excel"
            except Exception as e:  # noqa: BLE001 - COM wirft vielfaeltige Fehler; Rueckfall versuchen
                fehler = e
                pdf_tmp.unlink(missing_ok=True)
        if not ergebnis.werkzeug:
            if not soffice:
                raise UmwandlungFehler(f"Umwandlung mit {'Word' if ist_word else 'Excel'} fehlgeschlagen: {fehler}")
            if fehler is not None:
                ergebnis.hinweise.append(f"{'Word' if ist_word else 'Excel'} ging nicht ({fehler}) - LibreOffice verwendet.")
            lo_ziel = arbeit / (kopie.stem + ".pdf")
            _mit_libreoffice(soffice, kopie, lo_ziel, pdfa)
            lo_ziel.replace(pdf_tmp)
            ergebnis.werkzeug = "LibreOffice"
            ergebnis.pdfa = pdfa
        if not pdf_tmp.exists() or pdf_tmp.stat().st_size == 0:
            raise UmwandlungFehler("Die Umwandlung hat kein PDF erzeugt.")
        shutil.move(str(pdf_tmp), str(ziel))
    finally:
        shutil.rmtree(arbeit, ignore_errors=True)
    return ergebnis
