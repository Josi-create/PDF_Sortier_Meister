"""
Bezugsdokument fuer den Chat (Issue #148, #27) und Kennungen (Issue #166, #167).

Ist im Vorschau-Reiter ein PDF ausgewaehlt und wechselt der Nutzer in den
Chat, beziehen sich Fragen wie "Zu welcher Wohnung gehoert dieses
Dokument?" auf genau dieses PDF. Der :class:`Bezug` traegt dafuer alles,
was der GUI-Thread schon kennt (Text und KI-Metadaten aus dem
``pdf_cache``, die angezeigten Ordnervorschlaege, die Zielordner, den
Scan-Ordner). Der :class:`~src.rag.rag_controller.RAGController` liest
zuerst den Suchindex und nimmt diese Werte als Rueckfall.

Kennungen (Issue #166/#167): Vertrags-, Kunden-, Zaehler- und
Rechnungsnummern, IBANs und aehnliche Codes im Text des Bezugsdokuments
verbinden es mit anderen Dokumenten der Sammlung (die Verbrauchsabrechnung
mit derselben Vertragsnummer nennt die Abnahmestelle). :func:`kennungen_aus_text`
zieht sie heraus, :func:`kennungs_abfrage` macht daraus eine exakte
FTS-Phrase fuer den Suchindex.

Qt-frei, damit der Controller im Worker-Thread nichts aus der GUI braucht.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from src.core.similar_documents import relative_folder

# Laenge des Textauszugs fuer das Bezugsdokument: laenger als die Snippets
# der Suchtreffer, weil die Frage sich gerade auf dieses Dokument bezieht.
BEZUG_MAX_ZEICHEN = 5000

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

# Hoechstzahl eigener Schnellfragen (Phase 3, Issue #166)
MAX_SCHNELLFRAGEN = 12


def schnellfragen_aus_text(text: str) -> list[str]:
    """Eine Frage je Zeile (Einstellungen): leere Zeilen und Doppelte weg, hoechstens MAX_SCHNELLFRAGEN."""
    fragen: list[str] = []
    for zeile in (text or "").splitlines():
        frage = " ".join(zeile.split())
        if frage and frage not in fragen:
            fragen.append(frage)
    return fragen[:MAX_SCHNELLFRAGEN]


def schnellfragen_liste(chat_config=None) -> list[str]:
    """Die Schnellfragen des Chats: eigene aus der Konfiguration, sonst die Standardfragen."""
    eigene = getattr(chat_config, "schnellfragen", None) or []
    fragen = schnellfragen_aus_text("\n".join(str(f) for f in eigene))
    return fragen or list(SCHNELLFRAGEN)


# Fragen nach dem Ablageort bekommen den Vorschlag der Sortierlogik in den Kontext
_ORDNER_FRAGE_RE = re.compile(r"ordner|verzeichnis|ablegen|ablage|einsortier|einordn", re.IGNORECASE)

# Hoechstens so viele Kennungen je Bezugsdokument (jede loest eine Indexsuche aus)
MAX_KENNUNGEN = 8
# Treffer je Kennung aus dem Suchindex
KENNUNG_TREFFER_JE = 3


# Benannte Kennungen, die ein einzelnes Vertragsverhaeltnis bezeichnen; sie
# wiegen mehr als IBAN oder unbenannte Zahlen (die auch Absender-Angaben sein koennen)
BENANNTE_ARTEN = frozenset({
    "Vertragsnummer", "Kundennummer", "Zählernummer", "Rechnungsnummer", "Auftragsnummer",
    "Versicherungsnummer", "Mitgliedsnummer", "Marktlokation", "Messlokation", "Referenz",
    "Aktenzeichen",
})


@dataclass(frozen=True)
class Kennung:
    """Eine Kennung aus einem Dokument, z.B. ``Kennung("226541", "Zählernummer")``."""

    wert: str
    art: str = "Kennung"

    def __str__(self) -> str:
        return f"{self.wert} ({self.art})"

    @property
    def benannt(self) -> bool:
        """True fuer Vertrags-, Zaehler-, Kundennummer usw. (siehe ``BENANNTE_ARTEN``)."""
        return self.art in BENANNTE_ARTEN


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
        scan_ordner: Scan-Eingang; liegt das Dokument dort, hat es noch
            keinen Ablageort (sonst haelt die KI den Eingang fuer das Ziel).
    """

    pfad: Path
    text: str = ""
    metadaten: dict = field(default_factory=dict)
    sortier_vorschlaege: list[str] = field(default_factory=list)
    wurzeln: list[Path] = field(default_factory=list)
    scan_ordner: Optional[Path] = None

    def __post_init__(self) -> None:
        self.pfad = Path(self.pfad)
        if self.scan_ordner:
            self.scan_ordner = Path(self.scan_ordner)

    def im_scan_ordner(self) -> bool:
        """True, wenn das Dokument (noch) im Scan-Eingang oder einem Unterordner davon liegt."""
        if not self.scan_ordner:
            return False
        try:
            Path(self.pfad).resolve().relative_to(Path(self.scan_ordner).resolve())
            return True
        except (ValueError, OSError):
            return False


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
    # Backslashes selbst ersetzen: unter macOS/Linux laesst Path.as_posix()
    # Windows-Trenner stehen (CI-Fehler auf macOS)
    return (str(a).replace("\\", "/").casefold()
            == str(b).replace("\\", "/").casefold())


def selber_ordner(a, b) -> bool:
    """Wie :func:`gleicher_pfad`, erkennt aber auch denselben Ordner unter zwei Pfaden.

    Beispiel: ``C:\\Users\\x\\Documents`` ist eine Junction auf den OneDrive-Ordner
    auf ``E:``. Der Vergleich ueber das Dateisystem (``samefile``) erkennt beide als
    denselben Ordner; fehlt einer der Pfade, zaehlt nur der Textvergleich.
    """
    if gleicher_pfad(a, b):
        return True
    if not a or not b:
        return False
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


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


# --------------------------------------------------------------------------- Kennungen

# Benannte Kennungen: "<Stamm>nummer", "<Stamm>-Nr.", "<Stamm> ID" ... gefolgt vom Wert.
# Die Reihenfolge entscheidet bei mehrdeutigen Staemmen (zuerst passt).
_KENNUNG_ARTEN: tuple[tuple[str, str], ...] = (
    (r"vertrags?", "Vertragsnummer"),
    (r"kunden", "Kundennummer"),
    (r"(?:gas|strom|wasser|w(?:ä|ae|a)rme|heiz)?z(?:ä|ae|a)hler", "Zählernummer"),
    (r"rechnungs?|belegs?|invoice", "Rechnungsnummer"),
    (r"auftrags?|bestell", "Auftragsnummer"),
    (r"versicherungs?(?:schein)?|policen?", "Versicherungsnummer"),
    (r"mitglieds?", "Mitgliedsnummer"),
    (r"marktlokations?", "Marktlokation"),
    (r"messlokations?", "Messlokation"),
)
_STAMM_RE = "|".join(f"(?:{stamm})" for stamm, _art in _KENNUNG_ARTEN)
# Kennungen ohne "-nummer": Mandatsreferenz, Aktenzeichen, MaLo, MeLo, IBAN
_BARE_ARTEN: dict[str, str] = {
    "mandatsreferenz": "Referenz", "referenz": "Referenz", "referenznummer": "Referenz",
    "aktenzeichen": "Aktenzeichen", "az": "Aktenzeichen",
    "malo": "Marktlokation", "melo": "Messlokation", "iban": "IBAN",
}
_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"(?P<stamm>" + _STAMM_RE + r")[\s\-]?(?:nummer|nr\.?|no\.?|id)"
    r"|(?P<bare>mandatsreferenz|referenz(?:nummer)?|aktenzeichen|az\.|malo|melo|iban)"
    r")\s*[:.]?\s*(?P<wert>[A-Za-z0-9][A-Za-z0-9\-/]{3,})",
    re.IGNORECASE,
)
# IBAN auch ohne Beschriftung, mit oder ohne Leerzeichen zwischen den Vierergruppen
_IBAN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?)(?![A-Za-z0-9])")
# Unbeschriftete Kennungen: Woerter mit mindestens fuenf Ziffern
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/]*")
_DATUM_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{4}/\d{4}|\d{1,2}/\d{4})$")
# "Tel. 0251 123456": zwischen Beschriftung und Zahl duerfen Vorwahl und Trennzeichen stehen
_TELEFON_VOR_RE = re.compile(r"(?:tel|telefon|fax|mobil|handy|phone|hotline)\.?\s*:?\s*[\d\s/()+\-]*$", re.IGNORECASE)
# Angaben des Absenders, die auf jedem seiner Schreiben stehen (Handelsregister,
# USt-IdNr., Glaeubiger-ID, Steuernummer, Bankverbindung): sie verbinden nicht
# das einzelne Dokument, sondern alle Dokumente der Firma
_ABSENDER_VOR_RE = re.compile(
    r"(?:hrb|hra|handelsregister|registernummer|registergericht|amtsgericht|ust\.?[\s\-]?id(?:nr)?\.?|"
    r"umsatzsteuer[\s\-]?id(?:entifikationsnummer)?|uid|gl(?:ä|ae)ubiger[\s\-]?id(?:entifikationsnummer)?|"
    r"steuernummer|steuer[\s\-]?nr\.?|st\.?[\s\-]?nr\.?|bic|blz|bankleitzahl|swift)\s*[:.]?\s*[A-Za-z]{0,3}\s*$",
    re.IGNORECASE,
)
_EINHEIT_NACH_RE = re.compile(r"^\s*(?:kwh|m³|m3|cbm|€|eur|euro|%|cent|ct|kw|l|kg|km)\b", re.IGNORECASE)
_PLZ_NACH_RE = re.compile(r"^\s+[A-ZÄÖÜ][a-zäöüß]")


def _art_fuer_stamm(stamm: str) -> str:
    s = stamm.lower()
    for muster, art in _KENNUNG_ARTEN:
        if re.fullmatch(muster, s, re.IGNORECASE):
            return art
    return "Kennung"


def _plausibel(wert: str) -> bool:
    """Mindestens drei Ziffern, kein Datum, keine reine Buchstabenfolge."""
    ziffern = sum(c.isdigit() for c in wert)
    if ziffern < 3 or len(wert) < 4:
        return False
    if _DATUM_RE.match(wert):
        return False
    return True


def kennungen_aus_text(text: str, max_anzahl: int = MAX_KENNUNGEN) -> list[Kennung]:
    """Kennungen eines Dokuments, benannte zuerst, in Reihenfolge des Auftretens.

    Benannt: "Vertragsnummer G22504020299", "Zähler-Nr.: 226541",
    "Marktlokations ID 50941885277", "IBAN DE05 ...". Unbenannt: Woerter mit
    mindestens fuenf Ziffern, ausser Daten, Betraegen, Mengen mit Einheit,
    Telefonnummern, Postleitzahlen vor einem Ortsnamen und Absender-Angaben
    (Handelsregister, USt-IdNr., Glaeubiger-ID, Steuernummer, BIC).
    """
    text = text or ""
    if not text.strip():
        return []
    gefunden: list[Kennung] = []
    gesehen: set[str] = set()

    def merke(wert: str, art: str) -> None:
        wert = wert.strip().strip("-/")
        schluessel = re.sub(r"\s+", "", wert).casefold()
        if not wert or schluessel in gesehen:
            return
        gesehen.add(schluessel)
        gefunden.append(Kennung(wert, art))

    for m in _LABEL_RE.finditer(text):
        wert = m.group("wert")
        if not _plausibel(wert):
            continue
        if _ABSENDER_VOR_RE.search(text[max(0, m.start() - 40):m.start()]):
            continue  # z.B. "Gläubiger-ID" vor einer "Kundennummer" des Absenders
        if m.group("stamm"):
            art = _art_fuer_stamm(m.group("stamm"))
        else:
            art = _BARE_ARTEN.get(m.group("bare").lower().rstrip("."), "Kennung")
        if art == "IBAN":
            # IBAN mit Leerzeichen komplett nehmen (der Wert endet sonst an der ersten Luecke)
            iban = _IBAN_RE.match(text, m.start("wert"))
            if iban:
                wert = iban.group(1)
        merke(wert, art)

    for m in _IBAN_RE.finditer(text):
        wert = m.group(1)
        if len(re.sub(r"\s+", "", wert)) < 15:
            continue
        # Glaeubiger-IDs (DE34ZZZ...) und andere Absender-Angaben sehen aus wie IBANs
        if "ZZZ" in wert.upper() or _ABSENDER_VOR_RE.search(text[max(0, m.start() - 40):m.start()]):
            continue
        merke(wert, "IBAN")

    for m in _TOKEN_RE.finditer(text):
        wert = m.group(0)
        if sum(c.isdigit() for c in wert) < 5 or _DATUM_RE.match(wert):
            continue
        vorher = text[max(0, m.start() - 40):m.start()]
        nachher = text[m.end():m.end() + 12]
        if _TELEFON_VOR_RE.search(vorher) or _ABSENDER_VOR_RE.search(vorher):
            continue
        if _EINHEIT_NACH_RE.match(nachher):
            continue
        if nachher.startswith((",", ".")) and len(nachher) > 1 and nachher[1].isdigit():
            continue  # Teil eines Betrags oder Zaehlerstands wie 33.683,003
        if vorher.endswith((",", ".")) and vorher[-2:-1].isdigit():
            continue
        if wert.isdigit() and len(wert) == 5 and _PLZ_NACH_RE.match(nachher):
            continue  # Postleitzahl vor dem Ort
        merke(wert, "Kennung")

    return gefunden[:max_anzahl]


def kennungs_abfrage(wert: str) -> str:
    """Exakte FTS5-Phrase fuer eine Kennung: ``R26-3117753`` -> ``"R26 3117753"``.

    Der Tokenizer des Index trennt an Bindestrich und Schraegstrich; als
    Phrase treffen die Teile nur in dieser Reihenfolge. Eine IBAN mit
    Leerzeichen wird zusaetzlich in der zusammengeschriebenen Form gesucht.
    """
    teile = re.findall(r"[A-Za-z0-9]+", wert or "")
    if not teile:
        return ""
    phrase = '"' + " ".join(teile) + '"'
    if len(teile) > 1 and " " in (wert or "").strip():
        return f'{phrase} OR "{"".join(teile)}"'
    return phrase
