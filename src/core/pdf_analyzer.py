"""
PDF-Analyzer für PDF Sortier Meister

Funktionen:
- Thumbnail-Generierung aus PDFs
- Textextraktion (direkt und via OCR)
- Metadaten-Extraktion
"""

import re
from pathlib import Path
from typing import Optional
from datetime import datetime

import fitz  # PyMuPDF
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice


class PDFAnalyzer:
    """Analysiert PDF-Dateien und extrahiert Informationen."""

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

        Args:
            use_ocr: Falls True, wird OCR verwendet wenn kein Text gefunden wird

        Returns:
            Der extrahierte Text
        """
        if self._text is not None:
            return self._text

        self.open()

        # Zuerst versuchen, eingebetteten Text zu extrahieren
        text_parts = []
        for page in self._doc:
            page_text = page.get_text()
            if page_text.strip():
                text_parts.append(page_text)

        self._text = "\n".join(text_parts)

        # Falls kein Text gefunden und OCR aktiviert
        if not self._text.strip() and use_ocr:
            self._text = self._extract_text_ocr()

        return self._text

    def _extract_text_ocr(self) -> str:
        """
        Extrahiert Text mittels OCR (Tesseract).

        Returns:
            Der per OCR extrahierte Text
        """
        try:
            import pytesseract
            from PIL import Image
            import io

            self.open()
            text_parts = []

            for page_num in range(min(len(self._doc), 5)):  # Max 5 Seiten für OCR
                page = self._doc[page_num]

                # Höhere Auflösung für OCR
                matrix = fitz.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=matrix, alpha=False)

                # In PIL Image konvertieren
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))

                # OCR durchführen (Deutsch)
                page_text = pytesseract.image_to_string(img, lang='deu')
                if page_text.strip():
                    text_parts.append(page_text)

            return "\n".join(text_parts)

        except ImportError:
            print("Warnung: pytesseract nicht installiert. OCR nicht verfügbar.")
            return ""
        except Exception as e:
            print(f"OCR-Fehler: {e}")
            return ""

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
        Versucht, Datumsangaben aus dem PDF-Text zu extrahieren.

        Returns:
            Liste gefundener Datumsangaben
        """
        text = self.extract_text()
        dates = []

        # Deutsche Datumsformate
        patterns = [
            # DD.MM.YYYY oder DD.MM.YY
            r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})',
            # DD/MM/YYYY
            r'(\d{1,2})/(\d{1,2})/(\d{2,4})',
            # YYYY-MM-DD (ISO)
            r'(\d{4})-(\d{1,2})-(\d{1,2})',
            # Monat ausgeschrieben: 15. Januar 2025
            r'(\d{1,2})\.\s*(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s*(\d{4})',
        ]

        month_names = {
            'Januar': 1, 'Februar': 2, 'März': 3, 'April': 4,
            'Mai': 5, 'Juni': 6, 'Juli': 7, 'August': 8,
            'September': 9, 'Oktober': 10, 'November': 11, 'Dezember': 12
        }

        for pattern in patterns[:3]:  # Numerische Patterns
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    if pattern.startswith(r'(\d{4})'):  # ISO Format
                        year, month, day = int(match[0]), int(match[1]), int(match[2])
                    else:
                        day, month, year = int(match[0]), int(match[1]), int(match[2])

                    if year < 100:
                        year += 2000 if year < 50 else 1900

                    if 1 <= day <= 31 and 1 <= month <= 12 and 1990 <= year <= 2100:
                        dates.append(datetime(year, month, day))
                except (ValueError, IndexError):
                    continue

        # Ausgeschriebene Monate
        matches = re.findall(patterns[3], text, re.IGNORECASE)
        for match in matches:
            try:
                day = int(match[0])
                month = month_names.get(match[1].capitalize(), 0)
                year = int(match[2])
                if month > 0 and 1 <= day <= 31:
                    dates.append(datetime(year, month, day))
            except (ValueError, IndexError):
                continue

        # Duplikate entfernen und sortieren
        unique_dates = list(set(dates))
        unique_dates.sort(reverse=True)

        return unique_dates

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

    def suggest_filename(self) -> str:
        """
        Schlägt einen sinnvollen Dateinamen basierend auf dem Inhalt vor.

        Returns:
            Vorgeschlagener Dateiname
        """
        text = self.extract_text()
        keywords = self.extract_keywords()
        dates = self.extract_dates()

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

    # Aus Cache holen
    cached = _thumbnail_cache.get(pdf_path)
    if cached is not None:
        return cached

    # Neu generieren
    with PDFAnalyzer(pdf_path) as analyzer:
        thumbnail = analyzer.generate_thumbnail(width=width, height=height)
        _thumbnail_cache.put(pdf_path, thumbnail)
        return thumbnail


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
