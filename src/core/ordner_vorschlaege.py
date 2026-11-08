"""Zielvorschlaege fuer einen ganzen Ordner (Issue #196). Qt-frei.

Gesucht ist der ELTERNORDNER, unter den der markierte Ordner gehoert
("Versicherungen" -> "Steuer 2025"). Zwei Quellen laufen automatisch, die dritte
(KI) nur auf Knopfdruck (:func:`ki_zielordner`):

a) Inhalt: Fuer die Dateien im Ordner (rekursiv, bis ``MAX_DATEIEN``) zaehlt
   jede Quelle eine Stimme fuer einen Zielordner: die gelernte Zuordnung aus der
   Sortierhistorie (gleicher Dateiname wurde schon einmal dorthin sortiert), die
   Vorhersage des Klassifikators aus dem gecachten Text und der "zielordner"
   der gecachten KI-Vorschlaege. Die Mehrheit gewinnt; aus dem Zielordner wird der
   Elternordner abgeleitet (traegt er oder ein Oberordner den Namen des
   Ordners, ist es dessen Eltern, sonst der Zielordner selbst).
b) Namensvetter: Gleichnamige Ordner im Zielbaum ("Steuer 2024/Versicherungen")
   schlagen deren Elternordner vor, mit Jahresanpassung auf das Jahr des
   Ordners ("Steuer 2025", falls vorhanden, sonst als neuer Ordner).

Nie vorgeschlagen werden der aktuelle Elternordner, der Ordner selbst und seine
Unterordner. Das Ergebnis ist nach Konfidenz sortiert.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence

from src.core.similar_documents import (
    _YEAR_RE, _year_of, normalize_relative, relative_folder, resolve_relative_folder,
    year_adjusted_folder,
)

MAX_DATEIEN = 300  # so viele Dateien werden betrachtet
MAX_KLASSIFIKATOR = 25  # so viele davon fragen den Klassifikator (Text aus dem Cache)
MIN_STIMME = 0.31  # darunter ist es nur der "haeufig verwendet"-Rueckfall des Klassifikators
MAX_TIEFE_BAUM = 6
MAX_ORDNER_BAUM = 20000


def _norm(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(str(p))).rstrip("\\/")


def liegt_in(pfad: Path | str, ordner: Path | str) -> bool:
    """True, wenn ``pfad`` der Ordner selbst ist oder darunter liegt."""
    p, o = _norm(pfad), _norm(ordner)
    return p == o or p.startswith(o + os.sep)


def dateien_unter(ordner: Path, limit: int = MAX_DATEIEN) -> list[Path]:
    """Dateien unter ``ordner`` rekursiv (ohne versteckte), hoechstens ``limit``."""
    gefunden: list[Path] = []
    for wurzel, dirs, files in os.walk(ordner):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith("."):
                continue
            gefunden.append(Path(wurzel) / name)
            if len(gefunden) >= limit:
                return gefunden
    return gefunden


# --- Zieljahr ------------------------------------------------------------------

def ziel_jahr(ordner: Path, dateien: Sequence[Path], cache_get: Optional[Callable] = None) -> Optional[int]:
    """Jahr des Ordners: aus seinem Pfad, sonst Dokumentdaten aus dem Cache, sonst Dateidatum."""
    for teil in reversed(Path(ordner).parts[1:]):
        jahr = _year_of(teil)
        if jahr:
            return jahr
    jahre: Counter = Counter()
    if cache_get is not None:
        for f in dateien[:MAX_KLASSIFIKATOR * 4]:
            ergebnis = cache_get(f)
            for d in (getattr(ergebnis, "dates", None) or [])[:1]:
                jahr = _year_of(str(d))
                if jahr:
                    jahre[jahr] += 1
    if not jahre:
        for f in dateien[:MAX_KLASSIFIKATOR * 4]:
            try:
                jahr = _year_of(datetime.fromtimestamp(f.stat().st_mtime).year)
            except OSError:
                continue
            if jahr:
                jahre[jahr] += 1
    return jahre.most_common(1)[0][0] if jahre else None


# --- a) Inhalt -------------------------------------------------------------------

def eltern_fuer(zielordner: Path, ordner: Path) -> Path:
    """Elternordner, unter den ``ordner`` passt, wenn seine Dateien nach ``zielordner`` gehoeren."""
    name = ordner.name.lower()
    p = Path(zielordner)
    while p != p.parent:
        if p.name.lower() == name:
            return p.parent
        p = p.parent
    return Path(zielordner)


def _historie_nach_name(db) -> dict[str, list[str]]:
    """Dateiname (klein) -> Zielordner aus der Sortierhistorie."""
    if db is None:
        return {}
    karte: dict[str, list[str]] = {}
    try:
        zeilen = db.get_history_brief(limit=20000)
    except Exception:  # noqa: BLE001 - ohne Historie gibt es nur weniger Stimmen
        return {}
    for z in zeilen:
        ziel = z.get("target_folder")
        if not ziel:
            continue
        for key in ("new_filename", "original_filename"):
            name = (z.get(key) or "").strip().lower()
            if name:
                karte.setdefault(name, []).append(ziel)
    return karte


def _ki_ziele(ergebnis, root_folders) -> list[Path]:
    """Zielordner aus den gecachten KI-Vorschlaegen ("zielordner" in den Metadaten)."""
    ziele = []
    for s in getattr(ergebnis, "llm_suggestions", None) or []:
        meta = getattr(s, "metadata", None)
        rel = str(meta.get("zielordner") or "").strip() if isinstance(meta, dict) else ""
        pfad = resolve_relative_folder(rel, root_folders) if rel else None
        if pfad is not None:
            ziele.append(pfad)
    return ziele


def stimmen_aus_inhalt(
    ordner: Path,
    dateien: Sequence[Path],
    root_folders: Sequence[Path],
    db=None,
    cache_get: Optional[Callable] = None,
    suggest_fn: Optional[Callable] = None,
) -> Counter:
    """Gewichtete Stimmen fuer Zielordner (Path -> Gewicht) aus den Dateien im Ordner."""
    stimmen: Counter = Counter()
    historie = _historie_nach_name(db)
    gefragt = 0
    for f in dateien:
        # 1. Gelernte Zuordnung: dieselbe Datei wurde schon einmal einsortiert
        for ziel in set(historie.get(f.name.lower(), ())):
            if Path(ziel).is_dir() and not liegt_in(ziel, ordner):
                stimmen[Path(ziel)] += 1.0
        ergebnis = cache_get(f) if cache_get is not None else None
        if ergebnis is None:
            continue
        # 2. Vorhersage des Klassifikators aus dem gecachten Text
        text = getattr(ergebnis, "extracted_text", "") or ""
        if suggest_fn is not None and text and gefragt < MAX_KLASSIFIKATOR:
            gefragt += 1
            try:
                vorschlaege = suggest_fn(text, list(getattr(ergebnis, "keywords", None) or []))
            except Exception:  # noqa: BLE001
                vorschlaege = []
            if vorschlaege:
                top = vorschlaege[0]
                if top.confidence > MIN_STIMME and not liegt_in(top.folder_path, ordner):
                    stimmen[Path(top.folder_path)] += float(top.confidence)
        # 3. Gecachte KI-Vorschlaege
        for ziel in set(_ki_ziele(ergebnis, root_folders)):
            if not liegt_in(ziel, ordner):
                stimmen[ziel] += 1.0
    return stimmen


# --- b) Namensvetter ---------------------------------------------------------------

def _gleichnamige(ordner: Path, root_folders: Sequence[Path]) -> list[Path]:
    """Ordner im Zielbaum mit dem Namen von ``ordner`` (ohne ihn selbst und seine Unterordner)."""
    name = ordner.name.lower()
    treffer: list[Path] = []
    gesehen = 0
    for root in root_folders:
        root = Path(root)
        if not root.is_dir():
            continue
        basis = len(root.parts)
        for wurzel, dirs, _files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith((".", "$"))]
            if len(Path(wurzel).parts) - basis >= MAX_TIEFE_BAUM:
                dirs[:] = []
            for d in dirs:
                gesehen += 1
                p = Path(wurzel) / d
                if d.lower() == name and not liegt_in(p, ordner):
                    treffer.append(p)
            if gesehen >= MAX_ORDNER_BAUM:
                return treffer
    return treffer


def vorschlaege_aus_namensvettern(
    ordner: Path, root_folders: Sequence[Path], jahr: Optional[int]
) -> list:
    """Vorschlaege (Suggestion) aus gleichnamigen Ordnern, mit Jahresanpassung."""
    from src.core.neuer_ordner import QUELLE_JAHR, jahres_neuer_ordner
    from src.ml.classifier import Suggestion

    ergebnis: list = []

    def neu(eltern: Path, konfidenz: float, grund: str, quelle: str = ""):
        ergebnis.append(Suggestion(
            folder_path=eltern, folder_name=eltern.name, confidence=konfidenz, reason=grund,
            relative_path=relative_folder(eltern, root_folders) or eltern.name, new_source=quelle,
        ))

    for d in _gleichnamige(ordner, root_folders):
        rel = relative_folder(d, root_folders)
        hat_jahr = bool(rel and _YEAR_RE.search(rel))
        angepasst = None
        if hat_jahr and jahr and str(jahr) not in _YEAR_RE.findall(rel):
            vorhanden = year_adjusted_folder(rel, jahr, root_folders)
            if vorhanden:
                pfad = resolve_relative_folder(vorhanden, root_folders)
                if pfad is not None:
                    angepasst = pfad.parent
                    neu(angepasst, 0.8, f'Gleichnamiger Ordner für {jahr} existiert: "{vorhanden}"')
            else:
                muster = _Muster(d, rel)
                variante = jahres_neuer_ordner([muster], jahr, root_folders)
                if variante is not None:
                    angepasst = Path(variante.folder_path).parent
                    if angepasst.is_dir():
                        neu(angepasst, 0.75,
                            f'"{angepasst.name}" passt zum Jahr {jahr} (Muster: "{rel}")')
                    else:
                        neu(angepasst, 0.6,
                            f'Neuer Ordner "{angepasst.name}" für {jahr} (Muster: "{rel}")',
                            QUELLE_JAHR)
        # Der Namensvetter selbst: das Original-Jahr, bei Jahresanpassung nur zweite Wahl
        neu(d.parent, 0.5 if angepasst is not None else 0.7,
            f'Gleichnamiger Ordner existiert: "{rel or d}"')
    return ergebnis


class _Muster:
    """Minimaler Vorschlag fuer :func:`jahres_neuer_ordner` (folder_path, relative_path, confidence)."""

    new_source = ""
    confidence = 0.7

    def __init__(self, folder: Path, rel: str):
        self.folder_path = folder
        self.relative_path = rel


# --- Zusammenfuehren -------------------------------------------------------------------

def vorschlaege_fuer_ordner(
    ordner: Path | str,
    root_folders: Sequence[Path],
    db=None,
    cache_get: Optional[Callable] = None,
    suggest_fn: Optional[Callable] = None,
    max_vorschlaege: int = 6,
) -> list:
    """Alle automatischen Vorschlaege (a und b) fuer ``ordner``, nach Konfidenz sortiert."""
    from src.ml.classifier import Suggestion

    ordner = Path(ordner)
    roots = [Path(r) for r in root_folders]
    dateien = dateien_unter(ordner)
    jahr = ziel_jahr(ordner, dateien, cache_get)

    kandidaten: list = []

    # a) Mehrheit der Stimmen aus dem Inhalt
    stimmen = stimmen_aus_inhalt(ordner, dateien, roots, db, cache_get, suggest_fn)
    gesamt = sum(stimmen.values())
    if gesamt > 0:
        je_eltern: Counter = Counter()
        for ziel, gewicht in stimmen.items():
            je_eltern[eltern_fuer(ziel, ordner)] += gewicht
        for eltern, gewicht in je_eltern.items():
            anteil = gewicht / gesamt
            kandidaten.append(Suggestion(
                folder_path=eltern, folder_name=eltern.name or str(eltern),
                confidence=min(0.95, 0.3 + 0.65 * anteil),
                reason=f"Inhalt: {int(round(anteil * 100))} % der Dateien gehören laut Lernen/KI dorthin",
                relative_path=relative_folder(eltern, roots) or eltern.name,
            ))

    # b) gleichnamige Ordner im Zielbaum
    kandidaten.extend(vorschlaege_aus_namensvettern(ordner, roots, jahr))

    # Zusammenfuehren je Elternordner; der aktuelle Elternordner und Unterordner fallen weg
    gesperrt_eltern = _norm(ordner.parent)
    je_pfad: dict[str, Suggestion] = {}
    for s in kandidaten:
        pfad = Path(s.folder_path)
        if _norm(pfad) == gesperrt_eltern or liegt_in(pfad, ordner):
            continue
        if not s.new_source and not pfad.is_dir():
            continue
        if roots and not any(liegt_in(pfad, r) for r in roots):
            continue
        key = _norm(pfad)
        alt = je_pfad.get(key)
        if alt is None:
            je_pfad[key] = s
        else:  # beide Quellen nennen ihn: bestaetigt, hoeher bewertet
            alt.confidence = min(0.98, max(alt.confidence, s.confidence) + 0.05)
            if s.reason not in alt.reason:
                alt.reason = f"{alt.reason} + {s.reason}"
            if alt.new_source and not s.new_source:
                alt.new_source = ""
    ergebnis = sorted(je_pfad.values(), key=lambda s: s.confidence, reverse=True)
    return ergebnis[:max_vorschlaege]


# --- c) KI auf Knopfdruck ------------------------------------------------------------------

MAX_DATEINAMEN_PROMPT = 40


def inhaltsuebersicht(ordner: Path, cache_get: Optional[Callable] = None,
                      max_dateien: int = MAX_DATEINAMEN_PROMPT) -> str:
    """Dateinamen (relativ) mit Korrespondent/Kategorie aus dem Cache, begrenzt, fuer den Prompt."""
    dateien = dateien_unter(ordner, limit=max_dateien + 1)
    zeilen = []
    for f in dateien[:max_dateien]:
        zusatz = ""
        ergebnis = cache_get(f) if cache_get is not None else None
        for s in getattr(ergebnis, "llm_suggestions", None) or []:
            meta = getattr(s, "metadata", None)
            if isinstance(meta, dict):
                teile = [str(meta.get(k)).strip() for k in ("korrespondent", "kategorie", "steuerjahr")
                         if meta.get(k) and str(meta.get(k)).strip().upper() != "UNBEKANNT"]
                if teile:
                    zusatz = " (" + ", ".join(teile) + ")"
                    break
        zeilen.append(f"- {f.relative_to(ordner).as_posix()}{zusatz}")
    if len(dateien) > max_dateien:
        zeilen.append("- ... (weitere Dateien)")
    return "\n".join(zeilen) if zeilen else "- (leer)"


def ki_prompt(ordner: Path, root_folders: Sequence[Path], cache_get: Optional[Callable] = None) -> str:
    """Prompt: Wohin gehoert dieser Ordner? Antwort als JSON mit "zielordner" (Elternordner)."""
    from src.core.neuer_ordner import ordnerliste_fuer_prompt

    return (
        "Du hilfst beim Aufräumen einer Dokumentenablage. Ein ganzer Ordner soll unter einen "
        "passenden ELTERNORDNER einsortiert werden.\n\n"
        f'ORDNERNAME: {ordner.name}\n'
        f"INHALT (Dateinamen, ggf. Absender/Kategorie):\n{inhaltsuebersicht(ordner, cache_get)}\n"
        f"{ordnerliste_fuer_prompt(root_folders)}\n\n"
        "AUFGABE: Nenne den Elternordner, unter den der Ordner gehört (nicht den Ordner selbst), "
        "möglichst aus der Liste. Bei Jahresordnern passt das Jahr zum Inhalt "
        "(z.B. \"Steuer 2025\" statt \"Steuer 2024\").\n"
        'Antworte AUSSCHLIESSLICH mit JSON: {"zielordner": "Elternordner relativ wie in der Liste '
        'oder UNBEKANNT", "begruendung": "ein Satz"}'
    )


def ki_antwort_auswerten(text: str, ordner: Path, root_folders: Sequence[Path]):
    """Macht aus der KI-Antwort einen Vorschlag (Suggestion) oder None.

    Ein vorhandener Ordner wird direkt genommen, ein noch fehlender nur, wenn er sicher
    unter einem Zielordner liegt (:func:`neuer_ordner.neuer_pfad_unter_zielordner`).
    Der aktuelle Elternordner, der Ordner selbst und Unterordner werden verworfen.
    """
    from src.core.neuer_ordner import QUELLE_KI, neuer_pfad_unter_zielordner
    from src.ml.classifier import Suggestion

    daten = None
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if m:
        try:
            daten = json.loads(m.group(0))
        except ValueError:
            daten = None
    if not isinstance(daten, dict):
        return None
    rel = normalize_relative(str(daten.get("zielordner") or ""))
    if not rel or rel.upper() in ("UNBEKANNT", "NULL", "NONE"):
        return None
    roots = [Path(r) for r in root_folders]
    pfad = resolve_relative_folder(rel, roots)
    neu = False
    if pfad is None:
        pfad = neuer_pfad_unter_zielordner(rel, roots)
        neu = pfad is not None
    if pfad is None:
        return None
    if _norm(pfad) == _norm(ordner.parent) or liegt_in(pfad, ordner):
        return None
    grund = str(daten.get("begruendung") or "").strip()
    return Suggestion(
        folder_path=pfad, folder_name=pfad.name or str(pfad), confidence=0.85,
        reason="KI: " + (grund or "passender Elternordner"),
        relative_path=relative_folder(pfad, roots) or rel,
        new_source=QUELLE_KI if neu else "",
    )


def ki_zielordner(provider, ordner: Path | str, root_folders: Sequence[Path],
                  cache_get: Optional[Callable] = None):
    """Fragt die KI nach dem Elternordner; liefert einen Vorschlag oder None.

    Wirft ``RuntimeError`` mit lesbarem Text, wenn der Aufruf scheitert.
    """
    ordner = Path(ordner)
    antwort = provider.answer_with_context(
        system_prompt="Du bist ein Assistent zum Ordnen von Dokumenten. Antworte nur mit JSON.",
        context_docs=[],
        user_question=ki_prompt(ordner, root_folders, cache_get),
        max_tokens=400,
    )
    antwort = (antwort or "").strip()
    if not antwort:
        raise RuntimeError("Die KI hat nicht geantwortet.")
    if antwort.startswith("[") and "fehler" in antwort[:60].lower():
        raise RuntimeError(antwort.strip("[]"))
    return ki_antwort_auswerten(antwort, ordner, root_folders)
