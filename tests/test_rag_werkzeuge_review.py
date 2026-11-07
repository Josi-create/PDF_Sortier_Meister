"""Werkzeugkasten (Issue #166/#167, Phase 2): Befunde der Review - Kalenderdaten, Seitenbereich, SQL-Zeitlimit."""
from __future__ import annotations

import time

from src.ml.llm_provider import WerkzeugAufruf
from src.rag.werkzeuge import Werkzeugkasten, _datum_pruefen
from tests.test_rag_werkzeuge import (  # noqa: F401 - Fixture ``sammlung`` wird importiert
    JAHRESABRECHNUNG,
    _aufruf,
    _dok_id,
    _kasten,
    sammlung,
)


def test_datum_pruefen_formate_und_kalender():
    assert _datum_pruefen("2025-02-28", "von") == "2025-02-28"
    assert _datum_pruefen("28.02.2025", "von") == "2025-02-28"
    assert _datum_pruefen("2024", "bis") == "2024-01-01"
    for falsch in ("2025-02-30", "31.04.2025", "gestern", "2025-13-01", "20250101"):
        try:
            _datum_pruefen(falsch, "von")
        except Exception as e:  # noqa: BLE001 - _WerkzeugFehler ist modulintern
            assert "gültiges Datum" in str(e) and "von" in str(e)
        else:
            raise AssertionError(f"{falsch!r} wurde angenommen")


def test_suche_mit_unmoeglichem_datum_meldet_fehler_statt_keine_treffer(sammlung):
    kasten = _kasten(sammlung)
    text = _aufruf(kasten, "suche", abfrage="Stadtwerke", von="2025-02-30")
    assert text.startswith("Fehler: Argument „von“ muss ein gültiges Datum")
    assert kasten.protokoll[-1].fehler
    # Gueltiges Datum in deutscher Schreibweise wird angenommen
    text = _aufruf(kasten, "suche", abfrage="Stadtwerke", bis="31.12.2030")
    assert "Treffer für" in text


def test_suche_versteht_gaengige_typ_schreibweisen(sammlung):
    kasten = _kasten(sammlung)
    # "excel"/"word" -> office (keine Office-Dateien in der Sammlung: ehrlich keine Treffer, kein Fehler)
    text = _aufruf(kasten, "suche", abfrage="Stadtwerke", typ="Excel")
    assert text.startswith("Keine Treffer") and "typ=office" in text
    text = _aufruf(kasten, "suche", abfrage="Stadtwerke", typ="pdfs, E-Mail")
    assert "Treffer für" in text and "typ=pdf,mail" in text
    assert _aufruf(kasten, "suche", abfrage="Stadtwerke", typ="bild").startswith("Fehler: Unbekannter typ „bild“")


def test_registriere_kopiert_das_extra_dict():
    from src.rag.retrieval import RetrievedDoc

    original = RetrievedDoc(index=1, file_path="C:/a.pdf", filename="a.pdf", text_snippet="", rank=1,
                            extra={"bezug": True})
    kasten = Werkzeugkasten(None)
    kopie = kasten.registriere(original)
    kasten.markiere(1, "zitiert")
    assert kopie.extra["status"] == "zitiert" and kopie.extra["bezug"] is True
    assert "status" not in original.extra  # der Rueckfallweg ohne Werkzeuge sieht keinen Status


def test_erfundene_werkzeugnamen_werden_abgebildet(sammlung):
    kasten = _kasten(sammlung)
    text = kasten.ausfuehren(WerkzeugAufruf("abfrage", {"abfrage": "Stadtwerke"}))
    assert "Treffer für" in text and kasten.protokoll[-1].werkzeug == "suche"
    text = kasten.ausfuehren(WerkzeugAufruf("Lesen", {"dokument": "D1"}))
    assert text.startswith("[D1]") and kasten.protokoll[-1].werkzeug == "dokument_lesen"
    # SQL-Alias ohne Freigabe bleibt gesperrt, voellig Unbekanntes bleibt ein Fehler
    assert kasten.ausfuehren(WerkzeugAufruf("sql", {"sql": "SELECT 1"})).startswith("Fehler: SQL-Abfragen")
    assert kasten.ausfuehren(WerkzeugAufruf("zaubern", {})).startswith("Fehler: Unbekanntes Werkzeug „zaubern“")


def test_dokument_lesen_seiten_ausserhalb_des_dokuments(sammlung):
    db, bezug = sammlung
    kasten = _kasten(sammlung)
    _aufruf(kasten, "suche", abfrage="Jahresabrechnung")
    nummer = next(d.index for d in kasten.dokumente() if d.filename == JAHRESABRECHNUNG)
    text = _aufruf(kasten, "dokument_lesen", dokument=f"D{nummer}", seiten="7-9")
    assert text.startswith("Fehler: Seiten „7-9“ gibt es nicht") and "3 Seiten" in text
    # Innerhalb des Dokuments wie gehabt
    text = _aufruf(kasten, "dokument_lesen", dokument=f"D{nummer}", seiten="2")
    assert "Seite 2" in text and "Abnahmestelle" in text


def test_sql_zeitlimit_greift_auch_ohne_fortschritts_handler(sammlung, monkeypatch):
    """Der Timer-Thread ruft con.interrupt(): auch wenn der Handler (fast) nie prueft, endet die Abfrage."""
    monkeypatch.setattr(Werkzeugkasten, "SQL_HANDLER_SCHRITTE", 10**9)
    kasten = _kasten(sammlung, sql_erlaubt=True, sql_zeitlimit_s=0.3)
    t0 = time.monotonic()
    text = kasten.ausfuehren(WerkzeugAufruf("sql_abfrage", {
        "sql": "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c"}))
    assert text.startswith("Fehler: Zeitlimit von 0.3 s überschritten")
    assert time.monotonic() - t0 < 5


def test_sql_zweite_anweisung_hinter_kommentar_mit_apostroph(sammlung):
    """Ein Apostroph im Kommentar tarnt das ';' vor der Pruefung - SQLite selbst lehnt die zweite Anweisung ab."""
    kasten = _kasten(sammlung, sql_erlaubt=True)
    sql = "SELECT count(*) FROM dokumente -- Nutzer's Liste\n; SELECT 1"
    text = kasten.ausfuehren(WerkzeugAufruf("sql_abfrage", {"sql": sql}))
    assert text.startswith("Fehler:")
    # und eine Schreibanweisung dahinter erst recht nicht ausgefuehrt wird
    sql = "SELECT count(*) FROM dokumente -- Nutzer's Liste\n; DELETE FROM dokumente"
    text = kasten.ausfuehren(WerkzeugAufruf("sql_abfrage", {"sql": sql}))
    assert text.startswith("Fehler:")
    assert _aufruf(Werkzeugkasten(sammlung[0], sql_erlaubt=True), "sql_abfrage",
                   sql="SELECT count(*) AS n FROM dokumente").splitlines()[1].strip() == "3"
