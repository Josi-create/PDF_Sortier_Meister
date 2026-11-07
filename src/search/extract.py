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
import tempfile
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

def pdf_text(pfad: str, min_zeichen: int, gerade: bool = False) -> dict:
    """Textebene lesen. Seiten ohne Text, aber mit Bild, werden fuer OCR markiert.

    Dazu kommen ``bild_hashes`` (Seite -> Hash der Bild-Streams, fuer den
    OCR-Cache; nur fuer Seiten ohne Text) und ``metadaten`` (PDFSM-Felder aus
    Info-Dict und XMP, siehe ``pdf_metadaten``). Eine Seite mit einer
    OCR-Textebene (unsichtbare Schrift ``GlyphLessFont`` von Tesseract, auch
    OCRmyPDF; Phase 5b) gilt als Text, auch wenn sie wenig Text hat: Sie ist
    schon erkannt und bekommt weder OCR noch eine zweite Textebene.

    Mit ``gerade`` (Issue #165, ``SearchConfig.gerade_vormerken``) wird die
    Schraeglage jeder gescannten Seite gemessen, auch wenn sie schon Text
    traegt (``gerade.seite_messen``). Lohnt das Ausrichten, steht der Winkel
    in ``schraeglagen`` (``{seite: grad}``) und der Bild-Hash der Seite in
    ``bild_hashes``; daran haengt die Vormerkung im Index.
    """
    import pymupdf

    erg = {"seiten": [], "anzahl": 0, "ohne_text": [], "titel": None, "autor": None, "status": "text", "fehler": None,
           "bild_hashes": {}, "metadaten": {}, "schraeglagen": {}}
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
            if (len(t.strip()) < min_zeichen and seite is not None and _hat_bild(seite)
                    and not hat_ocr_textebene(seite)):
                erg["ohne_text"].append(i + 1)
                erg["seiten"].append((i + 1, "ohne_text", t))
                h = _bild_hash(doc, seite)
                if h:
                    erg["bild_hashes"][i + 1] = h
            else:
                erg["seiten"].append((i + 1, "text", t))
            if gerade and seite is not None:
                _schraeglage_messen(doc, seite, i + 1, erg)
        if erg["ohne_text"]:
            erg["status"] = "ocr_ausstehend"
        elif not any(t.strip() for _, _, t in erg["seiten"]):
            erg["status"] = "leer"
    except Exception as e:
        erg.update(status="fehler", fehler=f"Lesen: {fehlertext(e, pfad)}")
    finally:
        doc.close()
    return erg


def _schraeglage_messen(doc, seite, nr: int, erg: dict) -> None:
    """Schraeglage einer gescannten Seite messen (Issue #165); Fehler lassen die Seite einfach aus."""
    from src.search import gerade

    try:
        if not gerade.ist_scan(seite) or gerade.ist_ausgerichtet(doc, seite):
            return
        winkel = gerade.seite_messen(seite)
        if not gerade.lohnt(winkel):
            return
        h = erg["bild_hashes"].get(nr) or _bild_hash(doc, seite)
        if h:
            erg["schraeglagen"][nr] = winkel
            erg["bild_hashes"][nr] = h
    except Exception:
        return


OCR_SCHRIFT = "GlyphLessFont"   # unsichtbare Schrift der Tesseract-Textebene (auch OCRmyPDF)


def hat_ocr_textebene(seite) -> bool:
    """Traegt die Seite schon eine OCR-Textebene (Schrift ``GlyphLessFont``, auch in Form-XObjects)?"""
    try:
        return any(OCR_SCHRIFT in (f[3] or "") for f in seite.get_fonts(full=False))
    except Exception:
        return False


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

    Die Seitendrehung (``/Rotate``) geht mit ein (Issue #150): Drehen aendert
    die Bild-Streams nicht, wohl aber das Seitenbild, das Tesseract sieht. Ohne
    sie kaeme nach dem Drehen der alte, falsch orientierte OCR-Text aus dem
    Cache. Seiten ohne Drehung behalten ihren bisherigen Hash.

    Die Inhalts-Streams, mit denen PDFSM eine Seite gerade ausrichtet (Issue
    #165), zaehlen nicht: Das Ausrichten aendert weder Bild noch Hash, die
    Vormerkung am Hash bleibt so auch nach Rueckgaengig erledigt.
    """
    h = hashlib.blake2b(digest_size=16)
    gefunden = False
    try:
        drehung = seite.rotation % 360
        if drehung:
            h.update(f"rot={drehung}".encode())
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
            from src.search import gerade

            eigene = gerade.eigene_streams(doc, seite)
            if eigene:              # wie read_contents (Streams mit Leerzeichen verbunden), ohne die eigenen
                h.update(b" ".join(doc.xref_stream(x) for x in seite.get_contents() if x not in eigene))
            else:
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
    """Ausgewaehlte Seiten mit Tesseract erkennen. Liefert ``{'texte': {seite: text}, 'fehler': ...}``.

    Mit ``cfg["textebene"]`` liefert derselbe Tesseract-Aufruf je Seite auch
    die reine Text-PDF fuer die unsichtbare Textebene (``'ebenen': {seite:
    bytes}``, Phase 5b); sie kommt in den OCR-Cache und wird spaeter in die
    Datei geschrieben (``textebene.py``). Es gibt also nie eine zweite OCR.

    Mit ``cfg["lage_pruefen"]`` (Issue #151) wird eine Seite, die falsch herum
    oder quer liegt, zusaetzlich in den drei anderen Lagen gelesen
    (``seite_erkennen``); Text und Text-PDF stammen dann aus der besten Lage,
    und ``'drehungen'`` nennt sie (``{seite: 90 | 180 | 270}``, im
    Uhrzeigersinn zur angezeigten Seite).

    ``'lesbarkeit'`` (Issue #47, nur mit ``lage_pruefen``): ``{seite: (alle,
    gut)}`` der gewaehlten Lage (``lesbarkeit``), Grundlage fuer
    ``schlecht_erkannt``.
    """
    import pymupdf

    mit_ebene = bool(cfg.get("textebene"))
    erg: dict = {"texte": {}, "ebenen": {}, "drehungen": {}, "lesbarkeit": {}, "fehler": None}
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
                text, ebene, drehung, wert = _seite_erkennen(seite, cfg, ebene=mit_ebene)
                erg["texte"][nr] = _saeubern(text)
                if wert is not None:
                    erg["lesbarkeit"][nr] = wert
                if mit_ebene:
                    erg["ebenen"][nr] = ebene
                if drehung:
                    erg["drehungen"][nr] = drehung
            except Exception as e:
                erg["fehler"] = f"Seite {nr}: {fehlertext(e, pfad)}"
                erg["texte"][nr] = None
    finally:
        doc.close()
    return erg


def _seitenbild(seite, cfg: dict) -> tuple[bytes, int, dict]:
    """Seite fuer Tesseract in Graustufen rendern; sehr grosse Seiten mit geringerer Aufloesung.

    Gerendert wird die angezeigte Seite (Drehung und CropBox angewendet); die
    Text-PDF von Tesseract hat deshalb die angezeigte Seitengroesse.
    """
    import pymupdf

    dpi = cfg["dpi"]
    breite_zoll = seite.rect.width / 72
    hoehe_zoll = seite.rect.height / 72
    while dpi > 100 and breite_zoll * hoehe_zoll * dpi * dpi > 60_000_000:
        dpi -= 50
    pix = seite.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    if cfg.get("tessdata"):
        env["TESSDATA_PREFIX"] = cfg["tessdata"]
    return pix.tobytes("png"), dpi, env


TSV_KOPF = "level\tpage_num"   # erste Zeile der TSV-Ausgabe von Tesseract


def _psm(cfg: dict) -> str:
    """Seitensegmentierung: ``1`` (mit Lageerkennung, braucht ``osd.traineddata``), mit ``lage_pruefen`` ``3``.

    Mit ``osd.traineddata`` dreht Tesseract bei ``--psm 1`` kopfstehende
    Seiten intern selbst zurueck; die Lage liesse sich dann nicht mehr
    bewerten, und 90 von 270 Grad nicht unterscheiden. ``--psm 3`` liest
    genau das gerenderte Bild, die Lage bestimmt ``seite_erkennen``. Ohne
    ``osd.traineddata`` (mitgeliefertes Tesseract) faellt ``--psm 1`` ohnehin
    auf 3 zurueck.
    """
    return "3" if cfg.get("lage_pruefen") else "1"


def _ocr_seite(seite, cfg: dict, tsv: bool = False) -> tuple[str, str | None]:
    """Text der Seite ueber stdout; mit ``tsv`` dazu die TSV (``(text, tsv | None)``).

    Mit beiden Schaltern schreibt Tesseract nacheinander nach stdout: erst die
    TSV (jede Zeile mit Tabulatoren), dann den Text. Fehlt der TSV-Kopf (etwa
    bei einem Tesseract, der den Schalter nicht kennt), ist alles Text.
    """
    png, dpi, env = _seitenbild(seite, cfg)
    args = [cfg["tesseract"], "stdin", "stdout", "-l", cfg["sprachen"], "--psm", _psm(cfg), "--dpi", str(dpi)]
    if tsv:
        args += ["-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=1"]
    r = subprocess.run(args, input=png, capture_output=True, timeout=600, env=env, **_popen_kwargs())
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[-300:])
    ausgabe = r.stdout.decode("utf-8", "replace")
    if not tsv or not ausgabe.startswith(TSV_KOPF):
        return ausgabe, None
    zeilen = ausgabe.splitlines(keepends=True)
    i = 0
    while i < len(zeilen) and "\t" in zeilen[i]:
        i += 1
    return "".join(zeilen[i:]), "".join(zeilen[:i])


def ocr_seite_mit_textebene(seite, cfg: dict) -> tuple[str, bytes]:
    """Eine Seite erkennen und dabei die Textebene erzeugen: ``(text, text_pdf)`` aus einem Tesseract-Aufruf."""
    text, pdf, _ = _tesseract(seite, cfg, ebene=True)
    return text, pdf


def _tesseract(seite, cfg: dict, ebene: bool = False, tsv: bool = False) -> tuple[str, bytes | None, str | None]:
    """Ein Tesseract-Aufruf fuer die angezeigte Seite: ``(text, text_pdf | None, tsv | None)``.

    Tesseract schreibt Text (``tessedit_create_txt``), auf Wunsch eine reine
    Text-PDF (``tessedit_create_pdf`` mit ``textonly_pdf=1``: unsichtbarer Text
    in der Schrift ``GlyphLessFont``, ohne Bild) und die Woerter mit Lage und
    Konfidenz (``tessedit_create_tsv``) in einen temporaeren Ordner. Die
    Schalter statt der Konfigurationsdateien ``txt``/``pdf``/``tsv``
    funktionieren auch mit einem mitgelieferten Tesseract ohne
    ``tessdata/configs``. Ohne Text-PDF geht alles ueber stdout (``_ocr_seite``).
    """
    if not ebene:
        text, tsv_text = _ocr_seite(seite, cfg, tsv=tsv)
        return text, None, tsv_text
    png, dpi, env = _seitenbild(seite, cfg)
    schalter = ["-c", "tessedit_create_txt=1"]
    if ebene:
        schalter += ["-c", "tessedit_create_pdf=1", "-c", "textonly_pdf=1"]
    if tsv:
        schalter += ["-c", "tessedit_create_tsv=1"]
    with tempfile.TemporaryDirectory(prefix="pdfsm-ocr-") as tmp:
        basis = os.path.join(tmp, "seite")
        r = subprocess.run(
            [cfg["tesseract"], "stdin", basis, "-l", cfg["sprachen"], "--psm", _psm(cfg), "--dpi", str(dpi), *schalter],
            input=png, capture_output=True, timeout=600, env=env, **_popen_kwargs(),
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[-300:])
        text = Path(basis + ".txt").read_text(encoding="utf-8", errors="replace")
        pdf = Path(basis + ".pdf").read_bytes() if ebene else None
        tsv_datei = Path(basis + ".tsv")
        tsv_text = tsv_datei.read_text(encoding="utf-8", errors="replace") if tsv and tsv_datei.exists() else None
    return text, pdf, tsv_text


# --------------------------------------------------------------------------- Lage der Seite (Issue #151)

LAGE_KONFIDENZ = 70     # ab dieser Tesseract-Konfidenz (0-100) gilt ein Wort als sicher erkannt
LAGE_ANTEIL = 0.5       # weniger sichere, waagerechte Zeichen als dieser Anteil: Seite liegt falsch
LAGE_FAKTOR = 2         # eine andere Lage gewinnt nur deutlich: mindestens doppelt so viele sichere Zeichen
LAGEN = (90, 180, 270)  # weitere Lagen im Uhrzeigersinn, in dieser Reihenfolge gelesen


def lesbarkeit(tsv: str | None) -> tuple[int, int] | None:
    """``(alle, gut)`` aus der TSV-Ausgabe von Tesseract; None ohne TSV.

    ``alle``: Buchstaben und Ziffern aller Woerter, ``gut``: davon die der
    sicher erkannten (Konfidenz ab ``LAGE_KONFIDENZ``) *waagerechten* Woerter.
    Woerter mit weniger als zwei Buchstaben oder Ziffern zaehlen nicht
    (Rauschen, Striche). Ein Versuch mit dem mitgelieferten Tesseract (ohne
    ``osd``) zeigt, warum beides noetig ist: Kopfstehenden Text liest
    Tesseract als Buchstabensalat mit niedriger Konfidenz (etwa 12 % sicher),
    quer liegenden Text dagegen richtig, aber als senkrechte Woerter (Box
    hoeher als breit). Aufrecht sind es nahezu 100 %.
    """
    if tsv is None:
        return None
    alle = gut = 0
    for zeile in tsv.splitlines()[1:]:
        f = zeile.split("\t")
        if len(f) < 12 or f[0] != "5":
            continue
        n = sum(ch.isalnum() for ch in f[11])
        if n < 2:
            continue
        alle += n
        try:
            sicher = float(f[10]) >= LAGE_KONFIDENZ
            waagerecht = int(f[8]) >= int(f[9])
        except ValueError:
            continue
        if sicher and waagerecht:
            gut += n
    return alle, gut


def liegt_falsch(wert: tuple[int, int] | None, min_zeichen: int) -> bool:
    """Genug Schrift auf der Seite, aber zu wenig davon aufrecht lesbar? (leere Seiten: nein)"""
    if wert is None:
        return False
    alle, gut = wert
    return alle >= max(1, min_zeichen) and gut < LAGE_ANTEIL * alle


LESBAR_SCHWELLE = 0.6   # Issue #47: weniger sicher erkannte Zeichen als dieser Anteil: Text gilt als schlecht erkannt


def schlecht_erkannt(alle: int, gut: int, min_zeichen: int = 25) -> bool:
    """Ist der OCR-Text trotz bester Lage schlecht erkannt (Issue #47)?

    Mass ist dasselbe wie bei der Lagewahl (``lesbarkeit``): Anteil der
    Zeichen aus Woertern, die Tesseract mit Konfidenz ab ``LAGE_KONFIDENZ``
    erkannt hat. Sauberer Druck liegt nahe 1, Handschrift, Fraktur oder eine
    falsche Sprache deutlich darunter. Unter ``LESBAR_SCHWELLE`` gilt der Text
    als schlecht; Seiten mit weniger als ``min_zeichen`` Zeichen (leer,
    Stempel) sagen nichts.
    """
    return alle >= max(1, min_zeichen) and gut < LESBAR_SCHWELLE * alle


def ocr_kandidaten(pfad: str, min_zeichen: int) -> list[int]:
    """Seiten, die eine OCR neu lesen darf (Issue #47): Bildseiten ohne eigenen Text oder mit OCR-Textebene."""
    import pymupdf

    erg: list[int] = []
    try:
        doc = pymupdf.open(pfad)
    except Exception:
        return erg
    try:
        if doc.needs_pass and not doc.authenticate(""):
            return erg
        for i in range(doc.page_count):
            try:
                seite = doc[i]
                if _hat_bild(seite) and (len(_saeubern(seite.get_text("text")).strip()) < min_zeichen
                                         or hat_ocr_textebene(seite)):
                    erg.append(i + 1)
            except Exception:
                continue
    finally:
        doc.close()
    return erg


def seite_erkennen(seite, cfg: dict, ebene: bool = False) -> tuple[str, bytes | None, int]:
    """Wie ``_seite_erkennen``, ohne die Lesbarkeit: ``(text, text_pdf | None, drehung)``."""
    return _seite_erkennen(seite, cfg, ebene)[:3]


def _seite_erkennen(seite, cfg: dict, ebene: bool = False) -> tuple[str, bytes | None, int, tuple[int, int] | None]:
    """Eine Seite erkennen, bei falscher Lage auch gedreht: ``(text, text_pdf | None, drehung)``.

    Ohne ``cfg["lage_pruefen"]`` ein Aufruf wie bisher. Sonst liefert derselbe
    Aufruf die TSV mit; liegt die Seite falsch (``liegt_falsch``), liest
    Tesseract sie in den drei anderen Lagen (90, 180, 270 Grad im
    Uhrzeigersinn; gedreht wird nur die Seite im Speicher, die Datei bleibt
    unveraendert). Eine andere Lage gewinnt nur, wenn sie selbst aufrecht
    lesbar ist und mindestens ``LAGE_FAKTOR``-mal so viele sichere Zeichen hat
    wie die angezeigte, sonst bleibt alles wie angezeigt (``drehung`` 0).
    Text und Text-PDF stammen aus der gewaehlten Lage; die Text-PDF hat dann
    deren Seitengroesse (``textebene.ebene_auflegen`` mit ``drehung``).
    Kosten: drei weitere Tesseract-Aufrufe, nur fuer falsch liegende Seiten.

    Als Viertes kommt die Lesbarkeit der gewaehlten Lage ``(alle, gut)``
    (None ohne ``lage_pruefen``): Sie zeigt, ob die Seite auch aufrecht
    schlecht erkannt wurde (Handschrift, Fraktur, falsche Sprache; Issue #47).
    """
    pruefen = bool(cfg.get("lage_pruefen"))
    text, pdf, tsv = _tesseract(seite, cfg, ebene=ebene, tsv=pruefen)
    min_zeichen = int(cfg.get("min_zeichen", 25))
    wert = lesbarkeit(tsv) if pruefen else None
    if not liegt_falsch(wert, min_zeichen):
        return text, pdf, 0, wert
    beste = (wert[1], 0, text, pdf, wert)
    alt = seite.rotation
    try:
        for d in LAGEN:
            seite.set_rotation((alt + d) % 360)
            try:
                t, p, s = _tesseract(seite, cfg, ebene=ebene, tsv=True)
            finally:
                seite.set_rotation(alt)
            w = lesbarkeit(s)
            if w is None or liegt_falsch(w, min_zeichen):
                continue
            if w[1] > beste[0]:
                beste = (w[1], d, t, p, w)
    except Exception:  # noqa: BLE001 - die Lage zu pruefen ist Zusatz: dann gilt die angezeigte
        return text, pdf, 0, wert
    gut, d, t, p, w_beste = beste
    if d and gut >= max(min_zeichen, LAGE_FAKTOR * wert[1]):
        return t, p, d, w_beste
    return text, pdf, 0, wert


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
