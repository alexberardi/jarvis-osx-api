"""Read-aloud ledger (PRD decision #12).

The one deliberate exception to statelessness: a local SQLite set of message
GUIDs Jarvis has already spoken, so a text stays unread in chat.db (we never
write there) but doesn't resurface on the next "any new texts?". Entries are
pruned once the message is read on some device (is_read flips) or disappears.
"""

import sqlite3
import time
from pathlib import Path

from config import settings


class ReadAloudLedger:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else settings.ledger_db_path()
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS read_aloud (guid TEXT PRIMARY KEY, marked_at REAL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def mark(self, guids: list[str]) -> int:
        now = time.time()
        with self._connect() as conn:
            for guid in guids:
                conn.execute(
                    "INSERT OR REPLACE INTO read_aloud (guid, marked_at) VALUES (?, ?)",
                    (guid, now),
                )
        return len(guids)

    def marked(self) -> set[str]:
        with self._connect() as conn:
            return {r[0] for r in conn.execute("SELECT guid FROM read_aloud").fetchall()}

    def prune(self, still_unread: set[str]) -> None:
        """Drop entries no longer needed — the message was read elsewhere or deleted."""
        with self._connect() as conn:
            rows = conn.execute("SELECT guid FROM read_aloud").fetchall()
            for (guid,) in rows:
                if guid not in still_unread:
                    conn.execute("DELETE FROM read_aloud WHERE guid = ?", (guid,))
