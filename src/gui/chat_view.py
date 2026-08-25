"""
ChatView fuer das RAG-Chat-Feature (Phase 19 / M2).

Stellt den Inhalt des Chat-Tabs bereit: Nachrichten-Historie als
Bubbles, ein collapsible Quellen-Panel, eine Eingabezeile und einen
Status-/Banner-Bereich. Der eigentliche RAG-Aufruf laeuft asynchron
ueber :class:`~src.gui.chat_worker.ChatWorker` in einem ``QThread``,
damit die GUI nicht einfriert.

MIT License - Copyright (c) 2026
"""

from html import escape
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QScrollArea,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QFrame,
    QSizePolicy,
)

from src.gui.chat_worker import ChatWorker
from src.rag.rag_controller import RAGController


# Stylesheet-Schnipsel fuer die verschiedenen Bubble-Rollen.
_BUBBLE_STYLES = {
    "user": "background-color: #d6eaff; border-radius: 8px; padding: 8px;",
    "assistant": "background-color: #ececec; border-radius: 8px; padding: 8px;",
    "error": "background-color: #ffd6d6; border-radius: 8px; padding: 8px; color: #8a1f1f;",
    "system": "background-color: #f0f0f0; border-radius: 8px; padding: 6px; color: #555555;",
}

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

    def __init__(self, db, hybrid_classifier, chat_config, parent=None):
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

        # Referenzen auf Thread + Worker, damit sie nicht vom GC
        # eingesammelt werden, solange der Aufruf laeuft (Architektur R3).
        self._chat_thread: Optional[QThread] = None
        self._chat_worker: Optional[ChatWorker] = None

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

        # Horizontaler Split: links Verlauf, rechts Quellen
        self.split = QSplitter(Qt.Orientation.Horizontal)
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
        sources_title = QLabel("Quellen")
        sources_title.setStyleSheet("font-weight: bold;")
        self.toggle_sources_btn = QPushButton("▸")
        self.toggle_sources_btn.setFixedWidth(28)
        self.toggle_sources_btn.setToolTip("Quellen-Panel ein-/ausblenden")
        self.toggle_sources_btn.clicked.connect(self._toggle_sources)
        sources_header.addWidget(sources_title)
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
        bubble.setMaximumWidth(720)

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
                    f'color:#1a5fb4;font-weight:bold;">[{idx}]</a>'
                )
            return f"[{idx}]"

        rendered = re.sub(r"\[(\d+)\]", repl, escaped)
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
            llm_provider = getattr(self.hybrid_classifier, "llm_provider", None)
            self._controller = RAGController(
                self.db, llm_provider, self.chat_config
            )

        # UI in den Lade-Zustand versetzen.
        # Busy: Cancel-Button enabled (Label "Abbrechen"), Senden-Logik
        # deaktiviert (input_edit disabled, reset disabled). Der
        # send_btn bleibt klickbar, loest dann aber ``_cancel_current`` aus.
        self.input_edit.setEnabled(False)
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Abbrechen")
        self.reset_btn.setEnabled(False)
        self.status_label.setText("Suche läuft…")

        # Thread + Worker aufsetzen (moveToThread-Pattern)
        self._chat_thread = QThread()
        self._chat_worker = ChatWorker(self._controller, question)
        self._chat_worker.moveToThread(self._chat_thread)

        self._chat_thread.started.connect(self._chat_worker.run)
        self._chat_worker.progress.connect(self._on_worker_progress)
        self._chat_worker.finished.connect(self._on_worker_finished)
        self._chat_worker.failed.connect(self._on_worker_failed)

        self._chat_thread.start()

    def _on_worker_progress(self, message: str) -> None:
        """Aktualisiert die Status-Zeile waehrend des Aufrufs."""
        self.status_label.setText(message)

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

        if getattr(response, "used_llm", False):
            self._add_bubble(
                response.answer_text,
                "assistant",
                citations=response.citations,
            )
            if getattr(response, "has_hallucinated_citations", False):
                self._add_bubble(
                    "⚠ Einige Quellenangaben konnten nicht verifiziert "
                    "werden.",
                    "system",
                )
        else:
            # Offline-Modus: Treffer-Liste als klickbare Bubbles rendern
            docs = response.retrieved_docs or []
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
        bubble.setMaximumWidth(720)
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
        self._teardown_thread()
        # Cooldown: nach 500ms den Button wieder aktivieren
        QTimer.singleShot(500, self._re_enable_send_btn)

    def _re_enable_send_btn(self) -> None:
        """Weckt den send_btn nach dem Cancel-Cooldown wieder auf."""
        self.send_btn.setEnabled(True)

    def _teardown_thread(self) -> None:
        """Stoppt den QThread und gibt die Referenzen frei."""
        thread = self._chat_thread
        worker = self._chat_worker
        self._chat_thread = None
        self._chat_worker = None
        if thread is not None:
            thread.quit()
            thread.wait(2000)
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
        self.status_label.setText("")
        self.input_edit.setFocus()

    # ------------------------------------------------------------------ #
    # Quellen-Panel                                                      #
    # ------------------------------------------------------------------ #

    def _populate_sources(self, docs) -> None:
        """Fuellt das rechte Quellen-Panel mit allen retrieved docs."""
        self.sources_list.clear()
        for doc in docs:
            meta_parts = [
                p for p in (doc.kategorie, doc.steuerjahr, doc.betrag) if p
            ]
            label = f"D{doc.index}: {doc.filename}"
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
            # toolTip enthaelt Pfad + pdf_id (falls vorhanden)
            tooltip = doc.file_path
            if pdf_id:
                tooltip = (
                    f"{tooltip}\npdf_id: {pdf_id}" if tooltip
                    else f"pdf_id: {pdf_id}"
                )
            item.setToolTip(tooltip)
            self.sources_list.addItem(item)

    def _on_source_clicked(self, item: QListWidgetItem) -> None:
        """Oeffnet die zum Quellen-Eintrag gehoerende PDF.

        Phase 3 (Issue #25): Wenn der Eintrag eine ``pdf_id`` hat,
        wird diese bevorzugt (DB-Lookup holt den aktuellen Pfad),
        damit z.B. nach einem Move die korrekte Datei geoeffnet wird.
        Fallback: ``file_path`` (alter Pfad) wird verwendet.
        """
        file_path = item.data(Qt.ItemDataRole.UserRole)
        pdf_id = item.data(Qt.ItemDataRole.UserRole + 1)
        resolved = self._resolve_file_path(file_path, pdf_id)
        if resolved:
            self.open_pdf_requested.emit(resolved)

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
        else:
            file_path = entry
            pdf_id = ""
        resolved = self._resolve_file_path(file_path, pdf_id)
        if resolved:
            self.open_pdf_requested.emit(resolved)

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
        self.status_label.setText("")

    def refresh_llm_status(self) -> None:
        """Zeigt/versteckt das Banner je nach LLM-Verfuegbarkeit.

        Sollte aufgerufen werden, sobald der Chat-Tab sichtbar wird.
        """
        available = False
        try:
            available = bool(self.hybrid_classifier.is_llm_available())
        except Exception:  # noqa: BLE001 - defensiv
            available = False
        self.banner.setVisible(not available)
