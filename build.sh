#!/bin/bash
# ============================================
# PDF Sortier Meister - macOS-Build (Pendant zu build.bat)
#
# Erstellt dist/"PDF Sortier Meister.app" und ein DMG unter
# dist/installer/PDF_Sortier_Meister-macos-<arch>.dmg (fester Name,
# damit der GitHub-releases/latest-Direktlink stabil bleibt, wie #49).
#
# Voraussetzungen:
#   brew install tesseract tesseract-lang
#   Xcode Command Line Tools (otool, install_name_tool, codesign, sips)
#
# Optionale Signierung/Notarisierung ueber Umgebungsvariablen:
#   MACOS_CODESIGN_IDENTITY  -> App + DMG werden Developer-ID-signiert
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_SPECIFIC_PASSWORD
#                            -> zusaetzlich notarisiert + gestapelt
# Ohne diese Variablen entsteht ein unsignierter Build (Testen per
# Rechtsklick -> Oeffnen).
# ============================================
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
APP="dist/PDF Sortier Meister.app"
ARCH="$(uname -m)"
DMG="dist/installer/PDF_Sortier_Meister-macos-${ARCH}.dmg"

echo "========================================"
echo "PDF Sortier Meister - Build (macOS ${ARCH})"
echo "========================================"

if ! "$PYTHON" -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller nicht gefunden. Installiere..."
    "$PYTHON" -m pip install pyinstaller
fi

# Die LLM-Pakete sind in requirements.txt optional, muessen im Release aber
# enthalten sein - sonst fehlt die Cloud-KI (OpenRouter/OpenAI/Claude) im Build.
if ! "$PYTHON" -c "import openai, anthropic" 2>/dev/null; then
    echo "LLM-Pakete nicht gefunden. Installiere openai + anthropic..."
    "$PYTHON" -m pip install openai anthropic
fi

echo "Loesche alte Build-Dateien..."
rm -rf build dist

if [ ! -x vendor/tesseract/tesseract ]; then
    echo "Bereite Tesseract-Laufzeit vor (vendor/tesseract)..."
    "$PYTHON" scripts/prepare_tesseract_mac.py
fi

if [ ! -f icon.icns ]; then
    echo "Erzeuge icon.icns aus icon.png..."
    scripts/macos/make_icns.sh
fi

echo
echo "Starte Build (onedir, .app-Bundle)..."
"$PYTHON" -m PyInstaller pdf_sortier_meister.spec --clean --noconfirm

if [ ! -d "$APP" ]; then
    echo "BUILD FEHLGESCHLAGEN - $APP fehlt." >&2
    exit 1
fi

if [ -n "${MACOS_CODESIGN_IDENTITY:-}" ]; then
    scripts/macos/sign_app.sh "$APP" "$MACOS_CODESIGN_IDENTITY"
    if [ -n "${APPLE_ID:-}" ]; then
        scripts/macos/notarize.sh "$APP"
    fi
else
    echo "HINWEIS: MACOS_CODESIGN_IDENTITY nicht gesetzt - Build bleibt unsigniert."
fi

echo
echo "Erstelle DMG..."
mkdir -p dist/installer
STAGING="$(mktemp -d)"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname "PDF Sortier Meister" -srcfolder "$STAGING" \
    -format UDZO -ov "$DMG"
rm -rf "$STAGING"

if [ -n "${MACOS_CODESIGN_IDENTITY:-}" ]; then
    codesign --force --timestamp -s "$MACOS_CODESIGN_IDENTITY" "$DMG"
    if [ -n "${APPLE_ID:-}" ]; then
        scripts/macos/notarize.sh "$DMG"
    fi
fi

echo
echo "========================================"
echo "BUILD ERFOLGREICH!"
echo "========================================"
echo "App: $APP"
echo "DMG: $DMG"
