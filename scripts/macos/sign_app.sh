#!/bin/bash
# Signiert die .app mit einer Developer-ID-Identitaet (Hardened Runtime).
# Inside-out: erst alle eingebetteten Mach-O-Dateien, zuletzt das Bundle
# selbst (signiert dabei die Haupt-Executable mit; kein deprecated --deep).
#
# Aufruf: scripts/macos/sign_app.sh "<pfad/zur/.app>" "<identity>"
# Die Identity ist z.B. "Developer ID Application: Max Mustermann (TEAMID)".
set -euo pipefail

APP="${1:?Pfad zur .app fehlt}"
IDENTITY="${2:?Codesign-Identity fehlt}"
ENTITLEMENTS="$(cd "$(dirname "$0")/../.." && pwd)/packaging/macos/entitlements.plist"

echo "Signiere eingebettete Mach-O-Dateien in $APP ..."
find "$APP/Contents" -type f ! -path "*/Contents/MacOS/PDF_Sortier_Meister" -print0 |
    while IFS= read -r -d '' f; do
        if file -b "$f" | grep -q "Mach-O"; then
            codesign --force --timestamp --options runtime \
                --entitlements "$ENTITLEMENTS" -s "$IDENTITY" "$f"
        fi
    done

echo "Signiere Bundle (inkl. Haupt-Executable) ..."
codesign --force --timestamp --options runtime \
    --entitlements "$ENTITLEMENTS" -s "$IDENTITY" "$APP"

echo "Verifiziere ..."
codesign --verify --deep --strict --verbose=2 "$APP"
echo "Signatur OK."
