"""Konsolenprogramm ``pdfsm-dienst`` der Dokumentensuche (Qt-frei).

  pdfsm-dienst index [--nur-prioritaet] [--ohne-ocr] [--ohne-mail] [--pfad ORDNER] [--hintergrund]
                     [--nur-leerlauf] [--max-minuten N]
  pdfsm-dienst suche "Unterhalt UND 2019" [--typ pdf] [--ordner X] [--von 2019-01-01] [--bis ...] [-n 20] [--json]
  pdfsm-dienst lesen 1234 [--seiten 2-5]
  pdfsm-dienst status
  pdfsm-dienst web [--port N] [--nicht-oeffnen]
  pdfsm-dienst mcp
  pdfsm-dienst migration [--von ORDNER] [--kopieren] [--ja]
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
import multiprocessing
import re
import sys
from pathlib import Path

from src.search import ausgabe, konfig as konfig_modul
from src.search.suchindex import Suchindex


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
                                description="PDF Sortier Meister – Dokumentensuche (Indexierung, MCP, Web, Kommandozeile)")
    p.add_argument("--config", help="andere config.json oder eine config.toml von PDFsuche")
    p.add_argument("--version", action="version", version=f"pdfsm-dienst {version()}")
    sub = p.add_subparsers(dest="befehl", required=True)

    s = sub.add_parser("suche", help="Volltextsuche")
    s.add_argument("abfrage", nargs="+")
    s.add_argument("--typ", help="pdf, office, md, mail (mehrere mit Komma)")
    s.add_argument("--ordner", help="Teil des Pfads/Postfachs")
    s.add_argument("--von", help="ab Datum (JJJJ-MM-TT)")
    s.add_argument("--bis", help="bis Datum (JJJJ-MM-TT)")
    s.add_argument("--sort", choices=["relevanz", "neu", "alt"], default="relevanz")
    s.add_argument("--steuerjahr", help="PDFSM-Metadaten: Steuerjahr, z. B. 2024")
    s.add_argument("--kategorie", help="PDFSM-Metadaten: Kategorie, z. B. Rechnung")
    s.add_argument("--korrespondent", help="PDFSM-Metadaten: Korrespondent, z. B. Telekom")
    s.add_argument("-n", "--anzahl", type=int, default=20)
    s.add_argument("--json", action="store_true")

    lesen = sub.add_parser("lesen", help="Text eines Dokuments ausgeben")
    lesen.add_argument("id", type=int)
    lesen.add_argument("--seiten", help="z. B. 3 oder 2-5")
    lesen.add_argument("--max", type=int, default=0, help="höchstens so viele Zeichen")

    sub.add_parser("status", help="Indexstand anzeigen")

    i = sub.add_parser("index", help="Indexierungslauf starten")
    i.add_argument("--nur-prioritaet", action="store_true", help="nur die Vorrang-Ordner")
    i.add_argument("--ohne-ocr", action="store_true")
    i.add_argument("--ohne-mail", action="store_true")
    i.add_argument("--pfad", help="nur diesen Ordner indizieren")
    i.add_argument("--hintergrund", action="store_true", help="niedrige Priorität, keine Konsolenausgabe")
    i.add_argument("--nur-leerlauf", action="store_true",
                   help="pausieren, solange der Nutzer aktiv ist (für Zeitpläne ohne Leerlaufbedingung, z. B. macOS)")
    i.add_argument("--max-minuten", type=float, default=0)

    w = sub.add_parser("web", help="Browser-Oberfläche starten")
    w.add_argument("--port", type=int)
    w.add_argument("--nicht-oeffnen", action="store_true")

    sub.add_parser("mcp", help="MCP-Server (stdio) für KI-Assistenten starten")

    m = sub.add_parser("migration", help="vorhandene PDFsuche übernehmen (Einstellungen und Datenbank)")
    m.add_argument("--von", help="Projektordner der PDFsuche (mit config.toml); ohne Angabe wird gesucht")
    m.add_argument("--kopieren", action="store_true",
                   help="Datenbank in das Datenverzeichnis kopieren statt sie am bisherigen Ort zu lassen")
    m.add_argument("--ja", action="store_true", help="ohne Rückfrage übernehmen (sonst nur Vorschau)")
    return p


def _migration(a) -> int:
    """``pdfsm-dienst migration``: Vorschau, mit ``--ja`` Uebernahme in die config.json von PDF Sortier Meister."""
    from src.search import migration
    from src.utils.config import Config, get_config

    cfg = Config(a.config) if a.config and not str(a.config).lower().endswith(".toml") else get_config()
    ordner = a.von
    if not ordner:
        kandidaten = migration.finde_pdfsuche()
        if not kandidaten:
            print("Keine PDFsuche gefunden – Projektordner mit --von ORDNER angeben.")
            return 1
        ordner = kandidaten[0]
        if len(kandidaten) > 1:
            print("Mehrere Kandidaten, der erste wird geprüft: " + ", ".join(kandidaten))
    u = migration.pruefen(ordner)
    print(u.zusammenfassung())
    if not u.moeglich:
        return 1
    if not a.ja:
        print("\nVorschau – zum Übernehmen erneut mit --ja aufrufen"
              + (" (Datenbank wird kopiert)." if a.kopieren else " (Datenbank bleibt am Ort)."))
        return 0

    def fortschritt(kopiert, gesamt):
        if gesamt:
            print(f"\rKopiere Datenbank … {kopiert * 100 // gesamt} %", end="", flush=True)

    konfig = migration.uebernehmen(u, cfg, kopieren=a.kopieren, fortschritt=fortschritt)
    if a.kopieren:
        print()
    print(f"Übernommen. Datenbank: {konfig.db_datei}\nEinstellungen gespeichert in {cfg.config_path}")
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
    konfig = konfig_modul.lade(a.config)

    if a.befehl == "index":
        from src.search.indexer import Indexer, logging_einrichten
        logging_einrichten(konfig, konsole=not a.hintergrund)
        indexer = Indexer(konfig, hintergrund=a.hintergrund, max_minuten=a.max_minuten, nur_leerlauf=a.nur_leerlauf)
        return indexer.lauf(nur_prioritaet=a.nur_prioritaet, ohne_ocr=a.ohne_ocr, ohne_mail=a.ohne_mail,
                            nur_pfad=a.pfad)

    if a.befehl == "web":
        from src.search import web
        web.starte(konfig, port=a.port, oeffnen=not a.nicht_oeffnen)
        return 0

    if a.befehl == "mcp":
        from src.search import mcp_server
        return mcp_server.main(konfig)

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
