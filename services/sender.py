"""iMessage send path (PRD decisions #5, #13).

AppleScript automation of Messages.app — requires the Automation TCC grant and
a logged-in GUI session. v1 constraints enforced here:
- existing 1:1 chats only (group sends are BROKEN on macOS 26 — ghost messages)
- post-send verification against chat.db before reporting success; an
  AppleScript clean return is never trusted on its own.

The text is passed to osascript as an argv item (never interpolated into the
script source), which sidesteps quote-escaping entirely.
"""

import subprocess
import time
from dataclasses import dataclass

from services.chat_db import ChatDB, ChatInfo

_SEND_SCRIPT = """
on run argv
    set theChatId to item 1 of argv
    set theText to item 2 of argv
    tell application "Messages"
        send theText to chat id theChatId
    end tell
end run
"""

# Verification looks for outbound rows from slightly before the send call to
# absorb clock skew between our clock and the row's date.
_CLOCK_SLOP_SECONDS = 5.0


@dataclass
class SendResult:
    status: str  # sent | no_such_chat | group_unsupported | applescript_error | send_failed | unverified
    chat_guid: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "sent"


def _run_osascript(chat_guid: str, text: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["osascript", "-", chat_guid, text],
        input=_SEND_SCRIPT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


class MessageSender:
    def __init__(
        self,
        chat_db: ChatDB,
        osascript_runner=None,
        verify_timeout: float = 8.0,
        poll_interval: float = 0.5,
    ):
        self.chat_db = chat_db
        self._osascript = osascript_runner or _run_osascript
        self.verify_timeout = verify_timeout
        self.poll_interval = poll_interval

    def send(
        self,
        text: str,
        chat_guid: str | None = None,
        handle: str | None = None,
    ) -> SendResult:
        chat = self._resolve_chat(chat_guid, handle)
        if chat is None:
            return SendResult(status="no_such_chat", detail="no existing chat matches")
        if chat.is_group:
            return SendResult(
                status="group_unsupported",
                chat_guid=chat.guid,
                detail="group sends are disabled in v1 (macOS 26 AppleScript ghost-message bug)",
            )

        since = time.time() - _CLOCK_SLOP_SECONDS
        try:
            returncode, _, stderr = self._osascript(chat.guid, text)
        except subprocess.TimeoutExpired:
            return SendResult(status="applescript_error", chat_guid=chat.guid, detail="osascript timed out")
        if returncode != 0:
            return SendResult(
                status="applescript_error", chat_guid=chat.guid, detail=stderr.strip() or f"exit {returncode}"
            )

        deadline = time.monotonic() + self.verify_timeout
        while True:
            verdict = self.chat_db.verify_sent(chat.rowid, text, since)
            if verdict == "verified":
                return SendResult(status="sent", chat_guid=chat.guid)
            if verdict == "failed":
                return SendResult(
                    status="send_failed",
                    chat_guid=chat.guid,
                    detail="Messages recorded a send error for the message row",
                )
            if time.monotonic() >= deadline:
                return SendResult(
                    status="unverified",
                    chat_guid=chat.guid,
                    detail="AppleScript returned cleanly but the message never appeared in chat.db",
                )
            time.sleep(self.poll_interval)

    def _resolve_chat(self, chat_guid: str | None, handle: str | None) -> ChatInfo | None:
        if chat_guid:
            return self.chat_db.chat_by_guid(chat_guid)
        if handle:
            return self.chat_db.direct_chat_for_handle(handle)
        return None
