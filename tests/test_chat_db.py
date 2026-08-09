import pytest

from services.chat_db import ChatDB, apple_date_to_unix
from tests.fixtures import BASE_TIME, ChatDBFixture


@pytest.fixture()
def fx(tmp_path):
    return ChatDBFixture(tmp_path / "chat.db")


@pytest.fixture()
def db(fx):
    return ChatDB(fx.path)


def _basic_chat(fx, handle="+15551234567", guid="iMessage;-;+15551234567"):
    h = fx.add_handle(handle)
    c = fx.add_chat(guid, handle, handle_rowids=[h])
    return h, c


class TestProbe:
    def test_probe_ok(self, db):
        assert db.probe() is True

    def test_probe_missing_file(self, tmp_path):
        assert ChatDB(tmp_path / "nope.db").probe() is False


class TestUnread:
    def test_returns_unread_incoming(self, fx, db):
        h, c = _basic_chat(fx)
        _, guid = fx.add_message(c, text="hey there", handle_rowid=h)
        msgs = db.unread()
        assert [m.guid for m in msgs] == [guid]
        m = msgs[0]
        assert m.text == "hey there"
        assert m.sender_handle == "+15551234567"
        assert m.chat_guid == "iMessage;-;+15551234567"
        assert not m.is_group
        assert m.timestamp == pytest.approx(BASE_TIME)

    def test_excludes_read_outgoing_tapbacks_and_system_rows(self, fx, db):
        h, c = _basic_chat(fx)
        fx.add_message(c, text="already read", handle_rowid=h, is_read=1)
        fx.add_message(c, text="mine", is_from_me=1)
        fx.add_message(c, text="Loved it", handle_rowid=h, associated_message_type=2000)
        fx.add_message(c, text=None, handle_rowid=h, item_type=3)
        _, keep = fx.add_message(c, text="the real one", handle_rowid=h)
        assert [m.guid for m in db.unread()] == [keep]

    def test_decodes_attributed_body_when_text_null(self, fx, db):
        h, c = _basic_chat(fx)
        fx.add_message(c, text=None, attributed_text="body from blob", handle_rowid=h)
        assert db.unread()[0].text == "body from blob"

    def test_attachment_gets_spoken_placeholder(self, fx, db):
        h, c = _basic_chat(fx)
        fx.add_message(c, text="￼", handle_rowid=h, attachment_mimes=["image/jpeg"])
        m = db.unread()[0]
        assert m.spoken_text == "[an image]"
        assert m.has_attachments

    def test_ordered_oldest_first(self, fx, db):
        h, c = _basic_chat(fx)
        _, g2 = fx.add_message(c, text="second", handle_rowid=h, date_unix=BASE_TIME + 60)
        _, g1 = fx.add_message(c, text="first", handle_rowid=h, date_unix=BASE_TIME)
        assert [m.guid for m in db.unread()] == [g1, g2]


class TestThread:
    def test_returns_both_directions_in_order(self, fx, db):
        h, c = _basic_chat(fx)
        fx.add_message(c, text="them 1", handle_rowid=h, is_read=1, date_unix=BASE_TIME)
        fx.add_message(c, text="me 1", is_from_me=1, date_unix=BASE_TIME + 10)
        fx.add_message(c, text="them 2", handle_rowid=h, date_unix=BASE_TIME + 20)
        assert [m.text for m in db.thread(c)] == ["them 1", "me 1", "them 2"]

    def test_limit_keeps_most_recent(self, fx, db):
        h, c = _basic_chat(fx)
        for i in range(5):
            fx.add_message(c, text=f"msg {i}", handle_rowid=h, date_unix=BASE_TIME + i)
        assert [m.text for m in db.thread(c, limit=2)] == ["msg 3", "msg 4"]


class TestStyleContext:
    def test_sparse_below_floor(self, fx, db):
        _, c = _basic_chat(fx)
        for i in range(3):
            fx.add_message(c, text=f"mine {i}", is_from_me=1, date_unix=BASE_TIME + i)
        assert db.style_context(c) == {"messages": [], "sparse": True}

    def test_returns_outbound_only_oldest_first(self, fx, db):
        h, c = _basic_chat(fx)
        fx.add_message(c, text="theirs", handle_rowid=h)
        for i in range(6):
            fx.add_message(c, text=f"mine {i}", is_from_me=1, date_unix=BASE_TIME + i)
        result = db.style_context(c)
        assert result["sparse"] is False
        assert result["messages"] == [f"mine {i}" for i in range(6)]

    def test_char_cap_trims_then_floor_applies(self, fx, db):
        _, c = _basic_chat(fx)
        for i in range(10):
            fx.add_message(c, text="x" * 400, is_from_me=1, date_unix=BASE_TIME + i)
        result = db.style_context(c, char_cap=1500, sparse_floor=3)
        # 1500 // 400 -> only 3 fit under the cap (first always kept)
        assert result["sparse"] is False
        assert len(result["messages"]) == 3


class TestStillUnread:
    def test_filters_to_present_and_unread(self, fx, db):
        h, c = _basic_chat(fx)
        _, g1 = fx.add_message(c, text="a", handle_rowid=h)
        _, g2 = fx.add_message(c, text="b", handle_rowid=h)
        fx.set_read(g2)
        assert db.still_unread([g1, g2, "GHOST-GUID"]) == {g1}

    def test_empty_input(self, db):
        assert db.still_unread([]) == set()


class TestChatLookup:
    def test_by_guid(self, fx, db):
        _, c = _basic_chat(fx)
        info = db.chat_by_guid("iMessage;-;+15551234567")
        assert info is not None and info.rowid == c and not info.is_group

    def test_direct_chat_for_handle_exact_and_normalized(self, fx, db):
        _, c = _basic_chat(fx)
        for query in ("+15551234567", "5551234567", "(555) 123-4567"):
            info = db.direct_chat_for_handle(query)
            assert info is not None and info.rowid == c, query

    def test_direct_chat_ignores_groups(self, fx, db):
        h = fx.add_handle("+15551234567")
        fx.add_chat("chat123group", "chat123group", style=43, handle_rowids=[h])
        assert db.direct_chat_for_handle("+15551234567") is None

    def test_picks_most_recently_active_chat(self, fx, db):
        h = fx.add_handle("+15551234567")
        c_old = fx.add_chat("iMessage;-;+15551234567", "+15551234567", handle_rowids=[h])
        c_new = fx.add_chat("SMS;-;+15551234567", "+15551234567", handle_rowids=[h])
        fx.add_message(c_old, text="old", handle_rowid=h, is_read=1, date_unix=BASE_TIME - 500)
        fx.add_message(c_new, text="new", handle_rowid=h, is_read=1, date_unix=BASE_TIME)
        info = db.direct_chat_for_handle("+15551234567")
        assert info is not None and info.rowid == c_new

    def test_email_handle_matches_case_insensitive(self, fx, db):
        h = fx.add_handle("friend@example.com")
        c = fx.add_chat("iMessage;-;friend@example.com", "friend@example.com", handle_rowids=[h])
        info = db.direct_chat_for_handle("Friend@Example.com")
        assert info is not None and info.rowid == c


class TestVerifySent:
    def test_verified(self, fx, db):
        _, c = _basic_chat(fx)
        fx.add_message(c, text="on my way", is_from_me=1, date_unix=BASE_TIME)
        assert db.verify_sent(c, "on my way", since_unix=BASE_TIME - 10) == "verified"

    def test_not_found_when_no_matching_row(self, fx, db):
        _, c = _basic_chat(fx)
        fx.add_message(c, text="different text", is_from_me=1, date_unix=BASE_TIME)
        assert db.verify_sent(c, "on my way", since_unix=BASE_TIME - 10) == "not_found"

    def test_old_identical_row_does_not_count(self, fx, db):
        _, c = _basic_chat(fx)
        fx.add_message(c, text="on my way", is_from_me=1, date_unix=BASE_TIME - 3600)
        assert db.verify_sent(c, "on my way", since_unix=BASE_TIME - 10) == "not_found"

    def test_failed_when_error_flag_set(self, fx, db):
        _, c = _basic_chat(fx)
        fx.add_message(c, text="on my way", is_from_me=1, date_unix=BASE_TIME, error=22)
        assert db.verify_sent(c, "on my way", since_unix=BASE_TIME - 10) == "failed"


def test_apple_date_conversion_handles_ns_and_seconds():
    assert apple_date_to_unix(0) == 0.0
    ns = (BASE_TIME - 978307200) * 1_000_000_000
    assert apple_date_to_unix(ns) == pytest.approx(BASE_TIME)
    secs = BASE_TIME - 978307200
    assert apple_date_to_unix(secs) == pytest.approx(BASE_TIME)
