"""GUI-Tests fuer Issue #244: "Passwortschutz entfernen…" - Schloss, Menue, Passwortabfrage, Original.

Fixtures aus tests/test_office_gui.py (tmp-Pfade, nie die echte Config). Der Papierkorb ist
umgeleitet (tests/conftest.py); die Passwortabfrage (``entsperren._passwort_fragen``) und die
Frage zum Original (``original_wegraeumen._frage``) werden ersetzt.
"""
from __future__ import annotations

import hashlib
import json
import logging

import pymupdf
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLineEdit

from src.core.pdf_entsperren import braucht_passwort
from src.gui import entsperren as en
from src.gui import original_wegraeumen as ow
from tests.test_bild_gui import _fragen, _statusmeldungen
from tests.test_office_gui import (  # noqa: F401 - Fixtures
    _prime_cache_on_load,
    fresh_singletons,
    main_window,
)
from tests.test_pdf_entsperren import BENUTZER, BESITZER, geschuetzte_pdf

ANDERES = "anderes-2001"
ECHTE_FRAGE = ow._frage  # beim Import: vor der Test-Vorgabe "Nein" aus tests/conftest.py


@pytest.fixture(autouse=True)
def cursor_aufraeumen():
    yield
    from PyQt6.QtWidgets import QApplication
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


@pytest.fixture
def scan(fresh_singletons):  # noqa: F811
    ordner = fresh_singletons["tmp_path"] / "Scan"
    ordner.mkdir()
    return ordner


@pytest.fixture
def fenster(main_window, monkeypatch):  # noqa: F811
    """Hauptfenster, dessen neu ausgewaehlte PDFs keine Hintergrund-Analyse starten."""
    _prime_cache_on_load(main_window, monkeypatch)
    return main_window


def _offene_pdf(pfad):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Rechnung Stadtwerke Musterstadt")
    doc.save(str(pfad))
    doc.close()
    return pfad


def _kachel(mw, pfad):
    return next(w for w in mw.pdf_widgets if w.pdf_path == pfad)


def _menue(kachel) -> list[str]:
    return [a.text() for a in kachel._build_context_menu().actions() if not a.isSeparator()]


def _passwoerter(monkeypatch, *antworten):
    """Ersetzt die Passwortabfrage; liefert die Liste der Abfragen ``(Dateinamen, Hinweis)``."""
    gefragt = []
    rest = list(antworten)

    def fragen(parent, pfade, fehler=""):
        gefragt.append(([p.name for p in pfade], fehler))
        return rest.pop(0) if rest else None

    monkeypatch.setattr(en, "_passwort_fragen", fragen)
    return gefragt


def _sha(pfad) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _namen(ordner) -> list[str]:
    return sorted(p.name for p in ordner.iterdir())


# --- Kachel und Menue ---------------------------------------------------------------------

def test_menuepunkt_nur_bei_geschuetzter_pdf(fenster, scan):
    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    offen = _offene_pdf(scan / "Rechnung.pdf")
    rechte = geschuetzte_pdf(scan / "Rechte.pdf", benutzer="")
    fenster._navigate_to_folder(scan)

    k = _kachel(fenster, zu)
    assert _menue(k)[0] == "Passwortschutz entfernen…"
    assert k.geschuetzt and not k._schloss_symbol.isHidden()
    assert "Passwortgeschützt" in k.toolTip()
    for pfad in (offen, rechte):
        andere = _kachel(fenster, pfad)
        assert not any("Passwortschutz" in t for t in _menue(andere))
        assert not andere.geschuetzt and andere._schloss_symbol.isHidden()


def test_menuepunkt_nennt_die_anzahl_der_auswahl(fenster, scan):
    a = geschuetzte_pdf(scan / "A.pdf")
    b = geschuetzte_pdf(scan / "B.pdf")
    fenster._navigate_to_folder(scan)
    fenster.selected_pdfs = [a, b]
    k = _kachel(fenster, a)
    k.selected = True
    assert _menue(k)[0] == "Passwortschutz entfernen (2 PDFs)…"


def test_lade_thread_meldet_schloss_statt_fehler(qtbot, scan):
    """Der echte Lade-Thread: geschuetzte PDF -> Schloss; kaputte PDF -> weiter "Fehler beim Laden"."""
    from src.gui.pdf_thumbnail import PDFThumbnailWidget

    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    kaputt = scan / "kaputt.pdf"
    kaputt.write_bytes(b"kein pdf")
    offen = _offene_pdf(scan / "Rechnung.pdf")

    kacheln = {}
    for pfad in (zu, kaputt, offen):
        kachel = PDFThumbnailWidget(pfad)
        qtbot.addWidget(kachel)
        with qtbot.waitSignal(kachel.thumbnail_ready, timeout=10000):
            pass
        kacheln[pfad] = kachel
    try:
        assert kacheln[zu].geschuetzt and not kacheln[zu]._schloss_symbol.isHidden()
        assert kacheln[zu].thumbnail_label.text() == "" and kacheln[zu]._original_pixmap is None
        assert not kacheln[kaputt].geschuetzt and "Fehler" in kacheln[kaputt].thumbnail_label.text()
        assert not kacheln[offen].geschuetzt and kacheln[offen]._original_pixmap is not None
    finally:
        for kachel in kacheln.values():
            kachel.cleanup()


def test_schloss_passt_sich_der_kachelgroesse_an(qtbot, scan):
    from src.gui import pdf_thumbnail as th
    from src.gui.tile_view import TILE_VIEWS

    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    for ansicht in TILE_VIEWS:
        kachel = th.PDFThumbnailWidget(zu, view=ansicht)
        qtbot.addWidget(kachel)
        with qtbot.waitSignal(kachel.thumbnail_ready, timeout=10000):
            pass
        g = kachel._schloss_symbol.geometry()
        assert g.width() == g.height() >= 16
        assert 0 <= g.left() and g.right() < ansicht.thumb_w and 0 <= g.top() and g.bottom() < ansicht.thumb_h
        assert not kachel.grab().isNull()  # das Schloss laesst sich zeichnen
        kachel.cleanup()


# --- Entsperren ---------------------------------------------------------------------------

def test_richtiges_passwort_erzeugt_kopie_und_behaelt_original(fenster, scan, monkeypatch):
    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    vorher = _sha(zu)
    fenster._navigate_to_folder(scan)
    gefragt = _passwoerter(monkeypatch, BENUTZER)
    gestellt = _fragen(monkeypatch, (False, False))
    meldungen = _statusmeldungen(fenster)

    _kachel(fenster, zu).entsperren_requested.emit(zu)

    kopie = scan / "Auszug (entsperrt).pdf"
    assert _namen(scan) == ["Auszug (entsperrt).pdf", "Auszug.pdf"]
    assert _sha(zu) == vorher and not braucht_passwort(kopie)
    assert gefragt == [(["Auszug.pdf"], "")]
    assert len(gestellt) == 1 and "Auszug.pdf" in gestellt[0] and "Auszug (entsperrt).pdf" in gestellt[0]
    assert "geschützte Original in den Papierkorb" in gestellt[0]
    assert fenster.selected_pdf == kopie  # die Kopie ist ausgewaehlt wie jede andere PDF
    assert {w.pdf_path for w in fenster.pdf_widgets} == {zu, kopie}
    assert not _kachel(fenster, kopie)._braucht_passwort()
    assert any("Kopie ohne Passwortschutz erstellt: Auszug (entsperrt).pdf" in m for m in meldungen)
    assert not fenster._undo_stack  # Original behalten: nichts zum Rueckgaengigmachen


def test_besitzerpasswort_geht_auch(fenster, scan, monkeypatch):
    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    fenster._navigate_to_folder(scan)
    _passwoerter(monkeypatch, BESITZER)
    fenster.on_pdf_entsperren(zu)
    assert not braucht_passwort(scan / "Auszug (entsperrt).pdf")


def test_falsches_passwort_fragt_erneut_und_aendert_nichts(fenster, scan, monkeypatch):
    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    vorher = _sha(zu)
    fenster._navigate_to_folder(scan)
    gefragt = _passwoerter(monkeypatch, "falsch", "auch-falsch")  # danach: Abbruch
    monkeypatch.setattr(ow, "_frage", lambda *a: pytest.fail("Frage zum Original ohne Kopie"))
    meldungen = _statusmeldungen(fenster)

    fenster.on_pdf_entsperren(zu)

    assert len(gefragt) == 3
    assert gefragt[0][1] == "" and "passt nicht" in gefragt[1][1] and "passt nicht" in gefragt[2][1]
    assert _namen(scan) == ["Auszug.pdf"] and _sha(zu) == vorher
    assert any("Abgebrochen" in m for m in meldungen) and not fenster._undo_stack


def test_abbruch_der_abfrage_aendert_nichts(fenster, scan, monkeypatch):
    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    vorher = _sha(zu)
    fenster._navigate_to_folder(scan)
    gefragt = _passwoerter(monkeypatch)  # sofort Abbruch
    monkeypatch.setattr(ow, "_frage", lambda *a: pytest.fail("Frage zum Original nach Abbruch"))
    fenster.on_pdf_entsperren(zu)
    assert len(gefragt) == 1 and _namen(scan) == ["Auszug.pdf"] and _sha(zu) == vorher
    assert {w.pdf_path for w in fenster.pdf_widgets} == {zu}


def test_falsch_dann_richtig(fenster, scan, monkeypatch):
    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    fenster._navigate_to_folder(scan)
    gefragt = _passwoerter(monkeypatch, "falsch", BENUTZER)
    fenster.on_pdf_entsperren(zu)
    assert len(gefragt) == 2 and (scan / "Auszug (entsperrt).pdf").exists()


def test_ganzer_ablauf_mit_den_echten_dialogen(qtbot, fenster, scan, monkeypatch):
    """Nichts ersetzt: Menuepunkt -> echter Passwort-Dialog (falsch, dann richtig) -> echte Frage zum Original."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    fenster._navigate_to_folder(scan)
    monkeypatch.setattr(ow, "_frage", ECHTE_FRAGE)  # die Vorgabe aus conftest ("Nein") zuruecknehmen
    eingaben = ["falsch", BENUTZER]
    gesehen = []
    leerlauf = []

    def bedienen():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, en.PasswortDialog):
            gesehen.append(("passwort", dialog.fehler_label.text(), dialog.eingabe.echoMode()))
            qtbot.keyClicks(dialog.eingabe, eingaben.pop(0))
            QTimer.singleShot(50, bedienen)
            dialog.ok.click()
        elif isinstance(dialog, ow.OriginalFragenDialog):
            gesehen.append(("original", dialog.text(), None))
            dialog.button(dialog.StandardButton.Yes).click()
        else:  # noch kein Dialog da
            leerlauf.append(1)
            if len(leerlauf) > 200:  # nie haengen: ein unerwartetes Fenster schliessen
                for fenster_offen in QApplication.topLevelWidgets():
                    if isinstance(fenster_offen, en.QDialog) and fenster_offen.isVisible():
                        fenster_offen.reject()
                return
            QTimer.singleShot(50, bedienen)

    QTimer.singleShot(50, bedienen)
    aktion = next(a for a in _kachel(fenster, zu)._build_context_menu().actions()
                  if a.text() == "Passwortschutz entfernen…")
    aktion.trigger()

    assert [g[0] for g in gesehen] == ["passwort", "passwort", "original"]
    assert gesehen[0][1] == "" and "passt nicht" in gesehen[1][1]
    assert all(g[2] == QLineEdit.EchoMode.Password for g in gesehen[:2])
    assert "Auszug (entsperrt).pdf" in gesehen[2][1]
    assert _namen(scan) == ["Auszug (entsperrt).pdf"] and not braucht_passwort(scan / "Auszug (entsperrt).pdf")
    fenster.undo_last_action()
    assert _namen(scan) == ["Auszug (entsperrt).pdf", "Auszug.pdf"] and braucht_passwort(zu)


# --- Original wegraeumen --------------------------------------------------------------------

def test_ja_raeumt_original_weg_und_strg_z_holt_es_zurueck(fenster, scan, monkeypatch):
    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    vorher = _sha(zu)
    fenster._navigate_to_folder(scan)
    _passwoerter(monkeypatch, BENUTZER)
    _fragen(monkeypatch, (True, False))

    fenster.on_pdf_entsperren(zu)

    kopie = scan / "Auszug (entsperrt).pdf"
    assert _namen(scan) == ["Auszug (entsperrt).pdf"]
    assert {w.pdf_path for w in fenster.pdf_widgets} == {kopie}
    assert fenster._undo_stack[-1]["type"] == "wegraeumen"
    assert "Auszug.pdf" in fenster._undo_stack[-1]["description"]
    assert fenster.config.get("original_wegraeumen").get("entsperren") is None  # kein Haekchen: nichts gemerkt

    fenster.undo_last_action()
    assert _namen(scan) == ["Auszug (entsperrt).pdf", "Auszug.pdf"]
    assert _sha(zu) == vorher and braucht_passwort(zu)  # das Original ist wieder da, unveraendert


def test_gemerkte_antwort_gilt_nur_fuer_das_entsperren(fenster, scan, monkeypatch):
    a = geschuetzte_pdf(scan / "A.pdf")
    b = geschuetzte_pdf(scan / "B.pdf")
    fenster._navigate_to_folder(scan)
    # "Nach dem Umwandeln immer in den Papierkorb" gilt nicht fuer geschuetzte Originale
    ow.antwort_speichern(fenster.config, "umwandeln", True)
    _passwoerter(monkeypatch, BENUTZER)
    gestellt = _fragen(monkeypatch, (False, True))  # behalten + nicht mehr fragen
    fenster.on_pdf_entsperren(a)
    assert len(gestellt) == 1 and a.exists()
    assert fenster.config.get("original_wegraeumen")["entsperren"] is False
    assert fenster.config.get("original_wegraeumen")["umwandeln"] is True

    _passwoerter(monkeypatch, BENUTZER)
    monkeypatch.setattr(ow, "_frage", lambda *x: pytest.fail("Frage trotz gemerkter Antwort"))
    fenster.on_pdf_entsperren(b)
    assert b.exists() and (scan / "B (entsperrt).pdf").exists()


def test_einstellungen_kennen_die_neue_aktion():
    assert ow.AKTIONEN["entsperren"] == "Nach dem Entfernen des Passwortschutzes"
    from src.utils.config import Config
    assert Config.DEFAULTS["original_wegraeumen"]["entsperren"] is None


def test_ohne_papierkorb_bleibt_das_original_liegen(fenster, scan, monkeypatch):
    from src.gui import original_wegraeumen
    from tests.test_file_manager import _fake_papierkorb

    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    fenster._navigate_to_folder(scan)
    _passwoerter(monkeypatch, BENUTZER)
    _fragen(monkeypatch, (True, False))
    _fake_papierkorb(monkeypatch, scan.parent / "trash", ok=False)
    warnungen = []
    monkeypatch.setattr(original_wegraeumen.QMessageBox, "warning", lambda p, t, text: warnungen.append(text))
    fenster.on_pdf_entsperren(zu)
    assert zu.exists() and (scan / "Auszug (entsperrt).pdf").exists()
    assert warnungen and "Papierkorb nicht verfügbar" in warnungen[0]


def test_signiertes_original_wird_nie_zum_wegraeumen_angeboten(fenster, scan, monkeypatch):
    import pikepdf

    offen = _offene_pdf(scan.parent / "offen.pdf")
    zu = scan / "Vertrag.pdf"
    with pikepdf.open(str(offen)) as pdf:
        pdf.Root.AcroForm = pikepdf.Dictionary(SigFlags=3, Fields=pikepdf.Array())
        pdf.save(str(zu), encryption=pikepdf.Encryption(user=BENUTZER, owner=BESITZER, R=6))
    fenster._navigate_to_folder(scan)
    _passwoerter(monkeypatch, BENUTZER)
    monkeypatch.setattr(ow, "_frage", lambda *a: pytest.fail("signiertes Original zur Wahl gestellt"))
    hinweise = []
    monkeypatch.setattr(en.QMessageBox, "information", lambda p, t, text: hinweise.append(text))
    fenster.on_pdf_entsperren(zu)
    assert zu.exists() and (scan / "Vertrag (entsperrt).pdf").exists()
    assert hinweise and "digital signiert" in hinweise[0] and "Vertrag.pdf" in hinweise[0]


# --- Mehrere Dateien -------------------------------------------------------------------------

def test_ein_passwort_gilt_fuer_alle_markierten(fenster, scan, monkeypatch):
    a = geschuetzte_pdf(scan / "A.pdf")
    b = geschuetzte_pdf(scan / "B.pdf")
    c = geschuetzte_pdf(scan / "C.pdf", benutzer=ANDERES)
    offen = _offene_pdf(scan / "Rechnung.pdf")
    fenster._navigate_to_folder(scan)
    fenster.selected_pdfs = [a, b, c, offen]
    gefragt = _passwoerter(monkeypatch, BENUTZER, ANDERES)
    gestellt = _fragen(monkeypatch, (True, False))
    meldungen = _statusmeldungen(fenster)

    fenster.on_pdf_entsperren(a)

    # erste Abfrage fuer alle geschuetzten (die offene PDF gehoert nicht dazu), zweite nur fuer den Rest
    assert gefragt[0] == (["A.pdf", "B.pdf", "C.pdf"], "")
    assert gefragt[1][0] == ["C.pdf"] and "Anderes Passwort" in gefragt[1][1]
    assert _namen(scan) == ["A (entsperrt).pdf", "B (entsperrt).pdf", "C (entsperrt).pdf", "Rechnung.pdf"]
    assert len(gestellt) == 1 and "3 geschützten Originale" in gestellt[0]  # eine Frage fuer alle
    wegraeumen = [e for e in fenster._undo_stack if e["type"] == "wegraeumen"]
    assert len(wegraeumen) == 1 and len(wegraeumen[0]["eintraege"]) == 3
    assert any("3 Kopien ohne Passwortschutz erstellt, 1 PDF(s) hatten keinen Passwortschutz" in m
               for m in meldungen)
    fenster.undo_last_action()  # ein Strg+Z holt alle drei zurueck
    assert all(p.exists() and braucht_passwort(p) for p in (a, b, c))


def test_abbruch_nach_teilerfolg_behaelt_fertige_kopien(fenster, scan, monkeypatch):
    a = geschuetzte_pdf(scan / "A.pdf")
    c = geschuetzte_pdf(scan / "C.pdf", benutzer=ANDERES)
    fenster._navigate_to_folder(scan)
    fenster.selected_pdfs = [a, c]
    gefragt = _passwoerter(monkeypatch, BENUTZER)  # zweite Abfrage: Abbruch
    gestellt = _fragen(monkeypatch, (True, False))
    meldungen = _statusmeldungen(fenster)

    fenster.on_pdf_entsperren(a)

    assert len(gefragt) == 2
    assert _namen(scan) == ["A (entsperrt).pdf", "C.pdf"]  # nur das entsperrte Original wurde weggeraeumt
    assert len(gestellt) == 1 and "'A.pdf'" in gestellt[0] and "C.pdf" not in gestellt[0]
    assert any("1 PDF(s) bleiben geschützt" in m for m in meldungen)


def test_ohne_geschuetzte_pdf_wird_nicht_gefragt(fenster, scan, monkeypatch):
    offen = _offene_pdf(scan / "Rechnung.pdf")
    fenster._navigate_to_folder(scan)
    monkeypatch.setattr(en, "_passwort_fragen", lambda *a, **k: pytest.fail("Passwortabfrage ohne Schutz"))
    meldungen = _statusmeldungen(fenster)
    fenster.on_pdf_entsperren(offen)
    assert _namen(scan) == ["Rechnung.pdf"] and any("Kein Passwortschutz" in m for m in meldungen)


def test_fehler_je_datei_wird_gemeldet_ohne_passwort(fenster, scan, monkeypatch):
    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    fenster._navigate_to_folder(scan)
    _passwoerter(monkeypatch, BENUTZER)

    def kaputt(pfad, passwort):
        raise RuntimeError(f"intern {passwort}")

    monkeypatch.setattr(en, "entsperren", kaputt)
    warnungen = []
    monkeypatch.setattr(en.QMessageBox, "warning", lambda p, t, text: warnungen.append(text))
    fenster.on_pdf_entsperren(zu)
    assert warnungen and "Auszug.pdf" in warnungen[0] and "RuntimeError" in warnungen[0]
    assert BENUTZER not in warnungen[0] and _namen(scan) == ["Auszug.pdf"]


# --- Das Passwort bleibt nirgends liegen ----------------------------------------------------------

def test_passwort_wird_nicht_gespeichert_und_nicht_protokolliert(fenster, scan, monkeypatch, caplog, capsys,
                                                                 fresh_singletons):  # noqa: F811
    zu = geschuetzte_pdf(scan / "Auszug.pdf")
    fenster._navigate_to_folder(scan)
    _passwoerter(monkeypatch, "falsch-4711", BENUTZER)
    _fragen(monkeypatch, (True, True))
    meldungen = _statusmeldungen(fenster)
    gemeldet = []
    monkeypatch.setattr(en, "index_melden", lambda *a, **k: gemeldet.append((a, k)))

    with caplog.at_level(logging.DEBUG):
        fenster.on_pdf_entsperren(zu)
    fenster.config.save()

    tmp = fresh_singletons["tmp_path"]
    ausgabe = capsys.readouterr()
    texte = [caplog.text, ausgabe.out, ausgabe.err, repr(meldungen), repr(gemeldet), repr(fenster._undo_stack),
             json.dumps(fenster.config._config, default=str)]
    for geheim in (BENUTZER, "falsch-4711"):
        assert not any(geheim in t for t in texte)
        for datei in tmp.rglob("*"):
            # Config, Datenbank, Protokolle, Kopie: nirgends steht das Passwort
            if datei.is_file():
                roh = datei.read_bytes()
                assert geheim.encode() not in roh and geheim.encode("utf-16-le") not in roh, datei.name
        assert all(geheim not in str(wert) for wert in vars(fenster).values() if isinstance(wert, (str, bytes)))


# --- Passwort-Dialog -------------------------------------------------------------------------

def test_dialog_verdeckt_die_eingabe_und_sperrt_ok_bei_leerem_feld(qtbot, scan):
    zu = scan / "Auszug.pdf"
    dialog = en.PasswortDialog(None, [zu])
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Passwortschutz entfernen"
    assert dialog.eingabe.echoMode() == QLineEdit.EchoMode.Password
    assert not dialog.ok.isEnabled() and not dialog.fehler_label.isVisibleTo(dialog)
    qtbot.keyClicks(dialog.eingabe, "abc")
    assert dialog.ok.isEnabled() and dialog.passwort() == "abc"
    dialog.zeigen.setChecked(True)
    assert dialog.eingabe.echoMode() == QLineEdit.EchoMode.Normal
    dialog.leeren()
    assert dialog.passwort() == "" and dialog.eingabe.echoMode() == QLineEdit.EchoMode.Password
    assert not dialog.ok.isEnabled()
    texte = " ".join(label.text() for label in dialog.findChildren(type(dialog.fehler_label)))
    assert "Auszug.pdf" in texte and "nicht gespeichert" in texte and "nicht an die KI" in texte


def test_dialog_zeigt_fehler_und_mehrere_dateien(qtbot, scan):
    pfade = [scan / f"Auszug {i}.pdf" for i in range(1, 8)]
    dialog = en.PasswortDialog(None, pfade, "Das Passwort passt nicht.")
    qtbot.addWidget(dialog)
    texte = " ".join(label.text() for label in dialog.findChildren(type(dialog.fehler_label)))
    assert "7 PDFs" in texte and "Auszug 5.pdf" in texte and "(+2)" in texte and "Auszug 6.pdf" not in texte
    assert dialog.fehler_label.text() == "Das Passwort passt nicht." and dialog.fehler_label.isVisibleTo(dialog)


def test_passwort_fragen_liefert_eingabe_oder_none(qtbot, scan, monkeypatch):
    zu = scan / "Auszug.pdf"
    dialoge = []

    def bestaetigen(self):
        dialoge.append(self)
        self.eingabe.setText("abc")
        return en.QDialog.DialogCode.Accepted

    monkeypatch.setattr(en.PasswortDialog, "exec", bestaetigen)
    assert en._passwort_fragen(None, [zu]) == "abc"
    assert dialoge[0].passwort() == ""  # das Feld ist danach leer

    monkeypatch.setattr(en.PasswortDialog, "exec", lambda self: en.QDialog.DialogCode.Rejected)
    assert en._passwort_fragen(None, [zu]) is None


def test_dialog_eingabetaste_bestaetigt_und_esc_bricht_ab(qtbot, scan):
    dialog = en.PasswortDialog(None, [scan / "Auszug.pdf"])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.keyClicks(dialog.eingabe, "abc")
    with qtbot.waitSignal(dialog.accepted, timeout=2000):
        qtbot.keyClick(dialog.eingabe, Qt.Key.Key_Return)
    dialog2 = en.PasswortDialog(None, [scan / "Auszug.pdf"])
    qtbot.addWidget(dialog2)
    dialog2.show()
    with qtbot.waitSignal(dialog2.rejected, timeout=2000):
        qtbot.keyClick(dialog2, Qt.Key.Key_Escape)
