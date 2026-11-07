"""
Ordnervorschlag aus verknuepften Dokumenten (Issue #166/#167, Phase 3).

Die Sortierlogik vergleicht bisher Dateinamen, Schlagwoerter und
Korrespondenten. Die staerkere Information liegt im Text selbst: Nennt ein
Scan eine Vertrags-, Zaehler- oder Kundennummer, und liegen die Dokumente
mit derselben Nummer schon in einem Zielordner, gehoert der Scan mit hoher
Wahrscheinlichkeit dorthin. :func:`ordner_vorschlag_aus_kennungen` baut
daraus einen :class:`~src.ml.classifier.Suggestion`, den das Hauptfenster
wie den KI-Vorschlag an die Spitze der Liste stellt.

:func:`ordner_vorschlag_aus_chat` macht dasselbe aus einer Chat-Antwort,
deren zitierte Belege in einem Zielordner liegen.

Qt-frei.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional, Sequence

from src.core.similar_documents import relative_folder, resolve_relative_folder, year_adjusted_folder
from src.rag.bezug import KENNUNG_TREFFER_JE, gleicher_pfad, kennungen_aus_text
from src.rag.retrieval import RetrievalService

# Hoechstens so viele verknuepfte Dokumente werden ausgewertet
MAX_TREFFER = 12
# Vertrauen nach Zahl der verknuepften Dokumente im Ordner (1, 2, >= 3)
VERTRAUEN = (0.85, 0.9, 0.95)
# Abschlag, wenn nur unbenannte Zahlen (keine Vertrags-/Zaehlernummer) verbinden
ABSCHLAG_UNBENANNT = 0.15


def _suggestion(path: Path, confidence: float, reason: str, rel: str):
    from src.ml.classifier import Suggestion

    return Suggestion(folder_path=path, folder_name=path.name, confidence=confidence, reason=reason,
                      relative_path=rel)


def _arten(kennungen: Sequence[str]) -> list[str]:
    """``"226541 (Zählernummer)"`` -> ``"Zählernummer"``; Reihenfolge des Auftretens, ohne Doppelte."""
    arten: list[str] = []
    for k in kennungen:
        text = str(k)
        art = text[text.rfind("(") + 1:-1] if text.endswith(")") and "(" in text else "Kennung"
        if art not in arten:
            arten.append(art)
    return arten


def ordner_vorschlag_aus_kennungen(
    text: str,
    db,
    root_folders: Sequence[Path],
    *,
    ausser=None,
    year: Optional[int] = None,
    chat_config=None,
):
    """Zielordner, in dem Dokumente mit denselben Kennungen wie ``text`` liegen.

    Args:
        text: Text des Scans (Textebene oder OCR).
        db: :class:`~src.utils.database.Database` mit Suchindex.
        root_folders: Zielordner; nur Ablageorte darunter zaehlen.
        ausser: Pfad des Scans selbst (wird nicht als Treffer gewertet).
        year: Jahr des Dokuments; ein Jahresordner wird darauf angepasst
            ("Nebenkosten 2024" -> "Nebenkosten 2025", falls vorhanden).
        chat_config: Optionale :class:`ChatConfig` fuer den Retrieval-Service.

    Returns:
        :class:`~src.ml.classifier.Suggestion` oder None (keine Kennungen,
        keine Treffer unter einem Zielordner, Suchindex nicht verfuegbar).
    """
    kennungen = kennungen_aus_text(text or "")
    if not kennungen or db is None:
        return None
    try:
        docs = RetrievalService(db, chat_config).retrieve_kennungen(
            kennungen, k_je=KENNUNG_TREFFER_JE, limit=MAX_TREFFER, ausser=ausser,
        )
    except Exception:  # noqa: BLE001 - Vorschlag ist optional
        return None
    roots = [Path(r) for r in (root_folders or ()) if r]
    if not docs or not roots:
        return None

    anzahl: Counter = Counter()
    benannt: Counter = Counter()
    gemeinsame: dict = defaultdict(list)
    ordner_pfade: dict = {}
    for d in docs:
        pfad = d.file_path or ""
        if not pfad or (ausser and gleicher_pfad(pfad, ausser)):
            continue
        ordner = Path(pfad).parent
        rel = relative_folder(ordner, roots)
        if not rel:
            continue  # ausserhalb der Zielordner (Scan-Eingang, Downloads, Mails)
        schluessel = rel.casefold()
        ordner_pfade.setdefault(schluessel, (ordner, rel))
        anzahl[schluessel] += 1
        kennungen_doc = [str(k) for k in (d.extra or {}).get("gemeinsame_kennungen") or ()]
        gemeinsame[schluessel].extend(kennungen_doc)
        if any(art != "Kennung" and art != "IBAN" for art in _arten(kennungen_doc)):
            benannt[schluessel] += 1
    if not anzahl:
        return None

    bester = max(anzahl, key=lambda s: (benannt[s], anzahl[s]))
    ordner, rel = ordner_pfade[bester]
    n = anzahl[bester]
    confidence = VERTRAUEN[min(n, 3) - 1]
    if benannt[bester] == 0:
        confidence = round(confidence - ABSCHLAG_UNBENANNT, 2)

    # Jahresordner auf das Jahr des Dokuments anpassen (wie beim KI-Vorschlag)
    pfad: Path = ordner
    rel_final = rel
    angepasst = year_adjusted_folder(rel, year, roots) if year else None
    if angepasst and angepasst != rel:
        ziel = resolve_relative_folder(angepasst, roots)
        if ziel is not None:
            pfad, rel_final = ziel, angepasst

    arten = _arten(gemeinsame[bester])
    arten_text = ", ".join(arten) if arten else "Kennung"
    reason = (f"Verknüpft: gleiche {arten_text} in {n} Dokument{'en' if n != 1 else ''} dieses Ordners"
              + (" (Jahr angepasst)" if rel_final != rel else ""))
    return _suggestion(pfad, confidence, reason, rel_final)


def ordner_vorschlag_aus_chat(ordner_pfad, begruendung: str, root_folders: Sequence[Path]):
    """Vorschlag aus einer Chat-Antwort, deren Belege in ``ordner_pfad`` liegen (oder None)."""
    if not ordner_pfad:
        return None
    pfad = Path(str(ordner_pfad))
    roots = [Path(r) for r in (root_folders or ()) if r]
    rel = relative_folder(pfad, roots)
    if not rel or not pfad.is_dir():
        return None
    return _suggestion(pfad, 0.9, f"Chat: {begruendung}" if begruendung else "Chat: belegt durch die Antwort", rel)


def belegter_ordner(citations, docs, root_folders: Sequence[Path], ausser=None) -> tuple[str, str, str]:
    """Ordner, in dem die zitierten Belege einer Antwort liegen.

    Returns:
        ``(absoluter Ordner, Anzeige relativ zum Zielordner, Begruendung)``;
        drei leere Strings, wenn die Zitate keinen gemeinsamen Zielordner haben.
        Zitate ausserhalb der Zielordner (Scan-Eingang, Mails) zaehlen nicht;
        das Bezugsdokument selbst (``ausser``) auch nicht.
    """
    roots = [Path(r) for r in (root_folders or ()) if r]
    if not citations or not roots:
        return "", "", ""
    nach_index = {}
    for d in docs or ():
        idx = d.get("index") if isinstance(d, dict) else getattr(d, "index", None)
        if idx is not None:
            nach_index[int(idx)] = d
    zaehler: Counter = Counter()
    belege: dict = defaultdict(list)
    ordner_pfade: dict = {}
    for c in citations:
        if not getattr(c, "valid", True):
            continue
        pfad = getattr(c, "file_path", "") or ""
        if not pfad or (ausser and gleicher_pfad(pfad, ausser)):
            continue
        ordner = Path(pfad).parent
        rel = relative_folder(ordner, roots)
        if not rel:
            continue
        schluessel = rel.casefold()
        ordner_pfade.setdefault(schluessel, (ordner, rel))
        zaehler[schluessel] += 1
        belege[schluessel].append(int(c.index))
    if not zaehler:
        return "", "", ""
    bester, n = zaehler.most_common(1)[0]
    ordner, rel = ordner_pfade[bester]
    nummern = ", ".join(f"[{i}]" for i in sorted(set(belege[bester])))
    return str(ordner), rel, f"belegt durch {nummern}"
