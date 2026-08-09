"""FastAPI auth dependency enforcing per-capability scopes (PRD decision #3)."""

from fastapi import Header, HTTPException

from auth.api_keys import ApiKey, ApiKeyStore


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
        return key

    return dependency
