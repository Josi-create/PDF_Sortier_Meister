#!/bin/bash
# Erzeugt icon.icns aus icon.png (fuer das .app-Bundle).
# Aufruf aus dem Repo-Root: scripts/macos/make_icns.sh
set -euo pipefail

cd "$(dirname "$0")/../.."

if [ ! -f icon.png ]; then
    echo "icon.png fehlt im Repo-Root" >&2
    exit 1
fi

rm -rf icon.iconset
mkdir icon.iconset

for size in 16 32 128 256 512; do
    sips -z "$size" "$size" icon.png --out "icon.iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" icon.png --out "icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns icon.iconset -o icon.icns
rm -rf icon.iconset
echo "icon.icns erstellt."
