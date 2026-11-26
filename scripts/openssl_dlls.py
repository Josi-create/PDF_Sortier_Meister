"""OpenSSL-DLLs im Windows-Build: immer die des Python, nie die der Tesseract-Laufzeit (Issue #441).

Python (``_ssl.pyd``) und die gebuendelte Tesseract-Laufzeit (``vendor/tesseract``) bringen je
eine ``libcrypto-3-x64.dll`` mit. PyInstaller legt eine solche Abhaengigkeit nur einmal oben in
``_internal`` ab und nimmt die zuerst gefundene. Ist das die aeltere von Tesseract, scheitert
``import ssl`` (``DLL load failed while importing _ssl``) im Hauptprogramm wie im Dienst.
Dasselbe gilt fuer gleichnamige DLLs anderer Programme im PATH (z. B. Git fuer Windows).
Tesseract behaelt seine eigenen Dateien unter ``_internal/tesseract/``; Windows sucht DLLs
zuerst im Ordner der ``tesseract.exe``.

Benutzt von ``pdf_sortier_meister.spec`` (Eintraege umbiegen) und
``scripts/rauchtest_dienst.py`` (gebautes Programm pruefen).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_MUSTER = re.compile(r"lib(crypto|ssl)-\d[\w-]*\.dll", re.IGNORECASE)


def ist_openssl_dll(name: str) -> bool:
    return bool(_MUSTER.fullmatch(name))


def python_openssl_ordner() -> Path | None:
    """Ordner mit ``_ssl.pyd`` des laufenden Python (dort liegen dessen OpenSSL-DLLs)."""
    try:
        import _ssl
    except ImportError:
        return None
    datei = getattr(_ssl, "__file__", None)
    return Path(datei).parent if datei else None


def binaries_umbiegen(binaries: list, ordner: Path | None) -> tuple[list, list[tuple[str, str]]]:
    """Ersetzt die Quelle oben liegender OpenSSL-DLLs durch die gleichnamige Datei aus ``ordner``.

    ``binaries`` ist die TOC-Liste einer PyInstaller-Analyse (Eintraege ``(ziel, quelle, typ)``).
    Nur Eintraege direkt in ``_internal`` (ohne Unterordner) werden geaendert; was unter
    ``tesseract/`` liegt, bleibt. Liefert die neue Liste und je umgebogener Datei
    ``(name, alte_quelle)``.
    """
    if ordner is None:
        return list(binaries), []
    neu, geaendert = [], []
    for ziel, quelle, typ in binaries:
        pfad = Path(ziel)
        ersatz = ordner / pfad.name
        if (len(pfad.parts) == 1 and ist_openssl_dll(pfad.name) and ersatz.is_file()
                and Path(quelle).resolve() != ersatz.resolve()):
            geaendert.append((pfad.name, quelle))
            quelle = str(ersatz)
        neu.append((ziel, quelle, typ))
    return neu, geaendert


def _pruefsumme(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def abweichungen(internal: Path, ordner: Path) -> list[str]:
    """OpenSSL-DLLs oben in ``internal``, die nicht der gleichnamigen Datei in ``ordner`` gleichen."""
    fehler = []
    for datei in sorted(internal.iterdir()):
        if not (datei.is_file() and ist_openssl_dll(datei.name)):
            continue
        vorlage = ordner / datei.name
        if vorlage.is_file() and _pruefsumme(vorlage) != _pruefsumme(datei):
            fehler.append(datei.name)
    return fehler
