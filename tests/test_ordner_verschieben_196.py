"""Issue #196: ganzen Ordner verschieben/kopieren (Kernlogik, ohne GUI)."""
from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

import pytest

from src.core import ordner_verschieben as ov
from src.core.file_manager import FileManager


def _datei(pfad: Path, inhalt: bytes = b"x") -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    return pfad


class Papierkorb:
    """Ersatz fuer FileManager.delete_file: legt Dateien in einen Testordner."""

    def __init__(self, ordner: Path):
        self.ordner = ordner
        self.ordner.mkdir(exist_ok=True)
        self.n = 0
        self.dateien: list[Path] = []

    def __call__(self, pfad: Path) -> Path:
        self.n += 1
        ziel = self.ordner / f"{self.n}_{Path(pfad).name}"
        shutil.move(str(pfad), str(ziel))
        self.dateien.append(ziel)
        return ziel


@pytest.fixture
def papierkorb(tmp_path):
    return Papierkorb(tmp_path / "_korb")


def test_verschiebt_ordner_mit_unterordnern_und_allen_dateitypen(tmp_path, papierkorb):
    quelle = tmp_path / "Eingang" / "Versicherungen"
    _datei(quelle / "a.pdf", b"a")
    _datei(quelle / "Brief.docx", b"b")
    _datei(quelle / "Foto.jpg", b"c")
    _datei(quelle / "Kfz" / "Police.pdf", b"d")
    _datei(quelle / "Kfz" / "tief" / "notiz.txt", b"e")
    (quelle / "leer").mkdir()
    ziel_eltern = tmp_path / "Steuer 2025"
    ziel_eltern.mkdir()

    erg = ov.uebertrage(quelle, ziel_eltern, papierkorb=papierkorb)

    ziel = ziel_eltern / "Versicherungen"
    assert erg.ziel == ziel
    assert not quelle.exists()  # Quellordner samt Unterordnern weggeraeumt
    assert (ziel / "a.pdf").read_bytes() == b"a"
    assert (ziel / "Brief.docx").exists() and (ziel / "Foto.jpg").exists()
    assert (ziel / "Kfz" / "tief" / "notiz.txt").read_bytes() == b"e"
    assert (ziel / "leer").is_dir()
    assert len(erg.dateien) == 5 and not erg.fehler
    assert (tmp_path / "Eingang").is_dir()  # der Elternordner bleibt


def test_zusammenfuehren_gleicher_name_bekommt_2(tmp_path, papierkorb):
    quelle = tmp_path / "Eingang" / "Versicherungen"
    _datei(quelle / "Police.pdf", b"neu")
    ziel = tmp_path / "Steuer 2025" / "Versicherungen"
    _datei(ziel / "Police.pdf", b"alt")
    _datei(ziel / "Police (2).pdf", b"auch alt")

    erg = ov.uebertrage(quelle, tmp_path / "Steuer 2025", papierkorb=papierkorb)

    assert (ziel / "Police.pdf").read_bytes() == b"alt"  # Vorhandenes bleibt
    assert (ziel / "Police (2).pdf").read_bytes() == b"auch alt"
    assert (ziel / "Police (3).pdf").read_bytes() == b"neu"  # naechste freie Nummer
    assert erg.dateien == [(quelle / "Police.pdf", ziel / "Police (3).pdf")]
    assert not quelle.exists()


def test_erste_freie_nummer_ist_2(tmp_path, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "x.pdf", b"neu")
    _datei(tmp_path / "Z" / "Ordner" / "x.pdf", b"alt")
    ov.uebertrage(quelle, tmp_path / "Z", papierkorb=papierkorb)
    assert (tmp_path / "Z" / "Ordner" / "x (2).pdf").read_bytes() == b"neu"


def test_identische_datei_wird_in_den_papierkorb_gelegt(tmp_path, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "gleich.pdf", b"inhalt")
    _datei(quelle / "anders.pdf", b"neu")
    ziel = tmp_path / "Z" / "Ordner"
    _datei(ziel / "gleich.pdf", b"inhalt")
    _datei(ziel / "anders.pdf", b"alt")

    erg = ov.uebertrage(quelle, tmp_path / "Z", papierkorb=papierkorb)

    assert len(papierkorb.dateien) == 1 and papierkorb.dateien[0].read_bytes() == b"inhalt"
    assert not (ziel / "gleich (2).pdf").exists()  # kein Doppelgaenger
    assert (ziel / "anders (2).pdf").read_bytes() == b"neu"
    assert erg.identisch == [(quelle / "gleich.pdf", ziel / "gleich.pdf", papierkorb.dateien[0])]
    assert not quelle.exists()


def test_gleiche_groesse_aber_anderer_inhalt_ist_nicht_identisch(tmp_path, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "f.pdf", b"AAAA")
    _datei(tmp_path / "Z" / "Ordner" / "f.pdf", b"BBBB")
    erg = ov.uebertrage(quelle, tmp_path / "Z", papierkorb=papierkorb)
    assert not erg.identisch and not papierkorb.dateien
    assert (tmp_path / "Z" / "Ordner" / "f (2).pdf").read_bytes() == b"AAAA"


def test_kopieren_laesst_die_quelle_und_ueberspringt_identische(tmp_path, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "gleich.pdf", b"inhalt")
    _datei(quelle / "neu.pdf", b"neu")
    ziel = tmp_path / "Z" / "Ordner"
    _datei(ziel / "gleich.pdf", b"inhalt")

    erg = ov.uebertrage(quelle, tmp_path / "Z", kopieren=True, papierkorb=papierkorb)

    assert (quelle / "gleich.pdf").exists() and (quelle / "neu.pdf").exists()  # Original unveraendert
    assert (ziel / "neu.pdf").read_bytes() == b"neu"
    assert not papierkorb.dateien  # beim Kopieren wird nichts geloescht
    assert [n.name for _a, n in erg.dateien] == ["neu.pdf"]
    assert len(erg.identisch) == 1 and erg.identisch[0][2] is None
    assert not erg.entfernte_quellordner


def test_sperre_gegen_sich_selbst_und_unterordner(tmp_path):
    quelle = tmp_path / "A" / "Ordner"
    (quelle / "Unter" / "Tiefer").mkdir(parents=True)
    assert ov.pruefe(quelle, quelle) is not None
    assert ov.pruefe(quelle, quelle / "Unter") is not None
    assert ov.pruefe(quelle, quelle / "Unter" / "Tiefer") is not None
    with pytest.raises(ov.OrdnerFehler):
        ov.uebertrage(quelle, quelle / "Unter")
    assert (quelle / "Unter" / "Tiefer").is_dir()  # nichts angefasst
    # Aehnlicher Name ist KEIN Unterordner
    (tmp_path / "A" / "Ordner 2").mkdir()
    assert ov.pruefe(quelle, tmp_path / "A" / "Ordner 2") is None


def test_sperre_dorthin_wo_er_schon_liegt_und_dateien(tmp_path):
    quelle = tmp_path / "A" / "Ordner"
    quelle.mkdir(parents=True)
    assert "liegt schon" in ov.pruefe(quelle, quelle.parent)
    datei = _datei(tmp_path / "f.pdf")
    assert ov.pruefe(datei, tmp_path) is not None
    assert ov.pruefe(quelle, datei) is not None


def test_zielordner_wird_samt_eltern_angelegt(tmp_path, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "x.pdf")
    ziel_eltern = tmp_path / "Neu 2026" / "Unter"
    erg = ov.uebertrage(quelle, ziel_eltern, papierkorb=papierkorb)
    assert (ziel_eltern / "Ordner" / "x.pdf").exists()
    assert erg.neue_ordner[:2] == [tmp_path / "Neu 2026", ziel_eltern]  # aussen zuerst


def test_laufwerksgrenze_faellt_auf_kopieren_und_loeschen_zurueck(tmp_path, monkeypatch, papierkorb):
    """os.rename scheitert wie ueber Laufwerke (EXDEV): shutil.move kopiert und loescht."""
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "a.pdf", b"a")
    _datei(quelle / "Sub" / "b.pdf", b"b")

    def kein_rename(src, dst, *a, **k):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(shutil.os, "rename", kein_rename)
    erg = ov.uebertrage(quelle, tmp_path / "Z", papierkorb=papierkorb)

    assert (tmp_path / "Z" / "Ordner" / "a.pdf").read_bytes() == b"a"
    assert (tmp_path / "Z" / "Ordner" / "Sub" / "b.pdf").read_bytes() == b"b"
    assert not quelle.exists() and not erg.fehler


def test_dateisperre_wird_wiederholt(tmp_path, monkeypatch, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "a.pdf", b"a")
    echt = shutil.move
    versuche = []

    def zickig(src, dst, *a, **k):
        versuche.append(src)
        if len(versuche) < 3:
            raise PermissionError(13, "Zugriff verweigert")
        return echt(src, dst, *a, **k)

    monkeypatch.setattr(FileManager, "MOVE_RETRY_DELAYS", (0, 0, 0))
    monkeypatch.setattr(shutil, "move", zickig)
    erg = ov.uebertrage(quelle, tmp_path / "Z", papierkorb=papierkorb)
    assert len(versuche) == 3 and not erg.fehler
    assert (tmp_path / "Z" / "Ordner" / "a.pdf").exists()


def test_einzelne_fehler_stoppen_den_rest_nicht(tmp_path, monkeypatch, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "a.pdf")
    _datei(quelle / "b.pdf")
    echt = FileManager._move_with_retry.__func__

    def mal_kaputt(cls, src, dst):
        if Path(src).name == "a.pdf":
            raise PermissionError(13, "gesperrt")
        return echt(cls, src, dst)

    monkeypatch.setattr(FileManager, "_move_with_retry", classmethod(mal_kaputt))
    erg = ov.uebertrage(quelle, tmp_path / "Z", papierkorb=papierkorb)
    assert len(erg.fehler) == 1 and "a.pdf" in erg.fehler[0]
    assert (quelle / "a.pdf").exists()  # bleibt am alten Platz, Quellordner bleibt
    assert (tmp_path / "Z" / "Ordner" / "b.pdf").exists()
    assert quelle.exists() and not erg.entfernte_quellordner


def test_fortschritt_und_abbruch(tmp_path, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    for i in range(5):
        _datei(quelle / f"{i}.pdf")
    stand = []
    erg = ov.uebertrage(
        quelle, tmp_path / "Z", papierkorb=papierkorb,
        fortschritt=lambda i, n, name: stand.append((i, n)),
        abbruch=lambda: len(stand) >= 2,
    )
    assert stand == [(1, 5), (2, 5)]
    assert erg.abgebrochen and len(erg.dateien) == 2
    assert quelle.exists() and len(list(quelle.glob("*.pdf"))) == 3


def test_rueckgaengig_verschieben_stellt_alles_wieder_her(tmp_path, papierkorb):
    quelle = tmp_path / "Eingang" / "Versicherungen"
    _datei(quelle / "a.pdf", b"a")
    _datei(quelle / "Kfz" / "p.pdf", b"p")
    (quelle / "leer").mkdir()
    erg = ov.uebertrage(quelle, tmp_path / "Neu" / "Steuer", papierkorb=papierkorb)

    probleme = ov.rueckgaengig(erg, papierkorb)

    assert probleme == []
    assert (quelle / "a.pdf").read_bytes() == b"a"
    assert (quelle / "Kfz" / "p.pdf").read_bytes() == b"p"
    assert (quelle / "leer").is_dir()
    assert not (tmp_path / "Neu").exists()  # neu angelegte, jetzt leere Ordner weg


def test_rueckgaengig_beim_zusammenfuehren_holt_identische_aus_dem_papierkorb(tmp_path, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "gleich.pdf", b"inhalt")
    _datei(quelle / "neu.pdf", b"neu")
    _datei(quelle / "konflikt.pdf", b"quelle")
    ziel = tmp_path / "Z" / "Ordner"
    _datei(ziel / "gleich.pdf", b"inhalt")
    _datei(ziel / "konflikt.pdf", b"ziel")
    _datei(ziel / "bleibt.pdf", b"bleibt")
    erg = ov.uebertrage(quelle, tmp_path / "Z", papierkorb=papierkorb)

    probleme = ov.rueckgaengig(erg, papierkorb)

    assert probleme == []
    assert (quelle / "gleich.pdf").read_bytes() == b"inhalt"  # aus dem Papierkorb zurueck
    assert (quelle / "neu.pdf").read_bytes() == b"neu"
    assert (quelle / "konflikt.pdf").read_bytes() == b"quelle"
    # Vorhandenes im Ziel bleibt unberuehrt
    assert sorted(p.name for p in ziel.iterdir()) == ["bleibt.pdf", "gleich.pdf", "konflikt.pdf"]
    assert (ziel / "konflikt.pdf").read_bytes() == b"ziel"


def test_rueckgaengig_kopieren_legt_nur_die_kopien_in_den_papierkorb(tmp_path, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "a.pdf", b"a")
    _datei(quelle / "Sub" / "b.pdf", b"b")
    ziel = tmp_path / "Z" / "Ordner"
    _datei(ziel / "vorher.pdf", b"v")
    erg = ov.uebertrage(quelle, tmp_path / "Z", kopieren=True, papierkorb=papierkorb)
    assert (ziel / "Sub" / "b.pdf").exists()

    probleme = ov.rueckgaengig(erg, papierkorb)

    assert probleme == []
    assert len(papierkorb.dateien) == 2  # beide Kopien im Papierkorb
    assert (ziel / "vorher.pdf").exists() and not (ziel / "a.pdf").exists()
    assert not (ziel / "Sub").exists()  # neu angelegt und leer
    assert (quelle / "a.pdf").exists() and (quelle / "Sub" / "b.pdf").exists()


def test_rueckgaengig_meldet_fehlende_dateien(tmp_path, papierkorb):
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "a.pdf")
    erg = ov.uebertrage(quelle, tmp_path / "Z", papierkorb=papierkorb)
    (tmp_path / "Z" / "Ordner" / "a.pdf").unlink()
    probleme = ov.rueckgaengig(erg, papierkorb)
    assert len(probleme) == 1 and "a.pdf" in probleme[0]


def test_index_meldungen_je_datei(tmp_path, monkeypatch, papierkorb):
    gemeldet = []
    monkeypatch.setattr(ov, "index_melden", lambda *a, **k: gemeldet.append(a))
    quelle = tmp_path / "Q" / "Ordner"
    _datei(quelle / "a.pdf")
    ov.uebertrage(quelle, tmp_path / "Z", papierkorb=papierkorb)
    assert gemeldet == [("datei_verschoben", str(quelle / "a.pdf"), str(tmp_path / "Z" / "Ordner" / "a.pdf"))]
    gemeldet.clear()
    q2 = tmp_path / "Q2" / "Ordner"
    _datei(q2 / "b.pdf")
    ov.uebertrage(q2, tmp_path / "Z2", kopieren=True, papierkorb=papierkorb)
    assert gemeldet == [("datei_aufnehmen", str(tmp_path / "Z2" / "Ordner" / "b.pdf"))]
