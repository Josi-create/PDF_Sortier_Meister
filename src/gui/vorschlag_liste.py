"""
Kompakte Ordnervorschlaege (rechte Spalte "Vorgeschlagene Ziele").

* ``VorschlagZeile``: ein FolderWidget als schlanke Zeile (Symbol, voller Pfad auf
  zwei Zeilen, Prozentzahl rechts). Unten steht das Ende des Pfads mit dem Zielordner
  fett, oben grau der Anfang (``zeilen_aufteilen``). Rechts hat Vorrang: der Zielordner
  ist immer zu sehen, dann der Ordner darueber usw.; was oben nicht passt, faellt von
  links in ganzen Ordnern weg (``pfad_kuerzen``). Drop, Menue, Regenbogen und Signale
  erbt sie unveraendert von FolderWidget.
* ``SpaltenLayout``: verteilt die Zeilen zeilenweise auf 1 bis 3 Spalten, je
  nach verfuegbarer Breite. Die Mindestbreite bleibt klein (keine Rueckkopplung
  auf den Splitter).
* ``VorschlagListe``: Scrollbereich darum; scrollt allein stehend erst ab ``MAX_ZEILEN`` Reihen.
* ``VorschlagTeiler``: senkrechter Teiler aus Liste und Ordnerbaum (Issue #268). Die Liste
  ist so hoch, dass alle Vorschlaege ohne Scrollen Platz haben; die Trennlinie laesst sich
  ziehen, ein Doppelklick stellt die passende Hoehe wieder ein. Beim Loslassen rastet sie auf ganzen
  Reihen ein oder knapp unter der letzten Reihe (Issue #341).
"""

import html
from typing import Callable

from PyQt6.QtCore import QEvent, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QScrollArea, QSizePolicy, QSplitter, QSplitterHandle,
    QVBoxLayout, QWidget,
)

from src.gui.einrasten import LoslassMelder, reihen_hoehe
from src.gui.farben import css, melder, stil
from src.gui.folder_widget import FolderWidget
from src.i18n import tr

ZEILEN_HOEHE = 44
ZEILEN_MIN_BREITE = 210  # darunter wird eine Spalte weniger genommen
MAX_SPALTEN = 3
ABSTAND = 6
MAX_ZEILEN = 3  # sichtbare Reihen, danach vertikal scrollen
AUSLASSUNG = "…"


def pfad_kuerzen(pfad: str, messen: Callable[[str], int], breite: int) -> str:
    r"""Kuerzt einen Pfad von links in ganzen Ordnern, rechts hat Vorrang.

    ``C:\A\B\C\E`` wird je nach Breite zu ``…\B\C\E``, ``…\C\E`` oder ``…\E``.
    Passt selbst der letzte Ordner nicht, wird er links gekuerzt (Ende bleibt lesbar).
    ``messen`` liefert die Textbreite in Pixeln (QFontMetrics.horizontalAdvance).
    """
    if not pfad or messen(pfad) <= breite:
        return pfad
    sep = "\\" if "\\" in pfad else "/"
    teile = [t for t in pfad.replace("/", sep).split(sep) if t]
    for anzahl in range(len(teile) - 1, 0, -1):
        kandidat = AUSLASSUNG + sep + sep.join(teile[-anzahl:])
        if messen(kandidat) <= breite:
            return kandidat
    letzter = teile[-1] if teile else pfad
    for start in range(1, len(letzter)):
        kandidat = AUSLASSUNG + letzter[start:]
        if messen(kandidat) <= breite:
            return kandidat
    return AUSLASSUNG


def _rechts_kuerzen(text: str, messen: Callable[[str], int], breite: int) -> str:
    """Kuerzt ``text`` rechts mit "…", bis er in ``breite`` passt."""
    if messen(text) <= breite:
        return text
    for ende in range(len(text) - 1, 0, -1):
        kandidat = text[:ende] + AUSLASSUNG
        if messen(kandidat) <= breite:
            return kandidat
    return AUSLASSUNG


def zeilen_aufteilen(
    elternpfad: str,
    name: str,
    breite: int,
    messen_oben: Callable[[str], int],
    messen_unten: Callable[[str], int],
    messen_fett: Callable[[str], int],
    praefix: str = "",
) -> tuple[str, str, str]:
    r"""Verteilt den Pfad eines Zielordners auf zwei Zeilen (Live-Test 08.11.2026).

    Unten stehen so viele Ordner vom Ende des Elternpfads, wie neben dem fetten
    ``\Ziel`` Platz haben, oben grau der Rest bis zum Laufwerk. Passt oben nicht alles,
    fallen dort ganze Ordner von links weg:

        oben:  E:\Users\johan_000\OneDrive\
        unten: \1PaperPort14\Kinder          (\Kinder fett)

    Rueckgabe: ``(oben, unten_normal, unten_fett)``. ``breite <= 1`` (Geometrie noch
    unbekannt): alles unten, ungekuerzt.
    """
    sep = "\\" if "\\" in elternpfad else "/"
    anfang_len = len(elternpfad) - len(elternpfad.lstrip("\\/"))
    anfang = elternpfad[:anfang_len].replace("/", sep)  # "/" bei Unix, "\\" bei UNC-Pfaden
    teile = [t for t in elternpfad.replace("/", sep).split(sep) if t]
    fett = sep + name if teile else name
    if breite <= 1:
        return "", praefix + anfang + sep.join(teile), fett

    platz = breite - messen_unten(praefix)
    if messen_fett(fett) > platz:  # schon das Ziel passt nicht: Ziel kuerzen, Pfad oben
        unten_k = 0
        fett = _rechts_kuerzen(fett, messen_fett, max(platz, 0))
    else:
        unten_k = 0
        for k in range(len(teile), 0, -1):
            schwanz = anfang + sep.join(teile) if k == len(teile) else sep + sep.join(teile[-k:])
            if messen_unten(schwanz) + messen_fett(fett) <= platz:
                unten_k = k
                break
    if unten_k == len(teile):
        return "", praefix + anfang + sep.join(teile), fett
    schwanz = sep + sep.join(teile[-unten_k:]) if unten_k else ""
    rest = anfang + sep.join(teile[:len(teile) - unten_k])
    oben = pfad_kuerzen(rest, lambda s: messen_oben(s + sep), breite) + sep
    return oben, praefix + schwanz, fett


class VorschlagZeile(FolderWidget):
    """Kompakte Vorschlagszeile: oben der Anfang des Pfads (path_label), unten das Ende
    mit dem Zielordner fett (name_label, Rich Text)."""

    FARBE_PFAD = "$grau_66"
    FARBE_NEU = "$neu_blau"

    def __init__(self, folder_path, parent=None):
        self._name_voll = ""
        self._pfad_voll = ""
        self._praefix = ""
        self._zeilen = ("", "", "")  # (oben, unten normal, unten fett) - fuer Tests
        self._geometrie_bekannt = False
        super().__init__(folder_path, 0, parent)
        melder.geaendert.connect(self._kuerzen)  # die untere Zeile traegt ihre Farben im Text

    def setup_ui(self):
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        self.setFixedHeight(ZEILEN_HOEHE)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._update_style()
        self.setToolTip(tr("{folder_path}\nAnklicken verschiebt die ausgewählte PDF hierher.").format(folder_path=self.folder_path))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self.icon_label = QLabel("📁")
        self.icon_label.setStyleSheet("font-size: 16px; background: transparent; border: none;")
        layout.addWidget(self.icon_label)

        textspalte = QVBoxLayout()
        textspalte.setSpacing(0)
        textspalte.setContentsMargins(0, 0, 0, 0)
        self.path_label = self._label(bold=False, px=10, farbe=self.FARBE_PFAD)  # oben: Anfang
        self.name_label = self._label(bold=False, px=12)  # unten: Ende, Ziel fett
        self.name_label.setTextFormat(Qt.TextFormat.RichText)
        textspalte.addWidget(self.path_label)
        textspalte.addWidget(self.name_label)
        layout.addLayout(textspalte, 1)

        self.count_label = QLabel()
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        stil(self.count_label, "font-size: 11px; color: $grau_66; background: transparent; border: none;")
        layout.addWidget(self.count_label)

        self.set_anzeige(self.folder_path.name, "")

    @staticmethod
    def _label(bold: bool, px: int, farbe: str = "$grau_22") -> QLabel:
        lab = QLabel()
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        stil(lab, f"color: {farbe}; background: transparent; border: none;")
        font = QFont(lab.font())
        font.setPixelSize(px)
        font.setBold(bold)
        lab.setFont(font)
        return lab

    def _update_count_label(self):
        pass  # Prozentzahl setzt das Hauptfenster

    def set_anzeige(self, name: str, pfad: str, praefix: str = ""):
        """Setzt Ordnername, Elternpfad (ungekuerzt) und ein Praefix vor der unteren Zeile
        (z. B. "➕ neu: "); die Aufteilung auf zwei Zeilen passiert nach Breite."""
        self._name_voll = name
        self._pfad_voll = pfad
        self._praefix = praefix
        self._kuerzen()

    def _kuerzen(self):
        breite = self.name_label.width() if self._geometrie_bekannt else 0
        breite = max(breite - 4, 0) if breite > 1 else 0  # etwas Luft fuer den Rich-Text-Rand
        fett_font = QFont(self.name_label.font())
        fett_font.setBold(True)
        oben, unten, fett = zeilen_aufteilen(
            self._pfad_voll, self._name_voll, breite,
            QFontMetrics(self.path_label.font()).horizontalAdvance,
            QFontMetrics(self.name_label.font()).horizontalAdvance,
            QFontMetrics(fett_font).horizontalAdvance,
            self._praefix,
        )
        self._zeilen = (oben, unten, fett)
        self.path_label.setText(oben)
        self.path_label.setVisible(bool(oben))
        praefix = self._praefix if unten.startswith(self._praefix) else ""
        rest = unten[len(praefix):]
        teile = []
        if praefix:
            teile.append(f'<span style="color:{css(self.FARBE_NEU)}">{html.escape(praefix)}</span>')
        if rest:
            teile.append(f'<span style="color:{css(self.FARBE_PFAD)}">{html.escape(rest)}</span>')
        teile.append(f"<b>{html.escape(fett)}</b>")
        self.name_label.setText('<span style="white-space:pre">{}</span>'.format("".join(teile)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._geometrie_bekannt = True
        self._kuerzen()

    def showEvent(self, event):
        super().showEvent(event)
        self._kuerzen()


class SpaltenLayout(QLayout):
    """Zeilenweise Verteilung auf 1..MAX_SPALTEN gleich breite Spalten."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def _sichtbar(self):
        return [i for i in self._items if not i.isEmpty()]

    def spalten(self, breite: int) -> int:
        """Spaltenzahl fuer die Breite; andere Inhalte (Platzhalter) bekommen die ganze Breite."""
        items = self._sichtbar()
        if any(not isinstance(i.widget(), VorschlagZeile) for i in items):
            return 1
        return max(1, min(MAX_SPALTEN, (breite + ABSTAND) // (ZEILEN_MIN_BREITE + ABSTAND)))

    def _reihen_hoehen(self, spalten: int):
        items = self._sichtbar()
        hoehen = []
        for start in range(0, len(items), spalten):
            hoehen.append(max(i.sizeHint().height() for i in items[start:start + spalten]))
        return hoehen

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, breite):
        m = self.contentsMargins()
        innen = breite - m.left() - m.right()
        hoehen = self._reihen_hoehen(self.spalten(innen))
        gesamt = sum(hoehen) + ABSTAND * max(len(hoehen) - 1, 0)
        return gesamt + m.top() + m.bottom()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        n = self.spalten(r.width())
        zelle = (r.width() - ABSTAND * (n - 1)) // n
        items = self._sichtbar()
        y = r.top()
        for start in range(0, len(items), n):
            reihe = items[start:start + n]
            hoehe = max(i.sizeHint().height() for i in reihe)
            for k, item in enumerate(reihe):
                item.setGeometry(QRect(r.left() + k * (zelle + ABSTAND), y, zelle, hoehe))
            y += hoehe + ABSTAND

    def sizeHint(self):
        return QSize(ZEILEN_MIN_BREITE, self.heightForWidth(ZEILEN_MIN_BREITE))

    def minimumSize(self):
        # bewusst klein: der Inhalt darf die Splitter-Spalte nie aufweiten
        return QSize(60, 0)


class _Inhalt(QWidget):
    """Innenwidget; meldet Layout- und Groessenaenderungen an die Liste."""

    def __init__(self, liste):
        super().__init__()
        self._liste = liste

    def event(self, e):
        ergebnis = super().event(e)
        if e.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Resize):
            self._liste._hoehe_anpassen()
        return ergebnis


class VorschlagListe(QScrollArea):
    """Scrollbereich mit ``spalten`` (SpaltenLayout); Hoehe waechst bis MAX_ZEILEN Reihen.

    In einem ``VorschlagTeiler`` (``hoehe_fest = False``) bestimmt der Teiler die Hoehe;
    die Liste meldet dann nur noch, dass sich ihr Bedarf geaendert haben kann.
    """

    bedarf_geaendert = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hoehe_fest = True
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.inhalt = _Inhalt(self)
        # Nur dieses Widget: ein Stylesheet ohne Selektor erben auch die Tooltips
        # der Zeilen - transparent wird unter Windows zu schwarzen Tooltips
        self.inhalt.setObjectName("vorschlagInhalt")
        self.inhalt.setStyleSheet("QWidget#vorschlagInhalt { background: transparent; }")
        self.viewport().setAutoFillBackground(False)
        self.spalten = SpaltenLayout(self.inhalt)
        self.setWidget(self.inhalt)
        self._hoehe_anpassen()

    def bedarf(self) -> int:
        """Hoehe, bei der alle Zeilen ohne Scrollen Platz haben (ganze Breite, ohne Bildlaufleiste)."""
        return max(self.spalten.heightForWidth(max(self.width(), 1)), 1)

    def _hoehe_anpassen(self):
        if not self.hoehe_fest:
            self.bedarf_geaendert.emit()
            return
        breite = max(self.viewport().width(), 1)
        bedarf = self.spalten.heightForWidth(breite)
        deckel = MAX_ZEILEN * ZEILEN_HOEHE + (MAX_ZEILEN - 1) * ABSTAND
        ziel = max(min(bedarf, deckel), 1)
        if self.height() != ziel:
            self.setFixedHeight(ziel)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._hoehe_anpassen()


class _Griff(QSplitterHandle):
    """Trennlinie zum Ziehen; Doppelklick stellt die passende Hoehe ein."""

    def mouseDoubleClickEvent(self, event):
        self.splitter().automatisch()
        event.accept()

    def paintEvent(self, event):
        maler = QPainter(self)
        farbe = self.palette().windowText().color()  # in hellem wie dunklem Design sichtbar
        farbe.setAlpha(90)
        maler.setPen(farbe)
        y = self.height() // 2
        maler.drawLine(0, y, self.width(), y)


class VorschlagTeiler(QSplitter):
    """Vorschlagsliste oben, Ordnerbaum unten, dazwischen eine ziehbare Trennlinie (Issue #268).

    Ohne Eingriff ist die Liste genau so hoch wie ihr Inhalt (kein Scrollen); nur wenn dem
    Ordnerbaum sonst weniger als ``UNTEN_MIN`` bliebe, wird sie kleiner und scrollt. Zieht
    der Nutzer die Trennlinie, gilt seine Hoehe, bis er doppelt auf die Linie klickt. Beim
    Loslassen rastet sie ein (``einrasten``, Issue #341).
    """

    UNTEN_MIN = 120  # so viel bleibt dem Ordnerbaum mindestens

    def __init__(self, liste: VorschlagListe, unten: QWidget, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.liste = liste
        self._manuell = None  # vom Nutzer gezogene Hoehe der Liste
        self._gemerkt = None  # (Hoehe, (Fensterbreite, Fensterhoehe)) aus der letzten Sitzung
        self._stellt = False
        self._gezogen_seit_druck = False
        liste.hoehe_fest = False
        liste.setMinimumHeight(ZEILEN_HOEHE)
        liste.setMaximumHeight(16777215)
        liste.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        unten.setMinimumHeight(self.UNTEN_MIN)
        self.setHandleWidth(9)
        self.addWidget(liste)
        self.addWidget(unten)
        self.setChildrenCollapsible(False)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)
        self.handle(1).setToolTip(tr(
            "Ziehen ändert die Höhe der Vorschläge.\nDoppelklick: genau so hoch, dass alle Vorschläge Platz haben."
        ))
        # Verzoegert: beim Ziehen kommt die Meldung der Liste vor splitterMoved - sofort
        # angewandt, wuerde die Hoehe zurueckspringen, bevor _gezogen sie festhaelt
        liste.bedarf_geaendert.connect(self.anpassen, Qt.ConnectionType.QueuedConnection)
        self.splitterMoved.connect(self._gezogen)
        self._loslass_melder = LoslassMelder(self.handle(1), self.einrasten)

    def createHandle(self):
        return _Griff(self.orientation(), self)

    def _gezogen(self, *_):
        if self._stellt:
            return
        self._manuell = self.sizes()[0]
        self._gemerkt = None
        self._gezogen_seit_druck = True

    def einrasten(self):
        """Nach dem Loslassen (Issue #341): auf ganze Reihen, ab der letzten Reihe passend zum Inhalt.

        Wer bis unter die letzte Reihe zieht, will alle Vorschlaege sehen: dann gilt wieder die
        passende Hoehe (wie nach einem Doppelklick), ohne leeren Streifen darunter.
        """
        gezogen, self._gezogen_seit_druck = self._gezogen_seit_druck, False
        if not gezogen or self._manuell is None:
            return
        bedarf = self.liste.bedarf()
        hoechstens = sum(self.sizes()) - self.UNTEN_MIN
        ziel = reihen_hoehe(self._manuell, bedarf, ZEILEN_HOEHE, ABSTAND, hoechstens)
        if ziel >= bedarf:
            self.automatisch()
            return
        self._manuell = ziel
        self.anpassen()

    def automatisch(self):
        """Zurueck zur passenden Hoehe (Doppelklick auf die Trennlinie)."""
        self._manuell = None
        self._gemerkt = None
        self.anpassen()

    def manuelle_hoehe(self):
        return self._manuell

    def merken(self, hoehe, fenster) -> None:
        """Gezogene Hoehe der letzten Sitzung; gilt nur, wenn das Fenster wieder so gross ist."""
        try:
            hoehe, fenster = int(hoehe), (int(fenster[0]), int(fenster[1]))
        except (TypeError, ValueError, IndexError):
            return
        if hoehe > 0:
            self._gemerkt = (hoehe, fenster)
            self.anpassen()

    def gemerkt(self) -> tuple:
        """``(Hoehe, [Fensterbreite, Fensterhoehe])`` zum Speichern; ``(0, [])`` = passend zum Inhalt."""
        if self._manuell is not None:
            g = self.window().size()
            return self._manuell, [g.width(), g.height()]
        if self._gemerkt is not None:  # Fenster war diesmal anders gross: Merker behalten
            return self._gemerkt[0], list(self._gemerkt[1])
        return 0, []

    def anpassen(self):
        if self._stellt:
            return
        gesamt = sum(self.sizes())
        if gesamt <= 0:
            return
        if self._gemerkt is not None and self.isVisible():
            g = self.window().size()
            if (g.width(), g.height()) == self._gemerkt[1]:
                self._manuell, self._gemerkt = self._gemerkt[0], None
        bedarf = self.liste.bedarf()
        ziel = self._manuell if self._manuell is not None else bedarf
        ziel = max(min(ziel, gesamt - self.UNTEN_MIN), min(ZEILEN_HOEHE, gesamt))
        # Passt alles, gibt es keine Bildlaufleiste - sonst naehme sie Breite weg, eine Spalte
        # fiele weg und die Liste braeuchte doch wieder mehr Hoehe (bliebe haengen)
        leiste = Qt.ScrollBarPolicy.ScrollBarAlwaysOff if ziel >= bedarf else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        if self.liste.verticalScrollBarPolicy() != leiste:
            self.liste.setVerticalScrollBarPolicy(leiste)
        if self.sizes()[0] != ziel:
            self._stellt = True
            try:
                self.setSizes([ziel, gesamt - ziel])
            finally:
                self._stellt = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.anpassen()
