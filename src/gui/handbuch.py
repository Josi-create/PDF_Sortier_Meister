"""Handbuch im Programm (Issue #365).

Das Handbuch liegt als Markdown in ``docs/handbuch/<sprache>/``, je Kapitel eine Datei
(gleiche Dateinamen in jeder Sprache). Angezeigt wird es ohne KI und ohne Internet in einem
eigenen Fenster: Kapitelliste links, Text rechts, Suche oben.

Im gebauten Programm liegt ``docs/handbuch`` neben ``src`` (siehe ``pdf_sortier_meister.spec``),
deshalb wird der Ordner relativ zu diesem Modul gesucht.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
)

from src.i18n import current_language, tr

HANDBUCH_WURZEL = Path(__file__).resolve().parents[2] / "docs" / "handbuch"
ERSATZ_SPRACHE = "de"


def handbuch_ordner(sprache: str | None = None, wurzel: Path | None = None) -> Path:
    """Ordner des Handbuchs in der Sprache der Oberfläche, sonst Deutsch."""
    wurzel = wurzel or HANDBUCH_WURZEL
    sprache = (sprache or current_language() or ERSATZ_SPRACHE).lower()
    ordner = wurzel / sprache
    if ordner.is_dir() and any(ordner.glob("*.md")):
        return ordner
    return wurzel / ERSATZ_SPRACHE


def kapitel_titel(datei: Path) -> str:
    """Erste Überschrift der Datei, sonst der Dateiname."""
    try:
        with datei.open(encoding="utf-8") as f:
            for zeile in f:
                zeile = zeile.strip()
                if zeile.startswith("# "):
                    return zeile[2:].strip()
    except OSError:
        pass
    return datei.stem


def kapitel_liste(ordner: Path) -> list[tuple[Path, str]]:
    """Alle Kapitel eines Handbuch-Ordners, nach Dateinamen sortiert."""
    if not ordner.is_dir():
        return []
    return [(datei, kapitel_titel(datei)) for datei in sorted(ordner.glob("*.md"))]


class HandbuchDialog(QDialog):
    """Fenster mit Kapitelliste, Text und Suche."""

    def __init__(self, parent=None, ordner: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Handbuch"))
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1000, 700)

        self.ordner = ordner or handbuch_ordner()
        self.kapitel = kapitel_liste(self.ordner)

        layout = QVBoxLayout(self)

        suchzeile = QHBoxLayout()
        self.suchfeld = QLineEdit()
        self.suchfeld.setPlaceholderText(tr("Im Handbuch suchen …"))
        self.suchfeld.setClearButtonEnabled(True)
        self.suchfeld.returnPressed.connect(self.weitersuchen)
        self.suchfeld.textChanged.connect(lambda _t: self.suchhinweis.clear())
        suchzeile.addWidget(self.suchfeld, 1)
        self.weiter_knopf = QPushButton(tr("Weitersuchen"))
        self.weiter_knopf.clicked.connect(self.weitersuchen)
        suchzeile.addWidget(self.weiter_knopf)
        self.suchhinweis = QLabel()
        suchzeile.addWidget(self.suchhinweis)
        layout.addLayout(suchzeile)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.liste = QListWidget()
        for datei, titel in self.kapitel:
            eintrag = QListWidgetItem(titel)
            eintrag.setData(Qt.ItemDataRole.UserRole, str(datei))
            self.liste.addItem(eintrag)
        self.liste.currentRowChanged.connect(self._kapitel_gewaehlt)
        splitter.addWidget(self.liste)

        self.text = QTextBrowser()
        # Links ins Netz im Browser öffnen; Links auf andere Kapitel (.md) lädt das Fenster selbst.
        self.text.setOpenExternalLinks(True)
        self.text.sourceChanged.connect(self._quelle_geaendert)
        splitter.addWidget(self.text)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 740])
        layout.addWidget(splitter, 1)

        if self.kapitel:
            self.liste.setCurrentRow(0)
        else:
            self.text.setPlainText(tr("Das Handbuch wurde nicht gefunden."))
            self.suchfeld.setEnabled(False)
            self.weiter_knopf.setEnabled(False)

    # -- Kapitel --------------------------------------------------------------------------

    def zeige_kapitel(self, zeile: int) -> None:
        if 0 <= zeile < len(self.kapitel):
            self.liste.setCurrentRow(zeile)

    def _kapitel_gewaehlt(self, zeile: int) -> None:
        if not 0 <= zeile < len(self.kapitel):
            return
        url = QUrl.fromLocalFile(str(self.kapitel[zeile][0]))
        if self.text.source() != url:
            self.text.setSource(url, QTextDocument.ResourceType.MarkdownResource)

    def _quelle_geaendert(self, url: QUrl) -> None:
        """Link auf ein anderes Kapitel: Kapitelliste nachziehen."""
        pfad = Path(url.toLocalFile()) if url.isLocalFile() else None
        for zeile, (datei, _titel) in enumerate(self.kapitel):
            if pfad is not None and datei.resolve() == pfad.resolve():
                if self.liste.currentRow() != zeile:
                    self.liste.blockSignals(True)
                    self.liste.setCurrentRow(zeile)
                    self.liste.blockSignals(False)
                return

    def aktuelle_zeile(self) -> int:
        return self.liste.currentRow()

    # -- Suche ----------------------------------------------------------------------------

    def weitersuchen(self) -> bool:
        """Nächste Fundstelle, erst im aktuellen Kapitel, dann in den folgenden."""
        begriff = self.suchfeld.text().strip()
        self.suchhinweis.clear()
        if not begriff or not self.kapitel:
            return False
        if self.text.find(begriff):
            return True
        start = max(self.liste.currentRow(), 0)
        anzahl = len(self.kapitel)
        for schritt in range(1, anzahl + 1):
            zeile = (start + schritt) % anzahl
            self.liste.setCurrentRow(zeile)
            self.text.moveCursor(self.text.textCursor().MoveOperation.Start)
            if self.text.find(begriff):
                return True
        self.suchhinweis.setText(tr("Nicht gefunden"))
        return False
