# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec-File fuer PDF Sortier Meister (Windows + macOS)

Erstellt eine Distribution mit:
- Alle Dependencies gebuendelt (onedir = schneller Start)
- Windows: nativer PyInstaller-Splash (erscheint aus dem Bootloader,
  bevor Python/PyQt6 geladen werden -> maximal schneller Splash)
- macOS: .app-Bundle via BUNDLE (Splash() wird von PyInstaller auf
  macOS nicht unterstuetzt; der Qt-Fallback-Splash aus main.py greift)
- Icon fuer die Anwendung (falls vorhanden; .ico bzw. .icns)

Ausfuehren mit: pyinstaller pdf_sortier_meister.spec --clean
"""

import re
import sys
from pathlib import Path

block_cipher = None
IS_MAC = sys.platform == "darwin"

# Pfade
ROOT_DIR = Path(SPECPATH)
SRC_DIR = ROOT_DIR / "src"
SPLASH_IMG = ROOT_DIR / "SplashScreen3.png"
# icon.icns wird von scripts/macos/make_icns.sh aus icon.png erzeugt (gitignored)
ICON_PATH = ROOT_DIR / ("icon.icns" if IS_MAC else "icon.ico")

# Version aus src/main.py lesen (gleiche Technik wie scripts/build_installer.py)
_version_match = re.search(
    r'^__version__\s*=\s*"([^"]+)"',
    (SRC_DIR / "main.py").read_text(encoding="utf-8"),
    re.MULTILINE,
)
APP_VERSION = _version_match.group(1) if _version_match else "0.0.0"

# Daten-Dateien die eingebettet werden sollen
datas = []
if SPLASH_IMG.exists():
    # Splashbild auch als Datei mitliefern, damit der Fallback-Qt-Splash
    # (z.B. bei Python-Direktstart) ebenfalls funktioniert.
    datas.append((str(SPLASH_IMG), "."))
if (ROOT_DIR / "icon.png").exists():
    # Fenster-/Taskleisten-Icon zur Laufzeit (app.setWindowIcon)
    datas.append((str(ROOT_DIR / "icon.png"), "."))
# Gebuendelte Tesseract-Laufzeit (vorher scripts/prepare_tesseract.py bzw.
# scripts/prepare_tesseract_mac.py ausfuehren).
# Landet in _internal/tesseract/ und wird von find_tesseract() zuerst gefunden.
TESSERACT_DIR = ROOT_DIR / "vendor" / "tesseract"
TESS_BIN = TESSERACT_DIR / ("tesseract" if IS_MAC else "tesseract.exe")
if TESS_BIN.exists():
    datas.append((str(TESSERACT_DIR), "tesseract"))
else:
    print("HINWEIS: vendor/tesseract fehlt - Build ohne gebuendelte OCR "
          "(scripts/prepare_tesseract.py bzw. prepare_tesseract_mac.py ausfuehren).")

# Hidden imports fuer PyQt6 und sklearn
hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.sip",
    "sklearn.feature_extraction.text",
    "sklearn.metrics.pairwise",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors._typedefs",
    "sklearn.neighbors._quad_tree",
    "sklearn.tree._utils",
    "sqlalchemy.sql.default_comparator",
]

# Optionale LLM-Pakete nur einbinden, falls installiert
for _mod in ("anthropic", "openai"):
    try:
        __import__(_mod)
        hiddenimports.append(_mod)
    except ImportError:
        pass

a = Analysis(
    [str(SRC_DIR / "main.py")],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PIL.ImageQt",
        "IPython",
        "jupyter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---------------------------------------------------------------------------
# Nativer Splash: wird vom Bootloader angezeigt, bevor Python startet.
# So erscheint das Bild innerhalb von Millisekunden nach dem Doppelklick.
# Die App schliesst den Splash per pyi_splash.close() sobald das Hauptfenster
# vollstaendig geladen ist.
# Auf macOS unterstuetzt PyInstaller Splash() nicht - dort greift der
# Qt-Fallback-Splash in main.py.
# ---------------------------------------------------------------------------
splash = None
if SPLASH_IMG.exists() and not IS_MAC:
    splash = Splash(
        str(SPLASH_IMG),
        binaries=a.binaries,
        datas=a.datas,
        text_pos=None,          # keine Statustexte auf dem Splash
        text_size=12,
        minify_script=True,
        always_on_top=True,
    )

# Icon optional
# UPX nur unter Windows - auf macOS zerstoert es Mach-O-Codesignaturen.
exe_kwargs = dict(
    name="PDF_Sortier_Meister",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=not IS_MAC,
    upx_exclude=[],
    console=False,              # GUI-Anwendung, keine Konsole
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
if ICON_PATH.exists():
    exe_kwargs["icon"] = str(ICON_PATH)

# onedir-Build: .exe + Abhaengigkeiten nebeneinander im Ordner
# -> sofortiger Start (kein Entpacken nach %TEMP% wie bei onefile)
if splash is not None:
    exe = EXE(
        pyz,
        a.scripts,
        splash,                 # Splash-Script in die EXE
        [],
        exclude_binaries=True,
        **exe_kwargs,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        splash.binaries,        # Splash-Bootloader-Binaries
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="PDF_Sortier_Meister",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **exe_kwargs,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=not IS_MAC,
        upx_exclude=[],
        name="PDF_Sortier_Meister",
    )

# macOS: .app-Bundle um den onedir-Ordner. Signierung/Notarisierung passiert
# post-build (scripts/macos/sign_app.sh), nicht ueber codesign_identity.
if IS_MAC:
    app = BUNDLE(
        coll,
        name="PDF Sortier Meister.app",
        icon=str(ICON_PATH) if ICON_PATH.exists() else None,
        bundle_identifier="de.josi-create.pdf-sortier-meister",
        version=APP_VERSION,
        info_plist={
            "CFBundleName": "PDF Sortier Meister",
            "CFBundleShortVersionString": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
