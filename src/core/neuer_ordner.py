"""Vorschlaege fuer NEUE Ordner (Issue #116).

Zwei Quellen, hoechstens ein Vorschlag pro Dokument:

A) Jahresregel ohne KI: Der beste Vorschlag liegt in einem Ordner mit
   Jahreszahl ("Steuer 2025/Medikamente"), das Dokument stammt aber aus einem
   anderen Jahr und den Ordner dafuer gibt es noch nicht -> "Steuer 2028/
   Medikamente" als neuer Ordner mit derselben Unterstruktur.
B) Die KI nennt unter "zielordner" einen Pfad, den es noch nicht gibt. Er wird
   nur genommen, wenn er sicher unter einem Zielordner liegt (keine absoluten
   Pfade, kein "..", keine unter Windows verbotenen Namen).

Ausserdem: die Ordnerliste fuer den KI-Prompt (relative Pfade, begrenzt) und
das Anlegen bzw. Wegraeumen der neuen Ordner (fuer Rueckgaengig).
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Optional, Sequence

from src.core.similar_documents import (
    _YEAR_RE, normalize_relative, relative_folder, resolve_relative_folder, vorschlag_jahr,
)
from src.i18n import tr

QUELLE_JAHR = "jahr"
QUELLE_KI = "ki"

CONFIG_KEY = "suggest_new_folders"

# Ordnerliste im Prompt: lokale Modelle haben oft nur 4096 Tokens Kontext,
# der Dokumenttext ist standardmaessig 1500 Zeichen lang.
PROMPT_MAX_ORDNER = 120
PROMPT_MAX_ZEICHEN = 3000
PROMPT_MAX_TIEFE = 4
_LISTE_TTL_S = 120.0

# Kopfzeile der Ordnerliste; der Prompt-Baustein erkennt daran, dass die KI
# auch neue Pfade nennen darf.
ORDNERLISTE_KOPF = "VORHANDENE ORDNER DES NUTZERS"

_MAX_SEGMENTE = 8
_MAX_SEGMENT_LAENGE = 80
_VERBOTEN_RE = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVIERT = {"con", "prn", "aux", "nul",
               *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def ist_neu(suggestion) -> bool:
    """True, wenn der Vorschlag einen Ordner meint, den es noch nicht gibt."""
    return bool(getattr(suggestion, "new_source", ""))


def aktiv(config) -> bool:
    """Schalter "Neue Ordner vorschlagen" (Standard: ein)."""
    try:
        return bool(config.get(CONFIG_KEY, True))
    except Exception:  # noqa: BLE001
        return True


# --- Pfadpruefung (B) ------------------------------------------------------------

def _segment_bereinigen(segment: str) -> Optional[str]:
    """Ein Pfadteil ohne verbotene Zeichen; None, wenn er nicht taugt."""
    seg = _VERBOTEN_RE.sub("", segment)
    seg = re.sub(r"\s+", " ", seg).strip().rstrip(". ")
    if not seg or seg in (".", "..") or len(seg) > _MAX_SEGMENT_LAENGE:
        return None
    if seg.split(".")[0].strip().lower() in _RESERVIERT:
        return None
    return seg


def neuer_pfad_unter_zielordner(rel: str, root_folders: Sequence[Path]) -> Optional[Path]:
    """Macht aus einem relativen KI-Pfad einen sicheren NEUEN Ordnerpfad (oder None).

    Erster Teil = Name eines Zielordners ("Ablage/Steuer 2027/Medikamente").
    Ohne diesen Teil geht es nur bei genau einem Zielordner. Abgelehnt werden
    absolute Pfade, "." und "..", Windows-reservierte Namen, zu tiefe Pfade,
    der Zielordner selbst und Pfade, die (teilweise) auf Dateien treffen.
    Verbotene Zeichen (<>:"|?* usw.) werden entfernt.
    """
    raw = (rel or "").strip()
    if not raw or not root_folders:
        return None
    unified = raw.replace("\\", "/")
    if unified.startswith("/") or re.match(r"^[A-Za-z]:", unified) or "://" in unified:
        return None
    rohteile = [t for t in unified.split("/") if t.strip()]
    if any(t.strip() in (".", "..") for t in rohteile):
        return None
    teile = []
    for t in rohteile:
        seg = _segment_bereinigen(t)
        if seg is None:
            return None
        teile.append(seg)
    if not teile or len(teile) > _MAX_SEGMENTE:
        return None

    roots = [Path(r) for r in root_folders]
    root = next((r for r in roots if r.name.lower() == teile[0].lower()), None)
    if root is not None:
        teile = teile[1:]
    elif len(roots) == 1:
        root = roots[0]
    else:
        return None
    if not teile:
        return None  # nur der Zielordner selbst

    candidate = root.joinpath(*teile)
    try:
        candidate.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    # Kein Teil des Pfads darf eine Datei sein
    p = candidate
    while p != root:
        if p.exists() and not p.is_dir():
            return None
        p = p.parent
    return candidate


def ki_neuer_ordner(metadata: Optional[dict], root_folders: Sequence[Path]):
    """Neuer-Ordner-Vorschlag aus dem "zielordner" der KI (oder None).

    Nur, wenn der Pfad noch NICHT existiert - einen bestehenden Ordner
    liefert :func:`src.core.similar_documents.folder_suggestion_from_metadata`.
    """
    if not isinstance(metadata, dict):
        return None
    rel = str(metadata.get("zielordner") or "").strip()
    if not rel or resolve_relative_folder(rel, root_folders) is not None:
        return None
    path = neuer_pfad_unter_zielordner(rel, root_folders)
    if path is None or path.exists():
        return None
    from src.ml.classifier import Suggestion
    return Suggestion(
        folder_path=path,
        folder_name=path.name,
        confidence=0.8,
        reason=tr("KI: neuer Ordner nach dem Muster der vorhandenen"),
        relative_path=relative_folder(path, root_folders) or normalize_relative(rel),
        new_source=QUELLE_KI,
    )


# --- Jahresregel (A) -------------------------------------------------------------

def jahres_neuer_ordner(suggestions: Sequence, year: Optional[int], root_folders: Sequence[Path]):
    """Neuer Jahresordner nach dem Muster des besten Vorschlags mit Jahreszahl (oder None).

    Gibt es den Ordner fuer ``year`` schon, kommt nichts (dann bietet die
    bestehende Jahres-Variante aus Issue #30 ihn an).
    """
    if not year:
        return None
    from src.ml.classifier import PDFClassifier, Suggestion
    for s in suggestions:
        if ist_neu(s):
            continue
        folder = Path(s.folder_path)
        rel = getattr(s, "relative_path", "") or relative_folder(folder, root_folders)
        if not _YEAR_RE.search(rel or folder.name):
            continue
        variant = PDFClassifier._year_variant(folder, rel, year, must_exist=False)
        if variant is None:
            return None  # gleiches Jahr: der Ordner passt schon
        path, variant_rel = variant
        if path.exists():
            return None
        if not any(path == Path(r) or Path(r) in path.parents for r in root_folders):
            return None
        return Suggestion(
            folder_path=path,
            folder_name=path.name,
            confidence=float(s.confidence),
            reason=tr("Neuer Ordner: Dokument von {year}, Muster von \"{rel}\"").format(year=year, rel=rel),
            relative_path=relative_folder(path, root_folders) or variant_rel,
            new_source=QUELLE_JAHR,
        )
    return None


def dokument_jahr(detected_date: Optional[str], metadata: Optional[dict] = None, text: str = "") -> Optional[int]:
    """Jahr fuer die Jahresregel: Bezugsjahr im Text (#254), Steuerjahr der KI, sonst Dokumentdatum."""
    steuerjahr = (metadata or {}).get("steuerjahr") if isinstance(metadata, dict) else None
    return vorschlag_jahr(text, detected_date, steuerjahr)


def hoechstens_einer_vorne(suggestions: Sequence) -> list:
    """Hoechstens ein neuer Ordner, und zwar vorne; Jahresregel vor KI."""
    neue = [s for s in suggestions if ist_neu(s)]
    rest = [s for s in suggestions if not ist_neu(s)]
    if not neue:
        return rest
    neue.sort(key=lambda s: 0 if s.new_source == QUELLE_JAHR else 1)
    return [neue[0], *rest]


# --- Ordnerliste fuer den Prompt (B) ---------------------------------------------

_liste_cache: dict[tuple, tuple[float, list[str]]] = {}
_liste_lock = threading.Lock()


def invalidieren() -> None:
    """Vergisst die gemerkte Ordnerliste (nach Anlegen/Wegraeumen von Ordnern)."""
    with _liste_lock:
        _liste_cache.clear()


def ordner_relativ(root_folders: Sequence[Path], max_ordner: int = PROMPT_MAX_ORDNER,
                   max_tiefe: int = PROMPT_MAX_TIEFE) -> list[str]:
    """Relative Ordnerpfade unter den Zielordnern, ebenenweise (flache zuerst), begrenzt."""
    roots = [Path(r) for r in root_folders]
    key = (tuple(str(r) for r in roots), max_ordner, max_tiefe)
    with _liste_lock:
        hit = _liste_cache.get(key)
        if hit and time.monotonic() - hit[0] < _LISTE_TTL_S:
            return list(hit[1])
    result: list[str] = []
    ebene = [(r, r.name, 0) for r in roots if r.is_dir()]
    result.extend(name for _, name, _ in ebene)
    while ebene and len(result) < max_ordner:
        naechste = []
        for folder, rel, tiefe in ebene:
            if tiefe >= max_tiefe:
                continue
            try:
                with os.scandir(folder) as it:
                    namen = sorted(e.name for e in it
                                   if e.is_dir() and not e.name.startswith((".", "$")))
            except OSError:
                continue
            for name in namen:
                naechste.append((Path(folder) / name, f"{rel}/{name}", tiefe + 1))
        for _, rel, _ in naechste:
            if len(result) >= max_ordner:
                break
            result.append(rel)
        ebene = naechste
    with _liste_lock:
        _liste_cache[key] = (time.monotonic(), list(result))
    return result


def ordnerliste_fuer_prompt(root_folders: Sequence[Path], max_zeichen: int = PROMPT_MAX_ZEICHEN) -> str:
    """Prompt-Abschnitt mit den vorhandenen Ordnern; erlaubt einen neuen Pfad. Leer ohne Ordner."""
    if not root_folders:
        return ""
    pfade = sorted(ordner_relativ(root_folders), key=str.lower)
    if not pfade:
        return ""
    zeilen, laenge, gekuerzt = [], 0, False
    for p in pfade:
        zeile = f"- {p}"
        if laenge + len(zeile) + 1 > max_zeichen:
            gekuerzt = True
            break
        zeilen.append(zeile)
        laenge += len(zeile) + 1
    if len(pfade) >= PROMPT_MAX_ORDNER:
        gekuerzt = True
    if gekuerzt:
        zeilen.append("- ... (Liste gekürzt, tiefere Ordner fehlen)")
    return "\n".join([
        "",
        f"{ORDNERLISTE_KOPF} (relativ, der erste Teil ist der Zielordner):",
        *zeilen,
        'Nenne unter "zielordner" möglichst einen dieser Ordner in genau dieser Schreibweise. '
        "Passt keiner, darfst du einen NEUEN Ordner vorschlagen: Der Pfad beginnt mit einem "
        "Zielordner aus der Liste und folgt dem Aufbau der vorhandenen Ordner (z.B. "
        '"Steuer 2025/Medikamente" wird für ein Dokument von 2027 zu "Steuer 2027/Medikamente"). '
        "Kurze Ordnernamen, kein Dateiname, kein Laufwerk, kein \"..\". Passt gar nichts: UNBEKANNT.",
    ])


# --- Anlegen und Wegraeumen ------------------------------------------------------

def anlegen(path: Path) -> list[Path]:
    """Legt den Ordner samt fehlender Eltern an; liefert die NEU angelegten (aussen zuerst)."""
    path = Path(path)
    fehlend = []
    p = path
    while not p.exists():
        fehlend.append(p)
        if p.parent == p:
            break
        p = p.parent
    path.mkdir(parents=True, exist_ok=True)
    return list(reversed(fehlend))


def leere_wegraeumen(angelegt: Sequence[Path]) -> int:
    """Loescht die angelegten Ordner wieder, innen zuerst, aber nur wenn sie leer sind."""
    entfernt = 0
    for p in sorted((Path(x) for x in angelegt), key=lambda x: len(x.parts), reverse=True):
        try:
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()
                entfernt += 1
        except OSError:
            continue
    return entfernt
