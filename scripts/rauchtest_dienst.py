"""Rauchtest der gebauten Dienstprogramme der Dokumentensuche.

Aufruf nach dem PyInstaller-Build (``build.bat``, ``build.sh``, ``release.yml``):

  python scripts/rauchtest_dienst.py dist/PDF_Sortier_Meister                       (Windows)
  python scripts/rauchtest_dienst.py "dist/PDF Sortier Meister.app/Contents/MacOS"  (macOS)

Alles laeuft in einem Temp-Ordner mit eigener ``config.json``; ``APPDATA``
(Windows) bzw. ``HOME`` (macOS) zeigen fuer die Unterprozesse dorthin, damit
weder Einstellungen noch Index noch Protokolle des Nutzers beruehrt werden.
Die Testdokumente entstehen synthetisch.

Geprueft wird: ``--version``; ``status`` ohne Datenbank; ein vollstaendiger
Indexlauf mit zwei Arbeitsprozessen (spawn im eingefrorenen Programm) und, wenn
Tesseract mitgeliefert ist, OCR einer Bildseite; ``suche`` und ``lesen``;
MCP-Handshake mit den Werkzeugen ``suche``, ``dokument_lesen``,
``index_status``; dass ein schief gescannter neuer Scan gerade ausgerichtet
wird (Issue #165, braucht numpy im Arbeitsprozess); die Browser-Oberflaeche;
``zeitplan --status`` (nur lesend); unter Windows der Lauf ueber
``pdfsm-dienstw.exe`` ohne Konsole.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))

WOERTER = "Rauchtest Kontoauszug Zinsertrag"
BILD_WORT = "Quittung"
MCP_WERKZEUGE = {"suche", "dokument_lesen", "index_status", "ordner_vorschlag", "korrespondent_info"}


class Fehlschlag(Exception):  # noqa: N818 - deutscher Name wie Abbruch, ZeitplanFehler
    pass


def version() -> str:
    text = (WURZEL / "src" / "main.py").read_text(encoding="utf-8")
    return re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M).group(1)


def freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def dokumente_anlegen(ordner: Path) -> None:
    import pymupdf

    ordner.mkdir(parents=True)
    for i, text in enumerate([WOERTER, "Zweite Datei fuer den zweiten Arbeitsprozess", "Dritte Datei"]):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 100), text, fontsize=14)
        doc.save(ordner / f"text{i}.pdf")
        doc.close()
    (ordner / "notiz.md").write_text(f"# Notiz\n{WOERTER} in Markdown", encoding="utf-8")
    # Bildseite ohne Textebene: nur OCR findet das Wort
    quelle = pymupdf.open()
    seite = quelle.new_page()
    seite.insert_text((72, 120), f"{BILD_WORT} Nummer 4711", fontsize=28)
    png = seite.get_pixmap(dpi=200).tobytes("png")
    quelle.close()
    scan = pymupdf.open()
    scan.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=png)
    scan.save(ordner / "scan.pdf")
    scan.close()
    # Schief eingezogener Scan (2 Grad) mit Textebene des Scanprogramms (Issue #165)
    quelle = pymupdf.open()
    seite = quelle.new_page()
    for i in range(18):
        seite.insert_text((72, 120 + 24 * i), f"Abschlagsrechnung Stadtwerke Zeile {i + 1} Betrag {i * 37},50 EUR",
                          fontsize=12)
    pix = seite.get_pixmap(matrix=pymupdf.Matrix(100 / 72, 100 / 72).prerotate(2), colorspace=pymupdf.csGRAY)
    quelle.close()
    schief = pymupdf.open()
    s = schief.new_page(width=pix.width * 72 / 100, height=pix.height * 72 / 100)
    s.insert_image(s.rect, pixmap=pix)
    s.insert_text((72, 100), "Abschlagsrechnung Stadtwerke", fontsize=12, render_mode=3)
    schief.save(ordner / "schief.pdf")
    schief.close()


def konfig_schreiben(tmp: Path, dokumente: Path, port: int) -> Path:
    from src.search.konfig import SearchConfig

    k = SearchConfig(aktiv=True, db_pfad=str(tmp / "suche" / "suche.db"), wurzeln=[str(dokumente)],
                     prioritaet=[str(dokumente)], mails_aktiv=False, ocr_aktiv=True, prozesse=2, web_port=port,
                     textebene_sicherung_ordner=str(tmp / "sicherung"))
    pfad = tmp / "config.json"
    pfad.write_text(json.dumps({"suche": k.als_dict()}, ensure_ascii=False, indent=1), encoding="utf-8")
    return pfad


class Rauchtest:
    def __init__(self, ordner: Path):
        self.ordner = ordner
        endung = ".exe" if sys.platform == "win32" else ""
        self.dienst = ordner / f"pdfsm-dienst{endung}"
        self.dienstw = ordner / "pdfsm-dienstw.exe" if sys.platform == "win32" else None
        self.tmp = Path(tempfile.mkdtemp(prefix="pdfsm-rauchtest-"))
        self.env = dict(os.environ)
        if sys.platform == "win32":
            self.env["APPDATA"] = str(self.tmp / "appdata")
        else:
            self.env["HOME"] = str(self.tmp / "home")
        (self.tmp / "appdata").mkdir()
        (self.tmp / "home").mkdir()
        self.dokumente = self.tmp / "Dokumente"
        self.port = freier_port()
        self.cfg: Path | None = None

    def aufruf(self, *args, programm: Path | None = None, timeout: float = 120, ok: bool = True) -> str:
        befehl = [str(programm or self.dienst), *args]
        r = subprocess.run(befehl, capture_output=True, timeout=timeout, env=self.env, cwd=self.tmp)
        ausgabe = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        if ok and r.returncode != 0:
            raise Fehlschlag(f"{' '.join(args)}: Rückgabewert {r.returncode}\n{ausgabe}")
        return ausgabe

    def mit_konfig(self, *args, **kw) -> str:
        return self.aufruf("--config", str(self.cfg), *args, **kw)

    # ------------------------------------------------------------------ Schritte

    def programme_da(self) -> str:
        for p in (self.dienst, self.dienstw):
            if p is not None and not p.is_file():
                raise Fehlschlag(f"{p} fehlt")
        return "Programme vorhanden"

    def version_pruefen(self) -> str:
        aus = self.aufruf("--version")
        if version() not in aus:
            raise Fehlschlag(f"--version liefert {aus.strip()!r}, erwartet {version()}")
        return aus.strip()

    def status_leer(self) -> str:
        dokumente_anlegen(self.dokumente)
        self.cfg = konfig_schreiben(self.tmp, self.dokumente, self.port)
        aus = self.mit_konfig("status")
        if "noch nicht vorhanden" not in aus:
            raise Fehlschlag(f"status ohne Datenbank:\n{aus}")
        return "status ohne Datenbank"

    def indexlauf(self) -> str:
        t = time.monotonic()
        self.mit_konfig("index", timeout=600)
        aus = self.mit_konfig("status")
        if "Dokumente: 6" not in aus:
            raise Fehlschlag(f"nach dem Indexlauf:\n{aus}")
        self.ocr = "Texterkennung (OCR): aus" not in aus
        return f"Indexlauf mit Arbeitsprozessen ({time.monotonic() - t:.0f} s), OCR {'an' if self.ocr else 'aus'}"

    def suchen(self) -> str:
        erg = json.loads(self.mit_konfig("suche", "Zinsertrag", "--json"))
        if erg["gesamt"] != 2:
            raise Fehlschlag(f"suche Zinsertrag: {erg['gesamt']} statt 2 Treffer")
        dok = next(d for d in erg["treffer"] if d["typ"] == "pdf")
        if "Kontoauszug" not in self.mit_konfig("lesen", str(dok["id"])):
            raise Fehlschlag("lesen liefert den Text nicht")
        if self.ocr:
            ocr = json.loads(self.mit_konfig("suche", BILD_WORT, "--json"))
            if ocr["gesamt"] != 1:
                raise Fehlschlag(f"OCR: {BILD_WORT} {ocr['gesamt']} statt 1 Treffer")
        return "suche und lesen" + (", OCR-Treffer auf der Bildseite" if self.ocr else "")

    def ausrichten(self) -> str:
        import pymupdf

        from src.search import gerade

        with pymupdf.open(self.dokumente / "schief.pdf") as doc:
            winkel = gerade.ausrichtung(doc, doc[0])
        if not 1.5 < winkel < 2.5:
            raise Fehlschlag(f"schiefer Scan nicht gerade ausgerichtet (Winkel {winkel})")
        return f"schiefer Scan gerade ausgerichtet ({winkel:.1f}°)".replace(".", ",")

    def mcp(self) -> str:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def ablauf():
            params = StdioServerParameters(command=str(self.dienst), args=["--config", str(self.cfg), "mcp"],
                                           env=self.env, cwd=str(self.tmp))
            async with stdio_client(params) as (lesen, schreiben):
                async with ClientSession(lesen, schreiben) as sitzung:
                    await sitzung.initialize()
                    namen = {w.name for w in (await sitzung.list_tools()).tools}
                    erg = await sitzung.call_tool("suche", {"abfrage": "Zinsertrag"})
                    return namen, "".join(getattr(c, "text", "") for c in erg.content)

        t = time.monotonic()
        namen, text = asyncio.run(asyncio.wait_for(ablauf(), 90))
        if namen != MCP_WERKZEUGE:
            raise Fehlschlag(f"MCP-Werkzeuge {sorted(namen)}")
        if "text0.pdf" not in text:
            raise Fehlschlag(f"MCP-Suche ohne Treffer:\n{text}")
        return f"MCP-Handshake und Suche ({time.monotonic() - t:.1f} s)"

    def web(self) -> str:
        befehl = [str(self.dienst), "--config", str(self.cfg), "web", "--nicht-oeffnen"]
        p = subprocess.Popen(befehl, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=self.env, cwd=self.tmp)
        basis = f"http://127.0.0.1:{self.port}/"
        try:
            ende = time.monotonic() + 60
            while True:
                try:
                    with urllib.request.urlopen(basis + "api/status", timeout=2) as r:
                        status = json.loads(r.read())
                    break
                except OSError:
                    if p.poll() is not None or time.monotonic() > ende:
                        raise Fehlschlag("Browser-Oberfläche startet nicht:\n"
                                         + (p.stderr.read().decode("utf-8", "replace") if p.poll() is not None
                                            else "Zeitüberschreitung")) from None
                    time.sleep(0.5)
            with urllib.request.urlopen(basis + "api/suche?q=Zinsertrag", timeout=10) as r:
                treffer = json.loads(r.read())["gesamt"]
            with urllib.request.urlopen(basis, timeout=10) as r:
                seite = r.read().decode("utf-8", "replace")
        finally:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        if status.get("dokumente") != 6 or treffer != 2 or "<html" not in seite.lower():
            raise Fehlschlag(f"Browser-Oberfläche: dokumente={status.get('dokumente')}, treffer={treffer}")
        return "Browser-Oberfläche (Startseite, /api/status, /api/suche)"

    def zeitplan(self) -> str:
        aus = self.aufruf("zeitplan", "--status")
        if "Hintergrundindexierung" not in aus:
            raise Fehlschlag(f"zeitplan --status:\n{aus}")
        return "zeitplan --status (nur lesend)"

    def fensterlos(self) -> str:
        if self.dienstw is None:
            return "pdfsm-dienstw nur unter Windows"
        self.aufruf("--config", str(self.cfg), "index", "--hintergrund", programm=self.dienstw, timeout=600)
        self.aufruf("--config", str(self.cfg), "textebene", "schaetzen", programm=self.dienstw)
        return "pdfsm-dienstw.exe: Indexlauf und Schätzung ohne Konsole"

    def ausfuehren(self) -> int:
        schritte = [self.programme_da, self.version_pruefen, self.status_leer, self.indexlauf, self.suchen,
                    self.ausrichten, self.mcp, self.web, self.zeitplan, self.fensterlos]
        try:
            for schritt in schritte:
                print(f"OK  {schritt()}", flush=True)
        except Fehlschlag as e:
            print(f"FEHLER  {e}", flush=True)
            return 1
        except (OSError, subprocess.SubprocessError, TimeoutError) as e:
            print(f"FEHLER  {type(e).__name__}: {e}", flush=True)
            return 1
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)
        print("Rauchtest bestanden.")
        return 0


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    # Absolut: die Programme laufen mit dem Temp-Ordner als Arbeitsordner, und unter macOS/Linux
    # sucht subprocess einen relativen Programmpfad dann dort (Windows: im Arbeitsordner des Aufrufers)
    return Rauchtest(Path(sys.argv[1]).resolve()).ausfuehren()


if __name__ == "__main__":
    sys.exit(main())
