"""Einheit bzw. Verbrauchsstelle eines Dokuments (Issue #257). Qt-frei.

Wer mehrere Wohnungen oder Zaehler an einer Adresse hat, bekommt gleich
aussehende Rechnungen; Rechnungsanschrift und Verbrauchsstelle weichen oft
voneinander ab. Die KI liest deshalb zwei Angaben aus dem Dokument:

- ``einheit``: die Verbrauchsstelle/Lieferanschrift in Kurzform
  ("Musterweg 5 Whg 2") - sichtbar im Feld "Einheit" des Detail-Panels,
- ``einheit_kennung``: Zaehlernummer oder Vertragskonto dieser Einheit.

Beim Ablegen merkt sich das Programm, in welchen Ordner ein Dokument dieser
Einheit gelegt wurde (:meth:`Database.learn_einheit`). Beim naechsten Dokument
mit derselben Kennung oder derselben Einheit steht dieser Ordner oben
(:func:`ordner_vorschlag`), und die KI bekommt die bekannten Einheiten genannt
(:func:`fuer_prompt`), damit sie dieselbe Bezeichnung wieder verwendet.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Sequence

from src.i18n import tr

# Vertrauen: Die Zuordnung stammt aus einer Entscheidung des Nutzers und ist
# enger als "gleiche Kundennummer" (die gilt fuer alle Einheiten eines Kunden),
# darum ueber den Vorschlaegen aus verknuepften Dokumenten (hoechstens 0.95).
VERTRAUEN_KENNUNG = 0.97
VERTRAUEN_EINHEIT = 0.96
# So viele bekannte Einheiten nennt der Prompt der KI
EINHEITEN_IM_PROMPT = 12
MIN_KENNUNG = 4  # kuerzere Kennungen sind zu beliebig

_UNBEKANNT = {"", "unbekannt", "unknown", "null", "none", "n/a", "-"}


def kennung_schluessel(wert) -> str:
    """Vergleichsform einer Kennung: nur Buchstaben und Ziffern, klein ("DE 00-47 11" -> "de004711").

    Leer, wenn der Wert zu kurz ist oder keine Ziffer enthaelt.
    """
    s = re.sub(r"[^0-9a-z]", "", str(wert or "").casefold())
    if len(s) < MIN_KENNUNG or not any(c.isdigit() for c in s):
        return ""
    return s


def einheit_schluessel(wert) -> str:
    """Vergleichsform einer Einheit: klein, Umlaute wie geschrieben, ohne Satz- und Leerzeichen.

    "Musterweg 5, Whg. 2" und "musterweg 5 whg 2" sind dieselbe Einheit;
    "Straße"/"Strasse"/"Str." werden gleich behandelt.
    """
    s = str(wert or "").casefold().strip()
    if s in _UNBEKANNT:
        return ""
    s = re.sub(r"stra(?:ß|ss)e|str\.", "str", s)
    return re.sub(r"[^0-9a-zäöüß]", "", s)


def saeubern(wert) -> str:
    """Anzeigeform: ohne Rand, ohne Zeilenumbrueche; Platzhalter wie UNBEKANNT werden leer."""
    s = " ".join(str(wert or "").split())
    return "" if s.casefold() in _UNBEKANNT else s


# --- Gelernte Zuordnungen ------------------------------------------------------
# Das Hauptfenster haengt hier die Datenbank ein (wie ``schlagwoerter.quelle_setzen``);
# ohne Quelle - etwa in Tests - kennt der Prompt keine Einheiten, und nichts
# greift auf die Daten des Nutzers zu.
_quelle = None


def quelle_setzen(funktion) -> None:
    """``funktion() -> list[dict]`` liefert die gelernten Zuordnungen (neueste zuerst); None haengt aus.

    Je Eintrag ``einheit``, ``kennung``, ``target_folder`` und - fuer den Prompt -
    ``ablageort`` (Ordner relativ zum Zielordner).
    """
    global _quelle
    _quelle = funktion


def gelernte() -> list[dict]:
    """Gelernte Zuordnungen aus der eingehaengten Quelle; ohne Quelle oder bei Fehlern leer."""
    if _quelle is None:
        return []
    try:
        return list(_quelle() or [])
    except Exception:  # noqa: BLE001 - Zusatzwissen, nie Blocker
        return []


def fuer_prompt(zuordnungen: Optional[Sequence[dict]] = None, root_folders: Sequence[Path] = ()) -> str:
    """Prompt-Abschnitt mit den bekannten Einheiten des Nutzers; leer, wenn es keine gibt."""
    from src.core.similar_documents import relative_folder

    zeilen: list[str] = []
    gesehen: set[tuple[str, str]] = set()
    for z in (gelernte() if zuordnungen is None else zuordnungen):
        einheit = saeubern(z.get("einheit"))
        kennung = saeubern(z.get("kennung"))
        key = (einheit_schluessel(einheit), kennung_schluessel(kennung))
        if not einheit or key in gesehen:
            continue
        gesehen.add(key)
        zeile = f'- "{einheit}"'
        if kennung:
            zeile += f" (Zähler/Vertragskonto {kennung})"
        ordner = z.get("ablageort") or relative_folder(
            z.get("target_folder"), [Path(r) for r in root_folders or ()])
        if ordner:
            zeile += f', zuletzt abgelegt in "{ordner}"'
        zeilen.append(zeile)
        if len(zeilen) >= EINHEITEN_IM_PROMPT:
            break
    if not zeilen:
        return ""
    return (
        "\nBEKANNTE EINHEITEN DES NUTZERS (Wohnungen/Verbrauchsstellen aus früheren Ablagen):\n"
        + "\n".join(zeilen)
        + "\nGehört das Dokument zu einer davon (gleiche Zählernummer, gleiches Vertragskonto oder "
        'gleiche Verbrauchsstelle), nenne unter "einheit" genau diese Bezeichnung.\n'
    )


def _kennungen_im_text(text: str) -> set[str]:
    """Vergleichsformen aller Kennungen, die die Texterkennung im Dokument findet."""
    if not (text or "").strip():
        return set()
    try:
        from src.rag.bezug import kennungen_aus_text
        gefunden = kennungen_aus_text(text, max_anzahl=40)
    except Exception:  # noqa: BLE001 - Zusatzwissen, nie Blocker
        return set()
    return {k for k in (kennung_schluessel(kn.wert) for kn in gefunden) if k}


def ordner_vorschlag(
    metadata: Optional[dict],
    text: str,
    zuordnungen: Sequence[dict],
    root_folders: Sequence[Path],
    year: Optional[int] = None,
):
    """Zielordner, in den Dokumente derselben Einheit zuletzt abgelegt wurden (oder None).

    Zuerst zaehlt die Kennung (Zaehlernummer/Vertragskonto aus den KI-Metadaten
    oder woertlich im Text), dann die Bezeichnung der Einheit. ``zuordnungen``
    kommen neueste zuerst; ein Jahresordner wird auf ``year`` angepasst, wenn
    es den Ordner fuer das Jahr gibt. Nur bestehende Ordner unter einem Zielordner.
    """
    from src.core.similar_documents import relative_folder, resolve_relative_folder, year_adjusted_folder
    from src.ml.classifier import Suggestion

    roots = [Path(r) for r in (root_folders or ()) if r]
    if not zuordnungen or not roots:
        return None
    md = metadata if isinstance(metadata, dict) else {}
    kennungen = _kennungen_im_text(text)
    ki_kennung = kennung_schluessel(md.get("einheit_kennung"))
    if ki_kennung:
        kennungen.add(ki_kennung)
    einheit = einheit_schluessel(md.get("einheit"))

    def ziel(z: dict):
        ordner = z.get("target_folder")
        rel = relative_folder(ordner, roots) if ordner else ""
        if not rel:
            return None
        angepasst = year_adjusted_folder(rel, year, roots) if year else None
        if angepasst:
            rel = angepasst
        pfad = resolve_relative_folder(rel, roots)
        return (pfad, rel) if pfad is not None else None

    for ueber_kennung in (True, False):
        for z in zuordnungen:
            if ueber_kennung:
                passt = bool(kennungen) and kennung_schluessel(z.get("kennung")) in kennungen
            else:
                passt = bool(einheit) and einheit_schluessel(z.get("einheit")) == einheit
            if not passt:
                continue
            treffer = ziel(z)
            if treffer is None:
                continue  # Ordner gibt es nicht mehr: die naechstaeltere Zuordnung versuchen
            pfad, rel = treffer
            name = saeubern(z.get("einheit"))
            if ueber_kennung:
                grund = (tr("Einheit „{name}“: gleiche Zählernummer bzw. gleiches Vertragskonto wie zuletzt hier abgelegt")
                         if name else tr("Gleiche Zählernummer bzw. gleiches Vertragskonto wie zuletzt hier abgelegt"))
            else:
                grund = tr("Einheit „{name}“: zuletzt hier abgelegt")
            return Suggestion(
                folder_path=pfad, folder_name=pfad.name,
                confidence=VERTRAUEN_KENNUNG if ueber_kennung else VERTRAUEN_EINHEIT,
                reason=grund.format(name=name), relative_path=rel,
            )
    return None
