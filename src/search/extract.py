"""Textgewinnung der Dokumentensuche – laeuft in den Arbeitsprozessen (ProcessPool).

Uebernommen aus PDFsuche (``extract.py``). Alle Funktionen geben einfache
dicts/lists zurueck (picklebar) und importieren PyMuPDF erst bei Bedarf.
"""

from __future__ import annotations

import email
import hashlib
import html
import os
import re
import subprocess
from email import policy
from email.utils import parsedate_to_datetime
from pathlib import Path

from src.search import plattform

MAX_TEXT_PRO_SEITE = 2_000_000
MAX_MAIL_ROH = 6 * 1024 * 1024
MAX_FEHLERTEXT = 200
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # OLE2-Container (Outlook .msg, Office 97)


def fehlertext(e: BaseException | str, pfad: str | None = None, max_len: int = MAX_FEHLERTEXT) -> str:
    """Kurzer Fehlertext fuer die Datenbank: Ausnahmetyp und Meldung in einer Zeile.

    Der Dateipfad steht schon in der Zeile des Dokuments und wird aus der
    Meldung entfernt (auch in Schreibweisen mit ``/`` oder verdoppelten ``\\``);
    Zeilenumbrueche fallen weg, der Text wird gekappt.
    """
    if isinstance(e, BaseException):
        meldung = str(e)
        text = f"{type(e).__name__}: {meldung}" if meldung else type(e).__name__
    else:
        text = str(e)
    if pfad:
        for variante in sorted({pfad, pfad.replace("\\", "/"), pfad.replace("\\", "\\\\")}, key=len, reverse=True):
            text = text.replace(variante, "<Datei>")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _popen_kwargs() -> dict:
    """Unterprozess (Tesseract) ohne Konsolenfenster (``plattform.popen_flags``)."""
    return plattform.popen_flags()


def setze_niedrige_prioritaet() -> None:
    """Prozess im Hintergrundmodus (``plattform.niedrige_prioritaet_setzen``)."""
    plattform.niedrige_prioritaet_setzen()


def arbeiter_start(hintergrund: bool) -> None:
    """Initializer der Arbeitsprozesse: Prioritaet, Elternwaechter (macOS/Linux), PyMuPDF-Meldungen aus."""
    os.environ["OMP_THREAD_LIMIT"] = "1"
    if hintergrund:
        setze_niedrige_prioritaet()
    plattform.elternwaechter_starten()
    try:
        import pymupdf
        pymupdf.TOOLS.mupdf_display_errors(False)
        pymupdf.TOOLS.mupdf_display_warnings(False)
    except Exception:
        pass


def _saeubern(t: str) -> str:
    t = t.replace("\x00", "")
    return t[:MAX_TEXT_PRO_SEITE]


# --------------------------------------------------------------------------- PDF

def pdf_text(pfad: str, min_zeichen: int) -> dict:
    """Textebene lesen. Seiten ohne Text, aber mit Bild, werden fuer OCR markiert.

    Dazu kommen ``bild_hashes`` (Seite -> Hash der Bild-Streams, fuer den
    OCR-Cache; nur fuer Seiten ohne Text) und ``metadaten`` (PDFSM-Felder aus
    Info-Dict und XMP, siehe ``pdf_metadaten``).
    """
    import pymupdf

    erg = {"seiten": [], "anzahl": 0, "ohne_text": [], "titel": None, "autor": None, "status": "text", "fehler": None,
           "bild_hashes": {}, "metadaten": {}}
    try:
        doc = pymupdf.open(pfad)
    except Exception as e:
        erg.update(status="fehler", fehler=f"Öffnen: {fehlertext(e, pfad)}")
        return erg
    try:
        if doc.needs_pass and not doc.authenticate(""):
            erg.update(status="verschluesselt", anzahl=doc.page_count)
            return erg
        md = doc.metadata or {}
        erg["titel"] = (md.get("title") or "").strip() or None
        erg["autor"] = (md.get("author") or "").strip() or None
        erg["anzahl"] = doc.page_count
        try:
            erg["metadaten"] = pdf_metadaten(doc)
        except Exception:
            erg["metadaten"] = {}
        for i in range(doc.page_count):
            try:
                seite = doc[i]
                t = _saeubern(seite.get_text("text"))
            except Exception:
                t = ""
                seite = None
            if len(t.strip()) < min_zeichen and seite is not None and _hat_bild(seite):
                erg["ohne_text"].append(i + 1)
                erg["seiten"].append((i + 1, "ohne_text", t))
                h = _bild_hash(doc, seite)
                if h:
                    erg["bild_hashes"][i + 1] = h
            else:
                erg["seiten"].append((i + 1, "text", t))
        if erg["ohne_text"]:
            erg["status"] = "ocr_ausstehend"
        elif not any(t.strip() for _, _, t in erg["seiten"]):
            erg["status"] = "leer"
    except Exception as e:
        erg.update(status="fehler", fehler=f"Lesen: {fehlertext(e, pfad)}")
    finally:
        doc.close()
    return erg


def _hat_bild(seite) -> bool:
    try:
        if seite.get_images(full=False):
            return True
        # Manche Scanner legen das Bild als Inline-Bild ab
        return any(b.get("type") == 1 for b in seite.get_text("dict", flags=0)["blocks"])
    except Exception:
        return False


def _bild_hash(doc, seite) -> str | None:
    """BLAKE2b (16 Byte) ueber die Bild-Streams einer Seite (Inline-Bilder: Content-Stream).

    Gehasht werden die entpackten Streams (``xref_stream``): Flate packt jedes
    Programm anders (pikepdf beim XMP-Schreiben, PyMuPDF beim Stapeln), die
    Bilddaten bleiben gleich; JPEG-Daten (DCT) bleiben ohnehin unveraendert.
    Nichts wird gerendert. Derselbe Scan liefert nach Umbenennen, Verschieben,
    XMP-Schreiben, Stapeln, Teilen oder Kopieren denselben Hash, der OCR-Text
    kommt dann aus dem Cache.
    """
    h = hashlib.blake2b(digest_size=16)
    gefunden = False
    try:
        for bild in seite.get_images(full=False):
            try:
                h.update(doc.xref_stream(bild[0]))
                gefunden = True
            except Exception:
                try:
                    h.update(doc.xref_stream_raw(bild[0]))
                    gefunden = True
                except Exception:
                    continue
        if not gefunden:
            h.update(seite.read_contents())
            gefunden = True
    except Exception:
        return None
    return h.hexdigest() if gefunden else None


def pdf_bild_hashes(pfad: str, seiten: list[int]) -> dict:
    """Bild-Hashes fuer ausgewaehlte Seiten (OCR-Cache des Bestands auffuellen). ``{seite: hash}``."""
    import pymupdf

    erg: dict = {}
    try:
        doc = pymupdf.open(pfad)
    except Exception:
        return erg
    try:
        if doc.needs_pass and not doc.authenticate(""):
            return erg
        for nr in seiten:
            if 1 <= nr <= doc.page_count:
                h = _bild_hash(doc, doc[nr - 1])
                if h:
                    erg[nr] = h
    except Exception:
        pass
    finally:
        doc.close()
    return erg


_INFO_FELDER = {"Korrespondent": "korrespondent", "Steuerjahr": "steuerjahr", "Buchungsdatum": "buchungsdatum",
                "Subject": "zusammenfassung", "Keywords": "schlagwoerter"}
_XMP_SUBJECT = re.compile(r"<dc:subject[^>]*>(.*?)</dc:subject>", re.S)
_TAG = re.compile(r"<[^>]+>")
_DATEINAME = re.compile(r"[^\s/\\]+\.pdf", re.I)


def pdf_metadaten(doc) -> dict:
    """PDFSM-Metadaten aus einer PDF (``src/core/pdf_metadata.py`` schreibt sie beim Sortieren).

    Info-Dict: ``/Korrespondent``, ``/Steuerjahr``, ``/Buchungsdatum``,
    ``/BetragBrutto`` bzw. ``/Betrag``, ``/Subject`` (= dc:description, die
    Zusammenfassung), ``/Keywords``; die Kategorie steht nur im XMP (``dc:subject``).
    Liefert nur gefuellte Felder; ein Dateiname als Zusammenfassung (fremde
    Dokumentensysteme) wird verworfen.
    """
    erg: dict = {}
    try:
        info = doc.xref_get_key(-1, "Info")
    except Exception:
        info = None
    xref = None
    if info and info[0] == "xref":
        try:
            xref = int(str(info[1]).split()[0])
        except (ValueError, IndexError):
            xref = None
    if xref:
        try:
            schluessel = set(doc.xref_get_keys(xref))
        except Exception:
            schluessel = set()
        for k, feld in _INFO_FELDER.items():
            if k in schluessel:
                wert = _info_wert(doc, xref, k)
                if wert:
                    erg[feld] = wert
        for k in ("BetragBrutto", "Betrag"):
            if k in schluessel:
                wert = _info_wert(doc, xref, k)
                if wert:
                    erg["betrag"] = wert
                    break
    if erg.get("zusammenfassung") and _DATEINAME.fullmatch(erg["zusammenfassung"].strip()):
        del erg["zusammenfassung"]
    try:
        xmp = doc.get_xml_metadata() or ""
    except Exception:
        xmp = ""
    if xmp:
        m = _XMP_SUBJECT.search(xmp)
        if m:
            kategorie = html.unescape(_TAG.sub(" ", m.group(1))).strip()
            if kategorie:
                erg["kategorie"] = " ".join(kategorie.split())[:200]
    return erg


def _info_wert(doc, xref: int, schluessel: str) -> str | None:
    try:
        art, wert = doc.xref_get_key(xref, schluessel)
    except Exception:
        return None
    if art != "string" or wert is None:
        return None
    s = str(wert).strip()
    return s[:500] or None


def pdf_ocr(pfad: str, seiten: list[int], cfg: dict) -> dict:
    """Ausgewaehlte Seiten mit Tesseract erkennen. Liefert ``{'texte': {seite: text}, 'fehler': ...}``."""
    import pymupdf

    erg: dict = {"texte": {}, "fehler": None}
    try:
        doc = pymupdf.open(pfad)
        if doc.needs_pass:
            doc.authenticate("")
    except Exception as e:
        erg["fehler"] = f"Öffnen: {fehlertext(e, pfad)}"
        return erg
    try:
        for nr in seiten:
            if nr < 1 or nr > doc.page_count:
                continue
            seite = doc[nr - 1]
            try:
                erg["texte"][nr] = _saeubern(_ocr_seite(seite, cfg))
            except Exception as e:
                erg["fehler"] = f"Seite {nr}: {fehlertext(e, pfad)}"
                erg["texte"][nr] = None
    finally:
        doc.close()
    return erg


def _ocr_seite(seite, cfg: dict) -> str:
    import pymupdf

    # Seite in Graustufen rendern; sehr grosse Seiten mit geringerer Aufloesung
    dpi = cfg["dpi"]
    breite_zoll = seite.rect.width / 72
    hoehe_zoll = seite.rect.height / 72
    while dpi > 100 and breite_zoll * hoehe_zoll * dpi * dpi > 60_000_000:
        dpi -= 50
    pix = seite.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    png = pix.tobytes("png")
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    if cfg.get("tessdata"):
        env["TESSDATA_PREFIX"] = cfg["tessdata"]
    r = subprocess.run(
        [cfg["tesseract"], "stdin", "stdout", "-l", cfg["sprachen"], "--psm", "1", "--dpi", str(dpi)],
        input=png, capture_output=True, timeout=600, env=env, **_popen_kwargs(),
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[-300:])
    return r.stdout.decode("utf-8", "replace")


# --------------------------------------------------------------------------- Markdown

def md_text(pfad: str) -> dict:
    try:
        roh = Path(pfad).read_bytes()[:20 * 1024 * 1024]
    except Exception as e:
        return {"status": "fehler", "fehler": fehlertext(e, pfad), "text": "", "titel": None}
    text = _dekodiere(roh)
    titel = None
    m = re.search(r"^#\s+(.+)$", text, re.M)
    if m:
        titel = m.group(1).strip()[:300]
    return {"status": "text" if text.strip() else "leer", "fehler": None, "text": _saeubern(text), "titel": titel}


def _dekodiere(roh: bytes) -> str:
    if roh.startswith(b"\xef\xbb\xbf"):
        roh = roh[3:]
    for enc in ("utf-8", "cp1252"):
        try:
            return roh.decode(enc)
        except UnicodeDecodeError:
            continue
    return roh.decode("utf-8", "replace")


# --------------------------------------------------------------------------- Mail

class _HtmlZuText:
    _weg = re.compile(r"<(script|style|head)[^>]*>.*?</\1\s*>", re.S | re.I)
    _umbruch = re.compile(r"<\s*(br|/p|/div|/tr|/li|/h\d|/table)[^>]*>", re.I)
    _tag = re.compile(r"<[^>]+>")
    _leer = re.compile(r"[ \t\r\f\v]+")
    _zeilen = re.compile(r"\n\s*\n\s*\n+")

    @classmethod
    def wandle(cls, h: str) -> str:
        h = cls._weg.sub(" ", h)
        h = cls._umbruch.sub("\n", h)
        h = cls._tag.sub(" ", h)
        h = html.unescape(h)
        h = cls._leer.sub(" ", h)
        return cls._zeilen.sub("\n\n", h).strip()


def _mail_aus_message(msg) -> dict:
    def kopf(name):
        try:
            v = msg.get(name)
            return str(v).strip() if v is not None else ""
        except Exception:
            return ""

    betreff = kopf("Subject")
    von = kopf("From")
    an = ", ".join(x for x in (kopf("To"), kopf("Cc")) if x)
    datum_iso, ts = None, None
    d = kopf("Date")
    if d:
        try:
            dt = parsedate_to_datetime(d)
            datum_iso, ts = dt.isoformat(), dt.timestamp()
        except Exception:
            pass

    text = ""
    try:
        teil = msg.get_body(preferencelist=("plain", "html"))
        if teil is not None:
            inhalt = teil.get_content()
            if isinstance(inhalt, bytes):
                inhalt = _dekodiere(inhalt)
            text = _HtmlZuText.wandle(inhalt) if teil.get_content_type() == "text/html" else inhalt
    except Exception:
        try:
            for p in msg.walk():
                if p.get_content_type() in ("text/plain", "text/html"):
                    roh = p.get_payload(decode=True) or b""
                    t = _dekodiere(roh)
                    text = _HtmlZuText.wandle(t) if p.get_content_type() == "text/html" else t
                    break
        except Exception:
            pass

    anhaenge = []
    try:
        for p in msg.walk():
            fn = p.get_filename()
            if fn:
                anhaenge.append(str(fn))
    except Exception:
        pass

    voll = "\n".join([
        f"Betreff: {betreff}", f"Von: {von}", f"An: {an}", f"Datum: {d}",
        ("Anhänge: " + ", ".join(anhaenge)) if anhaenge else "", "", text or "",
    ])
    return {
        "betreff": betreff, "von": von, "an": an, "datum_iso": datum_iso, "datum_ts": ts,
        "anhaenge": " | ".join(anhaenge) or None, "text": _saeubern(voll),
    }


def _mail_fehler(fehler: str, status: str = "fehler") -> dict:
    return {"status": status, "fehler": fehler[:500] if fehler else None, "text": "", "betreff": "", "von": "",
            "an": "", "datum_iso": None, "datum_ts": None, "anhaenge": None}


def _mail_leer(grund: str | None = None) -> dict:
    """Keine Mail (leere Datei, fremdes Format): nichts zu indizieren, aber auch kein Fehler."""
    return _mail_fehler(grund, status="leer")


def mail_aus_bytes(roh: bytes) -> dict:
    try:
        msg = email.message_from_bytes(roh[:MAX_MAIL_ROH], policy=policy.default)
        return {"status": "text", "fehler": None, **_mail_aus_message(msg)}
    except Exception as e:
        return _mail_fehler(fehlertext(e))


def eml_text(pfad: str) -> dict:
    try:
        with open(pfad, "rb") as f:
            roh = f.read(MAX_MAIL_ROH)
    except Exception as e:
        return _mail_fehler(fehlertext(e, pfad))
    if not roh.strip():
        return _mail_leer()
    return mail_aus_bytes(roh)


_KOPFZEILE = re.compile(rb"^(?:From |[A-Za-z][A-Za-z0-9-]{0,60}:[ \t])")
_MAIL_KOEPFE = re.compile(
    rb"^(?:Subject|From|To|Date|Received|Return-Path|Message-ID|MIME-Version|Content-Type|X-[A-Za-z0-9-]+):",
    re.M | re.I,
)


def mail_format(kopf: bytes) -> str:
    """Woran erkennt man eine ``.msg``-Datei? ``'ole'`` (Outlook-Container), ``'rfc822'``
    (als Text gespeicherte Mail), ``'leer'`` oder ``'unbekannt'`` (z. B. Tcl-Nachrichtenkataloge,
    die ebenfalls ``.msg`` heissen)."""
    if not kopf.strip():
        return "leer"
    if kopf.startswith(OLE_MAGIC):
        return "ole"
    erste = kopf.lstrip(b"\r\n\t ").split(b"\n", 1)[0]
    if _KOPFZEILE.match(erste) and _MAIL_KOEPFE.search(kopf[:8192]):
        return "rfc822"
    return "unbekannt"


def mbox_stapel(stapel: list[tuple[int, int, bytes]]) -> list[tuple[int, int, dict]]:
    """Viele Mails aus einer mbox auf einmal zerlegen (weniger Prozess-Overhead)."""
    return [(off, laenge, mail_aus_bytes(roh)) for off, laenge, roh in stapel]


def msg_text(pfad: str) -> dict:
    """``.msg`` lesen: Outlook-Container ueber extract-msg; eine als Text gespeicherte
    Mail wie ``.eml``; alles andere (leer, fremdes Format) ist keine Mail -> ``leer``."""
    try:
        with open(pfad, "rb") as f:
            kopf = f.read(8192)
    except Exception as e:
        return _mail_fehler(fehlertext(e, pfad))
    art = mail_format(kopf)
    if art == "leer":
        return _mail_leer()
    if art == "rfc822":
        return eml_text(pfad)
    if art == "unbekannt":
        return _mail_leer("kein Outlook-Format (keine OLE2-Datei, keine Mail-Kopfzeilen)")
    try:
        import extract_msg
        m = extract_msg.openMsg(pfad)
        try:
            body = m.body or ""
            if not body.strip() and getattr(m, "htmlBody", None):
                hb = m.htmlBody
                body = _HtmlZuText.wandle(hb.decode("utf-8", "replace") if isinstance(hb, bytes) else hb)
            anh = [a.getFilename() for a in m.attachments if hasattr(a, "getFilename")]
            ts, iso = None, None
            if m.date:
                try:
                    iso, ts = m.date.isoformat(), m.date.timestamp()
                except Exception:
                    pass
            betreff, von = m.subject or "", m.sender or ""
            an = ", ".join(x for x in (m.to or "", m.cc or "") if x)
        finally:
            m.close()
        voll = "\n".join([f"Betreff: {betreff}", f"Von: {von}", f"An: {an}", f"Datum: {iso or ''}",
                          ("Anhänge: " + ", ".join(anh)) if anh else "", "", body])
        return {"status": "text", "fehler": None, "betreff": betreff, "von": von, "an": an,
                "datum_iso": iso, "datum_ts": ts, "anhaenge": " | ".join(anh) or None, "text": _saeubern(voll)}
    except Exception as e:
        return _mail_fehler(fehlertext(e, pfad))
