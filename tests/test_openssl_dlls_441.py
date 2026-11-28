"""OpenSSL-DLLs im Windows-Build kommen aus dem Python, nicht aus der Tesseract-Laufzeit (Issue #441)."""

from pathlib import Path

from scripts.openssl_dlls import abweichungen, binaries_umbiegen, ist_openssl_dll


def _datei(pfad: Path, inhalt: bytes) -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    return pfad


def test_namen_erkennen():
    assert ist_openssl_dll("libcrypto-3-x64.dll")
    assert ist_openssl_dll("libssl-3-x64.dll")
    assert ist_openssl_dll("libcrypto-3.dll")
    assert ist_openssl_dll("LIBSSL-3.DLL")
    assert not ist_openssl_dll("libcurl-4.dll")
    assert not ist_openssl_dll("_ssl.pyd")
    assert not ist_openssl_dll("libcrypto-3-x64.dll.bak")


def test_oben_liegende_tesseract_dll_wird_umgebogen(tmp_path):
    py = tmp_path / "Python Ärger" / "DLLs"
    _datei(py / "libcrypto-3-x64.dll", b"python")
    _datei(py / "libssl-3-x64.dll", b"python-ssl")
    tess = tmp_path / "vendor" / "tesseract"
    t_crypto = _datei(tess / "libcrypto-3-x64.dll", b"tesseract")
    binaries = [
        ("libcrypto-3-x64.dll", str(t_crypto), "BINARY"),
        ("libssl-3-x64.dll", str(py / "libssl-3-x64.dll"), "BINARY"),
        ("tesseract/libcrypto-3-x64.dll", str(t_crypto), "BINARY"),
        ("libcurl-4.dll", str(tess / "libcurl-4.dll"), "BINARY"),
    ]
    neu, geaendert = binaries_umbiegen(binaries, py)
    assert geaendert == [("libcrypto-3-x64.dll", str(t_crypto))]
    assert neu[0] == ("libcrypto-3-x64.dll", str(py / "libcrypto-3-x64.dll"), "BINARY")
    # bereits richtig, Unterordner von Tesseract und fremde DLLs bleiben unveraendert
    assert neu[1:] == binaries[1:]


def test_ohne_python_ordner_oder_ohne_gegenstueck_bleibt_alles(tmp_path):
    binaries = [("libcrypto-3.dll", str(tmp_path / "x" / "libcrypto-3.dll"), "BINARY")]
    assert binaries_umbiegen(binaries, None) == (binaries, [])
    leer = tmp_path / "leer"
    leer.mkdir()
    assert binaries_umbiegen(binaries, leer) == (binaries, [])


def test_abweichungen_im_gebauten_ordner(tmp_path):
    py = tmp_path / "DLLs"
    _datei(py / "libcrypto-3-x64.dll", b"python")
    _datei(py / "libssl-3-x64.dll", b"python-ssl")
    internal = tmp_path / "_internal"
    _datei(internal / "libssl-3-x64.dll", b"python-ssl")
    _datei(internal / "libcrypto-3-x64.dll", b"tesseract")
    _datei(internal / "libcrypto-3.dll", b"ohne Gegenstueck")
    _datei(internal / "tesseract" / "libcrypto-3-x64.dll", b"tesseract")
    assert abweichungen(internal, py) == ["libcrypto-3-x64.dll"]
    _datei(internal / "libcrypto-3-x64.dll", b"python")
    assert abweichungen(internal, py) == []
