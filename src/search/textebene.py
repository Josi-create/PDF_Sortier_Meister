"""OCR-Text als unsichtbare Textebene in gescannte PDFs schreiben (Phase 5b, Qt-frei).

Entscheidung 7 des Auftrags: Auch andere Programme (Explorer-Suche, Copernic,
Acrobat, PaperPort) sollen den erkannten Text finden, und man soll ihn
markieren koennen. Ablauf (``docs/SUCHE_ARCHITEKTUR.md``, Abschnitt 3.4):

1. **Erzeugen.** Die OCR (Indexlauf oder PDF-Analyzer) liefert im selben
   Tesseract-Aufruf je Seite eine reine Text-PDF
   (``extract.ocr_seite_mit_textebene``), wenn ``SearchConfig.textebene_erzeugen``
   es verlangt. Sie liegt im OCR-Cache beim Bild-Hash der Seite und uebersteht
   damit Umbenennen, Verschieben und XMP-Schreiben durch PDFSM.
2. **Schreiben.** Nur der Indexlauf (die eine Schreibquelle) legt sie in die
   Datei, dort, wo die Datei inzwischen liegt. Die Reihenfolge ist also
   „erst sortieren, dann Textebene“; war der Lauf schneller, wird die Datei mit
   Textebene sortiert. Beides fuehrt zu genau einer Textebene: Seiten, die schon
   eine haben (``extract.hat_ocr_textebene``) oder Text tragen, bekommen keine
   zweite, und ``dokumente.textebene_am`` haelt fest, dass die Datei fertig ist.
3. **Altbestand** (Stufe ``alle``): Der Index kennt nur den Klartext, nicht die
   Positionen; Tesseract liest diese Seiten deshalb noch einmal. Das laeuft als
   eigene Phase des Indexlaufs (im Hintergrund, mit Fortschritt, anhaltbar,
   setzt beim naechsten Lauf fort); ``schaetzung`` nennt Dauer, OneDrive-Upload
   und Platz fuer Sicherungskopien, bevor der Nutzer die Stufe einschaltet.

Sicher schreiben (``datei_schreiben``, laeuft im Arbeitsprozess): Kopie in eine
temporaere Datei im selben Ordner, Textebene darauflegen und *inkrementell*
speichern (das Original bleibt bytegleich der Anfang der neuen Datei, Bilder
werden weder neu komprimiert noch aufgeraeumt), pruefen (Seitenzahl, Seitengroesse
und -drehung, Bild- und Inhalts-Streams bytegleich, Text vorhanden, oeffnet ohne
Reparatur), Sicherungskopie anlegen, dann ``plattform.datei_ersetzen``. Bei jedem
Fehler bleibt das Original unveraendert und die temporaere Datei verschwindet.
Nie angefasst werden signierte, verschluesselte und PDF/A-Dateien, Dateien nur
in der Cloud, schreibgeschuetzte, geoeffnete und seit der OCR geaenderte Dateien.
Jede Aenderung steht im Protokoll (Tabelle ``textebene_protokoll``) und laesst
sich mit ``rueckgaengig`` zuruecknehmen, solange die Sicherungskopie existiert.

Automatisch drehen (Issue #151): Liest die OCR eine falsch herum oder quer
liegende Seite in einer anderen Lage besser (``extract.seite_erkennen``), steht
die Lage im OCR-Cache (``drehung``), und bei passender Stufe
(``SearchConfig.auto_drehen``) ist sie zum Schreiben vorgemerkt (``drehen``).
Derselbe Schreibschritt dreht dann die Seiten (``/Rotate``, Scanbild
unveraendert), auch ohne Textebene; mit Textebene entsteht beides in einer
Aenderung mit einer Sicherungskopie. Bleibt die Datei ungedreht, liegt die
Textebene trotzdem deckungsgleich auf dem Scan (``ebene_auflegen`` mit der
Lage, in der Tesseract gelesen hat).

Gerade ausrichten (Issue #165): Beim Einlesen eines neuen Scans misst
``extract.pdf_text`` die Schraeglage seiner Seiten (``gerade.seite_messen``);
lohnt das Ausrichten, ist der Winkel am Bild-Hash vorgemerkt (Tabelle
``schraeglage``). Derselbe Schreibschritt dreht dann den ganzen Seiteninhalt
um diesen kleinen Winkel (``gerade.ausrichten``, nach Drehung und Textebene,
damit beide mitdrehen), mit demselben Schutz, einer Sicherungskopie und
einem Protokolleintrag. Das gilt auch fuer Scans, deren Textebene schon das
Scanprogramm geschrieben hat. Danach ist die Vormerkung erledigt, auch nach
Rueckgaengig; eine von Hand ausgerichtete Seite bleibt, wie sie ist.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.search import db, extract, plattform
from src.search import gerade as geraderichten
from src.i18n import tr

log = logging.getLogger("pdf_sortier_meister.suche")

TMP_ENDUNG = ".textebene.tmp"
SEKUNDEN_JE_SEITE = 4.0        # Schaetzung fuer Tesseract je Seite und Prozess (300 dpi, deu+eng)
BYTES_JE_SEITE = 4 * 1024      # Zuwachs einer PDF je Seite mit Textebene (Schrift + Text, gepackt)
EBENE_AUFBEWAHREN_TAGE = 60    # so lange bleibt die Text-PDF im OCR-Cache (verlorene Textebene neu schreiben)

GRUENDE = {
    "signiert": tr("digital signiert"),
    "verschluesselt": tr("verschlüsselt"),
    "pdfa": tr("PDF/A (die Konformität bliebe nicht erhalten)"),
    "schreibgeschuetzt": tr("schreibgeschützt"),
    "leer": tr("keine erkannte Schrift"),
    "rueckgaengig": tr("Textebene wurde rückgängig gemacht"),
    "fehler": tr("Fehler beim Schreiben (siehe Protokoll)"),
    "nur_cloud": tr("liegt nur in der Cloud"),
    "gesperrt": tr("in einem anderen Programm geöffnet"),
    "geaendert": tr("seit der Texterkennung geändert"),
    "fehlt": tr("Datei nicht gefunden"),
}
# Gruende, bei denen kein Lauf es erneut versucht; die uebrigen sind voruebergehend
DAUERHAFT = ("signiert", "verschluesselt", "pdfa", "schreibgeschuetzt", "leer", "rueckgaengig", "fehler")

_DAUERHAFT_SQL = ", ".join(f"'{g}'" for g in DAUERHAFT)
# Antwort von ``rueckgaengig``, wenn die Datei seither geaendert wurde (die Oberflaeche bietet dann ``erzwingen`` an)
MELDUNG_GEAENDERT = (tr("Die Datei wurde seit dem Schreiben der Textebene geändert (z. B. Metadaten). "
                     "Rückgängig machen würde diese Änderung verwerfen."))
_SICHERUNG_ZEIT = re.compile(r"^(\d{8}-\d{6})_")


class PruefungFehlgeschlagen(Exception):  # noqa: N818
    """Die geschriebene Datei weicht vom Original ab; das Original bleibt unveraendert."""


# =========================================================================== Arbeitsprozess

def ebene_auflegen(seite, text_pdf: bytes, lage: int | None = None) -> None:
    """Die Text-PDF von Tesseract deckungsgleich als Ueberlagerung auf die Seite legen.

    Tesseract hat die *angezeigte* Seite gelesen (Drehung und CropBox
    angewendet). ``show_pdf_page`` rechnet Drehung und CropBox-Versatz
    zusammen nicht richtig; deshalb wird die Drehung kurz auf 0 gesetzt, die
    Text-PDF um die Seitendrehung gedreht in das ungedrehte Seitenrechteck
    gelegt und die Drehung wiederhergestellt (geprueft fuer 0/90/180/270 Grad,
    mit und ohne CropBox-Versatz). Der bisherige Seiteninhalt bleibt
    unveraendert, die Ueberlagerung kommt als eigener Inhalts-Stream dazu.

    ``lage``: angezeigte Drehung, in der Tesseract gelesen hat (Standard: die
    der Seite). Hat die OCR die Seite gedreht besser gelesen (Issue #151),
    liegt die Textebene damit auch auf einer ungedrehten Datei richtig.
    """
    import pymupdf

    quelle = pymupdf.open("pdf", text_pdf)
    try:
        drehung = seite.rotation
        lage = drehung if lage is None else int(lage) % 360
        if drehung:
            seite.set_rotation(0)
        try:
            seite.show_pdf_page(seite.rect, quelle, 0, overlay=True, rotate=lage, keep_proportion=False)
        finally:
            if drehung:
                seite.set_rotation(drehung)
    finally:
        quelle.close()


def ebene_hat_text(text_pdf: bytes | None) -> bool:
    """Enthaelt die Text-PDF ueberhaupt erkannten Text (leere Seiten bekommen keine Textebene)?"""
    if not text_pdf:
        return False
    import pymupdf

    try:
        with pymupdf.open("pdf", text_pdf) as d:
            return any(p.get_text().strip() for p in d)
    except Exception:
        return False


def dokument_grund(doc) -> str | None:
    """Gruende im Dokument selbst, es nicht anzufassen: verschluesselt, signiert, PDF/A."""
    try:
        if doc.needs_pass or (doc.metadata or {}).get("encryption"):
            return "verschluesselt"
    except Exception:
        return "verschluesselt"
    try:
        if doc.get_sigflags() > 0:
            return "signiert"
    except Exception:
        pass
    try:
        xmp = doc.get_xml_metadata() or ""
    except Exception:
        xmp = ""
    if "pdfaid:part" in xmp:
        return "pdfa"
    return None


def datei_grund(pfad: str, st: os.stat_result, groesse: int | None = None, mtime_ns: int | None = None) -> str | None:
    """Gruende an der Datei, sie (jetzt) nicht anzufassen; ``groesse``/``mtime_ns`` = Stand der OCR im Index."""
    if groesse is not None and (st.st_size, st.st_mtime_ns) != (groesse, mtime_ns):
        return "geaendert"
    if plattform.nur_cloud(st):
        return "nur_cloud"
    if plattform.schreibgeschuetzt(st):
        return "schreibgeschuetzt"
    if plattform.gesperrt(pfad):
        return "gesperrt"
    return None


def tmp_pfad(pfad: str) -> str:
    """Temporaere Datei im selben Ordner (gleiches Laufwerk fuer das Ersetzen).

    ``~$`` vorn und ``.tmp`` hinten: Office-Muster, die OneDrive nicht hochlaedt
    und die Suche nicht aufnimmt. Der Name ist je Datei fest, eine von einem
    abgebrochenen Lauf liegen gebliebene Datei wird beim naechsten Versuch ersetzt.
    """
    ordner, name = os.path.split(pfad)
    stamm = os.path.splitext(name)[0]
    kennung = hashlib.blake2b(os.path.normcase(name).encode("utf-8"), digest_size=3).hexdigest()
    return os.path.join(ordner, f"~${stamm[:40]}.{kennung}{TMP_ENDUNG}")


def sichern(pfad: str, ordner: str | Path) -> str:
    """Sicherungskopie des Originals (Inhalt und Zeitstempel); Name beginnt mit Datum und Uhrzeit."""
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    kennung = hashlib.blake2b(os.path.normcase(os.path.abspath(pfad)).encode("utf-8"), digest_size=4).hexdigest()
    basis = f"{datetime.now():%Y%m%d-%H%M%S}_{kennung}_"
    name = os.path.basename(pfad)
    ziel = ordner / f"{basis}{name}"
    n = 1
    while ziel.exists():
        n += 1
        ziel = ordner / f"{basis}{n}_{name}"
    shutil.copy2(pfad, ziel)
    return str(ziel)


def _weg(pfad: str | None) -> None:
    if pfad:
        try:
            os.remove(pfad)
        except OSError:
            pass


def _vorbereiten(pfad: str, a: dict, erg: dict) -> tuple[dict[int, tuple[bytes, int]], dict[int, int],
                                                         dict[int, float]]:
    """Original lesen: Dokument pruefen, Seiten auswaehlen, fehlende Text-PDFs mit Tesseract erzeugen.

    Liefert ``({seite: (text_pdf, lage)}, {seite: drehung}, {seite: winkel})``:
    ``lage`` ist die angezeigte Drehung, in der die Text-PDF entstand,
    ``drehung`` die vorgemerkte Drehung der Seite (Issue #151), ``winkel``
    die vorgemerkte Schraeglage (Issue #165; Seiten, die schon ausgerichtet
    sind, fallen weg). Bei einem Grund steht er in ``erg["grund"]``.
    """
    import pymupdf

    doc = pymupdf.open(pfad)
    try:
        grund = dokument_grund(doc)
        if grund:
            erg["grund"] = grund
            return {}, {}, {}
        drehen: dict[int, int] = {}
        for nr, info in sorted((a.get("drehen") or {}).items()):
            if nr < 1 or nr > doc.page_count:
                erg["grund"] = "geaendert"
                return {}, {}, {}
            if info.get("hash") and extract._bild_hash(doc, doc[nr - 1]) != info["hash"]:
                erg["grund"] = "geaendert"  # anderes Bild: die erkannte Lage gilt nicht mehr
                return {}, {}, {}
            if int(info["grad"]) % 360:
                drehen[nr] = int(info["grad"]) % 360
        gerade: dict[int, float] = {}
        for nr, info in sorted((a.get("gerade") or {}).items()):
            if nr < 1 or nr > doc.page_count:
                erg["grund"] = "geaendert"
                return {}, {}, {}
            seite = doc[nr - 1]
            if info.get("hash") and extract._bild_hash(doc, seite) != info["hash"]:
                erg["grund"] = "geaendert"  # anderes Bild: der gemessene Winkel gilt nicht mehr
                return {}, {}, {}
            if geraderichten.ist_ausgerichtet(doc, seite):
                continue                    # schon ausgerichtet (z. B. von Hand ueber das Kontextmenue)
            if geraderichten.lohnt(info.get("winkel")):
                gerade[nr] = round(float(info["winkel"]), 2)
        ebenen: dict[int, tuple[bytes, int]] = {}
        for nr, info in sorted((a.get("seiten") or {}).items()):
            if nr < 1 or nr > doc.page_count:
                erg["grund"] = "geaendert"
                return {}, {}, {}
            seite = doc[nr - 1]
            if extract.hat_ocr_textebene(seite):
                continue                    # schon erkannt (von uns oder einem anderen Programm)
            if len(seite.get_text("text").strip()) >= a.get("min_zeichen", 25):
                continue                    # die Seite hat inzwischen eigenen Text
            if info.get("hash") and extract._bild_hash(doc, seite) != info["hash"]:
                erg["grund"] = "geaendert"  # anderes Bild: die Text-PDF passt nicht mehr
                return {}, {}, {}
            lage = (seite.rotation + int(info.get("drehung") or 0)) % 360
            daten = info.get("ebene")
            if daten is not None and geraderichten.ist_ausgerichtet(doc, seite):
                # Schon ausgerichtet (Issue #165, z. B. von Hand): die Text-PDF im Cache stammt womoeglich aus der
                # Seite davor und laege um den Winkel schief; aus der angezeigten Seite neu erkennen
                daten = None
            if daten is None:
                if not a.get("ocr"):
                    continue
                alt = seite.rotation
                seite.set_rotation(lage)    # nur im Speicher: so liest Tesseract die Seite am besten
                try:
                    text, daten = extract.ocr_seite_mit_textebene(seite, a["ocr"])
                finally:
                    seite.set_rotation(alt)
                erg["texte"][nr] = extract._saeubern(text)
            if ebene_hat_text(daten):
                ebenen[nr] = (daten, lage)
        return ebenen, drehen, gerade
    finally:
        doc.close()


def _schreiben_tmp(pfad: str, tmp: str, ebenen: dict[int, tuple[bytes, int]],
                   drehen: dict[int, int] | None = None, gerade: dict[int, float] | None = None) -> dict[int, str]:
    """Kopie anlegen, Seiten drehen, Textebenen auflegen, gerade ausrichten, inkrementell speichern.

    Das Original bleibt bytegleich der Anfang der neuen Datei. Ausgerichtet
    wird zuletzt, damit die Textebene mitdreht (Issue #165). Liefert die neuen
    Bild-Hashes der gedrehten Seiten (die Drehung gehoert zum Hash,
    ``extract._bild_hash``; das Ausrichten nicht).
    """
    import pymupdf

    drehen = drehen or {}
    gerade = gerade or {}
    shutil.copyfile(pfad, tmp)
    doc = pymupdf.open(tmp)
    hashes: dict[int, str] = {}
    try:
        for nr, grad in sorted(drehen.items()):
            seite = doc[nr - 1]
            seite.set_rotation((seite.rotation + grad) % 360)
        for nr, (daten, lage) in sorted(ebenen.items()):
            ebene_auflegen(doc[nr - 1], daten, lage)
        for nr, winkel in sorted(gerade.items()):
            geraderichten.ausrichten(doc, doc[nr - 1], winkel)
        for nr in sorted(drehen):
            h = extract._bild_hash(doc, doc[nr - 1])
            if h:
                hashes[nr] = h
        if doc.can_save_incrementally():
            doc.saveIncr()
            return hashes
        # Reparierte Datei: vollstaendig speichern, ohne Aufraeumen und ohne Neukomprimieren
        neu = tmp + ".neu"
        doc.save(neu, garbage=0, clean=False, deflate=False)
    finally:
        doc.close()
    os.replace(neu, tmp)
    return hashes


def _bild_und_inhalt_xrefs(doc) -> list[int]:
    """Alle Bild-Streams und alle Inhalts-Streams der Seiten (das Scanbild, auch als Inline-Bild)."""
    xrefs: set[int] = set()
    for x in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(x, "Subtype") == ("name", "/Image"):
                xrefs.add(x)
        except Exception:
            continue
    for seite in doc:
        xrefs.update(seite.get_contents())
    return sorted(xrefs)


def _rechteck(r) -> tuple:
    return tuple(round(v, 2) for v in (r.x0, r.y0, r.x1, r.y1))


def pruefen(original: str, neu: str, ebenen, drehen: dict[int, int] | None = None,
            gerade: dict[int, float] | None = None) -> None:
    """Die neue Datei gegen das Original pruefen; ``PruefungFehlgeschlagen`` bei jeder Abweichung.

    ``drehen`` (Issue #151): Diese Seiten muessen um so viel gedreht sein,
    alle anderen ungedreht wie im Original. ``gerade`` (Issue #165): Diese
    Seiten muessen um genau diesen Winkel ausgerichtet sein, alle anderen wie
    im Original.
    """
    drehen = drehen or {}
    gerade = gerade or {}
    import pymupdf

    a = pymupdf.open(original)
    try:
        b = pymupdf.open(neu)
    except Exception as e:
        a.close()
        raise PruefungFehlgeschlagen(tr("neue Datei lässt sich nicht öffnen: {e}").format(e=e)) from e
    try:
        if b.is_repaired:
            raise PruefungFehlgeschlagen(tr("neue Datei musste beim Öffnen repariert werden"))
        if a.page_count != b.page_count:
            raise PruefungFehlgeschlagen(tr("Seitenzahl {page_count} -> {page_count2}").format(page_count=a.page_count, page_count2=b.page_count))
        for i in range(a.page_count):
            pa, pb = a[i], b[i]
            erwartet = (pa.rotation + drehen.get(i + 1, 0)) % 360
            if (pb.rotation != erwartet or _rechteck(pa.mediabox) != _rechteck(pb.mediabox)
                    or _rechteck(pa.cropbox) != _rechteck(pb.cropbox)):
                raise PruefungFehlgeschlagen(tr("Seite {0}: Größe oder Drehung verändert").format(i + 1))
            soll = gerade[i + 1] if i + 1 in gerade else geraderichten.ausrichtung(a, pa)
            if abs(geraderichten.ausrichtung(b, pb) - soll) > 0.005:
                raise PruefungFehlgeschlagen(tr("Seite {0}: Ausrichtung verändert").format(i + 1))
        for x in _bild_und_inhalt_xrefs(a):
            try:
                gleich = a.xref_stream_raw(x) == b.xref_stream_raw(x)
            except Exception:
                gleich = False
            if not gleich:
                raise PruefungFehlgeschlagen(tr("Bild- oder Inhalts-Stream {x} verändert").format(x=x))
        for nr in ebenen:
            seite = b[nr - 1]
            if not seite.get_text("text").strip() or not extract.hat_ocr_textebene(seite):
                raise PruefungFehlgeschlagen(tr("Seite {nr}: Textebene fehlt").format(nr=nr))
    finally:
        b.close()
        a.close()


def datei_schreiben(a: dict) -> dict:
    """Textebene in eine PDF schreiben (Arbeitsprozess; picklebare Ein- und Ausgabe).

    ``a``: ``pfad``, ``groesse``/``mtime_ns`` (Stand im Index; weicht die Datei
    ab, wird nichts geschrieben), ``seiten`` (``{seite: {"hash": str|None,
    "ebene": bytes|None, "drehung": int}}``; fehlende Text-PDFs erzeugt
    Tesseract mit ``ocr``, sonst bleibt die Seite aus), ``drehen`` (Issue #151:
    ``{seite: {"hash": str|None, "grad": int}}``), ``gerade`` (Issue #165:
    ``{seite: {"hash": str|None, "winkel": float}}``), ``sicherung_ordner``,
    ``min_zeichen``.

    Ergebnis: ``status`` ``'geschrieben'`` | ``'vorhanden'`` (nichts zu tun, die
    Seiten tragen schon Text) | ``'uebersprungen'`` (``grund``, siehe
    ``GRUENDE``) | ``'fehler'`` (``fehler``); dazu ``seiten`` (mit Textebene),
    ``gedreht`` (``{seite: grad}``) mit den neuen Bild-Hashes ``hashes``,
    ``gerade`` (``{seite: winkel}``), neu erkannte ``texte``, Groesse und
    Aenderungszeit vorher/nachher und ``sicherung``. ``gerade_hashes`` und
    ``mit_ebene`` geben den Auftrag an ``ergebnis_eintragen`` weiter.
    """
    pfad = a["pfad"]
    erg: dict = {"pfad": pfad, "status": "uebersprungen", "grund": None, "fehler": None, "seiten": [],
                 "gedreht": {}, "hashes": {}, "gerade": {}, "texte": {}, "groesse_vorher": None,
                 "mtime_ns_vorher": None, "groesse": None, "mtime_ns": None, "sicherung": None,
                 "gerade_hashes": [v.get("hash") for v in (a.get("gerade") or {}).values() if v.get("hash")],
                 "mit_ebene": bool(a.get("seiten"))}
    try:
        st = os.stat(pfad)
    except OSError:
        erg["grund"] = "fehlt"
        return erg
    erg["groesse_vorher"], erg["mtime_ns_vorher"] = st.st_size, st.st_mtime_ns
    grund = datei_grund(pfad, st, a.get("groesse"), a.get("mtime_ns"))
    if grund:
        erg["grund"] = grund
        return erg
    tmp = tmp_pfad(pfad)
    sicherung = None
    try:
        ebenen, drehen, gerade = _vorbereiten(pfad, a, erg)
        if erg["grund"]:
            return erg
        if not ebenen and not drehen and not gerade:
            erg["status"] = "vorhanden"
            return erg
        hashes = _schreiben_tmp(pfad, tmp, ebenen, drehen, gerade)
        pruefen(pfad, tmp, ebenen, drehen, gerade)
        sicherung = sichern(pfad, a["sicherung_ordner"])
        jetzt = os.stat(pfad)
        if (jetzt.st_size, jetzt.st_mtime_ns) != (st.st_size, st.st_mtime_ns):
            erg["grund"] = "geaendert"      # waehrenddessen von einem anderen Programm geaendert
            return erg
        plattform.datei_ersetzen(pfad, tmp)
        neu = os.stat(pfad)
        erg.update(status="geschrieben", seiten=sorted(ebenen), gedreht=dict(sorted(drehen.items())),
                   gerade=dict(sorted(gerade.items())), hashes=hashes, groesse=neu.st_size,
                   mtime_ns=neu.st_mtime_ns, sicherung=sicherung)
        return erg
    except FileNotFoundError:
        erg["grund"] = "fehlt"              # inzwischen verschoben oder geloescht: am alten Ort entsteht nichts
    except PermissionError:
        erg["grund"] = "gesperrt"
    except Exception as e:
        erg.update(status="fehler", grund="fehler", fehler=extract.fehlertext(e, pfad))
    finally:
        _weg(tmp)
        _weg(tmp + ".neu")
        if erg["status"] != "geschrieben":
            _weg(sicherung)
    return erg


# =========================================================================== Index (Hauptprozess)

_SCHREIBBAR = f"""d.typ = 'pdf'
    AND (d.textebene_grund IS NULL OR d.textebene_grund NOT IN ({_DAUERHAFT_SQL}))
    AND d.textstatus IN ('ocr', 'ocr_teilweise')"""
_KANDIDAT = f"d.textebene_am IS NULL AND {_SCHREIBBAR}"
# Ausrichten (Issue #165) auch fuer PDFs, deren Text schon in der Datei steht (Textebene des Scanprogramms)
_AUSRICHTBAR = f"""d.typ = 'pdf'
    AND (d.textebene_grund IS NULL OR d.textebene_grund NOT IN ({_DAUERHAFT_SQL}))"""
_KANDIDAT_SPALTEN = "d.id, d.datei, d.groesse, d.mtime_ns, d.prioritaet, d.datum, d.textebene_am"


def offene(con, ebene: bool = True, drehen: bool = False, gerade: bool = False) -> list[sqlite3.Row]:
    """Dokumente, deren OCR die Textebene mitgeliefert hat (Cache) und die sie noch nicht tragen.

    Mit ``drehen`` (Issue #151) auch Dokumente mit einer vorgemerkten Drehung
    (``ocr_cache.drehen``), ob mit Textebene oder ohne; mit ``gerade`` (Issue
    #165) Dokumente mit einer vorgemerkten Schraeglage (``schraeglage.gerade``).
    """
    # Je Bedingung eine Abfrage mit eigenem Teilindex (ix_ocr_cache_ebene/_drehen, ix_schraeglage_gerade),
    # per UNION ohne Doppelte; ein OR in einer Abfrage liesse SQLite den ganzen OCR-Cache lesen
    teile = []
    if ebene:
        teile.append("c.ebene IS NOT NULL AND d.textebene_am IS NULL")
    if drehen:
        teile.append("c.drehen = 1 AND c.drehung % 360 != 0")
    abfragen = [f"""SELECT DISTINCT {_KANDIDAT_SPALTEN}
            FROM ocr_cache c JOIN seiten s ON s.bild_hash = c.bild_hash JOIN dokumente d ON d.id = s.dok_id
            WHERE {bedingung} AND s.quelle = 'ocr' AND {_SCHREIBBAR}""" for bedingung in teile]
    if gerade:
        abfragen.append(f"""SELECT DISTINCT {_KANDIDAT_SPALTEN}
            FROM schraeglage g JOIN seiten s ON s.bild_hash = g.bild_hash JOIN dokumente d ON d.id = s.dok_id
            WHERE g.gerade = 1 AND {_AUSRICHTBAR}""")
    if not abfragen:
        return []
    return con.execute(" UNION ".join(abfragen) + " ORDER BY prioritaet, datum DESC").fetchall()


def altbestand(con) -> list[sqlite3.Row]:
    """Alle texterkannten PDFs ohne Textebene (Stufe ``alle``; fehlende Text-PDFs erzeugt Tesseract neu)."""
    return con.execute(
        f"""SELECT d.id, d.datei, d.groesse, d.mtime_ns, d.ocr_seiten, d.prioritaet, d.datum, d.textebene_am
            FROM dokumente d WHERE d.ocr_seiten > 0 AND {_KANDIDAT}
            ORDER BY d.prioritaet, d.datum DESC""").fetchall()


def hat_ebenen(con, dok_id: int) -> bool:
    """Liegt fuer eine Seite des Dokuments schon eine Text-PDF im Cache (dann auch die weiteren Seiten erzeugen)?"""
    return con.execute(
        """SELECT 1 FROM seiten s JOIN ocr_cache c ON c.bild_hash = s.bild_hash
           WHERE s.dok_id = ? AND c.ebene IS NOT NULL LIMIT 1""", (dok_id,)).fetchone() is not None


def auftrag(con, d, konfig, ocr: dict | None, altbestand: bool = False) -> dict | None:
    """Auftrag fuer ``datei_schreiben`` aus einem Kandidaten (``offene``/``altbestand``).

    Die Textebene gehoert dazu, wenn die Stufe sie erlaubt, die Datei noch
    keine traegt und die OCR sie mitgeliefert hat (bzw. ``altbestand``);
    vorgemerkte Drehungen (Issue #151), wenn ``auto_drehen`` nicht aus ist;
    vorgemerkte Schraeglagen (Issue #165), wenn ``auto_gerade`` nicht aus ist.
    None, wenn es nichts zu schreiben gibt (ohne erkannte Seiten und ohne
    Schraeglage dann ``textebene_grund = 'leer'``) oder wenn Text-PDFs fehlen,
    keine Texterkennung verfuegbar ist und nichts zu drehen oder auszurichten
    ist (dann spaeter erneut).
    """
    zeilen = con.execute(
        """SELECT s.seite, s.bild_hash, c.ebene, c.drehung, c.drehen FROM seiten s
           LEFT JOIN ocr_cache c ON c.bild_hash = s.bild_hash
           WHERE s.dok_id = ? AND s.quelle = 'ocr' AND length(trim(s.text)) > 0 ORDER BY s.seite""",
        (d["id"],)).fetchall()
    gerade: dict = {}
    if konfig.auto_gerade != "aus":
        for r in con.execute(
                """SELECT s.seite, s.bild_hash, g.winkel FROM seiten s JOIN schraeglage g ON g.bild_hash = s.bild_hash
                   WHERE s.dok_id = ? AND g.gerade = 1 ORDER BY s.seite""", (d["id"],)):
            gerade[r["seite"]] = {"hash": r["bild_hash"], "winkel": float(r["winkel"])}
    if not zeilen and not gerade:
        con.execute("UPDATE dokumente SET textebene_grund = 'leer' WHERE id = ?", (d["id"],))
        return None
    textebene_am = d["textebene_am"] if "textebene_am" in d.keys() else None
    ebene_an = (konfig.textebene != "aus" and textebene_am is None
                and (altbestand or any(r["ebene"] is not None for r in zeilen)))
    seiten: dict = {}
    drehen: dict = {}
    for r in zeilen:
        grad = int(r["drehung"] or 0) % 360
        if ebene_an:
            seiten[r["seite"]] = {"hash": r["bild_hash"], "drehung": grad,
                                  "ebene": bytes(r["ebene"]) if r["ebene"] is not None else None}
        if konfig.auto_drehen != "aus" and grad and r["drehen"]:
            drehen[r["seite"]] = {"hash": r["bild_hash"], "grad": grad}
    if ocr is None and any(v["ebene"] is None for v in seiten.values()):
        seiten = {}                 # Textebene spaeter mit Texterkennung; drehen geht schon jetzt
    if not seiten and not drehen and not gerade:
        return None
    return {"pfad": d["datei"], "groesse": d["groesse"], "mtime_ns": d["mtime_ns"], "seiten": seiten,
            "drehen": drehen, "gerade": gerade, "ocr": ocr, "sicherung_ordner": str(konfig.sicherung_ordner),
            "min_zeichen": konfig.ocr_min_zeichen}


def drehungen_text(gedreht: dict | None) -> str:
    """``{1: 180, 3: 90}`` -> ``"1:180,3:90"`` (Protokoll)."""
    return ",".join(f"{s}:{g}" for s, g in sorted((gedreht or {}).items()))


def gerade_text(gerade: dict | None) -> str:
    """``{1: -1.75, 2: 0.8}`` -> ``"1:-1.75,2:0.80"`` (Protokoll)."""
    return ",".join(f"{s}:{float(w):.2f}" for s, w in sorted((gerade or {}).items()))


def _gerade_erledigt(con, hashes) -> None:
    """Vormerkungen erledigt (Issue #165): auch nach Rueckgaengig und fuer Kopien des Scans nicht erneut."""
    hashes = [h for h in hashes or () if h]
    if hashes:
        con.execute(f"UPDATE schraeglage SET gerade = 0 WHERE bild_hash IN ({','.join('?' * len(hashes))})", hashes)


def _drehung_nachziehen(con, dok_id: int, gedreht: dict, hashes: dict) -> None:
    """Nach dem Drehen: Bild-Hash der Seiten und OCR-Cache auf die neue Lage umstellen (Issue #151).

    Der Cache-Eintrag der gedrehten Seite (Text, Text-PDF, beide aus dieser
    Lage) gilt unter dem neuen Hash ohne weitere Drehung; der alte bleibt fuer
    Kopien des ungedrehten Scans, aber ohne Vormerkung - eine Kopie
    (z. B. eine eigene Sicherung) wird nicht gedreht, und nach Rueckgaengig
    dreht kein Lauf die Datei erneut.
    """
    for seite, _grad in gedreht.items():
        neu = hashes.get(seite)
        r = con.execute("SELECT bild_hash FROM seiten WHERE dok_id = ? AND seite = ?", (dok_id, seite)).fetchone()
        alt = r["bild_hash"] if r else None
        if not alt:
            continue
        con.execute("UPDATE ocr_cache SET drehen = 0 WHERE bild_hash = ?", (alt,))
        if not neu or neu == alt:
            continue
        con.execute(
            """INSERT OR IGNORE INTO ocr_cache (bild_hash, text, sprachen, dpi, erstellt, ebene, ebene_am, drehung, drehen)
               SELECT ?, text, sprachen, dpi, erstellt, ebene, ebene_am, NULL, 0 FROM ocr_cache WHERE bild_hash = ?""",
            (neu, alt))
        con.execute("UPDATE seiten SET bild_hash = ? WHERE dok_id = ? AND seite = ?", (neu, dok_id, seite))


def ergebnis_eintragen(con, dok_id: int, res: dict) -> str:
    """Ergebnis von ``datei_schreiben`` in den Index: Stand der Datei, Spalten, Protokoll. Liefert den Status.

    Nach dem Schreiben bekommt der Eintrag sofort Groesse und Aenderungszeit
    der neuen Datei; der naechste Lauf liest sie deshalb nicht neu ein, und die
    Erkennung verschobener Dateien (Groesse, Aenderungszeit) passt weiter. Das
    Datum im Index (fuer Filter und Sortierung) bleibt das bisherige.
    """
    status = res.get("status")
    if status == "geschrieben":
        zeit = db.jetzt()
        gedreht = {int(k): int(v) for k, v in (res.get("gedreht") or {}).items()}
        gerade = {int(k): float(v) for k, v in (res.get("gerade") or {}).items()}
        if res["seiten"]:
            con.execute("UPDATE dokumente SET groesse = ?, mtime_ns = ?, textebene_am = ?, textebene_grund = NULL "
                        "WHERE id = ?", (res["groesse"], res["mtime_ns"], zeit, dok_id))
        else:                       # nur gedreht/ausgerichtet (#151, #165): die Textebene kann spaeter noch kommen
            con.execute("UPDATE dokumente SET groesse = ?, mtime_ns = ?, textebene_grund = NULL WHERE id = ?",
                        (res["groesse"], res["mtime_ns"], dok_id))
        con.execute(
            """INSERT INTO textebene_protokoll (dok_id, pfad, am, seiten, sicherung, groesse_vorher, mtime_ns_vorher,
                   groesse_nachher, mtime_ns_nachher, status, gedreht, gerade)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'geschrieben', ?, ?)""",
            (dok_id, res["pfad"], zeit, ",".join(str(s) for s in res["seiten"]), res.get("sicherung"),
             res.get("groesse_vorher"), res.get("mtime_ns_vorher"), res["groesse"], res["mtime_ns"],
             drehungen_text(gedreht) or None, gerade_text(gerade) or None))
        _gerade_erledigt(con, res.get("gerade_hashes"))
        if gerade:
            log.info("PDF gerade ausgerichtet: %s (Seiten %s)", res["pfad"], gerade_text(gerade))
        if gedreht:
            _drehung_nachziehen(con, dok_id, gedreht, {int(k): v for k, v in (res.get("hashes") or {}).items()})
            log.info("PDF gedreht: %s (Seiten %s)", res["pfad"], drehungen_text(gedreht))
        if res["seiten"]:
            log.info("Textebene geschrieben: %s (Seiten %s)", res["pfad"], ",".join(str(s) for s in res["seiten"]))
    elif status == "vorhanden":
        if res.get("mit_ebene", True):
            con.execute("UPDATE dokumente SET textebene_am = ?, textebene_grund = NULL WHERE id = ?",
                        (db.jetzt(), dok_id))
        _gerade_erledigt(con, res.get("gerade_hashes"))    # z. B. inzwischen von Hand ausgerichtet
    else:
        grund = res.get("grund") or "fehler"
        con.execute("UPDATE dokumente SET textebene_grund = ? WHERE id = ?", (grund, dok_id))
        if status == "fehler":
            log.warning("Textebene nicht geschrieben: %s – %s", res.get("pfad"), res.get("fehler"))
        else:
            log.info("Textebene übersprungen (%s): %s", GRUENDE.get(grund, grund), res.get("pfad"))
    return status or "fehler"


def protokoll(con, anzahl: int = 500) -> list[dict]:
    """Geaenderte Dateien, neueste zuerst; ``aktueller_pfad`` folgt Verschiebungen (ueber das Dokument)."""
    return [dict(r) for r in con.execute(
        """SELECT p.*, d.pfad AS aktueller_pfad FROM textebene_protokoll p LEFT JOIN dokumente d ON d.id = p.dok_id
           ORDER BY p.id DESC LIMIT ?""", (anzahl,))]


def rueckgaengig(con, konfig, eintrag_id: int, erzwingen: bool = False) -> tuple[bool, str]:
    """Eine Aenderung zuruecknehmen: Sicherungskopie zurueckspielen, Index nachziehen. ``(ok, meldung)``.

    Geschuetzt wie das Schreiben (temporaere Datei, ``datei_ersetzen``). Wurde
    die Datei seither geaendert (z. B. Metadaten von PDFSM), lehnt die Funktion
    ohne ``erzwingen`` ab, weil diese Aenderung sonst verloren ginge; reines
    Umbenennen und Verschieben stoeren nicht. Danach bekommt die Datei keine
    Textebene mehr automatisch (``textebene_grund = 'rueckgaengig'``).
    """
    import pymupdf

    from src.search.indexer import einzeldatei_indizieren

    r = con.execute("SELECT * FROM textebene_protokoll WHERE id = ?", (eintrag_id,)).fetchone()
    if r is None:
        return False, tr("Eintrag nicht gefunden.")
    if r["status"] != "geschrieben":
        return False, tr("Diese Änderung wurde schon rückgängig gemacht.")
    sicherung = r["sicherung"]
    if not sicherung or not os.path.isfile(sicherung):
        return False, tr("Die Sicherungskopie gibt es nicht mehr (Aufbewahrungsfrist abgelaufen).")
    aktuell = con.execute("SELECT pfad FROM dokumente WHERE id = ?", (r["dok_id"],)).fetchone() if r["dok_id"] else None
    pfad = aktuell["pfad"] if aktuell else r["pfad"]
    if not os.path.isfile(pfad):
        return False, tr("Die Datei wurde nicht gefunden: {pfad}").format(pfad=pfad)
    st = os.stat(pfad)
    if not erzwingen and (st.st_size, st.st_mtime_ns) != (r["groesse_nachher"], r["mtime_ns_nachher"]):
        return False, MELDUNG_GEAENDERT
    if plattform.gesperrt(pfad):
        return False, tr("Die Datei ist in einem anderen Programm geöffnet. Bitte schließen und erneut versuchen.")
    tmp = tmp_pfad(pfad)
    try:
        shutil.copyfile(sicherung, tmp)
        with pymupdf.open(tmp):
            pass
        alt = os.stat(sicherung)
        os.utime(tmp, ns=(alt.st_atime_ns, alt.st_mtime_ns))   # urspruengliche Aenderungszeit zurueck
        plattform.datei_ersetzen(pfad, tmp)
    except FileNotFoundError:
        return False, tr("Die Datei wurde währenddessen verschoben oder gelöscht.")
    except PermissionError:
        return False, tr("Die Datei ist in einem anderen Programm geöffnet. Bitte schließen und erneut versuchen.")
    except Exception as e:  # noqa: BLE001 - Original bleibt unveraendert
        return False, tr("Rückgängig machen fehlgeschlagen: {0}").format(extract.fehlertext(e, pfad))
    finally:
        _weg(tmp)
    dok_id = einzeldatei_indizieren(con, konfig, pfad) or r["dok_id"]
    if dok_id:
        con.execute("UPDATE dokumente SET textebene_am = NULL, textebene_grund = 'rueckgaengig' WHERE id = ?",
                    (dok_id,))
    con.execute("UPDATE textebene_protokoll SET status = 'rueckgaengig', rueckgaengig_am = ?, sicherung = NULL "
                "WHERE id = ?", (db.jetzt(), eintrag_id))
    con.commit()
    _weg(sicherung)
    log.info("Textebene rückgängig gemacht: %s", pfad)
    return True, tr("Das Original ist wiederhergestellt: {0}").format(os.path.basename(pfad))


def aufraeumen(con, konfig, jetzt: datetime | None = None) -> dict:
    """Abgelaufene Sicherungskopien loeschen und alte Text-PDFs aus dem Cache nehmen. Liefert Zaehler.

    ``textebene_sicherung_tage`` = 0 bewahrt Sicherungskopien unbegrenzt auf.
    Sicherungen ohne Protokolleintrag (Abbruch zwischen Ersetzen und Eintrag)
    laufen nach dem Datum in ihrem Namen ab.
    """
    jetzt = jetzt or datetime.now()
    erg = {"sicherungen": 0, "ebenen": 0}
    tage = int(konfig.textebene_sicherung_tage)
    if tage > 0:
        grenze = jetzt - timedelta(days=tage)
        for r in con.execute("SELECT id, sicherung FROM textebene_protokoll WHERE sicherung IS NOT NULL AND am < ?",
                             (grenze.isoformat(timespec="seconds"),)).fetchall():
            _weg(r["sicherung"])
            con.execute("UPDATE textebene_protokoll SET sicherung = NULL WHERE id = ?", (r["id"],))
            erg["sicherungen"] += 1
        ordner = konfig.sicherung_ordner
        if ordner.is_dir():
            bekannt = {os.path.normcase(r[0]) for r in con.execute(
                "SELECT sicherung FROM textebene_protokoll WHERE sicherung IS NOT NULL")}
            for f in ordner.iterdir():
                m = _SICHERUNG_ZEIT.match(f.name)
                if not m or not f.is_file() or os.path.normcase(str(f)) in bekannt:
                    continue
                try:
                    angelegt = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
                except ValueError:
                    continue
                if angelegt < grenze:
                    _weg(str(f))
                    erg["sicherungen"] += 1
    grenze_ebene = (jetzt - timedelta(days=EBENE_AUFBEWAHREN_TAGE)).isoformat(timespec="seconds")
    erg["ebenen"] = con.execute("UPDATE ocr_cache SET ebene = NULL, ebene_am = NULL "
                                "WHERE ebene IS NOT NULL AND ebene_am < ?", (grenze_ebene,)).rowcount
    return erg


# =========================================================================== Schaetzung

def _unter(pfad: str, ordner: list[str]) -> bool:
    p = os.path.normcase(pfad)
    return any(p.startswith(os.path.normcase(o).rstrip("\\/") + os.sep) for o in ordner)


def schaetzung(con, konfig, onedrive: list[str] | None = None) -> dict:
    """Was die Stufe ``alle`` fuer den Altbestand bedeutet: Dateien, Seiten, Dauer, OneDrive-Upload, Sicherungen."""
    onedrive = plattform.onedrive_ordner() if onedrive is None else onedrive
    dateien = seiten = groesse = od_dateien = od_bytes = 0
    for r in altbestand(con):
        dateien += 1
        seiten += r["ocr_seiten"] or 0
        g = r["groesse"] or 0
        groesse += g
        if onedrive and _unter(r["datei"], onedrive):
            od_dateien += 1
            od_bytes += g + (r["ocr_seiten"] or 0) * BYTES_JE_SEITE
    prozesse = max(1, konfig.anzahl_prozesse)
    return {"dateien": dateien, "seiten": seiten, "prozesse": prozesse,
            "sekunden": round(seiten * SEKUNDEN_JE_SEITE / prozesse),
            "bytes": groesse, "zuwachs_bytes": seiten * BYTES_JE_SEITE,
            "onedrive_dateien": od_dateien, "onedrive_bytes": od_bytes,
            "sicherung_tage": int(konfig.textebene_sicherung_tage)}


def _zahl(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def groesse_text(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB".replace(".", ",")
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.0f} MB"
    return f"{max(1, round(n / 1024))} KB"


def dauer_text(sekunden: float) -> str:
    if sekunden < 90:
        return tr("wenige Minuten")
    minuten = sekunden / 60
    if minuten < 90:
        return tr("etwa {0} Minuten").format(round(minuten))
    stunden = minuten / 60
    if stunden < 48:
        return tr("etwa {0} Stunden").format(round(stunden))
    return tr("etwa {0} Tage").format(round(stunden / 24))


def schaetzung_text(s: dict) -> str:
    """Schaetzung als kurzer Text (Einstellungen, ``pdfsm-dienst textebene schaetzen``)."""
    if not s["dateien"]:
        return tr("Im Index gibt es keine texterkannten PDFs ohne Textebene.")
    teile = [
        tr("{0} texterkannte PDFs mit {1} Seiten bekommen eine Textebene.").format(_zahl(s['dateien']), _zahl(s['seiten'])),
        tr(
            "Tesseract muss jede Seite noch einmal lesen (der Index kennt nur den Text, "
            "nicht seine Lage): {0} mit {prozesse} Prozessen, im Hintergrund und jederzeit "
            "anhaltbar."
        ).format(dauer_text(s['sekunden']), prozesse=s['prozesse']),
    ]
    if s["onedrive_dateien"]:
        teile.append(tr("{0} Dateien liegen in OneDrive und werden neu hochgeladen (etwa {1}).").format(_zahl(s['onedrive_dateien']), groesse_text(s['onedrive_bytes'])))
    if s["sicherung_tage"]:
        teile.append(tr(
            "Vor jeder Änderung entsteht eine Sicherungskopie; sie belegen bis zu {0} und "
            "werden nach {sicherung_tage} Tagen gelöscht."
        ).format(groesse_text(s['bytes']), sicherung_tage=s['sicherung_tage']))
    else:
        teile.append(tr(
            "Vor jeder Änderung entsteht eine Sicherungskopie; sie belegen bis zu {0} und "
            "bleiben unbegrenzt erhalten."
        ).format(groesse_text(s['bytes'])))
    return "\n\n".join(teile)
