"""GUI-Tests fuer den Reiter „Suche“ (Phase 4 der PDFsuche-Integration).

Ein kleiner Index entsteht im Test (PDF mit drei Seiten, Markdown, docx,
Thunderbird-mbox); die Ansicht liest ihn ueber eine Config in ``tmp_path``.
Geprueft werden: Hinweis ohne Einrichtung, Abfrage im Thread und Trefferliste,
Verwerfen veralteter Abfragen, Sprung der PDF-Vorschau auf die Trefferseite,
Textvorschau fuer Markdown und Mails, Filter, Aktionen (Oeffnen, im
Dateimanager zeigen, Pfad kopieren, Mail als .eml), Indexstand mit „Jetzt
indizieren“ und das Nachladen weiterer Treffer. Oeffnen und Dateimanager sind
gepatcht, es wird nichts wirklich gestartet.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog

from src.gui.search_view import SearchView, dokument_html, markiert_html, status_zeile
from src.search.indexer import Indexer
from src.search.suchindex import Suchindex
from src.utils.config import Config
from tests import helfer_suche as h


@pytest.fixture
def index_konfig(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    h.pdf_mit_text(ablage / "Vertrag.pdf", [
        "Erste Seite ohne Besonderheiten",
        "Zweite Seite: Kuendigungsfrist im Mietvertrag drei Monate",
        "Dritte Seite mit Unterschrift",
    ])
    (ablage / "Notiz.md").write_text("# Notiz\nKuendigungsfrist beachten, Mietvertrag kuendigen",
                                      encoding="utf-8")
    h.docx(ablage / "Brief.docx", ["Sehr geehrte Damen und Herren", "Anlage: Mietvertrag"])
    konto = tmp_path / "Mail" / "pop.example.invalid"
    konto.mkdir(parents=True)
    h.mbox(konto / "Inbox", [h.mail_roh("Kuendigungsfrist Mietvertrag", text="Hallo, die Frist endet im Maerz",
                                        datum="Wed, 10 Jan 2024 10:00:00 +0100", mozilla_status="0000")])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], prioritaet=[str(ablage)],
                           mails_aktiv=True, mail_ordner=[str(tmp_path / "Mail")])
    assert Indexer(konfig, synchron=True).lauf() == 0
    return konfig


@pytest.fixture
def view(qtbot, tmp_path, index_konfig):
    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_search_config(index_konfig)
    v = SearchView(cfg)
    qtbot.addWidget(v)
    v.resize(1100, 700)
    yield v
    v.shutdown()


def _suchen(qtbot, view, text):
    view.search_edit.setText(text)
    with qtbot.waitSignal(view.suche_fertig, timeout=15000):
        view._suche_starten()
    return view.karten()


def _karte(view, typ):
    return next(k for k in view.karten() if k.dok["typ"] == typ)


# --------------------------------------------------------------------------- Darstellung (ohne Qt-Ereignisse)

def test_darstellungshelfer():
    html = markiert_html("a  \x02b<\x03 \n c")
    assert html == 'a <span style="background-color:#fff0a0; color:#000000;"><b>b&lt;</b></span> c'
    assert "\n" in markiert_html("x\ny", zeilen=True)
    assert status_zeile({"vorhanden": False}).startswith("Noch kein Index")
    s = status_zeile({"vorhanden": True, "dokumente": 1234, "pro_typ": {"mail": 1000, "pdf": 234},
                      "ocr_ausstehend_seiten": 5, "laeuft": True, "fortschritt": "Laufwerke – gelesen 3"})
    assert "1.234 Dokumente (PDF 234, Mails 1.000)" in s
    assert "OCR ausstehend: 5 Seiten" in s and "Indexlauf aktiv: Laufwerke" in s
    s = status_zeile({"vorhanden": True, "dokumente": 1, "pro_typ": {"pdf": 1}, "laeufe": [
        {"beginn": "2026-01-01 03:00", "status": "fertig"}], "ocr_grund": "Tesseract nicht gefunden"})
    assert "Letzter Lauf: 2026-01-01 03:00 (fertig)" in s and "Texterkennung aus (Tesseract nicht gefunden)" in s
    html = dokument_html({"typ": "pdf", "name": "x.pdf", "datei": "/nirgends/x.pdf", "pfad": "/nirgends/x.pdf"},
                         [{"seite": 1, "quelle": "ocr", "text": "Hallo \x02Welt\x03", "treffer": True}])
    assert 'name="treffer"' in html and "Seite 1 · OCR" in html and "existiert nicht mehr" in html


# --------------------------------------------------------------------------- Einrichtung

def test_hinweis_wenn_nicht_eingerichtet(qtbot, tmp_path, index_konfig):
    cfg = Config(config_path=tmp_path / "config.json")
    v = SearchView(cfg)
    qtbot.addWidget(v)
    assert v.hinweis.isVisibleTo(v) and not v.suchbereich.isEnabled() and not v.index_button.isEnabled()
    with qtbot.waitSignal(v.einrichten_requested, timeout=1000):
        v.einrichten_button.click()
    # Nach der Einrichtung (Einstellungen > Suche) liest refresh_settings() die Konfiguration neu
    cfg.set_search_config(index_konfig)
    v.refresh_settings()
    assert not v.hinweis.isVisibleTo(v) and v.suchbereich.isEnabled() and v.index_button.isEnabled()
    v.shutdown()


# --------------------------------------------------------------------------- Abfrage und Trefferliste

def test_abfrage_im_thread_fuellt_trefferliste(qtbot, view):
    karten = _suchen(qtbot, view, "Kuendigungsfrist")
    assert sorted(k.dok["typ"] for k in karten) == ["mail", "md", "pdf"]
    assert view.count_label.text().startswith("3 Dokumente")
    assert not view.hilfe_label.isVisibleTo(view)
    pdf = _karte(view, "pdf")
    assert pdf.dok["stellen"][0]["seite"] == 2
    assert "S. 2" in pdf.stellen_labels[0].text() and "#fff0a0" in pdf.stellen_labels[0].text()
    mail = _karte(view, "mail")
    assert "MAIL" in mail.kopf_label.text() and "Kuendigungsfrist Mietvertrag" in mail.kopf_label.text()
    assert "Thunderbird/pop.example.invalid/Inbox" in mail.pfad_label.text()
    # Keine Treffer
    karten = _suchen(qtbot, view, "xyzzyGibtEsNicht")
    assert karten == [] and view.count_label.text().startswith("Keine Treffer")
    # Feld leeren: Liste leer, Hilfe wieder sichtbar
    view.search_edit.clear()
    assert view.karten() == [] and view.hilfe_label.isVisibleTo(view) and view.count_label.text() == ""


def test_veraltete_abfrage_wird_verworfen(qtbot, view, monkeypatch):
    original = Suchindex.suche

    def langsam(self, abfrage, **argumente):
        if abfrage == "Mietvertrag":
            time.sleep(0.6)
        return original(self, abfrage, **argumente)

    monkeypatch.setattr(Suchindex, "suche", langsam)
    view.search_edit.setText("Mietvertrag")
    view._suche_starten()
    view.search_edit.setText("Notiz")
    with qtbot.waitSignal(view.suche_fertig, timeout=15000):
        view._suche_starten()
    assert view.angezeigte_abfrage == "Notiz"
    qtbot.waitUntil(lambda: view.verworfene_ergebnisse == 1, timeout=5000)
    assert view.angezeigte_abfrage == "Notiz" and [k.dok["name"] for k in view.karten()] == ["Notiz.md"]


def test_weitere_treffer_laden(qtbot, view):
    view.seitengroesse = 3
    karten = _suchen(qtbot, view, "Mietvertrag")
    assert len(karten) == 3 and view.mehr_button.isVisibleTo(view) and view.count_label.text().startswith("4 Dokumente")
    with qtbot.waitSignal(view.suche_fertig, timeout=15000):
        view.mehr_button.click()
    assert len(view.karten()) == 4 and not view.mehr_button.isVisibleTo(view)


def test_filter_typ_zeitraum_ordner_und_sortierung(qtbot, view):
    view.typ_buttons["mail"].click()
    assert [k.dok["typ"] for k in _suchen(qtbot, view, "Mietvertrag")] == ["mail"]
    view.typ_buttons[""].click()
    assert len(_suchen(qtbot, view, "Mietvertrag")) == 4
    # Aelteste zuerst: die Mail von 2024 vor den heute erzeugten Dateien
    view.sort_combo.setCurrentIndex(view.sort_combo.findData("alt"))
    assert _suchen(qtbot, view, "Mietvertrag")[0].dok["typ"] == "mail"
    # Zeitraum Januar 2024: nur die Mail
    view.zeitraum_edit.setText("Jan 2024")
    assert view._filter_argumente()["von"] == "2024-01-01" and view._filter_argumente()["bis"] == "2024-01-31"
    assert [k.dok["typ"] for k in _suchen(qtbot, view, "Mietvertrag")] == ["mail"]
    # Unlesbar: roter Rand, Hinweis, keine Datumsgrenze in der Abfrage
    view.zeitraum_edit.setText("Jan 20x4")
    assert "von" not in view._filter_argumente() and "#d32f2f" in view.zeitraum_edit.edit.styleSheet()
    view.zeitraum_edit.setText("")
    assert "von" not in view._filter_argumente() and "bis" not in view._filter_argumente()
    # Offener Bereich ab 2025: nur die heute erzeugten Dateien, nicht die Mail von 2024
    view.zeitraum_edit.setText("ab 2025")
    assert "mail" not in [k.dok["typ"] for k in _suchen(qtbot, view, "Mietvertrag")]
    view.zeitraum_edit.setText("")
    # Ordnerfilter: nur die Dateien unter „Ablage“, nicht das Postfach
    view.ordner_edit.setText("Ablage")
    assert sorted(k.dok["typ"] for k in _suchen(qtbot, view, "Mietvertrag")) == ["md", "office", "pdf"]


# --------------------------------------------------------------------------- Vorschau

def test_pdf_treffer_springt_auf_trefferseite(qtbot, view):
    _suchen(qtbot, view, "Kuendigungsfrist")
    pdf = _karte(view, "pdf")
    with qtbot.waitSignal(view.pdf_vorschau.document_loaded, timeout=10000):
        qtbot.mouseClick(pdf, Qt.MouseButton.LeftButton)
    assert view.vorschau_stack.currentWidget() is view.pdf_vorschau
    qtbot.waitUntil(lambda: view.pdf_vorschau.current_page() == 1, timeout=3000)
    assert pdf.ist_ausgewaehlt() and view.titel_label.text() == "Vertrag.pdf"
    assert view.open_button.isEnabled() and view.show_button.isEnabled() and not view.eml_button.isVisibleTo(view)
    # Link „S. 3“ einer Fundstelle springt in der geladenen PDF weiter
    view._seite_angeklickt(pdf, 3)
    qtbot.waitUntil(lambda: view.pdf_vorschau.current_page() == 2, timeout=3000)


def test_textvorschau_fuer_markdown_und_mail(qtbot, view):
    _suchen(qtbot, view, "Kuendigungsfrist")
    md = _karte(view, "md")
    with qtbot.waitSignal(view.vorschau_fertig, timeout=10000) as blocker:
        qtbot.mouseClick(md, Qt.MouseButton.LeftButton)
    assert blocker.args == [md.dok["id"]]
    assert view.vorschau_stack.currentWidget() is view.text_vorschau
    assert "Kuendigungsfrist" in view.text_vorschau.toPlainText() and "fff0a0" in view.text_vorschau.toHtml()
    mail = _karte(view, "mail")
    with qtbot.waitSignal(view.vorschau_fertig, timeout=10000):
        qtbot.mouseClick(mail, Qt.MouseButton.LeftButton)
    text = view.text_vorschau.toPlainText()
    assert "Von: absender@example.invalid" in text and "Frist endet" in text
    assert view.eml_button.isVisibleTo(view) and not view.show_button.isEnabled()
    assert view.open_button.text() == "Mail öffnen" and not md.ist_ausgewaehlt() and mail.ist_ausgewaehlt()


def test_auswahl_per_tastatur(qtbot, view):
    _suchen(qtbot, view, "Mietvertrag")
    qtbot.keyClick(view.search_edit, Qt.Key.Key_Down)
    assert view.aktuelle_karte() is view.karten()[0]
    qtbot.keyClick(view.treffer_scroll, Qt.Key.Key_Down)
    assert view.aktuelle_karte() is view.karten()[1]
    qtbot.keyClick(view.treffer_scroll, Qt.Key.Key_Up)
    assert view.aktuelle_karte() is view.karten()[0]


# --------------------------------------------------------------------------- Aktionen

def test_aktionen_oeffnen_zeigen_kopieren_eml(qtbot, view, monkeypatch, tmp_path):
    geoeffnet, gezeigt = [], []
    monkeypatch.setattr("src.gui.search_view.open_with_default_app", lambda p: geoeffnet.append(str(p)))
    monkeypatch.setattr("src.gui.search_view.im_dateimanager_zeigen", lambda p: gezeigt.append(str(p)))
    _suchen(qtbot, view, "Mietvertrag")
    pdf, md, mail = _karte(view, "pdf"), _karte(view, "md"), _karte(view, "mail")

    with qtbot.waitSignal(view.open_pdf_requested, timeout=1000) as blocker:
        view._oeffnen(pdf.dok)
    assert blocker.args == [Path(pdf.dok["datei"])]
    view._oeffnen(md.dok)
    assert geoeffnet == [md.dok["datei"]]
    view._im_dateimanager_zeigen(md.dok)
    assert gezeigt == [md.dok["datei"]]
    view._pfad_kopieren(md.dok)
    assert QApplication.clipboard().text() == md.dok["pfad"]

    # Mail: als .eml im Temp-Ordner, die mbox bleibt unberuehrt
    view._oeffnen(mail.dok)
    eml = Path(geoeffnet[-1])
    assert eml.suffix == ".eml" and b"Subject: Kuendigungsfrist Mietvertrag" in eml.read_bytes()
    ziel = tmp_path / "abgelegt.eml"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(ziel), "")))
    view._eml_speichern(mail.dok)
    assert b"Frist endet im Maerz" in ziel.read_bytes()

    # Kontextmenue je Typ
    assert [a.text() for a in view._aktionen_menue(mail.dok).actions()] == [
        "Mail öffnen", "Pfad kopieren", "Als .eml speichern…"]
    texte = [a.text() for a in view._aktionen_menue(pdf.dok).actions()]
    assert texte[0] == "Öffnen" and texte[1] == "📂 Im Ordner anzeigen"
    assert texte[2].startswith("Im ") and texte[3:] == ["Pfad kopieren"]
    # Markdown ist nicht sortierbar: kein "Im Ordner anzeigen"
    assert "📂 Im Ordner anzeigen" not in [a.text() for a in view._aktionen_menue(md.dok).actions()]

    # "Im Ordner anzeigen" meldet die Datei ans Hauptfenster
    gemeldet = []
    view.im_ordner_anzeigen_requested.connect(gemeldet.append)
    view._im_ordner_anzeigen(pdf.dok)
    assert gemeldet == [Path(pdf.dok["datei"])]

    # Datei weg: Meldung statt Oeffnen
    Path(md.dok["datei"]).unlink()
    view._oeffnen(md.dok)
    assert len(geoeffnet) == 2 and view.meldung_label.isVisibleTo(view)
    assert "existiert nicht mehr" in view.meldung_label.text()


# --------------------------------------------------------------------------- Indexstand

def test_status_und_jetzt_indizieren(qtbot, view, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(Suchindex, "lauf_starten", lambda self, **kw: aufrufe.append(kw) or object())
    with qtbot.waitSignal(view.status_aktualisiert, timeout=10000):
        view.refresh_status()
    text = view.status_label.text()
    assert "4 Dokumente" in text and "PDF 1" in text and "Mails 1" in text and "Letzter Lauf" in text
    assert view.index_button.isEnabled() and view.index_all_button.isEnabled()

    view.index_button.click()
    assert aufrufe == [{"nur_prioritaet": True}]
    assert not view.index_button.isEnabled() and "Vorrang-Ordner" in view.status_label.text()
    view._lauf_starten(False)
    assert aufrufe[-1] == {"nur_prioritaet": False}

    monkeypatch.setattr(Suchindex, "lauf_starten", lambda self, **kw: None)
    view._lauf_starten(True)
    assert "läuft bereits" in view.status_label.text()

    # Waehrend eines Laufs bleiben die Knoepfe aus, der Stand wird periodisch gelesen
    monkeypatch.setattr(Suchindex, "laeuft_gerade", lambda self: True)
    with qtbot.waitSignal(view.status_aktualisiert, timeout=10000):
        view.refresh_status()
    assert "Indexlauf aktiv" in view.status_label.text()
    assert not view.index_button.isEnabled() and view._status_timer.isActive()


def test_status_ohne_datenbank(qtbot, tmp_path):
    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set_search_config(h.konfig_fuer(tmp_path, wurzeln=[str(tmp_path)]))
    v = SearchView(cfg)
    qtbot.addWidget(v)
    with qtbot.waitSignal(v.status_aktualisiert, timeout=10000):
        v.refresh_status()
    assert v.status_label.text().startswith("Noch kein Index") and v.index_button.isEnabled()
    assert _suchen(qtbot, v, "irgendwas") == [] and v.count_label.text().startswith("Keine Treffer")
    v.shutdown()
