"""Handbuch im Programm (Issue #365)."""

from pathlib import Path

import pytest

from src.gui.handbuch import (
    HANDBUCH_WURZEL,
    HandbuchDialog,
    handbuch_ordner,
    kapitel_liste,
    kapitel_titel,
)


def test_handbuch_gibt_es_in_beiden_sprachen_mit_gleichen_kapiteln():
    de = sorted(p.name for p in (HANDBUCH_WURZEL / "de").glob("*.md"))
    en = sorted(p.name for p in (HANDBUCH_WURZEL / "en").glob("*.md"))
    assert de, "kein deutsches Handbuch"
    assert de == en


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_jedes_kapitel_hat_eine_ueberschrift_und_gleich_viele_abschnitte(sprache):
    for datei in (HANDBUCH_WURZEL / sprache).glob("*.md"):
        text = datei.read_text(encoding="utf-8")
        assert text.startswith("# "), datei
        gegenstueck = HANDBUCH_WURZEL / ("en" if sprache == "de" else "de") / datei.name
        anzahl = text.count("\n## ")
        assert anzahl == gegenstueck.read_text(encoding="utf-8").count("\n## "), datei.name


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_links_zwischen_kapiteln_zeigen_auf_vorhandene_dateien(sprache):
    import re

    ordner = HANDBUCH_WURZEL / sprache
    for datei in ordner.glob("*.md"):
        for ziel in re.findall(r"\]\(([^)#:]+\.md)\)", datei.read_text(encoding="utf-8")):
            assert (ordner / ziel).is_file(), f"{datei.name}: {ziel}"


def test_paperport_max_hinweis_steht_in_beiden_sprachen():
    for sprache in ("de", "en"):
        texte = " ".join(p.read_text(encoding="utf-8") for p in (HANDBUCH_WURZEL / sprache).glob("*.md"))
        assert "`.max`" in texte
        assert "PaperPort" in texte


def test_handbuch_ordner_faellt_auf_deutsch_zurueck(tmp_path):
    (tmp_path / "de").mkdir()
    (tmp_path / "de" / "01-a.md").write_text("# Ä\n", encoding="utf-8")
    assert handbuch_ordner("en", tmp_path) == tmp_path / "de"
    assert handbuch_ordner("de", tmp_path) == tmp_path / "de"
    assert kapitel_titel(tmp_path / "de" / "01-a.md") == "Ä"
    assert kapitel_titel(tmp_path / "fehlt.md") == "fehlt"
    assert kapitel_liste(tmp_path / "gibtsnicht") == []


def _handbuch(tmp_path: Path) -> Path:
    ordner = tmp_path / "Handbüch" / "de"
    ordner.mkdir(parents=True)
    (ordner / "01-eins.md").write_text("# Eins\n\nHallo Welt. [Weiter](02-zwei.md)\n", encoding="utf-8")
    (ordner / "02-zwei.md").write_text("# Zwei\n\nHier steht der Kaffee.\n", encoding="utf-8")
    return ordner


def test_dialog_zeigt_kapitel_und_sucht_ueber_kapitel_hinweg(qtbot, tmp_path):
    dialog = HandbuchDialog(ordner=_handbuch(tmp_path))
    qtbot.addWidget(dialog)
    assert [dialog.liste.item(i).text() for i in range(dialog.liste.count())] == ["Eins", "Zwei"]
    assert dialog.aktuelle_zeile() == 0
    assert "Hallo Welt" in dialog.text.toPlainText()

    dialog.suchfeld.setText("Kaffee")
    assert dialog.weitersuchen() is True
    assert dialog.aktuelle_zeile() == 1
    assert dialog.text.textCursor().selectedText() == "Kaffee"

    dialog.suchfeld.setText("gibt es nicht")
    assert dialog.weitersuchen() is False
    assert dialog.suchhinweis.text()


def test_link_auf_anderes_kapitel_zieht_die_liste_nach(qtbot, tmp_path):
    ordner = _handbuch(tmp_path)
    dialog = HandbuchDialog(ordner=ordner)
    qtbot.addWidget(dialog)
    from PyQt6.QtCore import QUrl

    dialog.text.setSource(QUrl.fromLocalFile(str(ordner / "02-zwei.md")))
    assert dialog.aktuelle_zeile() == 1
    assert "Kaffee" in dialog.text.toPlainText()


def test_dialog_ohne_handbuch(qtbot, tmp_path):
    dialog = HandbuchDialog(ordner=tmp_path / "leer")
    qtbot.addWidget(dialog)
    assert dialog.liste.count() == 0
    assert not dialog.suchfeld.isEnabled()
    assert dialog.weitersuchen() is False
