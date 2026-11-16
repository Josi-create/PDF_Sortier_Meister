"""Issue #294: "PDFs zusammenfügen" zuoberst im Rechtsklick-Menü der Kachel."""
from pathlib import Path

from tests.test_pdf_drehen_150_gui import _texte, thumbnail  # noqa: F401 - Fixture


def _auswahl(monkeypatch, thumbnail, pfade):  # noqa: F811
    class _Fenster:
        selected_pdfs = [Path(p) for p in pfade]

    monkeypatch.setattr(thumbnail, "window", lambda: _Fenster())


def test_zwei_pdfs_markiert_zusammenfuegen_steht_zuoberst(thumbnail, monkeypatch):  # noqa: F811
    _auswahl(monkeypatch, thumbnail, ["a.pdf", "b.pdf"])
    texte = _texte(thumbnail._build_context_menu())
    assert texte[0] == "PDFs zusammenfügen (2)…"
    assert texte[1] == "PDF öffnen"
    # nur einmal im Menue, der alte Eintrag weiter unten ist weg
    assert sum("zusammenfügen" in t for t in texte) == 1


def test_eintrag_sendet_signal(thumbnail, monkeypatch):  # noqa: F811
    _auswahl(monkeypatch, thumbnail, ["a.pdf", "b.PDF", "c.pdf"])
    empfangen = []
    thumbnail.merge_requested.connect(lambda: empfangen.append(True))
    menu = thumbnail._build_context_menu()
    next(a for a in menu.actions() if a.text() == "PDFs zusammenfügen (3)…").trigger()
    assert empfangen == [True]


def test_bilder_und_office_zaehlen_nicht_mit(thumbnail, monkeypatch):  # noqa: F811
    _auswahl(monkeypatch, thumbnail, ["a.pdf", "Foto.jpg", "Brief.docx", "b.pdf"])
    assert _texte(thumbnail._build_context_menu())[0] == "PDFs zusammenfügen (2)…"


def test_ohne_zwei_pdfs_kein_eintrag(thumbnail, monkeypatch):  # noqa: F811
    for pfade in ([], ["a.pdf"], ["a.pdf", "Foto.jpg"]):
        _auswahl(monkeypatch, thumbnail, pfade)
        texte = _texte(thumbnail._build_context_menu())
        assert not any("zusammenfügen" in t for t in texte), pfade
        assert texte[0] == "PDF öffnen"


def test_englische_uebersetzung_vorhanden():
    po = (Path(__file__).resolve().parents[1] / "src" / "i18n" / "locale" / "en.po").read_text(encoding="utf-8")
    assert 'msgid "PDFs zusammenfügen ({anzahl})…"\nmsgstr "Merge PDFs ({anzahl})…"' in po
