# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec-File fuer PDF Sortier Meister (Windows + macOS)

Erstellt eine Distribution mit:
- Alle Dependencies gebuendelt (onedir = schneller Start)
- Hintergrunddienst der Dokumentensuche als eigene Programme im selben Ordner:
  pdfsm-dienst (mit Konsole: MCP, Kommandozeile) und unter Windows
  pdfsm-dienstw (ohne Konsolenfenster: Aufgabenplanung, Start aus der
  Oberflaeche, Web-Oberflaeche bei Anmeldung)
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

# Startbild des Bootloaders mit eingebrannter Versionsnummer (rechts unten).
# Der Bootloader zeigt das Bild, bevor Python laeuft; zur Laufzeit laesst sich
# dort nichts malen, also setzt der Build die Version ein.
SPLASH_BUILD_IMG = SPLASH_IMG
if SPLASH_IMG.exists() and not IS_MAC:
    try:
        sys.path.insert(0, str(ROOT_DIR))
        from src.utils.startbild import schreibe_bild_mit_version, versionstext
        SPLASH_BUILD_IMG = schreibe_bild_mit_version(
            SPLASH_IMG,
            Path(workpath) / "splash_mit_version.png",
            versionstext(APP_VERSION, entwicklung=False),
        )
    except Exception as _fehler:
        print(f"HINWEIS: Startbild ohne Versionsnummer ({_fehler}).")

# Die Oberflaeche meldet sich von Anfang an als DPI-faehig (Per-Monitor V2).
# Ohne diesen Eintrag startet der Bootloader DPI-unbewusst: Windows vergroessert
# das Startbild auf skalierten Bildschirmen (4K mit 150/175/200 %), und sobald
# Qt beim Erzeugen der QApplication die DPI-Faehigkeit des Prozesses einschaltet,
# schrumpft das Startbild auf seine echten Pixel und springt nach links oben.
# Ein eigenes Manifest ERSETZT das Standard-Manifest von PyInstaller (nur
# Ausfuehrungsebene und Common-Controls ergaenzt PyInstaller selbst). Deshalb
# stehen hier auch dessen uebrige Eintraege: unterstuetzte Windows-Versionen und
# longPathAware (lange Pfade). Vorlage: PyInstaller/utils/win32/winmanifest.py.
DPI_MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"></requestedExecutionLevel>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{e2011457-1546-43c5-a5fe-008deee3d3f0}"></supportedOS>
      <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"></supportedOS>
      <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"></supportedOS>
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"></supportedOS>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"></supportedOS>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0" processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"></assemblyIdentity>
    </dependentAssembly>
  </dependency>
</assembly>
"""

# Daten-Dateien die eingebettet werden sollen
datas = []
if SPLASH_IMG.exists():
    # Splashbild auch als Datei mitliefern, damit der Fallback-Qt-Splash
    # (z.B. bei Python-Direktstart) ebenfalls funktioniert.
    datas.append((str(SPLASH_IMG), "."))
if (ROOT_DIR / "icon.png").exists():
    # Fenster-/Taskleisten-Icon zur Laufzeit (app.setWindowIcon)
    datas.append((str(ROOT_DIR / "icon.png"), "."))
# Lizenztext (GPL-3.0-or-later) muss mit jedem Binary ausgeliefert werden
if (ROOT_DIR / "LICENSE").exists():
    datas.append((str(ROOT_DIR / "LICENSE"), "."))
# Uebersetzungen der Oberflaeche (Issue #118): src/i18n liest sie neben dem Modul
datas.append((str(SRC_DIR / "i18n" / "locale"), "src/i18n/locale"))
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
    # Integrierte PDF-Vorschau (Issues #74/#76): QtPdf bringt Qt6Pdf.dll mit
    "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets",
    "PyQt6.sip",
    "sklearn.feature_extraction.text",
    "sklearn.metrics.pairwise",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors._typedefs",
    "sklearn.neighbors._quad_tree",
    "sklearn.tree._utils",
    "sqlalchemy.sql.default_comparator",
    # HEIC-Handyfotos (Issue #205); der Hook von pyinstaller-hooks-contrib holt die Bibliotheken
    "pillow_heif",
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
# Hintergrunddienst der Dokumentensuche (docs/SUCHE_ARCHITEKTUR.md, Abschnitt 6).
# Eigene Analyse ohne Qt und sklearn: MCP-Clients warten auf den Handshake,
# und jeder Arbeitsprozess des Indexlaufs startet das Programm erneut.
# ---------------------------------------------------------------------------
dienst_datas = [
    # Browser-Oberflaeche (src/search/web.py liest sie neben dem Modul)
    (str(SRC_DIR / "search" / "static"), "src/search/static"),
    # Uebersetzungen (Meldungen des Dienstes, Browser-Oberflaeche)
    (str(SRC_DIR / "i18n" / "locale"), "src/i18n/locale"),
    # pdfsm-dienst --version liest __version__ aus src/main.py
    (str(SRC_DIR / "main.py"), "src"),
]
dienst_hiddenimports = [
    # MCP-Server (stdio): anyio laedt sein Backend dynamisch
    "anyio._backends._asyncio",
    "mcp.server.mcpserver",
    # Schraeglage messen (Issue #165): erst im Arbeitsprozess importiert, ohne numpy richtet nichts aus
    "src.search.gerade",
    "numpy",
    # Browser-Oberflaeche (optionales Extra suche-web), nur wenn installiert
]
for _mod in ("flask", "waitress"):
    try:
        __import__(_mod)
        dienst_hiddenimports.append(_mod)
    except ImportError:
        print(f"HINWEIS: {_mod} fehlt - pdfsm-dienst ohne Browser-Oberflaeche (pip install flask waitress).")

a_dienst = Analysis(
    [str(ROOT_DIR / "packaging" / "pdfsm_dienst.py")],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=dienst_datas,
    hiddenimports=dienst_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
        "PyQt6",
        "sklearn",
        "scipy",
        "sqlalchemy",
        # Chat-Werkzeuge im MCP-Server (Baustein 1, docs/CHAT_MCP_PLAN.md): src.rag und
        # src.core.similar_documents erreichen diese Module nur ueber verzoegerte Importe,
        # die der Dienst nie ausfuehrt (Historie liest src/search/pdfsm_daten.py per sqlite3).
        "src.utils.database",
        "src.ml.classifier",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_dienst = PYZ(a_dienst.pure, a_dienst.zipped_data, cipher=block_cipher)

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
        str(SPLASH_BUILD_IMG),
        binaries=a.binaries,
        datas=a.datas,
        text_pos=None,          # keine Statustexte auf dem Splash
        text_size=12,
        # Bild ist schon auf diese Groesse gerechnet (src/utils/startbild.py);
        # PyInstaller wuerde es sonst auf 760 x 480 verkleinern.
        max_img_size=(1056, 576),
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

# Dienstprogramme: pdfsm-dienst mit Konsole (MCP braucht stdio), unter Windows
# zusaetzlich pdfsm-dienstw ohne Konsolenfenster. Ein Absturz im Hintergrund
# darf kein Fenster mit Traceback oeffnen, das nachts auf einen Klick wartet.
dienst_exes = [
    EXE(pyz_dienst, a_dienst.scripts, [], exclude_binaries=True,
        **dict(exe_kwargs, name="pdfsm-dienst", console=True)),
]
if not IS_MAC:
    dienst_exes.append(
        EXE(pyz_dienst, a_dienst.scripts, [], exclude_binaries=True,
            **dict(exe_kwargs, name="pdfsm-dienstw", console=False, disable_windowed_traceback=True)))
dienst_toc = [*dienst_exes, a_dienst.binaries, a_dienst.zipfiles, a_dienst.datas]

# onedir-Build: .exe + Abhaengigkeiten nebeneinander im Ordner
# -> sofortiger Start (kein Entpacken nach %TEMP% wie bei onefile)
if splash is not None:
    exe = EXE(
        pyz,
        a.scripts,
        splash,                 # Splash-Script in die EXE
        [],
        exclude_binaries=True,
        manifest=DPI_MANIFEST,  # Startbild von Anfang an in echter Groesse
        **exe_kwargs,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        splash.binaries,        # Splash-Bootloader-Binaries
        a.zipfiles,
        a.datas,
        *dienst_toc,            # pdfsm-dienst(w) teilen sich _internal mit der Oberflaeche
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
        *dienst_toc,
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
            # Word/Excel/Pages per AppleScript (docx/xlsx -> PDF); ohne diesen
            # Text lehnt macOS die Steuerung stillschweigend ab
            "NSAppleEventsUsageDescription": (
                "PDF Sortier Meister steuert Microsoft Word/Excel oder Pages/Numbers, um Word- "
                "und Excel-Dateien in PDF umzuwandeln und in der Vorschau zu zeigen."
            ),
        },
    )
