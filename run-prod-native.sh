#!/usr/bin/env bash
# launchd entry point (see scripts/launchd/com.jarvis.osx-api.plist).
# NOTE: TCC grants (Full Disk Access / Automation / Contacts) attach to the
# venv's python binary — rebuilding the venv or upgrading Python silently
# revokes them. After any interpreter change, redo the TCC ceremony.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
SERVER_HOST="${SERVER_HOST:-0.0.0.0}"
PORT="${OSX_API_PORT:-7723}"
VENV="$ROOT/.venv"
SENTINEL="$VENV/.deps_installed"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export JARVIS_CONFIG_URL="${JARVIS_CONFIG_URL:-http://localhost:${CONFIG_SERVICE_PORT:-7700}}"
export JARVIS_CONFIG_URL_STYLE="${JARVIS_CONFIG_URL_STYLE:-external}"

PYBIN=""
for CAND in python3.13 python3.12 python3.11; do
    if command -v "$CAND" >/dev/null 2>&1; then
        PYBIN="$CAND"
        break
    fi
done
if [ -z "$PYBIN" ]; then
    if command -v python3 >/dev/null 2>&1 \
        && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
        PYBIN=python3
    else
        echo "jarvis-osx-api requires Python >= 3.11" >&2
        exit 1
    fi
fi

[ -d "$VENV" ] || "$PYBIN" -m venv "$VENV"

if [ ! -f "$SENTINEL" ] || [ "$ROOT/pyproject.toml" -nt "$SENTINEL" ]; then
    "$VENV/bin/pip" install -q -e "$ROOT[contacts,vision]"
    touch "$SENTINEL"
fi

exec "$VENV/bin/uvicorn" main:app --host "$SERVER_HOST" --port "$PORT"
