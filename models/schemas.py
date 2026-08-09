from pydantic import BaseModel, Field


class SendRequest(BaseModel):
    chat_id: str | None = None  # chat GUID from a messages listing
    handle: str | None = None  # phone/email — must resolve to an existing 1:1 chat
    text: str = Field(min_length=1)


class MarkReadRequest(BaseModel):
    guids: list[str] = Field(min_length=1)


class ShortcutRunRequest(BaseModel):
    name: str = Field(min_length=1)
    input: str | None = None
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
