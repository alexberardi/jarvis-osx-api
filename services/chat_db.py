"""Read-only access to the Messages database (~/Library/Messages/chat.db).

Requires Full Disk Access. Every connection is opened with mode=ro — this
module must NEVER write to chat.db (it is a live WAL database owned by
Messages.app; see PRD decision #12 rationale).
"""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from config import settings
from services import typedstream
from services.sanitize import sanitize_for_speech

APPLE_EPOCH_OFFSET = 978307200  # 2001-01-01 in unix seconds
GROUP_CHAT_STYLE = 43
DIRECT_CHAT_STYLE = 45


def apple_date_to_unix(value: int | float | None) -> float:
    if not value:
        return 0.0
    v = float(value)
    if v > 1e12:  # nanoseconds since 2001 (modern macOS); older DBs stored seconds
        v /= 1e9
    return v + APPLE_EPOCH_OFFSET


def unix_to_apple_ns(unix_ts: float) -> int:
    return int((unix_ts - APPLE_EPOCH_OFFSET) * 1_000_000_000)


class ChatDBUnreadable(Exception):
    """chat.db could not be opened/queried — almost always missing Full Disk Access."""


@dataclass
class ChatMessage:
    guid: str
    chat_rowid: int
    chat_guid: str
    chat_identifier: str
    chat_display_name: str | None
    is_group: bool
    sender_handle: str | None
    is_from_me: bool
    text: str
    spoken_text: str
    timestamp: float  # unix seconds
    has_attachments: bool


@dataclass
class ChatInfo:
    rowid: int
    guid: str
    identifier: str
    display_name: str | None
    is_group: bool


_MESSAGE_SELECT = """
SELECT m.ROWID AS message_rowid, m.guid, m.text, m.attributedBody,
       m.date, m.is_from_me, m.cache_has_attachments, m.error,
       h.id AS handle,
       c.ROWID AS chat_rowid, c.guid AS chat_guid,
       c.chat_identifier, c.display_name, c.style
FROM message m
JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
JOIN chat c ON c.ROWID = cmj.chat_id
LEFT JOIN handle h ON h.ROWID = m.handle_id
"""

# item_type != 0 are system rows (group renames, etc.); associated_message_type
# != 0 are tapbacks/edits — neither is a readable message.
_REAL_MESSAGE_FILTER = "m.item_type = 0 AND m.associated_message_type = 0"


class ChatDB:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else settings.chat_db_path()

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error as exc:
            raise ChatDBUnreadable(str(exc)) from exc
        conn.row_factory = sqlite3.Row
        return conn

    def probe(self) -> bool:
        try:
            conn = self._connect()
            try:
                conn.execute("SELECT ROWID FROM message LIMIT 1").fetchone()
            finally:
                conn.close()
            return True
        except (ChatDBUnreadable, sqlite3.Error):
            return False

    # ---------- read path ----------

    def unread(self) -> list[ChatMessage]:
        conn = self._connect()
        try:
            rows = conn.execute(
                _MESSAGE_SELECT
                + f"WHERE m.is_from_me = 0 AND m.is_read = 0 AND {_REAL_MESSAGE_FILTER} "
                + "ORDER BY m.date ASC"
            ).fetchall()
            return [self._to_message(conn, r) for r in rows]
        except sqlite3.Error as exc:
            raise ChatDBUnreadable(str(exc)) from exc
        finally:
            conn.close()

    def thread(self, chat_rowid: int, limit: int = 30) -> list[ChatMessage]:
        conn = self._connect()
        try:
            rows = conn.execute(
                _MESSAGE_SELECT
                + f"WHERE c.ROWID = ? AND {_REAL_MESSAGE_FILTER} "
                + "ORDER BY m.date DESC LIMIT ?",
                (chat_rowid, limit),
            ).fetchall()
            return [self._to_message(conn, r) for r in reversed(rows)]
        except sqlite3.Error as exc:
            raise ChatDBUnreadable(str(exc)) from exc
        finally:
            conn.close()

    def style_context(
        self,
        chat_rowid: int,
        max_messages: int = 20,
        char_cap: int = 1500,
        sparse_floor: int = 5,
    ) -> dict:
        """Last N outbound message bodies in a thread — CC's tone few-shots.

        Returns {"messages": [...oldest-first...], "sparse": bool}; below the
        floor returns empty + sparse=True so CC uses a neutral default instead
        of aping a 2-message sample (PRD open Q2 defaults).
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                _MESSAGE_SELECT
                + f"WHERE c.ROWID = ? AND m.is_from_me = 1 AND {_REAL_MESSAGE_FILTER} "
                + "ORDER BY m.date DESC LIMIT ?",
                (chat_rowid, max_messages),
            ).fetchall()
        except sqlite3.Error as exc:
            raise ChatDBUnreadable(str(exc)) from exc
        finally:
            conn.close()

        bodies: list[str] = []
        total = 0
        for row in rows:  # newest first; keep the most recent under the cap
            body = _row_body(row)
            if not body:
                continue
            if total + len(body) > char_cap and bodies:
                break
            bodies.append(body)
            total += len(body)
        if len(bodies) < sparse_floor:
            return {"messages": [], "sparse": True}
        return {"messages": list(reversed(bodies)), "sparse": False}

    def still_unread(self, guids: list[str]) -> set[str]:
        """Which of these GUIDs are still present and unread (ledger pruning)."""
        if not guids:
            return set()
        conn = self._connect()
        try:
            placeholders = ",".join("?" * len(guids))
            rows = conn.execute(
                f"SELECT guid FROM message WHERE guid IN ({placeholders}) "
                "AND is_read = 0 AND is_from_me = 0",
                guids,
            ).fetchall()
            return {r["guid"] for r in rows}
        except sqlite3.Error as exc:
            raise ChatDBUnreadable(str(exc)) from exc
        finally:
            conn.close()

    # ---------- chat lookup / send support ----------

    def chat_by_guid(self, chat_guid: str) -> ChatInfo | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM chat WHERE guid = ?", (chat_guid,)).fetchone()
            return _to_chat_info(row) if row else None
        finally:
            conn.close()

    def chat_by_rowid(self, chat_rowid: int) -> ChatInfo | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM chat WHERE ROWID = ?", (chat_rowid,)).fetchone()
            return _to_chat_info(row) if row else None
        finally:
            conn.close()

    def direct_chat_for_handle(self, handle: str) -> ChatInfo | None:
        """Most-recently-active existing 1:1 chat whose handle matches."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT c.*, h.id AS handle_value,
                          (SELECT MAX(message_date) FROM chat_message_join
                           WHERE chat_id = c.ROWID) AS last_activity
                   FROM chat c
                   JOIN chat_handle_join chj ON chj.chat_id = c.ROWID
                   JOIN handle h ON h.ROWID = chj.handle_id
                   WHERE c.style = ?
                   ORDER BY last_activity DESC""",
                (DIRECT_CHAT_STYLE,),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            if _handles_match(handle, row["handle_value"]):
                return _to_chat_info(row)
        return None

    def verify_sent(
        self, chat_rowid: int, text: str, since_unix: float, now: float | None = None
    ) -> str:
        """Post-send verification (decision #13): 'verified' | 'failed' | 'not_found'.

        Looks for an outbound row in the chat, at/after since_unix, whose body
        matches the sent text. error != 0 on that row means Messages recorded a
        send failure.
        """
        del now  # reserved for future recency asserts; keeps the signature stable
        conn = self._connect()
        try:
            rows = conn.execute(
                _MESSAGE_SELECT
                + f"WHERE c.ROWID = ? AND m.is_from_me = 1 AND m.date >= ? AND {_REAL_MESSAGE_FILTER} "
                + "ORDER BY m.date DESC",
                (chat_rowid, unix_to_apple_ns(since_unix)),
            ).fetchall()
        except sqlite3.Error as exc:
            raise ChatDBUnreadable(str(exc)) from exc
        finally:
            conn.close()
        for row in rows:
            if _row_body(row) == text:
                return "failed" if row["error"] else "verified"
        return "not_found"

    # ---------- helpers ----------

    def _to_message(self, conn: sqlite3.Connection, row: sqlite3.Row) -> ChatMessage:
        body = _row_body(row)
        mimes: list[str] = []
        if row["cache_has_attachments"]:
            mimes = [
                r["mime_type"]
                for r in conn.execute(
                    """SELECT a.mime_type FROM attachment a
                       JOIN message_attachment_join maj ON maj.attachment_id = a.ROWID
                       WHERE maj.message_id = ?""",
                    (row["message_rowid"],),
                ).fetchall()
            ]
        return ChatMessage(
            guid=row["guid"],
            chat_rowid=row["chat_rowid"],
            chat_guid=row["chat_guid"],
            chat_identifier=row["chat_identifier"],
            chat_display_name=row["display_name"] or None,
            is_group=row["style"] == GROUP_CHAT_STYLE,
            sender_handle=row["handle"],
            is_from_me=bool(row["is_from_me"]),
            text=body,
            spoken_text=sanitize_for_speech(body, mimes),
            timestamp=apple_date_to_unix(row["date"]),
            has_attachments=bool(row["cache_has_attachments"]),
        )


def _row_body(row: sqlite3.Row) -> str:
    if row["text"]:
        return row["text"]
    return typedstream.extract_text(row["attributedBody"]) or ""


def _to_chat_info(row: sqlite3.Row) -> ChatInfo:
    return ChatInfo(
        rowid=row["ROWID"],
        guid=row["guid"],
        identifier=row["chat_identifier"],
        display_name=row["display_name"] or None,
        is_group=row["style"] == GROUP_CHAT_STYLE,
    )


def _handles_match(query: str, candidate: str | None) -> bool:
    if not candidate:
        return False
    if query.strip().lower() == candidate.strip().lower():
        return True
    q_digits = _digits(query)
    c_digits = _digits(candidate)
    if len(q_digits) >= 7 and len(c_digits) >= 7:
        return q_digits[-10:] == c_digits[-10:]
    return False


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def now_unix() -> float:
    return time.time()
