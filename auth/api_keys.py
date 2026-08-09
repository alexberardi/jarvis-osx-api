"""Locally-generated scoped bearer API keys (PRD decision #3).

Follows the stack precedent for self-minted keys (command-center provisioning
tokens): prefixed `secrets.token_urlsafe` raw value, SHA-256 hash stored, raw
shown exactly once. SHA-256 rather than bcrypt because keys are verified on
every request. No jarvis-auth round-trip — the service stays self-contained.
"""

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from config import settings

KEY_PREFIX = "joxk_"
VALID_SCOPES = frozenset({"messages:read", "messages:send", "contacts:read", "shortcuts:run"})


class InvalidScopeError(ValueError):
    pass


@dataclass
class ApiKey:
    key_id: str
    name: str | None
    scopes: list[str]
    created_at: float

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class ApiKeyStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else settings.api_keys_path()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"keys": []}
        return json.loads(self.path.read_text())

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))
        os.chmod(self.path, 0o600)

    def generate(self, scopes: list[str], name: str | None = None) -> tuple[str, ApiKey]:
        clean = sorted(set(scopes))
        invalid = [s for s in clean if s not in VALID_SCOPES]
        if invalid or not clean:
            raise InvalidScopeError(
                f"invalid scopes: {invalid or 'none given'}; valid: {sorted(VALID_SCOPES)}"
            )
        raw_key = KEY_PREFIX + secrets.token_urlsafe(32)
        record = {
            "id": secrets.token_hex(4),
            "name": name,
            "hash": _hash(raw_key),
            "scopes": clean,
            "created_at": time.time(),
        }
        data = self._load()
        data["keys"].append(record)
        self._save(data)
        return raw_key, _to_api_key(record)

    def verify(self, raw_key: str) -> ApiKey | None:
        if not raw_key or not raw_key.startswith(KEY_PREFIX):
            return None
        h = _hash(raw_key)
        for record in self._load()["keys"]:
            if secrets.compare_digest(record["hash"], h):
                return _to_api_key(record)
        return None

    def list_keys(self) -> list[ApiKey]:
        return [_to_api_key(r) for r in self._load()["keys"]]

    def revoke(self, key_id: str) -> bool:
        data = self._load()
        before = len(data["keys"])
        data["keys"] = [r for r in data["keys"] if r["id"] != key_id]
        if len(data["keys"]) == before:
            return False
        self._save(data)
        return True


def _to_api_key(record: dict) -> ApiKey:
    return ApiKey(
        key_id=record["id"],
        name=record.get("name"),
        scopes=list(record["scopes"]),
        created_at=record["created_at"],
    )
