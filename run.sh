#!/bin/bash
# jarvis-osx-api dev runner (macOS only — native TCC APIs).
set -e
cd "$(dirname "$0")"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "jarvis-osx-api is macOS-only (chat.db / AppleScript / Contacts need a Mac)" >&2
    exit 1
fi

if [ ! -d ".venv" ]; then
    for PY in python3.13 python3.12 python3.11; do
        if command -v "$PY" >/dev/null 2>&1; then
            "$PY" -m venv .venv
            break
        fi
    done
fi
if [ ! -d ".venv" ]; then
    echo "no python >= 3.11 found (brew install python@3.12)" >&2
    exit 1
fi
source .venv/bin/activate

set -a
[ -f .env ] && source .env
set +a

JARVIS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "${JARVIS_ROOT}/scripts/install-clients.sh" ]; then
    source "${JARVIS_ROOT}/scripts/install-clients.sh"
    install_jarvis_clients log-client config-client
fi

pip install -q -e ".[contacts,dev]"

exec uvicorn main:app --host "${SERVER_HOST:-0.0.0.0}" --port "${OSX_API_PORT:-7723}" --reload
