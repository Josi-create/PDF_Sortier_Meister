"""RetrievalService seit Issue #166/#167: Fragewoerter, Dateityp-Hinweis, Reihenfolge, Kennungen, Auszuege."""
from src.rag.bezug import Kennung
from src.rag.retrieval import RetrievalService
from src.utils.config import ChatConfig
from src.utils.database import Database
from tests import helfer_suche as h


class _SpyDB:
    """search_documents mit festen bzw. berechneten Antworten; merkt sich die Aufrufe."""

    def __init__(self, antwort=None):
        self.calls = []
        self._antwort = antwort

    def search_documents(self, query, limit=50, **filters):
        self.calls.append((query, limit, dict(filters)))
        if callable(self._antwort):
            return self._antwort(query, filters)
        return list((self._antwort or {}).get(query, []))


def _zeile(pfad, name, rang=-5.0, datum=0, groesse=100, **rest):
    return {"file_path": pfad, "filename": name, "rang": rang, "datum": datum, "groesse": groesse,
            "text_snippet": "", **rest}


def test_fragewoerter_tragen_nicht_zur_abfrage_bei():
    db = _SpyDB()
    RetrievalService(db).retrieve("Bitte zeig mir die Dokumente: in welchen Ordner gehört diese Stromrechnung?")
    query = db.calls[0][0]
    assert query == '"Stromrechnung"*'


def test_dateityp_hinweis_loest_zweite_suche_im_typ_aus():
    db = _SpyDB()
    RetrievalService(db).retrieve("Bitte die Vertragsnummer in der Excel Tabelle Zählerstände nachschlagen", k=4)
    assert len(db.calls) == 2
    (q1, limit1, f1), (q2, limit2, f2) = db.calls
    assert q1 == q2 == '"Vertragsnummer"* OR "Zählerstände"*'
    assert f1 == {} and f2 == {"typ": "office"}
    assert limit1 >= 12 and limit2 == 4

    db = _SpyDB()
    RetrievalService(db).retrieve("Gibt es eine Mail von Immergrün dazu?")
    assert db.calls[1][2] == {"typ": "mail"} and db.calls[0][0] == '"Immergrün"*'


def test_typtreffer_vorn_kopien_einmal_neuere_bei_gleicher_relevanz_zuerst():
    xlsx = _zeile("/a/Zählerübersicht.xlsx", "Zählerübersicht.xlsx", rang=-5.2, datum=2000, groesse=10)

    def antwort(query, filters):
        if filters.get("typ") == "office":
            return [xlsx]
        return [
            _zeile("/x/alt.pdf", "alt.pdf", rang=-9.0, datum=100, groesse=55),
            _zeile("/kopie/alt.pdf", "alt.pdf", rang=-9.0, datum=100, groesse=55),
            _zeile("/y/neu.pdf", "neu.pdf", rang=-8.8, datum=900, groesse=77),
            dict(xlsx),
        ]

    docs = RetrievalService(_SpyDB(antwort)).retrieve("Excel Zählerstände", k=8)
    assert [d.filename for d in docs] == ["Zählerübersicht.xlsx", "neu.pdf", "alt.pdf"]
    assert [d.index for d in docs] == [1, 2, 3]


def test_ohne_rang_und_datum_bleibt_die_reihenfolge():
    db = _SpyDB({'"Strom"*': [{"file_path": "/1.pdf", "filename": "1.pdf"}, {"file_path": "/2.pdf", "filename": "2.pdf"}]})
    docs = RetrievalService(db).retrieve("Strom")
    assert [d.filename for d in docs] == ["1.pdf", "2.pdf"]


def test_k_begrenzt_das_ergebnis_nach_dem_sortieren():
    zeilen = [_zeile(f"/{i}.pdf", f"{i}.pdf", rang=-float(i), groesse=i + 1) for i in range(1, 30)]
    docs = RetrievalService(_SpyDB(lambda q, f: list(zeilen))).retrieve("Strom", k=3)
    assert len(docs) == 3 and docs[0].filename == "29.pdf"


def test_retrieve_kennungen_phrasen_reihenfolge_und_ausschluss():
    bezug = "/eingang/G1.pdf"
    antwort = {
        '"G1"': [_zeile(bezug, "G1.pdf"), _zeile("/a/abrechnung.pdf", "abrechnung.pdf"),
                 _zeile("/m/mail.eml", "mail.eml")],
        '"R26 31"': [_zeile("/a/abrechnung.pdf", "abrechnung.pdf")],
        '"226541"': [],
    }
    db = _SpyDB(antwort)
    kennungen = [Kennung("G1", "Vertragsnummer"), Kennung("R26-31", "Rechnungsnummer"), Kennung("226541", "Zählernummer")]
    docs = RetrievalService(db).retrieve_kennungen(kennungen, k_je=3, ausser=bezug)

    assert [q for q, _l, _f in db.calls] == ['"G1"', '"R26 31"', '"226541"']
    # Zwei mehr als k_je, weil der Bezug selbst (und seine Kopie) meist vorn stehen
    assert all(limit == 5 and filters == {} for _q, limit, filters in db.calls)
    assert [d.filename for d in docs] == ["abrechnung.pdf", "mail.eml"]
    assert docs[0].extra["gemeinsame_kennungen"] == ["G1 (Vertragsnummer)", "R26-31 (Rechnungsnummer)"]
    assert docs[1].extra["gemeinsame_kennungen"] == ["G1 (Vertragsnummer)"]
    assert [d.index for d in docs] == [1, 2]

    assert [d.filename for d in RetrievalService(_SpyDB(antwort)).retrieve_kennungen(kennungen, limit=1, ausser=bezug)] == ["abrechnung.pdf"]
    assert RetrievalService(_SpyDB(antwort)).retrieve_kennungen([]) == []


def test_retrieve_kennungen_bezug_verdraengt_keinen_treffer_und_k_je_gilt_danach():
    bezug = "/eingang/G1.pdf"
    antwort = {'"G1"': [_zeile(bezug, "G1.pdf"), _zeile("/kopie/G1.pdf", "G1.pdf", groesse=100),
                        _zeile("/a/abrechnung.pdf", "abrechnung.pdf"), _zeile("/b/vertrag.pdf", "vertrag.pdf"),
                        _zeile("/c/mail.eml", "mail.eml")]}
    docs = RetrievalService(_SpyDB(antwort)).retrieve_kennungen([Kennung("G1", "Vertragsnummer")], k_je=3, ausser=bezug)
    # Der Bezug faellt heraus, seine Kopie zaehlt als eigener Treffer (gleicher Name, anderer Ort)
    assert [d.filename for d in docs] == ["G1.pdf", "abrechnung.pdf", "vertrag.pdf"]


def test_benannte_kennungen_wiegen_mehr_als_allgemeine():
    antwort = {
        '"102538"': [_zeile("/m/portal.eml", "portal.eml", typ="mail", datum=1)],
        '"DE212755674"': [_zeile("/m/portal.eml", "portal.eml", typ="mail", datum=1)],
        '"G1"': [_zeile("/a/abrechnung.pdf", "abrechnung.pdf")],
    }
    kennungen = [Kennung("102538"), Kennung("DE212755674"), Kennung("G1", "Vertragsnummer")]
    docs = RetrievalService(_SpyDB(antwort)).retrieve_kennungen(kennungen)
    # Zwei allgemeine Kennungen (HRB, USt-IdNr) schlagen eine Vertragsnummer nicht
    assert [d.filename for d in docs] == ["abrechnung.pdf", "portal.eml"]


def test_mail_kopien_gleicher_betreff_und_datum_nur_einmal():
    zeilen = [
        _zeile("/inbox#1", "Ihre Rechnung", typ="mail", datum=1000, groesse=99),
        _zeile("/alle#7", "Ihre Rechnung", typ="mail", datum=1000, groesse=99),   # Kopie in "Alle Nachrichten"
        _zeile("/inbox#2", "Ihre Rechnung", typ="mail", datum=2000, groesse=99),  # naechster Monat, gleicher Betreff
    ]
    docs = RetrievalService(_SpyDB(lambda q, f: list(zeilen))).retrieve("Rechnung")
    assert [d.file_path for d in docs] == ["/inbox#2", "/inbox#1"]  # neuere zuerst, Kopie weg


def test_aeltere_db_ohne_typ_parameter_faellt_zurueck():
    class _AlteDB:
        def __init__(self):
            self.calls = []

        def search_documents(self, query, limit=50, steuerjahr="", kategorie="", korrespondent=""):
            self.calls.append((query, limit))
            return [{"file_path": "/a.pdf", "filename": "a.pdf", "text_snippet": "Treffer"}]

    db = _AlteDB()
    docs = RetrievalService(db).retrieve("Excel Zählerstände 2024")
    assert docs and docs[0].filename == "a.pdf"
    assert db.calls  # kein TypeError nach aussen


class _FakeIndex:
    def __init__(self, seiten):
        self._seiten = seiten
        self.calls = []

    def seiten_text(self, dok_id, von=None, bis=None, hervorheben=None):
        self.calls.append((dok_id, von, bis))
        return [{"seite": s, "quelle": "text", "text": t} for s, t in self._seiten.items() if von <= s <= bis]


class _DBMitIndex:
    def __init__(self, suchindex):
        self.suchindex = suchindex

    def search_documents(self, query, limit=50, **filters):
        return [{"file_path": "/a.pdf", "filename": "a.pdf", "dok_id": 7, "seite": 2, "typ": "pdf",
                 "text_snippet": "… >>>Stromrechnung<<< 142,30 …", "extracted_text": "Erste Seite\fZweite Seite"}]


def test_auszug_aus_fundstellen_und_trefferseite():
    index = _FakeIndex({1: "Erste Seite ohne Treffer", 2: "Zweite Seite mit Stromrechnung 142,30 EUR"})
    docs = RetrievalService(_DBMitIndex(index), ChatConfig()).retrieve("Stromrechnung")
    text = docs[0].text_snippet
    assert text.startswith("Fundstellen (markiert mit >>> <<<): … >>>Stromrechnung<<< 142,30 …")
    assert "--- Seite 2 ---\nZweite Seite mit Stromrechnung 142,30 EUR" in text
    assert "Erste Seite" not in text
    assert index.calls == [(7, 2, 2)]


def test_auszug_wird_auf_das_budget_gekuerzt():
    index = _FakeIndex({2: "x" * 5000})
    docs = RetrievalService(_DBMitIndex(index), ChatConfig(snippet_max_chars=600)).retrieve("Stromrechnung")
    text = docs[0].text_snippet
    assert text.endswith("[... gekürzt]") and len(text) <= 620


def test_auszug_ohne_index_wie_bisher():
    docs = RetrievalService(_DBMitIndex(suchindex=None), ChatConfig()).retrieve("Stromrechnung")
    assert docs[0].text_snippet == "Erste Seite\fZweite Seite"


def test_blatt_statt_seite_bei_tabellen():
    class _DBOffice(_DBMitIndex):
        def search_documents(self, query, limit=50, **filters):
            return [{"file_path": "/z.xlsx", "filename": "z.xlsx", "dok_id": 3, "seite": 2, "typ": "office",
                     "format": "xlsx", "text_snippet": ">>>Zählerstände<<<"}]

    docs = RetrievalService(_DBOffice(_FakeIndex({2: "Tabellenblatt: Zählerstände"}))).retrieve("Zählerstände")
    assert "--- Blatt 2 ---\nTabellenblatt: Zählerstände" in docs[0].text_snippet


def test_echte_datenbank_liefert_typ_datum_rang_und_seitentext(tmp_path):
    db = Database(tmp_path / "t.db")
    pdf = h.pdf_mit_text(tmp_path / "strom.pdf", ["Erste Seite ohne Treffer", "Zweite Seite mit Stromrechnung 142,30"])
    db.index_document(str(pdf), "strom.pdf", korrespondent="Stadtwerke", kategorie="Rechnung", steuerjahr="2023")

    raw = db.search_documents("Stromrechnung")
    assert raw[0]["typ"] == "pdf" and raw[0]["format"] == "pdf"
    assert raw[0]["groesse"] and raw[0]["datum"] and raw[0]["rang"] is not None
    assert db.search_documents("Stromrechnung", typ="office") == []
    assert db.search_documents("Stromrechnung", typ="pdf,office")[0]["filename"] == "strom.pdf"

    docs = RetrievalService(db, ChatConfig()).retrieve("Stromrechnung")
    assert docs[0].seite == 2
    assert "--- Seite 2 ---" in docs[0].text_snippet and "Stromrechnung" in docs[0].text_snippet
    assert "Erste Seite" not in docs[0].text_snippet
