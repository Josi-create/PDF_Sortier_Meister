"""
PDF-Metadaten-Writer für XMP-Standard.

Schreibt Metadaten direkt in PDF-Dateien (dual: XMP in PDF + SQLite-Index).
Kompatibel mit Paperless-ngx, DEVONthink, Adobe Acrobat.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Custom XMP-Namespace für PDF Sortier Meister
CUSTOM_NS = "http://pdfsortiermeister.de/ns/1.0/"
CUSTOM_PREFIX = "psm"


@dataclass
class PDFMetadata:
    """Metadaten-Container für eine PDF-Datei."""
    # Standard XMP-Felder
    title: Optional[str] = None            # dc:title
    subject: Optional[str] = None          # dc:subject (Kategorie)
    description: Optional[str] = None      # dc:description (Zusammenfassung)
    keywords: Optional[str] = None         # pdf:Keywords (kommagetrennt)

    # Custom-Felder (Steuer/Buchhaltung)
    korrespondent: Optional[str] = None    # Firmenname/Absender
    buchungsdatum: Optional[str] = None    # ISO: YYYY-MM-DD
    steuerjahr: Optional[str] = None       # z.B. "2024"
    betrag: Optional[str] = None           # z.B. "142.50"
    waehrung: Optional[str] = None         # EUR/USD
    mwst_satz: Optional[str] = None        # 7 / 19
    steuerlich_absetzbar: Optional[str] = None  # ja / nein / teilweise

    def has_any_data(self) -> bool:
        """Prüft ob mindestens ein Feld gesetzt ist."""
        return any([
            self.title, self.subject, self.description, self.keywords,
            self.korrespondent, self.buchungsdatum, self.steuerjahr,
            self.betrag, self.waehrung, self.mwst_satz,
            self.steuerlich_absetzbar,
        ])

    def to_dict(self) -> dict:
        """Gibt alle gesetzten Felder als Dictionary zurück."""
        result = {}
        for field_name in [
            "title", "subject", "description", "keywords",
            "korrespondent", "buchungsdatum", "steuerjahr",
            "betrag", "waehrung", "mwst_satz", "steuerlich_absetzbar",
        ]:
            value = getattr(self, field_name)
            if value:
                result[field_name] = value
        return result


def write_metadata(pdf_path: Path, metadata: PDFMetadata) -> bool:
    """
    Schreibt XMP-Metadaten in eine PDF-Datei.

    Args:
        pdf_path: Pfad zur PDF-Datei
        metadata: PDFMetadata-Objekt mit den zu schreibenden Feldern

    Returns:
        True bei Erfolg, False bei Fehler
    """
    if not metadata.has_any_data():
        return True  # Nichts zu schreiben

    try:
        import pikepdf

        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            with pdf.open_metadata() as meta:
                # Standard XMP-Felder setzen
                if metadata.title:
                    meta["dc:title"] = metadata.title
                if metadata.subject:
                    meta["dc:subject"] = metadata.subject
                if metadata.description:
                    meta["dc:description"] = metadata.description
                if metadata.keywords:
                    meta["pdf:Keywords"] = metadata.keywords

            # Custom-Felder als XMP Custom Properties schreiben
            # pikepdf unterstützt custom namespaces über die XML-Ebene
            _write_custom_fields(pdf, metadata)

            pdf.save()

        return True

    except ImportError:
        print("pikepdf nicht installiert. Metadaten werden nicht in PDF geschrieben.")
        return False
    except Exception as e:
        print(f"Fehler beim Schreiben der Metadaten in {pdf_path.name}: {e}")
        return False


def read_metadata(pdf_path: Path) -> Optional[PDFMetadata]:
    """
    Liest XMP-Metadaten aus einer PDF-Datei.

    Args:
        pdf_path: Pfad zur PDF-Datei

    Returns:
        PDFMetadata-Objekt oder None bei Fehler
    """
    try:
        import pikepdf

        metadata = PDFMetadata()

        with pikepdf.open(pdf_path) as pdf:
            with pdf.open_metadata() as meta:
                metadata.title = meta.get("dc:title", None)
                metadata.subject = meta.get("dc:subject", None)
                metadata.description = meta.get("dc:description", None)
                metadata.keywords = meta.get("pdf:Keywords", None)

            # Custom-Felder lesen
            _read_custom_fields(pdf, metadata)

        return metadata

    except ImportError:
        return None
    except Exception as e:
        print(f"Fehler beim Lesen der Metadaten aus {pdf_path.name}: {e}")
        return None


def _write_custom_fields(pdf, metadata: PDFMetadata):
    """Schreibt Custom-Felder als PDF Document Info Dictionary."""
    # Für maximale Kompatibilität: Custom-Felder im Info-Dictionary speichern
    # (wird von Adobe Acrobat, Foxit, etc. gelesen)
    info = pdf.docinfo if pdf.docinfo else {}

    custom_fields = {
        "/Korrespondent": metadata.korrespondent,
        "/Buchungsdatum": metadata.buchungsdatum,
        "/Steuerjahr": metadata.steuerjahr,
        "/Betrag": metadata.betrag,
        "/Waehrung": metadata.waehrung,
        "/MwStSatz": metadata.mwst_satz,
        "/SteuerlichAbsetzbar": metadata.steuerlich_absetzbar,
    }

    for key, value in custom_fields.items():
        if value:
            info[key] = value

    pdf.docinfo = info


def _read_custom_fields(pdf, metadata: PDFMetadata):
    """Liest Custom-Felder aus dem PDF Document Info Dictionary."""
    if not pdf.docinfo:
        return

    info = pdf.docinfo
    field_mapping = {
        "/Korrespondent": "korrespondent",
        "/Buchungsdatum": "buchungsdatum",
        "/Steuerjahr": "steuerjahr",
        "/Betrag": "betrag",
        "/Waehrung": "waehrung",
        "/MwStSatz": "mwst_satz",
        "/SteuerlichAbsetzbar": "steuerlich_absetzbar",
    }

    for pdf_key, attr_name in field_mapping.items():
        try:
            value = info.get(pdf_key)
            if value is not None:
                setattr(metadata, attr_name, str(value))
        except Exception:
            pass
