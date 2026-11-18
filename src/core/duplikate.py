"""Doppelte Dateien erkennen (Issue #245) - Qt-frei.

Zwei Dateien gelten als doppelt, wenn ihr Inhalt Byte fuer Byte gleich ist
(gleiche Pruefsumme). Ein Foto und das daraus erzeugte PDF oder ein zweiter
Scan desselben Blatts sind verschiedene Dateien und werden nicht gemeldet.
Hat das Programm in eine abgelegte PDF schon Metadaten oder eine Textebene
geschrieben, zaehlt fuer sie auch die Pruefsumme ihres Originals (Issue #307,
:data:`ORIGINAL_SCHLUESSEL`) - sofern der Suchindex sie kennt. Innerhalb eines
Ordners (:func:`gleiche_im_ordner`) gelten ausserdem zwei abgelegte Fassungen
desselben Originals als doppelt, auch solche ohne Vermerk, wenn ihre Seiten
dieselben Bilder zeigen (Issue #383, :class:`PdfMerkmale`).

Gerechnet wird sparsam: Nur Dateien gleicher Groesse koennen gleich sein, also
wird eine Pruefsumme erst gebildet, wenn es eine zweite Datei derselben Groesse
gibt. Einmal gebildete Pruefsummen merkt sich :class:`Pruefsummen`, solange
Groesse und Aenderungszeit der Datei gleich bleiben. Fuer Dokumente im
Suchindex schreibt der Indexlauf die Pruefsumme mit (``dokumente.pruefsumme``,
``src/search/db.py``); sie gilt nur, solange die Datei seitdem unveraendert ist.

Keine Funktion dieses Moduls gehoert in den Thread der Oberflaeche: Alle lesen
von der Platte. Dateien, die nur als Platzhalter in der Cloud liegen
(OneDrive „nur online“), werden nie geoeffnet - das wuerde sie herunterladen.
"""

from __future__ import annotations

import hashlib
import os
import stat as stat_modul
import threading
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.search.plattform import nur_cloud, verknuepfung

_BLOCK = 1 << 20  # 1 MB je Lesevorgang


def pruefsumme(pfad: Path | str) -> str:
    """BLAKE2b (16 Byte, hex) ueber den Inhalt der Datei.

    Raises:
        OSError: Datei fehlt oder ist nicht lesbar.
    """
    h = hashlib.blake2b(digest_size=16)
    with open(pfad, "rb") as f:
        while True:
            block = f.read(_BLOCK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def stand_text(groesse: int, mtime_ns: int) -> str:
    """Stand einer Datei, zu dem eine gespeicherte Pruefsumme gehoert (``dokumente.pruefsumme_stand``)."""
    return f"{groesse}:{mtime_ns}"


# Issue #307: Pruefsumme des Originals einer PDF. Bevor das Programm zum ersten Mal in eine PDF
# schreibt (Metadaten beim Ablegen, Textebene, Drehen), traegt es Groesse und Pruefsumme der
# unveraenderten Datei als "<Groesse>:<Pruefsumme>" in deren Info-Dictionary ein. Der Indexlauf
# liest den Eintrag (``dokumente.original_groesse``/``original_pruefsumme``), damit ein zweites
# Exemplar desselben Originals auch dann als doppelt gilt, wenn die abgelegte Fassung sich geaendert hat.
ORIGINAL_SCHLUESSEL = "PSMOriginal"


def original_text(groesse: int, summe: str) -> str:
    return f"{int(groesse)}:{summe}"


def original_lesen(text) -> Optional[tuple[int, str]]:
    """``(groesse, pruefsumme)`` aus einem Eintrag ``"<Groesse>:<Pruefsumme>"``; None, wenn er nicht passt."""
    try:
        groesse, summe = str(text).strip().split(":", 1)
        groesse_int = int(groesse)
    except (ValueError, TypeError):
        return None
    summe = summe.strip().lower()
    if groesse_int <= 0 or len(summe) != 32 or any(c not in "0123456789abcdef" for c in summe):
        return None
    return groesse_int, summe


def _original_der_datei(pfad: Path | str) -> Optional[str]:
    """Eintrag fuer die Datei, wie sie jetzt auf der Platte liegt; None, wenn sie nicht lesbar ist."""
    try:
        st = os.stat(pfad)
        if not _vergleichbar(st):
            return None
        return original_text(st.st_size, pruefsumme(pfad))
    except OSError:
        return None


def original_eintragen_pikepdf(pdf, pfad: Path | str) -> None:
    """Vor dem Speichern einer mit pikepdf geoeffneten PDF: Original merken, falls noch nicht geschehen.

    ``pfad`` muss zu diesem Zeitpunkt noch unveraendert auf der Platte liegen.
    """
    try:
        schluessel = "/" + ORIGINAL_SCHLUESSEL
        if schluessel in pdf.docinfo:
            return
        wert = _original_der_datei(pfad)
        if wert:
            pdf.docinfo[schluessel] = wert
    except Exception:  # noqa: BLE001 - ohne Eintrag weiter; das Speichern selbst darf nicht scheitern
        pass


def original_eintragen_pymupdf(doc, pfad: Path | str) -> None:
    """Wie :func:`original_eintragen_pikepdf` fuer ein mit PyMuPDF geoeffnetes Dokument."""
    try:
        import pymupdf

        info = doc.xref_get_key(-1, "Info")
        if info and info[0] == "xref":
            xref = int(str(info[1]).split()[0])
            if doc.xref_get_key(xref, ORIGINAL_SCHLUESSEL)[0] != "null":
                return
        else:
            xref = None
        wert = _original_der_datei(pfad)
        if not wert:
            return
        if xref is None:
            xref = doc.get_new_xref()
            doc.update_object(xref, "<<>>")
            doc.xref_set_key(-1, "Info", f"{xref} 0 R")
        doc.xref_set_key(xref, ORIGINAL_SCHLUESSEL, pymupdf.get_pdf_str(wert))
    except Exception:  # noqa: BLE001 - ohne Eintrag weiter
        pass


def original_aus_pdf(pfad: Path | str) -> Optional[tuple[int, str]]:
    """``(groesse, pruefsumme)`` des Originals, wie in der PDF vermerkt; None ohne (gueltigen) Eintrag."""
    try:
        import pymupdf

        with pymupdf.open(str(pfad)) as doc:
            info = doc.xref_get_key(-1, "Info")
            if not info or info[0] != "xref":
                return None
            art, wert = doc.xref_get_key(int(str(info[1]).split()[0]), ORIGINAL_SCHLUESSEL)
    except Exception:  # noqa: BLE001 - keine oder kaputte PDF
        return None
    return original_lesen(wert) if art == "string" else None


def _vergleichbar(st: os.stat_result) -> bool:
    """Regulaere, nicht leere Datei, die sich lesen laesst, ohne sie herunterzuladen."""
    return stat_modul.S_ISREG(st.st_mode) and st.st_size > 0 and not nur_cloud(st)


class Pruefsummen:
    """Zwischenspeicher: Pfad -> Pruefsumme, gueltig fuer genau eine Groesse und Aenderungszeit.

    Aus mehreren Threads benutzbar. Er lebt nur im Arbeitsspeicher; nach einem
    Neustart werden die wenigen Dateien gleicher Groesse neu gelesen.
    """

    GRENZE = 50_000  # so viele Eintraege hoechstens (rund 10 MB), danach wird neu begonnen

    def __init__(self) -> None:
        self._sperre = threading.Lock()
        self._werte: dict[str, tuple[int, int, str]] = {}
        self.gerechnet = 0  # so oft wurde eine Datei wirklich gelesen (Tests, Messung)

    def summe(self, pfad: Path | str, st: Optional[os.stat_result] = None) -> Optional[str]:
        """Pruefsumme der Datei; None, wenn sie fehlt, leer, nicht lesbar oder nur online ist
        oder sich waehrend des Lesens geaendert hat."""
        try:
            if st is None:
                st = os.stat(pfad)
            if not _vergleichbar(st):
                return None
            key = os.path.normcase(str(pfad))
            with self._sperre:
                alt = self._werte.get(key)
            if alt is not None and alt[0] == st.st_size and alt[1] == st.st_mtime_ns:
                return alt[2]
            wert = pruefsumme(pfad)
            danach = os.stat(pfad)
        except OSError:
            return None
        if (danach.st_size, danach.st_mtime_ns) != (st.st_size, st.st_mtime_ns):
            return None  # wird gerade geschrieben
        with self._sperre:
            self.gerechnet += 1
            if len(self._werte) >= self.GRENZE:
                self._werte.clear()
            self._werte[key] = (st.st_size, st.st_mtime_ns, wert)
        return wert


# Ein gemeinsamer Zwischenspeicher fuer das Programm
_summen = Pruefsummen()


def summen() -> Pruefsummen:
    return _summen


# Issue #383: Zwei abgelegte Fassungen desselben Originals sind nicht mehr Byte fuer Byte gleich
# (jede traegt ihre eigenen Metadaten). Im Ordner zaehlen deshalb auch
# - der Vermerk des Originals (ORIGINAL_SCHLUESSEL): Vermerk gegen Vermerk und Vermerk gegen den
#   heutigen Inhalt einer anderen Datei, und
# - fuer PDFs ohne Vermerk (etwa vor v0.31 abgelegt): die Bilder auf den Seiten. Metadaten,
#   Textebene und Drehung lassen sie unveraendert. In drei Stufen, jede nur fuer die Dateien, die
#   die vorige mit einer anderen gemeinsam haben: Seitenzahl und Bildgroessen (beim ohnehin
#   noetigen Oeffnen), dann die Bildstroeme roh (ohne sie zu dekodieren), zuletzt ein kleines Bild
#   jeder Seite ohne Drehung. Die letzte Stufe trennt Dateien mit gleichem Bild, aber
#   verschiedenem sichtbarem Text (Briefbogen oder Logo auf zwei Monatsrechnungen); eine
#   unsichtbare Textebene zeichnet sie nicht. Ein Vergleich ueber den erkannten Text gehoert
#   ausdruecklich nicht dazu.

ANSICHT_DPI = 24  # Aufloesung des kleinen Seitenbilds der letzten Stufe


def _vorpruefung(doc) -> Optional[tuple]:
    """Seitenzahl und Bildgroessen je Seite; None, wenn eine Seite gar kein Bild hat."""
    seiten = []
    for nr in range(doc.page_count):
        bilder = doc.get_page_images(nr)
        if not bilder:
            return None
        seiten.append(tuple(sorted((b[2], b[3]) for b in bilder)))
    return (doc.page_count, tuple(seiten)) if seiten else None


def _bildabdruck(doc) -> str:
    """Pruefsumme ueber die rohen Bildstroeme aller Seiten (nichts wird dekodiert)."""
    gesamt = hashlib.blake2b(digest_size=16)
    for nr in range(doc.page_count):
        summen = sorted(hashlib.blake2b(doc.xref_stream_raw(b[0]) or b"", digest_size=16).hexdigest()
                        for b in doc.get_page_images(nr))
        gesamt.update(("|".join(summen) + ";").encode("ascii"))
    return gesamt.hexdigest()


def _ansicht(doc) -> str:
    """Pruefsumme ueber ein kleines Graustufenbild jeder Seite, ohne ihre Drehung."""
    import pymupdf

    gesamt = hashlib.blake2b(digest_size=16)
    for seite in doc:
        if seite.rotation:
            seite.set_rotation(0)  # nur im Speicher; die Datei wird nicht gespeichert
        pix = seite.get_pixmap(dpi=ANSICHT_DPI, colorspace=pymupdf.csGRAY, alpha=False, annots=False)
        gesamt.update(f"{pix.width}x{pix.height};".encode("ascii"))
        gesamt.update(pix.samples)
    return gesamt.hexdigest()


class PdfMerkmale:
    """Zwischenspeicher fuer Vermerk und Bildvergleich einer PDF (Issue #383).

    Gueltig fuer genau eine Groesse und Aenderungszeit, aus mehreren Threads benutzbar.
    """

    GRENZE = 50_000

    def __init__(self) -> None:
        self._sperre = threading.Lock()
        self._werte: dict[str, tuple[int, int, dict]] = {}
        self.geoeffnet = 0  # so oft wurde eine PDF wirklich geoeffnet (Tests, Messung)

    def _wert(self, pfad: Path, st: os.stat_result, name: str, rechnen: Callable):
        key = os.path.normcase(str(pfad))
        with self._sperre:
            alt = self._werte.get(key)
        werte = alt[2] if alt is not None and alt[:2] == (st.st_size, st.st_mtime_ns) else {}
        if name in werte:
            return werte[name]
        try:
            import pymupdf

            with pymupdf.open(str(pfad)) as doc:
                with self._sperre:
                    self.geoeffnet += 1
                wert = rechnen(doc)
        except Exception:  # noqa: BLE001 - keine oder kaputte PDF: ohne dieses Merkmal
            wert = None
        with self._sperre:
            if len(self._werte) >= self.GRENZE:
                self._werte.clear()
            self._werte[key] = (st.st_size, st.st_mtime_ns, dict(werte, **{name: wert}))
        return wert

    def grunddaten(self, pfad: Path, st: os.stat_result) -> dict:
        """``{"original": (groesse, summe) | None, "vor": tuple | None}`` (Vermerk und Vorpruefung)."""
        def rechnen(doc):
            original = None
            info = doc.xref_get_key(-1, "Info")
            if info and info[0] == "xref":
                art, wert = doc.xref_get_key(int(str(info[1]).split()[0]), ORIGINAL_SCHLUESSEL)
                if art == "string":
                    original = original_lesen(wert)
            return {"original": original, "vor": _vorpruefung(doc)}

        return self._wert(pfad, st, "grund", rechnen) or {"original": None, "vor": None}

    def bildabdruck(self, pfad: Path, st: os.stat_result) -> Optional[str]:
        return self._wert(pfad, st, "bild", _bildabdruck)

    def ansicht(self, pfad: Path, st: os.stat_result) -> Optional[str]:
        return self._wert(pfad, st, "ansicht", _ansicht)


_merkmale = PdfMerkmale()


def selbe_datei(a: Path | str, b: Path | str) -> bool:
    """Dieselbe Datei bzw. derselbe Ordner - auch ueber zwei Schreibweisen des Pfads (Junction, #220)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def gleiche_im_ordner(pfade: Iterable[Path | str],
                      speicher: Optional[Pruefsummen] = None,
                      abbrechen: Optional[Callable[[], bool]] = None,
                      fortschritt: Optional[Callable[[int, int], None]] = None,
                      merkmale: Optional[PdfMerkmale] = None) -> list[list[Path]]:
    """Gruppen gleicher Dateien unter ``pfade`` (je Gruppe mindestens zwei, Reihenfolge wie uebergeben).

    Gleich sind Dateien mit demselben Inhalt und - Issue #383 - PDFs, die auf dasselbe
    Original zurueckgehen (Vermerk :data:`ORIGINAL_SCHLUESSEL`) oder dieselben Scanbilder
    tragen (siehe :class:`PdfMerkmale`). Gelesen werden nur Dateien, die ihre Groesse mit
    einer anderen oder mit einem vermerkten Original teilen; geoeffnet wird jede PDF einmal
    (danach aus dem Zwischenspeicher). ``abbrechen()`` wird vor jeder zu lesenden Datei
    gefragt (True: sofort mit dem bisherigen Ergebnis zurueck), ``fortschritt(gelesen,
    zu_lesen)`` danach gemeldet.
    """
    speicher = speicher or _summen
    merkmale = merkmale or _merkmale
    dateien: list[tuple[Path, os.stat_result]] = []
    for p in pfade:
        try:
            st = os.stat(p)
        except OSError:
            continue
        if _vergleichbar(st):
            dateien.append((Path(p), st))

    eltern = list(range(len(dateien)))

    def wurzel(i: int) -> int:
        while eltern[i] != i:
            eltern[i] = eltern[eltern[i]]
            i = eltern[i]
        return i

    def verbinden(i: int, j: int) -> None:
        a, b = wurzel(i), wurzel(j)
        if a != b:
            eltern[max(a, b)] = min(a, b)

    def ergebnis() -> list[list[Path]]:
        gruppen: dict[int, list[Path]] = {}
        for i, (p, _st) in enumerate(dateien):
            gruppen.setdefault(wurzel(i), []).append(p)
        return [g for _w, g in sorted(gruppen.items()) if len(g) > 1]

    pdfs = [i for i, (p, _st) in enumerate(dateien) if p.suffix.lower() == ".pdf"]
    nach_groesse: dict[int, list[int]] = {}
    for i, (_p, st) in enumerate(dateien):
        nach_groesse.setdefault(st.st_size, []).append(i)

    zu_lesen = sum(len(g) for g in nach_groesse.values() if len(g) > 1) + len(pdfs)
    gelesen = 0

    def weiter() -> bool:
        return not (abbrechen is not None and abbrechen())

    def gemeldet() -> None:
        nonlocal gelesen
        gelesen += 1
        if fortschritt is not None:
            fortschritt(gelesen, zu_lesen)

    # 1. Vermerke und Vorpruefung der PDFs (je PDF einmal oeffnen)
    grund: dict[int, dict] = {}
    for i in pdfs:
        if not weiter():
            return ergebnis()
        grund[i] = merkmale.grunddaten(*dateien[i])
        gemeldet()
    vermerkt = {i: w["original"] for i, w in grund.items() if w.get("original")}
    original_groessen = {o[0] for o in vermerkt.values()}

    # 2. Pruefsummen: gleiche Groesse untereinander, oder so gross wie ein vermerktes Original
    zu_summieren = [i for g in nach_groesse.values() if len(g) > 1 for i in g]
    zu_summieren += [i for g, liste in nach_groesse.items() if len(liste) == 1 and g in original_groessen
                     for i in liste]
    zu_lesen = len(pdfs) + len(zu_summieren)
    nach_schluessel: dict[tuple[int, str], int] = {}
    for i in zu_summieren:
        if not weiter():
            return ergebnis()
        p, st = dateien[i]
        wert = speicher.summe(p, st)
        gemeldet()
        if wert:
            schluessel = (st.st_size, wert)
            if schluessel in nach_schluessel:
                verbinden(i, nach_schluessel[schluessel])
            else:
                nach_schluessel[schluessel] = i
    for i, original in vermerkt.items():
        if original in nach_schluessel:
            verbinden(i, nach_schluessel[original])
        else:
            nach_schluessel[original] = i

    # 3. Bilder, nur wo Seitenzahl und Bildgroessen schon passen; zuletzt die Ansicht der Seiten
    def teilen(gruppen: Iterable[list[int]], merkmal: Callable) -> Optional[list[list[int]]]:
        """Teilt jede Gruppe nach ``merkmal``; None nach ``abbrechen()``."""
        neu: list[list[int]] = []
        for kandidaten in gruppen:
            if len(kandidaten) < 2 or len({wurzel(i) for i in kandidaten}) < 2:
                continue  # allein, oder ohnehin schon als gleich erkannt
            nach_wert: dict = {}
            for i in kandidaten:
                if not weiter():
                    return None
                wert = merkmal(*dateien[i])
                if wert:
                    nach_wert.setdefault(wert, []).append(i)
            neu.extend(nach_wert.values())
        return neu

    nach_vor: dict[tuple, list[int]] = {}
    for i, w in grund.items():
        if w.get("vor"):
            nach_vor.setdefault(w["vor"], []).append(i)
    gleiche_bilder = teilen(nach_vor.values(), merkmale.bildabdruck)
    gleich_anzusehen = teilen(gleiche_bilder or [], merkmale.ansicht)
    for gruppe in gleich_anzusehen or []:
        for i in gruppe[1:]:
            verbinden(gruppe[0], i)
    return ergebnis()


def dateien_unter(ordner: Path | str, abbrechen: Optional[Callable[[], bool]] = None) -> list[Path]:
    """Alle Dateien in ``ordner`` und seinen Unterordnern (Issue #299).

    Nicht betreten werden versteckte Ordner (Name beginnt mit „.“ oder „$“, etwa
    ``$RECYCLE.BIN``) sowie Junctions und Symlinks - sonst kaeme eine Datei ueber
    zwei Wege doppelt vor, oder die Suche liefe im Kreis. Nicht lesbare Ordner
    werden uebersprungen. Bei ``abbrechen()`` endet die Suche mit dem bisher Gefundenen.
    """
    dateien: list[Path] = []
    offen = [str(ordner)]
    while offen:
        if abbrechen is not None and abbrechen():
            break
        aktuell = offen.pop()
        try:
            with os.scandir(aktuell) as eintraege:
                for e in eintraege:
                    try:
                        st = e.stat(follow_symlinks=False)
                        if verknuepfung(st) or stat_modul.S_ISLNK(st.st_mode):
                            continue
                        if stat_modul.S_ISDIR(st.st_mode):
                            if not e.name.startswith((".", "$")):
                                offen.append(e.path)
                        elif stat_modul.S_ISREG(st.st_mode):
                            dateien.append(Path(e.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return dateien


def doppelte_unter(ordner: Path | str, speicher: Optional[Pruefsummen] = None,
                   abbrechen: Optional[Callable[[], bool]] = None,
                   fortschritt: Optional[Callable[[int, int], None]] = None) -> list[list[Path]]:
    """Gruppen inhaltsgleicher Dateien in ``ordner`` samt Unterordnern (Issue #299).

    Je Gruppe die aelteste Datei (Aenderungszeit) zuerst; die Gruppen nach dem
    Pfad ihrer ersten Datei. Dateien nur in der Cloud (OneDrive „nur online“)
    werden nicht gelesen und fehlen deshalb.
    """
    pfade = dateien_unter(ordner, abbrechen)
    gruppen = gleiche_im_ordner(pfade, speicher, abbrechen, fortschritt)

    def alter(p: Path):
        try:
            return (os.stat(p).st_mtime_ns, str(p).lower())
        except OSError:
            return (0, str(p).lower())

    gruppen = [sorted(g, key=alter) for g in gruppen]
    gruppen.sort(key=lambda g: str(g[0]).lower())
    return gruppen


def ordner_nach_groesse(ordner: Path | str) -> dict[int, list[Path]]:
    """Dateien eines Ordners nach Groesse; leer, wenn es ihn (noch) nicht gibt oder er nicht erreichbar ist."""
    dateien: dict[int, list[Path]] = {}
    try:
        with os.scandir(ordner) as eintraege:
            for e in eintraege:
                try:
                    if e.is_file():
                        dateien.setdefault(e.stat().st_size, []).append(Path(e.path))
                except OSError:
                    continue
    except OSError:
        pass
    return dateien


def gleiche_anderswo(quelle: Path | str, zielordner: Optional[Path | str | dict] = None,
                     index_kandidaten: Optional[Callable[[int], list[dict]]] = None,
                     speicher: Optional[Pruefsummen] = None) -> list[Path]:
    """Dateien mit demselben Inhalt wie ``quelle``: im Zielordner und unter den Dokumenten des Suchindex.

    ``zielordner`` ist ein Ordner oder - wenn mehrere Dateien in denselben Ordner
    sollen - dessen einmal gelesener Inhalt aus :func:`ordner_nach_groesse`.
    ``index_kandidaten(groesse)`` liefert die Dokumente dieser Groesse als
    ``{"pfad", "pruefsumme", "pruefsumme_stand"}`` (``Suchindex.gleiche_groesse``).
    Eine dort gespeicherte Pruefsumme zaehlt nur, wenn die Datei noch den Stand
    hat, zu dem sie gebildet wurde; sonst wird die Datei gelesen. So werden auch
    Dokumente erkannt, die inzwischen nur noch online liegen. Zeilen mit
    ``"original": True`` tragen die Pruefsumme des Originals einer abgelegten
    PDF (Issue #307); sie gilt unabhaengig von Groesse und Stand der Datei.
    ``quelle`` selbst ist nie dabei.
    """
    speicher = speicher or _summen
    try:
        st = os.stat(quelle)
    except OSError:
        return []
    if not _vergleichbar(st):
        return []
    groesse = st.st_size

    kandidaten: dict[str, tuple[Path, Optional[dict]]] = {}
    originale: list[tuple[Path, str]] = []  # Issue #307: abgelegte PDFs, deren Original so gross war
    if zielordner is not None:
        im_ziel = zielordner if isinstance(zielordner, dict) else ordner_nach_groesse(zielordner)
        for pfad in im_ziel.get(groesse, []):
            kandidaten[os.path.normcase(str(pfad))] = (pfad, None)
    if index_kandidaten is not None:
        try:
            zeilen = index_kandidaten(groesse)
        except Exception:  # noqa: BLE001 - ohne Suchindex bleibt der Vergleich im Zielordner
            zeilen = []
        for zeile in zeilen:
            pfad = zeile.get("pfad")
            if pfad and zeile.get("original"):
                if zeile.get("pruefsumme"):
                    originale.append((Path(pfad), zeile["pruefsumme"]))
            elif pfad:
                key = os.path.normcase(str(pfad))
                vorher = kandidaten.get(key)
                kandidaten[key] = (vorher[0] if vorher else Path(pfad), zeile)
    if not kandidaten and not originale:
        return []

    eigene = speicher.summe(quelle, st)
    if eigene is None:
        return []
    treffer: list[Path] = []
    for pfad, zeile in kandidaten.values():
        try:
            kst = os.stat(pfad)
        except OSError:
            continue  # im Index, aber nicht mehr auf der Platte
        if not stat_modul.S_ISREG(kst.st_mode) or kst.st_size != groesse or selbe_datei(pfad, quelle):
            continue
        if (zeile and zeile.get("pruefsumme")
                and zeile.get("pruefsumme_stand") == stand_text(kst.st_size, kst.st_mtime_ns)):
            wert = zeile["pruefsumme"]
        else:
            wert = speicher.summe(pfad, kst)
        if wert == eigene and not any(selbe_datei(pfad, t) for t in treffer):
            treffer.append(pfad)
    for pfad, wert in originale:
        if wert != eigene:
            continue
        try:
            if not stat_modul.S_ISREG(os.stat(pfad).st_mode) or selbe_datei(pfad, quelle):
                continue
        except OSError:
            continue  # im Index, aber nicht mehr auf der Platte
        if not any(selbe_datei(pfad, t) for t in treffer):
            treffer.append(pfad)
    return treffer
