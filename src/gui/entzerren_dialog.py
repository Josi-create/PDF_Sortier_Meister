"""Fenster zum Entzerren fotografierter Dokumente von Hand (Issue #205).

Links das Foto mit vier ziehbaren Eckpunkten und dem verbindenden Viereck, rechts die
Vorschau des entzerrten Ergebnisses. Sie wird erst beim Loslassen einer Ecke neu berechnet -
waehrend des Ziehens wuerde die Rechnung die Maus ausbremsen. Die Ecken sind mit der
automatischen Erkennung vorbelegt. Ist das Blatt angeschnitten fotografiert, zeigt "Foto
verkleinern" einen Rand um das Foto, in den man die fehlende Ecke ziehen kann (die Verlaengerung
der beiden sichtbaren Kanten trifft sie recht genau); der fehlende Zipfel wird weiss. Bei
mehreren Bildern blaettert man mit "Zurueck" und "Weiter", jedes Bild hat eigene Ecken;
"Uebernehmen" gilt fuer alle Bilder des Fensters, die Tonwerte ebenso.

Die Ecken liegen in Pixeln des vollen Fotos (EXIF-ausgerichtet, wie ``bild_laden``); die Anzeige
arbeitet mit einer auf ``ARBEIT_PX`` verkleinerten Kopie.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.entzerren import (
    TONWERT_NAMEN,
    TONWERT_STANDARD,
    TONWERTE,
    Entzerrung,
    bild_laden,
    entzerrte_seite,
    standard_ecken,
)
from src.i18n import tr

ARBEIT_PX = 1600        # laengste Seite der Anzeigekopie des Fotos
VORSCHAU_PX = 900       # laengste Seite der Vorschau rechts
RAND_ANTEIL = 0.35      # "Foto verkleinern": Rand um das Foto (Anteil der laengeren Seite) fuer Ecken ausserhalb
ECKEN_RADIUS = 11       # Pixel am Bildschirm (unabhaengig vom Zoom)
FENSTER_ANTEIL = 0.92   # Anteil des verfuegbaren Bildschirms


def _qimage(bild) -> QImage:
    """PIL-Bild (RGB, L oder 1 bit) als QImage."""
    rgb = bild.convert("RGB")
    daten = rgb.tobytes()
    return QImage(daten, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888).copy()


class _Eckpunkt(QGraphicsEllipseItem):
    """Ziehbare Ecke; haelt sich im Bild (oder im Rand darum) und meldet jede Bewegung dem Fenster."""

    def __init__(self, nummer: int, fenster: "EntzerrenDialog"):
        r = ECKEN_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.nummer = nummer
        self._fenster = fenster
        self.setBrush(QBrush(QColor(255, 190, 0, 200)))
        self.setPen(QPen(QColor(20, 20, 20), 2))
        self.setZValue(10)
        self.setFlags(
            QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QGraphicsEllipseItem.GraphicsItemFlag.ItemIgnoresTransformations
        )
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip(("Oben links", "Oben rechts", "Unten rechts", "Unten links")[nummer])

    def itemChange(self, aenderung, wert):
        if aenderung == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionChange and self._fenster is not None:
            grenzen = self._fenster._grenzen()
            wert = QPointF(min(max(wert.x(), grenzen.left()), grenzen.right()),
                           min(max(wert.y(), grenzen.top()), grenzen.bottom()))
        ergebnis = super().itemChange(aenderung, wert)
        if aenderung == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionHasChanged and self._fenster is not None:
            self._fenster._ecke_bewegt(self.nummer)
        return ergebnis

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._fenster is not None:
            self._fenster._ecke_losgelassen()


class _FotoAnsicht(QGraphicsView):
    """Foto links; passt sich der Fenstergroesse an."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.scene() is not None and not self.scene().sceneRect().isEmpty():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class _VorschauFeld(QLabel):
    """Vorschau rechts; skaliert das Bild beim Verkleinern/Vergroessern mit."""

    def __init__(self):
        super().__init__(tr("Vorschau"))
        self._pixmap: Optional[QPixmap] = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet("QLabel { background-color: #e8e8e8; border: 1px solid #aaa; color: #444; }")

    def pixmap_setzen(self, pixmap: Optional[QPixmap]):
        self._pixmap = pixmap
        self._anpassen()

    def _anpassen(self):
        if self._pixmap is None or self._pixmap.isNull():
            self.setText(tr("Vorschau"))
            return
        self.setPixmap(self._pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._anpassen()


class _Eintrag:
    """Zustand eines Bildes im Fenster."""

    def __init__(self, pfad: Path, vorgabe: Optional[list]):
        self.pfad = pfad
        self.vorgabe = vorgabe          # Ecken der Erkennung (volles Foto) oder None
        self.klein = None               # PIL-Anzeigekopie (lazy)
        self.groesse = (0, 0)           # volles Foto (Breite, Hoehe)
        self.faktor = 1.0               # voll / klein
        self.ecken: list[tuple[float, float]] = []  # volles Foto
        self.fehler: Optional[str] = None
        self.automatisch: list[tuple[float, float]] = []  # Ruecksetzwert (volles Foto)

    def laden(self):
        if self.klein is not None or self.fehler:
            return
        try:
            bild = bild_laden(self.pfad)
        except Exception as e:  # noqa: BLE001 - das Bild bleibt im Fenster, mit Fehlertext
            self.fehler = str(e)
            return
        self.groesse = bild.size
        self.faktor = max(max(bild.size) / ARBEIT_PX, 1.0)
        if self.faktor > 1.0:
            from PIL import Image
            bild = bild.resize((round(bild.width / self.faktor), round(bild.height / self.faktor)),
                               Image.Resampling.LANCZOS)
        self.klein = bild
        # Die Erkennung darf eine Blattecke knapp ausserhalb des Fotos setzen (Blatt angeschnitten);
        # das Fenster zeigt dann von selbst den Rand um das Foto, damit der Anfasser greifbar ist
        self.automatisch = [(float(x), float(y)) for x, y in self.vorgabe] \
            if self.vorgabe else standard_ecken(*self.groesse)
        if not self.ecken:
            self.ecken = list(self.automatisch)

    def ausserhalb(self) -> bool:
        """True, wenn eine Ecke ausserhalb des Fotos liegt."""
        b, h = self.groesse
        return any(x < 0 or y < 0 or x > b or y > h for x, y in self.ecken)


class EntzerrenDialog(QDialog):
    """Ecken je Foto ziehen, Tonwerte waehlen; ``ergebnis()`` liefert ``{Bild: Entzerrung}``."""

    def __init__(self, pfade: list[Path], vorgaben: Optional[dict] = None, tonwerte: str = TONWERT_STANDARD,
                 parent: Optional[QWidget] = None, unsicher: Optional[set] = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Foto entzerren"))
        self.setModal(True)
        vorgaben = vorgaben or {}
        self._unsicher = set(unsicher or ())
        self._eintraege = [_Eintrag(Path(p), vorgaben.get(Path(p))) for p in pfade]
        self._aktuell = 0
        self._laedt = False  # Ecken werden gerade programmatisch gesetzt (keine Rueckmeldung)

        self._szene = QGraphicsScene(self)
        self._foto_item = QGraphicsPixmapItem()
        self._szene.addItem(self._foto_item)
        self._rand_item = QGraphicsRectItem()  # hellerer Rand um das Foto ("Foto verkleinern")
        self._rand_item.setPen(QPen(Qt.PenStyle.NoPen))
        self._rand_item.setBrush(QBrush(QColor(96, 96, 96)))
        self._rand_item.setZValue(-1)
        self._rand_item.setVisible(False)
        self._szene.addItem(self._rand_item)
        self._viereck = QGraphicsPolygonItem()
        self._viereck.setPen(QPen(QColor(255, 190, 0), 2, Qt.PenStyle.DashLine))
        self._viereck.setBrush(QBrush(QColor(255, 190, 0, 40)))
        self._viereck.setZValue(5)
        self._szene.addItem(self._viereck)
        self._punkte = [_Eckpunkt(i, self) for i in range(4)]
        for p in self._punkte:
            self._szene.addItem(p)

        self._ansicht = _FotoAnsicht(self._szene)
        self._ansicht.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._ansicht.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._ansicht.setBackgroundBrush(QBrush(QColor(60, 60, 60)))
        self._vorschau = _VorschauFeld()

        self._kopf = QLabel()
        self._kopf.setStyleSheet("font-weight: bold;")
        self._hinweis = QLabel(
            tr("Ziehen Sie die vier Ecken auf die Ecken des Blatts. Rechts sehen Sie nach dem Loslassen "
               "das entzerrte Ergebnis. Fehlt eine Ecke auf dem Foto: „Foto verkleinern“ wählen und die Ecke "
               "dorthin ziehen, wo sich die beiden Blattkanten treffen würden.")
        )
        self._hinweis.setWordWrap(True)
        self._status = QLabel()
        self._status.setWordWrap(True)

        self.tonwerte_combo = QComboBox()
        for schluessel in TONWERTE:
            self.tonwerte_combo.addItem(TONWERT_NAMEN[schluessel], schluessel)
        self.tonwerte_combo.setCurrentIndex(max(self.tonwerte_combo.findData(tonwerte), 0))
        self.tonwerte_combo.setToolTip(
            tr("Farbe aufgehellt: Papier weiß, Schrift kräftig, Stempel und Logos bleiben farbig.\n"
            "Graustufen: wie oben, ohne Farbe.\nSchwarzweiß: nur Schwarz und Weiß (kleinste Datei).")
        )
        self.tonwerte_combo.currentIndexChanged.connect(lambda _i: self._vorschau_planen(0))

        self.zurueck_knopf = QPushButton(tr("◀ Zurück"))
        self.weiter_knopf = QPushButton(tr("Weiter ▶"))
        self.zuruecksetzen_knopf = QPushButton(tr("Zurücksetzen (automatisch)"))
        self.zuruecksetzen_knopf.setToolTip(tr("Die Ecken dieses Bildes auf die automatische Erkennung zurücksetzen"))
        self.rand_knopf = QPushButton(tr("Foto verkleinern"))
        self.rand_knopf.setCheckable(True)
        self.rand_knopf.setToolTip(
            tr("Zeigt einen Rand um das Foto. Dorthin lässt sich eine Ecke ziehen, die auf dem Foto fehlt, "
               "weil das Blatt angeschnitten ist. Der fehlende Zipfel wird weiß.")
        )
        self.rand_knopf.toggled.connect(self._rand_geschaltet)
        self.uebernehmen_knopf = QPushButton(tr("Übernehmen"))
        self.uebernehmen_knopf.setDefault(True)
        self.abbrechen_knopf = QPushButton(tr("Abbrechen"))
        self.zurueck_knopf.clicked.connect(lambda: self._blaettern(-1))
        self.weiter_knopf.clicked.connect(lambda: self._blaettern(1))
        self.zuruecksetzen_knopf.clicked.connect(self.zuruecksetzen)
        self.uebernehmen_knopf.clicked.connect(self.accept)
        self.abbrechen_knopf.clicked.connect(self.reject)

        mitte = QHBoxLayout()
        links, rechts = QVBoxLayout(), QVBoxLayout()
        links.addWidget(QLabel(tr("Foto")))
        links.addWidget(self._ansicht, 1)
        rechts.addWidget(QLabel(tr("Ergebnis (Vorschau)")))
        rechts.addWidget(self._vorschau, 1)
        mitte.addLayout(links, 1)
        mitte.addLayout(rechts, 1)

        unten = QHBoxLayout()
        unten.addWidget(QLabel(tr("Tonwerte:")))
        unten.addWidget(self.tonwerte_combo)
        unten.addSpacing(12)
        unten.addWidget(self.zuruecksetzen_knopf)
        unten.addWidget(self.rand_knopf)
        unten.addStretch(1)
        unten.addWidget(self.zurueck_knopf)
        unten.addWidget(self.weiter_knopf)
        unten.addSpacing(12)
        unten.addWidget(self.uebernehmen_knopf)
        unten.addWidget(self.abbrechen_knopf)

        layout = QVBoxLayout(self)
        layout.addWidget(self._kopf)
        layout.addWidget(self._hinweis)
        layout.addWidget(self._status)
        layout.addLayout(mitte, 1)
        layout.addLayout(unten)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._vorschau_aktualisieren)

        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.resize(int(geo.width() * FENSTER_ANTEIL), int(geo.height() * FENSTER_ANTEIL))
        self._zeigen(0)

    # --- Zustand ---------------------------------------------------------------------

    def _eintrag(self) -> _Eintrag:
        return self._eintraege[self._aktuell]

    def _zeigen(self, index: int, speichern: bool = True):
        if speichern:
            self._speichern()  # die Ecken des bisherigen Bildes merken
        self._aktuell = index
        e = self._eintrag()
        e.laden()
        self._laedt = True
        try:
            if e.klein is None:
                self._foto_item.setPixmap(QPixmap())
                self._rand_item.setVisible(False)
                self._szene.setSceneRect(0, 0, 10, 10)
                for p in self._punkte:
                    p.setVisible(False)
                self._viereck.setVisible(False)
            else:
                self._foto_item.setPixmap(QPixmap.fromImage(_qimage(e.klein)))
                if e.ausserhalb() and not self.rand_knopf.isChecked():
                    self.rand_knopf.blockSignals(True)  # sonst liefe die Umschaltung mitten im Laden
                    self.rand_knopf.setChecked(True)
                    self.rand_knopf.blockSignals(False)
                self._szene_einrichten()
                for p in self._punkte:
                    p.setVisible(True)
                self._viereck.setVisible(True)
                for p, (x, y) in zip(self._punkte, e.ecken):
                    p.setPos(x / e.faktor, y / e.faktor)
                self._viereck_zeichnen()
        finally:
            self._laedt = False
        n = len(self._eintraege)
        self._kopf.setText(tr("Bild {0} von {n}: {name}").format(index + 1, n=n, name=e.pfad.name) if n > 1 else e.pfad.name)
        self.zurueck_knopf.setVisible(n > 1)
        self.weiter_knopf.setVisible(n > 1)
        self.zurueck_knopf.setEnabled(index > 0)
        self.weiter_knopf.setEnabled(index < n - 1)
        self._status.setText(
            tr("Das Bild konnte nicht gelesen werden: {fehler}").format(fehler=e.fehler) if e.fehler
            else (tr("Die automatische Erkennung war bei diesem Bild unsicher - bitte die Ecken prüfen.")
                  if e.pfad in self._unsicher else "")
        )
        self.zuruecksetzen_knopf.setEnabled(e.klein is not None)
        self.rand_knopf.setEnabled(e.klein is not None)
        self._ansicht.fitInView(self._szene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._vorschau_aktualisieren()

    def _speichern(self):
        """Uebernimmt die Positionen der Eckpunkte in den Eintrag."""
        if not self._eintraege:
            return
        e = self._eintrag()
        if e.klein is None:
            return
        e.ecken = [(p.pos().x() * e.faktor, p.pos().y() * e.faktor) for p in self._punkte]

    def _foto_rechteck(self) -> QRectF:
        e = self._eintrag()
        return QRectF(0, 0, e.klein.width, e.klein.height) if e.klein is not None else QRectF(0, 0, 10, 10)

    def _grenzen(self) -> QRectF:
        """Bereich, in dem die Ecken liegen duerfen: das Foto, mit "Foto verkleinern" samt Rand."""
        foto = self._foto_rechteck()
        if not self.rand_knopf.isChecked() or self._eintrag().klein is None:
            return foto
        rand = RAND_ANTEIL * max(foto.width(), foto.height())
        return foto.adjusted(-rand, -rand, rand, rand)

    def _szene_einrichten(self):
        """Szene = Foto, mit "Foto verkleinern" samt sichtbarem Rand."""
        grenzen = self._grenzen()
        self._rand_item.setRect(grenzen)
        self._rand_item.setVisible(grenzen != self._foto_rechteck())
        self._szene.setSceneRect(grenzen)

    def _rand_geschaltet(self, _an: bool):
        e = self._eintrag()
        if e.klein is None:
            return
        self._szene_einrichten()
        # Ohne Rand muessen alle Ecken wieder im Foto liegen
        grenzen = self._grenzen()
        self._laedt = True
        try:
            for p in self._punkte:
                p.setPos(min(max(p.pos().x(), grenzen.left()), grenzen.right()),
                         min(max(p.pos().y(), grenzen.top()), grenzen.bottom()))
            self._viereck_zeichnen()
        finally:
            self._laedt = False
        self._ansicht.fitInView(self._szene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._vorschau_aktualisieren()

    def _blaettern(self, schritt: int):
        neu = self._aktuell + schritt
        if 0 <= neu < len(self._eintraege):
            self._zeigen(neu)

    def _viereck_zeichnen(self):
        self._viereck.setPolygon(QPolygonF([p.pos() for p in self._punkte]))

    # --- Rueckmeldungen der Eckpunkte -------------------------------------------------

    def _ecke_bewegt(self, _nummer: int):
        if self._laedt:
            return
        self._viereck_zeichnen()  # die Vorschau folgt erst beim Loslassen (sonst ruckelt das Ziehen)

    def _ecke_losgelassen(self):
        self._vorschau_planen(0)

    def _vorschau_planen(self, ms: int):
        self._timer.start(ms)

    def _vorschau_aktualisieren(self):
        self._timer.stop()
        e = self._eintrag()
        if e.klein is None:
            self._vorschau.pixmap_setzen(None)
            return
        self._speichern()
        klein = [(x / e.faktor, y / e.faktor) for x, y in e.ecken]
        try:
            bild, _pt, _name = entzerrte_seite(e.klein, klein, self.tonwerte(), max_pixel=VORSCHAU_PX)
        except Exception:  # noqa: BLE001 - entartetes Viereck (Ecken uebereinander): keine Vorschau
            self._vorschau.pixmap_setzen(None)
            return
        self._vorschau.pixmap_setzen(QPixmap.fromImage(_qimage(bild)))

    # --- Bedienung (auch fuer Tests) -------------------------------------------------

    def zuruecksetzen(self):
        """Ecken des aktuellen Bildes auf die automatische Erkennung."""
        e = self._eintrag()
        if e.klein is None:
            return
        e.ecken = list(e.automatisch)
        self._zeigen(self._aktuell, speichern=False)

    def ecken_setzen(self, ecken: list[tuple[float, float]]):
        """Setzt die Ecken des aktuellen Bildes (Pixel des vollen Fotos)."""
        e = self._eintrag()
        if e.klein is None:
            return
        e.ecken = [tuple(map(float, p)) for p in ecken]
        self._zeigen(self._aktuell, speichern=False)

    def ecken(self) -> list[tuple[float, float]]:
        """Ecken des aktuellen Bildes (Pixel des vollen Fotos)."""
        self._speichern()
        return list(self._eintrag().ecken)

    def tonwerte(self) -> str:
        return self.tonwerte_combo.currentData() or TONWERT_STANDARD

    def ergebnis(self) -> dict[Path, Entzerrung]:
        """``{Bild: Entzerrung}`` aller lesbaren Bilder des Fensters (aktuelle Ecken und Tonwerte)."""
        self._speichern()
        tonwerte = self.tonwerte()
        for e in self._eintraege:
            e.laden()  # nie gesehene Bilder: Erkennung bzw. Standard
        return {e.pfad: Entzerrung(list(e.ecken), tonwerte) for e in self._eintraege if e.klein is not None}
