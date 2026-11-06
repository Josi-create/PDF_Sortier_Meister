"""Textgewinnung der Dokumentensuche – laeuft in den Arbeitsprozessen (ProcessPool).

Uebernommen aus PDFsuche (``extract.py``). Alle Funktionen geben einfache
dicts/lists zurueck (picklebar) und importieren PyMuPDF erst bei Bedarf.
"""

from __future__ import annotations

import email
import html
import os
import re
import subprocess
import sys
from email import policy
from email.utils import parsedate_to_datetime
from pathlib import Path

MAX_TEXT_PRO_SEITE = 2_000_000
MAX_MAIL_ROH = 6 * 1024 * 1024


def _popen_kwargs() -> dict:
    """Unterprozess ohne Konsolenfenster (nur Windows kennt das Flag)."""
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def setze_niedrige_prioritaet() -> None:
    """Prozess im Hintergrundmodus: niedrige CPU- und Festplatten-Prioritaet.

    Windows: PROCESS_MODE_BACKGROUND_BEGIN (Fallback BELOW_NORMAL). Andere
    Plattformen: ``os.nice``; die Feinheiten (taskpolicy) kommen mit der
    Plattformschicht in Phase 2.
    """
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.GetCurrentProcess()
        PROCESS_MODE_BACKGROUND_BEGIN = 0x00100000
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        if not k32.SetPriorityClass(h, PROCESS_MODE_BACKGROUND_BEGIN):
            k32.SetPriorityClass(h, BELOW_NORMAL_PRIORITY_CLASS)
        return
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass


def arbeiter_start(hintergrund: bool) -> None:
    """Initializer der Arbeitsprozesse."""
    os.environ["OMP_THREAD_LIMIT"] = "1"
    if hintergrund:
        setze_niedrige_prioritaet()
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
    """Textebene lesen. Seiten ohne Text, aber mit Bild, werden fuer OCR markiert."""
    import pymupdf

    erg = {"seiten": [], "anzahl": 0, "ohne_text": [], "titel": None, "autor": None, "status": "text", "fehler": None}
    try:
        doc = pymupdf.open(pfad)
    except Exception as e:
        erg.update(status="fehler", fehler=f"Öffnen: {e}"[:500])
        return erg
    try:
        if doc.needs_pass and not doc.authenticate(""):
            erg.update(status="verschluesselt", anzahl=doc.page_count)
            return erg
        md = doc.metadata or {}
        erg["titel"] = (md.get("title") or "").strip() or None
        erg["autor"] = (md.get("author") or "").strip() or None
        erg["anzahl"] = doc.page_count
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
            else:
                erg["seiten"].append((i + 1, "text", t))
        if erg["ohne_text"]:
            erg["status"] = "ocr_ausstehend"
        elif not any(t.strip() for _, _, t in erg["seiten"]):
            erg["status"] = "leer"
    except Exception as e:
        erg.update(status="fehler", fehler=f"Lesen: {e}"[:500])
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


def pdf_ocr(pfad: str, seiten: list[int], cfg: dict) -> dict:
    """Ausgewaehlte Seiten mit Tesseract erkennen. Liefert ``{'texte': {seite: text}, 'fehler': ...}``."""
    import pymupdf

    erg: dict = {"texte": {}, "fehler": None}
    try:
        doc = pymupdf.open(pfad)
        if doc.needs_pass:
            doc.authenticate("")
    except Exception as e:
        erg["fehler"] = f"Öffnen: {e}"[:500]
        return erg
    try:
        for nr in seiten:
            if nr < 1 or nr > doc.page_count:
                continue
            seite = doc[nr - 1]
            try:
                erg["texte"][nr] = _saeubern(_ocr_seite(seite, cfg))
            except Exception as e:
                erg["fehler"] = f"Seite {nr}: {e}"[:500]
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
        return {"status": "fehler", "fehler": str(e)[:500], "text": "", "titel": None}
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


def _mail_fehler(fehler: str) -> dict:
    return {"status": "fehler", "fehler": fehler[:500], "text": "", "betreff": "", "von": "", "an": "",
            "datum_iso": None, "datum_ts": None, "anhaenge": None}


def mail_aus_bytes(roh: bytes) -> dict:
    try:
        msg = email.message_from_bytes(roh[:MAX_MAIL_ROH], policy=policy.default)
        return {"status": "text", "fehler": None, **_mail_aus_message(msg)}
    except Exception as e:
        return _mail_fehler(str(e))


def eml_text(pfad: str) -> dict:
    try:
        with open(pfad, "rb") as f:
            roh = f.read(MAX_MAIL_ROH)
    except Exception as e:
        return _mail_fehler(str(e))
    return mail_aus_bytes(roh)


def mbox_stapel(stapel: list[tuple[int, int, bytes]]) -> list[tuple[int, int, dict]]:
    """Viele Mails aus einer mbox auf einmal zerlegen (weniger Prozess-Overhead)."""
    return [(off, laenge, mail_aus_bytes(roh)) for off, laenge, roh in stapel]


def msg_text(pfad: str) -> dict:
    """Outlook-Nachricht (.msg) ueber extract-msg lesen."""
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
        return _mail_fehler(str(e))
