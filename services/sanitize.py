"""Voice-read sanitization (service-side half — PRD open Q4).

The service replaces attachments and URLs because it sees the raw rows and
attachment MIME types; burst-collapsing and spoken phrasing stay CC-side.

chat.db represents each inline attachment as U+FFFC (object replacement
character) in the message text; we substitute placeholders positionally and
append any leftovers.
"""

import re

OBJECT_REPLACEMENT_CHAR = "￼"

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_WS_RE = re.compile(r"[ \t]{2,}")


def attachment_placeholder(mime_type: str | None) -> str:
    if not mime_type:
        return "[an attachment]"
    major = mime_type.split("/", 1)[0].lower()
    return {
        "image": "[an image]",
        "video": "[a video]",
        "audio": "[an audio message]",
    }.get(major, "[an attachment]")


def sanitize_for_speech(text: str | None, attachment_mime_types: list[str] | None = None) -> str:
    mimes = list(attachment_mime_types or [])
    out = text or ""

    def _next_placeholder(_: re.Match) -> str:
        return attachment_placeholder(mimes.pop(0)) if mimes else "[an attachment]"

    out = re.sub(OBJECT_REPLACEMENT_CHAR, _next_placeholder, out)
    out = _URL_RE.sub("[a link]", out)
    # Attachments with no inline U+FFFC marker still deserve a mention.
    if mimes:
        extras = " ".join(attachment_placeholder(m) for m in mimes)
        out = f"{out} {extras}" if out.strip() else extras
    return _WS_RE.sub(" ", out).strip()
