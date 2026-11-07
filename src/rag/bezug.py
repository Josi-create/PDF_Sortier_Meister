"""
Bezugsdokument fuer den Chat (Issue #148, #27).

Ist im Vorschau-Reiter ein PDF ausgewaehlt und wechselt der Nutzer in den
Chat, beziehen sich Fragen wie "Zu welcher Wohnung gehoert dieses
Dokument?" auf genau dieses PDF. Der :class:`Bezug` traegt dafuer alles,
was der GUI-Thread schon kennt (Text und KI-Metadaten aus dem
``pdf_cache``, die angezeigten Ordnervorschlaege, die Zielordner). Der
:class:`~src.rag.rag_controller.RAGController` liest zuerst den Suchindex
und nimmt diese Werte als Rueckfall.

Qt-frei, damit der Controller im Worker-Thread nichts aus der GUI braucht.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from src.core.similar_documents import relative_folder

# Laenge des Textauszugs fuer das Bezugsdokument: laenger als die Snippets
# der Suchtreffer, weil die Frage sich gerade auf dieses Dokument bezieht.
BEZUG_MAX_ZEICHEN = 3000

# Metadaten, die im Kontext stehen und die Suche nach aehnlichen Dokumenten anreichern
BEZUG_FELDER = ("korrespondent", "kategorie", "steuerjahr", "betrag")
SUCH_FELDER = ("korrespondent", "kategorie", "steuerjahr")

# Schnellfragen im Chat (Reihenfolge = Reihenfolge der Knoepfe)
SCHNELLFRAGEN = (
    "Zu welcher Wohnung / welchem Objekt gehört dieses Dokument?",
    "Zeig mir ähnliche Rechnungen",
    "Gibt es schon einen Ordner mit ähnlichen Dokumenten?",
    "In welchen Ordner gehört dieses PDF?",
)

# Fragen nach dem Ablageort bekommen den Vorschlag der Sortierlogik in den Kontext
_ORDNER_FRAGE_RE = re.compile(r"ordner|verzeichnis|ablegen|ablage|einsortier|einordn", re.IGNORECASE)


@dataclass
class Bezug:
    """Das Dokument, auf das sich eine Chatfrage bezieht.

    Attributes:
        pfad: Pfad der PDF.
        text: Rueckfall-Text (z.B. aus dem ``pdf_cache``), falls der
            Suchindex die Datei noch nicht kennt.
        metadaten: Rueckfall-Metadaten (``korrespondent``, ``kategorie``,
            ``steuerjahr``, ``betrag``), z.B. aus dem KI-Vorschlag.
        sortier_vorschlaege: Ordnervorschlaege der Sortierlogik als Text,
            bester zuerst (z.B. ``"Steuer 2024/Energie (90 %)"``).
        wurzeln: Zielordner; Ablageorte werden relativ dazu angegeben.
    """

    pfad: Path
    text: str = ""
    metadaten: dict = field(default_factory=dict)
    sortier_vorschlaege: list[str] = field(default_factory=list)
    wurzeln: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.pfad = Path(self.pfad)


def als_bezug(wert) -> Optional[Bezug]:
    """Nimmt einen :class:`Bezug`, einen Pfad (str/Path) oder None."""
    if wert is None or wert == "":
        return None
    if isinstance(wert, Bezug):
        return wert
    return Bezug(pfad=Path(wert))


def frage_betrifft_ordner(frage: str) -> bool:
    """True, wenn die Frage nach einem Ordner bzw. Ablageort fragt."""
    return bool(_ORDNER_FRAGE_RE.search(frage or ""))


def gleicher_pfad(a, b) -> bool:
    """Vergleicht zwei Pfade ohne Gross-/Kleinschreibung und Trennzeichen-Unterschiede."""
    if not a or not b:
        return False
    return Path(str(a)).as_posix().casefold() == Path(str(b)).as_posix().casefold()


def ablageort(datei_pfad, wurzeln: Sequence[Path]) -> str:
    """Ordner der Datei relativ zu einem Zielordner ("Ablage/Steuer 2024/Energie").

    Gleiche Schreibweise wie die Ordnervorschlaege
    (:func:`src.core.similar_documents.relative_folder`). Liegt die Datei
    ausserhalb aller Zielordner (z.B. im Scan-Ordner), nur der Name des
    Ordners; ohne Pfad ein leerer String.
    """
    if not datei_pfad:
        return ""
    ordner = Path(str(datei_pfad)).parent
    return relative_folder(ordner, list(wurzeln or ())) or ordner.name
