"""
Favoriten-Leiste ueber der Pfadzeile der PDF-Ansicht (Issue #114)

Flache Knoepfe mit dem Ordnernamen (Tooltip: voller Pfad). Ein Klick oeffnet
den Ordner ueber das Signal ``ordner_geoeffnet`` (das Hauptfenster leitet es
an die zentrale Navigation mit History weiter). Der gerade geoeffnete Ordner
ist hervorgehoben, fehlende Ordner sind grau. Rechtsklick auf einen Knopf:
Entfernen, Umbenennen, verschieben, im Dateimanager oeffnen.

Gespeichert wird in der Konfiguration unter ``"favoriten"`` als Liste von
``{"pfad": ..., "name": ...}``. Ohne Eintraege ist die Leiste ausgeblendet.

GPL-3.0-or-later - Copyright (c) 2026
"""

import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from src.gui.pfad_aktionen import im_dateimanager_zeigen, oeffnen_text

FAVORIT_MERKEN_TEXT = "★ Als Favorit merken"
FAVORIT_ENTFERNEN_TEXT = "Favorit entfernen"
AKTUELLEN_MERKEN_TEXT = "Aktuellen Ordner als Favorit merken"


def _schluessel(pfad: Path | str) -> str:
    """Vergleichsschluessel eines Pfads (Gross-/Kleinschreibung unter Windows)."""
    return os.path.normcase(os.path.normpath(str(pfad)))


class _SeitwaertsScroll(QScrollArea):
    """Scrollbereich, dessen Mausrad seitwaerts scrollt."""

    def wheelEvent(self, event):
        leiste = self.horizontalScrollBar()
        delta = event.angleDelta().y() or event.angleDelta().x()
        leiste.setValue(leiste.value() - delta)
        event.accept()


class FavoritenLeiste(QFrame):
    """Buttonleiste mit den Favoriten-Ordnern."""

    ordner_geoeffnet = pyqtSignal(Path)  # Klick auf einen Favoriten
    geaendert = pyqtSignal()  # Liste wurde veraendert

    _STIL = (
        "QPushButton { border: 1px solid transparent; border-radius: 3px; "
        "padding: 2px 8px; font-size: 11px; }"
        "QPushButton:hover { background-color: #fff3cd; border-color: #daa520; }"
        "QPushButton[aktuell=\"true\"] { background-color: #ffe9a8; "
        "border-color: #daa520; font-weight: bold; }"
        "QPushButton[fehlt=\"true\"] { color: #999; font-style: italic; }"
    )

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._aktuell: Optional[Path] = None
        self.knoepfe: list[QPushButton] = []

        # Nur eine Zeile hoch: nie freien Platz der PDF-Ansicht abgreifen
        # (Live-Test: die Leiste wuchs auf die halbe Spaltenhoehe)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        aussen = QHBoxLayout(self)
        aussen.setContentsMargins(6, 0, 6, 0)
        self._scroll = _SeitwaertsScroll()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFixedHeight(40)
        innen = QWidget()
        self._zeile = QHBoxLayout(innen)
        self._zeile.setContentsMargins(0, 2, 0, 2)
        self._zeile.setSpacing(4)
        self._zeile.addStretch()
        self._scroll.setWidget(innen)
        aussen.addWidget(self._scroll)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._leere_flaeche_menue)
        self.aktualisieren()

    # --- Daten ---------------------------------------------------------

    def favoriten(self) -> list[dict]:
        roh = self._config.get("favoriten", []) or []
        return [
            {"pfad": str(e["pfad"]), "name": str(e.get("name") or "")}
            for e in roh
            if isinstance(e, dict) and e.get("pfad")
        ]

    def _speichern(self, liste: list[dict]) -> None:
        self._config.set("favoriten", liste)
        self.aktualisieren()
        self.geaendert.emit()

    def _index(self, pfad: Path | str) -> int:
        key = _schluessel(pfad)
        for i, e in enumerate(self.favoriten()):
            if _schluessel(e["pfad"]) == key:
                return i
        return -1

    def ist_favorit(self, pfad: Path | str) -> bool:
        return self._index(pfad) >= 0

    def hinzufuegen(self, pfad: Path | str, name: str = "") -> None:
        if self.ist_favorit(pfad):
            return
        liste = self.favoriten()
        liste.append({"pfad": str(Path(pfad)), "name": name.strip()})
        self._speichern(liste)

    def entfernen(self, pfad: Path | str) -> None:
        i = self._index(pfad)
        if i < 0:
            return
        liste = self.favoriten()
        del liste[i]
        self._speichern(liste)

    def umschalten(self, pfad: Path | str) -> None:
        if self.ist_favorit(pfad):
            self.entfernen(pfad)
        else:
            self.hinzufuegen(pfad)

    def umbenennen(self, pfad: Path | str, name: str) -> None:
        """Setzt den Anzeigenamen; leer = Ordnername."""
        i = self._index(pfad)
        if i < 0:
            return
        liste = self.favoriten()
        liste[i]["name"] = name.strip()
        self._speichern(liste)

    def verschieben(self, pfad: Path | str, richtung: int) -> None:
        """Verschiebt um ``richtung`` Plaetze (-1 nach links, +1 nach rechts)."""
        i = self._index(pfad)
        j = i + richtung
        liste = self.favoriten()
        if i < 0 or not 0 <= j < len(liste):
            return
        liste[i], liste[j] = liste[j], liste[i]
        self._speichern(liste)

    # --- Anzeige -------------------------------------------------------

    @staticmethod
    def anzeigename(eintrag: dict) -> str:
        if eintrag["name"]:
            return eintrag["name"]
        p = Path(eintrag["pfad"])
        return p.name or str(p)

    def set_aktueller_ordner(self, ordner: Optional[Path | str]) -> None:
        self._aktuell = Path(ordner) if ordner else None
        self.aktualisieren()

    def aktualisieren(self) -> None:
        for k in self.knoepfe:
            self._zeile.removeWidget(k)
            k.deleteLater()
        self.knoepfe = []
        liste = self.favoriten()
        akt = _schluessel(self._aktuell) if self._aktuell else None
        for i, e in enumerate(liste):
            pfad = Path(e["pfad"])
            fehlt = not pfad.is_dir()
            k = QPushButton(self.anzeigename(e).replace("&", "&&"))
            k.setFlat(True)
            k.setCursor(Qt.CursorShape.PointingHandCursor)
            k.setStyleSheet(self._STIL)
            k.setProperty("aktuell", "true" if akt == _schluessel(pfad) else "false")
            k.setProperty("fehlt", "true" if fehlt else "false")
            k.setToolTip(f"{pfad}\nOrdner nicht gefunden" if fehlt else str(pfad))
            k.clicked.connect(lambda _=False, p=pfad: self._geklickt(p))
            k.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            k.customContextMenuRequested.connect(
                lambda pos, p=pfad, b=k: self._knopf_menue(p).exec(b.mapToGlobal(pos))
            )
            self._zeile.insertWidget(i, k)
            self.knoepfe.append(k)
        self.setVisible(bool(liste))

    # --- Aktionen ------------------------------------------------------

    def _geklickt(self, pfad: Path) -> None:
        if pfad.is_dir():
            self.ordner_geoeffnet.emit(pfad)
            return
        antwort = QMessageBox.question(
            self,
            "Ordner nicht gefunden",
            f"Der Ordner existiert nicht mehr:\n{pfad}\n\nFavorit entfernen?",
        )
        if antwort == QMessageBox.StandardButton.Yes:
            self.entfernen(pfad)

    def _umbenennen_fragen(self, pfad: Path) -> None:
        i = self._index(pfad)
        if i < 0:
            return
        aktuell = self.anzeigename(self.favoriten()[i])
        name, ok = QInputDialog.getText(
            self, "Favorit umbenennen", "Anzeigename (leer = Ordnername):", text=aktuell
        )
        if ok:
            self.umbenennen(pfad, name)

    def _knopf_menue(self, pfad: Path) -> QMenu:
        """Kontextmenue eines Favoriten-Knopfs (getrennt, damit es testbar ist)."""
        menu = QMenu(self)
        i = self._index(pfad)
        menu.addAction("Entfernen").triggered.connect(lambda: self.entfernen(pfad))
        menu.addAction("Umbenennen (Anzeigename)").triggered.connect(
            lambda: self._umbenennen_fragen(pfad)
        )
        links = menu.addAction("Nach links")
        links.setEnabled(i > 0)
        links.triggered.connect(lambda: self.verschieben(pfad, -1))
        rechts = menu.addAction("Nach rechts")
        rechts.setEnabled(0 <= i < len(self.favoriten()) - 1)
        rechts.triggered.connect(lambda: self.verschieben(pfad, 1))
        menu.addSeparator()
        menu.addAction(oeffnen_text()).triggered.connect(lambda: im_dateimanager_zeigen(pfad))
        return menu

    def _leere_flaeche_menue(self, pos) -> None:
        if self._aktuell is None:
            return
        aktuellen_ordner_menue(self, self, self._aktuell).exec(self.mapToGlobal(pos))


def aktuellen_ordner_menue(parent, leiste: FavoritenLeiste, ordner: Path) -> QMenu:
    """Menue "Aktuellen Ordner als Favorit merken" bzw. "Favorit entfernen"."""
    menu = QMenu(parent)
    text = FAVORIT_ENTFERNEN_TEXT if leiste.ist_favorit(ordner) else AKTUELLEN_MERKEN_TEXT
    menu.addAction(text).triggered.connect(lambda: leiste.umschalten(ordner))
    return menu
