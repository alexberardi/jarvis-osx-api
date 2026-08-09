"""Extract plain text from Messages `attributedBody` typedstream blobs.

Post-Ventura the `text` column in chat.db is often NULL and the body lives in
`attributedBody` — a typedstream-serialized NSAttributedString. This is a
minimal extractor, not a full typedstream parser: it locates the first
NSString/NSMutableString class reference and decodes the length-prefixed UTF-8
payload that follows. Callers must fall back to the `text` column when this
returns None.
"""

STREAMTYPED_MAGIC = b"\x04\x0bstreamtyped"

_CLASS_MARKERS = (b"NSString", b"NSMutableString")

# After the class name, typedstream emits a handful of tag bytes ending in
# 0x2b ('+', the raw-bytes type marker) immediately before the length prefix.
# The markers sit within a few bytes of the class name in every observed blob.
_PLUS_SCAN_WINDOW = 16


def extract_text(blob: bytes | None) -> str | None:
    if not blob or not blob.startswith(STREAMTYPED_MAGIC):
        return None
    for marker in _CLASS_MARKERS:
        idx = blob.find(marker)
        if idx == -1:
            continue
        text = _read_string_after(blob, idx + len(marker))
        if text is not None:
            return text
    return None


def _read_string_after(blob: bytes, pos: int) -> str | None:
    window = blob[pos : pos + _PLUS_SCAN_WINDOW]
    plus = window.find(b"+")
    if plus == -1:
        return None
    i = pos + plus + 1
    parsed = _read_length(blob, i)
    if parsed is None:
        return None
    length, i = parsed
    raw = blob[i : i + length]
    if len(raw) < length:
        return None
    return raw.decode("utf-8", errors="replace")


def _read_length(blob: bytes, i: int) -> tuple[int, int] | None:
    if i >= len(blob):
        return None
    b0 = blob[i]
    if b0 == 0x81:
        if i + 3 > len(blob):
            return None
        return int.from_bytes(blob[i + 1 : i + 3], "little"), i + 3
    if b0 == 0x82:
        if i + 5 > len(blob):
            return None
        return int.from_bytes(blob[i + 1 : i + 5], "little"), i + 5
    return b0, i + 1
