"""
Ordnerzeile fuer den Scan-Bereich (Explorer-Gefuehl, Issues #29 und #147)

Zeigt einen Unterordner (oder ".." fuer den uebergeordneten Ordner) als
schmale Zeile ueber dem PDF-Raster: Symbol links, Name (bei Platzmangel
gekuerzt, voller Pfad im Tooltip), Anzahl PDFs rechts in grau. Hoehe und
Schrift sind fest und haengen nicht von der Kachelgroesse der PDFs ab
(Issue #117). Doppelklick wechselt in den Ordner, die ".."-Zeile reagiert
auf Einfachklick, PDFs koennen per Drag & Drop hineingeschoben werden.

Issue #196: Ein Einfachklick markiert den Ordner (er wird dann ganz verschoben
oder kopiert); die Zeile laesst sich auch auf den Zielbaum ziehen.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QDrag, QDragEnterEvent, QDropEvent, QFontMetrics
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy

from src.core.office_convert import ist_sortierbar
from src.gui.favoriten_leiste import FAVORIT_ENTFERNEN_TEXT, FAVORIT_MERKEN_TEXT
from src.gui.hierhin_kopieren import (
    ORDNER_MIME,
    drop_aktion_setzen,
    kopier_eintrag,
    verschieben_eintrag,
)
from src.gui.pfad_aktionen import (
    PFAD_KOPIEREN_TEXT,
    im_dateimanager_zeigen,
    oeffnen_text,
    pfad_kopieren,
)
from src.i18n import tr


class FolderTileWidget(QFrame):
    """Zeile fuer einen Ordner im Scan-Bereich (Issue #147).

    Der Klassenname bleibt aus Kompatibilitaet "Tile"; dargestellt wird eine
    Zeile. Das Hauptfenster ordnet die Zeilen in einem eigenen Raster mit ein
    oder zwei Spalten ueber den PDF-Kacheln an.
    """

    clicked = pyqtSignal(Path)  # Einfachklick: ".." wechselt hoch (#50), Ordner werden markiert (#196)
    double_clicked = pyqtSignal(Path)  # In den Ordner wechseln
    pdf_dropped = pyqtSignal(Path, Path)  # (pdf_path, folder_path)
    favorit_umschalten = pyqtSignal(Path)  # Favorit merken bzw. entfernen (Issue #114)
    copy_here_requested = pyqtSignal(Path)  # Menue "Hierhin kopieren" (Issue #179)
    pdf_copy_dropped = pyqtSignal(list, Path)  # Strg+Drop: (Dateien, Ordner), Issue #179
    move_here_requested = pyqtSignal(Path)  # Menue "Hierhin verschieben" (Issue #183)
    show_in_tree_requested = pyqtSignal(Path)  # Menue "Rechts im Baum zeigen" (Issue #183)
    target_toggle_requested = pyqtSignal(Path)  # Menue "Als Zielordner merken" (Issue #183)
    markieren_requested = pyqtSignal(Path)  # Rechtsklick: Ordner markieren, ohne umzuschalten (#196)
    ordner_ziel_gewaehlt = pyqtSignal(Path, Path, bool)  # (Ordner, Ziel, kopieren), Issue #196
    ordner_ziel_waehlen = pyqtSignal(Path, bool)  # Menue "Anderen Ordner wählen …" (Issue #196)

    ROW_HEIGHT = 26  # feste Zeilenhoehe in Pixeln
    NAME_PX = 12  # Schriftgroesse des Ordnernamens
    COUNT_PX = 11  # Schriftgroesse des Zaehlers
    ICON_PX = 14  # Schriftgroesse des Symbols
    MIN_WIDTH = 120  # schmaler wird eine Zeile nie

    _STYLE_NORMAL = (
        "FolderTileWidget { background-color: #fbf8ec; border: 1px solid #e3dcc2; "
        "border-radius: 3px; }"
    )
    _STYLE_HOVER = (
        "FolderTileWidget { background-color: #fff3cd; border: 1px solid #daa520; "
        "border-radius: 3px; }"
    )
    _STYLE_MARKIERT = (
        "FolderTileWidget { background-color: #d6e9ff; border: 2px solid #1e6fd9; "
        "border-radius: 3px; }"
    )
    _STYLE_DROP = (
        "FolderTileWidget { background-color: #d9f2d9; border: 2px solid #4caf50; "
        "border-radius: 3px; }"
    )

    def __init__(
        self,
        folder_path: Path,
        pdf_count: Optional[int] = None,
        is_parent: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.folder_path = Path(folder_path)
        self.is_parent = is_parent
        self._pdf_count = pdf_count
        self.favorit_pruefer = None  # Callable[[Path], bool], setzt das Hauptfenster
        self.auswahl_pruefer = None  # Callable[[], list[Path]], setzt das Hauptfenster (#179)
        self.ziel_pruefer = None  # Callable[[Path], bool]: Ordner schon in der Zielliste? (#183)
        # Callable[[Path], list[(Text, Path)]]: berechnete Zielvorschlaege fuer den Ordner (#196)
        self.ziel_vorschlag_pruefer = None
        self._markiert = False
        self._drag_start = None
        self._doppelklick = False
        self._setup_ui()

    def _setup_ui(self):
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAcceptDrops(True)
        self.setStyleSheet(self._STYLE_NORMAL)
        self.setFixedHeight(self.ROW_HEIGHT)
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 8, 0)
        layout.setSpacing(6)

        self.icon_label = QLabel("⬆" if self.is_parent else "📁")
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        icon_font = self.icon_label.font()
        icon_font.setPixelSize(self.ICON_PX)
        self.icon_label.setFont(icon_font)
        layout.addWidget(self.icon_label)

        # Name: darf schrumpfen (Ignored), wird dann mit "…" gekuerzt
        self.name_label = QLabel()
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.name_label.setStyleSheet("background: transparent; border: none;")
        # Schrift ueber QFont, damit QFontMetrics fuers Kuerzen dieselbe misst
        name_font = self.name_label.font()
        name_font.setPixelSize(self.NAME_PX)
        name_font.setBold(not self.is_parent)
        self.name_label.setFont(name_font)
        layout.addWidget(self.name_label, 1)

        self.count_label = QLabel(self._count_text())
        self.count_label.setStyleSheet("color: #777; background: transparent; border: none;")
        count_font = self.count_label.font()
        count_font.setPixelSize(self.COUNT_PX)
        self.count_label.setFont(count_font)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.count_label)

        self._update_name()

        if self.is_parent:
            self.setToolTip(
                tr(
                    "Übergeordneter Ordner: {folder_path}\n"
                    "Klick wechselt nach oben, PDFs hierher ziehen verschiebt sie."
                ).format(folder_path=self.folder_path)
            )
        else:
            self.setToolTip(
                tr(
                    "{folder_path}\nKlick markiert den Ordner (dann rechts das Ziel "
                    "anklicken), Doppelklick öffnet ihn, Ziehen verschiebt ihn (Strg: "
                    "kopiert).\nPDFs hierher ziehen verschiebt sie."
                ).format(folder_path=self.folder_path)
            )

    @property
    def full_name(self) -> str:
        """Ungekuerzter Anzeigename (".." fuer den uebergeordneten Ordner)."""
        return ".." if self.is_parent else self.folder_path.name

    def _update_name(self):
        """Name in die verfuegbare Breite einpassen (rechts mit "…" gekuerzt).

        Solange die Zeile nicht angezeigt wird, steht der volle Name da; das
        Kuerzen holt resizeEvent nach.
        """
        name = self.full_name
        width = self.name_label.width()
        if self.isVisible() and width > 0:
            fm = QFontMetrics(self.name_label.font())
            name = fm.elidedText(name, Qt.TextElideMode.ElideRight, width)
        self.name_label.setText(name)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_name()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_name()

    def _count_text(self) -> str:
        if self.is_parent:
            return tr("übergeordneter Ordner")
        if self._pdf_count is None:
            return ""
        return f"{self._pdf_count} {'PDF' if self._pdf_count == 1 else 'PDFs'}"

    # --- Markierung (Issue #196) -------------------------------------------

    @property
    def markiert(self) -> bool:
        return self._markiert

    @markiert.setter
    def markiert(self, wert: bool):
        wert = bool(wert) and not self.is_parent
        if wert != self._markiert:
            self._markiert = wert
            self.setStyleSheet(self._style_ruhe())

    def _style_ruhe(self) -> str:
        return self._STYLE_MARKIERT if self._markiert else self._STYLE_NORMAL

    # --- Maus -----------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.is_parent:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Ordnerzeile ziehen (Issue #196): auf den Zielbaum, Strg kopiert."""
        if (
            self._drag_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._drag_start).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._drag_start = None
            self._ziehen_starten()
            return
        super().mouseMoveEvent(event)

    def _ziehen_starten(self):
        mime = QMimeData()
        mime.setData(ORDNER_MIME, str(self.folder_path).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(
            Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction
        )
        self.setStyleSheet(self._style_ruhe())

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        if self._doppelklick:  # zweiter Klick eines Doppelklicks: nicht nochmal markieren
            self._doppelklick = False
        elif (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit(self.folder_path)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._doppelklick = True
            self.double_clicked.emit(self.folder_path)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Rechtsklick: im Dateimanager oeffnen, Pfad kopieren (Issue #154)."""
        if not self.is_parent:
            self.markieren_requested.emit(self.folder_path)  # Vorschlaege fuers Untermenue (#196)
        self._build_context_menu().exec(event.globalPos())

    def _build_context_menu(self) -> QMenu:
        """Baut das Kontextmenue (getrennt, damit es testbar ist)."""
        menu = QMenu(self)
        if not self.is_parent:
            # Issue #196: den ganzen Ordner verschieben/kopieren (Untermenue mit Vorschlaegen)
            self._ordner_ziel_menue(menu, tr("📁 Ordner verschieben nach …"), False)
            self._ordner_ziel_menue(menu, tr("📁 Ordner kopieren nach …"), True)
            menu.addSeparator()
            kopier_eintrag(
                menu, self.auswahl_pruefer, lambda: self.copy_here_requested.emit(self.folder_path)
            )
            # Issue #183: verschieben wie Ziehen, im Baum zeigen, als Zielordner merken
            verschieben_eintrag(
                menu, self.auswahl_pruefer, lambda: self.move_here_requested.emit(self.folder_path)
            )
            menu.addAction(tr("🌳 Rechts im Baum zeigen")).triggered.connect(
                lambda: self.show_in_tree_requested.emit(self.folder_path)
            )
            drin = bool(self.ziel_pruefer and self.ziel_pruefer(self.folder_path))
            menu.addAction(tr("Aus Zielliste entfernen") if drin else tr("⭐ Als Zielordner merken")).triggered.connect(
                lambda: self.target_toggle_requested.emit(self.folder_path)
            )
            menu.addSeparator()
        open_action = menu.addAction(oeffnen_text())
        open_action.triggered.connect(self._open_in_file_manager)
        copy_action = menu.addAction(PFAD_KOPIEREN_TEXT)
        copy_action.triggered.connect(self._copy_path)
        if not self.is_parent:
            ist = bool(self.favorit_pruefer and self.favorit_pruefer(self.folder_path))
            fav = menu.addAction(FAVORIT_ENTFERNEN_TEXT if ist else FAVORIT_MERKEN_TEXT)
            fav.triggered.connect(lambda: self.favorit_umschalten.emit(self.folder_path))
        return menu

    def _ordner_ziel_menue(self, menu: QMenu, titel: str, kopieren: bool) -> QMenu:
        """Untermenue: berechnete Vorschlaege fuer diesen Ordner, dazu "Anderen Ordner wählen …"."""
        untermenue = menu.addMenu(titel)
        pruefer = self.ziel_vorschlag_pruefer
        vorschlaege = list(pruefer(self.folder_path) or []) if pruefer else []
        if vorschlaege:
            for text, ziel in vorschlaege:
                aktion = untermenue.addAction(text.replace("&", "&&"))
                aktion.triggered.connect(
                    lambda _=False, z=Path(ziel): self.ordner_ziel_gewaehlt.emit(
                        self.folder_path, z, kopieren
                    )
                )
        else:
            leer = untermenue.addAction(tr("(noch keine Vorschläge)"))
            leer.setEnabled(False)
        untermenue.addSeparator()
        waehlen = untermenue.addAction(tr("Anderen Ordner wählen …"))
        waehlen.triggered.connect(lambda: self.ordner_ziel_waehlen.emit(self.folder_path, kopieren))
        return untermenue

    def _open_in_file_manager(self):
        im_dateimanager_zeigen(self.folder_path)

    def _copy_path(self):
        pfad_kopieren(self.folder_path)

    def enterEvent(self, event):
        self.setStyleSheet(self._STYLE_HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._style_ruhe())
        super().leaveEvent(event)

    # --- Drag & Drop ------------------------------------------------------

    @staticmethod
    def _pdf_paths(mime) -> list[Path]:
        if not mime.hasUrls():
            return []
        paths = [Path(url.toLocalFile()) for url in mime.urls()]
        return [p for p in paths if ist_sortierbar(p)]

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._pdf_paths(event.mimeData()):
            self.setStyleSheet(self._STYLE_DROP)
            drop_aktion_setzen(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """Strg waehrend des Ziehens: Cursor zeigt die Kopieraktion (Issue #179)."""
        if self._pdf_paths(event.mimeData()):
            drop_aktion_setzen(event)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._style_ruhe())
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self._style_ruhe())
        pdfs = self._pdf_paths(event.mimeData())
        if not pdfs:
            event.ignore()
            return
        if drop_aktion_setzen(event):
            self.pdf_copy_dropped.emit(pdfs, self.folder_path)
            return
        for pdf in pdfs:
            self.pdf_dropped.emit(pdf, self.folder_path)
