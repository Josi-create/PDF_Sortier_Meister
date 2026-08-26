"""
Baut den Windows-Installer (Inno Setup) aus dist/PDF_Sortier_Meister/.

Liest die Version aus src/main.py (__version__), sucht ISCC.exe und ruft
    ISCC.exe /DMyAppVersion=<version> installer.iss
auf. Ergebnis: dist/installer/PDF_Sortier_Meister_Setup_<version>.exe

Aufruf (nach build.bat bzw. PyInstaller):
    venv\\Scripts\\python.exe scripts\\build_installer.py
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_version() -> str:
    text = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        sys.exit("__version__ in src/main.py nicht gefunden")
    return match.group(1)


def find_iscc() -> str:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    on_path = shutil.which("ISCC")
    if on_path:
        return on_path
    sys.exit("ISCC.exe nicht gefunden - Inno Setup 6 installieren: https://jrsoftware.org/isdl.php")


def main() -> None:
    if not (ROOT / "dist" / "PDF_Sortier_Meister" / "PDF_Sortier_Meister.exe").is_file():
        sys.exit("dist/PDF_Sortier_Meister fehlt - zuerst build.bat ausfuehren")
    version = read_version()
    iscc = find_iscc()
    print(f"Inno Setup: {iscc}\nVersion:    {version}")
    result = subprocess.run(
        [iscc, f"/DMyAppVersion={version}", str(ROOT / "installer.iss")],
        cwd=ROOT,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)
    print(f"\nInstaller: dist\\installer\\PDF_Sortier_Meister_Setup_{version}.exe")


if __name__ == "__main__":
    main()
