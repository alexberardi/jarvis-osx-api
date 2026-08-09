import subprocess

import pytest

from services.chat_db import ChatDB
from services.sender import MessageSender
from tests.fixtures import BASE_TIME, ChatDBFixture

CHAT_GUID = "iMessage;-;+15551234567"


@pytest.fixture()
def fx(tmp_path):
    fixture = ChatDBFixture(tmp_path / "chat.db")
    h = fixture.add_handle("+15551234567")
    fixture.add_chat(CHAT_GUID, "+15551234567", handle_rowids=[h])
    return fixture


@pytest.fixture()
def db(fx):
    return ChatDB(fx.path)


def _sender(db, runner, **kwargs):
    kwargs.setdefault("verify_timeout", 0.3)
    kwargs.setdefault("poll_interval", 0.05)
    return MessageSender(db, osascript_runner=runner, **kwargs)


def _delivering_runner(fx, error=0):
    """Fake osascript that mimics Messages actually delivering: inserts the
    outbound row into the fixture chat.db (dated now, like the real DB)."""

    def run(chat_guid, text):
        import time

        fx.add_message(1, text=text, is_from_me=1, is_read=1, date_unix=time.time(), error=error)
        return 0, "", ""

    return run


def test_send_verified(fx, db):
    result = _sender(db, _delivering_runner(fx)).send("on my way", chat_guid=CHAT_GUID)
    assert result.status == "sent"
    assert result.ok
    assert result.chat_guid == CHAT_GUID


def test_send_by_handle_resolves_existing_chat(fx, db):
    result = _sender(db, _delivering_runner(fx)).send("on my way", handle="555-123-4567")
    assert result.status == "sent"


def test_no_such_chat(db):
    result = _sender(db, _delivering_runner(None)).send("hi", handle="+19998887777")
    assert result.status == "no_such_chat"


def test_group_chat_refused_before_osascript(fx, db):
    h = fx.add_handle("+15550001111")
    fx.add_chat("chatABCgroup", "chatABCgroup", style=43, handle_rowids=[h])
    calls = []

    def runner(chat_guid, text):
        calls.append(chat_guid)
        return 0, "", ""

    result = _sender(db, runner).send("hi all", chat_guid="chatABCgroup")
    assert result.status == "group_unsupported"
    assert calls == []


def test_applescript_error_surfaces(fx, db):
    result = _sender(db, lambda g, t: (1, "", "execution error: -1728")).send(
        "hi", chat_guid=CHAT_GUID
    )
    assert result.status == "applescript_error"
    assert "-1728" in result.detail


def test_applescript_timeout(fx, db):
    def runner(chat_guid, text):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=30)

    assert _sender(db, runner).send("hi", chat_guid=CHAT_GUID).status == "applescript_error"


def test_ghost_send_reported_unverified(fx, db):
    """AppleScript returns cleanly but nothing lands in chat.db — the Tahoe
    ghost-message failure mode must NOT be reported as success."""
    result = _sender(db, lambda g, t: (0, "", "")).send("hi", chat_guid=CHAT_GUID)
    assert result.status == "unverified"
    assert not result.ok


def test_messages_error_row_reported_send_failed(fx, db):
    result = _sender(db, _delivering_runner(fx, error=22)).send("hi", chat_guid=CHAT_GUID)
    assert result.status == "send_failed"


def test_preexisting_identical_message_does_not_fake_verification(fx, db):
    fx.add_message(1, text="hi", is_from_me=1, is_read=1, date_unix=BASE_TIME - 3600)
    result = _sender(db, lambda g, t: (0, "", "")).send("hi", chat_guid=CHAT_GUID)
    assert result.status == "unverified"
