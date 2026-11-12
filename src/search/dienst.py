"""Konsolenprogramm ``pdfsm-dienst`` der Dokumentensuche (Qt-frei).

  pdfsm-dienst index [--nur-prioritaet] [--ohne-ocr] [--ohne-mail] [--pfad ORDNER] [--hintergrund]
                     [--nur-leerlauf] [--einmal-taeglich] [--max-minuten N]
  pdfsm-dienst suche "Unterhalt UND 2019" [--typ pdf] [--ordner X] [--von 2019-01-01] [--bis ...] [-n 20] [--json]
  pdfsm-dienst lesen 1234 [--seiten 2-5]
  pdfsm-dienst status
  pdfsm-dienst web [--port N] [--nicht-oeffnen]
  pdfsm-dienst mcp
  pdfsm-dienst migration [--von ORDNER] [--kopieren] [--ja]
  pdfsm-dienst textebene schaetzen | protokoll [-n 50] | rueckgaengig ID [--erzwingen]
                         | schreiben [--max-minuten N] [--hintergrund]
  pdfsm-dienst zeitplan --einrichten | --entfernen | --status
  pdfsm-dienst --version

Die Konfiguration kommt aus der ``config.json`` von PDF Sortier Meister (Block
``"suche"``); ``--config`` nimmt eine andere ``config.json`` oder eine
``config.toml`` des frueheren Programms PDFsuche. Entwicklung:
``python -m src.search.dienst ...``; im gebauten Programm ``pdfsm-dienst.exe``
(mit Konsole, fuer MCP und Kommandozeile) bzw. ``pdfsm-dienstw.exe`` (ohne).
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import re
import sys
from pathlib import Path

from src.search import ausgabe, konfig as konfig_modul
from src.search.suchindex import Suchindex
from src.i18n import tr


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def version() -> str:
    """Programmversion aus ``src/main.py`` (dort zentral gepflegt), ohne das Modul zu importieren."""
    try:
        text = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "0.0.0"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdfsm-dienst",
                                description=tr("PDF Sortier Meister – Dokumentensuche (Indexierung, MCP, Web, Kommandozeile)"))
    p.add_argument("--config", help=tr("andere config.json oder eine config.toml von PDFsuche"))
    p.add_argument("--version", action="version", version=f"pdfsm-dienst {version()}")
    sub = p.add_subparsers(dest="befehl", required=True)

    s = sub.add_parser("suche", help=tr("Volltextsuche"))
    s.add_argument("abfrage", nargs="+")
    s.add_argument("--typ", help=tr("pdf, office, md, mail (mehrere mit Komma)"))
    s.add_argument("--ordner", help=tr("Teil des Pfads/Postfachs"))
    s.add_argument("--von", help=tr("ab Datum (JJJJ-MM-TT)"))
    s.add_argument("--bis", help=tr("bis Datum (JJJJ-MM-TT)"))
    s.add_argument("--sort", choices=["relevanz", "neu", "alt"], default="relevanz")
    s.add_argument("--steuerjahr", help=tr("PDFSM-Metadaten: Steuerjahr, z. B. 2024"))
    s.add_argument("--kategorie", help=tr("PDFSM-Metadaten: Kategorie, z. B. Rechnung"))
    s.add_argument("--korrespondent", help=tr("PDFSM-Metadaten: Korrespondent, z. B. Telekom"))
    s.add_argument("-n", "--anzahl", type=int, default=20)
    s.add_argument("--json", action="store_true")

    lesen = sub.add_parser("lesen", help=tr("Text eines Dokuments ausgeben"))
    lesen.add_argument("id", type=int)
    lesen.add_argument("--seiten", help=tr("z. B. 3 oder 2-5"))
    lesen.add_argument("--max", type=int, default=0, help=tr("höchstens so viele Zeichen"))

    sub.add_parser("status", help=tr("Indexstand anzeigen"))

    i = sub.add_parser("index", help=tr("Indexierungslauf starten"))
    i.add_argument("--nur-prioritaet", action="store_true", help=tr("nur die Vorrang-Ordner"))
    i.add_argument("--ohne-ocr", action="store_true")
    i.add_argument("--ohne-mail", action="store_true")
    i.add_argument("--pfad", help=tr("nur diesen Ordner indizieren"))
    i.add_argument("--hintergrund", action="store_true", help=tr("niedrige Priorität, keine Konsolenausgabe"))
    i.add_argument("--nur-leerlauf", action="store_true",
                   help=tr("pausieren, solange der Nutzer aktiv ist (für Zeitpläne ohne Leerlaufbedingung, z. B. macOS)"))
    i.add_argument("--einmal-taeglich", action="store_true",
                   help=tr("nichts tun, wenn heute schon ein vollständiger Lauf fertig wurde (Start bei der Anmeldung)"))
    i.add_argument("--max-minuten", type=float, default=0)

    w = sub.add_parser("web", help=tr("Browser-Oberfläche starten"))
    w.add_argument("--port", type=int)
    w.add_argument("--nicht-oeffnen", action="store_true")

    sub.add_parser("mcp", help=tr("MCP-Server (stdio) für KI-Assistenten starten"))

    m = sub.add_parser("migration", help=tr("vorhandene PDFsuche übernehmen (Einstellungen und Datenbank)"))
    m.add_argument("--von", help=tr("Projektordner der PDFsuche (mit config.toml); ohne Angabe wird gesucht"))
    m.add_argument("--kopieren", action="store_true",
                   help=tr("Datenbank in das Datenverzeichnis kopieren statt sie am bisherigen Ort zu lassen"))
    m.add_argument("--ja", action="store_true", help=tr("ohne Rückfrage übernehmen (sonst nur Vorschau)"))

    t = sub.add_parser("textebene", help=tr("unsichtbare OCR-Textebene in gescannten PDFs (Schätzung, Protokoll, "
                                            "Rückgängig, Schreiben)"))
    tsub = t.add_subparsers(dest="aktion", required=True)
    tsub.add_parser("schaetzen", help=tr("Aufwand für den Altbestand (Stufe „alle“) schätzen"))
    tp = tsub.add_parser("protokoll", help=tr("geänderte Dateien anzeigen"))
    tp.add_argument("-n", "--anzahl", type=int, default=50)
    tz = tsub.add_parser("rueckgaengig", help=tr("eine Änderung zurücknehmen (Nummer aus dem Protokoll)"))
    tz.add_argument("id", type=int)
    tz.add_argument("--erzwingen", action="store_true",
                    help=tr("auch wenn die Datei seither geändert wurde (diese Änderung geht verloren)"))
    ts = tsub.add_parser("schreiben", help=tr("nur die Textebene schreiben (Stufe aus den Einstellungen)"))
    ts.add_argument("--max-minuten", type=float, default=0)
    ts.add_argument("--hintergrund", action="store_true", help=tr("niedrige Priorität, keine Konsolenausgabe"))

    z = sub.add_parser("zeitplan", help=tr("Hintergrundindexierung und Web-Oberfläche bei Anmeldung "
                                           "(Aufgabenplanung bzw. LaunchAgent)"))
    za = z.add_mutually_exclusive_group(required=True)
    za.add_argument("--einrichten", action="store_true",
                    help=tr("nach den Einstellungen einrichten (Ausgeschaltetes wird entfernt)"))
    za.add_argument("--entfernen", action="store_true", help=tr("alles entfernen (z. B. beim Deinstallieren)"))
    za.add_argument("--status", action="store_true", help=tr("eingerichtete Einträge anzeigen"))
    return p


def _zeitplan(a) -> int:
    """``pdfsm-dienst zeitplan ...``; ``--entfernen`` braucht keine (lesbare) Konfiguration."""
    from src.search import zeitplan

    try:
        if a.entfernen:
            for zeile in zeitplan.entfernen() or ["Nichts eingerichtet."]:
                print(zeile)
            return 0
        if a.einrichten:
            konfig = konfig_modul.lade(a.config)
            konfig_pfad = a.config if a.config and not str(a.config).lower().endswith(".toml") else None
            for zeile in zeitplan.abgleichen(konfig, konfig_pfad=konfig_pfad) or ["Bereits wie eingestellt."]:
                print(zeile)
        print(zeitplan.zustand_text(zeitplan.zustand()))
    except zeitplan.ZeitplanFehler as e:
        print(e, file=sys.stderr)
        return 1
    return 0


def _textebene(a, konfig) -> int:
    """``pdfsm-dienst textebene ...``"""
    from src.search import textebene

    idx = Suchindex(konfig)
    if a.aktion == "schaetzen":
        print(tr("Stufe in den Einstellungen: {textebene}").format(textebene=konfig.textebene))
        print(textebene.schaetzung_text(idx.textebene_schaetzung()))
        return 0
    if a.aktion == "protokoll":
        eintraege = idx.textebene_protokoll(a.anzahl)
        if not eintraege:
            print(tr("Noch keine Datei mit Textebene versehen."))
            return 0
        for e in eintraege:
            pfad = e.get("aktueller_pfad") or e["pfad"]
            zusatz = tr("rückgängig gemacht") if e["status"] == "rueckgaengig" else (
                tr("Sicherung vorhanden") if e.get("sicherung") else tr("Sicherung abgelaufen"))
            gedreht = f"  gedreht {e['gedreht']}" if e.get("gedreht") else ""
            if e.get("gerade"):
                gedreht += f"  gerade {e['gerade']}"
            print(tr("[{id}] {am}  Seiten {0}{gedreht}  ({zusatz})  {pfad}").format(e['seiten'] or '-', id=e['id'], am=e['am'], gedreht=gedreht, zusatz=zusatz, pfad=pfad))
        return 0
    if a.aktion == "rueckgaengig":
        ok, meldung = idx.textebene_rueckgaengig(a.id, erzwingen=a.erzwingen)
        print(meldung)
        return 0 if ok else 1
    if konfig.textebene == "aus" and konfig.auto_drehen == "aus" and konfig.auto_gerade == "aus":
        print(tr("Textebene, automatisches Drehen und Ausrichten sind in den Einstellungen ausgeschaltet "
              "(Suche › Gescannte PDFs verbessern)."))
        return 1
    from src.search.indexer import Indexer, logging_einrichten
    logging_einrichten(konfig, konsole=not a.hintergrund)
    return Indexer(konfig, hintergrund=a.hintergrund, max_minuten=a.max_minuten).lauf(nur_textebene=True)


def _migration(a) -> int:
    """``pdfsm-dienst migration``: Vorschau, mit ``--ja`` Uebernahme in die config.json von PDF Sortier Meister."""
    from src.search import migration
    from src.utils.config import Config, get_config

    cfg = Config(a.config) if a.config and not str(a.config).lower().endswith(".toml") else get_config()
    ordner = a.von
    if not ordner:
        kandidaten = migration.finde_pdfsuche()
        if not kandidaten:
            print(tr("Keine PDFsuche gefunden – Projektordner mit --von ORDNER angeben."))
            return 1
        ordner = kandidaten[0]
        if len(kandidaten) > 1:
            print(tr("Mehrere Kandidaten, der erste wird geprüft: {0}").format(', '.join(kandidaten)))
    u = migration.pruefen(ordner)
    print(u.zusammenfassung())
    if not u.moeglich:
        return 1
    if not a.ja:
        print(tr("\nVorschau – zum Übernehmen erneut mit --ja aufrufen{0}").format(tr(" (Datenbank wird kopiert).") if a.kopieren else tr(" (Datenbank bleibt am Ort).")))
        return 0

    def fortschritt(kopiert, gesamt):
        if gesamt:
            print(tr("\rKopiere Datenbank … {0} %").format(kopiert * 100 // gesamt), end="", flush=True)

    konfig = migration.uebernehmen(u, cfg, kopieren=a.kopieren, fortschritt=fortschritt)
    if a.kopieren:
        print()
    print(tr("Übernommen. Datenbank: {db_datei}\nEinstellungen gespeichert in {config_path}").format(db_datei=konfig.db_datei, config_path=cfg.config_path))
    if u.mitgenommen:
        print(tr("PDFSM-Metadaten aus dem bisherigen Index mitgenommen: {mitgenommen} Dokumente").format(mitgenommen=u.mitgenommen))
    return 0


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    try:
        multiprocessing.set_start_method("spawn")
    except RuntimeError:
        pass  # bereits gesetzt (z. B. unter pytest)
    _utf8()
    a = parser().parse_args(argv)
    if a.befehl == "migration":
        return _migration(a)
    if a.befehl == "zeitplan":
        return _zeitplan(a)
    konfig = konfig_modul.lade(a.config)

    if a.befehl == "index":
        from src.search.indexer import Indexer, heute_schon_gelaufen, logging_einrichten
        logging_einrichten(konfig, konsole=not a.hintergrund)
        if a.einmal_taeglich and heute_schon_gelaufen(konfig):
            logging.getLogger("pdf_sortier_meister.suche").info("Heute lief schon ein vollständiger Lauf – Ende.")
            return 0
        indexer = Indexer(konfig, hintergrund=a.hintergrund, max_minuten=a.max_minuten, nur_leerlauf=a.nur_leerlauf)
        return indexer.lauf(nur_prioritaet=a.nur_prioritaet, ohne_ocr=a.ohne_ocr, ohne_mail=a.ohne_mail,
                            nur_pfad=a.pfad)

    if a.befehl == "web":
        from src.search import web
        web.starte(konfig, port=a.port, oeffnen=not a.nicht_oeffnen)
        return 0

    if a.befehl == "mcp":
        from src.search import mcp_server
        return mcp_server.main(konfig, a.config)

    if a.befehl == "textebene":
        return _textebene(a, konfig)

    idx = Suchindex(konfig)
    if a.befehl == "suche":
        abfrage = " ".join(a.abfrage)
        erg = idx.suche(abfrage, typ=a.typ, ordner=a.ordner, von=a.von, bis=a.bis, sortierung=a.sort, anzahl=a.anzahl,
                        steuerjahr=a.steuerjahr, kategorie=a.kategorie, korrespondent=a.korrespondent)
        if a.json:
            print(json.dumps(erg, ensure_ascii=False, indent=1, default=str))
        else:
            print(ausgabe.ergebnisse(erg, abfrage))
    elif a.befehl == "lesen":
        print(ausgabe.dokument_text(idx, a.id, a.seiten, a.max))
    elif a.befehl == "status":
        print(ausgabe.status_text(idx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
