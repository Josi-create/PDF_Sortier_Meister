"""
Kopiert eine minimale Tesseract-Laufzeit nach vendor/tesseract/, damit
PyInstaller sie mit der macOS-App buendelt (siehe pdf_sortier_meister.spec).
Pendant zu scripts/prepare_tesseract.py (Windows).

Quelle: eine Homebrew-Installation. Voraussetzungen:
    brew install tesseract tesseract-lang   # deu.traineddata kommt aus tesseract-lang
    Xcode Command Line Tools                # otool, install_name_tool, codesign

Vorgehen:
1. tesseract-Binary via Homebrew finden (Symlinks aufloesen).
2. Alle Nicht-System-dylibs rekursiv ermitteln (otool -L, analog zur
   pefile-Analyse im Windows-Skript) und flach nach vendor/tesseract/
   kopieren.
3. Loadpfade auf @loader_path/<name> umschreiben (install_name_tool),
   damit das Bundle ohne Homebrew auf dem Zielrechner laeuft.
4. Jede veraenderte Datei ad-hoc signieren (auf arm64 zwingend; die
   Developer-ID-Signatur von sign_app.sh ueberschreibt das spaeter).
5. Sprachdaten deu + eng nach vendor/tesseract/tessdata/.
6. Selbsttest: das relozierte Binary mit --version ausfuehren.

Aufruf:
    python3 scripts/prepare_tesseract_mac.py [Pfad-zur-tesseract-Binary]
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "vendor" / "tesseract"
LANGUAGES = ("deu", "eng")

# Systempfade, deren Bibliotheken auf jedem Mac vorhanden sind.
_SYSTEM_PREFIXES = ("/usr/lib/", "/System/")


def _run(*cmd: str) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"Befehl fehlgeschlagen: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def find_source() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).resolve()
    found = shutil.which("tesseract")
    if found:
        return Path(found).resolve()
    for prefix in ("/opt/homebrew", "/usr/local"):
        candidate = Path(prefix) / "bin" / "tesseract"
        if candidate.is_file():
            return candidate.resolve()
    sys.exit(
        "Keine Tesseract-Installation gefunden. "
        "Bitte 'brew install tesseract tesseract-lang' ausfuehren "
        "oder den Binary-Pfad als Argument angeben."
    )


def linked_libs(binary: Path) -> list[str]:
    """Nicht-System-Abhaengigkeiten einer Mach-O-Datei laut otool -L."""
    libs = []
    for line in _run("otool", "-L", str(binary)).splitlines()[1:]:
        dep = line.strip().split(" (compatibility")[0].strip()
        if not dep or dep.startswith(_SYSTEM_PREFIXES):
            continue
        libs.append(dep)
    return libs


def resolve_dep(dep: str, referrer: Path) -> Path:
    """Loest eine otool-Referenz (auch @rpath/@loader_path) in einen echten Pfad auf."""
    if dep.startswith("@loader_path/"):
        return (referrer.parent / dep[len("@loader_path/"):]).resolve()
    if dep.startswith("@rpath/"):
        name = dep[len("@rpath/"):]
        # Homebrew-Kegs legen rpath-Referenzen neben den anderen dylibs ab.
        for base in (referrer.parent, *_homebrew_lib_dirs()):
            candidate = (base / name).resolve()
            if candidate.is_file():
                return candidate
        sys.exit(f"@rpath-Referenz nicht aufloesbar: {dep} (aus {referrer})")
    return Path(dep).resolve()


def _homebrew_lib_dirs() -> list[Path]:
    return [p for p in (Path("/opt/homebrew/lib"), Path("/usr/local/lib")) if p.is_dir()]


def collect_files(exe: Path) -> tuple[dict[str, Path], dict[str, str]]:
    """Alle zu buendelnden Dateien: Binary + transitiv alle Nicht-System-dylibs.

    Liefert zusaetzlich ein Mapping Referenzname -> Bundle-Dateiname, weil
    Homebrew-Referenzen oft auf Symlinks zeigen (z.B. libgif.dylib), waehrend
    gebuendelt der aufgeloeste reale Name liegt (libgif.7.2.0.dylib).
    """
    needed: dict[str, Path] = {exe.name: exe}
    alias: dict[str, str] = {}
    todo = [exe]
    while todo:
        current = todo.pop()
        for dep in linked_libs(current):
            real = resolve_dep(dep, current)
            alias[Path(dep).name] = real.name
            if real.name in needed:
                continue
            if not real.is_file():
                sys.exit(f"Abhaengigkeit nicht gefunden: {dep} -> {real}")
            needed[real.name] = real
            todo.append(real)
    return needed, alias


def rewrite_load_paths(target_file: Path, alias: dict[str, str]) -> None:
    """Setzt id und alle gebuendelten Referenzen auf @loader_path/<name>."""
    if target_file.suffix == ".dylib" or ".dylib" in target_file.name:
        _run("install_name_tool", "-id", f"@loader_path/{target_file.name}", str(target_file))
    for dep in linked_libs(target_file):
        bundled = alias.get(Path(dep).name)
        if bundled and not dep.startswith("@loader_path/"):
            _run("install_name_tool", "-change", dep, f"@loader_path/{bundled}", str(target_file))


def copy_tessdata(source_exe: Path) -> None:
    """Kopiert deu/eng-Sprachdaten aus dem Homebrew-Keg."""
    tessdata_target = TARGET / "tessdata"
    tessdata_target.mkdir(parents=True, exist_ok=True)
    # <keg>/bin/tesseract -> <keg>/share/tessdata
    candidates = [source_exe.parent.parent / "share" / "tessdata"]
    for prefix in ("/opt/homebrew", "/usr/local"):
        candidates.append(Path(prefix) / "share" / "tessdata")
    tessdata_dirs = [c for c in candidates if c.is_dir()]
    if not tessdata_dirs:
        sys.exit("Kein tessdata-Verzeichnis gefunden (brew install tesseract).")
    # deu.traineddata liegt im tesseract-lang-Keg, nicht im tesseract-Keg -
    # daher pro Sprache alle Kandidaten durchsuchen.
    for lang in LANGUAGES:
        src = next(
            (d / f"{lang}.traineddata" for d in tessdata_dirs
             if (d / f"{lang}.traineddata").is_file()),
            None,
        )
        if src is None:
            sys.exit(
                f"{lang}.traineddata in keinem tessdata-Verzeichnis gefunden "
                f"({', '.join(str(d) for d in tessdata_dirs)}). "
                "Fuer deutsche Sprachdaten bitte "
                "'brew install tesseract-lang' ausfuehren."
            )
        shutil.copy2(src, tessdata_target / src.name)


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("Dieses Skript ist nur fuer macOS gedacht "
                 "(Windows: scripts/prepare_tesseract.py).")

    source_exe = find_source()
    print(f"Quelle: {source_exe}")

    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)

    files, alias = collect_files(source_exe)
    for name, src in sorted(files.items()):
        dest = TARGET / name
        shutil.copy2(src, dest)
        os.chmod(dest, 0o755)
        rewrite_load_paths(dest, alias)
        # Umschreiben invalidiert die Signatur - ad-hoc neu signieren.
        _run("codesign", "--force", "-s", "-", str(dest))
        print(f"  {name}")

    # Relokation verifizieren: --version allein reicht nicht, weil auf dem
    # Build-Rechner die Homebrew-Pfade noch existieren und Fehler kaschieren.
    leftovers = [
        f"  {name}: {dep}"
        for name in sorted(files)
        for dep in linked_libs(TARGET / name)
        if not dep.startswith(("@loader_path/",) + _SYSTEM_PREFIXES)
    ]
    if leftovers:
        sys.exit("Nicht relozierte Referenzen:\n" + "\n".join(leftovers))

    copy_tessdata(source_exe)

    # Selbsttest: beweist, dass die Relokation vollstaendig ist.
    bundled_exe = TARGET / source_exe.name
    version = subprocess.run(
        [str(bundled_exe), "--version"], capture_output=True, text=True
    )
    if version.returncode != 0:
        sys.exit(f"Selbsttest fehlgeschlagen:\n{version.stderr}")
    first_line = (version.stdout or version.stderr).splitlines()[0]
    print(f"OK: {len(files)} Dateien + tessdata ({', '.join(LANGUAGES)}) "
          f"nach {TARGET} kopiert ({first_line}).")


if __name__ == "__main__":
    main()
