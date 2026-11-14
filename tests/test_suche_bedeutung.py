"""Bedeutungssuche (Issue #230): Vektoren berechnen, speichern, suchen - mit einer Ollama-Attrappe.

Die Attrappe kennt ein paar Themen und legt Woerter desselben Themas auf
dieselbe Stelle des Vektors: "Autoversicherung" und "Kraftfahrtversicherung"
bedeuten fuer sie dasselbe, haben aber kein gemeinsames Wort.
"""

import numpy as np
import pytest

import helfer_suche as h
from src.rag.retrieval import RetrievalService
from src.search import bedeutung, db
from src.search.indexer import Indexer
from src.search.konfig import SearchConfig
from src.search.pdfsm_daten import PdfsmDaten, bedeutung_suchen
from src.search.suchindex import Suchindex

THEMEN = {
    0: ("autoversicherung", "kraftfahrtversicherung", "kfz-haftpflicht"),
    1: ("brille", "gleitsichtgläser", "augenoptiker"),
    2: ("müllabfuhr", "abfallgebühren", "restabfall"),
    3: ("wetter", "regen"),
}
KFZ = "Beitragsrechnung zur Kraftfahrtversicherung, Kfz-Haftpflicht SF 14, Gesamtbeitrag 755,54 EUR"
OPTIK = "Rechnung Augenoptiker: zwei Gleitsichtgläser und eine Fassung, zusammen 735,00 EUR"
ABFALL = "Bescheid über Abfallgebühren 2026: Restabfall 120 Liter, vierzehntäglich, 187,20 EUR"


def _vektor(text: str) -> list[float]:
    v = [0.0] * 768
    for stelle, woerter in THEMEN.items():
        v[stelle] = float(sum(text.lower().count(w) for w in woerter))
    v[300] = 0.05   # jenseits von DIM: wird abgeschnitten
    if not any(v[:bedeutung.DIM]):
        v[200] = 1.0   # Text ohne bekanntes Thema
    return v


@pytest.fixture
def ollama(monkeypatch):
    """Ollama-Attrappe; ``ollama.anfragen`` sammelt die Aufrufe, ``ollama.modelle`` die geladenen Modelle."""
    class Attrappe:
        anfragen: list = []
        modelle: list = ["embeddinggemma:latest"]
        fehler: str = ""

    def anfrage(url, pfad, daten, zeitlimit):
        Attrappe.anfragen.append((url, pfad, daten))
        if Attrappe.fehler:
            raise bedeutung.BedeutungFehler(Attrappe.fehler)
        if pfad == "/api/tags":
            return {"models": [{"name": m} for m in Attrappe.modelle]}
        return {"embeddings": [_vektor(t) for t in daten["input"]]}

    Attrappe.anfragen = []
    monkeypatch.setattr(bedeutung, "_anfrage", anfrage)
    monkeypatch.setattr(bedeutung, "_matrix_ablage", {})
    return Attrappe


def _dok(pfad: str, typ: str = "pdf") -> dict:
    return {"pfad": pfad, "datei": pfad, "name": pfad.rsplit("/", 1)[-1], "ordner": "/ablage", "typ": typ,
            "format": typ, "groesse": 1000 + len(pfad), "mtime_ns": 1, "datum": 1.7e9, "seiten": 1,
            "textstatus": "text"}


@pytest.fixture
def index(tmp_path):
    """Suchindex mit drei Dokumenten; das erste hat eine zweite, fast leere Seite."""
    konfig = h.konfig_fuer(tmp_path, bedeutung_aktiv=True)
    con = db.verbinde(konfig.db_datei)
    db.init(con)
    db.speichere(con, _dok("/ablage/Scan_001.pdf"), [(1, "text", "Anschreiben ohne besonderen Inhalt, bitte wenden"),
                                                      (2, "text", KFZ), (3, "text", "Seite 3")])
    db.speichere(con, _dok("/ablage/Scan_002.pdf"), [(1, "text", OPTIK)])
    db.speichere(con, _dok("/ablage/Scan_003.pdf"), [(1, "text", ABFALL)])
    con.commit()
    yield konfig, con
    con.close()


# --------------------------------------------------------------------------- Berechnen und Ablage

def test_berechnen_legt_je_seite_einen_vektor_von_256_bytes_ab(index, ollama):
    konfig, con = index
    assert bedeutung.stand(con, "embeddinggemma") == {"seiten": 5, "fertig": 0}
    assert not bedeutung.vorhanden(con)

    assert bedeutung.berechnen(con, "", "embeddinggemma") == 4   # "Seite 3" ist zu kurz

    zeilen = con.execute("SELECT modell, length(vektor) FROM seiten_vektor").fetchall()
    assert [tuple(z) for z in zeilen] == [("embeddinggemma", 256)] * 4
    assert bedeutung.stand(con, "embeddinggemma") == {"seiten": 5, "fertig": 4}
    # Dokumenttexte bekommen den Dokument-Vorsatz von EmbeddingGemma
    texte = [t for _u, pfad, daten in ollama.anfragen if pfad == "/api/embed" for t in daten["input"]]
    assert all(t.startswith("title: none | text: ") for t in texte)


def test_zweiter_lauf_rechnet_nur_neues(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    ollama.anfragen.clear()
    assert bedeutung.berechnen(con, "", "embeddinggemma") == 0
    assert not [a for a in ollama.anfragen if a[1] == "/api/embed"]

    db.speichere(con, _dok("/ablage/Scan_004.pdf"), [(1, "text", "Ein weiteres Schreiben mit genug Text darin.")])
    assert bedeutung.berechnen(con, "", "embeddinggemma") == 1


def test_geaenderter_text_und_geloeschtes_dokument_verlieren_den_vektor(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    con.execute("UPDATE seiten SET text = ? WHERE text = ?", (OPTIK + " Nachtrag", OPTIK))
    assert con.execute("SELECT count(*) FROM seiten_vektor").fetchone()[0] == 3
    db.loesche(con, [con.execute("SELECT id FROM dokumente WHERE name = 'Scan_003.pdf'").fetchone()[0]])
    assert con.execute("SELECT count(*) FROM seiten_vektor").fetchone()[0] == 2
    # Ersetzen eines Dokuments (neu eingelesen) raeumt ebenfalls auf
    db.speichere(con, _dok("/ablage/Scan_001.pdf"), [(1, "text", KFZ)])
    assert con.execute("SELECT count(*) FROM seiten_vektor").fetchone()[0] == 0
    assert bedeutung.berechnen(con, "", "embeddinggemma") == 2


def test_anderes_modell_rechnet_alles_neu(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    assert bedeutung.berechnen(con, "", "anderes-modell") == 4
    assert {z[0] for z in con.execute("SELECT modell FROM seiten_vektor")} == {"anderes-modell"}
    assert bedeutung.stand(con, "embeddinggemma")["fertig"] == 0


def test_abbruch_behaelt_fertige_stapel(index, ollama, monkeypatch):
    konfig, con = index
    monkeypatch.setattr(bedeutung, "STAPEL", 1)
    aufrufe = []

    def weiter():
        aufrufe.append(1)
        if len(aufrufe) > 2:
            raise RuntimeError("Zeitlimit")

    with pytest.raises(RuntimeError):
        bedeutung.berechnen(con, "", "embeddinggemma", weiter=weiter)
    con.rollback()
    assert con.execute("SELECT count(*) FROM seiten_vektor").fetchone()[0] == 2


def test_mails_kommen_nach_den_dokumenten(index, ollama, monkeypatch):
    konfig, con = index
    db.speichere(con, _dok("/post/Inbox#1", typ="mail"), [(1, "text", "Eine Mail mit genug Text für einen Vektor.")])
    monkeypatch.setattr(bedeutung, "STAPEL", 1)
    bedeutung.berechnen(con, "", "embeddinggemma")
    texte = [daten["input"][0] for _u, pfad, daten in ollama.anfragen if pfad == "/api/embed"]
    assert "Eine Mail" in texte[-1] and len(texte) == 5


def test_zu_kurze_vektoren_sind_ein_fehler(index, ollama, monkeypatch):
    konfig, con = index
    monkeypatch.setattr(bedeutung, "_anfrage", lambda *a: {"embeddings": [[0.1] * 64 for _ in a[2]["input"]]})
    with pytest.raises(bedeutung.BedeutungFehler, match="zu kurze Vektoren"):
        bedeutung.berechnen(con, "", "kleines-modell")


def test_packen_normiert_und_rundet():
    v = bedeutung._packen([[3.0, 4.0] + [0.0] * 766])
    assert v.dtype == np.int8 and v.shape == (1, 256)
    assert v[0, 0] == 127 and v[0, 1] == 127      # 0,6 und 0,8 liegen ueber der Skala und werden gekappt
    w = bedeutung._packen([[0.1] * 768])
    assert int(w[0, 0]) == round(bedeutung.SKALA / 16)   # 1/sqrt(256) = 0,0625


@pytest.mark.parametrize("modelle,erwartet", [
    (["embeddinggemma:latest"], True), (["embeddinggemma:300m", "gemma4:12b"], True), (["gemma4:12b"], False),
])
def test_modell_vorhanden(ollama, modelle, erwartet):
    ollama.modelle = modelle
    assert bedeutung.modell_vorhanden("", "embeddinggemma") is erwartet


def test_modell_vorhanden_ohne_ollama(ollama):
    ollama.fehler = "nicht erreichbar"
    assert bedeutung.modell_vorhanden("", "embeddinggemma") is None


# --------------------------------------------------------------------------- Suchen

def _frage(text: str):
    return bedeutung.einbetten("", "embeddinggemma", [text], frage=True)[0]


def test_suche_findet_andere_woerter_und_nennt_die_passende_seite(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    assert db.suche(con, "Autoversicherung")["gesamt"] == 0     # die Wortsuche findet nichts

    treffer = bedeutung.suche(con, _frage("Was zahle ich für meine Autoversicherung?"), "embeddinggemma")

    assert len(treffer) == 1 and treffer[0]["seite"] == 2 and treffer[0]["aehnlichkeit"] > 0.9
    assert db.dokument(con, treffer[0]["dok_id"])["name"] == "Scan_001.pdf"
    # die Frage bekommt den Frage-Vorsatz
    assert ollama.anfragen[-1][2]["input"][0].startswith("task: search result | query: ")


def test_suche_ohne_passendes_dokument_bleibt_leer(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    assert bedeutung.suche(con, _frage("Wie wird das Wetter, gibt es Regen?"), "embeddinggemma") == []


def test_suche_ohne_tabelle_und_mit_anderem_modell_bleibt_leer(index, ollama):
    konfig, con = index
    frage = _frage("Brille")
    assert bedeutung.suche(con, frage, "embeddinggemma") == []
    bedeutung.berechnen(con, "", "embeddinggemma")
    assert bedeutung.suche(con, frage, "anderes-modell") == []
    assert len(bedeutung.suche(con, frage, "embeddinggemma")) == 1


def test_suche_sieht_neue_vektoren_trotz_ablage_im_speicher(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    frage = _frage("Müllabfuhr")
    assert len(bedeutung.suche(con, frage, "embeddinggemma", schluessel="a")) == 1
    db.speichere(con, _dok("/ablage/Scan_005.pdf"), [(1, "text", "Abfallgebühren Nachberechnung Restabfall 2025")])
    bedeutung.berechnen(con, "", "embeddinggemma")
    assert len(bedeutung.suche(con, frage, "embeddinggemma", anzahl=4, schluessel="a")) == 2


def test_suche_je_dokument_nur_die_beste_seite(tmp_path, ollama):
    konfig = h.konfig_fuer(tmp_path)
    con = db.verbinde(konfig.db_datei)
    db.init(con)
    db.speichere(con, _dok("/ablage/Police.pdf"), [(1, "text", KFZ), (2, "text", KFZ + " Kraftfahrtversicherung")])
    bedeutung.berechnen(con, "", "embeddinggemma")
    treffer = bedeutung.suche(con, _frage("Autoversicherung"), "embeddinggemma", anzahl=4)
    con.close()
    assert len(treffer) == 1


# --------------------------------------------------------------------------- Suchindex und Chat

def test_suchindex_liefert_treffer_in_der_form_der_wortsuche(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    treffer = Suchindex(konfig).bedeutung_suche("Was hat die neue Brille gekostet?")
    assert [t["name"] for t in treffer] == ["Scan_002.pdf"]
    assert treffer[0]["stellen"] == [{"seite": 1, "quelle": "bedeutung", "text": ""}]
    assert Suchindex(konfig).bedeutung_stand() == {"seiten": 5, "fertig": 4}

    daten = bedeutung_suchen(Suchindex(konfig), "Was hat die neue Brille gekostet?")
    assert daten[0]["filename"] == "Scan_002.pdf" and daten[0]["seite"] == 1 and OPTIK in daten[0]["extracted_text"]


def test_suchindex_ausgeschaltet_fragt_ollama_nicht(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    ollama.anfragen.clear()
    konfig.bedeutung_aktiv = False
    assert Suchindex(konfig).bedeutung_suche("Brille") == []
    assert ollama.anfragen == []


def test_suchindex_ohne_vorbereitete_seiten_fragt_ollama_nicht(index, ollama):
    konfig, con = index
    assert Suchindex(konfig).bedeutung_suche("Brille") == []
    assert ollama.anfragen == []


def test_suchindex_ohne_ollama_bleibt_leer(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    ollama.fehler = "Verbindung abgelehnt"
    assert Suchindex(konfig).bedeutung_suche("Brille") == []
    assert bedeutung_suchen(object(), "Brille") == []


def test_chat_suche_stellt_bedeutungstreffer_vor_die_worttreffer(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    dienst = RetrievalService(PdfsmDaten(Suchindex(konfig), None))

    # "Rechnung" steht woertlich nur beim Optiker; gemeint ist die Autoversicherung
    docs = dienst.retrieve("Rechnung für die Autoversicherung")

    assert [d.filename for d in docs] == ["Scan_001.pdf", "Scan_002.pdf"]
    assert docs[0].seite == 2 and "Kraftfahrtversicherung" in docs[0].text_snippet
    assert [d.index for d in docs] == [1, 2]
    # ohne Worttreffer bleibt der Bedeutungstreffer
    assert [d.filename for d in dienst.retrieve("Müllabfuhr")] == ["Scan_003.pdf"]
    # ein Dokument, das beide Suchen finden, steht nur einmal da
    assert [d.filename for d in dienst.retrieve("Gleitsichtgläser Brille")] == ["Scan_002.pdf"]


def test_chat_suche_ohne_bedeutung_wie_bisher(index, ollama):
    konfig, con = index
    bedeutung.berechnen(con, "", "embeddinggemma")
    dienst = RetrievalService(PdfsmDaten(Suchindex(konfig), None))
    ollama.anfragen.clear()
    assert dienst.retrieve("Müllabfuhr", bedeutung=False) == []
    assert ollama.anfragen == []
    konfig.bedeutung_aktiv = False
    assert dienst.retrieve("Müllabfuhr") == []


# --------------------------------------------------------------------------- Indexlauf und Einstellungen

@pytest.fixture
def ablage(tmp_path):
    ordner = tmp_path / "Ablage"
    ordner.mkdir()
    (ordner / "Police.md").write_text(KFZ, encoding="utf-8")
    (ordner / "Optiker.md").write_text(OPTIK, encoding="utf-8")
    return ordner


def test_indexlauf_bereitet_neue_seiten_vor(tmp_path, ablage, ollama):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], bedeutung_aktiv=True)
    ix = Indexer(konfig, synchron=True)
    assert ix.lauf() == 0
    assert ix.stat["bedeutung_seiten"] == 2
    assert [t["name"] for t in Suchindex(konfig).bedeutung_suche("Autoversicherung")] == ["Police.md"]

    # geaenderte Datei: der naechste Lauf rechnet nur diese Seite neu
    (ablage / "Optiker.md").write_text(OPTIK + " zuzüglich Etui", encoding="utf-8")
    ix = Indexer(konfig, synchron=True)
    assert ix.lauf() == 0
    assert ix.stat["bedeutung_seiten"] == 1


def test_kurzer_lauf_rechnet_nur_die_neuesten_seiten(tmp_path, ablage, ollama, monkeypatch):
    monkeypatch.setattr(bedeutung, "STAPEL", 1)
    monkeypatch.setattr(bedeutung, "KURZLAUF_SEITEN", 1)
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], bedeutung_aktiv=True)
    ix = Indexer(konfig, synchron=True)
    assert ix.lauf(nur_pfad=str(ablage)) == 0
    assert ix.stat["bedeutung_seiten"] == 1
    # der volle Lauf holt den Rest nach
    ix = Indexer(konfig, synchron=True)
    assert ix.lauf() == 0
    assert ix.stat["bedeutung_seiten"] == 1
    assert Suchindex(konfig).bedeutung_stand() == {"seiten": 2, "fertig": 2}


def test_indexlauf_ohne_schalter_legt_nichts_an(tmp_path, ablage, ollama):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)])
    assert Indexer(konfig, synchron=True).lauf() == 0
    con = db.verbinde(konfig.db_datei, nur_lesen=True)
    try:
        assert not bedeutung.vorhanden(con)
    finally:
        con.close()
    assert ollama.anfragen == []


@pytest.mark.parametrize("modelle,fehler", [(["gemma4:12b"], ""), ([], "nicht erreichbar")])
def test_indexlauf_ohne_modell_oder_ollama_wird_trotzdem_fertig(tmp_path, ablage, ollama, modelle, fehler):
    ollama.modelle, ollama.fehler = modelle, fehler
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], bedeutung_aktiv=True)
    ix = Indexer(konfig, synchron=True)
    assert ix.lauf() == 0
    assert "bedeutung_seiten" not in ix.stat
    assert Suchindex(konfig).bedeutung_stand() == {"seiten": 2, "fertig": 0}


def test_indexlauf_ollama_faellt_mittendrin_aus(tmp_path, ablage, ollama, monkeypatch):
    konfig = h.konfig_fuer(tmp_path, wurzeln=[str(ablage)], bedeutung_aktiv=True)
    echt = bedeutung._anfrage

    def anfrage(url, pfad, daten, zeitlimit):
        if pfad == "/api/embed":
            raise bedeutung.BedeutungFehler("Ollama: model runner has unexpectedly stopped")
        return echt(url, pfad, daten, zeitlimit)

    monkeypatch.setattr(bedeutung, "_anfrage", anfrage)
    assert Indexer(konfig, synchron=True).lauf() == 0


def test_einstellungen_ueberstehen_das_speichern():
    konfig = SearchConfig(bedeutung_aktiv=True, bedeutung_modell="bge-m3", bedeutung_url="http://rechner:11434")
    neu = SearchConfig.aus_dict(konfig.als_dict())
    assert (neu.bedeutung_aktiv, neu.bedeutung_modell, neu.bedeutung_url) == (True, "bge-m3", "http://rechner:11434")
    standard = SearchConfig.aus_dict({})
    assert (standard.bedeutung_aktiv, standard.bedeutung_modell, standard.bedeutung_url) == (False, "embeddinggemma", "")
