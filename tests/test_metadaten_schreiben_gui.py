"""Metadaten schreiben nach dem Verschieben (Live-Test 2026-11-08).

- Der Suchindex wird vor der Konsolenausgabe gemeldet: scheitert ``print`` am
  Zeichensatz der Konsole, fehlte sonst die Index-Meldung.
- Die Kategorie wird bereinigt, bevor sie in PDF und Index geht.
- Word/Excel-Dateien bekommen keinen pikepdf-Schreibversuch.
"""
from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

pikepdf = pytest.importorskip("pikepdf")


def _pdf(tmp_path):
    path = tmp_path / "2025-02-27_Brief_Jester.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(path)
    return path


def _fenster(gemeldet):
    return SimpleNamespace(_metadaten_an_index=lambda pfad, md: gemeldet.append((pfad, md.subject)))


def test_index_wird_vor_der_ausgabe_gemeldet(tmp_path, monkeypatch):
    from src.core.pdf_metadata import read_metadata
    from src.gui.main_window import MainWindow

    pdf = _pdf(tmp_path)
    gemeldet = []
    echt = builtins.print

    def konsole_cp1252(*args, **kwargs):
        if args and str(args[0]).startswith("Metadaten in"):
            raise UnicodeEncodeError("cp1252", "→", 0, 1, "character maps to <undefined>")
        echt(*args, **kwargs)

    monkeypatch.setattr(builtins, "print", konsole_cp1252)
    MainWindow._write_pdf_metadata(
        _fenster(gemeldet), pdf, pdf.name, ["rechnung"],
        {"subject": "{'Sonstiges'}", "korrespondent": "Jester GmbH & Co KG"},
    )

    assert gemeldet == [(pdf, "Sonstiges")]
    meta = read_metadata(pdf)
    assert meta.subject == "Sonstiges"
    assert meta.korrespondent == "Jester GmbH & Co KG"


def test_abgeschriebene_auswahlliste_wird_nicht_geschrieben(tmp_path):
    from src.gui.main_window import MainWindow

    pdf = _pdf(tmp_path)
    gemeldet = []
    MainWindow._write_pdf_metadata(
        _fenster(gemeldet), pdf, pdf.name, None,
        {"subject": "Rechnung/Vertrag/Steuer/Versicherung/Bank/Gehalt/Arzt/Energie/Sonstiges",
         "korrespondent": "Jester"},
    )
    assert gemeldet == [(pdf, None)]


@pytest.mark.parametrize("endung", [".docx", ".xlsx"])
def test_office_datei_bekommt_keine_pdf_metadaten(tmp_path, capsys, endung):
    from src.gui.main_window import MainWindow

    datei = tmp_path / f"Brief Jester{endung}"
    datei.write_bytes(b"PK\x03\x04 office")
    gemeldet = []
    MainWindow._write_pdf_metadata(_fenster(gemeldet), datei, datei.name, ["rechnung"], {"korrespondent": "Jester"})

    assert gemeldet == []
    assert datei.read_bytes() == b"PK\x03\x04 office"
    assert "Fehler" not in capsys.readouterr().out
