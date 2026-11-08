"""Reiter "Korrespondenten" (Issue #160): Liste aus dem Suchindex, Dokumente, KI-Abgleich, Aufraeumen.

Alles in tmp_path (Konfiguration, history.db, Suchindex); KI nur als Fake, kein Netz.
"""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QMessageBox

from src.gui import korrespondenten_view as kv_mod
from src.gui.korrespondenten_view import KorrespondentenView
from src.ml.hybrid_classifier import HybridFilename


def _pdf(pfad: Path) -> Path:
    import pikepdf

    pfad.parent.mkdir(parents=True, exist_ok=True)
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(pfad)
    return pfad


class FakeProvider:
    def __init__(self, antwort: str = '{"paare": []}'):
        self.antwort = antwort
        self.fragen: list[str] = []

    def answer_with_context(self, system_prompt, context_docs, user_question, max_tokens=1000):
        self.fragen.append(user_question)
        return self.antwort


class FakeHybrid:
    """Wie HybridClassifier.suggest_filename: liefert je Dateiname einen KI-Vorschlag mit Korrespondent."""

    def __init__(self, antworten: dict | None = None, provider: FakeProvider | None = None, warten=None):
        self.antworten = antworten or {}
        self.llm_provider = provider or FakeProvider()
        self.warten = warten
        self.aufrufe: list[str] = []
        self.last_llm_error = None

    def is_llm_available(self):
        return True

    def get_llm_provider_name(self):
        return "Fake-KI"

    def suggest_filename(self, text, current_filename, **kw):
        self.aufrufe.append(current_filename)
        if self.warten:
            self.warten()
        return [HybridFilename(filename="neu.pdf", reason="", confidence=0.9, source="llm",
                               metadata={"korrespondent": self.antworten.get(current_filename, "")})]


@pytest.fixture
def umgebung(tmp_path):
    from src.utils.config import Config
    from src.utils.database import Database

    cfg = Config(config_path=tmp_path / "config.json")
    cfg.set("suche", {"aktiv": True})
    cfg.set("llm", {"provider": "ollama"})
    db = Database(db_path=str(tmp_path / "history.db"))
    ablage = tmp_path / "Ablage"

    def dok(rel: str, korrespondent: str, **felder) -> Path:
        pfad = _pdf(ablage / rel)
        db.suchindex.metadaten_setzen(str(pfad), {"korrespondent": korrespondent, **felder},
                                      text=f"Text von {pfad.name}", lesen=False)
        return pfad

    return SimpleNamespace(cfg=cfg, db=db, ablage=ablage, dok=dok, tmp=tmp_path)


@pytest.fixture
def view_bauen(qtbot, umgebung):
    erzeugt = []

    def bauen(hybrid=None):
        v = KorrespondentenView(umgebung.db, umgebung.cfg, hybrid, wurzeln=lambda: [umgebung.ablage])
        qtbot.addWidget(v)
        erzeugt.append(v)
        return v

    yield bauen
    for v in erzeugt:
        v.shutdown()


def _texte(view) -> list[str]:
    return [view.liste.item(i).text() for i in range(view.liste.count()) if not view.liste.item(i).isHidden()]


def test_hinweis_ohne_eingerichtete_suche(umgebung, view_bauen, qtbot):
    umgebung.cfg.set("suche", {"aktiv": False})
    view = view_bauen()
    view.refresh()
    assert not view.hinweis.isHidden()
    assert view.inhalt.isHidden()
    with qtbot.waitSignal(view.einrichten_requested, timeout=1000):
        view.einrichten_button.click()


def test_liste_aus_index_gruppiert_nach_anzahl(umgebung, view_bauen):
    umgebung.dok("Energie/a.pdf", "Stadtwerke Göttingen AG")
    umgebung.dok("Energie/b.pdf", "Stadtwerke Goettingen")
    umgebung.dok("Energie/c.pdf", "stadtwerke göttingen")
    umgebung.dok("Telefon/d.pdf", "Telekom")
    umgebung.dok("Telefon/e.pdf", "Telekom Deutschland")
    umgebung.dok("Bank/f.pdf", "")
    view = view_bauen()
    view.refresh()
    assert view.hinweis.isHidden()
    texte = _texte(view)
    assert texte[0].endswith("(3)") and "tadtwerke" in texte[0]
    assert texte[1:] == ["Telekom  (1)", "Telekom Deutschland  (1)"]
    view.filter_edit.setText("goett")
    assert len(_texte(view)) == 1


def test_klick_zeigt_dokumente_neueste_zuerst_und_aktionen(umgebung, view_bauen, qtbot):
    alt = umgebung.dok("Energie/2023/alt.pdf", "Stadtwerke", buchungsdatum="2023-05-01", kategorie="Rechnung")
    neu = umgebung.dok("Energie/2024/neu.pdf", "Stadtwerke AG", buchungsdatum="2024-02-03", kategorie="Vertrag")
    view = view_bauen()
    view.refresh()
    view.liste.setCurrentRow(0)

    baum = view.dokumente
    assert baum.topLevelItemCount() == 2
    erste = baum.topLevelItem(0)
    assert [erste.text(i) for i in range(4)] == [
        "2024-02-03", "neu.pdf", str(Path("Ablage") / "Energie" / "2024"), "Vertrag"]
    assert baum.topLevelItem(1).text(1) == "alt.pdf"
    assert "Stadtwerke" in view.dokumente_label.text() and "(2)" in view.dokumente_label.text()

    with qtbot.waitSignal(view.dokumente_gewaehlt, timeout=1000) as sig:
        erste.setSelected(True)
    assert [Path(d["datei"]) for d in sig.args[0]] == [neu]
    with qtbot.waitSignal(view.dokument_oeffnen, timeout=1000) as sig:
        baum.itemDoubleClicked.emit(baum.topLevelItem(1), 1)
    assert sig.args[0] == alt

    menue = view.dokument_menue(view.angezeigte_dokumente()[0])
    texte = [a.text() for a in menue.actions()]
    from src.gui.pfad_aktionen import zeigen_text
    assert texte == [zeigen_text(), "Ordner links öffnen"]
    with qtbot.waitSignal(view.ordner_oeffnen, timeout=1000) as sig:
        menue.actions()[1].trigger()
    assert sig.args[0] == neu.parent


def test_waehlen_von_aussen(umgebung, view_bauen):
    umgebung.dok("a.pdf", "Stadtwerke Göttingen")
    umgebung.dok("b.pdf", "Telekom")
    view = view_bauen()
    view.filter_edit.setText("Telekom")
    assert view.waehlen("stadtwerke goettingen") is True
    assert view.filter_edit.text() == ""  # Filter aufgehoben, damit die Auswahl sichtbar ist
    assert view.liste.currentItem().text().startswith("Stadtwerke Göttingen")
    assert view.dokumente.topLevelItemCount() == 1
    assert view.waehlen("Gibt es nicht") is False
    assert view.dokumente.topLevelItemCount() == 0
    assert "Gibt es nicht" in view.status_label.text()


def test_ki_fuehrt_unsichere_schreibweisen_automatisch_zusammen(umgebung, view_bauen, qtbot):
    for i in range(3):
        umgebung.dok(f"g{i}.pdf", "Stadtwerke Göttingen")
    umgebung.dok("kurz.pdf", "Stadtwerke GÖ")
    umgebung.dok("kassel.pdf", "Telekom")
    provider = FakeProvider('```json\n{"paare": [{"nr": 1, "gleich": true}]}\n```')
    view = view_bauen(FakeHybrid(provider=provider))

    with qtbot.waitSignal(view.abgleich_fertig, timeout=5000) as sig:
        view.refresh()
    assert sig.args == [1]
    assert '"Stadtwerke Göttingen" | "Stadtwerke GÖ"' in provider.fragen[0]
    assert _texte(view) == ["Stadtwerke Göttingen  (4)", "Telekom  (1)"]
    eintrag = umgebung.db.get_korrespondent("Stadtwerke Göttingen")
    assert eintrag["aliases"] == ["Stadtwerke GÖ"]
    # Der Index bleibt, wie er war - die Zuordnung gilt beim Anzeigen und Lernen
    assert ("Stadtwerke GÖ", 1) in umgebung.db.suchindex.werte_mit_anzahl("korrespondent")
    umgebung.db.learn_korrespondent_metadata("Stadtwerke GÖ", {"subject": "Energie"})
    assert umgebung.db.get_all_korrespondenten() == ["Stadtwerke Göttingen"]

    # Einmal je Sitzung, und gepruefte Paare werden nie wieder gefragt
    view.refresh()
    zweite = view_bauen(FakeHybrid(provider=provider))
    zweite.refresh()
    qtbot.wait(50)
    assert len(provider.fragen) == 1


def test_ki_sagt_verschieden_dann_bleibt_es_getrennt(umgebung, view_bauen, qtbot):
    umgebung.dok("a.pdf", "Stadtwerke Göttingen")
    umgebung.dok("b.pdf", "Stadtwerke Gö")
    view = view_bauen(FakeHybrid(provider=FakeProvider('{"paare": [{"nr": 1, "gleich": false}]}')))
    with qtbot.waitSignal(view.abgleich_fertig, timeout=5000) as sig:
        view.refresh()
    assert sig.args == [0]
    assert len(_texte(view)) == 2
    assert umgebung.db.list_korrespondenten() == []


@pytest.fixture
def aufraeumen_umgebung(umgebung):
    umgebung.cfg.set("owner_name", "Dr. Johannes Härle-Wack")
    umgebung.cfg.set("owner_name_variants", "J. Härle")
    pfade = SimpleNamespace(
        mietvertrag=umgebung.dok("Miete/mietvertrag.pdf", "Haus & Grund"),
        eigener=umgebung.dok("Praxis/arztbrief.pdf", "J. Härle"),
        leer=umgebung.dok("Sonstiges/leer.pdf", ""),
        gut=umgebung.dok("Energie/strom.pdf", "Stadtwerke"),
    )
    _pdf(umgebung.tmp / "Woanders" / "fremd.pdf")
    umgebung.db.suchindex.metadaten_setzen(str(umgebung.tmp / "Woanders" / "fremd.pdf"), {"korrespondent": ""},
                                           text="x", lesen=False)
    return pfade


def _fertig(view, qtbot, ausloesen):
    with qtbot.waitSignal(view.aufraeumen_fertig, timeout=10000) as sig:
        ausloesen()
    from src.search.meldungen import meldungen
    meldungen.warten(5.0)
    return sig.args[0]


def test_aufraeumen_bewertet_nur_auffaellige_und_schreibt_pdf_und_index(
        umgebung, aufraeumen_umgebung, view_bauen, qtbot, monkeypatch):
    from src.core.pdf_metadata import read_metadata

    def nie_fragen(*a, **k):
        raise AssertionError("Lokaler Anbieter: keine Rueckfrage erwartet")
    monkeypatch.setattr(kv_mod.QMessageBox, "question", nie_fragen)
    hybrid = FakeHybrid({
        "mietvertrag.pdf": "Max Mieter",
        "arztbrief.pdf": "Erika Patientin",
        "leer.pdf": "Haus und Grund",          # wieder auffaellig -> bleibt, wie es ist
    })
    view = view_bauen(hybrid)
    view.refresh(abgleich=False)
    stand = _fertig(view, qtbot, view.aufraeumen)

    assert sorted(hybrid.aufrufe) == ["arztbrief.pdf", "leer.pdf", "mietvertrag.pdf"]
    assert stand["gesamt"] == 3 and stand["geaendert"] == 2 and stand["unveraendert"] == 1
    assert not stand["abgebrochen"]
    assert read_metadata(aufraeumen_umgebung.mietvertrag).korrespondent == "Max Mieter"
    assert read_metadata(aufraeumen_umgebung.eigener).korrespondent == "Erika Patientin"
    werte = dict(umgebung.db.suchindex.werte_mit_anzahl("korrespondent"))
    assert werte == {"Max Mieter": 1, "Erika Patientin": 1, "Stadtwerke": 1}
    assert "2 geändert" in view.status_label.text()
    assert view.fortschritt_box.isHidden()


def test_aufraeumen_bei_cloud_nur_nach_rueckfrage(umgebung, aufraeumen_umgebung, view_bauen, qtbot, monkeypatch):
    umgebung.cfg.set("llm", {"provider": "claude"})
    fragen = []

    def nein(parent, titel, text, *a, **k):
        fragen.append(text)
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(kv_mod.QMessageBox, "question", nein)
    hybrid = FakeHybrid({"mietvertrag.pdf": "Max Mieter"})
    view = view_bauen(hybrid)
    view.refresh(abgleich=False)
    view.aufraeumen()
    assert len(fragen) == 1 and "3 Dokumente" in fragen[0] and "Kosten" in fragen[0] and "Fake-KI" in fragen[0]
    assert hybrid.aufrufe == [] and view._aufraeumen_thread is None

    monkeypatch.setattr(kv_mod.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    stand = _fertig(view, qtbot, view.aufraeumen)
    assert stand["gesamt"] == 3 and len(hybrid.aufrufe) == 3


def test_aufraeumen_abbrechen(umgebung, aufraeumen_umgebung, view_bauen, qtbot):
    weiter = threading.Event()
    hybrid = FakeHybrid({"mietvertrag.pdf": "Max Mieter", "arztbrief.pdf": "Erika Patientin"},
                        warten=lambda: weiter.wait(5))
    view = view_bauen(hybrid)
    view.refresh(abgleich=False)

    def starten_und_abbrechen():
        view.aufraeumen()
        assert not view.fortschritt_box.isHidden()
        qtbot.waitUntil(lambda: len(hybrid.aufrufe) == 1, timeout=5000)
        view.abbrechen_button.click()
        weiter.set()

    stand = _fertig(view, qtbot, starten_und_abbrechen)
    assert stand["abgebrochen"] is True
    assert len(hybrid.aufrufe) == 1
    assert "abgebrochen" in view.status_label.text()


def test_aufraeumen_ohne_auffaellige_meldet_nur(umgebung, view_bauen):
    umgebung.dok("Energie/strom.pdf", "Stadtwerke")
    hybrid = FakeHybrid()
    view = view_bauen(hybrid)
    view.refresh(abgleich=False)
    view.aufraeumen()
    assert hybrid.aufrufe == [] and view._aufraeumen_thread is None
    assert "Nichts aufzuräumen" in view.status_label.text()
