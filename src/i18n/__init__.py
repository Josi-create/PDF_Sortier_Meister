"""
Übersetzung der Oberfläche (Issue #118).

Die Texte stehen auf Deutsch im Code und laufen durch :func:`tr`. Mit Sprache
Deutsch gibt ``tr`` den Text unverändert zurück; für jede andere Sprache schlägt
es ihn in ``locale/<kürzel>.po`` nach (gettext-Format, lesbar mit Poedit oder
Weblate). Fehlt ein Eintrag, bleibt der deutsche Text stehen.

Eine weitere Sprache braucht nur eine weitere Datei ``locale/<kürzel>.po``;
sie erscheint dann von selbst in den Einstellungen.

Regel für die Sprachwahl (``config["language"]``):

- ``"auto"`` (Standard): Systemsprache Deutsch bleibt Deutsch, alles andere
  wird Englisch.
- ein Kürzel (``"de"``, ``"en"``, ...): genau diese Sprache.
- Die Umgebungsvariable ``PDFSM_LANGUAGE`` geht vor (Tests, Bildschirmfotos).

Die Sprache wird beim ersten ``tr``-Aufruf festgelegt und gilt bis zum
Programmende; ein Wechsel in den Einstellungen wirkt nach dem Neustart.

Das Modul braucht weder Qt noch andere Pakete, damit es auch im
Hintergrunddienst der Suche (``pdfsm-dienst``) läuft.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger("pdf_sortier_meister.i18n")

#: Name des Programms. Die einzige Stelle für eine Umbenennung in einer anderen
#: Sprache ist der Eintrag ``msgid "PDF Sortier Meister"`` in der jeweiligen
#: .po-Datei: ``tr`` setzt dessen Übersetzung in allen Texten dieser Sprache ein.
APP_NAME = "PDF Sortier Meister"

#: Sprache der Texte im Quellcode
SOURCE_LANGUAGE = "de"
#: Sprache für alle Systeme, die nicht deutsch eingestellt sind
FALLBACK_LANGUAGE = "en"
#: Wert der Einstellung für „nach Systemsprache“
AUTO = "auto"
#: Umgebungsvariable, die Einstellung und Systemsprache übersteuert
ENV_VAR = "PDFSM_LANGUAGE"

LOCALE_DIR = Path(__file__).resolve().parent / "locale"

_KONTEXT_TRENNER = "\x04"  # wie gettext: msgctxt + EOT + msgid

_language: str | None = None
_catalog: dict[str, str] = {}
_app_name: str = APP_NAME


# ---------------------------------------------------------------------------
# .po-Dateien lesen
# ---------------------------------------------------------------------------

def read_po(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Liest eine .po-Datei.

    Returns:
        ``(einträge, kopf)``: ``einträge`` bildet den deutschen Text (bei
        ``msgctxt``: ``kontext + "\\x04" + text``) auf die Übersetzung ab, leere
        Übersetzungen fehlen darin. ``kopf`` enthält die Felder des Kopfeintrags
        (``Language``, ``X-Language-Name``, ...).

    Mehrzahlformen (``msgid_plural``) werden nicht unterstützt und überlesen.
    """
    eintraege: dict[str, str] = {}
    kopf: dict[str, str] = {}
    felder: dict[str, str] = {}
    aktuell: str | None = None

    def abschliessen() -> None:
        if "msgid" in felder and "msgid_plural" not in felder:
            msgid, msgstr = felder["msgid"], felder.get("msgstr", "")
            if msgid == "" and "msgctxt" not in felder:
                for zeile in msgstr.split("\n"):
                    name, trenner, wert = zeile.partition(":")
                    if trenner:
                        kopf[name.strip()] = wert.strip()
            elif msgstr:
                if "msgctxt" in felder:
                    msgid = felder["msgctxt"] + _KONTEXT_TRENNER + msgid
                eintraege[msgid] = msgstr
        felder.clear()

    for roh in path.read_text(encoding="utf-8").splitlines():
        zeile = roh.strip()
        if not zeile:
            abschliessen()
            aktuell = None
            continue
        if zeile.startswith("#"):
            continue
        if zeile.startswith('"'):
            if aktuell is not None:
                felder[aktuell] += _po_text(zeile)
            continue
        wort, _, rest = zeile.partition(" ")
        if wort in ("msgctxt", "msgid", "msgid_plural", "msgstr"):
            if wort in ("msgctxt", "msgid") and "msgstr" in felder:
                abschliessen()  # neuer Eintrag ohne Leerzeile davor
            aktuell = wort
            felder[wort] = _po_text(rest)
        else:
            aktuell = None  # msgstr[0] usw.: Mehrzahlformen überlesen
    abschliessen()
    return eintraege, kopf


def _po_text(literal: str) -> str:
    """Wandelt ein .po-Zeichenkettenliteral ("...") in Text um."""
    literal = literal.strip()
    if len(literal) < 2 or not (literal.startswith('"') and literal.endswith('"')):
        return ""
    try:
        return ast.literal_eval(literal)
    except (ValueError, SyntaxError):
        return literal[1:-1]


def po_literal(text: str) -> str:
    """Schreibt Text als .po-Zeichenkettenliteral (Gegenstück zu ``_po_text``)."""
    ersetzt = (
        text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{ersetzt}"'


# ---------------------------------------------------------------------------
# Sprache bestimmen
# ---------------------------------------------------------------------------

def available_languages() -> list[tuple[str, str]]:
    """Wählbare Sprachen als ``(kürzel, anzeigename)``, Deutsch zuerst."""
    sprachen = [(SOURCE_LANGUAGE, "Deutsch")]
    try:
        dateien = sorted(LOCALE_DIR.glob("*.po"))
    except OSError:
        dateien = []
    for datei in dateien:
        kuerzel = datei.stem
        try:
            _, kopf = read_po(datei)
        except OSError:
            continue
        sprachen.append((kuerzel, kopf.get("X-Language-Name") or kuerzel))
    return sprachen


def system_language() -> str:
    """Sprache der Oberfläche des Betriebssystems als Kürzel (``"de"``, ``"en"``, ...).

    Leer, wenn sie sich nicht feststellen lässt.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            import locale

            kennung = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            name = locale.windows_locale.get(kennung, "")
            if name:
                return _kuerzel(name)
            # Unbekannte Kennung: die unteren 10 Bit sind die Hauptsprache (7 = Deutsch)
            if kennung & 0x3FF == 0x07:
                return "de"
        except Exception:  # noqa: BLE001 - nie am Start scheitern
            pass
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        wert = os.environ.get(variable, "")
        if wert and wert not in ("C", "POSIX"):
            return _kuerzel(wert.split(":")[0])
    if sys.platform == "darwin":
        # Aus Finder/launchd gestartet ist LANG nicht gesetzt
        try:
            import subprocess

            ausgabe = subprocess.run(
                ["defaults", "read", "-g", "AppleLocale"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if ausgabe:
                return _kuerzel(ausgabe)
        except Exception:  # noqa: BLE001
            pass
    return ""


def _kuerzel(name: str) -> str:
    """``de_DE.UTF-8`` / ``de-AT`` -> ``de``."""
    for trenner in ("_", "-", ".", "@"):
        name = name.split(trenner)[0]
    return name.strip().lower()


def resolve_language(setting: str | None, system: str | None = None) -> str:
    """Bestimmt die Sprache der Oberfläche aus Einstellung und Systemsprache.

    Args:
        setting: Wert aus der Konfiguration (``"auto"``, ``""``, ``"de"``, ``"en"``, ...)
        system: Systemsprache; ``None`` = selbst ermitteln
    """
    verfuegbar = {kuerzel for kuerzel, _ in available_languages()}
    wunsch = _kuerzel(setting or "")
    if wunsch and wunsch != AUTO:
        if wunsch in verfuegbar:
            return wunsch
        return FALLBACK_LANGUAGE if FALLBACK_LANGUAGE in verfuegbar else SOURCE_LANGUAGE
    if system is None:
        system = system_language()
    system = _kuerzel(system or "")
    if system == SOURCE_LANGUAGE:
        return SOURCE_LANGUAGE
    # Hier ließe sich später "system in verfuegbar -> system" ergänzen, sobald es
    # weitere Sprachen gibt. Bis dahin gilt die Regel aus Issue #118.
    return FALLBACK_LANGUAGE if FALLBACK_LANGUAGE in verfuegbar else SOURCE_LANGUAGE


def configured_language() -> str:
    """Der gespeicherte Wert der Einstellung (``"auto"``, ``"de"``, ``"en"``, ...).

    Liest ``config.json`` direkt statt über ``get_config()``: ``tr`` läuft schon
    beim Import der Fenster-Module, und zu diesem Zeitpunkt darf die
    Konfiguration noch nicht geöffnet sein (``main`` spielt vorher eine
    vorgemerkte Wiederherstellung ein, Tests verdrahten eine eigene).
    """
    try:
        import json

        from src.utils.platform_paths import get_app_data_dir

        datei = get_app_data_dir(create=False) / "config.json"
        if not datei.is_file():
            return AUTO
        with open(datei, encoding="utf-8") as f:
            wert = json.load(f).get("language", AUTO)
        return str(wert or AUTO)
    except Exception:  # noqa: BLE001 - defekte Konfiguration darf den Start nicht verhindern
        return AUTO


def _initialise() -> None:
    wunsch = os.environ.get(ENV_VAR, "").strip() or configured_language()
    set_language(resolve_language(wunsch))


def set_language(language: str) -> None:
    """Legt die Sprache fest und lädt ihre Übersetzungen.

    Wirkt auf alle späteren ``tr``-Aufrufe. Bereits aufgebaute Fenster ändern
    sich nicht, deshalb verlangt die Umschaltung in den Einstellungen einen Neustart.
    """
    global _language, _catalog, _app_name
    language = _kuerzel(language) or SOURCE_LANGUAGE
    katalog: dict[str, str] = {}
    if language != SOURCE_LANGUAGE:
        datei = LOCALE_DIR / f"{language}.po"
        try:
            katalog, _ = read_po(datei)
        except OSError as fehler:
            logger.warning("Übersetzung %s nicht lesbar: %s", datei, fehler)
            language = SOURCE_LANGUAGE
    _language = language
    _catalog = katalog
    _app_name = katalog.get(APP_NAME, APP_NAME)


def current_language() -> str:
    """Die Sprache der Oberfläche in diesem Programmlauf."""
    if _language is None:
        _initialise()
    return _language or SOURCE_LANGUAGE


def app_name() -> str:
    """Programmname in der Sprache der Oberfläche."""
    if _language is None:
        _initialise()
    return _app_name


# Texte der Browser-Oberflaeche (src/search/static/*.html): t("...") im Skript,
# data-t am Element (Text des Elements) und data-tp vor placeholder="...".
_HTML_MUSTER = (
    re.compile(r'(?<![\w$.])t\("((?:[^"\\]|\\.)*)"'),
    re.compile(r"\bdata-t>\s*([^<]+?)\s*<"),
    re.compile(r'\bdata-tp placeholder="([^"]*)"'),
)


def texte_in_html(html: str) -> list[str]:
    """Die übersetzbaren Texte einer HTML-Seite, in der Reihenfolge des Vorkommens."""
    funde: list[tuple[int, str]] = []
    for nummer, muster in enumerate(_HTML_MUSTER):
        for treffer in muster.finditer(html):
            text = treffer.group(1)
            if nummer == 0:
                text = text.replace('\\"', '"').replace("\\\\", "\\")
            funde.append((treffer.start(), text))
    ergebnis: list[str] = []
    for _, text in sorted(funde):
        if text not in ergebnis:
            ergebnis.append(text)
    return ergebnis


def translate(text: str) -> str:
    """Wie :func:`tr`, aber für Texte, die nicht als Literal im Python-Code stehen
    (Texte aus HTML-Seiten). Im Python-Code immer ``tr("...")`` verwenden."""
    return _uebersetze(text, None)


def tr(text: str, kontext: str | None = None) -> str:
    """Übersetzt einen Text der Oberfläche in die eingestellte Sprache.

    Args:
        text: der deutsche Text, als Zeichenkettenliteral (sonst findet ihn die
            Prüfung auf fehlende Übersetzungen nicht). Platzhalter in der Form
            ``"{anzahl} Dateien"`` schreiben und ``.format(...)`` auf das Ergebnis
            anwenden, keine f-Strings.
        kontext: unterscheidet gleiche deutsche Texte mit verschiedenen
            Übersetzungen (``msgctxt`` in der .po-Datei)
    """
    return _uebersetze(text, kontext)


def _uebersetze(text: str, kontext: str | None) -> str:
    if _language is None:
        _initialise()
    if _language == SOURCE_LANGUAGE:
        return text
    uebersetzt = None
    if kontext:
        uebersetzt = _catalog.get(kontext + _KONTEXT_TRENNER + text)
    if uebersetzt is None:
        uebersetzt = _catalog.get(text, text)
    if _app_name != APP_NAME and APP_NAME in uebersetzt:
        uebersetzt = uebersetzt.replace(APP_NAME, _app_name)
    return uebersetzt
