"""
Farben der Oberflaeche fuer das helle und das dunkle Farbschema (Issue #238).

Alle Farben der Oberflaeche stehen hier mit einem Namen und je einem Wert fuer
Hell und Dunkel. Stylesheets nennen die Farbe als ``$name``::

    stil(label, "color: $grau_66; font-size: 11px;")

``stil`` setzt das Stylesheet und merkt sich die Vorlage am Widget; beim
Wechsel des Farbschemas im laufenden Betrieb wird sie neu eingesetzt. Wo kein
Widget im Spiel ist (HTML-Text, selbst Gezeichnetes), liefern ``css`` (ganzer
Text mit ``$name``) und ``farbe`` (ein Wert) die Farbe des aktiven Schemas.

Die hellen Werte sind die bisherigen des Programms. Ein neuer Farbton kommt
als neue Zeile in ``FARBEN`` - nicht als fester Wert in ein Stylesheet
(``tests/test_farben.py`` prueft das).

GPL-3.0-or-later - Copyright (c) 2026
"""

import re

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

SYSTEM = "system"
HELL = "hell"
DUNKEL = "dunkel"
SCHEMATA = (SYSTEM, HELL, DUNKEL)
KONFIG_SCHLUESSEL = "farbschema"

# Name -> (hell, dunkel). Die Namen beschreiben das helle Aussehen; der dunkle
# Wert ist das Gegenstueck auf dunklem Grund (Text wird hell, Flaechen dunkel).
FARBEN: dict[str, tuple[str, str]] = {
    # --- Grautoene: Text (dunkel auf hell -> hell auf dunkel)
    "schwarz": ("black", "#f0f0f0"),
    "grau_20": ("#202020", "#e6e6e6"),
    "grau_22": ("#222", "#e4e4e4"),
    "grau_33": ("#333", "#dcdcdc"),
    "grau_44": ("#444", "#d0d0d0"),
    "grau_55": ("#555", "#c4c4c4"),
    "grau_5a": ("#5a5a5a", "#bebebe"),
    "grau_66": ("#666", "#b4b4b4"),
    "grau_77": ("#777", "#a8a8a8"),
    "grau_88": ("#888", "#9c9c9c"),
    "grau_99": ("#999", "#8c8c8c"),
    "grau_9e": ("#9e9e9e", "#858585"),
    # --- Grautoene: Raender und Flaechen
    "grau_7a": ("#7a7a7a", "#8a8a8a"),
    "grau_aa": ("#aaa", "#6a6a6a"),
    "grau_b5": ("#b5b5b5", "#5e5e5e"),
    "grau_bd": ("#bdbdbd", "#4a4a4a"),
    "grau_c0": ("#c0c0c0", "#505050"),
    "grau_cc": ("#ccc", "#505050"),
    "grau_dd": ("#ddd", "#484848"),
    "grau_e8": ("#e8e8e8", "#3a3a3a"),
    "grau_ec": ("#ececec", "#3c3c3c"),
    "grau_f0": ("#f0f0f0", "#353535"),
    "grau_f5": ("#f5f5f5", "#333333"),
    "weiss": ("white", "#262626"),
    # Weisse Schrift auf farbigem Knopf oder Etikett: bleibt weiss
    "weiss_schrift": ("white", "white"),
    # --- Blau: Auswahl, Verweise, "neu"
    "akzent": ("#0078d7", "#0078d7"),
    "akzent_rand": ("#005a9e", "#3d9be9"),
    "akzent_blass": ("#9dc5e8", "#3d5a73"),
    "auswahl_flaeche": ("#cce5ff", "#1d3f66"),
    "auswahl_rand": ("#0066cc", "#4da3ff"),
    "verweis": ("#0066cc", "#6cb2ff"),
    "blau_text": ("#1a5fb4", "#78b4f5"),
    "blau_flaeche": ("#e3f2fd", "#1c3247"),
    "blau_kraeftig": ("#2563eb", "#7aa5f7"),
    "kachel_hover_flaeche": ("#f0f7ff", "#2a3340"),
    "kachel_hover_rand": ("#99c2ff", "#3d6ea8"),
    "neu_blau": ("#1e6fd9", "#5aa2f5"),
    "neu_flaeche": ("#e7f1ff", "#1e2f47"),
    "neu_flaeche_hover": ("#d0e4ff", "#263b5a"),
    "ablegen_flaeche": ("#b8daff", "#1f4470"),
    "ablegen_rand": ("#007bff", "#4da3ff"),
    "zeile_markiert_flaeche": ("#d6e9ff", "#1d3f66"),
    "chat_frage_flaeche": ("#d6eaff", "#1f3d5c"),
    "bezug_flaeche": ("#e7f0fb", "#25344a"),
    "bezug_rand": ("#b6cdea", "#3f5878"),
    "muster_flaeche": ("#d6eaff", "#1f3d5c"),
    "muster_text": ("#143c78", "#a8cdf5"),
    "knopf_blau": ("#1565c0", "#1565c0"),
    "knopf_blau_hover": ("#0d47a1", "#1976d2"),
    "knopf_blau_hell": ("#1976d2", "#1976d2"),
    "knopf_blau_hell_hover": ("#1565c0", "#2286e6"),
    # Kacheln fuer Word/Excel/Text und Bilder: Flaeche, Rand, Hover-Flaeche, Hover-Rand
    "kachel_office_flaeche": ("#e3edfb", "#1f2c40"),
    "kachel_office_rand": ("#6a9be0", "#4f7fc4"),
    "kachel_office_hover": ("#d3e3f9", "#27374f"),
    "kachel_office_hover_rand": ("#4f86d6", "#6a9be0"),
    "kachel_bild_flaeche": ("#fde6f0", "#3d2230"),
    "kachel_bild_rand": ("#e58ab4", "#b0668a"),
    "kachel_bild_hover": ("#fbd5e6", "#4a2a3b"),
    "kachel_bild_hover_rand": ("#d96aa0", "#d96aa0"),
    # --- Gruen: KI-Vorschlag, Ziel, "in Ordnung"
    "gruen_flaeche": ("#e8f5e9", "#1e3323"),
    "gruen_rand": ("#a5d6a7", "#3f7a45"),
    "gruen_text": ("#1b5e20", "#a5d6a7"),
    "gruen_text_hell": ("#2e7d32", "#81c784"),
    "gruen_text_suche": ("#166534", "#86d39a"),
    "gruen_text_hinweis": ("#1a6b1a", "#7fd17f"),
    "gruen_status": ("green", "#5fd35f"),
    "ki_flaeche": ("#e6f4e6", "#1f3a24"),
    "ki_rand": ("#7cc47f", "#4c9a52"),
    "ki_hover_flaeche": ("#d5ecd6", "#284a2e"),
    "ki_hover_rand": ("#5cb860", "#5cb860"),
    "zeile_ziel_flaeche": ("#d9f2d9", "#214227"),
    "zeile_ziel_rand": ("#4caf50", "#4caf50"),
    "vorschlag_flaeche": ("#d4edda", "#1f3d28"),
    "vorschlag_flaeche_hover": ("#c3e6cb", "#285034"),
    "vorschlag_gruen": ("#28a745", "#4cc76a"),
    "baum_treffer_flaeche": ("#90EE90", "#2e6b2e"),
    "baum_ziel_flaeche": ("#00ff00", "#1f7a1f"),
    "liste_ok_flaeche": ("#00ff00", "#1f5f1f"),
    "liste_ok_text": ("#008000", "#b9f5b9"),
    "liste_warn_flaeche": ("#ffff00", "#6b6300"),
    "knopf_gruen": ("#2e7d32", "#2e7d32"),
    "knopf_gruen_hover": ("#1b5e20", "#388e3c"),
    # --- Gelb und Orange: Ordner, Hinweise, Warnungen
    "gelb_flaeche": ("#fff3cd", "#4a3d14"),
    "gelb_flaeche_hover": ("#ffecb3", "#5a4a18"),
    "gelb_flaeche_blass": ("#fffef5", "#26241c"),
    "gelb_rand": ("#daa520", "#b8891a"),
    "gelb_rand_kraeftig": ("#ffc107", "#e0a800"),
    "gelb_banner": ("rgba(255, 243, 205, 230)", "rgba(74, 61, 20, 230)"),
    "gelb_banner_text": ("#6b4e00", "#f0d98c"),
    "gold_text": ("#b8860b", "#e0b84d"),
    "ordner_flaeche": ("#fff8e7", "#2f2a1c"),
    "zeile_flaeche": ("#fbf8ec", "#2d2a20"),
    "zeile_rand": ("#e3dcc2", "#575038"),
    "favorit_aktuell_flaeche": ("#ffe9a8", "#6b5514"),
    "hinweis_flaeche": ("#fff8e1", "#3a3218"),
    "hinweis_rand": ("#f0d58c", "#7a6520"),
    "hinweis_rand_kraeftig": ("#ffe082", "#8a6d1a"),
    "warnung_rand": ("#ffe69c", "#8a6d1a"),
    "warnung_text": ("#664d03", "#f0d98c"),
    "treffer_flaeche": ("#fff0a0", "#806a00"),
    "treffer_text": ("#000000", "#ffffff"),
    "braun_text": ("#7a4a00", "#e6b566"),
    "orange_text": ("#b35c00", "#f0a04d"),
    "orange_text_hell": ("#d17a00", "#f0a030"),
    "orange_text_kraeftig": ("#e65100", "#ff9d5c"),
    "rost_text": ("#9a3412", "#f09a7a"),
    "stapel_flaeche": ("#fff3e0", "#3d2e1a"),
    "stapel_rand": ("#e67e22", "#e67e22"),
    "orange_rand": ("#ffcc80", "#8a5e1f"),
    # --- Rot: Fehler
    "rot": ("#d32f2f", "#ef6b6b"),
    "rot_text": ("#b71c1c", "#f28b82"),
    "rot_text_status": ("#c0392b", "#f0705f"),
    "rot_text_kraeftig": ("#cc0000", "#ff6b6b"),
    "rot_text_dunkel": ("#8a1f1f", "#f5a3a3"),
    "rot_flaeche": ("#ffebee", "#3d1f22"),
    "rot_flaeche_feld": ("#fdecea", "#3d2220"),
    "rot_flaeche_chat": ("#ffd6d6", "#4a2222"),
    "rot_flaeche_kachel": ("#ffe0e0", "#452020"),
    "rot_rand": ("#ef9a9a", "#8a3a3a"),
    "rot_rand_kachel": ("#ffaaaa", "#8a3a3a"),
    # --- Lila: KI-Knopf, Quelle "KI"
    "lila_flaeche": ("#f3e5f5", "#33203a"),
    "lila_text": ("#6a1b9a", "#ce93d8"),
    "knopf_lila": ("#7b1fa2", "#7b1fa2"),
    "knopf_lila_hover": ("#6a1b9a", "#9c27b0"),
}

# Grundfarben der Bedienelemente (QPalette). Hell: die bisherige Palette aus main.py.
_PALETTE_HELL = {
    "Window": "#f0f0f0", "WindowText": "#000000", "Base": "#ffffff", "AlternateBase": "#f5f5f5",
    "ToolTipBase": "#ffffdc", "ToolTipText": "#000000", "Text": "#000000", "Button": "#f0f0f0",
    "ButtonText": "#000000", "BrightText": "#ff0000", "Link": "#0066cc", "Highlight": "#0078d7",
    "HighlightedText": "#ffffff", "PlaceholderText": "#787878",
}
_PALETTE_DUNKEL = {
    "Window": "#2b2b2b", "WindowText": "#e6e6e6", "Base": "#1e1e1e", "AlternateBase": "#262626",
    "ToolTipBase": "#3c3c3c", "ToolTipText": "#f0f0f0", "Text": "#e6e6e6", "Button": "#3a3a3a",
    "ButtonText": "#e6e6e6", "BrightText": "#ff6b6b", "Link": "#6cb2ff", "Highlight": "#2f7fd6",
    "HighlightedText": "#ffffff", "PlaceholderText": "#8c8c8c", "LinkVisited": "#b39ddb", "Accent": "#2f7fd6",
    "Light": "#4a4a4a", "Midlight": "#404040", "Mid": "#555555", "Dark": "#1a1a1a", "Shadow": "#000000",
}
_PALETTE_DUNKEL_AUS = {
    "WindowText": "#7a7a7a", "Text": "#7a7a7a", "ButtonText": "#7a7a7a",
    "Highlight": "#4a4a4a", "HighlightedText": "#9a9a9a",
}

_PLATZHALTER = re.compile(r"\$([a-z][a-z0-9_]*)")
_VORLAGE = "_pdfsm_stil"  # dynamische Eigenschaft am Widget: Stylesheet-Vorlage mit $name


class _Melder(QObject):
    geaendert = pyqtSignal()


# Meldet einen Wechsel des Farbschemas im laufenden Betrieb (nach dem Umfaerben
# der Stylesheets). Fuer Inhalte, die ihre Farben selbst einsetzen (HTML-Texte).
melder = _Melder()

_dunkel = False
_wahl = HELL
_app_stil = None  # Fabrik fuer das Stylesheet der Anwendung (Checkboxen)
_verbunden = False


def schema(wert) -> str:
    """Gespeicherter Wert -> gueltiges Farbschema ("system" bei Unbekanntem)."""
    wert = str(wert or "").strip().lower()
    return wert if wert in SCHEMATA else SYSTEM


def ist_dunkel() -> bool:
    """True, wenn gerade das dunkle Farbschema gilt."""
    return _dunkel


def farbe(name: str) -> str:
    """Farbwert des aktiven Farbschemas (KeyError bei unbekanntem Namen).

    Auch ``farbe("$name")`` ist erlaubt: So kann eine Konstante, die in Stylesheets
    als ``$name`` steht, auch fuer selbst Gezeichnetes dienen.
    """
    return FARBEN[name.lstrip("$")][1 if _dunkel else 0]


def qfarbe(name: str) -> QColor:
    """Wie farbe(), als QColor (fuer selbst Gezeichnetes und Listeneintraege)."""
    return QColor(farbe(name))


def css(text: str) -> str:
    """Setzt in einem Stylesheet- oder HTML-Text alle ``$name`` durch die Farbwerte.

    Unbekannte Namen bleiben stehen (ein Dateiname darf ein ``$`` enthalten); dass alle
    Namen im Quelltext stimmen, prueft tests/test_farben_238_gui.py. Trotzdem nur eigene
    Texte hindurchschicken, nie Dateinamen oder Dokumentinhalt.
    """
    return _css(text, _dunkel)


def _css(text: str, dunkel: bool) -> str:
    return _PLATZHALTER.sub(
        lambda m: FARBEN[m.group(1)][1 if dunkel else 0] if m.group(1) in FARBEN else m.group(0), text)


def stil(widget, text: str) -> None:
    """``widget.setStyleSheet`` mit ``$name``-Farben; folgt einem spaeteren Wechsel des Farbschemas."""
    widget.setProperty(_VORLAGE, text if "$" in text else None)
    widget.setStyleSheet(css(text))


def _palette(app) -> QPalette:
    # Zurueck auf die Grundpalette von Stil und System (eine leere Palette setzt die
    # eigene zurueck); darauf die eigenen Rollen. So haengt das Ergebnis nicht davon ab,
    # welches Farbschema vorher galt.
    app.setPalette(QPalette())
    palette = QPalette(app.palette())
    for rolle, wert in (_PALETTE_DUNKEL if _dunkel else _PALETTE_HELL).items():
        if hasattr(QPalette.ColorRole, rolle):  # Accent gibt es erst ab Qt 6.6
            palette.setColor(getattr(QPalette.ColorRole, rolle), QColor(wert))
    if _dunkel:
        for rolle, wert in _PALETTE_DUNKEL_AUS.items():
            palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, rolle), QColor(wert))
    return palette


def _system_dunkel(app) -> bool:
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return False


def anwenden(wahl: str, app=None) -> None:
    """Stellt die Anwendung auf "system", "hell" oder "dunkel" und faerbt offene Fenster um."""
    global _dunkel, _wahl
    if app is None:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
    _wahl = schema(wahl)
    hinweise = app.styleHints()
    # Qt sagen, welches Schema gilt: faerbt Titelleiste (Windows/macOS) und
    # Standarddialoge passend. Bei "system" die Vorgabe zuruecknehmen, damit
    # colorScheme() wieder die Einstellung des Betriebssystems meldet.
    try:
        if _wahl == SYSTEM:
            hinweise.unsetColorScheme()
        else:
            hinweise.setColorScheme(Qt.ColorScheme.Dark if _wahl == DUNKEL else Qt.ColorScheme.Light)
    except AttributeError:  # Qt < 6.8
        pass
    vorher = _dunkel
    _dunkel = _system_dunkel(app) if _wahl == SYSTEM else _wahl == DUNKEL
    _umfaerben(app, vorher)


def _umfaerben(app, vorher: bool) -> None:
    app.setPalette(_palette(app))
    if _app_stil is not None:
        app.setStyleSheet(css(_app_stil()))
    if vorher == _dunkel:
        return
    for widget in app.allWidgets():
        vorlage = widget.property(_VORLAGE)
        if not vorlage:
            continue
        if widget.styleSheet() != _css(vorlage, vorher):
            # inzwischen mit setStyleSheet() ueberschrieben: die Vorlage gilt nicht mehr
            widget.setProperty(_VORLAGE, None)
            continue
        widget.setStyleSheet(css(vorlage))
    melder.geaendert.emit()


def _system_geaendert(_schema=None) -> None:
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None or _wahl != SYSTEM or _system_dunkel(app) == _dunkel:
        return
    logger.info("Farbschema des Systems geaendert: " + ("dunkel" if _system_dunkel(app) else "hell"))
    anwenden(SYSTEM, app)


def einrichten(app, config, app_stil=None) -> None:
    """Beim Programmstart: Fusion-Stil, Palette nach Einstellung, dem System im Betrieb folgen.

    ``app_stil`` liefert das Stylesheet der Anwendung (mit ``$name``-Farben).
    """
    global _app_stil, _verbunden
    _app_stil = app_stil
    # Fusion sorgt fuer plattformuebergreifend gleiches Verhalten; die Palette
    # wird ausdruecklich gesetzt, damit ein dunkles System die Lesbarkeit nicht
    # zerschiesst (Issue #1).
    app.setStyle("Fusion")
    anwenden(schema(config.get(KONFIG_SCHLUESSEL, SYSTEM)), app)
    if not _verbunden:
        try:
            app.styleHints().colorSchemeChanged.connect(_system_geaendert)
            _verbunden = True
        except AttributeError:  # Qt < 6.5
            pass
