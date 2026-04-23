# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec-File fuer PDF Sortier Meister

Erstellt eine Windows-Distribution mit:
- Alle Dependencies gebuendelt (onedir = schneller Start)
- Nativer PyInstaller-Splash (erscheint aus dem Bootloader,
  bevor Python/PyQt6 geladen werden -> maximal schneller Splash)
- Icon fuer die Anwendung (falls vorhanden)

Ausfuehren mit: pyinstaller pdf_sortier_meister.spec --clean
"""

from pathlib import Path

block_cipher = None

# Pfade
ROOT_DIR = Path(SPECPATH)
SRC_DIR = ROOT_DIR / "src"
SPLASH_IMG = ROOT_DIR / "SplashScreen3.png"
ICON_PATH = ROOT_DIR / "icon.ico"

# Daten-Dateien die eingebettet werden sollen
datas = []
if SPLASH_IMG.exists():
    # Splashbild auch als Datei mitliefern, damit der Fallback-Qt-Splash
    # (z.B. bei Python-Direktstart) ebenfalls funktioniert.
    datas.append((str(SPLASH_IMG), "."))

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
# ---------------------------------------------------------------------------
splash = None
if SPLASH_IMG.exists():
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
exe_kwargs = dict(
    name="PDF_Sortier_Meister",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
        upx=True,
        upx_exclude=[],
        name="PDF_Sortier_Meister",
    )
