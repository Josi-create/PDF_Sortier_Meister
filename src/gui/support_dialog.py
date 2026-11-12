"""Unterstuetzen-Dialog (Issue #115).

Freiwilliger Beitrag ohne Gegenleistung und ohne Freischaltung von Funktionen.
Jede Stufe oeffnet dieselbe Zahlungsseite (``support.DONATE_URL``); der Betrag
wird dort eingegeben. "Ich habe unterstuetzt" ist eine reine Selbstauskunft.
Die Logik steckt in ``src.core.support``.
"""
from __future__ import annotations

from datetime import date

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.core import support
from src.i18n import tr


def tier_text(tier: support.Tier) -> str:
    """Beschriftung fuer Knopf und Auswahl, z.B. "Ein Kaffee – 3 €"."""
    return f"{tier.label} – {tier.amount} €"


class SupportDialog(QDialog):
    """Freundlicher Hinweis mit Stufenliste; "Später erinnern" schliesst ihn."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(tr("PDF Sortier Meister unterstützen"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(tr("<h3>Gefällt Ihnen PDF Sortier Meister?</h3>"))
        layout.addWidget(title)

        intro = QLabel(
            tr("Das Programm ist freie Software und bleibt es. Wenn es Ihnen Zeit spart, "
            "freue ich mich über einen kleinen Beitrag zur Weiterentwicklung.<br><br>"
            "<b>Ein freiwilliger Beitrag, keine Gegenleistung, keine Freischaltung "
            "von Funktionen.</b> Das Programm funktioniert mit und ohne Beitrag gleich.")
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.tier_buttons: dict[str, QPushButton] = {}
        for tier in support.TIERS:
            button = QPushButton(tier_text(tier))
            button.setEnabled(bool(support.DONATE_URL))
            button.clicked.connect(lambda _checked=False, t=tier: self._open_donate(t))
            self.tier_buttons[tier.key] = button
            layout.addWidget(button)

        if support.DONATE_URL:
            hint_text = (
                tr("Die Knöpfe öffnen die Seite bei Buy Me a Coffee. Bitte geben Sie dort "
                "den gewünschten Betrag ein bzw. wählen Sie die passende Anzahl Kaffees.")
            )
        else:
            hint_text = tr("Der Zahlungslink ist noch nicht eingerichtet.")
        self.amount_hint = QLabel(hint_text)
        self.amount_hint.setWordWrap(True)
        self.amount_hint.setStyleSheet("color: gray;")
        layout.addWidget(self.amount_hint)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        self.supported_label = QLabel(tr("<b>Ich habe gerade unterstützt:</b>"))
        layout.addWidget(self.supported_label)
        row = QHBoxLayout()
        self.tier_combo = QComboBox()
        for tier in support.TIERS:
            self.tier_combo.addItem(tier_text(tier), tier.key)
        row.addWidget(self.tier_combo, 1)
        self.confirm_button = QPushButton(tr("Danke, merken"))
        self.confirm_button.setToolTip(
            tr("Speichert nur auf diesem Rechner, dass Sie unterstützt haben - "
            "es wird nichts geprüft und nichts übertragen.")
        )
        self.confirm_button.clicked.connect(self._confirm_supported)
        row.addWidget(self.confirm_button)
        layout.addLayout(row)

        if support.IMPRESSUM_URL:
            impressum = QLabel(tr("<a href=\"{IMPRESSUM_URL}\">Impressum</a>").format(IMPRESSUM_URL=support.IMPRESSUM_URL))
            impressum.setOpenExternalLinks(True)
            impressum.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
            layout.addWidget(impressum)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.later_button = QPushButton(tr("Später erinnern"))
        self.later_button.clicked.connect(self.reject)
        bottom.addWidget(self.later_button)
        layout.addLayout(bottom)

    def _open_donate(self, tier: support.Tier) -> None:
        """Alle Stufen oeffnen dieselbe Zahlungsseite (kein Betrag in der URL)."""
        if support.DONATE_URL:
            QDesktopServices.openUrl(QUrl(support.DONATE_URL))

    def _confirm_supported(self) -> None:
        tier_key = self.tier_combo.currentData()
        if support.record_support(self.config, tier_key, date.today()):
            self.accept()
