# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec-File für PDF Sortier Meister

Erstellt eine Windows .exe mit:
- Alle Dependencies gebündelt
- SplashScreen-Bild eingebettet
- Icon für die Anwendung

Ausführen mit: pyinstaller pdf_sortier_meister.spec
"""

import sys
from pathlib import Path

block_cipher = None

# Pfade
ROOT_DIR = Path(SPECPATH)
SRC_DIR = ROOT_DIR / "src"

# Daten-Dateien die eingebettet werden sollen
datas = [
    # SplashScreen
    (str(ROOT_DIR / "SplashScreen3.png"), "."),
    # Evtl. weitere Assets
]

# Nur hinzufügen wenn vorhanden
splash_path = ROOT_DIR / "SplashScreen3.png"
if not splash_path.exists():
    datas = []

# Hidden imports für PyQt6 und sklearn
hiddenimports = [
    # PyQt6
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.sip",
    # sklearn
    "sklearn.feature_extraction.text",
    "sklearn.metrics.pairwise",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors._typedefs",
    "sklearn.neighbors._quad_tree",
    "sklearn.tree._utils",
    # SQLAlchemy
    "sqlalchemy.sql.default_comparator",
    # LLM (optional)
    "anthropic",
    "openai",
]

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
        # Nicht benötigte Module ausschließen
        "tkinter",
        "matplotlib",
        "PIL",
        "IPython",
        "jupyter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PDF_Sortier_Meister",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Keine Konsole (GUI-Anwendung)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Icon (falls vorhanden)
    # icon=str(ROOT_DIR / "icon.ico"),
)
