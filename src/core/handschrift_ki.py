"""
Handschrift mit KI entziffern (Issue #47)

Schwer lesbare Seiten (Handschrift, ungewoehnliche Schrift), die Tesseract
nicht erkennt, rendert die Funktion als Bilder und schickt sie an das
eingestellte KI-Modell, falls es Bilder versteht (``LLMProvider.describe_images``).
Das Ergebnis kann als OCR-Text gespeichert werden (``text_uebernehmen``).

Qt-frei; Oberflaeche und Hintergrund-Thread liegen in
``src/gui/handschrift_dialog.py``.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

# Hoechstens so viele Seiten je Aufruf: jede Seite ist ein Bild und kostet Zeit (lokal) bzw. Geld (Cloud)
MAX_SEITEN = 10
LANGE_KANTE_PX = 1600   # laengste Bildkante; mehr braucht die Schrifterkennung nicht
JPEG_QUALITAET = 80

PROMPT = (
    "Das Bild ist die Seite eines gescannten Dokuments, möglicherweise mit Handschrift. "
    "Schreibe den gesamten Text der Seite genau so ab, wie er dasteht, in der Originalsprache und "
    "in der Reihenfolge von oben nach unten. Gib nur den abgeschriebenen Text aus, ohne Erklärung "
    "und ohne Formatierung. Stellen, die du nicht lesen kannst, schreibst du als [unleserlich]."
)

HILFE_TEXT = (
    "Für „Handschrift mit KI entziffern“ braucht der KI-Assistent ein Modell, das Bilder versteht.\n\n"
    "Möglich sind:\n"
    "• Ollama mit einem Vision-Modell, z. B. qwen2.5vl, llama3.2-vision oder llava\n"
    "• ein Cloud-Anbieter wie Claude, OpenAI oder OpenRouter mit einem Modell, das Bilder versteht\n\n"
    "Stellen Sie das in den Einstellungen auf der Seite „KI-Assistent (LLM)“ ein."
)


def vision_bereit(classifier) -> tuple[Optional[object], str]:
    """Prueft, ob der eingestellte KI-Anbieter Bilder lesen kann: ``(provider, "")`` oder ``(None, Grund)``."""
    provider = getattr(classifier, "llm_provider", None)
    if provider is None or not classifier.is_llm_available():
        return None, "Es ist kein KI-Anbieter eingestellt (oder er ist ausgeschaltet)."
    if not provider.supports_vision():
        getter = getattr(provider, "_get_model_id", None)
        modell = getter() if callable(getter) else getattr(provider.config, "model", "")
        wer = classifier.get_llm_provider_name()
        if modell:
            return None, f"Das Modell „{modell}“ ({wer}) versteht keine Bilder."
        return None, f"{wer} ist als Bildleser nicht möglich."
    return provider, ""


def seiten_als_bilder(pdf_path: Path | str, max_seiten: int = MAX_SEITEN) -> tuple[list[bytes], int]:
    """Die ersten ``max_seiten`` Seiten als JPEG; zusammen mit der Seitenzahl der PDF."""
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    try:
        if doc.needs_pass and not doc.authenticate(""):
            raise RuntimeError("Die PDF ist verschlüsselt.")
        gesamt = doc.page_count
        bilder: list[bytes] = []
        for i in range(min(gesamt, max_seiten)):
            seite = doc[i]
            lang = max(seite.rect.width, seite.rect.height)
            zoom = min(2.5, LANGE_KANTE_PX / lang) if lang else 1.0
            pix = seite.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
            bilder.append(pix.tobytes("jpeg", jpg_quality=JPEG_QUALITAET))
        return bilder, gesamt
    finally:
        doc.close()


def entziffern(
    pdf_path: Path | str,
    provider,
    max_seiten: int = MAX_SEITEN,
    abbrechen: Optional[Callable[[], bool]] = None,
    fortschritt: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """Seiten der PDF als Bilder an das Modell schicken und den entzifferten Text sammeln.

    Eine Anfrage je Seite (kleine Anfragen, Fortschritt, Abbruch zwischen den
    Seiten). Liefert ``{"texte": {seite: text}, "seiten": gelesen, "gesamt":
    Seiten der PDF, "gekuerzt": bool, "fehler": str | None}``. Bei einem Fehler
    bleiben bis dahin gelesene Seiten erhalten.
    """
    erg: dict = {"texte": {}, "seiten": 0, "gesamt": 0, "gekuerzt": False, "fehler": None}
    try:
        bilder, gesamt = seiten_als_bilder(pdf_path, max_seiten)
    except Exception as e:  # noqa: BLE001 - dem Nutzer melden
        erg["fehler"] = f"Die Seiten konnten nicht gerendert werden: {e}"
        return erg
    erg["gesamt"] = gesamt
    erg["gekuerzt"] = gesamt > len(bilder)
    for nr, bild in enumerate(bilder, start=1):
        if abbrechen is not None and abbrechen():
            break
        if fortschritt is not None:
            fortschritt(nr, len(bilder))
        try:
            text = provider.describe_images([bild], PROMPT)
        except Exception as e:  # noqa: BLE001 - Netz, Schluessel, Modell ohne Bilder ...
            erg["fehler"] = str(e) or type(e).__name__
            break
        text = (text or "").strip()
        if text:
            erg["texte"][nr] = text
    erg["seiten"] = len(erg["texte"])
    return erg


def gesamttext(texte: dict[int, str]) -> str:
    """Alle Seitentexte zum Anzeigen; bei mehreren Seiten mit Kopfzeile je Seite."""
    if len(texte) <= 1:
        return "\n".join(texte.values())
    return "\n\n".join(f"--- Seite {nr} ---\n{t}" for nr, t in sorted(texte.items()))


def vorhandener_text(pdf_path: Path | str, seiten) -> bool:
    """Steht im Suchindex fuer eine dieser Seiten schon Text (er wuerde beim Uebernehmen ersetzt)?"""
    from src.core import pdf_analyzer

    index = pdf_analyzer.suchindex_fuer_analyse()
    if index is None:
        return False
    try:
        stand = index.text_fuer_datei(str(pdf_path))
    except Exception:  # noqa: BLE001
        return False
    if not stand:
        return False
    wanted = set(seiten)
    return any(nr in wanted and (txt or "").strip() for nr, _q, txt in stand["seiten"])


def text_uebernehmen(pdf_path: Path | str, texte: dict[int, str]) -> dict:
    """Entzifferten Text wie OCR-Text speichern (Seiten und OCR-Cache im Suchindex ersetzt).

    Die Datei wird, falls noetig, in den Index aufgenommen. Als Lesbarkeit
    gilt der Text als einwandfrei (``alle == gut``): Die Markierung "schlecht
    erkannt" faellt danach weg. Liefert ``{"index": bool, "seiten": int,
    "fehler": str | None}``; ohne eingerichtete Suche gibt es keinen
    Speicherort (``"index": False``).
    """
    from src.core import pdf_analyzer
    from src.search import extract as suche_extract

    erg: dict = {"index": False, "seiten": 0, "fehler": None}
    texte = {nr: t for nr, t in texte.items() if t and t.strip()}
    index = pdf_analyzer.suchindex_fuer_analyse()
    if index is None or not texte:
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
    lesbarkeit = {nr: (n, n) for nr, t in texte.items() for n in [sum(ch.isalnum() for ch in t)]}
    erg["seiten"] = index.ocr_eintragen(pfad, texte, ersetzen=True, lesbarkeit=lesbarkeit, sprachen="ki")
    return erg
