"""
Kopiert eine minimale Tesseract-Laufzeit nach vendor/tesseract/, damit
PyInstaller sie mit der App buendelt (siehe pdf_sortier_meister.spec).

Quelle: eine installierte Tesseract-Version (UB-Mannheim-Build), Standard
C:\\Program Files\\Tesseract-OCR. Mitgenommen werden nur tesseract.exe, die
DLLs, die sie tatsaechlich importiert (transitiv, via pefile), und die
Sprachdaten deu + eng.

Aufruf:
    venv\\Scripts\\python.exe scripts\\prepare_tesseract.py [Quellordner]
"""

import os
import shutil
import sys
from pathlib import Path

import pefile

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "vendor" / "tesseract"
LANGUAGES = ("deu", "eng")


def find_source() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    for base in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA", "") + r"\Programs"):
        if base and (Path(base) / "Tesseract-OCR" / "tesseract.exe").is_file():
            return Path(base) / "Tesseract-OCR"
    sys.exit("Keine Tesseract-Installation gefunden. Quellordner als Argument angeben.")


def required_dlls(exe: Path) -> list[Path]:
    """Alle DLLs aus dem Tesseract-Ordner, die tesseract.exe (transitiv) importiert."""
    folder = exe.parent
    present = {p.name.lower(): p for p in folder.glob("*.dll")}
    needed: dict[str, Path] = {}
    todo = [exe]
    while todo:
        pe = pefile.PE(str(todo.pop()), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            name = entry.dll.decode().lower()
            if name in present and name not in needed:
                needed[name] = present[name]
                todo.append(present[name])
    return sorted(needed.values())


def main() -> None:
    source = find_source()
    exe = source / "tesseract.exe"
    if not exe.is_file():
        sys.exit(f"tesseract.exe nicht gefunden in {source}")

    if TARGET.exists():
        shutil.rmtree(TARGET)
    (TARGET / "tessdata").mkdir(parents=True)

    files = [exe] + required_dlls(exe)
    for f in files:
        shutil.copy2(f, TARGET / f.name)
    for lang in LANGUAGES:
        data = source / "tessdata" / f"{lang}.traineddata"
        if not data.is_file():
            sys.exit(f"Sprachdaten fehlen: {data}")
        shutil.copy2(data, TARGET / "tessdata" / data.name)

    total = sum(p.stat().st_size for p in TARGET.rglob("*") if p.is_file())
    print(f"{len(files)} Dateien + {len(LANGUAGES)} Sprachen nach {TARGET} kopiert "
          f"({total / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
