"""Reiter „Suche“ im Hauptfenster: Volltextsuche im Index der Dokumentensuche (Phase 4).

Links Suchfeld mit Syntaxhilfe, Filter (Typ, Ordner, Zeitraum, Sortierung)
und die Trefferliste mit hervorgehobenen Fundstellen samt Seiten- bzw.
Blattangabe; rechts eine eigene :class:`PdfPreviewWidget`-Instanz, die direkt
auf die Trefferseite springt, bzw. die Textvorschau fuer Office-Dateien,
Markdown und Mails. Unten der Indexstand mit „Jetzt indizieren“.

Alle Datenbankzugriffe laufen in den Threads aus :mod:`src.gui.search_worker`;
die Oberflaeche blockiert nie. Ergebnisse veralteter Abfragen (schnelles
Weitertippen) werden ueber eine Generation verworfen.

GPL-3.0-or-later - Copyright (c) 2026
"""

from __future__ import annotations

import os
from html import escape
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QDate, QEvent, QPoint, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.pdf_preview_widget import PdfPreviewWidget
from src.gui.search_worker import DokumentLaden, StatusAbfrage, SuchAbfrage
from src.search.ausgabe import datum as datum_text
from src.search.plattform import im_dateimanager_zeigen
from src.search.suchindex import Suchindex
from src.utils.platform_paths import file_manager_name, open_with_default_app

TYPEN = (("", "Alle"), ("pdf", "PDF"), ("office", "Office"), ("md", "Markdown"), ("mail", "Mail"))
SORTIERUNGEN = (("relevanz", "Relevanz"), ("neu", "Neueste zuerst"), ("alt", "Älteste zuerst"))
STATUS_MARKEN = {
    "ocr_ausstehend": "OCR ausstehend", "ocr_teilweise": "OCR teilweise", "fehler": "Fehler",
    "cloud": "nur in der Cloud", "zu_gross": "zu groß", "verschluesselt": "verschlüsselt", "leer": "ohne Text",
    "ausstehend": "noch nicht gelesen",
}
METADATEN_FILTER = ("steuerjahr", "kategorie", "korrespondent")
TYP_NAMEN = {"pdf": "PDF", "office": "Office", "md": "Markdown", "mail": "Mails"}
TABELLEN_FORMATE = ("xlsx", "xlsm", "xls")

SEITENGROESSE = 50            # Treffer je Ladevorgang („Weitere Treffer laden“)
TIPP_VERZOEGERUNG_MS = 500    # Suche beim Tippen erst nach dieser Pause
MIN_ZEICHEN_TIPPEN = 3        # kuerzere Eingaben nur mit Enter suchen
STATUS_INTERVALL_MS = 15_000  # Indexstand waehrend eines Laufs auffrischen
MELDUNG_MS = 6000
WEB_PRUEFEN_MS = 6000         # nach dem Start der Browser-Oberflaeche pruefen, ob sie antwortet

_MARK_AUF = '<span style="background-color:#fff0a0; color:#000000;"><b>'
_MARK_ZU = "</b></span>"
_KEIN_DATUM = QDate(1900, 1, 1)  # Sonderwert der Datumsfelder: kein Filter

HILFE_HTML = (
    "<b>So wird gesucht</b><ul>"
    "<li>Mehrere Wörter: alle müssen vorkommen – <code>Rechnung Telekom</code></li>"
    "<li>Genaue Wortfolge: <code>\"Betrag in Höhe von\"</code></li>"
    "<li>Oder / Nicht: <code>Mietvertrag ODER Pachtvertrag</code>, <code>Rechnung NICHT Mahnung</code></li>"
    "<li>Wortanfang: <code>Rechnung*</code> findet Rechnungen, Rechnungsnummer …</li>"
    "<li>Nähe: <code>NEAR(Kündigung Frist, 10)</code> – höchstens 10 Wörter auseinander</li>"
    "<li>Umlaute sind egal: <code>Muller</code> findet auch <code>Müller</code></li>"
    "<li>Auch Dateinamen, Ordner und Mail-Betreffs werden durchsucht.</li>"
    "</ul>"
)


# --------------------------------------------------------------------------- Darstellungshelfer (Qt-frei, testbar)

def markiert_html(text: str, zeilen: bool = False) -> str:
    """Fundstellen-Marker (``\\x02``/``\\x03``) in HTML-Hervorhebung umwandeln, alles andere maskieren.

    Ohne ``zeilen`` wird Leerraum geglaettet (Ausschnitte in der Liste), mit
    ``zeilen`` bleiben Zeilenumbrueche erhalten (Textvorschau).
    """
    t = text or ""
    if not zeilen:
        t = " ".join(t.split())
    return escape(t).replace("\x02", _MARK_AUF).replace("\x03", _MARK_ZU)


def zahl(n) -> str:
    """1234567 -> „1.234.567“."""
    return f"{int(n or 0):,}".replace(",", ".")


def groesse_text(b) -> str:
    if b is None:
        return ""
    b = int(b)
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b / 1024:.0f} KB"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} MB"
    return f"{b / 1024 ** 3:.2f} GB"


def ist_tabelle(d: dict) -> bool:
    return (d.get("format") or "") in TABELLEN_FORMATE


def titel_von(d: dict) -> str:
    if d.get("typ") == "mail":
        return d.get("mail_betreff") or d.get("name") or ""
    return d.get("name") or ""


def typ_kuerzel(d: dict) -> str:
    if d.get("typ") == "office":
        return (d.get("format") or "office").upper()
    return (d.get("typ") or "").upper()


def meta_zeile(d: dict) -> str:
    """Datum, Seiten/Blaetter, Groesse, OCR bzw. bei Mails Datum, Absender, Anhaenge."""
    if d.get("typ") == "mail":
        teile = [datum_text(d.get("datum")), f"Von: {d.get('mail_von') or '?'}"]
        if d.get("mail_anhaenge"):
            teile.append(f"Anhänge: {d['mail_anhaenge']}")
    else:
        teile = [datum_text(d.get("datum"))]
        if d.get("seiten"):
            n = int(d["seiten"])
            if ist_tabelle(d):
                teile.append(f"{n} {'Blatt' if n == 1 else 'Blätter'}")
            else:
                teile.append(f"{n} S.")
        if d.get("groesse") is not None:
            teile.append(groesse_text(d["groesse"]))
        if d.get("ocr_seiten"):
            teile.append(f"{d['ocr_seiten']} S. per OCR")
    return " · ".join(t for t in teile if t)


def metadaten_zeile(d: dict) -> str:
    """PDFSM-Metadaten eines Treffers: Korrespondent · Kategorie · Steuerjahr · Betrag · Buchungsdatum."""
    teile = [d.get("korrespondent"), d.get("kategorie")]
    if d.get("steuerjahr"):
        teile.append(f"Steuerjahr {d['steuerjahr']}")
    if d.get("betrag") is not None and d.get("betrag") != "":
        try:
            teile.append(f"{float(d['betrag']):,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
        except (TypeError, ValueError):
            teile.append(str(d["betrag"]))
    if d.get("buchungsdatum"):
        teile.append(str(d["buchungsdatum"]))
    return " · ".join(str(x) for x in teile if x)


def stellen_beschriftung(d: dict, seite) -> str:
    if d.get("typ") == "pdf":
        return f"S. {seite}"
    if ist_tabelle(d):
        return f"Blatt {seite}"
    return ""


def status_zeile(st: dict) -> str:
    """Indexstand in einem Satz fuer die Statusleiste des Reiters."""
    if st.get("fehler"):
        return f"Indexstand nicht lesbar: {st['fehler']}"
    if not st.get("vorhanden"):
        return ("Noch kein Index vorhanden – „Jetzt indizieren“ liest die Vorrang-Ordner ein, "
                "„Kompletten Lauf starten“ alle Ordner.")
    pro_typ = dict(st.get("pro_typ") or {})
    reihenfolge = [k for k in TYP_NAMEN if k in pro_typ] + [k for k in pro_typ if k not in TYP_NAMEN]
    detail = ", ".join(f"{TYP_NAMEN.get(k, k)} {zahl(pro_typ[k])}" for k in reihenfolge if pro_typ[k])
    teile = [f"{zahl(st.get('dokumente'))} Dokumente" + (f" ({detail})" if detail else "")]
    if st.get("ocr_ausstehend_seiten"):
        teile.append(f"OCR ausstehend: {zahl(st['ocr_ausstehend_seiten'])} Seiten")
    if st.get("ocr_grund"):
        teile.append(f"Texterkennung aus ({st['ocr_grund']})")
    geschrieben = (st.get("textebene") or {}).get("geschrieben")
    if geschrieben:
        teile.append(f"Textebene in {zahl(geschrieben)} PDFs")
    if st.get("laeuft"):
        teile.append("Indexlauf aktiv" + (f": {st['fortschritt']}" if st.get("fortschritt") else ""))
    elif st.get("laeufe"):
        lauf = st["laeufe"][0]
        teile.append(f"Letzter Lauf: {lauf.get('beginn') or '?'} ({lauf.get('status') or '?'})")
    return " · ".join(teile)


def dokument_html(d: dict, seiten: list[dict]) -> str:
    """Textvorschau eines Dokuments: Kopf, dann je Seite/Blatt der Text mit Fundstellen.

    Vor der ersten Seite mit Treffern steht der Anker ``treffer`` (zum Hinscrollen).
    """
    kopf = [f"<h3 style='margin:0 0 4px 0'>{escape(titel_von(d))}</h3>"]
    if d.get("typ") == "mail":
        zeilen = [f"Von: {escape(d.get('mail_von') or '')}", f"An: {escape(d.get('mail_an') or '')}",
                  f"Datum: {escape(datum_text(d.get('datum')) if d.get('datum') else str(d.get('mail_datum') or ''))}"]
        if d.get("mail_anhaenge"):
            zeilen.append(f"Anhänge: {escape(str(d['mail_anhaenge']))}")
        kopf.append("<p style='color:#666666; margin:0'>" + "<br>".join(zeilen) + "</p>")
    else:
        kopf.append(f"<p style='color:#666666; margin:0'>{escape(meta_zeile(d))} · "
                    f"Status: {escape(d.get('textstatus') or '')}</p>")
        if d.get("datei") and not os.path.exists(d["datei"]):
            kopf.append("<p style='color:#9a3412'>Die Datei existiert nicht mehr – "
                        "hier der im Index gespeicherte Text.</p>")
    teile = []
    anker_gesetzt = False
    for s in seiten:
        ueberschrift = ""
        if d.get("typ") == "pdf":
            ueberschrift = f"Seite {s.get('seite')}" + (" · OCR" if s.get("quelle") == "ocr" else "")
        elif ist_tabelle(d):
            ueberschrift = f"Blatt {s.get('seite')}"
        anker = ""
        if s.get("treffer") and not anker_gesetzt:
            anker, anker_gesetzt = '<a name="treffer"></a>', True
        text = markiert_html(s.get("text") or "", zeilen=True) or "<i>(kein Text)</i>"
        if ueberschrift:
            teile.append(f"<h4 style='margin:10px 0 2px 0'>{anker}{escape(ueberschrift)}</h4>")
        else:
            teile.append(anker)
        teile.append(f"<p style='white-space:pre-wrap; margin:0'>{text}</p>")
    if not seiten:
        teile.append("<p style='color:#888888'>Kein Text vorhanden.</p>")
    return "".join(kopf) + "<hr>" + "".join(teile)


# --------------------------------------------------------------------------- Trefferkarte

class TrefferKarte(QFrame):
    """Ein Treffer in der Liste: Kopf (Typ, Titel, Marken), Metazeile, Pfad, Fundstellen.

    Signale: ``angeklickt(karte)``, ``doppelklick(karte)``,
    ``seite_angeklickt(karte, seite)`` (Link „S. 3“ / „Blatt 2“ einer Fundstelle),
    ``kontextmenue(karte, globale_position)``.
    """

    angeklickt = pyqtSignal(object)
    doppelklick = pyqtSignal(object)
    seite_angeklickt = pyqtSignal(object, int)
    kontextmenue = pyqtSignal(object, QPoint)

    _STIL = "QFrame#trefferKarte {{ background: palette(base); border: {rand}; border-radius: 6px; }}"

    def __init__(self, dok: dict, parent=None) -> None:
        super().__init__(parent)
        self.dok = dok
        self.setObjectName("trefferKarte")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menue_angefordert)
        self.stellen_labels: list[QLabel] = []
        self._bauen()
        self.set_ausgewaehlt(False)

    def _label(self, html: str, stil: str = "", links: bool = False) -> QLabel:
        lbl = QLabel(html, self)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)  # Rechtsklick geht an die Karte
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse if links
                                    else Qt.TextInteractionFlag.NoTextInteraction)
        if stil:
            lbl.setStyleSheet(stil)
        return lbl

    def _bauen(self) -> None:
        d = self.dok
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)

        marken = []
        marke = STATUS_MARKEN.get(d.get("textstatus") or "")
        if marke:
            marken.append(marke)
        if d.get("im_namen"):
            marken.append("Treffer im Namen")
        if d.get("im_metadaten"):
            marken.append("Treffer in Metadaten")
        kopf = (f'<span style="color:#2563eb; font-weight:bold;">{escape(typ_kuerzel(d))}</span>&nbsp; '
                f"<b>{escape(titel_von(d))}</b>"
                + "".join(f'&nbsp; <span style="color:#9a3412;">[{escape(m)}]</span>' for m in marken))
        self.kopf_label = self._label(kopf)
        lay.addWidget(self.kopf_label)

        self.meta_label = self._label(escape(meta_zeile(d)), "color: #666666; font-size: 11px;")
        lay.addWidget(self.meta_label)
        self.metadaten_label = None
        if metadaten_zeile(d):
            self.metadaten_label = self._label(escape(metadaten_zeile(d)), "color: #166534; font-size: 11px;")
            lay.addWidget(self.metadaten_label)

        pfad = d.get("ordner") if d.get("typ") == "mail" and d.get("format") == "mbox" else d.get("pfad")
        self.pfad_label = self._label(escape(pfad or ""), "color: #888888; font-size: 11px;")
        lay.addWidget(self.pfad_label)

        for s in d.get("stellen") or []:
            beschriftung = stellen_beschriftung(d, s.get("seite"))
            link = (f'<a href="seite:{s.get("seite")}" style="color:#2563eb; text-decoration:none;">'
                    f"{escape(beschriftung)}</a>&nbsp; ") if beschriftung else ""
            lbl = self._label(link + markiert_html(s.get("text") or ""), links=bool(link))
            lbl.linkActivated.connect(self._link_aktiviert)
            lay.addWidget(lbl)
            self.stellen_labels.append(lbl)

        if d.get("im_namen") and not d.get("stellen"):
            lay.addWidget(self._label("(Treffer im Datei-/Ordnernamen)", "color: #888888; font-size: 11px;"))
        if (d.get("treffer_seiten") or 0) > len(d.get("stellen") or []):
            lay.addWidget(self._label(f"… insgesamt {d['treffer_seiten']} Seiten mit Treffern",
                                      "color: #888888; font-size: 11px;"))

    def set_ausgewaehlt(self, an: bool) -> None:
        self._ausgewaehlt = an
        self.setStyleSheet(self._STIL.format(rand="2px solid #2563eb" if an else "1px solid palette(mid)"))

    def ist_ausgewaehlt(self) -> bool:
        return self._ausgewaehlt

    def _link_aktiviert(self, href: str) -> None:
        if href.startswith("seite:"):
            try:
                self.seite_angeklickt.emit(self, int(href[6:]))
            except ValueError:
                pass

    def _menue_angefordert(self, pos: QPoint) -> None:
        self.kontextmenue.emit(self, self.mapToGlobal(pos))

    def mousePressEvent(self, event):  # noqa: N802 (Qt-API)
        if event.button() == Qt.MouseButton.LeftButton:
            self.angeklickt.emit(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 (Qt-API)
        if event.button() == Qt.MouseButton.LeftButton:
            self.doppelklick.emit(self)
        super().mouseDoubleClickEvent(event)


# --------------------------------------------------------------------------- Ansicht

class SearchView(QWidget):
    """Inhalt des Reiters „Suche“.

    Signale:
        open_pdf_requested(Path): PDF so oeffnen, wie es eingestellt ist (Hauptfenster)
        open_pdf_external_requested(Path): „Extern öffnen“ aus der Vorschau
        einrichten_requested: Knopf „Einrichten…“ im Hinweis (Einstellungen > Suche)
        suche_fertig(dict): Ergebnis der angezeigten Abfrage (auch fuer Tests)
        status_aktualisiert(dict): Indexstand ist da
        vorschau_fertig(int): Textvorschau fuer dieses Dokument steht
    """

    open_pdf_requested = pyqtSignal(Path)
    open_pdf_external_requested = pyqtSignal(Path)
    einrichten_requested = pyqtSignal()
    suche_fertig = pyqtSignal(object)
    status_aktualisiert = pyqtSignal(object)
    vorschau_fertig = pyqtSignal(int)

    def __init__(self, config, parent=None) -> None:
        """``config``: die :class:`~src.utils.config.Config` (liefert ``get_search_config()``)."""
        super().__init__(parent)
        self.config = config
        self.konfig = None
        self.index: Suchindex | None = None
        self.seitengroesse = SEITENGROESSE
        self.status: dict = {}
        self.angezeigte_abfrage = ""
        self.verworfene_ergebnisse = 0  # Ergebnisse veralteter Generationen (Tests)

        self._generation = 0            # Suchabfragen
        self._vorschau_generation = 0   # Dokument laden
        self._abfragen: dict[int, tuple[str, int]] = {}  # Generation -> (Text, Start)
        self._threads: list[QThread] = []
        self._karten: list[TrefferKarte] = []
        self._aktuelle: TrefferKarte | None = None
        self._letzte_id: int | None = None
        self._ergebnis: dict | None = None
        self._start = 0
        self._pdf_pfad: Path | None = None
        self._pending_seite: int | None = None
        self._status_laeuft = False

        self._tipp_timer = QTimer(self)
        self._tipp_timer.setSingleShot(True)
        self._tipp_timer.setInterval(TIPP_VERZOEGERUNG_MS)
        self._tipp_timer.timeout.connect(self._suche_starten)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(STATUS_INTERVALL_MS)
        self._status_timer.timeout.connect(self.refresh_status)
        self._meldung_timer = QTimer(self)
        self._meldung_timer.setSingleShot(True)
        self._meldung_timer.setInterval(MELDUNG_MS)
        self._meldung_timer.timeout.connect(lambda: self.meldung_label.setVisible(False))
        self._nachlauf_timer = QTimer(self)  # Indexstand kurz nach dem Start eines Laufs
        self._nachlauf_timer.setSingleShot(True)
        self._nachlauf_timer.setInterval(2000)
        self._nachlauf_timer.timeout.connect(self.refresh_status)

        self._ui_bauen()
        self.refresh_settings()

    # ------------------------------------------------------------------ Aufbau

    def _ui_bauen(self) -> None:
        aussen = QVBoxLayout(self)
        aussen.setContentsMargins(6, 6, 6, 6)
        aussen.setSpacing(6)

        # Hinweis, solange die Suche nicht eingerichtet ist
        self.hinweis = QFrame()
        self.hinweis.setObjectName("suchHinweis")
        self.hinweis.setStyleSheet("QFrame#suchHinweis { background: #fff8e1; border: 1px solid #f0d58c; "
                                   "border-radius: 6px; }")
        h = QHBoxLayout(self.hinweis)
        h.setContentsMargins(12, 8, 12, 8)
        self.hinweis_label = QLabel(
            "Die Dokumentensuche ist noch nicht eingerichtet. Sie durchsucht PDFs (auch gescannte), "
            "Office-Dateien, Markdown und Mails auf diesem Rechner – alles bleibt lokal."
        )
        self.hinweis_label.setWordWrap(True)
        h.addWidget(self.hinweis_label, 1)
        self.einrichten_button = QPushButton("Einrichten…")
        self.einrichten_button.setToolTip("Einstellungen > Suche öffnen")
        self.einrichten_button.clicked.connect(self.einrichten_requested)
        h.addWidget(self.einrichten_button)
        aussen.addWidget(self.hinweis)

        # Suchbereich: links Suche und Treffer, rechts Vorschau
        self.suchbereich = QSplitter(Qt.Orientation.Horizontal)
        self.suchbereich.addWidget(self._links_bauen())
        self.suchbereich.addWidget(self._rechts_bauen())
        self.suchbereich.setStretchFactor(0, 4)
        self.suchbereich.setStretchFactor(1, 5)
        self.suchbereich.setSizes([460, 560])
        aussen.addWidget(self.suchbereich, 1)

        # Statuszeile: Indexstand und Laeufe
        status = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #666666; font-size: 11px;")
        status.addWidget(self.status_label, 1)
        self.refresh_button = QToolButton()
        self.refresh_button.setText("↻")
        self.refresh_button.setToolTip("Indexstand aktualisieren")
        self.refresh_button.setAutoRaise(True)
        self.refresh_button.clicked.connect(self.refresh_status)
        status.addWidget(self.refresh_button)
        self.index_button = QPushButton("Jetzt indizieren")
        self.index_button.setToolTip("Vorrang-Ordner (z. B. frisch gescannte PDFs) sofort einlesen – "
                                     "läuft im Hintergrund")
        self.index_button.clicked.connect(lambda: self._lauf_starten(True))
        status.addWidget(self.index_button)
        self.index_all_button = QPushButton("Kompletten Lauf starten")
        self.index_all_button.setToolTip("Alle eingerichteten Ordner, Laufwerke und Postfächer einlesen – "
                                         "läuft im Hintergrund")
        self.index_all_button.clicked.connect(lambda: self._lauf_starten(False))
        status.addWidget(self.index_all_button)
        self.web_button = QPushButton("Im Browser öffnen")
        self.web_button.setToolTip("Browser-Oberfläche der Suche öffnen (nur auf diesem Rechner erreichbar); "
                                   "läuft sie noch nicht, wird sie gestartet")
        self.web_button.clicked.connect(self._web_oeffnen)
        self.web_button.setVisible(False)
        status.addWidget(self.web_button)
        self.anhalten_button = QPushButton("Anhalten")
        self.anhalten_button.setToolTip("Den laufenden Indexlauf anhalten – laufende Aufträge werden noch "
                                        "fertig, der nächste Lauf setzt fort")
        self.anhalten_button.clicked.connect(self._lauf_anhalten)
        self.anhalten_button.setVisible(False)
        status.addWidget(self.anhalten_button)
        aussen.addLayout(status)

    def _links_bauen(self) -> QWidget:
        links = QWidget()
        lay = QVBoxLayout(links)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        zeile = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Suchen in PDFs, Office-Dateien, Markdown und Mails …")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setToolTip(HILFE_HTML)
        self.search_edit.returnPressed.connect(self._suche_starten)
        self.search_edit.textChanged.connect(self._text_geaendert)
        self.search_edit.installEventFilter(self)
        zeile.addWidget(self.search_edit, 1)
        self.search_button = QPushButton("Suchen")
        self.search_button.clicked.connect(self._suche_starten)
        zeile.addWidget(self.search_button)
        self.help_button = QToolButton()
        self.help_button.setText("?")
        self.help_button.setToolTip("Hilfe zur Suchsyntax")
        self.help_button.clicked.connect(self._hilfe_zeigen)
        zeile.addWidget(self.help_button)
        lay.addLayout(zeile)

        filter1 = QHBoxLayout()
        self._typ_gruppe = QButtonGroup(self)
        self._typ_gruppe.setExclusive(True)
        self.typ_buttons: dict[str, QToolButton] = {}
        for typ, beschriftung in TYPEN:
            b = QToolButton()
            b.setText(beschriftung)
            b.setCheckable(True)
            b.setProperty("typ", typ)
            self._typ_gruppe.addButton(b)
            self.typ_buttons[typ] = b
            filter1.addWidget(b)
        self.typ_buttons[""].setChecked(True)
        self._typ_gruppe.buttonClicked.connect(lambda _b: self._filter_geaendert())
        filter1.addStretch(1)
        filter1.addWidget(QLabel("Sortierung:"))
        self.sort_combo = QComboBox()
        for key, beschriftung in SORTIERUNGEN:
            self.sort_combo.addItem(beschriftung, key)
        self.sort_combo.currentIndexChanged.connect(lambda _i: self._filter_geaendert())
        filter1.addWidget(self.sort_combo)
        lay.addLayout(filter1)

        filter2 = QHBoxLayout()
        filter2.addWidget(QLabel("Ordner:"))
        self.ordner_edit = QLineEdit()
        self.ordner_edit.setPlaceholderText("Teil des Pfads oder Postfachs, z. B. Steuer")
        self.ordner_edit.setClearButtonEnabled(True)
        self.ordner_edit.editingFinished.connect(self._filter_geaendert)
        filter2.addWidget(self.ordner_edit, 1)
        filter2.addWidget(QLabel("von:"))
        self.von_edit = self._datum_feld()
        filter2.addWidget(self.von_edit)
        filter2.addWidget(QLabel("bis:"))
        self.bis_edit = self._datum_feld()
        filter2.addWidget(self.bis_edit)
        self.datum_reset = QToolButton()
        self.datum_reset.setText("×")
        self.datum_reset.setToolTip("Zeitraum zurücksetzen")
        self.datum_reset.setAutoRaise(True)
        self.datum_reset.clicked.connect(self._zeitraum_zuruecksetzen)
        filter2.addWidget(self.datum_reset)
        lay.addLayout(filter2)

        # PDFSM-Metadaten (Phase 5): Steuerjahr, Kategorie, Korrespondent, Betrag
        filter3 = QHBoxLayout()
        self.meta_combos: dict[str, QComboBox] = {}
        for feld, beschriftung in (("steuerjahr", "Steuerjahr:"), ("kategorie", "Kategorie:"),
                                   ("korrespondent", "Korrespondent:")):
            filter3.addWidget(QLabel(beschriftung))
            combo = QComboBox()
            combo.addItem("Alle", "")
            combo.setMinimumWidth(90)
            combo.currentIndexChanged.connect(lambda _i: self._filter_geaendert())
            self.meta_combos[feld] = combo
            filter3.addWidget(combo, 1 if feld != "steuerjahr" else 0)
        filter3.addWidget(QLabel("Betrag von:"))
        self.betrag_von_spin = self._betrag_feld()
        filter3.addWidget(self.betrag_von_spin)
        filter3.addWidget(QLabel("bis:"))
        self.betrag_bis_spin = self._betrag_feld()
        filter3.addWidget(self.betrag_bis_spin)
        lay.addLayout(filter3)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: #666666;")
        self.count_label.setWordWrap(True)
        lay.addWidget(self.count_label)

        self.treffer_scroll = QScrollArea()
        self.treffer_scroll.setWidgetResizable(True)
        self.treffer_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self.treffer_scroll.installEventFilter(self)
        self.treffer_container = QWidget()
        self.treffer_layout = QVBoxLayout(self.treffer_container)
        self.treffer_layout.setContentsMargins(4, 4, 4, 4)
        self.treffer_layout.setSpacing(6)
        self.hilfe_label = QLabel(HILFE_HTML)
        self.hilfe_label.setWordWrap(True)
        self.hilfe_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.hilfe_label.setStyleSheet("color: #444444; padding: 8px;")
        self.treffer_layout.addWidget(self.hilfe_label)
        self.mehr_button = QPushButton("Weitere Treffer laden")
        self.mehr_button.setVisible(False)
        self.mehr_button.clicked.connect(self._mehr_laden)
        self.treffer_layout.addWidget(self.mehr_button)
        self.treffer_layout.addStretch(1)
        self.treffer_scroll.setWidget(self.treffer_container)
        lay.addWidget(self.treffer_scroll, 1)
        return links

    def _rechts_bauen(self) -> QWidget:
        rechts = QWidget()
        lay = QVBoxLayout(rechts)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.titel_label = QLabel("Kein Treffer ausgewählt")
        self.titel_label.setStyleSheet("font-weight: bold;")
        self.titel_label.setWordWrap(True)
        self.titel_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.titel_label)
        self.pfad_label = QLabel("")
        self.pfad_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.pfad_label.setWordWrap(True)
        self.pfad_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.pfad_label)

        aktionen = QHBoxLayout()
        self.open_button = QPushButton("Öffnen")
        self.open_button.setToolTip("PDFs wie in den Einstellungen gewählt, andere Dateien mit dem "
                                    "Standardprogramm, Mails als .eml mit dem Mailprogramm")
        self.open_button.clicked.connect(lambda: self._mit_aktuellem(self._oeffnen))
        aktionen.addWidget(self.open_button)
        self.show_button = QPushButton(f"Im {file_manager_name()} zeigen")
        self.show_button.clicked.connect(lambda: self._mit_aktuellem(self._im_dateimanager_zeigen))
        aktionen.addWidget(self.show_button)
        self.copy_button = QPushButton("Pfad kopieren")
        self.copy_button.clicked.connect(lambda: self._mit_aktuellem(self._pfad_kopieren))
        aktionen.addWidget(self.copy_button)
        self.eml_button = QPushButton("Als .eml speichern…")
        self.eml_button.setToolTip("Die Mail als Datei ablegen (z. B. zu den Belegen)")
        self.eml_button.clicked.connect(lambda: self._mit_aktuellem(self._eml_speichern))
        aktionen.addWidget(self.eml_button)
        aktionen.addStretch(1)
        lay.addLayout(aktionen)
        for b in (self.open_button, self.show_button, self.copy_button):
            b.setEnabled(False)
        self.eml_button.setVisible(False)

        self.meldung_label = QLabel("")
        self.meldung_label.setStyleSheet("color: #9a3412;")
        self.meldung_label.setWordWrap(True)
        self.meldung_label.setVisible(False)
        lay.addWidget(self.meldung_label)

        self.vorschau_stack = QStackedWidget()
        self.vorschau_hinweis = QLabel("Treffer auswählen – PDFs erscheinen hier auf der Trefferseite, "
                                       "Office-Dateien, Markdown und Mails als Text.")
        self.vorschau_hinweis.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vorschau_hinweis.setWordWrap(True)
        self.vorschau_hinweis.setStyleSheet("color: #888888; padding: 16px;")
        self.vorschau_stack.addWidget(self.vorschau_hinweis)
        self.pdf_vorschau = PdfPreviewWidget(self, compact=False)
        self.pdf_vorschau.document_loaded.connect(self._pdf_geladen)
        self.pdf_vorschau.load_failed.connect(self._pdf_fehler)
        self.pdf_vorschau.open_external_requested.connect(self.open_pdf_external_requested)
        self.vorschau_stack.addWidget(self.pdf_vorschau)
        self.text_vorschau = QTextBrowser()
        self.text_vorschau.setOpenLinks(False)
        self.text_vorschau.setOpenExternalLinks(False)
        self.vorschau_stack.addWidget(self.text_vorschau)
        self.vorschau_stack.setCurrentWidget(self.vorschau_hinweis)
        lay.addWidget(self.vorschau_stack, 1)
        return rechts

    def _betrag_feld(self) -> QDoubleSpinBox:
        feld = QDoubleSpinBox()
        feld.setRange(0.0, 1_000_000_000.0)
        feld.setDecimals(2)
        feld.setSpecialValueText("–")
        feld.setSuffix(" €")
        feld.setToolTip("Bruttobetrag aus den PDFSM-Metadaten; „–“ = kein Filter")
        feld.valueChanged.connect(lambda _v: self._filter_geaendert())
        return feld

    def _datum_feld(self) -> QDateEdit:
        feld = QDateEdit()
        feld.setCalendarPopup(True)
        feld.setDisplayFormat("dd.MM.yyyy")
        feld.setMinimumDate(_KEIN_DATUM)
        feld.setSpecialValueText("–")
        feld.setDate(_KEIN_DATUM)
        feld.setToolTip("Dokumentdatum (Dateidatum bzw. Mail-Datum); „–“ = kein Filter")
        feld.dateChanged.connect(lambda _d: self._filter_geaendert())
        return feld

    # ------------------------------------------------------------------ Einstellungen / Sichtbarkeit

    def refresh_settings(self) -> None:
        """Konfiguration neu lesen (nach dem Einstellungsdialog); verwirft laufende Abfragen."""
        self.konfig = self.config.get_search_config()
        self.index = Suchindex(self.konfig)
        aktiv = bool(self.konfig.aktiv)
        self.hinweis.setVisible(not aktiv)
        self.suchbereich.setEnabled(aktiv)
        for b in (self.index_button, self.index_all_button, self.refresh_button):
            b.setEnabled(aktiv)
        self.web_button.setVisible(aktiv and bool(self.konfig.web_aktiv))
        self._generation += 1
        self._vorschau_generation += 1
        self._status_timer.stop()
        self._liste_leeren(hilfe=True)
        self.count_label.setText("")
        self.status_label.setText("" if aktiv else "Dokumentensuche ausgeschaltet (Einstellungen > Suche).")
        if aktiv and self.isVisible():
            self.refresh_status()

    def tab_gezeigt(self) -> None:
        """Der Reiter wurde gewaehlt: Indexstand auffrischen, Suchfeld fokussieren."""
        self.refresh_status()
        if self.suchbereich.isEnabled():
            self.search_edit.setFocus()

    def fokus(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def showEvent(self, event):  # noqa: N802 (Qt-API)
        super().showEvent(event)
        self.refresh_status()

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Timer anhalten und auf Hintergrund-Threads warten (beim Schliessen)."""
        for t in (self._tipp_timer, self._status_timer, self._meldung_timer, self._nachlauf_timer):
            t.stop()
        self._generation += 1
        self._vorschau_generation += 1
        self.pdf_vorschau.shutdown(timeout_ms)
        for t in list(self._threads):
            if not sip.isdeleted(t):
                t.wait(timeout_ms)
        self._threads = []

    # ------------------------------------------------------------------ Threads

    def _thread_starten(self, thread: QThread) -> None:
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._threads_aufraeumen)
        self._threads.append(thread)
        thread.start()

    def _threads_aufraeumen(self) -> None:
        self._threads = [t for t in self._threads if not sip.isdeleted(t) and t.isRunning()]

    # ------------------------------------------------------------------ Suche

    def _text_geaendert(self, text: str) -> None:
        t = text.strip()
        if not t:
            self._tipp_timer.stop()
            if self._hat_filter():
                self._tipp_timer.start()   # reine Filterabfrage
                return
            self._generation += 1  # laufende Abfragen verfallen
            self._liste_leeren(hilfe=True)
            self.count_label.setText("")
            self.angezeigte_abfrage = ""
        elif len(t) >= MIN_ZEICHEN_TIPPEN:
            self._tipp_timer.start()

    def _filter_geaendert(self) -> None:
        if self.search_edit.text().strip() or self._hat_filter():
            self._tipp_timer.start()
        else:
            self._text_geaendert("")

    def _zeitraum_zuruecksetzen(self) -> None:
        for feld in (self.von_edit, self.bis_edit):
            feld.setDate(_KEIN_DATUM)

    @staticmethod
    def _datum(feld: QDateEdit) -> str | None:
        d = feld.date()
        return None if d <= _KEIN_DATUM else d.toString("yyyy-MM-dd")

    def _filter_argumente(self) -> dict:
        """Filter der Oberflaeche als Argumente fuer ``Suchindex.suche``."""
        args: dict = {"sortierung": self.sort_combo.currentData() or "relevanz"}
        knopf = self._typ_gruppe.checkedButton()
        typ = knopf.property("typ") if knopf is not None else ""
        if typ:
            args["typ"] = typ
        ordner = self.ordner_edit.text().strip()
        if ordner:
            args["ordner"] = ordner
        von, bis = self._datum(self.von_edit), self._datum(self.bis_edit)
        if von:
            args["von"] = von
        if bis:
            args["bis"] = bis
        for feld, combo in self.meta_combos.items():
            wert = combo.currentData() if combo.currentIndex() > 0 else ""
            if wert:
                args[feld] = wert
        if self.betrag_von_spin.value() > 0:
            args["betrag_von"] = self.betrag_von_spin.value()
        if self.betrag_bis_spin.value() > 0:
            args["betrag_bis"] = self.betrag_bis_spin.value()
        return args

    def _hat_filter(self) -> bool:
        """Mindestens ein Filter gesetzt (dann sucht der Index auch ohne Suchbegriff)?"""
        args = self._filter_argumente()
        args.pop("sortierung", None)
        return bool(args)

    def suchen(self, text: str, typ: str | None = None, steuerjahr: str = "", kategorie: str = "",
               korrespondent: str = "", von: str = "", bis: str = "", betrag_von: float = 0.0,
               betrag_bis: float = 0.0) -> None:
        """Suche von aussen (Werkzeugleiste, Strg+F): Suchbegriff und Filter setzen, sofort suchen."""
        for w in (self.search_edit, self.sort_combo, self.ordner_edit, self.von_edit, self.bis_edit,
                  self.betrag_von_spin, self.betrag_bis_spin, *self.meta_combos.values()):
            w.blockSignals(True)
        try:
            self.search_edit.setText(text or "")
            if typ is not None and typ in self.typ_buttons:
                self.typ_buttons[typ].setChecked(True)
            for feld, wert in (("steuerjahr", steuerjahr), ("kategorie", kategorie), ("korrespondent", korrespondent)):
                self._combo_waehlen(self.meta_combos[feld], wert)
            self.von_edit.setDate(QDate.fromString(von, "yyyy-MM-dd") if von else _KEIN_DATUM)
            self.bis_edit.setDate(QDate.fromString(bis, "yyyy-MM-dd") if bis else _KEIN_DATUM)
            self.betrag_von_spin.setValue(float(betrag_von or 0))
            self.betrag_bis_spin.setValue(float(betrag_bis or 0))
        finally:
            for w in (self.search_edit, self.sort_combo, self.ordner_edit, self.von_edit, self.bis_edit,
                      self.betrag_von_spin, self.betrag_bis_spin, *self.meta_combos.values()):
                w.blockSignals(False)
        self._suche_starten()

    @staticmethod
    def _combo_waehlen(combo: QComboBox, wert: str) -> None:
        """Wert waehlen; ein noch unbekannter Wert wird als Eintrag ergaenzt."""
        if not wert:
            combo.setCurrentIndex(0)
            return
        i = combo.findData(wert)
        if i < 0:
            combo.addItem(str(wert), str(wert))
            i = combo.count() - 1
        combo.setCurrentIndex(i)

    def leeren(self) -> None:
        """Suchfeld, Filter und Trefferliste zuruecksetzen (Werkzeugleiste „Suche leeren“)."""
        self._tipp_timer.stop()
        felder = (self.search_edit, self.ordner_edit, self.von_edit, self.bis_edit, self.betrag_von_spin,
                  self.betrag_bis_spin, *self.meta_combos.values())
        for w in felder:
            w.blockSignals(True)
        try:
            self.search_edit.clear()
            self.ordner_edit.clear()
            for combo in self.meta_combos.values():
                combo.setCurrentIndex(0)
            for spin in (self.betrag_von_spin, self.betrag_bis_spin):
                spin.setValue(0.0)
            self._zeitraum_zuruecksetzen()
        finally:
            for w in felder:
                w.blockSignals(False)
        self._generation += 1  # laufende Abfragen verfallen
        self._liste_leeren(hilfe=True)
        self.count_label.setText("")
        self.angezeigte_abfrage = ""

    def _werte_fuellen(self, werte: dict | None) -> None:
        """Auswahllisten der Metadatenfilter aus dem Index fuellen; die Auswahl bleibt erhalten."""
        for feld, combo in self.meta_combos.items():
            liste = list((werte or {}).get(feld) or [])
            aktuell = combo.currentData() if combo.currentIndex() > 0 else ""
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem("Alle", "")
                for w in liste:
                    combo.addItem(str(w), str(w))
                self._combo_waehlen(combo, aktuell)
            finally:
                combo.blockSignals(False)

    def _suche_starten(self, start: int = 0) -> None:
        """Abfrage mit den aktuellen Filtern starten; ``start`` > 0 haengt weitere Treffer an."""
        self._tipp_timer.stop()
        if self.index is None or not self.konfig.aktiv:
            return
        text = self.search_edit.text().strip()
        if not text and not self._hat_filter():
            self._text_geaendert("")
            return
        self._generation += 1
        generation = self._generation
        self._abfragen[generation] = (text, int(start or 0))
        argumente = self._filter_argumente()
        argumente.update(anzahl=self.seitengroesse, start=int(start or 0))
        thread = SuchAbfrage(self.index, generation, text, argumente, self)
        thread.fertig.connect(self._ergebnis_da)
        thread.fehler.connect(self._abfrage_fehler)
        self._thread_starten(thread)
        self.count_label.setText("Suche …" if not start else "Lade weitere Treffer …")
        self.mehr_button.setEnabled(False)

    def _mehr_laden(self) -> None:
        if self._ergebnis is not None:
            self._suche_starten(start=self._start + len(self._ergebnis.get("treffer") or []))

    def _ergebnis_da(self, generation: int, ergebnis: dict) -> None:
        text, start = self._abfragen.pop(generation, ("", 0))
        if generation != self._generation:
            self.verworfene_ergebnisse += 1
            return
        if start == 0:
            self._liste_leeren(hilfe=False)
        self._ergebnis = ergebnis
        self._start = start
        self.angezeigte_abfrage = text
        for d in ergebnis.get("treffer") or []:
            self._karte_anlegen(d)
        gesamt = int(ergebnis.get("gesamt") or 0)
        if gesamt:
            self.count_label.setText(f"{zahl(gesamt)}{'+' if ergebnis.get('mehr') else ''} Dokumente · "
                                     f"{ergebnis.get('dauer_ms', 0)} ms")
        elif text:
            self.count_label.setText(f"Keine Treffer für „{text}“ (Abfrage: {ergebnis.get('abfrage', '')})")
        else:
            self.count_label.setText("Keine Dokumente mit diesen Filtern")
        geladen = start + len(ergebnis.get("treffer") or [])
        self.mehr_button.setVisible(geladen < gesamt)
        self.mehr_button.setEnabled(True)
        # Bleibt das zuvor gewaehlte Dokument in der Liste, bleibt auch die Vorschau stehen
        if start == 0:
            vorherige = next((k for k in self._karten if k.dok.get("id") == self._letzte_id), None)
            if vorherige is not None:
                self._aktuelle = vorherige
                vorherige.set_ausgewaehlt(True)
            else:
                self._vorschau_leeren()
        self.suche_fertig.emit(ergebnis)

    def _abfrage_fehler(self, generation: int, text: str) -> None:
        self._abfragen.pop(generation, None)
        if generation != self._generation:
            return
        self.count_label.setText(f"Suche fehlgeschlagen: {text}")
        self.mehr_button.setEnabled(True)

    def _liste_leeren(self, hilfe: bool) -> None:
        self._letzte_id = self._aktuelle.dok.get("id") if self._aktuelle is not None else None
        for k in self._karten:
            self.treffer_layout.removeWidget(k)
            k.setParent(None)
            k.deleteLater()
        self._karten = []
        self._aktuelle = None
        self._ergebnis = None
        self._start = 0
        self.hilfe_label.setVisible(hilfe)
        self.mehr_button.setVisible(False)
        if hilfe:
            self._vorschau_leeren()

    def _karte_anlegen(self, d: dict) -> None:
        karte = TrefferKarte(d, self.treffer_container)
        karte.angeklickt.connect(self._karte_angeklickt)
        karte.doppelklick.connect(self._karte_doppelklick)
        karte.seite_angeklickt.connect(self._seite_angeklickt)
        karte.kontextmenue.connect(self._kontextmenue_zeigen)
        self.treffer_layout.insertWidget(self.treffer_layout.indexOf(self.mehr_button), karte)
        self._karten.append(karte)

    def karten(self) -> list[TrefferKarte]:
        return list(self._karten)

    def aktuelle_karte(self) -> TrefferKarte | None:
        return self._aktuelle

    # ------------------------------------------------------------------ Auswahl und Vorschau

    def _karte_angeklickt(self, karte: TrefferKarte) -> None:
        self._auswaehlen(karte)

    def _karte_doppelklick(self, karte: TrefferKarte) -> None:
        self._auswaehlen(karte)
        self._oeffnen(karte.dok)

    def _seite_angeklickt(self, karte: TrefferKarte, seite: int) -> None:
        self._auswaehlen(karte, seite)

    def _auswahl_bewegen(self, schritt: int) -> None:
        if not self._karten:
            return
        if self._aktuelle is None or self._aktuelle not in self._karten:
            i = 0 if schritt > 0 else len(self._karten) - 1
        else:
            i = max(0, min(len(self._karten) - 1, self._karten.index(self._aktuelle) + schritt))
        karte = self._karten[i]
        self._auswaehlen(karte)
        karte.setFocus()

    def _auswaehlen(self, karte: TrefferKarte, seite: int | None = None) -> None:
        """Karte markieren und das Dokument rechts zeigen; ``seite`` = Trefferseite (1-basiert)."""
        d = karte.dok
        if seite is None:
            stellen = d.get("stellen") or []
            seite = int(stellen[0].get("seite") or 1) if stellen else 1
        if self._aktuelle is karte:
            if d.get("typ") == "pdf":
                self._pdf_seite(seite)
            return
        if self._aktuelle is not None and not sip.isdeleted(self._aktuelle):
            self._aktuelle.set_ausgewaehlt(False)
        self._aktuelle = karte
        karte.set_ausgewaehlt(True)
        self.treffer_scroll.ensureWidgetVisible(karte)
        self._aktionen_aktualisieren(d)
        self._vorschau_zeigen(d, seite)

    def _vorschau_zeigen(self, d: dict, seite: int) -> None:
        pfad = d.get("datei") or ""
        if d.get("typ") == "pdf" and pfad and os.path.exists(pfad):
            self._pdf_pfad = Path(pfad)
            self._pending_seite = seite
            self.vorschau_stack.setCurrentWidget(self.pdf_vorschau)
            self.pdf_vorschau.load_pdf(self._pdf_pfad)
            return
        # Office, Markdown, Mail - oder eine PDF, die es nicht mehr gibt: Text aus dem Index
        self._pdf_pfad = None
        self._pending_seite = None
        self._vorschau_generation += 1
        self.text_vorschau.setHtml("<p style='color:#888888'>Lade Text …</p>")
        self.vorschau_stack.setCurrentWidget(self.text_vorschau)
        thread = DokumentLaden(self.index, self._vorschau_generation, int(d["id"]),
                               self.angezeigte_abfrage or None, self)
        thread.fertig.connect(self._dokument_geladen)
        self._thread_starten(thread)

    def _vorschau_leeren(self) -> None:
        self._pdf_pfad = None
        self._pending_seite = None
        self._vorschau_generation += 1
        self.pdf_vorschau.clear()
        self.text_vorschau.clear()
        self.vorschau_stack.setCurrentWidget(self.vorschau_hinweis)
        self.titel_label.setText("Kein Treffer ausgewählt")
        self.pfad_label.setText("")
        for b in (self.open_button, self.show_button, self.copy_button):
            b.setEnabled(False)
        self.eml_button.setVisible(False)

    def _pdf_seite(self, seite: int) -> None:
        """Auf eine Seite springen; ist die PDF noch nicht geladen, wird die Seite vorgemerkt."""
        if (self.pdf_vorschau.is_showing_document() and self._pdf_pfad is not None
                and self.pdf_vorschau.current_path == self._pdf_pfad):
            self.pdf_vorschau.go_to_page(max(0, int(seite) - 1))
            self._pending_seite = None
        else:
            self._pending_seite = seite

    def _pdf_geladen(self, pfad: Path) -> None:
        if self._pdf_pfad is not None and Path(pfad) == self._pdf_pfad and self._pending_seite:
            self.pdf_vorschau.go_to_page(max(0, int(self._pending_seite) - 1))
            self._pending_seite = None

    def _pdf_fehler(self, _pfad: Path, _meldung: str) -> None:
        self._pending_seite = None  # die Vorschau zeigt den Fehler selbst an

    def _dokument_geladen(self, generation: int, d, seiten) -> None:
        if generation != self._vorschau_generation:
            return
        if d is None:
            self.text_vorschau.setHtml("<p>Dieses Dokument ist nicht mehr im Index.</p>")
            return
        self.text_vorschau.setHtml(dokument_html(d, list(seiten or [])))
        if any(s.get("treffer") for s in seiten or []):
            self.text_vorschau.scrollToAnchor("treffer")
        self.vorschau_fertig.emit(int(d["id"]))

    def _aktionen_aktualisieren(self, d: dict) -> None:
        mail = d.get("typ") == "mail"
        mbox = d.get("format") == "mbox"
        self.titel_label.setText(titel_von(d) or "–")
        self.pfad_label.setText((d.get("ordner") if mbox else d.get("pfad")) or "")
        self.open_button.setEnabled(True)
        self.open_button.setText("Mail öffnen" if mail else "Öffnen")
        self.show_button.setEnabled(not mbox)
        self.copy_button.setEnabled(True)
        self.eml_button.setVisible(mail)
        self.meldung_label.setVisible(False)

    # ------------------------------------------------------------------ Aktionen

    def _mit_aktuellem(self, aktion) -> None:
        if self._aktuelle is not None:
            aktion(self._aktuelle.dok)

    def _meldung(self, text: str) -> None:
        self.meldung_label.setText(text)
        self.meldung_label.setVisible(True)
        self._meldung_timer.start()

    def _aktionen_menue(self, d: dict) -> QMenu:
        """Kontextmenue eines Treffers (ohne exec, auch fuer Tests)."""
        menue = QMenu(self)
        menue.addAction("Mail öffnen" if d.get("typ") == "mail" else "Öffnen", lambda: self._oeffnen(d))
        if d.get("format") != "mbox":
            menue.addAction(f"Im {file_manager_name()} zeigen", lambda: self._im_dateimanager_zeigen(d))
        menue.addAction("Pfad kopieren", lambda: self._pfad_kopieren(d))
        if d.get("typ") == "mail":
            menue.addAction("Als .eml speichern…", lambda: self._eml_speichern(d))
        return menue

    def _kontextmenue_zeigen(self, karte: TrefferKarte, pos: QPoint) -> None:
        self._auswaehlen(karte)
        self._aktionen_menue(karte.dok).exec(pos)

    def _oeffnen(self, d: dict) -> None:
        """PDFs nach Einstellung (Hauptfenster), sonst Standardprogramm; Mails als .eml."""
        if d.get("typ") == "mail":
            try:
                pfad = self.index.mail_als_eml(d)
            except OSError as e:
                self._meldung(f"Die Mail konnte nicht gelesen werden: {e}")
                return
            open_with_default_app(pfad)
            return
        pfad = d.get("datei") or ""
        if not pfad or not os.path.exists(pfad):
            self._meldung("Die Datei existiert nicht mehr.")
            return
        if d.get("typ") == "pdf":
            self.open_pdf_requested.emit(Path(pfad))
        else:
            open_with_default_app(pfad)

    def _im_dateimanager_zeigen(self, d: dict) -> None:
        pfad = d.get("datei") or ""
        if not pfad or not os.path.exists(pfad):
            self._meldung("Die Datei existiert nicht mehr.")
            return
        im_dateimanager_zeigen(pfad)

    def _pfad_kopieren(self, d: dict) -> None:
        QApplication.clipboard().setText(d.get("pfad") or "")
        self._meldung("Pfad kopiert.")

    def _eml_speichern(self, d: dict) -> None:
        endung = ".msg" if d.get("format") == "msg" else ".eml"
        vorschlag = str(Path.home() / (Suchindex.eml_dateiname(titel_von(d)) + endung))
        ziel, _ = QFileDialog.getSaveFileName(self, "Mail speichern", vorschlag, f"E-Mail (*{endung})")
        if not ziel:
            return
        try:
            quelle = self.index.mail_als_eml(d)
            Path(ziel).write_bytes(Path(quelle).read_bytes())
        except OSError as e:
            self._meldung(f"Speichern fehlgeschlagen: {e}")
            return
        self._meldung(f"Gespeichert: {ziel}")

    def _hilfe_zeigen(self) -> None:
        QMessageBox.information(self, "So wird gesucht", HILFE_HTML)

    # ------------------------------------------------------------------ Indexstand und Laeufe

    def refresh_status(self) -> None:
        """Indexstand im Hintergrund lesen (nur wenn die Suche eingerichtet ist)."""
        if self.index is None or not self.konfig.aktiv or self._status_laeuft:
            return
        self._status_laeuft = True
        thread = StatusAbfrage(self.index, self)
        thread.fertig.connect(self._status_da)
        self._thread_starten(thread)

    def _status_da(self, st: dict) -> None:
        self._status_laeuft = False
        self.status = dict(st or {})
        self._werte_fuellen(self.status.get("werte"))
        self.status_label.setText(status_zeile(self.status))
        laeuft = bool(self.status.get("laeuft"))
        aktiv = bool(self.konfig and self.konfig.aktiv)
        self.index_button.setEnabled(aktiv and not laeuft)
        self.index_all_button.setEnabled(aktiv and not laeuft)
        self.anhalten_button.setVisible(laeuft)
        if not laeuft:
            self.anhalten_button.setEnabled(True)
        if laeuft:
            self._status_timer.start()
        else:
            self._status_timer.stop()
        self.status_aktualisiert.emit(self.status)

    def _lauf_starten(self, nur_prioritaet: bool) -> None:
        """Indexlauf als eigenen Prozess starten (``pdfsm-dienst index --hintergrund``)."""
        if self.index is None:
            return
        try:
            prozess = self.index.lauf_starten(nur_prioritaet=nur_prioritaet)
        except OSError as e:
            self._meldung(f"Der Indexlauf konnte nicht gestartet werden: {e}")
            return
        if prozess is None:
            self.status_label.setText("Ein Indexlauf läuft bereits.")
        else:
            self.status_label.setText("Indexlauf gestartet – " + ("die Vorrang-Ordner werden"
                                      if nur_prioritaet else "alle Ordner werden") + " im Hintergrund eingelesen …")
        self.index_button.setEnabled(False)
        self.index_all_button.setEnabled(False)
        self._status_timer.start()
        self._nachlauf_timer.start()

    def _lauf_anhalten(self) -> None:
        """Den laufenden Lauf anhalten (z. B. das Nachtragen der Textebene im Altbestand)."""
        if self.index is None:
            return
        try:
            angehalten = self.index.lauf_anhalten()
        except OSError as e:
            self._meldung(f"Der Lauf konnte nicht angehalten werden: {e}")
            return
        if angehalten:
            self.anhalten_button.setEnabled(False)
            self.status_label.setText("Der Indexlauf hält an, sobald die laufenden Aufträge fertig sind – "
                                      "der nächste Lauf setzt fort …")
        else:
            self.refresh_status()

    def _web_oeffnen(self) -> None:
        """Browser-Oberfläche öffnen; läuft sie noch nicht, wird sie gestartet und öffnet den Browser selbst."""
        if self.index is None:
            return
        if self.index.web_erreichbar():
            QDesktopServices.openUrl(QUrl(self.index.web_adresse()))
            return
        try:
            self.index.web_starten(oeffnen=True)
        except OSError as e:
            self._meldung(f"Die Browser-Oberfläche konnte nicht gestartet werden: {e}")
            return
        self.status_label.setText("Die Browser-Oberfläche wird gestartet …")
        QTimer.singleShot(WEB_PRUEFEN_MS, self._web_pruefen)

    def _web_pruefen(self) -> None:
        """Nach dem Start: antwortet die Oberfläche? Sonst ist der Port belegt oder Flask fehlt."""
        if self.index is None or self.index.web_erreichbar():
            return
        self._meldung(f"Die Browser-Oberfläche antwortet nicht. Ist Port {self.konfig.web_port} von einem anderen "
                      "Programm belegt? Der Port lässt sich unter Einstellungen > Suche ändern.")

    # ------------------------------------------------------------------ Tastatur

    def eventFilter(self, obj, event):  # noqa: N802 (Qt-API)
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if obj is self.search_edit and key == Qt.Key.Key_Down and self._karten:
                self._auswahl_bewegen(1)
                return True
            if obj is self.treffer_scroll:
                if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    self._auswahl_bewegen(1 if key == Qt.Key.Key_Down else -1)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._aktuelle is not None:
                    self._oeffnen(self._aktuelle.dok)
                    return True
        return super().eventFilter(obj, event)
