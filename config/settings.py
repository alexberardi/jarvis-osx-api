"""Runtime configuration.

Everything is env-overridable so tests can point at fixture databases and a
throwaway data dir. This service deliberately has no settings-DB dependency —
it must work on a bare Mac with nothing but Python installed (decision #3:
self-contained, no jarvis-auth / config-service round-trips on the hot path).
"""

import os
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".jarvis" / "osx-api"


def data_dir() -> Path:
    d = Path(os.environ.get("OSX_API_DATA_DIR", str(DEFAULT_DATA_DIR)))
    d.mkdir(parents=True, exist_ok=True)
    return d


def chat_db_path() -> Path:
    return Path(
        os.environ.get("CHAT_DB_PATH", str(Path.home() / "Library" / "Messages" / "chat.db"))
    )


def api_keys_path() -> Path:
    return data_dir() / "api_keys.json"


def ledger_db_path() -> Path:
    return data_dir() / "read_aloud_ledger.db"


def server_host() -> str:
    return os.environ.get("SERVER_HOST", "0.0.0.0")


def server_port() -> int:
    return int(os.environ.get("SERVER_PORT", "7723"))
