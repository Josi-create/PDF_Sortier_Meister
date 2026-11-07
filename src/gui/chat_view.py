"""
ChatView fuer das RAG-Chat-Feature (Phase 19 / M2).

Stellt den Inhalt des Chat-Tabs bereit: Nachrichten-Historie als
Bubbles, ein collapsible Quellen-Panel, eine Eingabezeile und einen
Status-/Banner-Bereich. Der eigentliche RAG-Aufruf laeuft asynchron
ueber :class:`~src.gui.chat_worker.ChatWorker` in einem ``QThread``,
damit die GUI nicht einfriert.

Issue #166/#167 (Werkzeuge im Chat, Phase 2): Die Werkzeugaufrufe des
Modells (``RAGResponse.schritte``) stehen als aufklappbarer Block
"🔧 Arbeitsschritte (n)" vor der Antwort, das Quellen-Panel gruppiert
Dokumente nach ``extra["status"]`` (Zitiert / Gelesen / Gefunden), und
ein eigenes Chat-Modell kommt ueber ``chat_provider_quelle`` vom
MainWindow (``provider_geaendert()`` nach geaenderten Einstellungen).

GPL-3.0-or-later - Copyright (c) 2026
"""

from html import escape
from pathlib import Path
from typing import Any, Callable, Optional

import time

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QScrollArea,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QFrame,
    QSizePolicy,
    QToolButton,
)

from src.gui.chat_worker import ChatWorker
from src.rag.bezug import Bezug, schnellfragen_liste
from src.rag.rag_controller import ABGEBROCHEN_TEXT, RAGController


# Stylesheet-Schnipsel fuer die verschiedenen Bubble-Rollen.
_BUBBLE_STYLES = {
    "user": "background-color: #d6eaff; border-radius: 8px; padding: 8px;",
    "assistant": "background-color: #ececec; border-radius: 8px; padding: 8px;",
    "error": "background-color: #ffd6d6; border-radius: 8px; padding: 8px; color: #8a1f1f;",
    "system": "background-color: #f0f0f0; border-radius: 8px; padding: 6px; color: #555555;",
}

# Arbeitsschritte der Werkzeug-Schleife (Issue #166/#167): eine kompakte Zeile
# je Werkzeugaufruf, Fehler-Schritte in der Fehlerfarbe der Fehler-Bubble.
_SCHRITT_STYLES = {
    "schritt": "background-color: #f0f0f0; border-radius: 6px; padding: 3px 6px; color: #555555;",
    "fehler": "background-color: #ffd6d6; border-radius: 6px; padding: 3px 6px; color: #8a1f1f;",
}

# Symbol je Werkzeug (Namen wie in src/rag/werkzeuge.py); unbekannt -> 🔧
_WERKZEUG_SYMBOLE = {
    "suche": "🔎",
    "dokument_lesen": "📖",
    "ordner_vorschlag": "📁",
    "korrespondent_info": "👤",
    "sql_abfrage": "🗄",
}
_SCHRITT_SYMBOL_STANDARD = "🔧"

# Quellen-Panel: Gruppen nach extra["status"] der Dokumente (Issue #166/#167),
# in dieser Reihenfolge; Dokumente ohne bekannten Status zaehlen als "gefunden".
_STATUS_GRUPPEN = (
    ("zitiert", "Zitiert", "In der Antwort zitiert"),
    ("gelesen", "Gelesen", "Von der KI ganz gelesen, aber nicht zitiert"),
    ("gefunden", "Gefunden", "Bei der Suche gefunden, nicht gelesen"),
)
_STATUS_STANDARD = "gefunden"
# Rolle, die eine Kopfzeile im Quellen-Panel markiert (Klick oeffnet nichts)
_ROLLE_KOPFZEILE = Qt.ItemDataRole.UserRole + 3

# Chip "Bezug: <Datei>  ✕" ueber dem Eingabefeld (Issue #148)
_BEZUG_CHIP_STYLE = (
    "QFrame#bezugChip { background-color: #e7f0fb; border: 1px solid #b6cdea; "
    "border-radius: 10px; }"
)

_BANNER_TEXT = (
    "Kein LLM verfügbar. Du bekommst nur Dokument-Treffer, "
    "keine synthetisierte Antwort."
)


class _ChatInput(QTextEdit):
    """Mehrzeiliges Eingabefeld mit Chat-typischer Tastenbelegung.

    * ``Return`` / ``Enter`` (ohne Modifier) sendet die Frage ab
      (emittiert :attr:`submit`).
    * ``Shift+Return`` fuegt einen Zeilenumbruch ein (Standard-Verhalten).

    Damit verhaelt sich das Feld wie gaengige Chat-Eingaben (z.B. Slack,
    WhatsApp Web) statt wie ein normales Textfeld.
    """

    submit = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt-API)
        is_return = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        shift_held = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if is_return and not shift_held:
            # Return ohne Shift -> absenden, Event nicht weiterreichen
            event.accept()
            self.submit.emit()
            return
        # Shift+Return (oder jede andere Taste) -> normales Verhalten
        super().keyPressEvent(event)


class ChatView(QWidget):
    """Chat-Tab-Inhalt: Bubbles, Quellen-Panel, Eingabe, Status.

    Signale:
        open_pdf_requested(str): Wird mit dem ``file_path`` emittiert,
            wenn eine Citation oder ein Quellen-Eintrag angeklickt wird.
            Das MainWindow verbindet dies mit dem PDF-Oeffnen.
    """

    open_pdf_requested = pyqtSignal(str)
    # Phase 5 (PDFsuche-Integration): PDF direkt auf der Seite der Fundstelle oeffnen
    open_pdf_page_requested = pyqtSignal(str, int)
    # Phase 3 (Issue #166/#167): "Nach … verschieben" unter einer Antwort, deren
    # Belege in einem Zielordner liegen (absoluter Ordnerpfad); und derselbe
    # Ordner als Vorschlag fuer das Detail-Panel (Pfad, Begruendung)
    verschieben_requested = pyqtSignal(str)
    ordner_belegt = pyqtSignal(str, str)

    def __init__(self, db, hybrid_classifier, chat_config, parent=None, kompakt: bool = False):
        """
        Args:
            db: :class:`~src.utils.database.Database`-Instanz.
            hybrid_classifier: :class:`~src.ml.hybrid_classifier.HybridClassifier`
                mit ``.llm_provider`` (ggf. ``None``) und
                ``.is_llm_available()``.
            chat_config: :class:`~src.utils.config.ChatConfig`.
            parent: Optionales Eltern-Widget.
        """
        super().__init__(parent)
        self.db = db
        self.hybrid_classifier = hybrid_classifier
        self.chat_config = chat_config

        # Der RAGController wird lazy erzeugt (beim ersten Senden), weil
        # sich der llm_provider zur Laufzeit aendern kann.
        self._controller: Optional[RAGController] = None
        # Eigenes Chat-Modell (Issue #166/#167): liefert einen LLMProvider oder
        # None (dann gilt das Modell der Sortierung); setzt das MainWindow.
        self.chat_provider_quelle: Optional[Callable[[], Any]] = None
        # ChatSession eines verworfenen Controllers (provider_geaendert), die der
        # naechste Controller uebernimmt, damit der Gespraechsverlauf bleibt.
        self._session_uebernahme = None

        # Referenzen auf Thread + Worker, damit sie nicht vom GC
        # eingesammelt werden, solange der Aufruf laeuft (Architektur R3).
        self._chat_thread: Optional[QThread] = None
        # Laufende Uhr in der Statuszeile waehrend eines KI-Aufrufs (Issue #68)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_base = ""
        self._request_started = None
        self._chat_worker: Optional[ChatWorker] = None
        # Nach einem Abbruch noch laufende Threads samt Worker, bis sie fertig
        # sind (siehe _teardown_thread, Issue #166/#167)
        self._alte_threads: list = []

        # Bezugsdokument (Issue #148): ausgewaehltes PDF beim Wechsel in den Chat
        self._bezug: Optional[Path] = None
        # Liefert Text, KI-Metadaten und Ordnervorschlaege zum Bezug; setzt das
        # MainWindow (gebundene Methode). Ohne Quelle nur der Pfad.
        self.bezug_daten: Optional[Callable[[Path], Bezug]] = None

        # Phase 3 (Issue #166/#167): kompakt = schmale linke Spalte des
        # Vorschau-Reiters (Quellen unter dem Verlauf, Schnellfragen als Menue)
        self.kompakt = bool(kompakt)

        self._build_ui()
        self.refresh_llm_status()

    # ------------------------------------------------------------------ #
    # UI-Aufbau                                                          #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        """Baut das Layout gemaess ARCHITECTURE.md Abschnitt 8 auf."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Banner (oben, standardmaessig versteckt)
        self.banner = QLabel(_BANNER_TEXT)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            "background-color: #fff3cd; color: #664d03; "
            "border: 1px solid #ffe69c; border-radius: 6px; padding: 6px;"
        )
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

        # Split: links Verlauf, rechts Quellen - in der schmalen linken Spalte
        # des Vorschau-Reiters (kompakt, Phase 3) Verlauf oben, Quellen darunter
        self.split = QSplitter(Qt.Orientation.Vertical if self.kompakt else Qt.Orientation.Horizontal)
        layout.addWidget(self.split, 1)

        # Linke Seite: Nachrichten-Historie in einer QScrollArea
        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._history_container = QWidget()
        self.history_layout = QVBoxLayout(self._history_container)
        self.history_layout.setContentsMargins(4, 4, 4, 4)
        self.history_layout.setSpacing(8)
        self.history_layout.addStretch(1)  # Bubbles oben halten
        self.history_scroll.setWidget(self._history_container)
        self.split.addWidget(self.history_scroll)

        # Rechte Seite: Quellen-Panel (collapsible -> startet sichtbar)
        sources_panel = QWidget()
        sources_layout = QVBoxLayout(sources_panel)
        sources_layout.setContentsMargins(2, 2, 2, 2)
        sources_layout.setSpacing(4)

        sources_header = QHBoxLayout()
        self.sources_title = QLabel("Quellen")
        self.sources_title.setStyleSheet("font-weight: bold;")
        self.toggle_sources_btn = QPushButton("▸")
        self.toggle_sources_btn.setFixedWidth(28)
        self.toggle_sources_btn.setToolTip("Quellen-Panel ein-/ausblenden")
        self.toggle_sources_btn.clicked.connect(self._toggle_sources)
        sources_header.addWidget(self.sources_title)
        sources_header.addStretch(1)
        sources_header.addWidget(self.toggle_sources_btn)
        sources_layout.addLayout(sources_header)

        self.sources_list = QListWidget()
        self.sources_list.itemClicked.connect(self._on_source_clicked)
        sources_layout.addWidget(self.sources_list, 1)

        self.split.addWidget(sources_panel)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([600, 250])
        if self.kompakt:
            # Quellen eingeklappt starten; der Knopf klappt sie unter dem Verlauf auf
            self.split.setSizes([520, 140])
            self.sources_list.setVisible(False)

        # Bezug-Chip und Schnellfragen (Issue #148), nur mit Bezugsdokument sichtbar
        self.bezug_box = QWidget()
        bezug_layout = QVBoxLayout(self.bezug_box)
        bezug_layout.setContentsMargins(0, 0, 0, 0)
        bezug_layout.setSpacing(4)

        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        self.bezug_chip = QFrame()
        self.bezug_chip.setObjectName("bezugChip")
        self.bezug_chip.setStyleSheet(_BEZUG_CHIP_STYLE)
        chip_layout = QHBoxLayout(self.bezug_chip)
        chip_layout.setContentsMargins(8, 2, 2, 2)
        chip_layout.setSpacing(4)
        self.bezug_label = QLabel()
        self.bezug_label.setTextFormat(Qt.TextFormat.PlainText)
        chip_layout.addWidget(self.bezug_label)
        self.bezug_entfernen_btn = QToolButton()
        self.bezug_entfernen_btn.setText("✕")
        self.bezug_entfernen_btn.setAutoRaise(True)
        self.bezug_entfernen_btn.setToolTip("Bezug entfernen: Fragen gelten wieder der ganzen Sammlung")
        self.bezug_entfernen_btn.clicked.connect(self._on_bezug_entfernen)
        chip_layout.addWidget(self.bezug_entfernen_btn)
        chip_row.addWidget(self.bezug_chip)
        chip_row.addStretch(1)
        bezug_layout.addLayout(chip_row)

        self.schnellfragen_btns: list[QPushButton] = []
        # Schmale Spalte (Phase 3): Dreieck zum Ein-/Ausklappen der Schnellfragen;
        # None = breiter Reiter. _schnellfragen_manuell: None = automatisch nach
        # der Hoehe (kleiner Monitor -> eingeklappt), sonst die Wahl des Nutzers.
        self.schnellfragen_toggle: Optional[QToolButton] = None
        self.schnellfragen_box: Optional[QWidget] = None
        self._schnellfragen_manuell: Optional[bool] = None
        if self.kompakt:
            self.schnellfragen_toggle = QToolButton()
            self.schnellfragen_toggle.setCheckable(True)
            self.schnellfragen_toggle.setAutoRaise(True)
            self.schnellfragen_toggle.setToolTip("Schnellfragen ein-/ausklappen")
            self.schnellfragen_toggle.setStyleSheet("QToolButton { color: #555555; padding: 2px 4px; }")
            self.schnellfragen_toggle.toggled.connect(self._on_schnellfragen_toggle)
            bezug_layout.addWidget(self.schnellfragen_toggle, 0, Qt.AlignmentFlag.AlignLeft)
            self.schnellfragen_box = QWidget()
            self._schnellfragen_layout = QVBoxLayout(self.schnellfragen_box)
            self._schnellfragen_layout.setContentsMargins(0, 0, 0, 0)
            self._schnellfragen_layout.setSpacing(2)
            bezug_layout.addWidget(self.schnellfragen_box)
            self._schnellfragen_bauen()
            self._schnellfragen_zeigen(True)
        else:
            self._schnellfragen_layout = QGridLayout()
            self._schnellfragen_layout.setContentsMargins(0, 0, 0, 0)
            self._schnellfragen_layout.setHorizontalSpacing(4)
            self._schnellfragen_layout.setVerticalSpacing(4)
            self._schnellfragen_bauen()
            bezug_layout.addLayout(self._schnellfragen_layout)
        self.bezug_box.setVisible(False)
        layout.addWidget(self.bezug_box)

        # Untere Zeile: Eingabe + Buttons
        input_row = QHBoxLayout()
        self.input_edit = _ChatInput()
        self.input_edit.setPlaceholderText(
            "Frage eingeben…  (Return = senden, Shift+Return = neue Zeile)"
        )
        self.input_edit.setMaximumHeight(80)
        self.input_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.input_edit.submit.connect(self._on_send)
        input_row.addWidget(self.input_edit, 1)

        button_col = QVBoxLayout()
        self.send_btn = QPushButton("Senden")
        self.send_btn.clicked.connect(self._on_send)
        self.reset_btn = QPushButton("Zurücksetzen")
        self.reset_btn.clicked.connect(self._on_reset)
        button_col.addWidget(self.send_btn)
        button_col.addWidget(self.reset_btn)
        input_row.addLayout(button_col)
        layout.addLayout(input_row)

        # Status-Zeile
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666666;")
        layout.addWidget(self.status_label)

    # ------------------------------------------------------------------ #
    # Bubbles & Rendering                                                #
    # ------------------------------------------------------------------ #

    def _add_bubble(self, text: str, role: str, citations=None) -> QWidget:
        """Fuegt eine Nachrichten-Bubble in die Historie ein.

        Args:
            text: Anzuzeigender Text.
            role: ``"user"`` (rechts, blau), ``"assistant"`` (links,
                grau), ``"error"`` (links, rot) oder ``"system"``
                (zentriert, grau).
            citations: Optionale Liste von :class:`Citation`. Sind sie
                gesetzt, werden ``[N]``-Marker im Text in klickbare
                Links umgewandelt (assistant-Rolle).

        Returns:
            Das erzeugte Bubble-QLabel.
        """
        bubble = QLabel()
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        bubble.setStyleSheet(
            _BUBBLE_STYLES.get(role, _BUBBLE_STYLES["system"])
        )
        self._bubble_breite(bubble)

        if citations:
            bubble.setText(self._render_citations(text, citations))
            # Phase 3 (Issue #25): Mapping index -> {"file_path", "pdf_id"}.
            # Aelterer Aufrufer (nur file_path als String) wird in
            # ``_on_citation_link`` defensiv gehandhabt.
            cite_map = {
                str(c.index): {
                    "file_path": c.file_path,
                    "pdf_id": getattr(c, "pdf_id", "") or "",
                }
                for c in citations
            }
            bubble.linkActivated.connect(
                lambda href, m=cite_map: self._on_citation_link(href, m)
            )
        else:
            bubble.setText(escape(text).replace("\n", "<br>"))

        # Ausrichtung ueber eine Zeile mit Stretch
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble)
        elif role == "system":
            row.addStretch(1)
            row.addWidget(bubble)
            row.addStretch(1)
        else:  # assistant, error -> links
            row.addWidget(bubble)
            row.addStretch(1)

        wrapper = QWidget()
        wrapper.setLayout(row)
        # Vor dem abschliessenden Stretch einfuegen
        self.history_layout.insertWidget(
            self.history_layout.count() - 1, wrapper
        )
        self._scroll_to_bottom()
        return bubble

    def _render_citations(self, text: str, citations) -> str:
        """Wandelt ``[N]``-Marker in klickbare HTML-Links um."""
        valid_indices = {str(c.index) for c in citations if c.valid}
        escaped = escape(text)

        # Marker [N] ersetzen. Nur gueltige Indizes werden verlinkt.
        import re

        def repl(match):
            idx = match.group(1)
            if idx in valid_indices:
                return (
                    f'<a href="{idx}" style="text-decoration:none;'
                    f'color:#1a5fb4;font-weight:bold;">{match.group(0)}</a>'
                )
            return match.group(0)

        # ``[7]`` wie ``[D7]`` (Issue #166/#167: Modelle zitieren die D-Nummern)
        rendered = re.sub(r"\[[Dd]?(\d+)\]", repl, escaped)
        return rendered.replace("\n", "<br>")

    def _scroll_to_bottom(self) -> None:
        """Scrollt die Historie ans Ende."""
        bar = self.history_scroll.verticalScrollBar()
        # Nach dem Layout-Durchlauf ans Ende scrollen
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------ #
    # Senden / Worker-Lifecycle                                          #
    # ------------------------------------------------------------------ #

    def _on_send(self) -> None:
        """Startet einen RAG-Aufruf fuer die eingegebene Frage."""
        # Laeuft bereits ein Aufruf? Dann fungiert der Button als Abbrechen.
        if self._chat_thread is not None:
            self._cancel_current()
            return

        question = self.input_edit.toPlainText().strip()
        if not question:
            return
        self.input_edit.clear()

        self._add_bubble(question, "user")

        # RAGController lazy erzeugen (llm_provider kann sich aendern)
        if self._controller is None:
            self._controller = self._controller_bauen()

        # UI in den Lade-Zustand versetzen.
        # Busy: Cancel-Button enabled (Label "Abbrechen"), Senden-Logik
        # deaktiviert (input_edit disabled, reset disabled). Der
        # send_btn bleibt klickbar, loest dann aber ``_cancel_current`` aus.
        self.input_edit.setEnabled(False)
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Abbrechen")
        self.reset_btn.setEnabled(False)
        self._status_base = "Suche läuft…"
        self._request_started = time.monotonic()
        self._tick_status()
        self._status_timer.start()

        self._schnellfragen_freigeben(False)

        # Thread + Worker aufsetzen (moveToThread-Pattern)
        self._chat_thread = QThread()
        self._chat_worker = ChatWorker(self._controller, question, bezug=self._bezug_fuer_frage())
        self._chat_worker.moveToThread(self._chat_thread)

        self._chat_thread.started.connect(self._chat_worker.run)
        self._chat_worker.progress.connect(self._on_worker_progress)
        self._chat_worker.finished.connect(self._on_worker_finished)
        self._chat_worker.failed.connect(self._on_worker_failed)

        self._chat_thread.start()

    def _on_worker_progress(self, message: str) -> None:
        """Aktualisiert die Status-Zeile waehrend des Aufrufs.

        Meldungen eines abgebrochenen Workers (er laeuft bis zum Ende seines
        Schritts weiter) werden ignoriert, wie bei ``finished``/``failed``.
        """
        sender = self.sender()  # None bei direktem Aufruf (Tests), sonst der Worker
        if sender is not None and sender is not self._chat_worker:
            return
        self._status_base = message
        self._tick_status()

    def _tick_status(self) -> None:
        """Statuszeile mit laufender Uhr und Schaetzung (Issue #68)."""
        if self._request_started is None:
            return
        from src.core.llm_activity import (
            KIND_CHAT, format_elapsed, format_estimate, get_llm_activity,
        )
        elapsed = time.monotonic() - self._request_started
        text = f"{self._status_base} seit {format_elapsed(elapsed)}"
        estimate = format_estimate(get_llm_activity().estimate(KIND_CHAT))
        if estimate:
            text += f" · {estimate}"
        self.status_label.setText(text)

    def _on_worker_finished(self, response) -> None:
        """Rendert die Antwort und raeumt den Thread auf."""
        # Signal-Safety (M3-Hardening): Wenn der Sender nicht mehr der
        # aktuelle Worker ist, wurde der Aufruf bereits abgebrochen.
        # Das Signal ist dann stale und darf das Rendering nicht
        # ueberschreiben.
        if self._chat_worker is None or self.sender() is not self._chat_worker:
            return
        self._teardown_thread()
        self._reset_input_state()
        self._zeige_antwort(response)

    def _zeige_antwort(self, response) -> None:
        """Rendert eine ``RAGResponse``: Arbeitsschritte, Antwort-Bubble(s), Quellen.

        Issue #166/#167: Die Werkzeugaufrufe des Modells (``response.schritte``)
        stehen VOR der Antwort - in der Reihenfolge des Gespraechs. Auch bei
        "Abgebrochen." oder einem Werkzeugfehler (``werkzeuge_benutzt`` ohne
        ``used_llm``) werden die bis dahin gelaufenen Schritte gezeigt.
        """
        schritte = list(getattr(response, "schritte", None) or [])
        if schritte:
            self._add_schritte(schritte)

        if getattr(response, "used_llm", False):
            self._add_bubble(
                response.answer_text,
                "assistant",
                citations=response.citations,
            )
            self._zeige_ordner_vorschlag(response)
            if getattr(response, "has_hallucinated_citations", False):
                self._add_bubble(
                    "⚠ Einige Quellenangaben konnten nicht verifiziert "
                    "werden.",
                    "system",
                )
        elif getattr(response, "werkzeuge_benutzt", False):
            # Werkzeug-Weg ohne Endantwort: Abbruch (System-Bubble) oder
            # "Werkzeugaufruf fehlgeschlagen: ..." (Fehler-Bubble). Kein
            # Offline-Hinweis - ein LLM war ja da.
            text = (getattr(response, "answer_text", "") or "").strip()
            if text == ABGEBROCHEN_TEXT:
                self._add_bubble(text, "system")
            else:
                self._add_bubble(text or "Keine Antwort erhalten.", "error")
        else:
            # Offline-Modus: Treffer-Liste als klickbare Bubbles rendern
            docs = response.retrieved_docs or []
            hinweis = getattr(response, "hinweis", "") or ""
            if hinweis:
                # z.B. Vorschlag der Sortierlogik zum Bezugsdokument (Issue #148)
                self._add_bubble(hinweis, "system")
            if not docs:
                self._add_bubble(
                    "Keine passenden Dokumente gefunden.", "system"
                )
            else:
                self._add_bubble(
                    "Kein LLM verfügbar – hier sind die passenden "
                    "Dokument-Treffer:",
                    "system",
                )
                for doc in docs:
                    self._add_doc_bubble(doc)

        self._populate_sources(response.retrieved_docs or [])

    # ------------------------------------------------------------------ #
    # Arbeitsschritte der Werkzeug-Schleife (Issue #166/#167)            #
    # ------------------------------------------------------------------ #

    def _add_schritte(self, schritte) -> QWidget:
        """Block "🔧 Arbeitsschritte (n)" mit einer Zeile je Werkzeugaufruf.

        Der Knopf ist checkable (Pfeil ▾ = aufgeklappt, ▸ = zugeklappt) und
        blendet die Schritt-Bubbles aus und ein; Standard: sichtbar.

        Args:
            schritte: Liste von :class:`~src.rag.werkzeuge.Schritt` (oder
                Objekten mit ``werkzeug``, ``zusammenfassung``, ``fehler``).

        Returns:
            Das Wrapper-Widget in der Historie (Knopf + Schritt-Box).
        """
        schritte = list(schritte)
        wrapper = QWidget()
        aussen = QVBoxLayout(wrapper)
        aussen.setContentsMargins(0, 0, 0, 0)
        aussen.setSpacing(2)

        knopf = QToolButton()
        knopf.setCheckable(True)
        knopf.setAutoRaise(True)
        knopf.setToolTip("Werkzeugaufrufe der KI ein-/ausblenden")
        knopf.setProperty("arbeitsschritte", True)
        knopf.setStyleSheet("QToolButton { color: #555555; padding: 2px 4px; }")
        aussen.addWidget(knopf, 0, Qt.AlignmentFlag.AlignLeft)

        box = QWidget()
        box.setProperty("schritte_box", True)
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(16, 0, 0, 0)
        box_layout.setSpacing(2)
        for schritt in schritte:
            zeile = QHBoxLayout()
            zeile.setContentsMargins(0, 0, 0, 0)
            zeile.addWidget(self._schritt_bubble(schritt))
            zeile.addStretch(1)
            box_layout.addLayout(zeile)
        aussen.addWidget(box)

        anzahl = len(schritte)

        def umschalten(sichtbar: bool) -> None:
            box.setVisible(sichtbar)
            pfeil = "▾" if sichtbar else "▸"
            knopf.setText(f"{pfeil} 🔧 Arbeitsschritte ({anzahl})")

        knopf.toggled.connect(umschalten)
        knopf.setChecked(True)
        umschalten(True)

        self.history_layout.insertWidget(
            self.history_layout.count() - 1, wrapper
        )
        self._scroll_to_bottom()
        return wrapper

    def _schritt_bubble(self, schritt) -> QLabel:
        """Kompakte System-Bubble fuer einen Schritt: Symbol + Zusammenfassung.

        Fehler-Schritte (``schritt.fehler`` gesetzt) erscheinen in der
        Fehlerfarbe; der Tooltip zeigt Werkzeug und Argumente.
        """
        werkzeug = str(getattr(schritt, "werkzeug", "") or "")
        fehler = str(getattr(schritt, "fehler", "") or "")
        text = str(getattr(schritt, "zusammenfassung", "") or "").strip()
        if not text:
            text = fehler or werkzeug or "Werkzeugaufruf"
        symbol = _WERKZEUG_SYMBOLE.get(werkzeug, _SCHRITT_SYMBOL_STANDARD)

        bubble = QLabel()
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        bubble.setStyleSheet(_SCHRITT_STYLES["fehler" if fehler else "schritt"])
        self._bubble_breite(bubble)
        bubble.setText(f"{symbol} {escape(text)}")
        bubble.setProperty("schritt", True)
        bubble.setProperty("fehler", bool(fehler))
        bubble.setToolTip(_schritt_tooltip(werkzeug, getattr(schritt, "argumente", None), fehler))
        return bubble

    def _add_doc_bubble(self, doc) -> None:
        """Rendert einen ``RetrievedDoc`` als klickbare Treffer-Bubble."""
        meta_parts = [
            p
            for p in (doc.kategorie, doc.steuerjahr, doc.betrag)
            if p
        ]
        meta = " | ".join(meta_parts)
        header = f"📄 {escape(doc.filename)}"
        if meta:
            header += f" — {escape(meta)}"
        snippet = escape((doc.text_snippet or "")[:300])

        html = (
            f'<a href="{escape(doc.file_path)}" '
            f'style="text-decoration:none;color:#1a5fb4;font-weight:bold;">'
            f"{header}</a>"
        )
        if snippet:
            html += f'<br><span style="color:#555555;">{snippet}</span>'

        bubble = QLabel()
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        bubble.setStyleSheet(_BUBBLE_STYLES["assistant"])
        self._bubble_breite(bubble)
        bubble.setText(html)
        bubble.linkActivated.connect(
            lambda href: self.open_pdf_requested.emit(href)
        )

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(bubble)
        row.addStretch(1)
        wrapper = QWidget()
        wrapper.setLayout(row)
        self.history_layout.insertWidget(
            self.history_layout.count() - 1, wrapper
        )
        self._scroll_to_bottom()

    def _on_worker_failed(self, error: str) -> None:
        """Zeigt eine Fehler-Bubble und raeumt den Thread auf."""
        # Signal-Safety (M3-Hardening): Stale-Signal-Schutz (siehe finished).
        if self._chat_worker is None or self.sender() is not self._chat_worker:
            return
        self._teardown_thread()
        self._reset_input_state()
        self._add_bubble(f"Fehler: {error}", "error")

    def _cancel_current(self) -> None:
        """Bricht den laufenden Aufruf ab (verwirft das Ergebnis).

        M3-Hardening:
        * send_btn wird sofort deaktiviert, damit kein Doppel-Klick
          einen zweiten Cancel-Vorgang startet.
        * Erst nach einem kurzen Cooldown (500ms) wird der Button
          wieder aktiviert, sodass der User Zeit hat, die Aktion
          visuell zu verarbeiten.

        Wichtig: Hier wird bewusst NICHT ``_reset_input_state`` gerufen,
        weil dieses den send_btn sofort wieder aktiviert und damit den
        Cooldown aushebelt. Stattdessen nur das noetige Mindest-Reset
        (input_edit freigeben, Status-Label setzen, Button-Text
        zuruecksetzen). Das Aktivieren des send_btn uebernimmt dann
        ``_re_enable_send_btn`` nach Ablauf des Cooldowns.
        """
        if self._chat_worker is not None:
            self._chat_worker.cancel()
        self.status_label.setText("Abgebrochen.")
        # Cancel-Button sofort deaktivieren (Cooldown startet)
        self.send_btn.setEnabled(False)
        # Minimal-Reset: input_edit freigeben, Button-Text zurueck,
        # reset_btn wieder aktivieren. send_btn bleibt disabled.
        self.input_edit.setEnabled(True)
        self.input_edit.setFocus()
        self.send_btn.setText("Senden")
        self.reset_btn.setEnabled(True)
        self._schnellfragen_freigeben(True)
        self._teardown_thread()
        # Cooldown: nach 500ms den Button wieder aktivieren
        QTimer.singleShot(500, self._re_enable_send_btn)

    def _re_enable_send_btn(self) -> None:
        """Weckt den send_btn nach dem Cancel-Cooldown wieder auf."""
        self.send_btn.setEnabled(True)

    def _teardown_thread(self) -> None:
        """Stoppt den QThread und gibt die Referenzen frei."""
        self._status_timer.stop()
        self._request_started = None
        thread = self._chat_thread
        worker = self._chat_worker
        self._chat_thread = None
        self._chat_worker = None
        if thread is not None:
            thread.quit()
            if not thread.wait(2000):
                # Der Worker steckt noch in einem Modell- oder Werkzeugaufruf
                # (Abbrechen waehrend eines langen Schritts, Issue #166/#167):
                # deleteLater auf einem laufenden QThread beendet das Programm
                # (qFatal). Thread und Worker bleiben referenziert und werden
                # erst freigegeben, wenn der Thread wirklich zu Ende ist.
                self._alte_threads.append((thread, worker))
                thread.finished.connect(
                    lambda t=thread, w=worker: self._alten_thread_freigeben(t, w)
                )
                return
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()

    def _alten_thread_freigeben(self, thread, worker) -> None:
        """Ein nach dem Abbruch weitergelaufener Thread ist fertig: jetzt freigeben."""
        self._alte_threads = [(t, w) for t, w in self._alte_threads if t is not thread]
        thread.deleteLater()
        if worker is not None:
            worker.deleteLater()

    def _reset_input_state(self) -> None:
        """Setzt Eingabe + Buttons in den Ruhezustand.

        M3-Hardening: ``input_edit`` wird immer reaktiviert (auch wenn
        ``_reset_input_state`` aus dem Cancel-Pfad aufgerufen wurde) und
        der send_btn wird aktiviert, damit der User sofort eine neue
        Frage stellen kann.
        """
        self.input_edit.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Senden")
        self.reset_btn.setEnabled(True)
        self._schnellfragen_freigeben(True)
        self.status_label.setText("")
        self.input_edit.setFocus()

    # ------------------------------------------------------------------ #
    # Bezugsdokument (Issue #148)                                        #
    # ------------------------------------------------------------------ #

    @property
    def bezug(self) -> Optional[Path]:
        """Das aktuelle Bezugsdokument (oder None)."""
        return self._bezug

    def set_bezug(self, path) -> None:
        """Setzt das Bezugsdokument; ``None`` entfernt Chip und Schnellfragen.

        Der Bezug gilt fuer alle folgenden Fragen, bis ✕ geklickt oder beim
        naechsten Wechsel in den Chat ein anderes PDF uebergeben wird.
        """
        self._bezug = Path(path) if path else None
        if self._bezug is None:
            self.bezug_label.clear()
            self.bezug_chip.setToolTip("")
            self.bezug_box.setVisible(False)
            return
        self.bezug_label.setText(f"Bezug: {self._bezug.name}")
        self.bezug_chip.setToolTip(
            f"{self._bezug}\nFragen beziehen sich auf dieses PDF; "
            "ähnliche Dokumente kommen aus der Sammlung dazu."
        )
        self.bezug_box.setVisible(True)

    def _on_bezug_entfernen(self) -> None:
        """✕ am Chip: Fragen gelten wieder der ganzen Sammlung."""
        self.set_bezug(None)
        self.input_edit.setFocus()

    def _on_schnellfrage(self) -> None:
        """Schnellfrage-Knopf: Frage eintragen und sofort senden."""
        btn = self.sender()
        frage = btn.property("frage") if btn is not None else None
        self._on_schnellfrage_text(frage)

    def _on_schnellfrage_text(self, frage) -> None:
        """Schnellfrage (Knopf oder Menueeintrag) eintragen und sofort senden."""
        if not frage or self._chat_thread is not None:
            return
        self.input_edit.setPlainText(str(frage))
        self._on_send()

    def _schnellfragen_freigeben(self, aktiv: bool) -> None:
        """Schnellfragen waehrend eines Aufrufs sperren."""
        for btn in self.schnellfragen_btns:
            btn.setEnabled(aktiv)

    def _schnellfragen_bauen(self) -> None:
        """Knoepfe aus den Schnellfragen der Konfiguration (Phase 3, Issue #166) neu aufbauen.

        Kompakt untereinander, im breiten Reiter als Raster mit zwei Spalten.
        Eigene Fragen kommen aus ``ChatConfig.schnellfragen``, sonst gelten die
        Standardfragen (:func:`~src.rag.bezug.schnellfragen_liste`).
        """
        for btn in self.schnellfragen_btns:
            self._schnellfragen_layout.removeWidget(btn)
            btn.deleteLater()
        self.schnellfragen_btns = []
        for i, frage in enumerate(schnellfragen_liste(self.chat_config)):
            btn = QPushButton(frage)
            btn.setProperty("frage", frage)
            btn.setToolTip("Frage zum Bezugsdokument stellen")
            btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(self._on_schnellfrage)
            if isinstance(self._schnellfragen_layout, QGridLayout):
                self._schnellfragen_layout.addWidget(btn, i // 2, i % 2)
            else:
                self._schnellfragen_layout.addWidget(btn)
            self.schnellfragen_btns.append(btn)

    def konfig_geaendert(self, chat_config) -> None:
        """Einstellungen gespeichert: neue ChatConfig uebernehmen (Schnellfragen, Werkzeuge, Modell).

        Baut die Schnellfragen neu und verwirft den Controller wie
        :meth:`provider_geaendert`, damit auch Werkzeug-Einstellungen und das
        Chat-Modell ab der naechsten Frage gelten.
        """
        if chat_config is not None:
            self.chat_config = chat_config
        self._schnellfragen_bauen()
        self.provider_geaendert()

    # Ab dieser Hoehe der Chat-Spalte bleiben die Schnellfragen von selbst
    # ausgeklappt (kompakt); darunter, etwa auf einem kleinen Monitor, klappen
    # sie ein, bis der Nutzer das Dreieck anklickt
    SCHNELLFRAGEN_MIN_HOEHE = 560

    def _on_schnellfragen_toggle(self, sichtbar: bool) -> None:
        """Dreieck geklickt: die Wahl des Nutzers gilt ab jetzt vor der Automatik."""
        self._schnellfragen_manuell = sichtbar
        self._schnellfragen_zeigen(sichtbar)

    def _schnellfragen_zeigen(self, sichtbar: bool) -> None:
        """Schnellfragen ein- oder ausklappen (nur kompakt); Dreieck und Haekchen nachziehen."""
        if self.schnellfragen_box is None or self.schnellfragen_toggle is None:
            return
        self.schnellfragen_box.setVisible(sichtbar)
        self.schnellfragen_toggle.setText(("▾ " if sichtbar else "▸ ") + "Schnellfragen")
        if self.schnellfragen_toggle.isChecked() != sichtbar:
            self.schnellfragen_toggle.blockSignals(True)
            self.schnellfragen_toggle.setChecked(sichtbar)
            self.schnellfragen_toggle.blockSignals(False)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt-API)
        super().resizeEvent(event)
        if self.kompakt and self.schnellfragen_box is not None and self._schnellfragen_manuell is None:
            self._schnellfragen_zeigen(event.size().height() >= self.SCHNELLFRAGEN_MIN_HOEHE)

    def _bubble_breite(self, bubble: QLabel) -> None:
        """Bubbles im breiten Reiter begrenzen; in der schmalen Spalte (kompakt) volle Breite."""
        if not self.kompakt:
            bubble.setMaximumWidth(720)

    # ------------------------------------------------------------------ #
    # Zielordner der Belege (Phase 3)                                    #
    # ------------------------------------------------------------------ #

    def _zeige_ordner_vorschlag(self, response) -> None:
        """Knopf "Nach … verschieben" unter einer Antwort, deren Belege in einem Zielordner liegen.

        Gleichzeitig geht ``ordner_belegt`` ans Hauptfenster, damit der Ordner
        im Detail-Panel als Vorschlag erscheint. Nur mit Bezugsdokument - der
        Knopf verschiebt genau dieses.
        """
        pfad = str(getattr(response, "ordner_vorschlag", "") or "")
        if not pfad or self._bezug is None:
            return
        anzeige = str(getattr(response, "ordner_anzeige", "") or "") or Path(pfad).name
        begruendung = str(getattr(response, "ordner_begruendung", "") or "")
        self.ordner_belegt.emit(pfad, begruendung)

        knopf = QPushButton(f"📁 Nach {anzeige} verschieben")
        knopf.setProperty("ordner_pfad", pfad)
        knopf.setToolTip(f"{self._bezug.name} nach {pfad} verschieben"
                         + (f"\n{begruendung}" if begruendung else ""))
        knopf.setStyleSheet("QPushButton { padding: 4px 10px; }")
        knopf.clicked.connect(lambda _checked=False, p=pfad: self.verschieben_requested.emit(p))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(knopf)
        row.addStretch(1)
        wrapper = QWidget()
        wrapper.setProperty("ordner_vorschlag", True)
        wrapper.setLayout(row)
        self.history_layout.insertWidget(self.history_layout.count() - 1, wrapper)
        self._scroll_to_bottom()

    def _bezug_fuer_frage(self) -> Optional[Bezug]:
        """Bezug fuer den naechsten Aufruf, mit den Daten aus der GUI (falls bekannt)."""
        if self._bezug is None:
            return None
        if self.bezug_daten is not None:
            try:
                daten = self.bezug_daten(self._bezug)
                if daten is not None:
                    return daten
            except Exception:  # noqa: BLE001 - Zusatzdaten sind optional
                pass
        return Bezug(pfad=self._bezug)

    # ------------------------------------------------------------------ #
    # Quellen-Panel                                                      #
    # ------------------------------------------------------------------ #

    def _populate_sources(self, docs) -> None:
        """Fuellt das rechte Quellen-Panel mit allen retrieved docs.

        Issue #166/#167: Tragen die Dokumente ``extra["status"]`` (Werkzeug-Weg),
        stehen sie unter den Kopfzeilen "Zitiert", "Gelesen", "Gefunden" (nur
        nicht-leere Gruppen, in dieser Reihenfolge); sonst wie bisher flach.
        """
        self.sources_list.clear()
        anzahl = len(list(docs or []))
        self.sources_title.setText(f"Quellen ({anzahl})" if anzahl else "Quellen")
        docs = list(docs or [])
        if not any(_doc_status(doc) for doc in docs):
            for doc in docs:
                self.sources_list.addItem(self._quellen_eintrag(doc))
            return
        for status, titel, tooltip in _STATUS_GRUPPEN:
            gruppe = [doc for doc in docs if (_doc_status(doc) or _STATUS_STANDARD) == status]
            if not gruppe:
                continue
            self.sources_list.addItem(_kopfzeile(titel, tooltip))
            for doc in gruppe:
                self.sources_list.addItem(self._quellen_eintrag(doc))

    def _quellen_eintrag(self, doc) -> QListWidgetItem:
        """Ein Quellen-Eintrag "D<n>: <Datei>  (S. x)  (Meta)  [#id…]" mit Pfad-Daten."""
        meta_parts = [
            p for p in (doc.kategorie, doc.steuerjahr, doc.betrag) if p
        ]
        label = f"D{doc.index}: {doc.filename}"
        seite = int(getattr(doc, "seite", 0) or 0)
        if seite > 0:
            label += f"  (S. {seite})"
        if meta_parts:
            label += f"  ({' | '.join(meta_parts)})"
        # Phase 3 (Issue #25): gekuerzte pdf_id im Label, sofern vorhanden.
        pdf_id = getattr(doc, "pdf_id", "") or ""
        if pdf_id:
            short_id = pdf_id[:8] if len(pdf_id) >= 8 else pdf_id
            label += f"  [#{short_id}…]"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, doc.file_path)
        # Phase 3 (Issue #25): pdf_id in einer zusaetzlichen Rolle
        # speichern, damit _on_source_clicked sie bevorzugt
        # auswerten kann.
        if pdf_id:
            item.setData(Qt.ItemDataRole.UserRole + 1, pdf_id)
        item.setData(Qt.ItemDataRole.UserRole + 2, seite)
        # toolTip enthaelt Pfad + pdf_id (falls vorhanden)
        tooltip = doc.file_path
        if pdf_id:
            tooltip = (
                f"{tooltip}\npdf_id: {pdf_id}" if tooltip
                else f"pdf_id: {pdf_id}"
            )
        item.setToolTip(tooltip)
        return item

    def _on_source_clicked(self, item: QListWidgetItem) -> None:
        """Oeffnet die zum Quellen-Eintrag gehoerende PDF.

        Phase 3 (Issue #25): Wenn der Eintrag eine ``pdf_id`` hat,
        wird diese bevorzugt (DB-Lookup holt den aktuellen Pfad),
        damit z.B. nach einem Move die korrekte Datei geoeffnet wird.
        Fallback: ``file_path`` (alter Pfad) wird verwendet.
        Kopfzeilen der Gruppen (Issue #166/#167) oeffnen nichts.
        """
        if item is None or item.data(_ROLLE_KOPFZEILE):
            return
        file_path = item.data(Qt.ItemDataRole.UserRole)
        pdf_id = item.data(Qt.ItemDataRole.UserRole + 1)
        seite = item.data(Qt.ItemDataRole.UserRole + 2) or 0
        resolved = self._resolve_file_path(file_path, pdf_id)
        if resolved:
            self._oeffnen(resolved, int(seite))

    def _oeffnen(self, pfad: str, seite: int = 0) -> None:
        """PDF oeffnen; mit bekannter Seite direkt auf der Fundstelle (Phase 5)."""
        if seite and seite > 0:
            self.open_pdf_page_requested.emit(pfad, int(seite))
        else:
            self.open_pdf_requested.emit(pfad)

    def _on_citation_link(self, href: str, cite_map: dict) -> None:
        """Mappt einen geklickten Citation-Link auf eine PDF.

        Phase 3 (Issue #25): ``cite_map`` enthaelt jetzt optional die
        ``pdf_id`` als Value (siehe ``_add_bubble``). Wenn vorhanden,
        wird die pdf_id bevorzugt (DB-Lookup), sonst der alte
        ``file_path``-Wert. So funktionieren alte Aufrufer weiterhin.
        """
        if not cite_map:
            return
        entry = cite_map.get(href)
        if not entry:
            return
        # Rueckwaertskompatibel: alter Aufrufer uebergibt einen
        # reinen ``file_path``-String, neue Aufrufer ein Dict mit
        # ``file_path`` und ``pdf_id``.
        if isinstance(entry, dict):
            file_path = entry.get("file_path", "")
            pdf_id = entry.get("pdf_id", "")
            seite = int(entry.get("seite", 0) or 0)
        else:
            file_path = entry
            pdf_id = ""
            seite = 0
        resolved = self._resolve_file_path(file_path, pdf_id)
        if resolved:
            self._oeffnen(resolved, seite)

    def _resolve_file_path(
        self, file_path: str = "", pdf_id: str = ""
    ) -> str:
        """Loest einen zu oeffnenden Dateipfad auf.

        Reihenfolge:
        1. ``pdf_id`` (falls gesetzt) -> DB-Lookup via
           ``db.search_documents(pdf_id=...)`` -> nimmt den
           ``file_path`` des ersten Treffers.
        2. ``file_path`` (Fallback) -> direkt verwenden.

        Defensiv: DB-Fehler werden geschluckt, damit der Fallback
        greift. Liefert einen leeren String, wenn beides fehlschlaegt.
        """
        if pdf_id:
            try:
                if self.db is not None and hasattr(self.db, "search_documents"):
                    results = self.db.search_documents("", pdf_id=pdf_id) or []
                    if results:
                        rp = results[0].get("file_path", "")
                        if rp:
                            return rp
            except Exception:  # noqa: BLE001 - defensiv
                pass
        return file_path or ""

    def _toggle_sources(self) -> None:
        """Blendet die Quellen-Liste ein/aus (collapsible)."""
        visible = self.sources_list.isVisible()
        self.sources_list.setVisible(not visible)
        self.toggle_sources_btn.setText("▸" if visible else "▾")

    # ------------------------------------------------------------------ #
    # Reset & Status                                                     #
    # ------------------------------------------------------------------ #

    def _on_reset(self) -> None:
        """Loescht Historie + Quellen und setzt die Session zurueck."""
        # Alle Bubbles entfernen (der abschliessende Stretch bleibt)
        while self.history_layout.count() > 1:
            item = self.history_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.sources_list.clear()
        if self._controller is not None:
            self._controller.reset()
        # Ein verworfener Controller hinterlaesst keinen Verlauf mehr
        self._session_uebernahme = None
        self.status_label.setText("")

    def refresh_llm_status(self) -> None:
        """Zeigt/versteckt das Banner je nach LLM-Verfuegbarkeit.

        Sollte aufgerufen werden, sobald der Chat-Tab sichtbar wird.
        Issue #166/#167: Das Banner erscheint nur, wenn weder das eigene
        Chat-Modell (``chat_provider_quelle``, ``is_available()``) noch das
        Modell der Sortierung (``hybrid_classifier``) verfuegbar ist.
        """
        available = self._chat_provider_verfuegbar()
        if not available:
            try:
                available = bool(self.hybrid_classifier.is_llm_available())
            except Exception:  # noqa: BLE001 - defensiv
                available = False
        self.banner.setVisible(not available)

    # ------------------------------------------------------------------ #
    # Chat-Provider (Issue #166/#167)                                     #
    # ------------------------------------------------------------------ #

    def provider_geaendert(self) -> None:
        """Einstellungen geaendert: Controller verwerfen, Banner nachziehen.

        Die naechste Frage baut den Controller mit dem aktuellen Provider
        neu; die :class:`~src.rag.chat_session.ChatSession` des alten
        Controllers wird dabei uebernommen, damit der Verlauf bleibt. Ein
        gerade laufender Aufruf behaelt seinen Controller.
        """
        alt = self._controller
        self._controller = None
        if alt is not None:
            session = getattr(alt, "chat_session", None)
            if session is not None:
                self._session_uebernahme = session
        self.refresh_llm_status()

    def _chat_provider(self):
        """Provider des eigenen Chat-Modells aus ``chat_provider_quelle``; None, wenn keiner."""
        quelle = self.chat_provider_quelle
        if quelle is None:
            return None
        try:
            return quelle()
        except Exception:  # noqa: BLE001 - defensiv, Rueckfall auf die Sortierung
            return None

    def _chat_provider_verfuegbar(self) -> bool:
        """True, wenn ein eigener Chat-Provider da ist und ``is_available()`` sagt."""
        return self._verfuegbar(self._chat_provider())

    @staticmethod
    def _verfuegbar(provider) -> bool:
        if provider is None:
            return False
        try:
            return bool(provider.is_available())
        except Exception:  # noqa: BLE001 - defensiv
            return False

    def _llm_provider_fuer_chat(self):
        """Provider fuer den RAGController: Chat-Modell, sonst das der Sortierung.

        Ein Chat-Provider, der ``is_available()`` verneint (z.B. Paket fehlt,
        Key leer), wird uebergangen - sonst liefe jede Frage im Offline-Pfad,
        waehrend das Banner wegen des Sortier-Modells aus bleibt (Review-Befund).
        """
        provider = self._chat_provider()
        if provider is not None and self._verfuegbar(provider):
            return provider
        return getattr(self.hybrid_classifier, "llm_provider", None)

    def _controller_bauen(self) -> RAGController:
        """Neuer RAGController; uebernimmt ggf. die Session des verworfenen Controllers."""
        controller = RAGController(
            self.db, self._llm_provider_fuer_chat(), self.chat_config
        )
        session = self._session_uebernahme
        self._session_uebernahme = None
        if session is not None:
            controller.chat_session = session
        return controller


# ---------------------------------------------------------------------- #
# Modul-Helfer (Issue #166/#167)                                         #
# ---------------------------------------------------------------------- #


def _doc_status(doc) -> str:
    """``extra["status"]`` eines Dokuments (zitiert/gelesen/gefunden), sonst leer."""
    extra = getattr(doc, "extra", None)
    if not isinstance(extra, dict):
        return ""
    status = str(extra.get("status") or "").strip().lower()
    if status and status not in {s for s, _t, _tip in _STATUS_GRUPPEN}:
        return _STATUS_STANDARD
    return status


def _kopfzeile(titel: str, tooltip: str = "") -> QListWidgetItem:
    """Nicht waehlbare, fette Kopfzeile fuer das Quellen-Panel (ohne Pfad-Daten)."""
    item = QListWidgetItem(titel)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    font = QFont(item.font())
    font.setBold(True)
    item.setFont(font)
    item.setData(_ROLLE_KOPFZEILE, True)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def _schritt_tooltip(werkzeug: str, argumente, fehler: str = "") -> str:
    """Tooltip eines Schritts: ``suche(abfrage=226541, typ=office)`` plus Fehlerzeile."""
    teile = []
    if isinstance(argumente, dict) and argumente:
        for schluessel, wert in argumente.items():
            wert_text = " ".join(str(wert).split())
            if len(wert_text) > 80:
                wert_text = wert_text[:77] + "…"
            teile.append(f"{schluessel}={wert_text}")
    text = f"{werkzeug or 'Werkzeug'}({', '.join(teile)})"
    if fehler:
        text += f"\n{fehler}"
    return text
