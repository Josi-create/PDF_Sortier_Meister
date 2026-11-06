"""Synthetische Testdateien fuer die Dokumentensuche (tests/test_suche_*.py).

Alle Inhalte entstehen im Test; es werden keine echten Dokumente verwendet.
Die Funktionen ``absturz`` und ``haengt`` dienen als Auftraege fuer echte
Arbeitsprozesse (Absturz- und Zeitlimit-Tests) und muessen deshalb in einem
importierbaren Modul liegen.
"""

from __future__ import annotations

import os
import struct
import time
import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from src.search.konfig import SearchConfig


def konfig_fuer(tmp_path: Path, **kw) -> SearchConfig:
    """SearchConfig mit Datenbank unter tmp_path; OCR und Mails standardmaessig aus."""
    kw.setdefault("aktiv", True)
    kw.setdefault("db_pfad", str(tmp_path / "suche" / "suche.db"))
    kw.setdefault("prozesse", 1)
    kw.setdefault("ocr_aktiv", False)
    kw.setdefault("mails_aktiv", False)
    # Sicherungskopien der Textebene nie ins echte Datenverzeichnis
    kw.setdefault("textebene_sicherung_ordner", str(tmp_path / "textebene_sicherung"))
    return SearchConfig(**kw)


# --------------------------------------------------------------------------- Arbeitsprozess-Auftraege

def absturz(pfad: str) -> dict:
    """Simuliert einen Absturz des Arbeitsprozesses (z. B. durch eine beschaedigte Datei)."""
    os._exit(3)


def haengt(pfad: str) -> dict:
    """Simuliert einen haengenden Arbeitsprozess."""
    time.sleep(60)
    return {}


# --------------------------------------------------------------------------- PDF

def pdf_mit_text(pfad: Path, texte: list[str], titel: str | None = None, autor: str | None = None) -> Path:
    import pymupdf

    doc = pymupdf.open()
    for t in texte:
        page = doc.new_page()
        page.insert_text((72, 72), t, fontsize=11)
    if titel or autor:
        doc.set_metadata({"title": titel or "", "author": autor or ""})
    doc.save(str(pfad))
    doc.close()
    return pfad


def _png_bild() -> bytes:
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 40, 40), False)
    pix.clear_with(255)
    for x in range(10, 30):
        for y in range(10, 30):
            pix.set_pixel(x, y, (0,))
    return pix.tobytes("png")


def pdf_mit_bild(pfad: Path, seiten: int = 1, text_seiten: list[str] | None = None) -> Path:
    """Scan ohne Textebene: jede Seite enthaelt nur ein Bild; optional vorweg Seiten mit Text."""
    import pymupdf

    doc = pymupdf.open()
    for t in text_seiten or []:
        doc.new_page().insert_text((72, 72), t, fontsize=11)
    png = _png_bild()
    for _ in range(seiten):
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(50, 50, 250, 250), stream=png)
    doc.save(str(pfad))
    doc.close()
    return pfad


def scan_pdf(pfad: Path, zeilen: list[str], seiten: int = 1, drehung: int = 0, dpi: int = 150,
             cropbox: tuple | None = None) -> Path:
    """Gescannte Seiten wie aus dem Scanner: Text gerendert, nur das Bild in einer neuen PDF.

    ``drehung``: Seitendrehung (``/Rotate``); das Bild ist so eingesetzt, dass
    die Seite aufrecht angezeigt wird (wie ein quer eingelegter Scan).
    ``cropbox`` (ungedrehte Koordinaten) verschiebt den sichtbaren Ausschnitt.
    """
    import pymupdf

    quelle = pymupdf.open()
    q = quelle.new_page(width=595, height=842)
    for i, zeile in enumerate(zeilen):
        q.insert_text((72, 100 + 36 * i), zeile, fontsize=20)
    png = q.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).tobytes("png")
    quelle.close()
    doc = pymupdf.open()
    for _ in range(seiten):
        seite = doc.new_page(width=842, height=595) if drehung in (90, 270) else doc.new_page(width=595, height=842)
        seite.insert_image(seite.rect, stream=png, rotate=drehung)
        if cropbox:
            seite.set_cropbox(pymupdf.Rect(*cropbox))
        if drehung:
            seite.set_rotation(drehung)
    doc.save(str(pfad), deflate=True)
    doc.close()
    return pfad


def text_pdf(breite: float, hoehe: float, text: str, sichtbar: bool = False) -> bytes:
    """Reine Text-PDF wie von Tesseract (``textonly_pdf=1``): unsichtbarer Text in der Schrift ``GlyphLessFont``.

    ``sichtbar``: schwarzer Text und ein Quadrat oben links (Geometrie-Tests).
    """
    import pymupdf

    doc = pymupdf.open()
    seite = doc.new_page(width=breite, height=hoehe)
    if sichtbar:
        seite.draw_rect(pymupdf.Rect(10, 10, 60, 60), color=(0, 0, 0), fill=(0, 0, 0))
    seite.insert_text((80, 40), text, fontsize=12, render_mode=0 if sichtbar else 3, fontname="helv")
    for f in seite.get_fonts():
        doc.xref_set_key(f[0], "BaseFont", "/GlyphLessFont")
    daten = doc.tobytes()
    doc.close()
    return daten


def fake_tesseract(monkeypatch, text: str = "Erkannter Scantext") -> list:
    """``subprocess.run`` in ``extract`` ersetzen: Text nach stdout bzw. Text und Text-PDF in Dateien.

    Liefert die Liste der Aufrufe (zum Zaehlen). Die Text-PDF hat die Groesse
    des gelieferten Seitenbilds bei der angegebenen Aufloesung, wie bei Tesseract.
    """
    import subprocess

    import pymupdf

    from src.search import extract

    aufrufe: list = []

    def run(args, **kw):
        aufrufe.append(list(args))
        if args[2] == "stdout":
            return subprocess.CompletedProcess(args, 0, stdout=text.encode("utf-8"), stderr=b"")
        basis = args[2]
        dpi = int(args[args.index("--dpi") + 1])
        pix = pymupdf.Pixmap(kw["input"])
        Path(basis + ".txt").write_text(text, encoding="utf-8")
        Path(basis + ".pdf").write_bytes(text_pdf(pix.width * 72 / dpi, pix.height * 72 / dpi, text))
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(extract.subprocess, "run", run)
    return aufrufe


def pdf_verschluesselt(pfad: Path, text: str = "Geheim") -> Path:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(str(pfad), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="passwort", owner_pw="passwort")
    doc.close()
    return pfad


# --------------------------------------------------------------------------- Office (ZIP + XML)

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_ODF = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"')


def _core_xml(titel: str | None, autor: str | None) -> str:
    return ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{escape(titel or '')}</dc:title><dc:creator>{escape(autor or '')}</dc:creator>"
            "</cp:coreProperties>")


def docx(pfad: Path, absaetze: list[str], kopf: str | None = None, fuss: str | None = None,
         titel: str | None = None, autor: str | None = None) -> Path:
    def body(ps):
        return "".join(f"<w:p><w:r><w:t>{escape(p)}</w:t></w:r></w:p>" for p in ps)

    with zipfile.ZipFile(pfad, "w") as z:
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document {_W}><w:body>{body(absaetze)}</w:body></w:document>')
        if kopf:
            z.writestr("word/header1.xml", f"<w:hdr {_W}>{body([kopf])}</w:hdr>")
        if fuss:
            z.writestr("word/footer1.xml", f"<w:ftr {_W}>{body([fuss])}</w:ftr>")
        if titel or autor:
            z.writestr("docProps/core.xml", _core_xml(titel, autor))
    return pfad


# Zellformate (Index = ``s``-Attribut) in der styles.xml der xlsx-Testdateien
XLSX_STILE = {
    0: 0,     # Standard
    1: 14,    # eingebautes Datum (m/d/yy)
    2: 164,   # eigenes Datum + Uhrzeit
    3: 165,   # Zahl mit "d" in Anfuehrungszeichen - kein Datum
    4: 166,   # eigenes Datum mit Sprachkennung [$-407]
    5: 21,    # eingebaute Uhrzeit (h:mm:ss)
}
_XLSX_NUMFMTS = {164: "dd.mm.yyyy hh:mm", 165: '#,##0.00 "d"', 166: "[$-407]d. mmmm yyyy;@"}


def _excel_seriennummer(w, date1904: bool) -> float:
    basis = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
    dt = w if isinstance(w, datetime) else datetime(w.year, w.month, w.day)
    delta = dt - basis
    return delta.days + delta.seconds / 86400


def xlsx(pfad: Path, blaetter: dict[str, list[list]], date1904: bool = False) -> Path:
    """Zeichenketten landen in sharedStrings, mit Praefix ``inline:`` als inlineStr; Zahlen und bool direkt.

    ``date``/``datetime`` werden als Seriennummer mit Datums-Zellformat geschrieben
    (Stil 1 bzw. 2), ein Tupel ``(zahl, stil)`` mit dem angegebenen Stil aus ``XLSX_STILE``.
    """
    strings: list[str] = []

    def zelle(ref: str, w) -> str:
        if isinstance(w, bool):
            return f'<c r="{ref}" t="b"><v>{1 if w else 0}</v></c>'
        if isinstance(w, tuple):
            zahl, stil = w
            return f'<c r="{ref}" s="{stil}"><v>{zahl!r}</v></c>'
        if isinstance(w, datetime):
            return f'<c r="{ref}" s="2"><v>{_excel_seriennummer(w, date1904)!r}</v></c>'
        if isinstance(w, date):
            return f'<c r="{ref}" s="1"><v>{int(_excel_seriennummer(w, date1904))}</v></c>'
        if isinstance(w, (int, float)):
            return f'<c r="{ref}"><v>{w!r}</v></c>'
        s = str(w)
        if s.startswith("inline:"):
            return f'<c r="{ref}" t="inlineStr"><is><t>{escape(s[7:])}</t></is></c>'
        strings.append(s)
        return f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'

    sheets = {}
    for i, (name, zeilen) in enumerate(blaetter.items(), 1):
        rows = "".join(
            f'<row r="{ri}">' + "".join(zelle(f"{chr(65 + ci)}{ri}", w) for ci, w in enumerate(zeile)) + "</row>"
            for ri, zeile in enumerate(zeilen, 1)
        )
        sheets[f"xl/worksheets/sheet{i}.xml"] = f"<worksheet {_S}><sheetData>{rows}</sheetData></worksheet>"
    with zipfile.ZipFile(pfad, "w") as z:
        pr = '<workbookPr date1904="1"/>' if date1904 else ""
        z.writestr("xl/workbook.xml", f"<workbook {_S} {_R}>{pr}<sheets>" + "".join(
            f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(blaetter, 1)
        ) + "</sheets></workbook>")
        z.writestr("xl/styles.xml", f"<styleSheet {_S}><numFmts>" + "".join(
            f'<numFmt numFmtId="{i}" formatCode="{escape(c, {chr(34): "&quot;"})}"/>' for i, c in _XLSX_NUMFMTS.items()
        ) + "</numFmts><cellXfs>" + "".join(
            f'<xf numFmtId="{XLSX_STILE[i]}"/>' for i in sorted(XLSX_STILE)
        ) + "</cellXfs></styleSheet>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
                       f'<Relationship Id="rId{i}" Type="x" Target="worksheets/sheet{i}.xml"/>'
                       for i in range(1, len(blaetter) + 1)) + "</Relationships>")
        z.writestr("xl/sharedStrings.xml",
                   f"<sst {_S}>" + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")
        for n, x in sheets.items():
            z.writestr(n, x)
    return pfad


def odt(pfad: Path, absaetze: list[str], titel: str | None = None) -> Path:
    body = "".join(f"<text:p>{escape(p)}</text:p>" for p in absaetze)
    with zipfile.ZipFile(pfad, "w") as z:
        z.writestr("content.xml", f"<office:document-content {_ODF}><office:body><office:text>{body}"
                                  "</office:text></office:body></office:document-content>")
        if titel:
            z.writestr("meta.xml", f'<office:document-meta {_ODF} xmlns:dc="http://purl.org/dc/elements/1.1/">'
                                   f"<office:meta><dc:title>{escape(titel)}</dc:title></office:meta>"
                                   "</office:document-meta>")
    return pfad


# --------------------------------------------------------------------------- OLE2-Container (.doc, verschluesselte Office-Dateien)

_FREE, _ENDE, _FATSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD


def ole_container(streams: dict[str, bytes]) -> bytes:
    """Minimaler OLE2-Compound-File (512-Byte-Sektoren, ein FAT-Sektor, nur reguläre Streams).

    Streams werden auf mindestens 4096 Byte aufgefuellt, damit kein Mini-Stream noetig ist.
    """
    sek = 512
    fat = [_FATSECT, _ENDE]              # Sektor 0 = FAT, Sektor 1 = Verzeichnis
    daten, eintraege = [], []
    naechster = 2
    for name, inhalt in streams.items():
        inhalt = inhalt + b"\x00" * max(0, 4096 - len(inhalt))
        n = (len(inhalt) + sek - 1) // sek
        start = naechster
        for k in range(n):
            fat.append(naechster + 1 if k < n - 1 else _ENDE)
            naechster += 1
        daten.append(inhalt + b"\x00" * (n * sek - len(inhalt)))
        eintraege.append((name, start, len(inhalt)))
    assert len(fat) <= 128, "zu gross fuer einen FAT-Sektor"
    fat += [_FREE] * (128 - len(fat))

    def eintrag(name, typ, links, rechts, kind, start, groesse):
        n16 = name.encode("utf-16-le") + b"\x00\x00"
        return (n16.ljust(64, b"\x00") + struct.pack("<HBBIII", len(n16), typ, 1, links, rechts, kind)
                + b"\x00" * 16 + struct.pack("<I", 0) + b"\x00" * 16 + struct.pack("<IQ", start, groesse))

    verzeichnis = [eintrag("Root Entry", 5, _FREE, _FREE, 1 if eintraege else _FREE, _ENDE, 0)]
    for i, (name, start, groesse) in enumerate(eintraege):
        rechts = i + 2 if i + 1 < len(eintraege) else _FREE
        verzeichnis.append(eintrag(name, 2, _FREE, rechts, _FREE, start, groesse))
    kopf = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
            + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
            + struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, _ENDE, 0, _ENDE, 0)
            + struct.pack("<I", 0) + b"\xff" * (108 * 4))
    assert len(kopf) == 512
    return (kopf + struct.pack("<128I", *fat) + b"".join(verzeichnis).ljust(sek, b"\x00") + b"".join(daten))


def doc_word97(pfad: Path, text: str, unicode: bool = False, verschluesselt: bool = False) -> Path:
    """Word-97-Dokument mit Piece-Table (ein Stueck Text, 8-Bit cp1252 oder UTF-16LE)."""
    wd = bytearray(4096)
    struct.pack_into("<H", wd, 0, 0xA5EC)
    struct.pack_into("<H", wd, 2, 0x00C1)                         # nFib: Word 97
    struct.pack_into("<H", wd, 0x0A, 0x0200 | (0x0100 if verschluesselt else 0))  # 1Table, fEncrypted
    offset = 0x800
    if unicode:
        roh = text.encode("utf-16-le")
        fc = offset
    else:
        roh = text.encode("cp1252")
        fc = 0x40000000 | (offset * 2)
    wd[offset:offset + len(roh)] = roh
    cps = struct.pack("<II", 0, len(text))
    pcd = struct.pack("<HIH", 0, fc, 0)
    plc = cps + pcd
    clx = b"\x02" + struct.pack("<I", len(plc)) + plc
    struct.pack_into("<II", wd, 0x01A2, 0, len(clx))              # fcClx, lcbClx
    pfad.write_bytes(ole_container({"WordDocument": bytes(wd), "1Table": clx}))
    return pfad


# --------------------------------------------------------------------------- Mails

def mail_roh(betreff: str, von: str = "absender@example.invalid", an: str = "empfaenger@example.invalid",
             datum: str = "Wed, 10 Jan 2024 10:00:00 +0100", text: str = "Hallo", html: bool = False,
             anhang: str | None = None, mozilla_status: str | None = None) -> bytes:
    """RFC-822-Mail als Bytes (``.eml``); ``mozilla_status`` ergaenzt die Thunderbird-Kopfzeile."""
    zeilen = []
    if mozilla_status is not None:
        zeilen += [f"X-Mozilla-Status: {mozilla_status}", "X-Mozilla-Status2: 00000000"]
    zeilen += [f"Subject: {betreff}", f"From: {von}", f"To: {an}", f"Date: {datum}", "MIME-Version: 1.0"]
    if anhang:
        grenze = "GRENZE123"
        zeilen += [f'Content-Type: multipart/mixed; boundary="{grenze}"', "",
                   f"--{grenze}", "Content-Type: text/plain; charset=utf-8", "", text, "",
                   f"--{grenze}", f'Content-Type: application/pdf; name="{anhang}"',
                   f'Content-Disposition: attachment; filename="{anhang}"', "", "JVBERi0=", "", f"--{grenze}--"]
    elif html:
        zeilen += ["Content-Type: text/html; charset=utf-8", "",
                   f"<html><body><p>{text}</p><script>alert(1)</script></body></html>"]
    else:
        zeilen += ["Content-Type: text/plain; charset=utf-8", "", text]
    return ("\r\n".join(zeilen) + "\r\n").encode("utf-8")


def mbox(pfad: Path, mails: list[bytes]) -> Path:
    """Thunderbird-mbox samt ``.msf``-Markierung; jede Mail bekommt eine ``From - ``-Trennzeile."""
    with open(pfad, "wb") as f:
        for roh in mails:
            f.write(b"From - Wed Jan 10 10:00:00 2024\n" + roh + b"\n")
    Path(str(pfad) + ".msf").write_bytes(b"")
    return pfad


# --------------------------------------------------------------------------- PDFsuche-Projektordner (Uebernahme)

def v1_datenbank(pfad) -> int:
    """Datenbank im Stand von PDFsuche (Version 1) mit einem OCR-Dokument anlegen; liefert dessen id."""
    from src.search import db

    con = db.verbinde(pfad)
    con.executescript(db.SCHEMA)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', '1')")
    cur = con.execute(
        "INSERT INTO dokumente (pfad, datei, name, ordner, typ, format, groesse, mtime_ns, datum, seiten, "
        "textstatus, ocr_seiten, prioritaet, indiziert_am) VALUES (?, ?, ?, ?, 'pdf', 'pdf', 10, 1, 1.0, 1, "
        "'ocr', 1, 9, '2026-01-01T00:00:00')",
        (os.path.join("alt", "a.pdf"), os.path.join("alt", "a.pdf"), "a.pdf", "alt"))
    dok_id = cur.lastrowid
    con.execute("INSERT INTO seiten (dok_id, seite, quelle, text) VALUES (?, 1, 'ocr', 'Alter OCR-Text')", (dok_id,))
    con.commit()
    con.close()
    return dok_id


def pdfsuche_projekt(tmp_path: Path) -> Path:
    """Synthetischer Projektordner des frueheren Programms PDFsuche: config.toml + data/pdfsuche.db mit zwei Dokumenten."""
    ordner = tmp_path / "PDFsuche"
    (ordner / "data").mkdir(parents=True)
    ablage = tmp_path / "Ablage"
    ablage.mkdir(exist_ok=True)
    (ablage / "Rechnung.md").write_text("# Rechnung\nBetrag 49,99 Euro von Telekom", encoding="utf-8")
    pdf_mit_text(ablage / "Brief.pdf", ["Sehr geehrte Frau Beispiel"])
    (ordner / "config.toml").write_text(
        '[datenbank]\npfad = "data/pdfsuche.db"\n\n[suche]\nprioritaet = ["' + ablage.as_posix() + '"]\n'
        'wurzeln = ["' + ablage.as_posix() + '"]\n\n[ocr]\naktiv = false\n\n[web]\nport = 18425\n',
        encoding="utf-8",
    )
    konfig = konfig_fuer(tmp_path, db_pfad=str(ordner / "data" / "pdfsuche.db"),
                         wurzeln=[str(ablage)], prioritaet=[str(ablage)])
    from src.search.indexer import Indexer

    assert Indexer(konfig, synchron=True).lauf() == 0
    return ordner
