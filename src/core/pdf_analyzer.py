"""
PDF-Analyzer für PDF Sortier Meister

Funktionen:
- Thumbnail-Generierung aus PDFs
- Textextraktion (direkt und via OCR)
- Metadaten-Extraktion

Seit Phase 5 der PDFsuche-Integration kommt der Text aus dem Suchindex, wenn
die Datei dort aktuell ist (Groesse und mtime stimmen). Sonst liest der
Analyzer mit denselben Funktionen wie der Index (``src.search.extract``:
Textebene, OCR ueber Tesseract mit ``deu+eng`` und 300 dpi, hoechstens fuenf
Bildseiten interaktiv) und schreibt das Ergebnis zurueck (``datei_aufnehmen``,
``ocr_eintragen``), damit der naechste Lauf nichts doppelt erkennt.
"""

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

import fitz  # PyMuPDF
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice


def _search_konfig():
    """SearchConfig des Nutzers; None, wenn keine Konfiguration erreichbar ist."""
    try:
        from src.utils.config import get_config
        return get_config().get_search_config()
    except Exception:  # noqa: BLE001 - ohne Konfiguration laeuft die Analyse wie frueher
        return None


def suchindex_fuer_analyse():
    """Suchindex fuer Text aus dem Index und das Zurueckschreiben; None, wenn die Suche nicht eingerichtet ist.

    Tests ersetzen diese Funktion, damit kein Zugriff auf den Index des Nutzers stattfindet.
    """
    konfig = _search_konfig()
    if konfig is None or not konfig.aktiv:
        return None
    from src.search.suchindex import Suchindex
    return Suchindex(konfig)


def ocr_einstellungen_fuer_analyse() -> Optional[dict]:
    """Tesseract-Einstellungen fuer die interaktive OCR (wie der Index: ``deu+eng``, 300 dpi, psm 1).

    Fehlen einzelne Sprachdaten, wird mit den vorhandenen erkannt; ohne
    Tesseract oder ganz ohne Sprachdaten None.
    """
    from src.search.konfig import SearchConfig
    from src.utils.tesseract import fehlende_sprachen

    konfig = _search_konfig() or SearchConfig()
    cfg = konfig.ocr_einstellungen()
    if not cfg.get("tesseract"):
        return None
    fehlend = set(fehlende_sprachen(cfg.get("tessdata"), cfg["sprachen"]))
    rest = [s for s in cfg["sprachen"].split("+") if s and s not in fehlend]
    if not rest:
        return None
    cfg["sprachen"] = "+".join(rest)
    return cfg


def ocr_neu_durchfuehren(pdf_path: Path | str, abbrechen=None) -> dict:
    """Bildseiten einer PDF neu erkennen, am OCR-Cache vorbei (Issue #150).

    Fuer "OCR neu durchführen" im Kontextmenue: Der OCR-Cache (Bild-Hash ->
    Text) wuerde sonst den alten Text liefern. Erkannt werden alle Seiten ohne
    Textebene, das Ergebnis ersetzt Seiten und Cache-Eintraege im Suchindex
    (``ocr_eintragen(..., ersetzen=True)``); Dateien ausserhalb der Wurzeln
    nimmt der Index dafuer auf. Ohne eingerichtete Suche gibt es keinen Cache:
    Dann passiert hier nichts, und die naechste Analyse erkennt die Datei neu
    (``"index": False``). ``abbrechen`` (Funktion ohne Argumente) wird vor
    jeder Seite gefragt.

    Liegt eine Seite falsch herum, liest Tesseract sie auch gedreht
    (Issue #151); die Lage merkt sich der Index. Weil der Nutzer die neue
    Erkennung ausdruecklich verlangt hat, dreht der naechste Indexlauf die
    Datei, wo sie auch liegt - ausser ``auto_drehen`` ist aus.

    Liefert ``{"index": bool, "seiten": int, "fehler": str | None}``, dazu
    ``"gedreht": int``, wenn Seiten erst gedreht lesbar waren.
    """
    from src.search import extract as suche_extract

    erg: dict = {"index": False, "seiten": 0, "fehler": None}
    index = suchindex_fuer_analyse()
    if index is None:
        return erg
    erg["index"] = True
    pfad = str(pdf_path)
    gelesen = suche_extract.pdf_text(pfad, index.konfig.ocr_min_zeichen)
    if gelesen["status"] in ("fehler", "verschluesselt"):
        erg["fehler"] = gelesen.get("fehler") or "Die PDF ist verschlüsselt."
        return erg
    if index.datei_aufnehmen(pfad, erzwingen=True, vorab=gelesen) is None:
        erg["fehler"] = "Die Datei konnte nicht in den Suchindex aufgenommen werden."
        return erg
    offen = list(gelesen["ohne_text"])
    if not offen:
        return erg
    cfg = ocr_einstellungen_fuer_analyse()
    if cfg is None:
        erg["fehler"] = "Tesseract nicht gefunden - keine Texterkennung möglich."
        return erg
    if index.konfig.textebene_erzeugen(pfad):
        cfg["textebene"] = True
    texte: dict = {}
    ebenen: dict = {}
    drehungen: dict = {}
    for nr in offen:
        if abbrechen is not None and abbrechen():
            break
        res = suche_extract.pdf_ocr(pfad, [nr], cfg)
        if res.get("fehler"):
            erg["fehler"] = res["fehler"]
        text = res["texte"].get(nr)
        if text and text.strip():
            texte[nr] = text
            if res.get("ebenen", {}).get(nr):
                ebenen[nr] = res["ebenen"][nr]
            if res.get("drehungen", {}).get(nr):
                drehungen[nr] = res["drehungen"][nr]
    if texte:
        erg["seiten"] = index.ocr_eintragen(pfad, texte, ebenen=ebenen or None, ersetzen=True,
                                            drehungen=drehungen or None,
                                            drehen=index.konfig.auto_drehen != "aus")
    if drehungen:
        erg["gedreht"] = len(drehungen)
    return erg


class PDFAnalyzer:
    """Analysiert PDF-Dateien und extrahiert Informationen."""

    # Interaktive OCR: hoechstens so viele Bildseiten, damit die Oberflaeche schnell antwortet
    OCR_MAX_SEITEN = 5

    def __init__(self, pdf_path: Path | str):
        """
        Initialisiert den PDF-Analyzer.

        Args:
            pdf_path: Pfad zur PDF-Datei
        """
        self.pdf_path = Path(pdf_path)
        self._doc: Optional[fitz.Document] = None
        self._text: Optional[str] = None
        self._thumbnail: Optional[QPixmap] = None
        # True, sobald extract_text() auf OCR zurueckgreifen musste (Log, #108)
        self.ocr_used = False

    def __enter__(self):
        """Context Manager Eintritt."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context Manager Austritt."""
        self.close()

    def open(self) -> None:
        """Öffnet das PDF-Dokument."""
        if self._doc is None:
            self._doc = fitz.open(str(self.pdf_path))

    def close(self) -> None:
        """Schließt das PDF-Dokument."""
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    @property
    def page_count(self) -> int:
        """Gibt die Anzahl der Seiten zurück."""
        self.open()
        return len(self._doc)

    @property
    def filename(self) -> str:
        """Gibt den Dateinamen zurück."""
        return self.pdf_path.name

    def generate_thumbnail(
        self,
        page_num: int = 0,
        width: int = 150,
        height: int = 200
    ) -> QPixmap:
        """
        Generiert ein Thumbnail der ersten Seite.

        Args:
            page_num: Seitennummer (0-basiert)
            width: Maximale Breite des Thumbnails
            height: Maximale Höhe des Thumbnails

        Returns:
            QPixmap mit dem Thumbnail
        """
        if self._thumbnail is not None:
            return self._thumbnail

        self.open()

        if page_num >= len(self._doc):
            page_num = 0

        page = self._doc[page_num]

        # Skalierungsfaktor berechnen
        page_rect = page.rect
        scale_x = width / page_rect.width
        scale_y = height / page_rect.height
        scale = min(scale_x, scale_y)

        # Matrix für Skalierung
        matrix = fitz.Matrix(scale, scale)

        # Seite als Pixmap rendern
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        # In QPixmap konvertieren
        img_data = pix.tobytes("ppm")
        qimg = QImage.fromData(QByteArray(img_data))
        self._thumbnail = QPixmap.fromImage(qimg)

        return self._thumbnail

    def extract_text(self, use_ocr: bool = True) -> str:
        """
        Extrahiert den Text aus dem PDF.

        Reihenfolge: aktueller Eintrag im Suchindex -> Textebene mit
        ``src.search.extract.pdf_text`` (Bildseiten bekommen OCR-Text aus dem
        Cache) -> interaktive OCR der ersten Bildseiten. Was der Analyzer selbst
        liest oder erkennt, geht an den Index zurueck.

        Args:
            use_ocr: Falls True, wird OCR verwendet wenn Bildseiten ohne Text da sind

        Returns:
            Der extrahierte Text
        """
        if self._text is not None:
            return self._text

        pfad = str(self.pdf_path)
        index = suchindex_fuer_analyse()
        stand = self._textstand(index, pfad)
        if stand is not None and stand["aktuell"] and stand["textstatus"] in TEXT_AUS_INDEX:
            self._text = self._text_aus_seiten(stand["seiten"])
            return self._text

        if stand is not None and stand["aktuell"] and stand["textstatus"] == "ocr_ausstehend":
            seiten, offen = list(stand["seiten"]), list(stand["ocr_offen"])
        else:
            from src.search import extract as suche_extract

            konfig = _search_konfig()
            gelesen = suche_extract.pdf_text(pfad, konfig.ocr_min_zeichen if konfig else 25)
            if gelesen["status"] in ("fehler", "verschluesselt"):
                self._text = self._text_direkt()
                return self._text
            seiten, offen = list(gelesen["seiten"]), list(gelesen["ohne_text"])
            if index is not None:
                try:
                    if index.datei_aufnehmen(pfad, vorab=gelesen) is not None:
                        neu = self._textstand(index, pfad)
                        if neu is not None and neu["aktuell"]:
                            # OCR-Cache kann Bildseiten schon gefuellt haben
                            seiten, offen = list(neu["seiten"]), list(neu["ocr_offen"])
                except Exception as e:  # noqa: BLE001 - Index ist Zusatz, nie Blocker
                    print(f"Suchindex: Datei nicht aufgenommen: {e}")

        if offen and use_ocr:
            self.ocr_used = True
            # Neuer Scan im ersten Vorrang-Ordner (bzw. Stufe „alle“): Textebene im selben Tesseract-Aufruf
            mit_ebene = index is not None and index.konfig.textebene_erzeugen(pfad)
            erkannt, ebenen = self._ocr_seiten(offen[:self.OCR_MAX_SEITEN], textebene=mit_ebene)
            if erkannt:
                seiten = [(nr, "ocr", erkannt[nr]) if nr in erkannt else (nr, q, txt) for nr, q, txt in seiten]
                if index is not None:
                    try:
                        index.ocr_eintragen(pfad, erkannt, ebenen=ebenen or None,
                                            drehungen=self._ocr_drehungen or None)
                    except Exception as e:  # noqa: BLE001
                        print(f"Suchindex: OCR nicht eingetragen: {e}")

        self._text = self._text_aus_seiten(seiten)
        return self._text

    @staticmethod
    def _textstand(index, pfad: str):
        if index is None:
            return None
        try:
            return index.text_fuer_datei(pfad)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _text_aus_seiten(seiten) -> str:
        return "\n".join(txt for _, _, txt in seiten if txt and txt.strip())

    def _text_direkt(self) -> str:
        """Bisheriger Weg (Textebene ueber das offene Dokument), wenn ``extract.pdf_text`` nicht lesen konnte."""
        try:
            self.open()
            return "\n".join(p.get_text() for p in self._doc if p.get_text().strip())
        except Exception:  # noqa: BLE001
            return ""

    def _ocr_seiten(self, seiten: list[int], textebene: bool = False) -> tuple[dict[int, str], dict[int, bytes]]:
        """Bildseiten mit Tesseract erkennen (gemeinsame Funktion mit dem Index).

        Liefert ``({seite: text}, {seite: text_pdf})``; die Text-PDFs fuer die
        unsichtbare Textebene (Phase 5b) nur mit ``textebene``, aus demselben
        Tesseract-Aufruf. Geschrieben werden sie vom naechsten Indexlauf.
        Seiten, die Tesseract gedreht besser las (Issue #151), stehen danach in
        ``self._ocr_drehungen`` (``{seite: grad}``) fuer den Index.
        """
        self._ocr_drehungen = {}
        cfg = ocr_einstellungen_fuer_analyse()
        if cfg is None:
            print("Warnung: Tesseract nicht gefunden. OCR nicht verfügbar.")
            return {}, {}
        if textebene:
            cfg["textebene"] = True
        try:
            from src.search import extract as suche_extract
            res = suche_extract.pdf_ocr(str(self.pdf_path), list(seiten), cfg)
        except Exception as e:  # noqa: BLE001
            print(f"OCR-Fehler: {e}")
            return {}, {}
        if res.get("fehler"):
            print(f"OCR-Fehler: {res['fehler']}")
        texte = {nr: txt for nr, txt in res["texte"].items() if txt and txt.strip()}
        ebenen = {nr: e for nr, e in (res.get("ebenen") or {}).items() if nr in texte and e}
        self._ocr_drehungen = {nr: g for nr, g in (res.get("drehungen") or {}).items() if nr in texte and g}
        return texte, ebenen

    def get_metadata(self) -> dict:
        """
        Extrahiert Metadaten aus dem PDF.

        Returns:
            Dictionary mit Metadaten
        """
        self.open()

        metadata = self._doc.metadata or {}

        return {
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "subject": metadata.get("subject", ""),
            "creator": metadata.get("creator", ""),
            "creation_date": metadata.get("creationDate", ""),
            "modification_date": metadata.get("modDate", ""),
            "page_count": len(self._doc),
            "file_size": self.pdf_path.stat().st_size,
            "filename": self.filename,
        }

    def extract_dates(self) -> list[datetime]:
        """
        Datumsangaben aus dem PDF-Text - Dokumentdatum zuerst (Issue #132).

        ``dates[0]`` ist das wahrscheinlichste Dokumentdatum (Briefkopf,
        "Datum:", "Rechnungsdatum", ", den"), nicht mehr das juengste Datum im
        Text; danach folgen die uebrigen Daten absteigend. Muster und Auswahl
        stehen in :mod:`src.core.document_date`.

        Returns:
            Liste gefundener Datumsangaben
        """
        from src.core.document_date import ordered_dates

        return ordered_dates(self.extract_text())

    def extract_keywords(self) -> list[str]:
        """
        Extrahiert wichtige Schlüsselwörter aus dem Text.

        Returns:
            Liste von Schlüsselwörtern
        """
        text = self.extract_text().lower()

        # Wichtige Kategorien und ihre Schlüsselwörter
        keyword_patterns = {
            "rechnung": ["rechnung", "invoice", "rechnungsnummer", "rechnungsbetrag", "zahlbar"],
            "vertrag": ["vertrag", "vereinbarung", "contract", "laufzeit", "kündigung"],
            "steuer": ["steuer", "finanzamt", "steuernummer", "steuererklärung", "einkommensteuer"],
            "versicherung": ["versicherung", "police", "versicherungsnummer", "beitrag", "prämie"],
            "bank": ["bank", "konto", "kontoauszug", "überweisung", "iban", "bic"],
            "gehalt": ["gehalt", "lohn", "gehaltsabrechnung", "brutto", "netto", "lohnabrechnung"],
            "arzt": ["arzt", "patient", "diagnose", "rezept", "krankenhaus", "praxis"],
            "handwerker": ["handwerker", "reparatur", "montage", "material", "arbeitslohn"],
            "energie": ["strom", "gas", "energie", "verbrauch", "zählerstand", "kwh"],
            "telefon": ["telefon", "mobilfunk", "internet", "tarif", "anschluss"],
        }

        found_keywords = []
        for category, keywords in keyword_patterns.items():
            for keyword in keywords:
                if keyword in text:
                    if category not in found_keywords:
                        found_keywords.append(category)
                    break

        return found_keywords

    def suggest_filename(
        self,
        text: Optional[str] = None,
        keywords: Optional[list[str]] = None,
        dates: Optional[list] = None,
    ) -> str:
        """
        Schlägt einen sinnvollen Dateinamen basierend auf dem Inhalt vor.

        Args:
            text: Bereits extrahierter Text (z.B. aus dem Cache). Wird er
                uebergeben, wird die PDF NICHT erneut geoeffnet und keine
                OCR wiederholt (Issue #108: 7 s Freeze pro Klick).
            keywords: Bereits extrahierte Schluesselwoerter
            dates: Bereits extrahierte Datumsangaben; datetime-Objekte oder
                Strings wie "2026-05-12 00:00:00" (so liegen sie im Cache)

        Returns:
            Vorgeschlagener Dateiname
        """
        if text is None:
            text = self.extract_text()
        if keywords is None:
            keywords = self.extract_keywords()
        if dates is None:
            dates = self.extract_dates()
        dates = coerce_dates(dates)

        parts = []

        # Kategorie/Typ
        if keywords:
            # Erste Kategorie kapitalisieren
            parts.append(keywords[0].capitalize())

        # Nach Firmennamen oder Absender suchen
        company = self._extract_company_name(text)
        if company:
            parts.append(company)

        # Datum hinzufügen
        if dates:
            date_str = dates[0].strftime("%Y-%m")
            parts.append(date_str)

        # Falls nichts gefunden, Original-Datum aus Dateiname verwenden
        if not parts:
            # Versuche Datum aus Dateiname zu extrahieren (YYYY-MM-DD-XXX.pdf)
            match = re.match(r'(\d{4}-\d{2}-\d{2})', self.filename)
            if match:
                parts.append(match.group(1))
            parts.append("Dokument")

        # Zusammenfügen
        suggested = " ".join(parts)

        # Ungültige Zeichen entfernen
        suggested = re.sub(r'[<>:"/\\|?*]', '', suggested)
        suggested = suggested.strip()

        return f"{suggested}.pdf"

    def _extract_company_name(self, text: str) -> Optional[str]:
        """
        Versucht, einen Firmennamen aus dem Text zu extrahieren.

        Args:
            text: Der zu durchsuchende Text

        Returns:
            Gefundener Firmenname oder None
        """
        # Häufige Firmenbezeichnungen
        patterns = [
            r'([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)*)\s+(?:GmbH|AG|KG|OHG|e\.V\.|Ltd\.?)',
            r'(?:Firma|Company|Von|From)[\s:]+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)*)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                company = match.group(1).strip()
                if len(company) > 2 and len(company) < 50:
                    return company

        return None



def coerce_date(value) -> Optional[datetime]:
    """Macht aus einem Cache-Datum wieder ein datetime.

    Der PDF-Cache speichert Datumsangaben als ``str(datetime)``, also
    "2026-05-12 00:00:00"; aeltere Eintraege oder LLM-Antworten liefern
    "2026-05-12". Alles andere ergibt None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "strftime"):  # date
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def coerce_dates(values) -> list[datetime]:
    """Wie :func:`coerce_date`, fuer Listen; unbrauchbare Eintraege fallen weg."""
    if not values:
        return []
    result = []
    for v in values:
        d = coerce_date(v)
        if d is not None:
            result.append(d)
    return result


# Die Tesseract-Suche liegt Qt-frei in src/utils/tesseract.py, damit auch die
# Dokumentensuche (Hintergrunddienst, Arbeitsprozesse) sie ohne PyQt6 laden
# kann. Hier nur re-exportiert, damit bestehende Importe und Tests weiter
# funktionieren (``import shutil`` oben bleibt dafuer ebenfalls erhalten).
from src.search.suchindex import TEXT_AUS_INDEX  # noqa: E402
from src.utils.tesseract import _tesseract_candidates, find_tesseract  # noqa: E402,F401


class PDFThumbnailCache:
    """Cache für PDF-Thumbnails zur Performanceoptimierung."""

    def __init__(self, max_size: int = 100):
        """
        Initialisiert den Cache.

        Args:
            max_size: Maximale Anzahl gecachter Thumbnails
        """
        self.max_size = max_size
        self._cache: dict[str, QPixmap] = {}
        self._access_order: list[str] = []

    def get(self, pdf_path: Path | str) -> Optional[QPixmap]:
        """
        Holt ein Thumbnail aus dem Cache.

        Args:
            pdf_path: Pfad zur PDF-Datei

        Returns:
            Gecachtes QPixmap oder None
        """
        key = str(pdf_path)
        if key in self._cache:
            # Zugriff aktualisieren (LRU)
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None

    def put(self, pdf_path: Path | str, thumbnail: QPixmap) -> None:
        """
        Fügt ein Thumbnail zum Cache hinzu.

        Args:
            pdf_path: Pfad zur PDF-Datei
            thumbnail: Das zu cachende Thumbnail
        """
        key = str(pdf_path)

        # Falls bereits vorhanden, aktualisieren
        if key in self._cache:
            self._access_order.remove(key)
        elif len(self._cache) >= self.max_size:
            # Ältesten Eintrag entfernen (LRU)
            oldest = self._access_order.pop(0)
            del self._cache[oldest]

        self._cache[key] = thumbnail
        self._access_order.append(key)

    def clear(self) -> None:
        """Leert den Cache."""
        self._cache.clear()
        self._access_order.clear()


# Globaler Thumbnail-Cache
_thumbnail_cache = PDFThumbnailCache()


def get_thumbnail(pdf_path: Path | str, width: int = 150, height: int = 200) -> QPixmap:
    """
    Holt ein Thumbnail für eine PDF-Datei (mit Caching).

    Args:
        pdf_path: Pfad zur PDF-Datei
        width: Maximale Breite
        height: Maximale Höhe

    Returns:
        QPixmap mit dem Thumbnail
    """
    pdf_path = Path(pdf_path)

    # 1) RAM-Cache
    cached = _thumbnail_cache.get(pdf_path)
    if cached is not None:
        return cached

    # 2) Disk-Cache (Issue #28): Rendern kostet ~15-20 ms pro PDF, Laden ~1 ms
    disk_file = _thumbnail_disk_path(pdf_path, width, height)
    if disk_file is not None and disk_file.exists():
        pixmap = QPixmap(str(disk_file))
        if not pixmap.isNull():
            _thumbnail_cache.put(pdf_path, pixmap)
            return pixmap

    # 3) Neu generieren
    with PDFAnalyzer(pdf_path) as analyzer:
        thumbnail = analyzer.generate_thumbnail(width=width, height=height)
        _thumbnail_cache.put(pdf_path, thumbnail)
        if disk_file is not None:
            try:
                disk_file.parent.mkdir(parents=True, exist_ok=True)
                thumbnail.save(str(disk_file), "PNG")
            except Exception:
                pass  # Cache ist optional
        return thumbnail


# Masse, in denen die Kacheln ihr Thumbnail laden (ThumbnailLoaderThread)
THUMBNAIL_GROESSEN = ((140, 160),)


def thumbnail_vergessen(pdf_path: Path | str) -> None:
    """Thumbnail einer geaenderten PDF verwerfen (Speicher und PNG, Issue #150).

    Nach dem Drehen hat die Datei eine neue mtime und damit ohnehin einen neuen
    PNG-Schluessel - aber nur auf die Sekunde genau. Wird zweimal in derselben
    Sekunde gedreht (Drehen + Rueckgaengig), passte sonst ein veraltetes Bild.
    """
    pdf_path = Path(pdf_path)
    key = str(pdf_path)
    if key in _thumbnail_cache._cache:
        del _thumbnail_cache._cache[key]
        try:
            _thumbnail_cache._access_order.remove(key)
        except ValueError:
            pass
    for breite, hoehe in THUMBNAIL_GROESSEN:
        datei = _thumbnail_disk_path(pdf_path, breite, hoehe)
        if datei is not None:
            try:
                datei.unlink()
            except OSError:
                pass


def _thumbnail_disk_path(pdf_path: Path, width: int, height: int) -> Optional[Path]:
    """Pfad der gecachten PNG-Datei; Schluessel = Pfad + Groesse + mtime + Masse."""
    try:
        import hashlib
        from src.utils.config import get_config
        st = pdf_path.stat()
        key = f"{pdf_path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{width}x{height}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return get_config().data_dir / "thumbnails" / f"{digest}.png"
    except Exception:
        return None


def analyze_pdf(pdf_path: Path | str) -> dict:
    """
    Führt eine vollständige Analyse einer PDF-Datei durch.

    Args:
        pdf_path: Pfad zur PDF-Datei

    Returns:
        Dictionary mit Analyseergebnissen
    """
    with PDFAnalyzer(pdf_path) as analyzer:
        return {
            "path": str(pdf_path),
            "filename": analyzer.filename,
            "metadata": analyzer.get_metadata(),
            "text": analyzer.extract_text(),
            "dates": [d.isoformat() for d in analyzer.extract_dates()],
            "keywords": analyzer.extract_keywords(),
            "suggested_filename": analyzer.suggest_filename(),
        }
