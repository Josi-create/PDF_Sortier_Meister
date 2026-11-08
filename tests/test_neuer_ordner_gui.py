"""Issue #116 im Hauptfenster: Neuer-Ordner-Kachel vorne, kein Regenbogen daran,
Klick legt an und verschiebt, Ablehnen legt nichts an, Rueckgaengig raeumt auf,
Schalter aus = altes Verhalten.

Fixtures aus tests/test_auto_next_after_move_gui.py (tmp-Config, Dialoge bestaetigt).
Ordner nur unter tmp_path, kein Netz/LLM (KI-Antworten liegen direkt im Cache).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtWidgets import QMessageBox

from src.core import neuer_ordner
from src.gui.folder_widget import REGENBOGEN_SCHWELLE
from src.ml.classifier import Suggestion
from tests.test_auto_next_after_move_gui import (  # noqa: F401 - Fixtures
    _make_scan_folder,
    _prime_cache,
    fresh_singletons,
    main_window,
)


def _ablage(main_window, tmp: Path, *folders) -> Path:
    ablage = tmp / "Ablage"
    for f in folders:
        (ablage / f).mkdir(parents=True, exist_ok=True)
    ablage.mkdir(exist_ok=True)
    main_window.config.add_target_folder(ablage)
    main_window.folder_manager.add_folder(ablage)
    main_window.load_folders()
    return ablage


def _bestehend(path: Path, rel: str, conf: float) -> Suggestion:
    return Suggestion(path, path.name, conf, "gelernt", relative_path=rel)


def _neu(path: Path, rel: str, quelle=neuer_ordner.QUELLE_JAHR) -> Suggestion:
    return Suggestion(path, path.name, 0.9, "neu", relative_path=rel, new_source=quelle)


def _select(main_window, scan: Path, name: str) -> Path:
    main_window._navigate_to_folder(scan)
    _prime_cache(main_window, [w.pdf_path for w in main_window.pdf_widgets])
    pdf = scan / name
    main_window.on_pdf_clicked(pdf)
    main_window.detail_panel.name_input.setText(name)  # Name bleibt, nur verschieben
    return pdf


def _ki_antwort(monkeypatch, main_window, antwort) -> None:
    """Gecachte KI-Antwort (statt eines echten LLM-Aufrufs)."""
    monkeypatch.setattr(main_window.pdf_cache, "get_llm_suggestions", lambda p: [antwort])


# --- Darstellung -----------------------------------------------------------------

def test_neuer_ordner_vorne_anders_und_ohne_regenbogen(main_window, fresh_singletons):
    tmp = fresh_singletons["tmp_path"]
    ablage = _ablage(main_window, tmp, "Steuer 2025/Medikamente")
    alt = ablage / "Steuer 2025" / "Medikamente"
    neu_pfad = ablage / "Steuer 2027" / "Medikamente"

    main_window.display_suggestions([
        _bestehend(alt, "Ablage/Steuer 2025/Medikamente", 0.95),
        _neu(neu_pfad, "Ablage/Steuer 2027/Medikamente"),
    ])

    widgets = main_window.suggestion_widgets
    assert widgets[0].folder_path == neu_pfad                      # Position 1
    assert widgets[0].neu and widgets[0].name_label.text().startswith("➕ neu:")
    assert "dashed" in widgets[0].styleSheet()
    assert not widgets[0].acceptDrops()                             # kein Drag & Drop
    assert not widgets[0].regenbogen                                # nie am neuen Ordner
    assert widgets[1].regenbogen                                    # erster bestehender >= 85 %
    assert not widgets[1].neu and "dashed" not in widgets[1].styleSheet()


def test_regenbogen_nur_wenn_erster_bestehender_ueber_schwelle(main_window, fresh_singletons):
    tmp = fresh_singletons["tmp_path"]
    ablage = _ablage(main_window, tmp, "A", "B")
    main_window.display_suggestions([
        _neu(ablage / "Neu", "Ablage/Neu"),
        _bestehend(ablage / "A", "Ablage/A", REGENBOGEN_SCHWELLE - 0.01),
        _bestehend(ablage / "B", "Ablage/B", 0.99),
    ])
    assert [w.regenbogen for w in main_window.suggestion_widgets] == [False, False, False]


def test_with_ki_folder_hoechstens_einer_jahresregel_vor_ki(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["a.pdf"])
    ablage = _ablage(main_window, tmp, "Steuer 2025/Medikamente", "Banken")
    pdf = _select(main_window, scan, "a.pdf")
    _ki_antwort(monkeypatch, main_window, SimpleNamespace(
        filename="x.pdf", confidence=0.9,
        metadata={"zielordner": "Ablage/Klaviernoten/Bach", "steuerjahr": "2027"},
    ))
    base = [
        _bestehend(ablage / "Banken", "Ablage/Banken", 0.3),
        _bestehend(ablage / "Steuer 2025" / "Medikamente", "Ablage/Steuer 2025/Medikamente", 0.8),
    ]

    out = main_window._with_ki_folder(pdf, base, "2027-02-01")

    neue = [s for s in out if neuer_ordner.ist_neu(s)]
    assert len(neue) == 1 and out[0] is neue[0]
    assert out[0].relative_path == "Ablage/Steuer 2027/Medikamente"   # A vor B

    # Ohne Jahresregel greift der KI-Pfad
    out = main_window._with_ki_folder(pdf, [base[0]], "2027-02-01")
    assert out[0].new_source == neuer_ordner.QUELLE_KI
    assert out[0].relative_path == "Ablage/Klaviernoten/Bach"


def test_schalter_aus_altes_verhalten(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["a.pdf"])
    ablage = _ablage(main_window, tmp, "Steuer 2025/Medikamente")
    pdf = _select(main_window, scan, "a.pdf")
    _ki_antwort(monkeypatch, main_window, SimpleNamespace(
        filename="x.pdf", confidence=0.9, metadata={"zielordner": "Ablage/Klaviernoten"},
    ))
    base = [_bestehend(ablage / "Steuer 2025" / "Medikamente", "Ablage/Steuer 2025/Medikamente", 0.8)]
    main_window.config.set("suggest_new_folders", False, auto_save=False)

    out = main_window._with_ki_folder(pdf, list(base), "2027-02-01")

    assert [s.folder_path for s in out] == [base[0].folder_path]
    assert not any(neuer_ordner.ist_neu(s) for s in out)


# --- Klick, Ablehnen, Rueckgaengig ------------------------------------------------

def _show_new(main_window, ablage: Path) -> Path:
    ziel = ablage / "Steuer 2027" / "Medikamente"
    main_window.display_suggestions([
        _neu(ziel, "Ablage/Steuer 2027/Medikamente"),
        _bestehend(ablage / "Steuer 2025" / "Medikamente", "Ablage/Steuer 2025/Medikamente", 0.9),
    ])
    return ziel


def test_klick_legt_an_verschiebt_und_rueckgaengig_raeumt_auf(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["a.pdf"])
    ablage = _ablage(main_window, tmp, "Steuer 2025/Medikamente")
    pdf = _select(main_window, scan, "a.pdf")
    ziel = _show_new(main_window, ablage)
    fragen = []
    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMessageBox, "question",
                        lambda *a, **k: fragen.append(a[2]) or QMessageBox.StandardButton.Yes)

    main_window.on_suggestion_clicked(ziel)

    assert fragen[0].startswith("Ordner 'Ablage")
    assert "Steuer 2027" in fragen[0] and "anlegen und Datei dorthin verschieben?" in fragen[0]
    assert (ziel / "a.pdf").exists() and not pdf.exists()
    entry = main_window._undo_stack[-1]
    assert entry["created_dirs"] == [ablage / "Steuer 2027", ziel]
    assert main_window.classifier._folder_cache_roots == []  # Cache invalidiert

    main_window.undo_last_action()

    assert pdf.exists()
    assert not (ablage / "Steuer 2027").exists()               # neue Ordner weg
    assert (ablage / "Steuer 2025" / "Medikamente").is_dir()   # vorhandene bleiben


def test_rueckgaengig_laesst_nicht_leere_neue_ordner_stehen(main_window, fresh_singletons):
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["a.pdf"])
    ablage = _ablage(main_window, tmp, "Steuer 2025/Medikamente")
    _select(main_window, scan, "a.pdf")
    ziel = _show_new(main_window, ablage)
    main_window.on_suggestion_clicked(ziel)
    (ziel / "fremd.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

    main_window.undo_last_action()

    assert (scan / "a.pdf").exists()
    assert (ziel / "fremd.pdf").exists() and ziel.is_dir()


def test_ablehnen_legt_nichts_an(main_window, fresh_singletons, monkeypatch):
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["a.pdf"])
    ablage = _ablage(main_window, tmp, "Steuer 2025/Medikamente")
    pdf = _select(main_window, scan, "a.pdf")
    ziel = _show_new(main_window, ablage)
    from src.gui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

    main_window.on_suggestion_clicked(ziel)

    assert pdf.exists()
    assert not (ablage / "Steuer 2027").exists()
    assert not main_window._undo_stack


def test_mehrfachauswahl_nutzt_neuen_ordner_nicht(main_window, fresh_singletons):
    tmp = fresh_singletons["tmp_path"]
    scan = _make_scan_folder(tmp, ["a.pdf", "b.pdf"])
    ablage = _ablage(main_window, tmp, "Steuer 2025/Medikamente")
    _select(main_window, scan, "a.pdf")
    ziel = _show_new(main_window, ablage)
    main_window.selected_pdfs = [scan / "a.pdf", scan / "b.pdf"]

    main_window.on_suggestion_clicked(ziel)

    assert not (ablage / "Steuer 2027").exists()
    assert (scan / "a.pdf").exists() and (scan / "b.pdf").exists()
