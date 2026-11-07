"""Aehnliche, bereits einsortierte Dokumente als Kontext fuer die KI.

Die KI bekommt beim Beurteilen eines neuen Scans nicht nur den Text, sondern
auch: Welche aehnlichen Dokumente gibt es schon, und WO liegen sie? Quellen
sind die Sortierhistorie (vom Nutzer verschobene PDFs) und der Suchindex
(``document_search``, manuell indexierte Ordner) der PDFSM-Datenbank.

Aehnlich heisst wie bei den Stil-Beispielen (:mod:`src.core.rename_examples`):
Namensbestandteile des alten Dateinamens oder der Korrespondent kommen im
neuen Text vor, oder mehrere Stichwoerter stimmen ueberein.

Wichtig beim Jahr: Eine Rechnung, die fast genauso aussieht wie eine in
"Steuer 2024", gehoert trotzdem nicht dorthin, sondern in den Ordner fuer
das Jahr des NEUEN Dokuments. Deshalb bekommt jeder Ablageort mit Jahreszahl
die passende Jahres-Variante mitgeliefert (sofern der Ordner existiert) und
der Prompt sagt das ausdruecklich.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from src.core.rename_examples import _TOKEN_RE, name_tokens

_YEAR_RE = re.compile(r"(?<!\d)20\d{2}(?!\d)")

NAME_HIT_WEIGHT = 2
KORRESPONDENT_WEIGHT = 2
KEYWORD_HIT_WEIGHT = 1
# Ein einzelner Namensbestandteil (z.B. ein Vorname, der in vielen Briefen
# steht) reicht nicht: es braucht zwei Namenstreffer, Name + Stichwort oder
# Korrespondent + Stichwort.
MIN_SCORE = 3
MAX_TEXT_CHARS = 20000
MAX_ROWS = 20000


@dataclass
class SimilarDocument:
    """Ein bereits einsortiertes Dokument, das dem neuen aehnelt."""
    filename: str
    folder: str  # relativer Ablageort, z.B. "Steuer 2024/Energie" ("" = unbekannt)
    year: Optional[int]  # Jahr des Dokuments (Steuerjahr, Datum, Name, Ordner)
    score: int


# --- Ordnerpfade ---------------------------------------------------------------

def relative_folder(folder: Path | str | None, root_folders: Sequence[Path]) -> str:
    """Ordner relativ zum Zielordner, z.B. "Steuer 2024/Energie"; "" wenn ausserhalb."""
    if not folder:
        return ""
    folder = Path(folder)
    for root in root_folders:
        root = Path(root)
        try:
            rel = folder.relative_to(root)
        except ValueError:
            continue
        return root.name if str(rel) == "." else f"{root.name}/{rel.as_posix()}"
    return ""


def normalize_relative(rel: str | None) -> str:
    """Einheitliche Schreibweise relativer Pfade: "/" statt "\\", ohne Rand."""
    return (rel or "").strip().replace("\\", "/").strip("/")


def resolve_relative_folder(rel: str, root_folders: Sequence[Path]) -> Optional[Path]:
    """Macht aus "Ablage/Steuer 2024/Energie" wieder einen existierenden Ordner (oder None).

    Aeltere Historien-Eintraege nennen den Pfad auch ohne den Namen des
    Zielordners ("Steuer 2024/Energie"); dann wird er unter jedem Zielordner
    gesucht.
    """
    rel = normalize_relative(rel)
    if not rel:
        return None
    first, _, rest = rel.partition("/")
    for root in root_folders:
        root = Path(root)
        if root.name.lower() == first.lower():
            candidate = root / rest if rest else root
            if candidate.is_dir():
                return candidate
    for root in root_folders:
        candidate = Path(root) / rel
        if candidate.is_dir():
            return candidate
    return None


def year_adjusted_folder(rel: str, year: Optional[int], root_folders: Sequence[Path]) -> Optional[str]:
    """Jahres-Variante eines Ablageorts fuer ``year``, falls sie existiert.

    "Steuer 2024/Energie" + 2026 -> "Steuer 2026/Energie". None, wenn der Pfad
    keine andere Jahreszahl enthaelt oder der Ordner nicht existiert.
    """
    if not rel or not year:
        return None
    adjusted = _YEAR_RE.sub(str(year), rel)
    if adjusted == rel:
        return None
    path = resolve_relative_folder(adjusted, root_folders)
    if path is None:
        return None
    return relative_folder(path, root_folders) or adjusted


# --- Jahr ----------------------------------------------------------------------

def _plausible_year(value: int) -> bool:
    from datetime import date
    return 2000 <= value <= date.today().year + 1


def _year_of(*candidates) -> Optional[int]:
    """Erstes plausibles Jahr (20xx, nicht in der Zukunft) aus den Kandidaten."""
    for value in candidates:
        if not value:
            continue
        for m in _YEAR_RE.finditer(str(value)):
            year = int(m.group())
            if _plausible_year(year):
                return year
    return None


def document_year(detected_date: Optional[str], file_date: Optional[str] = None) -> Optional[int]:
    """Jahr des neuen Dokuments: erkanntes Datum, sonst Dateidatum (Scandatum)."""
    return _year_of(detected_date, file_date)


# --- Aehnlichkeit --------------------------------------------------------------

def _keyword_set(keywords) -> set[str]:
    if not keywords:
        return set()
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    return {k.strip().lower() for k in keywords if k and k.strip()}


def _tokens(value: str | None) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(value or "")}


class _Scorer:
    """Bewertet Kandidaten gegen den Text des neuen Dokuments (Text nur einmal zerlegt)."""

    def __init__(self, text: str, keywords):
        self.text_words = _tokens((text or "")[:MAX_TEXT_CHARS])
        self.keywords = _keyword_set(keywords)

    def score(self, filename: str, keywords, korrespondent: str | None) -> int:
        """Punkte; 0, wenn weder Name noch Korrespondent im Text vorkommen.

        Gemeinsame Stichwoerter allein ("rechnung", "datum") reichen nicht:
        sie wuerden fast jedes Dokument zum Zwilling machen.
        """
        if not self.text_words and not self.keywords:
            return 0
        name_hits = len(name_tokens(filename) & self.text_words)
        korr_tokens = _tokens(korrespondent)
        korr_hits = 1 if (korr_tokens and korr_tokens <= self.text_words) else 0
        if not name_hits and not korr_hits:
            return 0
        keyword_hits = len(_keyword_set(keywords) & self.keywords)
        return (NAME_HIT_WEIGHT * name_hits + KORRESPONDENT_WEIGHT * korr_hits
                + KEYWORD_HIT_WEIGHT * keyword_hits)


def _history_candidates(db, root_folders: Sequence[Path]) -> Iterable[dict]:
    """Sortierhistorie: neueste zuerst, ohne den Volltext.

    Der Ablageort kommt bevorzugt aus dem absoluten Zielordner (einheitliche
    Schreibweise); der gespeicherte relative Pfad ist nur Rueckfall, aeltere
    Eintraege haben ihn in gemischter Form.
    """
    for row in db.get_history_brief(limit=MAX_ROWS):
        filename = row.get("new_filename") or row.get("original_filename") or ""
        folder = (relative_folder(row.get("target_folder"), root_folders)
                  or normalize_relative(row.get("target_relative_path")))
        yield {
            "filename": filename,
            "folder": folder,
            "keywords": row.get("keywords"),
            "korrespondent": row.get("korrespondent"),
            "year": _year_of(row.get("steuerjahr"), row.get("detected_date"), filename, folder),
        }


def _index_candidates(db, root_folders: Sequence[Path]) -> Iterable[dict]:
    """Suchindex (document_search): Dokumente, die bereits in Zielordnern liegen."""
    for row in db.get_indexed_documents_brief(limit=MAX_ROWS):
        file_path = row.get("file_path") or ""
        folder = relative_folder(Path(file_path).parent if file_path else None, root_folders)
        if not folder:
            folder = relative_folder(row.get("target_folder"), root_folders)
        filename = row.get("filename") or (Path(file_path).name if file_path else "")
        yield {
            "filename": filename,
            "folder": folder,
            "keywords": row.get("keywords"),
            "korrespondent": row.get("korrespondent"),
            "year": _year_of(row.get("steuerjahr"), filename, folder),
        }


def find_similar_documents(
    text: str,
    keywords,
    root_folders: Sequence[Path],
    db=None,
    limit: int = 5,
) -> list[SimilarDocument]:
    """Die aehnlichsten bereits einsortierten Dokumente, beste zuerst.

    Nur Dokumente mit bekanntem Ablageort unterhalb eines Zielordners; jeder
    Dateiname erscheint einmal. Fehler der Datenbank liefern eine leere Liste.
    """
    if db is None:
        from src.utils.database import get_database
        db = get_database()
    scorer = _Scorer(text, keywords)
    scored: list[tuple[int, int, dict]] = []
    idx = 0
    for source in (_history_candidates, _index_candidates):
        try:
            candidates = list(source(db, root_folders))
        except Exception:  # noqa: BLE001 - Kontext ist optional
            continue
        for cand in candidates:
            if not cand["filename"] or not cand["folder"]:
                continue
            score = scorer.score(cand["filename"], cand["keywords"], cand["korrespondent"])
            if score >= MIN_SCORE:
                scored.append((score, idx, cand))
            idx += 1
    scored.sort(key=lambda t: (-t[0], t[1]))

    seen: set[str] = set()
    result: list[SimilarDocument] = []
    for score, _idx, cand in scored:
        key = cand["filename"].lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(SimilarDocument(cand["filename"], cand["folder"], cand["year"], score))
        if len(result) >= limit:
            break
    return result


# --- Prompt --------------------------------------------------------------------

def describe_similar_for_prompt(
    similar: Sequence[SimilarDocument],
    year: Optional[int],
    root_folders: Sequence[Path],
) -> str:
    """Prompt-Abschnitt mit Ablageorten aehnlicher Dokumente; leer ohne Treffer."""
    docs = [d for d in similar if d.filename and d.folder]
    if not docs:
        return ""
    lines = ["", "ÄHNLICHE DOKUMENTE, DIE BEREITS EINSORTIERT SIND (Ablageort relativ zum Zielordner):"]
    for d in docs:
        line = f'- "{d.filename}"'
        if d.year:
            line += f" (Dokument von {d.year})"
        line += f' liegt in "{d.folder}"'
        adjusted = year_adjusted_folder(d.folder, year, root_folders)
        if adjusted:
            line += f'; für ein Dokument von {year} entspricht das "{adjusted}"'
        lines.append(line)
    year_hint = f" Dieses Dokument stammt laut Texterkennung aus {year} (am Text prüfen)." if year else ""
    lines.append(
        "Diese Ablageorte zeigen die Ordnerstruktur des Nutzers. Ordner mit Jahreszahl gelten "
        "nur für Dokumente dieses Jahres: Ein fast gleiches Dokument aus einem anderen Jahr "
        "gehört in den Ordner für SEIN Jahr, nicht in den des Beispiels." + year_hint +
        ' Nenne unter "zielordner" den passenden Ablageort in genau dieser Schreibweise '
        "(Jahr an dieses Dokument angepasst) oder UNBEKANNT."
    )
    return "\n".join(lines)


def folder_suggestion_from_metadata(
    metadata: Optional[dict],
    root_folders: Sequence[Path],
    year: Optional[int],
):
    """Ordnervorschlag aus dem "zielordner" der KI-Antwort (oder None).

    Existiert der genannte Ordner nicht, wird seine Jahres-Variante fuer
    ``year`` versucht. Liefert :class:`src.ml.classifier.Suggestion`.
    """
    if not isinstance(metadata, dict):
        return None
    rel = str(metadata.get("zielordner") or "").strip()
    if not rel:
        return None
    from src.ml.classifier import Suggestion

    adjusted = year_adjusted_folder(rel, year, root_folders)
    if adjusted:
        rel = adjusted  # KI hat das Jahr des Beispiels uebernommen -> korrigieren
    path = resolve_relative_folder(rel, root_folders)
    if path is None:
        return None
    return Suggestion(
        folder_path=path,
        folder_name=path.name,
        confidence=0.85,
        reason="KI: ähnliche Dokumente liegen dort",
        relative_path=relative_folder(path, root_folders) or rel,
    )


def merge_folder_suggestion(suggestions: list, ki_suggestion, bestaetigung: str = "KI bestätigt") -> list:
    """Setzt den Vorschlag an die Spitze; kennt die Liste den Ordner schon, wird er bestaetigt.

    ``bestaetigung`` ist der Zusatz zur Begruendung ("KI bestätigt", oder
    Phase 3: "verknüpfte Dokumente", "Chat bestätigt"); sein erstes Wort
    verhindert eine doppelte Bestaetigung. Das Vertrauen steigt auf
    mindestens das des Vorschlags (und 0.9).
    """
    if ki_suggestion is None:
        return list(suggestions)
    merged = list(suggestions)
    marker = bestaetigung.split()[0] if bestaetigung else ""
    for i, s in enumerate(merged):
        if Path(s.folder_path) == Path(ki_suggestion.folder_path):
            s.confidence = max(s.confidence, 0.9, float(getattr(ki_suggestion, "confidence", 0) or 0))
            if marker and marker not in s.reason:
                s.reason = f"{s.reason} + {bestaetigung}"
            merged.insert(0, merged.pop(i))
            return merged
    merged.insert(0, ki_suggestion)
    return merged
