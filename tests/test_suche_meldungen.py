"""Schreibmeldungen der Oberflaeche an den Suchindex (Phase 5): Warteschlange und FileManager.

Verschieben und Umbenennen behalten Text und Metadaten, Loeschen entfernt den
Eintrag, Kopie/Teilen/Zusammenfuegen nehmen die neuen Dateien auf. Ohne Quelle
sind die Meldungen wirkungslos; Fehler im Index werfen nie in die Oberflaeche.
"""
from __future__ import annotations

from src.core.file_manager import FileManager
from src.search.indexer import Indexer
from src.search.meldungen import IndexMeldungen, melden, meldungen
from src.search.suchindex import Suchindex
from tests import helfer_suche as h


def test_filemanager_meldet_an_den_index(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    pdf = h.pdf_mit_text(ablage / "a.pdf", ["Mietvertrag Seite eins"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage), str(ziel)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    idx = Suchindex(konfig)
    assert idx.metadaten_setzen(str(pdf), {"kategorie": "Vertrag"}, pdf_id="p1")
    meldungen.konfigurieren(lambda: idx)
    fm = FileManager()

    neu = fm.rename_file(pdf, "b.pdf")
    assert meldungen.warten(10)
    assert idx.dokument_nach_pfad(str(pdf)) is None
    d = idx.dokument_nach_pfad(str(neu))
    assert d["textstatus"] == "text" and d["kategorie"] == "Vertrag" and d["pdf_id"] == "p1"

    verschoben = fm.move_file(neu, ziel)
    assert meldungen.warten(10)
    assert idx.dokument_nach_pfad(str(neu)) is None
    assert idx.dokument_nach_pfad(str(verschoben))["kategorie"] == "Vertrag"

    kopie = fm.copy_file(verschoben, ablage, "kopie.pdf")
    teile = fm.split_pdf(verschoben, ziel)
    zusammen = fm.merge_pdfs([verschoben, kopie], ziel, "zusammen.pdf")
    assert meldungen.warten(10)
    for p in (kopie, *teile, zusammen):
        assert idx.dokument_nach_pfad(str(p))["textstatus"] == "text", p

    fm.delete_file(kopie)
    assert meldungen.warten(10)
    assert idx.dokument_nach_pfad(str(kopie)) is None
    assert meldungen.fehler == 0 and idx.suche("Mietvertrag")["gesamt"] == 3


def test_stapeln_und_rueckgaengig_melden_inhalt_und_quellen(tmp_path):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    ziel = h.pdf_mit_text(ablage / "ziel.pdf", ["Ziel Seite"])
    quelle = h.pdf_mit_text(ablage / "quelle.pdf", ["Quelle Seite"])
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    idx = Suchindex(konfig)
    meldungen.konfigurieren(lambda: idx)
    fm = FileManager()

    sicherungen = fm.stack_pdfs(ziel, [quelle], tmp_path / "sicherung")
    assert meldungen.warten(10)
    assert idx.dokument_nach_pfad(str(quelle)) is None
    d = idx.dokument_nach_pfad(str(ziel))
    assert d["seiten"] == 2 and idx.suche("Quelle")["treffer"][0]["stellen"][0]["seite"] == 1  # Quelle liegt jetzt vorn

    fm.restore_stack(sicherungen)
    assert meldungen.warten(10)
    assert idx.dokument_nach_pfad(str(ziel))["seiten"] == 1
    assert idx.dokument_nach_pfad(str(quelle))["textstatus"] == "text"
    assert meldungen.fehler == 0


def test_ohne_quelle_wirkungslos_und_fehler_werfen_nicht(tmp_path):
    meldungen.konfigurieren(None)
    assert melden("datei_geloescht", str(tmp_path / "x.pdf")) is False

    class Kaputt:
        konfig = None

        def datei_geloescht(self, pfad):
            raise RuntimeError("Datenbank gesperrt")

    eigene = IndexMeldungen(lambda: Kaputt())
    assert eigene.melden("datei_geloescht", "x.pdf") is True
    assert eigene.warten(5)
    assert eigene.fehler == 1 and eigene.erledigt == 0
    try:
        eigene.melden("unbekannt", "x")
    except ValueError:
        pass
    else:
        raise AssertionError("unbekannte Meldung muss abgewiesen werden")

    # Ausserhalb der Wurzeln wird nichts aufgenommen, innerhalb schon
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    idx = Suchindex(konfig)
    drinnen = h.pdf_mit_text(ablage / "drinnen.pdf", ["drinnen"])
    draussen = h.pdf_mit_text(tmp_path / "draussen.pdf", ["draussen"])
    meldungen.konfigurieren(lambda: idx)
    melden("datei_aufnehmen", str(drinnen))
    melden("datei_aufnehmen", str(draussen))
    assert meldungen.warten(10)
    assert idx.dokument_nach_pfad(str(drinnen)) is not None
    assert idx.dokument_nach_pfad(str(draussen)) is None
