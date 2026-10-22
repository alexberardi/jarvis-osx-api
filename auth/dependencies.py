"""FastAPI auth dependency enforcing per-capability scopes (PRD decision #3)."""

from fastapi import Header, HTTPException

from auth.api_keys import ApiKey, ApiKeyStore, class_of_scope


def require_scope(scope: str):
    async def dependency(authorization: str | None = Header(default=None)) -> ApiKey:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing_bearer_token")
        raw_key = authorization.split(" ", 1)[1].strip()
        key = ApiKeyStore().verify(raw_key)
        if key is None:
            raise HTTPException(status_code=401, detail="invalid_api_key")
        if not key.has_scope(scope):
            raise HTTPException(status_code=403, detail=f"missing_scope:{scope}")
        # Belt and braces for decision #15. generate() already refuses to mint a
        # mixed-class key, but the store is a JSON file on disk: a hand-edited
        # key must not be able to cross the speaker/service line either.
        if key.key_class != class_of_scope(scope):
            raise HTTPException(status_code=403, detail=f"wrong_key_class:{scope}")
        return key

    return dependency
