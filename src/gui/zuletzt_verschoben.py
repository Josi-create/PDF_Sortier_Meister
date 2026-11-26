"""„Zuletzt verschoben nach …“ (Issue #253): mit einem Klick in den Zielordner springen.

Nach jedem Verschieben merkt sich das Fenster den Zielordner und die dort
angekommenen Dateien (nur fuer diese Sitzung). Ein Hinweis in der Statusleiste
oeffnet den Ordner links im Reiter „PDFs“ und markiert die Dateien; der
Rechtsklick darauf und das Menue „Ansicht“ zeigen auch fruehere Ziele.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QLabel, QMenu

from src.gui import farben
from src.i18n import tr
from src.rag.bezug import gleicher_pfad

MAX_ZIELE = 8  # so viele Zielordner bleiben in der Liste
LEUCHT_DAUER_MS = 2500  # so lange leuchtet der Hinweis nach einer Aenderung (Issue #428)


def anzeige_name(ordner: Path) -> str:
    """Ordnername mit dem Ordner davor, z. B. „Steuer 2025 › Quittungen“ (Issue #428)."""
    name = ordner.name or str(ordner)
    eltern = ordner.parent.name if ordner.name else ""
    return f"{eltern} › {name}" if eltern else name


class _ZielLabel(QLabel):
    """Hinweis in der Statusleiste; ``clicked`` nur bei Linksklick (rechts: Kontextmenue).

    Nimmt so viel Platz, wie der ganze Text braucht, und kuerzt erst, wenn die
    Statusleiste zu schmal ist (in der Mitte, damit eine Jahreszahl am Ende
    sichtbar bleibt). ``text()`` liefert weiter den ganzen Text. Nach
    ``aufleuchten()`` liegt kurz ein gelber Textmarker dahinter, der verblasst.
    """

    clicked = pyqtSignal()
    MINDESTBREITE = 120

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._leucht = 0.0  # 1.0 = volles Gelb, 0.0 = aus
        self._leucht_anim: QVariantAnimation | None = None

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def angezeigter_text(self) -> str:
        """Der Text, der bei der aktuellen Breite gemalt wird."""
        breite = self.contentsRect().width()
        fm = self.fontMetrics()
        if fm.horizontalAdvance(self.text()) <= breite:
            return self.text()
        return fm.elidedText(self.text(), Qt.TextElideMode.ElideMiddle, breite)

    def minimumSizeHint(self) -> QSize:
        breite = min(self.MINDESTBREITE, self.sizeHint().width())
        return QSize(breite, super().minimumSizeHint().height())

    # --- Aufleuchten (Issue #428) ---------------------------------------------

    def leuchtet(self) -> bool:
        return self._leucht > 0.0

    def aufleuchten(self) -> None:
        """Gelb hinterlegen und in ``LEUCHT_DAUER_MS`` zur normalen Farbe verblassen."""
        if self._leucht_anim is None:
            anim = QVariantAnimation(self)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setDuration(LEUCHT_DAUER_MS)
            anim.setEasingCurve(QEasingCurve.Type.InQuad)  # erst kraeftig, dann verblassen
            anim.valueChanged.connect(self._leucht_setzen)
            anim.finished.connect(lambda: self._leucht_setzen(0.0))
            self._leucht_anim = anim
        self._leucht_anim.stop()
        self._leucht_setzen(1.0)
        self._leucht_anim.start()

    def _leucht_setzen(self, wert) -> None:
        self._leucht = max(0.0, float(wert))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self._leucht > 0.0:
            # Textmarker-Gelb; im dunklen Design schwaecher, damit die helle Schrift lesbar bleibt
            gelb = QColor(255, 225, 40)
            gelb.setAlpha(int((110 if farben.ist_dunkel() else 200) * self._leucht))
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gelb)
            painter.drawRoundedRect(self.rect().adjusted(0, 1, 0, -1).toRectF(), 3, 3)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(
            self.contentsRect(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.angezeigter_text(),
        )
        painter.end()


class ZuletztVerschobenMixin:
    """Fuer das Hauptfenster: letzte Zielordner merken, anzeigen und oeffnen."""

    def zuletzt_verschoben_einrichten(self) -> None:
        """Legt Liste und Hinweis an; der Hinweis erscheint erst nach dem ersten Verschieben."""
        # Neueste zuerst: (Zielordner, dort angekommene Dateien)
        self._letzte_ziele: list[tuple[Path, list[Path]]] = []
        label = _ZielLabel("")
        schrift = label.font()
        schrift.setUnderline(True)
        label.setFont(schrift)
        label.setCursor(Qt.CursorShape.PointingHandCursor)
        label.setVisible(False)
        label.clicked.connect(self.zuletzt_verschoben_oeffnen)
        label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        label.customContextMenuRequested.connect(self._zuletzt_verschoben_kontextmenue)
        self.zuletzt_verschoben_label = label
        self.statusbar.insertPermanentWidget(0, label)

    # --- Merken -----------------------------------------------------------------

    def _ziel_merken(self, paare, ordner: Path | None = None) -> None:
        """Nach einem Verschieben oder Kopieren: ``paare`` = [(alter Pfad, neuer Pfad), ...].

        Mit ``ordner`` (ganzer Ordner verschoben/kopiert, Issue #312) gibt es genau
        einen Eintrag fuer diesen Ordner, auch wenn Dateien in Unterordnern liegen.
        """
        ziele = getattr(self, "_letzte_ziele", None)
        if ziele is None or not paare:
            return
        je_ordner: dict[Path, list[Path]] = {}
        for _alt, neu in paare:
            neu = Path(neu)
            je_ordner.setdefault(Path(ordner) if ordner is not None else neu.parent, []).append(neu)
        for ordner, dateien in je_ordner.items():
            ziele[:] = [z for z in ziele if not gleicher_pfad(z[0], ordner)]
            ziele.insert(0, (ordner, dateien))
        del ziele[MAX_ZIELE:]
        self._zuletzt_verschoben_anzeigen(aufleuchten=True)

    def _ziel_vergessen(self, dateien) -> None:
        """Nach „Rückgängig“: die zurueckgeholten Dateien liegen nicht mehr im Zielordner."""
        ziele = getattr(self, "_letzte_ziele", None)
        if not ziele:
            return
        weg = [Path(d) for d in dateien]
        neu = []
        for ordner, liste in ziele:
            rest = [d for d in liste if not any(gleicher_pfad(d, w) for w in weg)]
            if rest:
                neu.append((ordner, rest))
        ziele[:] = neu
        self._zuletzt_verschoben_anzeigen()

    def _zuletzt_verschoben_anzeigen(self, aufleuchten: bool = False) -> None:
        label = getattr(self, "zuletzt_verschoben_label", None)
        if label is None:
            return
        if not self._letzte_ziele:
            label.setVisible(False)
            return
        ordner = self._letzte_ziele[0][0]
        text = tr("Zuletzt verschoben nach: {name}").format(name=anzeige_name(ordner))
        aufleuchten = aufleuchten or text != label.text() or label.isHidden()
        label.setText(text)
        label.setToolTip(tr(
            "{pfad}\nKlick: Ordner links öffnen und die verschobenen Dateien markieren.\n"
            "Rechtsklick: frühere Ziele."
        ).format(pfad=ordner))
        label.setVisible(True)
        if aufleuchten:
            label.aufleuchten()  # Issue #428

    # --- Menue ------------------------------------------------------------------

    def zuletzt_verschoben_menue_fuellen(self, menu: QMenu) -> None:
        """Fuellt ``menu`` mit den letzten Zielordnern (neuester zuerst)."""
        menu.clear()
        menu.setToolTipsVisible(True)
        ziele = getattr(self, "_letzte_ziele", None) or []
        if not ziele:
            menu.addAction(tr("Noch nichts verschoben")).setEnabled(False)
            return
        for ordner, dateien in ziele:
            name = (ordner.name or str(ordner)).replace("&", "&&")
            aktion = menu.addAction(f"{name} ({len(dateien)})")
            aktion.setToolTip(str(ordner))
            aktion.triggered.connect(lambda _=False, o=ordner: self.zuletzt_verschoben_oeffnen(o))

    def _zuletzt_verschoben_kontextmenue(self, pos) -> None:
        menu = QMenu(self)
        self.zuletzt_verschoben_menue_fuellen(menu)
        menu.exec(self.zuletzt_verschoben_label.mapToGlobal(pos))

    # --- Oeffnen ----------------------------------------------------------------

    def zuletzt_verschoben_oeffnen(self, ordner: Path | None = None) -> None:
        """Oeffnet den Zielordner links in „PDFs“ und markiert die dorthin verschobenen Dateien.

        Ohne ``ordner`` das neueste Ziel.
        """
        ziele = getattr(self, "_letzte_ziele", None) or []
        if ordner is None:
            eintrag = ziele[0] if ziele else None
        else:
            eintrag = next((z for z in ziele if z[0] == ordner), None)
        if eintrag is None:
            return
        ordner, dateien = eintrag
        if not ordner.is_dir():
            self.statusbar.showMessage(tr("Den Ordner {ziel} gibt es nicht mehr").format(ziel=ordner), 5000)
            return

        aktuell = self.config.get_scan_folder()
        gewechselt = not (aktuell and gleicher_pfad(aktuell, ordner))
        if not gewechselt:
            self.load_pdfs()  # die Kacheln koennen aelter sein als das Verschieben
        else:
            # load_pdfs baut die Kacheln synchron; ausgewaehlt werden unten die Treffer
            self._navigate_to_folder(ordner, auswaehlen=False)
        self.left_tabs.setCurrentIndex(0)

        treffer = [w.pdf_path for w in self.pdf_widgets
                   if any(gleicher_pfad(w.pdf_path, d) for d in dateien)]
        if not treffer:
            if gewechselt:
                self._auswahl_nach_ordnerwechsel(ordner)  # Issue #340: erste Kachel
            # z. B. inzwischen umbenannt, weiterverschoben oder vom Filter ausgeblendet
            self.statusbar.showMessage(tr("Ordner geöffnet: {name}").format(name=ordner.name), 4000)
            return
        if len(treffer) == 1:
            pfad = treffer[0]
            if self.selected_pdf == pfad and not self.selected_pdfs:
                # schon ausgewaehlt: ein weiterer Klick wuerde die Auswahl aufheben
                widget = self._pdf_widget_for(pfad)
                if widget is not None:
                    widget.selected = True
            else:
                self.on_pdf_clicked(pfad)
        else:
            self._ordner_markierung_aufheben()  # Ordnermarkierung und PDF-Auswahl schliessen sich aus
            for widget in self.pdf_widgets:
                widget.selected = widget.pdf_path in treffer
            self.selected_pdfs = list(treffer)
            self._update_selection_status()
        self.zur_kachel_scrollen(treffer[0])
        if len(treffer) == 1:
            self.statusbar.showMessage(tr("Im Ordner angezeigt: {name}").format(name=treffer[0].name), 4000)
        else:
            self.statusbar.showMessage(
                tr("{anzahl} verschobene Dateien in „{name}“ markiert").format(
                    anzahl=len(treffer), name=ordner.name), 5000)
