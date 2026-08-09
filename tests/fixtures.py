"""Test fixtures: attributedBody blob builder + a chat.db-shaped SQLite fixture.

The fixture schema is the minimal subset of the real chat.db that the service
queries. Column names and semantics mirror the real database (Apple-epoch
nanosecond dates, is_read/is_from_me flags, U+FFFC attachment markers).
"""

import sqlite3
import uuid
from pathlib import Path

APPLE_EPOCH_OFFSET = 978307200

# Byte-exact prefix observed in real post-Ventura attributedBody blobs, up to
# the '+' raw-bytes marker that precedes the length-prefixed UTF-8 payload.
ATTRIBUTED_BODY_PREFIX = (
    b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00"
    b"\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+"
)
ATTRIBUTED_BODY_SUFFIX = (
    b"\x86\x84\x02iI\x01\x92\x84\x84\x84\x0cNSDictionary\x00\x94\x84\x01i\x00\x92\x86\x86"
)


def _encode_length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x10000:
        return b"\x81" + n.to_bytes(2, "little")
    return b"\x82" + n.to_bytes(4, "little")


def make_attributed_body(text: str) -> bytes:
    raw = text.encode("utf-8")
    return ATTRIBUTED_BODY_PREFIX + _encode_length(len(raw)) + raw + ATTRIBUTED_BODY_SUFFIX


def unix_to_apple_ns(unix_ts: float) -> int:
    return int((unix_ts - APPLE_EPOCH_OFFSET) * 1_000_000_000)


_SCHEMA = """
CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE,
    text TEXT,
    attributedBody BLOB,
    handle_id INTEGER DEFAULT 0,
    date INTEGER DEFAULT 0,
    is_from_me INTEGER DEFAULT 0,
    is_read INTEGER DEFAULT 0,
    item_type INTEGER DEFAULT 0,
    associated_message_type INTEGER DEFAULT 0,
    cache_has_attachments INTEGER DEFAULT 0,
    error INTEGER DEFAULT 0
);
CREATE TABLE chat (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE,
    chat_identifier TEXT,
    display_name TEXT,
    style INTEGER DEFAULT 45
);
CREATE TABLE handle (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT,
    service TEXT DEFAULT 'iMessage'
);
CREATE TABLE chat_message_join (
    chat_id INTEGER,
    message_id INTEGER,
    message_date INTEGER
);
CREATE TABLE chat_handle_join (
    chat_id INTEGER,
    handle_id INTEGER
);
CREATE TABLE attachment (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    mime_type TEXT,
    transfer_name TEXT
);
CREATE TABLE message_attachment_join (
    message_id INTEGER,
    attachment_id INTEGER
);
"""

BASE_TIME = 1_754_700_000.0  # fixed "now" for deterministic fixtures


class ChatDBFixture:
    def __init__(self, path: Path):
        self.path = Path(path)
        conn = self._connect()
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_handle(self, handle_id: str, service: str = "iMessage") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO handle (id, service) VALUES (?, ?)", (handle_id, service)
            )
            return int(cur.lastrowid or 0)

    def add_chat(
        self,
        guid: str,
        identifier: str,
        display_name: str | None = None,
        style: int = 45,
        handle_rowids: list[int] | None = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO chat (guid, chat_identifier, display_name, style) VALUES (?, ?, ?, ?)",
                (guid, identifier, display_name, style),
            )
            chat_rowid = int(cur.lastrowid or 0)
            for h in handle_rowids or []:
                conn.execute(
                    "INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)",
                    (chat_rowid, h),
                )
            return chat_rowid

    def add_message(
        self,
        chat_rowid: int,
        text: str | None = None,
        attributed_text: str | None = None,
        handle_rowid: int | None = None,
        is_from_me: int = 0,
        is_read: int = 0,
        date_unix: float = BASE_TIME,
        attachment_mimes: list[str] | None = None,
        associated_message_type: int = 0,
        item_type: int = 0,
        error: int = 0,
        guid: str | None = None,
    ) -> tuple[int, str]:
        guid = guid or str(uuid.uuid4()).upper()
        body_blob = make_attributed_body(attributed_text) if attributed_text is not None else None
        date_ns = unix_to_apple_ns(date_unix)
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO message
                   (guid, text, attributedBody, handle_id, date, is_from_me, is_read,
                    item_type, associated_message_type, cache_has_attachments, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    guid,
                    text,
                    body_blob,
                    handle_rowid or 0,
                    date_ns,
                    is_from_me,
                    is_read,
                    item_type,
                    associated_message_type,
                    1 if attachment_mimes else 0,
                    error,
                ),
            )
            message_rowid = int(cur.lastrowid or 0)
            conn.execute(
                "INSERT INTO chat_message_join (chat_id, message_id, message_date) VALUES (?, ?, ?)",
                (chat_rowid, message_rowid, date_ns),
            )
            for mime in attachment_mimes or []:
                acur = conn.execute(
                    "INSERT INTO attachment (mime_type, transfer_name) VALUES (?, ?)",
                    (mime, "file"),
                )
                conn.execute(
                    "INSERT INTO message_attachment_join (message_id, attachment_id) VALUES (?, ?)",
                    (message_rowid, acur.lastrowid),
                )
        return message_rowid, guid

    def set_read(self, guid: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE message SET is_read = 1 WHERE guid = ?", (guid,))
