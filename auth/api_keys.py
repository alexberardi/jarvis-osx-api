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

# Two classes of scope, and therefore two classes of key (PRD decision #15).
#
# SPEAKER scopes reach a specific person's data and keep decision #9's binding:
# the key belongs to an enrolled speaker, and no speaker secret means refusal.
# SERVICE scopes reach impersonal capabilities where there IS no speaker — the
# caller is infrastructure and the input is something it already holds.
#
# A key may hold scopes from exactly ONE class. That is the whole containment
# guarantee: jarvis-ocr-service holding an `ocr:read` key cannot read a single
# message, and a compromise of it never becomes a compromise of iMessage.
SPEAKER_SCOPES = frozenset({"messages:read", "messages:send", "contacts:read", "shortcuts:run"})
SERVICE_SCOPES = frozenset({"ocr:read"})
VALID_SCOPES = SPEAKER_SCOPES | SERVICE_SCOPES


def class_of_scope(scope: str) -> str | None:
    if scope in SPEAKER_SCOPES:
        return "speaker"
    if scope in SERVICE_SCOPES:
        return "service"
    return None


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

    @property
    def key_class(self) -> str | None:
        """"speaker" or "service" — derived, never stored, so an old key file
        cannot disagree with the current partition."""
        classes = {class_of_scope(s) for s in self.scopes}
        return classes.pop() if len(classes) == 1 else None


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
        classes = {class_of_scope(s) for s in clean}
        if len(classes) > 1:
            raise InvalidScopeError(
                "a key may not mix speaker and service scopes "
                f"(speaker: {sorted(SPEAKER_SCOPES)}; service: {sorted(SERVICE_SCOPES)}). "
                "Mint two keys instead — the split is what keeps a service key away "
                "from personal data."
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
