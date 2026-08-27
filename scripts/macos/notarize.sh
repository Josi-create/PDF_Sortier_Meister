#!/bin/bash
# Notarisiert eine .app oder .dmg bei Apple und heftet das Ticket an.
# Benoetigte Umgebungsvariablen:
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_SPECIFIC_PASSWORD
#
# Aufruf: scripts/macos/notarize.sh "<pfad/zur/.app-oder-.dmg>"
set -euo pipefail

TARGET="${1:?Pfad zur .app oder .dmg fehlt}"
: "${APPLE_ID:?APPLE_ID fehlt}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID fehlt}"
: "${APPLE_APP_SPECIFIC_PASSWORD:?APPLE_APP_SPECIFIC_PASSWORD fehlt}"

SUBMIT_PATH="$TARGET"
CLEANUP=""
if [[ "$TARGET" == *.app ]]; then
    # .app muss als Zip eingereicht werden; das Ticket wird an die .app geheftet.
    SUBMIT_PATH="$(mktemp -d)/$(basename "$TARGET").zip"
    ditto -c -k --keepParent "$TARGET" "$SUBMIT_PATH"
    CLEANUP="$SUBMIT_PATH"
fi

echo "Reiche $SUBMIT_PATH zur Notarisierung ein ..."
xcrun notarytool submit "$SUBMIT_PATH" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_SPECIFIC_PASSWORD" \
    --wait

echo "Staple Ticket an $TARGET ..."
xcrun stapler staple "$TARGET"

[ -n "$CLEANUP" ] && rm -f "$CLEANUP"
echo "Notarisierung OK."
