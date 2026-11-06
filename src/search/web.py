"""Browser-Oberflaeche der Dokumentensuche (nur lokal: http://127.0.0.1:18425).

Optionales Extra ``suche-web`` (Flask, waitress); uebernommen aus PDFsuche.
Schutz: nur die Hosts 127.0.0.1/localhost, POST nur mit Header ``X-PDFsuche: 1``
(gegen fremde Webseiten, die den lokalen Server ansprechen). Alle Zugriffe
lesen; „Jetzt indizieren“ startet den Dienst als eigenen Prozess.
"""

from __future__ import annotations

import io
import mimetypes
import os
import threading
import webbrowser
from pathlib import Path

from src.search import fenster, mbox
from src.search.konfig import SearchConfig
from src.search.plattform import im_dateimanager_zeigen as _im_dateimanager_zeigen
from src.search.suchindex import Suchindex

STATIC = Path(__file__).parent / "static"
ERLAUBTE_HOSTS = {"127.0.0.1", "localhost"}


def _dateiname(s: str) -> str:
    return Suchindex.eml_dateiname(s)


def erstelle_app(konfig: SearchConfig):
    from flask import Flask, abort, jsonify, request, send_file, send_from_directory

    app = Flask(__name__, static_folder=None)
    idx = Suchindex(konfig)

    @app.before_request
    def schutz():
        host = (request.host or "").rsplit(":", 1)[0].strip("[]")
        if host not in ERLAUBTE_HOSTS:
            abort(403)
        if request.method == "POST" and request.headers.get("X-PDFsuche") != "1":
            abort(403)

    @app.get("/")
    def start():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def statisch(name):
        return send_from_directory(STATIC, name)

    @app.get("/api/suche")
    def api_suche():
        a = request.args
        q = (a.get("q") or "").strip()
        if not q:
            return jsonify({"treffer": [], "gesamt": 0, "mehr": False, "abfrage": "", "dauer_ms": 0})
        try:
            erg = idx.suche(q, typ=a.get("typ") or None, ordner=a.get("ordner") or None,
                            von=a.get("von") or None, bis=a.get("bis") or None,
                            sortierung=a.get("sort") or "relevanz",
                            anzahl=min(int(a.get("anzahl", 50)), 200), start=int(a.get("start", 0)))
        except ValueError as e:
            return jsonify({"fehler": str(e)}), 400
        return jsonify(erg)

    def _dok_oder_404(dok_id):
        d = idx.dokument(dok_id)
        if not d:
            abort(404)
        return d

    @app.get("/api/dokument/<int:dok_id>")
    def api_dokument(dok_id):
        d = _dok_oder_404(dok_id)
        seiten = idx.seiten_text(dok_id, hervorheben=request.args.get("q") or None)
        return jsonify({"dokument": d, "seiten": seiten})

    @app.get("/api/status")
    def api_status():
        return jsonify(idx.status())

    @app.get("/datei/<int:dok_id>")
    def datei(dok_id):
        d = _dok_oder_404(dok_id)
        if d["format"] == "mbox":
            roh = mbox.mail_roh(d["datei"], d["mbox_offset"], d["mbox_laenge"])
            return send_file(io.BytesIO(roh), mimetype="message/rfc822", as_attachment=True,
                             download_name=_dateiname(d["name"]) + ".eml")
        if not os.path.exists(d["datei"]):
            abort(404, "Datei existiert nicht mehr")
        if d["format"] == "md":
            return send_file(d["datei"], mimetype="text/plain; charset=utf-8")
        mt = mimetypes.guess_type(d["datei"])[0] or "application/octet-stream"
        return send_file(d["datei"], mimetype=mt, as_attachment=d["format"] != "pdf",
                         download_name=os.path.basename(d["datei"]))

    @app.post("/api/oeffnen/<int:dok_id>")
    def oeffnen(dok_id):
        d = _dok_oder_404(dok_id)
        # Die Oberflaeche laeuft als Hintergrundaufgabe: das geoeffnete Programm nach vorn holen (fenster.py)
        if d["format"] == "mbox":
            eml = idx.mail_als_eml(d)
            fenster.starte(eml, [Path(eml).name, d["name"]])
        elif os.path.exists(d["datei"]):
            fenster.starte(d["datei"])
        else:
            return jsonify({"ok": False, "fehler": "Datei existiert nicht mehr"}), 404
        return jsonify({"ok": True})

    @app.post("/api/ordner/<int:dok_id>")
    def ordner(dok_id):
        d = _dok_oder_404(dok_id)
        if not os.path.exists(d["datei"]):
            return jsonify({"ok": False, "fehler": "Datei existiert nicht mehr"}), 404
        fenster.ordner_zeigen(d["datei"], _im_dateimanager_zeigen)
        return jsonify({"ok": True})

    @app.post("/api/index-starten")
    def index_starten():
        if idx.laeuft_gerade():
            return jsonify({"ok": False, "fehler": "Läuft bereits"})
        idx.lauf_starten(nur_prioritaet=request.args.get("nur_prioritaet") == "1")
        return jsonify({"ok": True})

    return app


def starte(konfig: SearchConfig, port: int | None = None, oeffnen: bool = True) -> None:
    port = port or konfig.web_port
    url = f"http://127.0.0.1:{port}/"
    app = erstelle_app(konfig)
    if oeffnen:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Dokumentensuche läuft auf {url}  (Beenden: Strg+C)")
    try:
        from waitress import serve
        serve(app, host=konfig.web_host, port=port, threads=8)
    except ImportError:
        app.run(host=konfig.web_host, port=port, threaded=True)
