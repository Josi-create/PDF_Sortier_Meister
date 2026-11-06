"""Text aus Office-Dateien (docx, xlsx, odt, doc, xls) – weitgehend Standardbibliothek.

Uebernommen aus PDFsuche (``office.py``). docx/xlsx/odt sind ZIP-Archive mit
XML darin; ``.doc`` wird ueber den Word-97-Piece-Table (olefile) gelesen, ``.xls``
ueber xlrd. Laeuft in den Arbeitsprozessen.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from src.search.extract import fehlertext

MAX_XML = 300 * 1024 * 1024          # Schutz gegen ZIP-Bomben (entpackte Groesse je Teil)
MAX_TEXT = 2_000_000                 # Zeichen je "Seite" (Dokument bzw. Tabellenblatt)
MAX_MAPPE = 3_000_000                # Zeichen je Excel-Arbeitsmappe insgesamt
OLE_MAGIC = b"\xd0\xcf\x11\xe0"      # verschluesselte Office-Dateien sind OLE-Container

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DC = "{http://purl.org/dc/elements/1.1/}"
ODT_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
ODT_META = "{urn:oasis:names:tc:opendocument:xmlns:meta:1.0}"


def _lokal(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _lies(z: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_XML:
        raise ValueError(f"{name} zu groß ({info.file_size // 1_000_000} MB entpackt)")
    return z.read(info)


def _knapp(t: str) -> str:
    t = t.replace("\x00", "")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()[:MAX_TEXT]


def office_text(pfad: str, fmt: str) -> dict:
    """Text je "Seite" (Dokument bzw. Tabellenblatt) samt Titel/Autor; Status wie bei PDFs."""
    erg = {"status": "text", "fehler": None, "seiten": [], "titel": None, "autor": None}
    try:
        with open(pfad, "rb") as f:
            kopf = f.read(4)
        if fmt in ("doc", "xls"):
            if kopf != OLE_MAGIC:
                # z. B. als .doc gespeichertes RTF/HTML oder umbenannte docx
                return _ersatz_text(pfad, erg)
            seiten, erg["titel"], erg["autor"] = (_doc if fmt == "doc" else _xls)(pfad)
            erg["seiten"] = [(i + 1, "text", t) for i, t in enumerate(seiten)]
            if not any(t.strip() for t in seiten):
                erg["status"] = "leer"
            return erg
        if kopf == OLE_MAGIC:
            erg["status"] = "verschluesselt"
            return erg
        with zipfile.ZipFile(pfad) as z:
            if fmt in ("docx", "docm"):
                seiten = _docx(z)
                erg["titel"], erg["autor"] = _ooxml_meta(z)
            elif fmt in ("xlsx", "xlsm"):
                seiten = _xlsx(z)
                erg["titel"], erg["autor"] = _ooxml_meta(z)
            else:
                seiten = _odt(z)
                erg["titel"], erg["autor"] = _odf_meta(z)
        erg["seiten"] = [(i + 1, "text", t) for i, t in enumerate(seiten)]
        if not any(t.strip() for t in seiten):
            erg["status"] = "leer"
    except Verschluesselt:
        erg["status"] = "verschluesselt"
    except Exception as e:
        erg.update(status="fehler", fehler=fehlertext(e, pfad))
    return erg


class Verschluesselt(Exception):
    pass


# --------------------------------------------------------------------------- Word 97–2003 (.doc)

_FELD = re.compile(r"\x13[^\x13\x14\x15]*\x14?|\x15")       # Feldanweisung entfernen, Ergebnis behalten
_STEUER = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")


def _doc(pfad: str):
    import olefile
    import struct

    with olefile.OleFileIO(pfad) as ole:
        if not ole.exists("WordDocument"):
            raise ValueError("kein Word-Dokument")
        wd = ole.openstream("WordDocument").read()
        titel, autor = _ole_meta(ole)
        n_fib, = struct.unpack_from("<H", wd, 2)
        flags, = struct.unpack_from("<H", wd, 0x0A)
        if flags & 0x0100:                       # fEncrypted
            raise Verschluesselt()
        if n_fib < 0x00C1 or len(wd) < 0x01AA:   # vor Word 97: kein Piece-Table
            return [_druckbar(wd)], titel, autor
        tabelle = "1Table" if flags & 0x0200 else "0Table"
        if not ole.exists(tabelle):
            return [_druckbar(wd)], titel, autor
        tbl = ole.openstream(tabelle).read()
        fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
        clx = tbl[fc_clx:fc_clx + lcb_clx]

    # CLX: Prc-Eintraege (0x01) ueberspringen, dann Pcdt (0x02) mit dem Piece-Table
    i = 0
    while i < len(clx) and clx[i] == 0x01:
        cb, = struct.unpack_from("<H", clx, i + 1)
        i += 3 + cb
    if i >= len(clx) or clx[i] != 0x02:
        return [_druckbar(wd)], titel, autor
    lcb, = struct.unpack_from("<I", clx, i + 1)
    plc = clx[i + 5:i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    teile = []
    for k in range(n):
        fc, = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)
        anzahl = cps[k + 1] - cps[k]
        if fc & 0x40000000:                      # 8-Bit-Zeichen (cp1252)
            start = (fc & 0x3FFFFFFF) // 2
            teile.append(wd[start:start + anzahl].decode("cp1252", "replace"))
        else:                                    # UTF-16LE
            teile.append(wd[fc:fc + 2 * anzahl].decode("utf-16-le", "replace"))
    text = "".join(teile)
    text = _FELD.sub("", text)
    text = text.replace("\r", "\n").replace("\x0b", "\n").replace("\x0c", "\n").replace("\x07", "\t")
    text = _STEUER.sub("", text)
    return [_knapp(text)], titel, autor


def _druckbar(daten: bytes) -> str:
    """Notloesung fuer sehr alte Formate: lesbare Textstuecke herausziehen."""
    t = daten.decode("cp1252", "replace")
    stuecke = re.findall(r"[\w\s.,;:!?()\-–/%€$&'\"„“]{6,}", t)
    return _knapp("\n".join(s.strip() for s in stuecke if sum(c.isalpha() for c in s) >= 4))


def _ersatz_text(pfad: str, erg: dict) -> dict:
    with open(pfad, "rb") as f:
        roh = f.read(20 * 1024 * 1024)
    if roh.startswith(b"PK"):                    # eigentlich docx/xlsx
        fmt = "docx" if b"word/" in roh[:4096] else "xlsx"
        return office_text_zip(pfad, fmt, erg)
    t = roh.decode("utf-8", "replace") if not roh.startswith(b"{\\rtf") else _rtf(roh.decode("cp1252", "replace"))
    if "<html" in t[:2000].lower():
        t = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", t))
    erg["seiten"] = [(1, "text", _knapp(t))]
    erg["status"] = "text" if t.strip() else "leer"
    return erg


def office_text_zip(pfad: str, fmt: str, erg: dict) -> dict:
    with zipfile.ZipFile(pfad) as z:
        seiten = _docx(z) if fmt == "docx" else _xlsx(z)
        erg["titel"], erg["autor"] = _ooxml_meta(z)
    erg["seiten"] = [(i + 1, "text", t) for i, t in enumerate(seiten)]
    erg["status"] = "text" if any(t.strip() for t in seiten) else "leer"
    return erg


_RTF_TOKEN = re.compile(r"\\([a-z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)", re.I | re.S)
_RTF_ZIELE = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header", "footer", "headerl", "headerr",
    "footerl", "footerr", "themedata", "colorschememapping", "latentstyles", "datastore", "xmlnstbl",
    "listtable", "listoverridetable", "rsidtbl", "generator", "filetbl", "revtbl", "pgdsctbl", "fldinst",
    "bkmkstart", "bkmkend", "field", "xe", "tc", "pn", "pntext", "pntxta", "pntxtb", "objdata", "fcharset",
    "falt", "panose", "mmathPr", "defchp", "defpap", "wgrffmtfilter", "nonshppict", "shp", "shpinst", "sp",
}


def _rtf(t: str) -> str:
    """RTF in Klartext: Steuerwoerter, Tabellen fuer Schriften/Farben/Stile und Bilder entfallen."""
    stapel: list[tuple[int, bool]] = []
    ignorieren, uc_skip, rest_skip = False, 1, 0
    aus: list[str] = []
    for m in _RTF_TOKEN.finditer(t):
        wort, arg, hexz, zeichen, klammer, txt = m.groups()
        if klammer:
            rest_skip = 0
            if klammer == "{":
                stapel.append((uc_skip, ignorieren))
            elif stapel:
                uc_skip, ignorieren = stapel.pop()
        elif zeichen:
            rest_skip = 0
            if zeichen == "*":
                ignorieren = True
            elif not ignorieren:
                aus.append({"~": " ", "_": "-", "-": ""}.get(zeichen, zeichen if zeichen in "{}\\" else ""))
        elif wort:
            rest_skip = 0
            if wort in _RTF_ZIELE:
                ignorieren = True
            elif wort == "uc":
                uc_skip = int(arg or 1)
            elif ignorieren:
                continue
            elif wort in ("par", "line", "sect", "page", "row"):
                aus.append("\n")
            elif wort in ("tab", "cell"):
                aus.append("\t")
            elif wort == "u" and arg:
                c = int(arg)
                aus.append(chr(c + 65536 if c < 0 else c))
                rest_skip = uc_skip
        elif hexz:
            if rest_skip:
                rest_skip -= 1
            elif not ignorieren:
                aus.append(bytes([int(hexz, 16)]).decode("cp1252", "replace"))
        elif txt:
            if rest_skip:
                rest_skip -= 1
            elif not ignorieren:
                aus.append(txt)
    return "".join(aus)


def _ole_meta(ole):
    try:
        m = ole.get_metadata()
        dek = lambda b: b.decode("cp1252", "replace").strip() if isinstance(b, bytes) else (b or None)  # noqa: E731
        return dek(m.title) or None, dek(m.author) or None
    except Exception:
        return None, None


# --------------------------------------------------------------------------- Excel 97–2003 (.xls)

def _xls(pfad: str):
    import xlrd

    try:
        buch = xlrd.open_workbook(pfad, on_demand=True)
    except xlrd.biffh.XLRDError as e:
        if "encrypt" in str(e).lower() or "password" in str(e).lower():
            raise Verschluesselt()
        raise
    seiten, gesamt = [], 0
    try:
        for idx in range(buch.nsheets):
            blatt = buch.sheet_by_index(idx)
            if gesamt > MAX_MAPPE:
                seiten.append(f"Tabellenblatt: {blatt.name}\n(nicht indiziert – Arbeitsmappe zu groß)")
                continue
            zeilen, laenge = [f"Tabellenblatt: {blatt.name}"], 0
            for r in range(blatt.nrows):
                zellen = []
                for c in blatt.row(r):
                    if c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                        continue
                    if c.ctype == xlrd.XL_CELL_NUMBER:
                        w = f"{c.value:.10g}"
                    elif c.ctype == xlrd.XL_CELL_DATE:
                        try:
                            j, mo, t, h, mi, s = xlrd.xldate_as_tuple(c.value, buch.datemode)
                            w = f"{t:02d}.{mo:02d}.{j}" + (f" {h:02d}:{mi:02d}" if h or mi else "")
                        except Exception:
                            w = str(c.value)
                    elif c.ctype == xlrd.XL_CELL_BOOLEAN:
                        w = "WAHR" if c.value else "FALSCH"
                    else:
                        w = str(c.value).strip()
                    if w:
                        zellen.append(w)
                if zellen:
                    z = "\t".join(zellen)
                    zeilen.append(z)
                    laenge += len(z)
                    if laenge > MAX_TEXT:
                        break
            buch.unload_sheet(idx)
            seiten.append(_knapp("\n".join(zeilen)))
            gesamt += len(seiten[-1])
        meta_autor = (buch.user_name or "").strip() or None
    finally:
        buch.release_resources()
    return seiten, None, meta_autor


# --------------------------------------------------------------------------- Word

def _docx_teil(daten: bytes) -> str:
    aus: list[str] = []
    for ereignis, e in ET.iterparse(_als_datei(daten), events=("start", "end")):
        tag = _lokal(e.tag)
        if ereignis == "end":
            if tag == "t" and e.text:
                aus.append(e.text)
            elif tag == "tab":
                aus.append("\t")
            elif tag in ("br", "cr"):
                aus.append("\n")
            elif tag == "p":
                aus.append("\n")
            elif tag == "tc":
                aus.append("\t")
            if tag in ("p", "tbl"):
                e.clear()
    return "".join(aus)


def _docx(z: zipfile.ZipFile) -> list[str]:
    namen = z.namelist()
    teile = ["word/document.xml"]
    teile += sorted(n for n in namen if re.fullmatch(r"word/(header|footer)\d*\.xml", n))
    teile += [n for n in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml") if n in namen]
    texte = []
    for n in teile:
        d = _lies(z, n)
        if d:
            texte.append(_docx_teil(d))
    return [_knapp("\n".join(t for t in texte if t.strip()))]


# --------------------------------------------------------------------------- Excel

# Eingebaute Zahlenformate von Excel, die Datum/Zeit darstellen (ECMA-376, 18.8.30)
_DATUM_EINGEBAUT = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
# In Formatcodes zaehlen Anfuehrungszeichen, Escapes (\x) und Klammern ([Rot], [>=100], [$€-407]) nicht
_FORMAT_LITERALE = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]')
_DATUM_ZEICHEN = re.compile(r"[ymdhsYMDHS]")


def _ist_datumsformat(code: str) -> bool:
    """Eigenes Zahlenformat mit Tages-, Monats-, Jahres- oder Zeitzeichen ausserhalb von Literalen?"""
    return bool(_DATUM_ZEICHEN.search(_FORMAT_LITERALE.sub("", code or "")))


def _xlsx_datumsstile(z: zipfile.ZipFile) -> set[str]:
    """Indizes (``s``-Attribut der Zellen) der Zellformate, die ein Datum oder eine Zeit anzeigen."""
    d = _lies(z, "xl/styles.xml")
    if not d:
        return set()
    try:
        wurzel = ET.fromstring(d)
    except ET.ParseError:
        return set()
    eigene: dict[int, str] = {}
    for nf in wurzel.iter(S + "numFmt"):
        try:
            eigene[int(nf.get("numFmtId"))] = nf.get("formatCode") or ""
        except (TypeError, ValueError):
            continue
    xfs = wurzel.find(S + "cellXfs")
    if xfs is None:
        return set()
    stile = set()
    for i, xf in enumerate(xfs.findall(S + "xf")):
        try:
            fid = int(xf.get("numFmtId", "0"))
        except ValueError:
            continue
        if fid in _DATUM_EINGEBAUT or (fid in eigene and _ist_datumsformat(eigene[fid])):
            stile.add(str(i))
    return stile


def _excel_datum(wert: str, date1904: bool) -> str | None:
    """Excel-Seriennummer -> ``TT.MM.JJJJ[ HH:MM]`` (wie bei .xls), reine Uhrzeit -> ``HH:MM``.

    1900-System: Tag 1 = 01.01.1900, Tag 60 ist der erfundene 29.02.1900 (bleibt Zahl).
    1904-System (Mac): Tag 0 = 01.01.1904.
    """
    try:
        w = float(wert)
    except ValueError:
        return None
    if date1904:
        basis = datetime(1904, 1, 1)
    elif w >= 61:
        basis = datetime(1899, 12, 30)
    elif 1 <= w < 60:
        basis = datetime(1899, 12, 31)
    elif 0 <= w < 1:
        basis = None
    else:
        return None
    sekunden = round(w * 86400)
    if basis is None:
        h, m = divmod(sekunden // 60, 60)
        return f"{h:02d}:{m:02d}"
    try:
        dt = basis + timedelta(seconds=sekunden)
    except OverflowError:
        return None
    text = f"{dt.day:02d}.{dt.month:02d}.{dt.year}"
    if dt.hour or dt.minute:
        text += f" {dt.hour:02d}:{dt.minute:02d}"
    return text


def _xlsx(z: zipfile.ZipFile) -> list[str]:
    geteilt: list[str] = []
    d = _lies(z, "xl/sharedStrings.xml")
    if d:
        for _, e in ET.iterparse(_als_datei(d)):
            if e.tag == S + "si":
                # <si><t/></si> oder <si><r><t/></r>…</si>; phonetische Hilfen (rPh) auslassen
                teile = []
                for k in e:
                    if k.tag == S + "t":
                        teile.append(k.text or "")
                    elif k.tag == S + "r":
                        teile += [t.text or "" for t in k.iter(S + "t")]
                geteilt.append("".join(teile))
                e.clear()

    # Blattnamen und Dateien in der Reihenfolge der Arbeitsmappe
    blaetter: list[tuple[str, str]] = []
    wb = _lies(z, "xl/workbook.xml")
    rels = _lies(z, "xl/_rels/workbook.xml.rels")
    ziel = {}
    if rels:
        for r in ET.fromstring(rels).iter(PR + "Relationship"):
            t = r.get("Target", "")
            ziel[r.get("Id")] = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join("xl", t))
    date1904 = False
    if wb:
        mappe = ET.fromstring(wb)
        for s in mappe.iter(S + "sheet"):
            p = ziel.get(s.get(R + "id"))
            if p:
                blaetter.append((s.get("name") or "", p))
        pr = mappe.find(S + "workbookPr")
        date1904 = pr is not None and (pr.get("date1904") or "").lower() in ("1", "true")
    if not blaetter:
        blaetter = [(posixpath.basename(n), n) for n in sorted(z.namelist())
                    if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)]
    datumsstile = _xlsx_datumsstile(z)

    seiten = []
    gesamt = 0
    for name, datei in blaetter:
        if gesamt > MAX_MAPPE:
            seiten.append(f"Tabellenblatt: {name}\n(nicht indiziert – Arbeitsmappe zu groß)")
            continue
        d = _lies(z, datei)
        if not d:
            continue
        zeilen, laenge = [f"Tabellenblatt: {name}"], 0
        for _, e in ET.iterparse(_als_datei(d)):
            if e.tag != S + "row":
                continue
            zellen = []
            for c in e.iter(S + "c"):
                typ = c.get("t")
                if typ == "inlineStr":
                    wert = "".join(t.text or "" for t in c.iter(S + "t"))
                else:
                    v = c.find(S + "v")
                    wert = v.text if v is not None and v.text else ""
                    if typ == "s" and wert:
                        try:
                            wert = geteilt[int(wert)]
                        except (ValueError, IndexError):
                            pass
                    elif typ == "b":
                        wert = "WAHR" if wert == "1" else "FALSCH"
                    elif typ in (None, "n") and wert:
                        datum = _excel_datum(wert, date1904) if c.get("s") in datumsstile else None
                        if datum:
                            wert = datum                   # 45363 -> 12.03.2024
                        elif len(wert) > 10 and ("." in wert or "E" in wert):
                            try:
                                wert = f"{float(wert):.10g}"   # 15880.219999999 -> 15880.22
                            except ValueError:
                                pass
                if wert:
                    zellen.append(wert.strip())
            e.clear()
            if zellen:
                z_text = "\t".join(zellen)
                zeilen.append(z_text)
                laenge += len(z_text)
                if laenge > MAX_TEXT:
                    break
        seiten.append(_knapp("\n".join(zeilen)))
        gesamt += len(seiten[-1])
    return seiten


# --------------------------------------------------------------------------- OpenDocument

_ODT_ABSATZ = {"p", "h", "list-item", "table-row"}


def _odt(z: zipfile.ZipFile) -> list[str]:
    d = _lies(z, "content.xml")
    if not d:
        return [""]
    wurzel = ET.fromstring(d)
    aus: list[str] = []

    def lauf(e):
        tag = _lokal(e.tag)
        if tag == "s":
            aus.append(" " * int(e.get(ODT_TEXT + "c", "1") or 1))
        elif tag == "tab":
            aus.append("\t")
        elif tag == "line-break":
            aus.append("\n")
        if e.text and tag not in ("s",):
            aus.append(e.text)
        for k in e:
            if _lokal(k.tag) in ("automatic-styles", "font-face-decls", "scripts"):
                continue
            lauf(k)
            if k.tail:
                aus.append(k.tail)
        if tag in _ODT_ABSATZ:
            aus.append("\n")
        elif tag == "table-cell":
            aus.append("\t")

    lauf(wurzel)
    return [_knapp("".join(aus))]


# --------------------------------------------------------------------------- Metadaten

def _ooxml_meta(z):
    d = _lies(z, "docProps/core.xml")
    if not d:
        return None, None
    try:
        w = ET.fromstring(d)
    except ET.ParseError:
        return None, None
    titel = (w.findtext(DC + "title") or "").strip() or None
    autor = (w.findtext(DC + "creator") or "").strip() or None
    return titel, autor


def _odf_meta(z):
    d = _lies(z, "meta.xml")
    if not d:
        return None, None
    try:
        w = ET.fromstring(d)
    except ET.ParseError:
        return None, None
    titel = next((e.text for e in w.iter(DC + "title") if e.text), None)
    autor = next((e.text for e in w.iter(ODT_META + "initial-creator") if e.text), None) or \
        next((e.text for e in w.iter(DC + "creator") if e.text), None)
    return titel, autor


def _als_datei(daten: bytes):
    import io
    return io.BytesIO(daten)
