"""Issue #47, Teil 2: schwer lesbare Scans markieren und andere Erkennung anbieten.

* Mass fuer "schlecht erkannt" (``extract.schlecht_erkannt``, Anteil sicher erkannter Zeichen)
  und seine Ablage (Analyse, Suchindex, PDF-Cache)
* Warndreieck auf der Kachel, Sprachliste im Kontextmenue
* "OCR wiederholen mit ...": nur Besseres wird uebernommen
* "Handschrift mit KI entziffern": Bildeingabe der Provider, Fake-Provider im Ablauf,
  Hilfedialog ohne Vision-Modell

Kein echtes Netz, kein echtes Tesseract, kein echtes LLM; Konfiguration und Index liegen in ``tmp_path``.
"""
from __future__ import annotations

import base64
import sqlite3
import subprocess
from pathlib import Path

import pytest

from src.core.pdf_analyzer import PDFAnalyzer, ocr_schlecht, ocr_wiederholen
from src.search import extract
from src.search.suchindex import Suchindex
from tests import helfer_suche as h
from tests.test_main_window_gui import fresh_singletons, main_window  # noqa: F401 - Fixtures

GUT = "Rechnung Nummer 4711 Gesamtbetrag 1181 Euro Stadtwerke"
SCHLECHT = "Rxchn Nmmr 47l1 Gsmtbtrg ll81 Eur Stdtwrk Zxqpt Vbnmk"


def fake_sprachen(monkeypatch, nach_sprache: dict | None = None, standard=(SCHLECHT, 30)) -> list:
    """Tesseract-Attrappe: Text und Konfidenz hängen von ``-l`` ab. Liefert die gesehenen Sprachen."""
    gesehen: list = []

    def run(args, **kw):
        sprachen = args[args.index("-l") + 1]
        gesehen.append(sprachen)
        text, konf = (nach_sprache or {}).get(sprachen, standard)
        tsv = h._lage_tsv(text.split(), konf, senkrecht=False)
        out = (tsv if "tessedit_create_tsv=1" in args else "") + text
        return subprocess.CompletedProcess(args, 0, stdout=out.encode("utf-8"), stderr=b"")

    monkeypatch.setattr(extract.subprocess, "run", run)
    return gesehen


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    ablage = tmp_path / "Ablage"
    ablage.mkdir()
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], ocr_aktiv=True, ocr_tesseract="tesseract-fake")
    idx = Suchindex(konfig)
    monkeypatch.setattr("src.core.pdf_analyzer.suchindex_fuer_analyse", lambda: idx)
    monkeypatch.setattr("src.core.pdf_analyzer._search_konfig", lambda: konfig)
    return ablage, konfig, idx


def _ratio(wert):
    return wert[1] / wert[0]


# --------------------------------------------------------------------------- Mass und Schwelle

def test_schwelle_fuer_schlecht_erkannt():
    assert extract.LESBAR_SCHWELLE == 0.6
    assert extract.schlecht_erkannt(100, 59) and extract.schlecht_erkannt(100, 0)
    assert not extract.schlecht_erkannt(100, 60) and not extract.schlecht_erkannt(100, 100)
    assert not extract.schlecht_erkannt(10, 0)       # zu wenig Schrift (leere Seite, Stempel)
    assert not extract.schlecht_erkannt(0, 0)
    assert ocr_schlecht((100, 10)) and not ocr_schlecht((100, 90)) and not ocr_schlecht(None)


def test_pdf_ocr_liefert_lesbarkeit_der_gewaehlten_lage(tmp_path, monkeypatch):
    fake_sprachen(monkeypatch, {"deu": (GUT, 95)})
    scan = h.pdf_mit_bild(tmp_path / "scan.pdf", seiten=2)
    cfg = {"tesseract": "t", "tessdata": None, "sprachen": "deu", "dpi": 72, "min_zeichen": 25, "lage_pruefen": True}
    erg = extract.pdf_ocr(str(scan), [1, 2], cfg)
    assert erg["lesbarkeit"][1] == erg["lesbarkeit"][2] and _ratio(erg["lesbarkeit"][1]) == 1
    cfg["sprachen"] = "deu+eng"
    erg = extract.pdf_ocr(str(scan), [1], cfg)
    assert erg["lesbarkeit"][1][1] == 0 and erg["lesbarkeit"][1][0] > 25
    # ohne Lagepruefung gibt es keine TSV und damit keine Lesbarkeit
    cfg["lage_pruefen"] = False
    assert extract.pdf_ocr(str(scan), [1], cfg)["lesbarkeit"] == {}


def test_ocr_kandidaten_sind_bildseiten_ohne_eigenen_text(tmp_path):
    pdf = h.pdf_mit_bild(tmp_path / "gemischt.pdf", seiten=2, text_seiten=["Ein langer Text auf Seite eins"])
    assert extract.ocr_kandidaten(str(pdf), 5) == [2, 3]


# --------------------------------------------------------------------------- Analyse und Index

def test_analyse_merkt_schlechte_erkennung_im_index(umgebung, monkeypatch):
    ablage, konfig, idx = umgebung
    aufrufe = fake_sprachen(monkeypatch)
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=1)
    with PDFAnalyzer(scan) as a:
        a.extract_text()
    assert a.ocr_lesbarkeit is not None and ocr_schlecht(a.ocr_lesbarkeit)
    assert idx.ocr_lesbarkeit(str(scan)) == a.ocr_lesbarkeit
    # Zweite Analyse: alles aus dem Index, auch die Lesbarkeit - ohne neue OCR
    n = len(aufrufe)
    with PDFAnalyzer(scan) as b:
        b.extract_text()
    assert len(aufrufe) == n and b.ocr_lesbarkeit == a.ocr_lesbarkeit and not b.ocr_used


def test_analyse_gut_erkannter_scan_ist_nicht_markiert(umgebung, monkeypatch):
    ablage, konfig, idx = umgebung
    fake_sprachen(monkeypatch, standard=(GUT, 95))
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=1)
    with PDFAnalyzer(scan) as a:
        a.extract_text()
    assert a.ocr_lesbarkeit is not None and not ocr_schlecht(a.ocr_lesbarkeit)


def test_analyse_ohne_index_behaelt_die_lesbarkeit_des_laufs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.pdf_analyzer.suchindex_fuer_analyse", lambda: None)
    monkeypatch.setattr("src.core.pdf_analyzer.ocr_einstellungen_fuer_analyse",
                        lambda: {"tesseract": "t", "tessdata": None, "sprachen": "deu+eng", "dpi": 72,
                                 "min_zeichen": 25, "lage_pruefen": True})
    fake_sprachen(monkeypatch)
    scan = h.pdf_mit_bild(tmp_path / "scan.pdf", seiten=1)
    with PDFAnalyzer(scan) as a:
        a.extract_text()
    assert ocr_schlecht(a.ocr_lesbarkeit)


def test_text_pdf_hat_keine_lesbarkeit(umgebung):
    ablage, konfig, idx = umgebung
    pdf = h.pdf_mit_text(ablage / "text.pdf", ["Rechnung mit eigener Textebene"])
    with PDFAnalyzer(pdf) as a:
        a.extract_text()
    assert a.ocr_lesbarkeit is None and not ocr_schlecht(a.ocr_lesbarkeit)


# --------------------------------------------------------------------------- OCR wiederholen

def test_ocr_wiederholen_uebernimmt_besseres(umgebung, monkeypatch):
    ablage, konfig, idx = umgebung
    gesehen = fake_sprachen(monkeypatch, {"deu_frak": (GUT, 95)})
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=1)
    with PDFAnalyzer(scan) as a:
        a.extract_text()
    assert ocr_schlecht(idx.ocr_lesbarkeit(str(scan)))

    erg = ocr_wiederholen(scan, "deu_frak")
    assert erg["fehler"] is None and erg["besser"] and erg["seiten"] == 1
    assert _ratio(erg["nachher"]) == 1 and _ratio(erg["vorher"]) == 0
    assert "deu_frak" in gesehen
    assert not ocr_schlecht(idx.ocr_lesbarkeit(str(scan)))
    # Text und Cache sind ersetzt: eine neue Analyse und eine Kopie sehen den besseren Text
    with PDFAnalyzer(scan) as a:
        assert "Rechnung Nummer 4711" in a.extract_text() and "Rxchn" not in a.extract_text()
        assert not a.ocr_used and not ocr_schlecht(a.ocr_lesbarkeit)
    import shutil
    shutil.copy2(scan, ablage / "kopie.pdf")
    with PDFAnalyzer(ablage / "kopie.pdf") as a:
        assert "Rechnung Nummer 4711" in a.extract_text() and not a.ocr_used


def test_ocr_wiederholen_uebernimmt_nichts_schlechteres(umgebung, monkeypatch):
    ablage, konfig, idx = umgebung
    fake_sprachen(monkeypatch, {"deu+eng": (GUT, 95), "fra": (SCHLECHT, 20)})
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=1)
    with PDFAnalyzer(scan) as a:
        text = a.extract_text()
    vorher = idx.ocr_lesbarkeit(str(scan))
    assert "Rechnung Nummer 4711" in text and not ocr_schlecht(vorher)

    erg = ocr_wiederholen(scan, "fra")
    assert erg["fehler"] is None and not erg["besser"] and erg["seiten"] == 0
    assert idx.ocr_lesbarkeit(str(scan)) == vorher
    with PDFAnalyzer(scan) as a:
        assert "Rechnung Nummer 4711" in a.extract_text() and "Rxchn" not in a.extract_text()


def test_ocr_wiederholen_ohne_bisherige_messung_vergleicht_mit_standardsprachen(umgebung, monkeypatch):
    ablage, konfig, idx = umgebung
    gesehen = fake_sprachen(monkeypatch, {"deu_frak": (GUT, 95)})
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=1)
    with PDFAnalyzer(scan) as a:
        a.extract_text()
    con = sqlite3.connect(konfig.db_pfad)   # Erkennung aus der Zeit vor Issue #47: keine Lesbarkeit gespeichert
    con.execute("UPDATE dokumente SET ocr_lesbar_alle = NULL, ocr_lesbar_gut = NULL")
    con.commit()
    con.close()
    assert idx.ocr_lesbarkeit(str(scan)) is None
    gesehen.clear()
    erg = ocr_wiederholen(scan, "deu_frak")
    assert erg["besser"] and _ratio(erg["vorher"]) == 0 and "deu+eng" in gesehen  # Vergleichslauf


def test_ocr_wiederholen_meldet_fehlende_sprachdaten_und_fehlenden_index(umgebung, tmp_path, monkeypatch):
    ablage, konfig, idx = umgebung
    fake_sprachen(monkeypatch)
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=1)
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "deu.traineddata").write_bytes(b"x")
    (tessdata / "eng.traineddata").write_bytes(b"x")
    monkeypatch.setattr(type(konfig), "ocr_einstellungen",
                        lambda self: {"tesseract": "t", "tessdata": str(tessdata), "sprachen": "deu+eng", "dpi": 72,
                                      "min_zeichen": 25, "lage_pruefen": True})
    erg = ocr_wiederholen(scan, "deu_frak")
    assert not erg["besser"] and "deu_frak" in erg["fehler"]

    monkeypatch.setattr("src.core.pdf_analyzer.suchindex_fuer_analyse", lambda: None)
    assert ocr_wiederholen(scan, "deu")["index"] is False


def test_ocr_wiederholen_bricht_ab_und_speichert_nichts(umgebung, monkeypatch):
    ablage, konfig, idx = umgebung
    fake_sprachen(monkeypatch, {"deu_frak": (GUT, 95)})
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=1)
    with PDFAnalyzer(scan) as a:
        a.extract_text()
    erg = ocr_wiederholen(scan, "deu_frak", abbrechen=lambda: True)
    assert not erg["besser"]
    assert ocr_schlecht(idx.ocr_lesbarkeit(str(scan)))


# --------------------------------------------------------------------------- Sprachliste

def _list_langs(monkeypatch, ausgabe: str, rc: int = 0):
    from src.utils import tesseract as t

    aufrufe = []

    def run(args, **kw):
        aufrufe.append(list(args))
        return subprocess.CompletedProcess(args, rc, stdout=ausgabe.encode(), stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    return aufrufe, t


def test_installierte_sprachen_aus_list_langs(monkeypatch):
    aufrufe, t = _list_langs(monkeypatch,
                             'List of available languages in "C:/tessdata" (5):\ndeu\neng\ndeu_frak\nosd\nfra\n')
    assert t.installierte_sprachen("tesseract-fake", "C:/tessdata") == ["deu", "eng", "deu_frak", "fra"]
    assert aufrufe[0][:2] == ["tesseract-fake", "--list-langs"] and "--tessdata-dir" in aufrufe[0]


def test_installierte_sprachen_ersatzweise_aus_dem_ordner(monkeypatch, tmp_path):
    _aufrufe, t = _list_langs(monkeypatch, "", rc=1)
    (tmp_path / "deu.traineddata").write_bytes(b"x")
    (tmp_path / "osd.traineddata").write_bytes(b"x")
    assert t.installierte_sprachen("tesseract-fake", str(tmp_path)) == ["deu"]
    assert t.installierte_sprachen(None, None) == []


def test_sprachwahl_mit_deutschen_namen_und_kombinationen():
    from src.utils.tesseract import hat_fraktur, sprachwahl

    wahl = sprachwahl(["deu", "eng", "deu_frak", "fra", "xyz"])
    assert wahl == [("deu+eng", "Deutsch + Englisch"), ("deu_frak+deu", "Deutsch (Fraktur) + Deutsch"),
                    ("deu", "Deutsch"), ("eng", "Englisch"), ("deu_frak", "Deutsch (Fraktur)"),
                    ("fra", "Französisch"), ("xyz", "xyz")]
    assert hat_fraktur(["deu", "deu_frak"]) and not hat_fraktur(["deu", "eng"])
    assert sprachwahl(["deu"]) == [("deu", "Deutsch")]     # keine Kombination ohne das zweite Modell


def test_fraktur_hinweis_nennt_quelle_und_ordner_ohne_herunterzuladen():
    from src.utils.tesseract import FRAKTUR_URL, fraktur_hinweis

    text = fraktur_hinweis("C:/Tesseract/tessdata")
    assert FRAKTUR_URL in text and "C:/Tesseract/tessdata" in text and "nichts automatisch" in text


def test_sprachangebot_nennt_fehlendes_fraktur(monkeypatch, tmp_path):
    from src.core import pdf_analyzer

    konfig = h.konfig_fuer(tmp_path, ocr_aktiv=True, ocr_tesseract="tesseract-fake")
    monkeypatch.setattr(pdf_analyzer, "_search_konfig", lambda: konfig)
    _list_langs(monkeypatch, 'List of available languages (3):\ndeu\neng\nosd\n')
    angebot = pdf_analyzer.ocr_sprachangebot()
    assert angebot["tesseract"] and not angebot["fraktur"]
    assert [c for c, _ in angebot["sprachen"]] == ["deu+eng", "deu", "eng"]
    monkeypatch.setattr(type(konfig), "ocr_einstellungen", lambda self: {"tesseract": None, "tessdata": None})
    assert pdf_analyzer.ocr_sprachangebot()["tesseract"] is False


# --------------------------------------------------------------------------- PDF-Cache

@pytest.fixture
def cache(tmp_path, monkeypatch):
    from src.core import pdf_cache as pc
    from src.utils import config as cfg_mod

    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fresh)
    monkeypatch.setattr(pc.PDFCache, "_instance", None)
    c = pc.PDFCache()
    assert c._persist_cache and c._db_path.parent == tmp_path
    return c


def test_pdf_cache_speichert_lesbarkeit_und_markierung(cache, tmp_path, monkeypatch):
    from src.core import pdf_cache as pc

    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Text"])
    result = pc.PDFAnalysisResult(pdf_path=pdf, extracted_text="x", file_modified=pdf.stat().st_mtime,
                                  ocr_lesbarkeit=(120, 10))
    cache._cache[pdf] = result
    cache._save_to_db(result)
    assert cache.ocr_schlecht(pdf)

    monkeypatch.setattr(pc.PDFCache, "_instance", None)
    neu = pc.PDFCache()                       # liest die gespeicherte Datenbank
    assert neu.get(pdf).ocr_lesbarkeit == (120, 10) and neu.ocr_schlecht(pdf)

    neu.clear_for_pdf(pdf)                    # auch der gespeicherte Eintrag faellt weg
    assert not neu.ocr_schlecht(pdf)
    monkeypatch.setattr(pc.PDFCache, "_instance", None)
    assert pc.PDFCache().get(pdf) is None


def test_pdf_cache_ohne_lesbarkeit_oder_gut_erkannt_ist_nicht_markiert(cache, tmp_path):
    from src.core import pdf_cache as pc

    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Text"])
    cache._cache[pdf] = pc.PDFAnalysisResult(pdf_path=pdf, file_modified=pdf.stat().st_mtime)
    assert not cache.ocr_schlecht(pdf)
    cache._cache[pdf].ocr_lesbarkeit = (120, 118)
    assert not cache.ocr_schlecht(pdf)
    assert not cache.ocr_schlecht(tmp_path / "unbekannt.pdf")


def test_pdf_cache_migriert_alte_datenbank(tmp_path, monkeypatch):
    """Eine pdf_cache.db aus der Zeit vor Issue #47 bekommt die Spalten nachgereicht."""
    from src.core import pdf_cache as pc
    from src.utils import config as cfg_mod

    con = sqlite3.connect(tmp_path / "pdf_cache.db")
    con.execute("CREATE TABLE pdf_cache (pdf_path TEXT PRIMARY KEY, extracted_text TEXT, keywords TEXT, dates TEXT, "
                "analyzed_at TEXT, file_modified REAL, llm_suggestions TEXT, llm_fetched INTEGER DEFAULT 0)")
    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Text"])
    con.execute("INSERT INTO pdf_cache VALUES (?, 'alt', '[]', '[]', '2026-01-01T00:00:00', ?, NULL, 0)",
                (str(pdf), pdf.stat().st_mtime))
    con.commit()
    con.close()
    fresh = cfg_mod.Config(config_path=tmp_path / "config.json")
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fresh)
    monkeypatch.setattr(pc.PDFCache, "_instance", None)
    c = pc.PDFCache()
    assert c.get(pdf).extracted_text == "alt" and c.get(pdf).ocr_lesbarkeit is None


# --------------------------------------------------------------------------- Kachel

@pytest.fixture
def thumbnail(qtbot, monkeypatch, tmp_path):
    from src.gui import pdf_thumbnail as th
    monkeypatch.setattr(th.ThumbnailLoaderThread, "start", lambda self: None)
    pdf = h.pdf_mit_text(tmp_path / "a.pdf", ["Text"])
    widget = th.PDFThumbnailWidget(pdf)
    qtbot.addWidget(widget)
    return widget


def _untermenue(menu, anfang: str):
    for a in menu.actions():
        if a.menu() is not None and a.text().startswith(anfang):
            return a.menu()
    raise AssertionError(f"Kein Untermenue {anfang!r}: {[a.text() for a in menu.actions()]}")


def test_warndreieck_an_und_aus_mit_tooltip(thumbnail):
    assert not thumbnail.ocr_schlecht and thumbnail._ocr_symbol.isHidden()
    assert "Text schlecht erkannt" not in thumbnail.toolTip()

    thumbnail.ocr_schlecht = True
    assert not thumbnail._ocr_symbol.isHidden()
    assert "Text schlecht erkannt – Rechtsklick für andere Erkennung" in thumbnail.toolTip()
    # liegt oben rechts im Bild und schluckt keine Mausklicks
    sym = thumbnail._ocr_symbol
    assert sym.parent() is thumbnail.thumbnail_label and sym.x() > thumbnail.thumbnail_label.width() // 2 and sym.y() < 10
    from PyQt6.QtCore import Qt
    assert sym.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    thumbnail.ocr_schlecht = False
    assert thumbnail._ocr_symbol.isHidden() and "schlecht erkannt" not in thumbnail.toolTip()


def test_warndreieck_und_ki_marker_vertragen_sich(thumbnail):
    thumbnail.has_ai_suggestion = True
    thumbnail.ocr_schlecht = True
    assert "KI-Vorschlag vorhanden" in thumbnail.toolTip() and "schlecht erkannt" in thumbnail.toolTip()
    thumbnail.has_ai_suggestion = False
    assert "KI-Vorschlag" not in thumbnail.toolTip() and "schlecht erkannt" in thumbnail.toolTip()


def test_warndreieck_wird_gezeichnet(thumbnail):
    thumbnail.ocr_schlecht = True
    bild = thumbnail._ocr_symbol.grab().toImage()
    farben = {bild.pixelColor(x, y).name() for x in range(bild.width()) for y in range(bild.height())}
    assert "#f39c12" in farben


def test_menue_hat_ocr_wiederholen_und_handschrift(thumbnail):
    menu = thumbnail._build_context_menu()
    texte = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texte.index("OCR wiederholen mit …") == texte.index("OCR neu durchführen") + 1
    assert texte[texte.index("OCR wiederholen mit …") + 1] == "Handschrift mit KI entziffern (Bilderkennung)"


def _angebot(thumbnail, monkeypatch, sprachen, fraktur=False, tesseract=True):
    monkeypatch.setattr(thumbnail, "_ocr_sprachangebot", lambda: {
        "tesseract": tesseract, "sprachen": sprachen, "fraktur": fraktur, "tessdata": "C:/tessdata"})


def test_sprachmenue_listet_installierte_sprachen_und_sendet_code(thumbnail, monkeypatch):
    _angebot(thumbnail, monkeypatch, [("deu+eng", "Deutsch + Englisch"), ("deu_frak", "Deutsch (Fraktur)")],
             fraktur=True)
    empfangen = []
    thumbnail.reocr_sprache_requested.connect(lambda p, s: empfangen.append((p, s)))
    sub = _untermenue(thumbnail._build_context_menu(), "OCR wiederholen mit")
    assert [a.text() for a in sub.actions()] == ["Sprachen werden gelesen …"]    # erst beim Aufklappen gefuellt
    sub.aboutToShow.emit()
    assert [a.text() for a in sub.actions()] == ["Deutsch + Englisch", "Deutsch (Fraktur)"]   # Fraktur da: kein Hinweis
    sub.actions()[1].trigger()
    assert empfangen == [(thumbnail.pdf_path, "deu_frak")]


def test_sprachmenue_ohne_fraktur_zeigt_installationshinweis(thumbnail, monkeypatch):
    from src.gui import pdf_thumbnail as th

    _angebot(thumbnail, monkeypatch, [("deu", "Deutsch")], fraktur=False)
    sub = _untermenue(thumbnail._build_context_menu(), "OCR wiederholen mit")
    sub.aboutToShow.emit()
    texte = [a.text() for a in sub.actions() if not a.isSeparator()]
    assert texte == ["Deutsch", "Fraktur (nicht installiert) – so installieren …"]
    gezeigt = []
    monkeypatch.setattr(th.QMessageBox, "information", lambda *a, **k: gezeigt.append(a[2]))
    sub.actions()[-1].trigger()
    assert "deu_frak.traineddata" in gezeigt[0] and "C:/tessdata" in gezeigt[0]


def test_sprachmenue_ohne_tesseract(thumbnail, monkeypatch):
    _angebot(thumbnail, monkeypatch, [], tesseract=False)
    sub = _untermenue(thumbnail._build_context_menu(), "OCR wiederholen mit")
    sub.aboutToShow.emit()
    assert [a.text() for a in sub.actions()] == ["Tesseract nicht gefunden"] and not sub.actions()[0].isEnabled()


def test_handschrift_sendet_signal(thumbnail):
    empfangen = []
    thumbnail.handschrift_requested.connect(empfangen.append)
    menu = thumbnail._build_context_menu()
    next(a for a in menu.actions() if a.text().startswith("Handschrift mit KI")).trigger()
    assert empfangen == [thumbnail.pdf_path]


# --------------------------------------------------------------------------- Bildeingabe der Provider

def test_modellnamen_mit_bilderkennung():
    from src.ml.llm_provider import modell_versteht_bilder as v

    for name in ("qwen2.5vl:7b", "llama3.2-vision", "llava:13b", "claude-sonnet-4-20250514", "gpt-4o-mini",
                 "openai/gpt-4.1-nano", "google/gemini-2.5-flash", "minicpm-v", "gemma3:12b"):
        assert v(name), name
    for name in ("", None, "llama3.1:8b", "gpt-oss:20b", "gpt-3.5-turbo", "o3-mini", "mistral-small", "qwen3:8b"):
        assert not v(name), name


def _llm_config(modell: str, **kw):
    from src.ml.llm_provider import LLMConfig
    return LLMConfig(api_key=kw.pop("api_key", "schluessel"), model=modell, **kw)


def test_basis_provider_ohne_bildeingabe_kann_keine_bilder():
    from src.ml.poe_provider import PoeProvider

    p = PoeProvider(_llm_config("GPT-4o"))
    assert not p.supports_vision()
    with pytest.raises(NotImplementedError):
        p.describe_images([b"x"], "lies")


def test_claude_schickt_bilder_als_image_bloecke(monkeypatch):
    from src.ml.claude_provider import ClaudeProvider

    p = ClaudeProvider(_llm_config("sonnet-4"))
    assert p.supports_vision()
    gesehen = {}

    def post(url, body, headers, timeout=120):
        gesehen.update(url=url, body=body, headers=headers)
        return {"content": [{"type": "text", "text": "Entziffert"}]}, None

    monkeypatch.setattr(p, "_http_post_json", post)
    assert p.describe_images([b"jpeg1", b"jpeg2"], "Lies das") == "Entziffert"
    inhalt = gesehen["body"]["messages"][0]["content"]
    assert [b["type"] for b in inhalt] == ["image", "image", "text"] and inhalt[-1]["text"] == "Lies das"
    assert inhalt[0]["source"] == {"type": "base64", "media_type": "image/jpeg",
                                   "data": base64.b64encode(b"jpeg1").decode()}
    assert gesehen["headers"]["x-api-key"] == "schluessel"


def test_openai_und_openrouter_schicken_image_url(monkeypatch):
    from src.ml.openai_provider import OpenAIProvider
    from src.ml.openrouter_provider import OpenRouterProvider

    for klasse, modell, name in ((OpenAIProvider, "gpt-4o-mini", "OpenAI"),
                                 (OpenRouterProvider, "google/gemini-2.5-flash", "OpenRouter")):
        p = klasse(_llm_config(modell))
        assert p.supports_vision()
        gesehen = {}

        def post(url, body, headers, timeout=None, gesehen=gesehen):
            gesehen.update(url=url, body=body)
            return {"choices": [{"message": {"content": "Text von " + name}}]}, None

        monkeypatch.setattr(p, "_http_post_json", post)
        assert p.describe_images([b"jpeg"], "Lies das") == "Text von " + name
        inhalt = gesehen["body"]["messages"][0]["content"]
        assert inhalt[0] == {"type": "text", "text": "Lies das"}
        assert inhalt[1]["image_url"]["url"] == "data:image/jpeg;base64," + base64.b64encode(b"jpeg").decode()
    assert not OpenAIProvider(_llm_config("gpt-3.5-turbo")).supports_vision()
    assert not OpenRouterProvider(_llm_config("meta-llama/llama-3.1-70b-instruct")).supports_vision()


def test_ollama_schickt_images_und_erkennt_vision_modelle(monkeypatch):
    from src.ml.ollama_provider import OllamaCloudProvider, OllamaProvider

    p = OllamaProvider(_llm_config("qwen2.5vl:7b", api_key=""))
    assert p.supports_vision() and not OllamaProvider(_llm_config("llama3.1:8b", api_key="")).supports_vision()
    assert OllamaCloudProvider(_llm_config("gemma3:27b")).supports_vision()
    gesehen = {}

    def post(url, payload):
        gesehen.update(url=url, payload=payload)
        return {"message": {"content": "Handschrift"}}, None

    monkeypatch.setattr(p, "_post_chat", post)
    assert p.describe_images([b"jpeg"], "Lies das") == "Handschrift"
    nachricht = gesehen["payload"]["messages"][0]
    assert nachricht["images"] == [base64.b64encode(b"jpeg").decode()] and nachricht["content"] == "Lies das"
    assert gesehen["payload"]["model"] == "qwen2.5vl:7b" and gesehen["url"].endswith("/api/chat")


def test_provider_fehler_werden_zu_runtime_error(monkeypatch):
    from src.ml.claude_provider import ClaudeProvider
    from src.ml.ollama_provider import OllamaProvider

    p = ClaudeProvider(_llm_config("sonnet-4"))
    monkeypatch.setattr(p, "_http_post_json", lambda *a, **k: (None, "Claude HTTP 401: ungueltig"))
    with pytest.raises(RuntimeError, match="401"):
        p.describe_images([b"x"], "lies")
    with pytest.raises(RuntimeError, match="API-Schlüssel"):
        ClaudeProvider(_llm_config("sonnet-4", api_key="")).describe_images([b"x"], "lies")
    o = OllamaProvider(_llm_config("llava", api_key=""))
    monkeypatch.setattr(o, "_post_chat", lambda url, payload: (None, "Keine Verbindung zu Ollama"))
    with pytest.raises(RuntimeError, match="Verbindung"):
        o.describe_images([b"x"], "lies")


# --------------------------------------------------------------------------- Handschrift (Kern, Fake-Provider)

class FakeVision:
    """Fake-Provider, der Bilder 'liest'."""

    def __init__(self, antworten=None, fehler_bei: int | None = None):
        self.bilder: list[bytes] = []
        self.prompts: list[str] = []
        self.antworten = antworten or {}
        self.fehler_bei = fehler_bei

    def describe_images(self, images, prompt, max_tokens=3000):
        self.bilder.extend(images)
        self.prompts.append(prompt)
        n = len(self.bilder)
        if self.fehler_bei == n:
            raise RuntimeError("Claude HTTP 429: Limit erreicht")
        return self.antworten.get(n, f"Handschrift Seite {n}")


def test_entziffern_rendert_jede_seite_als_jpeg_und_sammelt_den_text(tmp_path):
    from src.core import handschrift_ki as hk

    pdf = h.pdf_mit_bild(tmp_path / "brief.pdf", seiten=3)
    provider = FakeVision()
    erg = hk.entziffern(pdf, provider)
    assert erg["fehler"] is None and erg["seiten"] == 3 and erg["gesamt"] == 3 and not erg["gekuerzt"]
    assert erg["texte"] == {1: "Handschrift Seite 1", 2: "Handschrift Seite 2", 3: "Handschrift Seite 3"}
    assert len(provider.bilder) == 3 and all(b[:3] == b"\xff\xd8\xff" for b in provider.bilder)   # JPEG
    assert all("Handschrift" in p for p in provider.prompts)
    assert "--- Seite 2 ---" in hk.gesamttext(erg["texte"])


def test_entziffern_begrenzt_die_seitenzahl(tmp_path):
    from src.core import handschrift_ki as hk

    pdf = h.pdf_mit_bild(tmp_path / "lang.pdf", seiten=12)
    provider = FakeVision()
    erg = hk.entziffern(pdf, provider)
    assert hk.MAX_SEITEN == 10 and len(provider.bilder) == 10
    assert erg["gesamt"] == 12 and erg["gekuerzt"] and erg["seiten"] == 10


def test_entziffern_behaelt_bis_zum_fehler_gelesenes_und_bricht_ab(tmp_path):
    from src.core import handschrift_ki as hk

    pdf = h.pdf_mit_bild(tmp_path / "brief.pdf", seiten=3)
    erg = hk.entziffern(pdf, FakeVision(fehler_bei=2))
    assert erg["texte"] == {1: "Handschrift Seite 1"} and "429" in erg["fehler"]
    stopp = FakeVision()
    erg = hk.entziffern(pdf, stopp, abbrechen=lambda: len(stopp.bilder) >= 1)
    assert len(stopp.bilder) == 1 and erg["seiten"] == 1


def test_entziffern_meldet_kaputte_pdf(tmp_path):
    from src.core import handschrift_ki as hk

    kaputt = tmp_path / "kaputt.pdf"
    kaputt.write_bytes(b"kein pdf")
    erg = hk.entziffern(kaputt, FakeVision())
    assert erg["fehler"] and not erg["texte"]


def test_vision_bereit_prueft_provider_und_modell():
    from src.core import handschrift_ki as hk
    from src.ml.ollama_provider import OllamaProvider

    class Klassifikator:
        def __init__(self, provider, an=True):
            self.llm_provider, self._an = provider, an

        def is_llm_available(self):
            return self._an

        def get_llm_provider_name(self):
            return "Ollama"

    ok = OllamaProvider(_llm_config("qwen2.5vl", api_key=""))
    assert hk.vision_bereit(Klassifikator(ok)) == (ok, "")
    provider, grund = hk.vision_bereit(Klassifikator(OllamaProvider(_llm_config("llama3.1:8b", api_key=""))))
    assert provider is None and "llama3.1:8b" in grund and "versteht keine Bilder" in grund
    assert hk.vision_bereit(Klassifikator(None))[0] is None
    assert hk.vision_bereit(Klassifikator(ok, an=False))[0] is None


def test_text_uebernehmen_speichert_wie_ocr_text_und_entfernt_die_markierung(umgebung, monkeypatch):
    from src.core import handschrift_ki as hk

    ablage, konfig, idx = umgebung
    fake_sprachen(monkeypatch)
    scan = h.pdf_mit_bild(ablage / "scan.pdf", seiten=1)
    with PDFAnalyzer(scan) as a:
        a.extract_text()
    assert ocr_schlecht(idx.ocr_lesbarkeit(str(scan)))
    assert hk.vorhandener_text(scan, [1]) and not hk.vorhandener_text(scan, [2])

    erg = hk.text_uebernehmen(scan, {1: "Lieber Hans, ich komme am Montag um 14 Uhr"})
    assert erg == {"index": True, "seiten": 1, "fehler": None}
    assert not ocr_schlecht(idx.ocr_lesbarkeit(str(scan)))
    with PDFAnalyzer(scan) as a:
        assert "ich komme am Montag" in a.extract_text() and "Rxchn" not in a.extract_text() and not a.ocr_used
    assert [t["name"] for t in idx.suche("Montag")["treffer"]] == ["scan.pdf"]   # auch gefunden


def test_text_uebernehmen_ohne_suche_tut_nichts(tmp_path, monkeypatch):
    from src.core import handschrift_ki as hk

    monkeypatch.setattr("src.core.pdf_analyzer.suchindex_fuer_analyse", lambda: None)
    assert hk.text_uebernehmen(tmp_path / "x.pdf", {1: "Text"}) == {"index": False, "seiten": 0, "fehler": None}
    assert not hk.vorhandener_text(tmp_path / "x.pdf", [1])


# --------------------------------------------------------------------------- Ablauf im Hauptfenster

@pytest.fixture
def scan_ordner(fresh_singletons):  # noqa: F811
    scan = fresh_singletons["tmp_path"] / "Scan"
    scan.mkdir()
    h.pdf_mit_bild(scan / "a.pdf", seiten=2)
    return scan


@pytest.fixture
def fenster(main_window, scan_ordner, monkeypatch):  # noqa: F811
    from src.gui import main_window as mw_mod
    from src.gui import ocr_schwer_lesbar as osl
    from src.gui.pdf_thumbnail import PDFThumbnailWidget

    monkeypatch.setattr(PDFThumbnailWidget, "load_thumbnail", lambda self: None)
    monkeypatch.setattr(mw_mod, "thumbnail_vergessen", lambda p: None)
    monkeypatch.setattr(mw_mod, "index_melden", lambda *a, **k: None)
    log = {"info": [], "warn": [], "frage": [], "analyse": [], "einstellungen": [], "cleared": []}
    monkeypatch.setattr(osl.QMessageBox, "information", lambda *a, **k: log["info"].append(a[2]))
    monkeypatch.setattr(osl.QMessageBox, "warning", lambda *a, **k: log["warn"].append(a[2]))
    monkeypatch.setattr(main_window, "update_suggestions_for_pdf", lambda p: log["analyse"].append(p))
    monkeypatch.setattr(main_window, "_open_settings_dialog", lambda tab=None: log["einstellungen"].append(tab))
    orig = main_window.pdf_cache.clear_for_pdf
    monkeypatch.setattr(main_window.pdf_cache, "clear_for_pdf", lambda p: log["cleared"].append(p) or orig(p))
    main_window._navigate_to_folder(scan_ordner)
    main_window._log = log
    main_window._pdf = scan_ordner / "a.pdf"
    main_window._widget = next(w for w in main_window.pdf_widgets if w.pdf_path.name == "a.pdf")
    return main_window


def _kachel(win):
    """Aktuelle Kachel der PDF (das Hauptfenster baut die Kacheln im Hintergrund gelegentlich neu auf)."""
    return next(w for w in win.pdf_widgets if w.pdf_path == win._pdf)


def _provider_setzen(win, provider, art: str, modell: str = "") -> None:
    """KI-Einstellung vortaeuschen, ohne ``config.set`` (das lädt die Kacheln neu)."""
    orig = win.config.get
    win.config.get = lambda key, default=None: {"provider": art, "model": modell} if key == "llm" else orig(key, default)
    win.hybrid_classifier.llm_provider = provider
    win.hybrid_classifier.llm_enabled = True


def _vision_provider(klasse_name: str):
    from src.ml.claude_provider import ClaudeProvider
    from src.ml.ollama_provider import OllamaProvider

    if klasse_name == "claude":
        class P(ClaudeProvider):
            def describe_images(self, images, prompt, max_tokens=3000):
                return FakeVision.describe_images(self.fake, images, prompt)

        p = P(_llm_config("sonnet-4"))
    else:
        class P(OllamaProvider):
            def describe_images(self, images, prompt, max_tokens=3000):
                return FakeVision.describe_images(self.fake, images, prompt)

        p = P(_llm_config("qwen2.5vl:7b", api_key=""))
    p.fake = FakeVision()
    return p


def test_marker_beim_laden_und_nach_analyse(fenster, monkeypatch):
    from src.core.pdf_cache import PDFAnalysisResult

    pdf, widget = fenster._pdf, _kachel(fenster)
    assert not widget.ocr_schlecht
    fenster.pdf_cache._cache[pdf] = PDFAnalysisResult(pdf_path=pdf, file_modified=pdf.stat().st_mtime,
                                                      ocr_lesbarkeit=(200, 20))
    fenster._on_pdf_analyzed(pdf)      # Cache-Signal nach einer Analyse
    assert widget.ocr_schlecht
    fenster._navigate_to_folder(pdf.parent)   # neue Kachel: gleich markiert
    assert next(w for w in fenster.pdf_widgets if w.pdf_path == pdf).ocr_schlecht
    fenster.pdf_cache._cache[pdf].ocr_lesbarkeit = (200, 190)
    fenster._on_pdf_analyzed(pdf)
    assert not next(w for w in fenster.pdf_widgets if w.pdf_path == pdf).ocr_schlecht


def test_ocr_wiederholen_besser_ersetzt_und_informiert(fenster, qtbot, monkeypatch):
    from src.gui import ocr_neu_worker

    pdf, widget = fenster._pdf, _kachel(fenster)
    widget.ocr_schlecht = True
    gesehen = []
    monkeypatch.setattr(ocr_neu_worker, "ocr_wiederholen", lambda p, s, abbrechen=None: gesehen.append((Path(p), s)) or
                        {"index": True, "seiten": 2, "besser": True, "vorher": (100, 10), "nachher": (100, 95),
                         "fehler": None})
    fenster.selected_pdf = pdf
    fenster.selected_pdfs = []
    widget.reocr_sprache_requested.emit(pdf, "deu_frak")
    assert widget.analyzing
    qtbot.waitUntil(lambda: not fenster._ocr_schwer_lesbar.laeuft, timeout=5000)

    assert gesehen == [(pdf, "deu_frak")] and not widget.analyzing
    assert not widget.ocr_schlecht                       # Markierung neu bewertet: jetzt gut (95 %)
    assert fenster._log["cleared"] == [pdf] and fenster._log["analyse"] == [pdf]
    (meldung,) = fenster._log["info"]
    assert "Deutsch (Fraktur)" in meldung and "besser" in meldung and "95 % statt 10 %" in meldung


def test_ocr_wiederholen_nicht_besser_laesst_alles_und_informiert(fenster, qtbot, monkeypatch):
    from src.gui import ocr_neu_worker

    pdf, widget = fenster._pdf, _kachel(fenster)
    widget.ocr_schlecht = True
    monkeypatch.setattr(ocr_neu_worker, "ocr_wiederholen", lambda p, s, abbrechen=None:
                        {"index": True, "seiten": 0, "besser": False, "vorher": (100, 30), "nachher": (100, 20),
                         "fehler": None})
    widget.reocr_sprache_requested.emit(pdf, "fra")
    qtbot.waitUntil(lambda: not fenster._ocr_schwer_lesbar.laeuft, timeout=5000)
    assert widget.ocr_schlecht and fenster._log["cleared"] == []     # nichts verworfen, weiter markiert
    assert "nicht besser" in fenster._log["info"][0] and "bleibt" in fenster._log["info"][0]


def test_ocr_wiederholen_fehler_wird_gemeldet(fenster, qtbot, monkeypatch):
    from src.gui import ocr_neu_worker

    pdf, widget = fenster._pdf, _kachel(fenster)
    monkeypatch.setattr(ocr_neu_worker, "ocr_wiederholen", lambda p, s, abbrechen=None:
                        {"index": True, "seiten": 0, "besser": False, "vorher": None, "nachher": None,
                         "fehler": "Sprachdaten fehlen: deu_frak"})
    widget.reocr_sprache_requested.emit(pdf, "deu_frak")
    qtbot.waitUntil(lambda: not fenster._ocr_schwer_lesbar.laeuft, timeout=5000)
    assert "Sprachdaten fehlen" in fenster._log["warn"][0] and not widget.analyzing


def test_handschrift_ohne_vision_provider_zeigt_hilfedialog_mit_einstellungen(fenster, monkeypatch):
    from src.gui import ocr_schwer_lesbar as osl

    fenster.hybrid_classifier.llm_enabled = False       # kein KI-Anbieter
    gezeigt = []
    monkeypatch.setattr(osl, "zeige_vision_hilfe", lambda parent, grund: gezeigt.append(grund) or True)
    _kachel(fenster).handschrift_requested.emit(fenster._pdf)
    assert len(gezeigt) == 1 and "kein KI-Anbieter" in gezeigt[0]
    assert fenster._log["einstellungen"] == [osl.KI_TAB] and osl.KI_TAB == "KI-Assistent (LLM)"
    assert not fenster._ocr_schwer_lesbar.laeuft

    fenster._log["einstellungen"].clear()                # "Schließen": keine Einstellungen
    monkeypatch.setattr(osl, "zeige_vision_hilfe", lambda parent, grund: False)
    _kachel(fenster).handschrift_requested.emit(fenster._pdf)
    assert fenster._log["einstellungen"] == []


def test_handschrift_mit_text_modell_zeigt_hilfedialog(fenster, monkeypatch):
    from src.gui import ocr_schwer_lesbar as osl
    from src.ml.ollama_provider import OllamaProvider

    _provider_setzen(fenster, OllamaProvider(_llm_config("llama3.1:8b", api_key="")), "ollama", "llama3.1:8b")
    gezeigt = []
    monkeypatch.setattr(osl, "zeige_vision_hilfe", lambda parent, grund: gezeigt.append(grund) or False)
    _kachel(fenster).handschrift_requested.emit(fenster._pdf)
    assert "llama3.1:8b" in gezeigt[0] and "versteht keine Bilder" in gezeigt[0]


def test_hilfedialog_text_und_einstellungsknopf(qtbot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox, QWidget

    from src.gui.ocr_schwer_lesbar import zeige_vision_hilfe

    eltern = QWidget()
    qtbot.addWidget(eltern)
    inhalt = {}

    def exec_(self, knopf):
        inhalt["text"] = self.informativeText()
        inhalt["knoepfe"] = [b.text() for b in self.buttons()]
        self.buttons()[knopf].click()

    monkeypatch.setattr(QMessageBox, "exec", lambda self: exec_(self, 0))
    assert zeige_vision_hilfe(eltern, "Kein Modell.") is True
    assert inhalt["knoepfe"] == ["Einstellungen öffnen", "Schließen"]
    for stichwort in ("Ollama", "qwen2.5vl", "Claude", "OpenAI", "Kein Modell."):
        assert stichwort in inhalt["text"]
    monkeypatch.setattr(QMessageBox, "exec", lambda self: exec_(self, 1))
    assert zeige_vision_hilfe(eltern, "x") is False


def _auf_ergebnis_warten(fenster, qtbot):
    qtbot.waitUntil(lambda: not fenster._ocr_schwer_lesbar.laeuft, timeout=8000)


def test_handschrift_cloud_fragt_vor_dem_hochladen(fenster, qtbot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from src.gui import ocr_schwer_lesbar as osl

    provider = _vision_provider("claude")
    _provider_setzen(fenster, provider, "claude", "sonnet-4")
    fragen = []
    antwort = {"wert": QMessageBox.StandardButton.No}
    monkeypatch.setattr(osl.QMessageBox, "question", lambda *a, **k: fragen.append(a[2]) or antwort["wert"])
    ergebnisse = []
    monkeypatch.setattr(osl.HandschriftErgebnisDialog, "exec", lambda self: ergebnisse.append(self.text_edit.toPlainText()))

    _kachel(fenster).handschrift_requested.emit(fenster._pdf)           # Nein: nichts wird gesendet
    assert len(fragen) == 1 and "hochgeladen" in fragen[0] and "Kosten" in fragen[0] and "2 Seite(n)" in fragen[0]
    assert not fenster._ocr_schwer_lesbar.laeuft and provider.fake.bilder == []

    antwort["wert"] = QMessageBox.StandardButton.Yes                   # Ja: Seiten gehen an das Modell
    _kachel(fenster).handschrift_requested.emit(fenster._pdf)
    _auf_ergebnis_warten(fenster, qtbot)
    assert len(provider.fake.bilder) == 2
    assert len(ergebnisse) == 1 and "Handschrift Seite 1" in ergebnisse[0] and "Handschrift Seite 2" in ergebnisse[0]
    assert not _kachel(fenster).analyzing


def test_handschrift_lokales_ollama_fragt_nicht(fenster, qtbot, monkeypatch):
    from src.gui import ocr_schwer_lesbar as osl

    provider = _vision_provider("ollama")
    _provider_setzen(fenster, provider, "ollama", "qwen2.5vl:7b")
    monkeypatch.setattr(osl.QMessageBox, "question",
                        lambda *a, **k: pytest.fail("lokal: keine Rückfrage zum Hochladen"))
    monkeypatch.setattr(osl.HandschriftErgebnisDialog, "exec", lambda self: None)
    _kachel(fenster).handschrift_requested.emit(fenster._pdf)
    _auf_ergebnis_warten(fenster, qtbot)
    assert len(provider.fake.bilder) == 2


def test_handschrift_uebernehmen_fragt_vor_dem_ersetzen(fenster, qtbot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from src.core import handschrift_ki as hk
    from src.gui import ocr_schwer_lesbar as osl

    provider = _vision_provider("ollama")
    _provider_setzen(fenster, provider, "ollama", "qwen2.5vl:7b")

    def dialog_exec(self):
        self.uebernehmen_button.click()          # "Als Text übernehmen"

    monkeypatch.setattr(osl.HandschriftErgebnisDialog, "exec", dialog_exec)
    uebernommen = []
    monkeypatch.setattr(hk, "text_uebernehmen", lambda p, t: uebernommen.append((Path(p), dict(t))) or
                        {"index": True, "seiten": len(t), "fehler": None})
    fragen = []
    antwort = {"wert": QMessageBox.StandardButton.No}
    monkeypatch.setattr(osl.QMessageBox, "question", lambda *a, **k: fragen.append(a[2]) or antwort["wert"])

    # vorhandener Text, Nutzer sagt Nein: nichts wird ueberschrieben
    monkeypatch.setattr(hk, "vorhandener_text", lambda p, s: True)
    _kachel(fenster).handschrift_requested.emit(fenster._pdf)
    _auf_ergebnis_warten(fenster, qtbot)
    assert len(fragen) == 1 and "ersetzt" in fragen[0] and uebernommen == []

    # Ja: gespeichert, Markierung faellt weg, Cache verworfen
    _kachel(fenster).ocr_schlecht = True
    antwort["wert"] = QMessageBox.StandardButton.Yes
    _kachel(fenster).handschrift_requested.emit(fenster._pdf)
    _auf_ergebnis_warten(fenster, qtbot)
    assert len(uebernommen) == 1 and uebernommen[0][0] == fenster._pdf
    assert uebernommen[0][1] == {1: "Handschrift Seite 3", 2: "Handschrift Seite 4"}
    assert not _kachel(fenster).ocr_schlecht and fenster._log["cleared"] == [fenster._pdf]

    # ohne vorhandenen Text keine Rueckfrage
    monkeypatch.setattr(hk, "vorhandener_text", lambda p, s: False)
    n = len(fragen)
    _kachel(fenster).handschrift_requested.emit(fenster._pdf)
    _auf_ergebnis_warten(fenster, qtbot)
    assert len(fragen) == n and len(uebernommen) == 2


def test_ergebnisdialog_zeigt_text_kopierbar_und_ohne_uebernehmen_beim_schliessen(qtbot):
    from PyQt6.QtWidgets import QApplication

    from src.gui.ocr_schwer_lesbar import HandschriftErgebnisDialog

    dialog = HandschriftErgebnisDialog({1: "Eins", 2: "Zwei"}, "2 Seite(n) entziffert.")
    qtbot.addWidget(dialog)
    assert dialog.text_edit.isReadOnly() and "--- Seite 2 ---" in dialog.text_edit.toPlainText()
    dialog.kopieren_button.click()
    assert "Eins" in QApplication.clipboard().text()
    dialog.reject()
    assert dialog.uebernehmen is False
    assert dialog.uebernehmen_button.text() == "Als Text übernehmen"


def test_handschrift_fehler_der_ki_wird_gemeldet(fenster, qtbot, monkeypatch):
    from src.gui import ocr_schwer_lesbar as osl

    provider = _vision_provider("ollama")
    provider.fake.fehler_bei = 1
    _provider_setzen(fenster, provider, "ollama", "qwen2.5vl:7b")
    monkeypatch.setattr(osl.HandschriftErgebnisDialog, "exec", lambda self: pytest.fail("kein Text, kein Dialog"))
    _kachel(fenster).handschrift_requested.emit(fenster._pdf)
    _auf_ergebnis_warten(fenster, qtbot)
    assert "429" in fenster._log["warn"][0] and not _kachel(fenster).analyzing
