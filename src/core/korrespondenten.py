"""Korrespondenten: Schreibweisen vereinheitlichen, gruppieren, Auffaelliges finden (Issue #160, Qt-frei).

Der Korrespondent ist die Gegenpartei eines Dokuments aus Sicht des Nutzers
(Absender fremder Post bzw. Empfaenger oder Vertragspartner eigener
Schreiben), nie der Nutzer selbst und nie ein Formularverlag.

* :func:`schluessel` bildet Schreibweisen, die eindeutig dasselbe meinen
  (Gross-/Kleinschreibung, Leerzeichen, Satzzeichen, Rechtsformen, ae/ä),
  auf denselben Vergleichswert ab.
* :func:`gruppieren` fasst die Korrespondenten des Suchindex zu Gruppen
  zusammen, wendet dabei die gespeicherten Aliasse an (Tabelle
  ``korrespondenten``) und waehlt die kanonische Schreibweise.
* :func:`kandidaten_paare`, :func:`ki_frage` und :func:`ki_antwort_lesen`
  bereiten unsichere Faelle ("Stadtwerke GÖ" / "Stadtwerke Göttingen") fuer
  die KI auf; deren Urteil wird als Alias gespeichert.
* :func:`auffaelligkeit` erkennt Korrespondenten, die neu bewertet werden
  sollten: leer, der Nutzer selbst oder ein Formular- bzw. Druckverlag.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import difflib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping
from src.i18n import tr

# Rechtsformen und Zusaetze, die nichts an der Identitaet aendern (nach :func:`schluessel`
# geschrieben: klein, ohne Punkte, Umlaute als ae/oe/ue). Nur am Ende bzw. nach dem
# ersten Wort entfernt ("AG Göttingen" ist das Amtsgericht).
RECHTSFORMEN = frozenset({
    "gmbh", "mbh", "ag", "kg", "kgaa", "ohg", "gbr", "ug", "haftungsbeschraenkt", "ev", "eg", "ek", "ekfm",
    "se", "ltd", "limited", "inc", "llc", "plc", "corp", "partg", "partgmbb", "mbb", "gmbhco", "kgco",
})

# Formular-, Vordruck- und Druckverlage, deren Name nur auf dem Formular steht
# (Mietvertrag von "Haus & Grund", Vordrucke von Zweckform ...). Erweiterbar;
# geschrieben wie im Dokument, verglichen ueber :func:`schluessel`.
FORMULAR_VERLAGE: tuple[str, ...] = (
    "Haus und Grund",
    "Haus & Grund",
    "Zweckform",
    "Avery",
    "Formblitz",
    "RNK",
    "Herlitz",
    "Soldan",
    "Formularverlag",
    "Vordruckverlag",
)

# Titel und Anreden, die bei der Erkennung des Nutzers nicht zaehlen
_TITEL = frozenset({
    "dr", "prof", "med", "dent", "vet", "dipl", "ing", "mag", "phil", "rer", "nat", "jur", "univ", "pd",
    "hc", "herr", "frau", "hr", "fr",
})

GRUND_LEER = "leer"
GRUND_NUTZER = "nutzer"
GRUND_VERLAG = "verlag"

GRUND_TEXT = {
    GRUND_LEER: tr("kein Korrespondent"),
    GRUND_NUTZER: tr("der Nutzer selbst"),
    GRUND_VERLAG: tr("Formular- bzw. Druckverlag"),
}


# --------------------------------------------------------------------------- Normalisierung


def _ascii(text: str) -> str:
    """Kleinschreibung, Umlaute als ae/oe/ue/ss, uebrige Akzente weg."""
    s = unicodedata.normalize("NFKC", text or "").lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(alt, neu)
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens(name: str) -> list[str]:
    """Woerter einer Schreibweise ohne Satzzeichen und Rechtsformen (siehe :func:`schluessel`)."""
    s = _ascii(name)
    s = re.sub(r"(?:&|\+|\bund)\s*co\b\.?", " ", s)              # "& Co.", "und Co"
    s = re.sub(r"\b([a-z])\.\s*(?=[a-z]\b)", r"\1", s)           # "e. V." / "e.V." -> "ev."
    s = s.replace("&", " und ").replace("+", " und ")
    s = re.sub(r"[^\w\s]|_", " ", s)
    woerter = s.split()
    ohne = [w for i, w in enumerate(woerter) if i == 0 or w not in RECHTSFORMEN]
    return ohne or woerter


def schluessel(name: str) -> str:
    """Vergleichswert einer Schreibweise; gleiche Werte meinen eindeutig denselben Korrespondenten.

    ``"Stadtwerke Göttingen AG"``, ``"stadtwerke goettingen"`` und
    ``"Stadtwerke  Göttingen."`` ergeben denselben Wert, ebenso
    ``"Haus & Grund e.V."`` und ``"Haus und Grund"``.
    """
    return " ".join(_tokens(name))


# --------------------------------------------------------------------------- Gruppen


@dataclass
class Gruppe:
    """Ein Korrespondent mit allen Schreibweisen, die im Index vorkommen.

    Attributes:
        name: kanonische Schreibweise (vom Nutzer uebernommen, sonst die haeufigste)
        anzahl: Dokumente aller Schreibweisen zusammen
        schreibweisen: Werte genau so, wie sie im Index stehen (fuer die Dokumentabfrage)
    """

    name: str
    anzahl: int = 0
    schreibweisen: list[str] = field(default_factory=list)

    @property
    def schluessel(self) -> str:
        return schluessel(self.name)


def _aliase(eintrag: Mapping) -> list[str]:
    aliases = eintrag.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    return [str(a) for a in aliases if str(a).strip()]


def _zielkarte(eintraege: Iterable[Mapping]) -> dict[str, str]:
    """Schluessel (Name oder Alias eines Eintrags) -> Name des Eintrags; der zuerst gelistete gewinnt."""
    karte: dict[str, str] = {}
    eintraege = [e for e in eintraege if str(e.get("name") or "").strip()]
    for e in eintraege:  # erst alle Namen, damit ein Alias nie einen eigenen Namen ueberdeckt
        karte.setdefault(schluessel(str(e["name"])), str(e["name"]).strip())
    for e in eintraege:
        for a in _aliase(e):
            karte.setdefault(schluessel(a), str(e["name"]).strip())
    return karte


def kanonisch(name: str, eintraege: Iterable[Mapping]) -> str:
    """Kanonische Schreibweise fuer ``name``: der Eintrag der Verwaltung, dessen Name oder Alias passt.

    Ohne passenden Eintrag bleibt ``name`` (ohne Randleerzeichen) stehen.
    """
    name = (name or "").strip()
    if not name:
        return ""
    return _zielkarte(eintraege).get(schluessel(name), name)


def gruppieren(zaehlung: Iterable[tuple[str, int]], eintraege: Iterable[Mapping] = ()) -> list[Gruppe]:
    """Fasst ``(Schreibweise, Anzahl)`` aus dem Index zu Gruppen zusammen.

    Schreibweisen mit gleichem :func:`schluessel` gehoeren zusammen; ein
    gespeicherter Alias (``eintraege`` = Zeilen der Tabelle ``korrespondenten``)
    haengt eine Schreibweise an den Eintrag, zu dem er gehoert. Kanonisch ist
    der Name des Eintrags (die Schreibweise des Nutzers), sonst die
    haeufigste Schreibweise. Sortiert nach Anzahl absteigend, dann Name.
    """
    karte = _zielkarte(eintraege)
    gruppen: dict[str, dict] = {}
    for wert, n in zaehlung:
        wert = str(wert or "").strip()
        if not wert:
            continue
        k = schluessel(wert)
        ziel = karte.get(k)
        gk = schluessel(ziel) if ziel else k
        g = gruppen.setdefault(gk, {"name": ziel, "zaehlung": {}})
        g["zaehlung"][wert] = g["zaehlung"].get(wert, 0) + int(n or 0)
    ergebnis = []
    for g in gruppen.values():
        zaehlung_g = g["zaehlung"]
        name = g["name"] or sorted(zaehlung_g, key=lambda w: (-zaehlung_g[w], -len(w), w.casefold()))[0]
        ergebnis.append(Gruppe(name=name, anzahl=sum(zaehlung_g.values()),
                               schreibweisen=sorted(zaehlung_g, key=lambda w: (-zaehlung_g[w], w.casefold()))))
    ergebnis.sort(key=lambda g: (-g.anzahl, g.name.casefold()))
    return ergebnis


def passt_zu(gruppe: Gruppe, name: str) -> bool:
    """Meint ``name`` diese Gruppe (Name oder eine ihrer Schreibweisen, nach :func:`schluessel`)?"""
    k = schluessel(name)
    return bool(k) and (k == gruppe.schluessel or any(schluessel(s) == k for s in gruppe.schreibweisen))


def filter_passt(gruppe: Gruppe, suchtext: str) -> bool:
    """Suchfeld der Liste: Teiltext im Namen oder einer Schreibweise (ae/ä und Gross/klein egal)."""
    t = _ascii(suchtext).strip()
    if not t:
        return True
    return any(t in _ascii(s) for s in (gruppe.name, *gruppe.schreibweisen))


# --------------------------------------------------------------------------- Auffaellige Korrespondenten


def owner_namen(config) -> list[str]:
    """Namen des Nutzers aus der Konfiguration: ``owner_name``, ``owner_name_variants``, ``owner_company``."""
    try:
        namen = [str(config.get("owner_name", "") or "")]
        namen += str(config.get("owner_name_variants", "") or "").split(",")
        namen.append(str(config.get("owner_company", "") or ""))
    except Exception:  # noqa: BLE001 - ohne Konfiguration kein Nutzername
        return []
    return [n.strip() for n in namen if n and n.strip()]


def _kern(name: str) -> list[str]:
    return [w for w in _tokens(name) if w not in _TITEL]


def ist_nutzer(name: str, owner: Iterable[str]) -> bool:
    """Ist ``name`` der Nutzer selbst? Gleiche Woerter (ohne Titel), oder bei mindestens
    zwei Woertern sind die einen ganz in den anderen enthalten ("Härle-Wack" in
    "Dr. Johannes Härle-Wack")."""
    t = _kern(name)
    if not t:
        return False
    for o in owner:
        ot = _kern(o)
        if not ot:
            continue
        if t == ot:
            return True
        if len(t) >= 2 and len(ot) >= 2 and (set(t) <= set(ot) or set(ot) <= set(t)):
            return True
    return False


def ist_verlag(name: str, verlage: Iterable[str] = FORMULAR_VERLAGE) -> bool:
    """Steht ein bekannter Formular- bzw. Druckverlag im Namen ("Haus & Grund Göttingen e.V.")?"""
    k = f" {schluessel(name)} "
    for v in verlage:
        vk = schluessel(v)
        if vk and f" {vk} " in k:
            return True
    return False


def auffaelligkeit(name: str | None, owner: Iterable[str] = ()) -> str | None:
    """Grund, den Korrespondenten neu zu bewerten (:data:`GRUND_LEER`, :data:`GRUND_NUTZER`,
    :data:`GRUND_VERLAG`), oder None, wenn er plausibel ist."""
    if not schluessel(name or ""):
        return GRUND_LEER
    if ist_nutzer(name, owner):
        return GRUND_NUTZER
    if ist_verlag(name):
        return GRUND_VERLAG
    return None


def _unter(pfad: str, wurzeln: Iterable[str]) -> bool:
    p = os.path.normcase(os.path.normpath(str(pfad)))
    for w in wurzeln:
        w = os.path.normcase(os.path.normpath(str(w))).rstrip("\\/")
        if w and (p == w or p.startswith(w + os.sep)):
            return True
    return False


def auffaellige_dokumente(dokumente: Iterable[Mapping], wurzeln: Iterable, owner: Iterable[str] = ()) -> list[dict]:
    """Dokumente unter ``wurzeln`` (Zielordner), deren Korrespondent neu bewertet werden sollte.

    ``dokumente``: Zeilen des Suchindex mit ``datei`` (bzw. ``pfad``) und
    ``korrespondent``. Ergebnis: Kopien mit zusaetzlichem Schluessel ``grund``.
    """
    wurzeln = [str(w) for w in wurzeln]
    owner = list(owner)
    ergebnis = []
    for d in dokumente:
        pfad = d.get("datei") or d.get("pfad") or ""
        if not pfad or not _unter(pfad, wurzeln):
            continue
        grund = auffaelligkeit(d.get("korrespondent"), owner)
        if grund:
            ergebnis.append({**d, "grund": grund})
    return ergebnis


def erkennbare_eintraege(eintraege: Iterable[Mapping], owner: Iterable[str] = ()) -> list[Mapping]:
    """Eintraege fuer das Wiedererkennen im Text (#109) ohne Nutzer und Formularverlage.

    Sonst setzte "Haus & Grund" aus dem Kopf jedes Mietvertragsformulars sich
    immer wieder selbst als Korrespondent.
    """
    owner = list(owner)
    return [e for e in eintraege if auffaelligkeit(str(e.get("name") or ""), owner) is None]


# --------------------------------------------------------------------------- Unsichere Faelle: KI


def paar_schluessel(a: str, b: str) -> str:
    """Reihenfolge-unabhaengige Kennung eines Paares (fuer die Liste der schon geprueften)."""
    return "|".join(sorted((schluessel(a), schluessel(b))))


def _aehnlich(ta: list[str], tb: list[str]) -> bool:
    """Koennten zwei (verschiedene) Schreibweisen denselben Korrespondenten meinen?"""
    kurz, lang = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if set(kurz) <= set(lang):
        return True  # "Telekom" / "Telekom Deutschland"
    if ta[0] == tb[0] and len(ta[0]) >= 3:
        # "Stadtwerke GÖ" / "Stadtwerke Göttingen": jedes Wort der einen Seite ist Anfang eines Worts der anderen
        for x, y in ((ta, tb), (tb, ta)):
            if all(any(w.startswith(k) for w in y) for k in x):
                return True
    return difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio() >= 0.85  # Tippfehler


def kandidaten_paare(gruppen: Iterable[Gruppe], geprueft: Iterable[str] = (), max_paare: int = 40) -> list[tuple[str, str]]:
    """Paare von Gruppen, ueber deren Gleichheit die KI entscheiden soll.

    Nur Gruppen mit gleichem Anfang (erste drei Buchstaben) werden verglichen,
    schon gepruefte Paare (:func:`paar_schluessel`) fallen weg. Paare mit
    vielen Dokumenten kommen zuerst.
    """
    geprueft = set(geprueft)
    gruppen = [g for g in gruppen if g.schluessel]
    eimer: dict[str, list[Gruppe]] = {}
    for g in gruppen:
        eimer.setdefault(g.schluessel[:3], []).append(g)
    paare = []
    for liste in eimer.values():
        for i, a in enumerate(liste):
            ta = a.schluessel.split()
            for b in liste[i + 1:]:
                if paar_schluessel(a.name, b.name) in geprueft:
                    continue
                if _aehnlich(ta, b.schluessel.split()):
                    paare.append((a.anzahl + b.anzahl, a.name, b.name))
    paare.sort(key=lambda p: (-p[0], p[1].casefold(), p[2].casefold()))
    return [(a, b) for _, a, b in paare[:max_paare]]


KI_SYSTEM_PROMPT = (
    "Du gleichst Namen von Korrespondenten ab (Personen, Firmen, Behörden, Praxen, Institutionen). "
    "Du antwortest ausschließlich mit einem JSON-Objekt, ohne Erklärungen und ohne Code-Block."
)


def ki_frage(paare: list[tuple[str, str]]) -> str:
    """Anweisung an die KI fuer :data:`KI_SYSTEM_PROMPT`; Antwort siehe :func:`ki_antwort_lesen`."""
    zeilen = "\n".join(f'{i}. "{a}" | "{b}"' for i, (a, b) in enumerate(paare, 1))
    return f"""Prüfe für jedes Paar, ob beide Namen denselben Korrespondenten meinen: dieselbe Person bzw. dieselbe Firma, Behörde oder Institution, nur anders geschrieben, abgekürzt oder mit bzw. ohne Zusatz.

Gleich sind zum Beispiel:
- "Stadtwerke GÖ" und "Stadtwerke Göttingen" (Abkürzung)
- "Telekom" und "Telekom Deutschland" (Zusatz)
- "Dr. Anna Schmidt" und "Anna Schmidt" (Titel)
Verschieden sind zum Beispiel:
- "Stadtwerke Göttingen" und "Stadtwerke Kassel" (andere Stadt)
- "Anna Schmidt" und "Peter Schmidt" (andere Person)
- "Finanzamt Göttingen" und "Finanzamt Northeim" (anderes Amt)
Im Zweifel: verschieden.

PAARE:
{zeilen}

Antworte NUR mit diesem JSON, ein Eintrag je Paar:
{{"paare": [{{"nr": 1, "gleich": true}}, {{"nr": 2, "gleich": false}}]}}"""


def ki_antwort_lesen(text: str, paare: list[tuple[str, str]]) -> list[tuple[str, str, bool]]:
    """Liest die Antwort der KI tolerant (Code-Block, Text davor oder danach).

    Liefert ``(a, b, gleich)`` fuer jedes beantwortete Paar; unbekannte
    Nummern und unlesbare Eintraege fallen weg.
    """
    text = re.sub(r"```(?:json)?", "", text or "")
    m = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
    if not m:
        return []
    try:
        daten = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    eintraege = daten.get("paare") if isinstance(daten, dict) else daten
    if not isinstance(eintraege, list):
        return []
    ergebnis = []
    for e in eintraege:
        if not isinstance(e, dict):
            continue
        try:
            nr = int(e.get("nr"))
        except (TypeError, ValueError):
            continue
        if not 1 <= nr <= len(paare):
            continue
        gleich = e.get("gleich")
        if isinstance(gleich, str):
            gleich = gleich.strip().lower() in ("true", "ja", "yes", "1")
        a, b = paare[nr - 1]
        ergebnis.append((a, b, bool(gleich)))
    return ergebnis


def geprueft_laden(pfad: Path) -> set[str]:
    """Schon von der KI gepruefte Paare (JSON-Datei neben der Datenbank)."""
    try:
        daten = json.loads(Path(pfad).read_text(encoding="utf-8"))
        return {str(p) for p in daten.get("geprueft", [])}
    except (OSError, ValueError, AttributeError):
        return set()


def geprueft_speichern(pfad: Path, geprueft: Iterable[str]) -> None:
    try:
        Path(pfad).write_text(json.dumps({"geprueft": sorted(set(geprueft))}, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except OSError:
        pass  # Komfort: dann fragt der naechste Start dieselben Paare noch einmal


# --------------------------------------------------------------------------- Anzeige


def relativer_ordner(ordner: str, wurzeln: Iterable) -> str:
    """Ablageort relativ zum Zielordner, der ihn enthaelt (mit dessen Namen), sonst der volle Pfad."""
    ordner = str(ordner or "")
    beste = None
    for w in wurzeln:
        w = str(w)
        if _unter(ordner, [w]) and (beste is None or len(w) > len(beste)):
            beste = w
    if beste is None:
        return ordner
    try:
        rel = os.path.relpath(ordner, beste)
    except ValueError:
        return ordner
    basis = Path(beste).name or beste
    return basis if rel in (".", "") else os.path.join(basis, rel)
