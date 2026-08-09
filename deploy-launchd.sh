#!/usr/bin/env bash
# Install/refresh jarvis-osx-api as a user LaunchAgent (same pattern as
# jarvis-tts / jarvis-whisper-api). Must be a LaunchAgent, not a LaunchDaemon:
# AppleScript sends need a logged-in GUI session.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="${LAUNCHD_LABEL:-com.jarvis.osx-api}"
PORT="${OSX_API_PORT:-7723}"
ENV_FILE_PATH="${ENV_FILE_PATH:-$HOME/.jarvis/compose/.env}"
LOG_DIR="$HOME/Library/Logs/jarvis-osx-api"
PLIST_SRC="$ROOT/scripts/launchd/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "jarvis-osx-api is macOS-only" >&2
    exit 1
fi

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

sed -e "s|__ROOT__|$ROOT|g" \
    -e "s|__USER__|$USER|g" \
    -e "s|__PORT__|$PORT|g" \
    -e "s|__ENV_FILE__|$ENV_FILE_PATH|g" \
    "$PLIST_SRC" >"$PLIST_DST"

UID_NUM="$(id -u)"

# Tear down any existing agent and wait for the label to disappear — bootstrapping
# over a live agent races and can silently kill the replacement.
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
for _ in $(seq 1 50); do
    launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || break
    sleep 0.2
done

for _ in $(seq 1 5); do
    if launchctl bootstrap "gui/$UID_NUM" "$PLIST_DST" 2>/dev/null; then
        break
    fi
    sleep 1
done
launchctl enable "gui/$UID_NUM/$LABEL"
launchctl kickstart -k "gui/$UID_NUM/$LABEL"

echo "deployed $LABEL (port $PORT)"
echo "logs: $LOG_DIR"
echo ""
echo "REMINDER — TCC ceremony (one-time, and again after any venv rebuild):"
echo "  1. System Settings > Privacy & Security > Full Disk Access: add $ROOT/.venv/bin/python"
echo "  2. First send triggers the Automation prompt (Messages.app) — do a test send to yourself"
echo "  3. Contacts prompt appears on first /v1/contacts/resolve call"
