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


class OCRRequest(BaseModel):
    """Mirrors jarvis-ocr-service's OCRProvider.process() signature, so the
    remote provider on that side is a transport shim with nothing to translate."""

    image_base64: str = Field(min_length=1)
    language_hints: list[str] | None = None
    return_boxes: bool = True
    mode: str = "document"  # accepted for parity; Vision has no mode switch
