"""Dokumentensuche: SearchConfig (Standardwerte, JSON-Block, config.toml, Anbindung an die PDFSM-Config)."""

from pathlib import Path

from src.search import konfig as konfig_modul
from src.search.konfig import SearchConfig, norm_pfad
from src.utils.config import Config


def test_standardwerte_und_normalisierung(tmp_path, monkeypatch):
    monkeypatch.setattr(konfig_modul, "get_app_data_dir", lambda create=True: tmp_path / "appdata")
    c = SearchConfig()
    assert c.aktiv is False and c.web_port == 18425 and c.ocr_sprachen == "deu+eng"
    assert ".pdf" in c.endungen and ".xlsx" in c.endungen and "node_modules" in c.ordner_ausschliessen
    assert c.db_datei == tmp_path / "appdata" / "suche" / "suche.db"
    assert c.daten_ordner == tmp_path / "appdata" / "suche" and c.log_ordner == tmp_path / "appdata" / "logs"
    assert c.max_dateigroesse == 500 * 1024 * 1024
    assert 1 <= c.anzahl_prozesse <= 8

    c2 = SearchConfig(wurzeln=[" " + str(tmp_path) + "/", ""], endungen=["PDF", " .Md"],
                      ordner_ausschliessen=["AppData"], pfade_ausschliessen=[str(tmp_path / "X")],
                      prozesse=3, db_pfad=str(tmp_path / "db" / "s.db"))
    assert c2.wurzeln == [norm_pfad(str(tmp_path))] and c2.endungen == {".pdf", ".md"}
    assert c2.ordner_ausschliessen == {"appdata"} and c2.pfade_ausschliessen == {norm_pfad(str(tmp_path / "X")).lower()}
    assert c2.anzahl_prozesse == 3 and c2.db_datei == tmp_path / "db" / "s.db"


def test_json_block_hin_und_zurueck():
    c = SearchConfig(aktiv=True, wurzeln=["/a"], endungen=[".pdf"], mails_aktiv=True, ocr_dpi=200)
    d = c.als_dict()
    assert d["endungen"] == [".pdf"] and isinstance(d["ordner_ausschliessen"], list)
    assert SearchConfig.aus_dict(d) == c
    # fremde und falsch typisierte Werte
    c3 = SearchConfig.aus_dict({"unbekannt": 1, "prozesse": "4", "aktiv": "ja", "wurzeln": "/einzeln", "ocr_aktiv": 0})
    assert c3.prozesse == 4 and c3.aktiv is True and c3.wurzeln == [norm_pfad("/einzeln")] and c3.ocr_aktiv is False
    assert SearchConfig.aus_dict(None) == SearchConfig()


def test_ocr_einstellungen(monkeypatch):
    monkeypatch.setattr("src.utils.tesseract.find_tesseract", lambda: None)
    c = SearchConfig(ocr_aktiv=True)
    e = c.ocr_einstellungen()
    assert e["aktiv"] is False and e["tesseract"] is None and e["tessdata"] is None
    c2 = SearchConfig(ocr_aktiv=True, ocr_tesseract="/opt/tesseract", ocr_tessdata="/opt/tessdata", ocr_sprachen="deu")
    e2 = c2.ocr_einstellungen()
    assert e2 == {"aktiv": True, "grund": None, "tesseract": "/opt/tesseract", "tessdata": "/opt/tessdata",
                  "sprachen": "deu", "dpi": 300, "min_zeichen": 25, "max_seiten": 1000, "lage_pruefen": True}
    e3 = SearchConfig(ocr_aktiv=False, ocr_tesseract="/opt/tesseract").ocr_einstellungen()
    assert e3["aktiv"] is False and "ausgeschaltet" in e3["grund"]
    assert "Tesseract nicht gefunden" == e["grund"]


def test_ocr_ohne_sprachdaten_aus(tmp_path):
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "eng.traineddata").write_bytes(b"x")
    c = SearchConfig(ocr_aktiv=True, ocr_tesseract="/opt/tesseract", ocr_tessdata=str(tessdata), ocr_sprachen="deu+eng")
    e = c.ocr_einstellungen()
    assert e["aktiv"] is False and e["grund"] == "Sprachdaten fehlen: deu"
    (tessdata / "deu.traineddata").write_bytes(b"x")
    assert c.ocr_einstellungen()["aktiv"] is True


def test_mail_ordner_effektiv(tmp_path, monkeypatch):
    monkeypatch.setattr("src.search.plattform.thunderbird_mail_ordner", lambda: [str(tmp_path / "Profil" / "Mail")])
    assert SearchConfig().mail_ordner_effektiv() == [norm_pfad(str(tmp_path / "Profil" / "Mail"))]
    eigen = SearchConfig(mail_ordner=[str(tmp_path / "Eigene")])
    assert eigen.mail_ordner_effektiv() == [norm_pfad(str(tmp_path / "Eigene"))]


def test_alte_config_toml(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text(
        "[datenbank]\npfad = \"" + (tmp_path / "data" / "alt.db").as_posix() + "\"\n"
        "[suche]\nprioritaet = [\"" + (tmp_path / "Scans").as_posix() + "\"]\n"
        "wurzeln = [\"" + (tmp_path / "Ablage").as_posix() + "\"]\n"
        "endungen = [\".pdf\", \".md\"]\nordner_ausschliessen = [\"Windows\"]\n"
        "pfade_ausschliessen = [\"" + (tmp_path / "Ablage" / "Tmp").as_posix() + "\"]\n"
        "cloud_dateien_herunterladen = true\nmax_dateigroesse_mb = 100\n"
        "[thunderbird]\nmail_ordner = [\"" + (tmp_path / "Mail").as_posix() + "\"]\n"
        "[ocr]\naktiv = true\ntesseract = \"/t/tesseract\"\ntessdata = \"/t/tessdata\"\nsprachen = \"deu\"\n"
        "dpi = 200\nmin_zeichen_pro_seite = 10\nmax_seiten = 50\n"
        "[leistung]\nprozesse = 2\n[web]\nhost = \"127.0.0.1\"\nport = 18500\n",
        encoding="utf-8",
    )
    c = konfig_modul.lade_config_toml(toml)
    assert c.aktiv is True and c.db_datei == tmp_path / "data" / "alt.db"
    assert c.prioritaet == [norm_pfad(str(tmp_path / "Scans"))] and c.wurzeln == [norm_pfad(str(tmp_path / "Ablage"))]
    assert c.endungen == {".pdf", ".md"} and c.ordner_ausschliessen == {"windows"}
    assert c.pfade_ausschliessen == {norm_pfad(str(tmp_path / "Ablage" / "Tmp")).lower()}
    assert c.cloud_herunterladen is True and c.max_dateigroesse_mb == 100
    assert c.mails_aktiv is True and c.mail_ordner == [norm_pfad(str(tmp_path / "Mail"))]
    assert c.ocr_tesseract == norm_pfad("/t/tesseract") or c.ocr_tesseract == "/t/tesseract"
    assert c.ocr_sprachen == "deu" and c.ocr_dpi == 200 and c.ocr_min_zeichen == 10 and c.ocr_max_seiten == 50
    assert c.prozesse == 2 and c.web_port == 18500
    assert konfig_modul.lade(str(toml)).web_port == 18500


def test_pdfsm_config_block_suche(tmp_path):
    cfg = Config(config_path=tmp_path / "config.json")
    scan = tmp_path / "Scan"
    ziel = tmp_path / "Ziel"
    cfg.set("scan_folder", str(scan), auto_save=False)
    cfg.set("target_folders", [str(ziel)], auto_save=False)
    s = cfg.get_search_config()
    assert s.aktiv is False
    assert s.wurzeln == [norm_pfad(str(scan)), norm_pfad(str(ziel))] and s.prioritaet == [norm_pfad(str(scan))]

    s.aktiv = True
    s.wurzeln = [str(tmp_path)]
    s.prioritaet = []
    cfg.set_search_config(s)
    cfg2 = Config(config_path=tmp_path / "config.json")
    s2 = cfg2.get_search_config()
    assert s2.aktiv is True and s2.wurzeln == [norm_pfad(str(tmp_path))] and s2.prioritaet == []
    assert konfig_modul.lade(str(tmp_path / "config.json")).aktiv is True


def test_norm_pfad_laufwerkswurzel(monkeypatch):
    monkeypatch.setattr(konfig_modul.sys, "platform", "win32")
    assert norm_pfad("E:").endswith("\\") and len(norm_pfad("E:")) == 3
    assert not norm_pfad(str(Path("/a/b/"))).endswith(("/", "\\")) or len(norm_pfad("/")) == 1


def test_textebene_stufen_und_sicherung():
    c = SearchConfig(textebene="alle", textebene_sicherung_tage=7)
    assert c.textebene == "alle" and c.textebene_sicherung_tage == 7
    assert SearchConfig(textebene="unsinn").textebene == "aus"
    # Standard (Opt-out): neue Scans bekommen die Textebene; der Lauf beginnt frühestens um 00:00 im Leerlauf
    assert SearchConfig().textebene == "neue_scans" and SearchConfig().hintergrund_uhrzeit == "00:00"
    # Keine Anmeldeaufgabe fuer die Browser-Oberflaeche ohne ausdruecklichen Wunsch (Defender, #163)
    assert SearchConfig().web_aktiv is False and SearchConfig().web_bei_anmeldung is False
    assert SearchConfig(textebene_sicherung_tage=-3).textebene_sicherung_tage == 0
    d = c.als_dict()
    assert d["textebene"] == "alle" and SearchConfig.aus_dict(d).textebene == "alle"
