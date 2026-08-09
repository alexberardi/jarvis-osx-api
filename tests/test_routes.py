import api.message_routes as message_routes_mod
import api.shortcut_routes as shortcut_routes_mod
from services.sender import SendResult
from services.shortcuts import ShortcutResult
from tests.fixtures import BASE_TIME

CHAT_GUID = "iMessage;-;+15551234567"


def _seed_chat(fx):
    h = fx.add_handle("+15551234567")
    c = fx.add_chat(CHAT_GUID, "+15551234567", handle_rowids=[h])
    return h, c


class TestAuth:
    def test_missing_token_401(self, client):
        assert client.get("/v1/messages/unread").status_code == 401

    def test_bad_token_401(self, client):
        r = client.get("/v1/messages/unread", headers={"Authorization": "Bearer joxk_nope"})
        assert r.status_code == 401

    def test_wrong_scope_403(self, client, key_factory):
        headers = key_factory("contacts:read")
        assert client.get("/v1/messages/unread", headers=headers).status_code == 403

    def test_health_needs_no_auth(self, client):
        assert client.get("/health").status_code == 200


class TestUnreadEndpoint:
    def test_grouped_with_contact_names(self, client, key_factory, fx):
        h, c = _seed_chat(fx)
        fx.add_message(c, text="you around?", handle_rowid=h)
        r = client.get("/v1/messages/unread", headers=key_factory("messages:read"))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        chat = body["chats"][0]
        assert chat["chat_id"] == CHAT_GUID
        msg = chat["messages"][0]
        assert msg["text"] == "you around?"
        assert msg["sender_name"] == "Sarah Example"

    def test_mark_read_hides_message_from_next_poll(self, client, key_factory, fx):
        """The decision #12 regression test: reading a text aloud must stop it
        resurfacing even though chat.db still says unread."""
        h, c = _seed_chat(fx)
        _, guid = fx.add_message(c, text="you around?", handle_rowid=h)
        headers = key_factory("messages:read")

        assert client.get("/v1/messages/unread", headers=headers).json()["total"] == 1
        r = client.post("/v1/messages/mark-read", headers=headers, json={"guids": [guid]})
        assert r.status_code == 200 and r.json()["marked"] == 1
        assert client.get("/v1/messages/unread", headers=headers).json()["total"] == 0

    def test_ledger_pruned_when_read_on_another_device(self, client, key_factory, fx):
        from services.ledger import ReadAloudLedger

        h, c = _seed_chat(fx)
        _, guid = fx.add_message(c, text="hi", handle_rowid=h)
        headers = key_factory("messages:read")
        client.post("/v1/messages/mark-read", headers=headers, json={"guids": [guid]})
        fx.set_read(guid)  # read on iPhone
        assert client.get("/v1/messages/unread", headers=headers).json()["total"] == 0
        assert ReadAloudLedger().marked() == set()

    def test_unreadable_chat_db_503(self, client, key_factory, fx, monkeypatch):
        monkeypatch.setenv("CHAT_DB_PATH", str(fx.path) + ".missing")
        r = client.get("/v1/messages/unread", headers=key_factory("messages:read"))
        assert r.status_code == 503


class TestThreadEndpoints:
    def test_thread_by_guid_and_rowid(self, client, key_factory, fx):
        h, c = _seed_chat(fx)
        fx.add_message(c, text="them", handle_rowid=h, is_read=1, date_unix=BASE_TIME)
        fx.add_message(c, text="me", is_from_me=1, date_unix=BASE_TIME + 5)
        headers = key_factory("messages:read")
        for chat_ref in (CHAT_GUID, str(c)):
            r = client.get(f"/v1/messages/threads/{chat_ref}", headers=headers)
            assert r.status_code == 200
            assert [m["text"] for m in r.json()["messages"]] == ["them", "me"]

    def test_thread_unknown_chat_404(self, client, key_factory):
        r = client.get("/v1/messages/threads/999", headers=key_factory("messages:read"))
        assert r.status_code == 404

    def test_style_context_sparse(self, client, key_factory, fx):
        _, c = _seed_chat(fx)
        fx.add_message(c, text="mine", is_from_me=1)
        r = client.get(
            f"/v1/messages/threads/{c}/style-context", headers=key_factory("messages:read")
        )
        assert r.status_code == 200
        assert r.json() == {"messages": [], "sparse": True}


class TestSendEndpoint:
    def _patch_sender(self, monkeypatch, result: SendResult):
        captured = {}

        class FakeSender:
            def __init__(self, chat_db):
                pass

            def send(self, text, chat_guid=None, handle=None):
                captured.update(text=text, chat_guid=chat_guid, handle=handle)
                return result

        monkeypatch.setattr(message_routes_mod, "MessageSender", FakeSender)
        return captured

    def test_send_success(self, client, key_factory, monkeypatch):
        captured = self._patch_sender(
            monkeypatch, SendResult(status="sent", chat_guid=CHAT_GUID)
        )
        r = client.post(
            "/v1/messages/send",
            headers=key_factory("messages:send"),
            json={"chat_id": CHAT_GUID, "text": "on my way"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "sent"
        assert captured["text"] == "on my way"

    def test_send_requires_send_scope(self, client, key_factory):
        r = client.post(
            "/v1/messages/send",
            headers=key_factory("messages:read"),
            json={"chat_id": CHAT_GUID, "text": "hi"},
        )
        assert r.status_code == 403

    def test_send_status_mapping(self, client, key_factory, monkeypatch):
        cases = [
            ("no_such_chat", 404),
            ("group_unsupported", 400),
            ("applescript_error", 502),
            ("send_failed", 502),
            ("unverified", 502),
        ]
        headers = key_factory("messages:send")
        for status, expected_http in cases:
            self._patch_sender(monkeypatch, SendResult(status=status))
            r = client.post(
                "/v1/messages/send", headers=headers, json={"handle": "+1555", "text": "x"}
            )
            assert (r.status_code, r.json()["status"]) == (expected_http, status)

    def test_send_needs_chat_or_handle(self, client, key_factory):
        r = client.post(
            "/v1/messages/send", headers=key_factory("messages:send"), json={"text": "hi"}
        )
        assert r.status_code == 422


class TestContactsEndpoint:
    def test_resolve(self, client, key_factory):
        r = client.get(
            "/v1/contacts/resolve",
            params={"query": "sarah"},
            headers=key_factory("contacts:read"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["authorization"] == "authorized"
        assert body["results"][0]["handles"][0]["value"] == "+15551234567"


class TestShortcutsEndpoint:
    def test_run_ok(self, client, key_factory, monkeypatch):
        class FakeRunner:
            def run(self, name, input_text=None, timeout=60.0):
                return ShortcutResult(status="ok", returncode=0, stdout="done")

        monkeypatch.setattr(shortcut_routes_mod, "ShortcutsRunner", lambda: FakeRunner())
        r = client.post(
            "/v1/shortcuts/run",
            headers=key_factory("shortcuts:run"),
            json={"name": "Good Morning"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_cli_missing_503(self, client, key_factory, monkeypatch):
        class FakeRunner:
            def run(self, name, input_text=None, timeout=60.0):
                return ShortcutResult(status="cli_missing")

        monkeypatch.setattr(shortcut_routes_mod, "ShortcutsRunner", lambda: FakeRunner())
        r = client.post(
            "/v1/shortcuts/run", headers=key_factory("shortcuts:run"), json={"name": "X"}
        )
        assert r.status_code == 503


class TestHealth:
    def test_ok_when_all_capabilities_good(self, client, fx, monkeypatch):
        monkeypatch.setattr("api.health_routes.shortcuts_cli_present", lambda: True)
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["capabilities"]["messages_db"] == "readable"
        assert body["capabilities"]["contacts"] == "authorized"
        assert body["capabilities"]["automation"] == "unknown"

    def test_degraded_when_chat_db_unreadable(self, client, fx, monkeypatch):
        monkeypatch.setenv("CHAT_DB_PATH", str(fx.path) + ".missing")
        body = client.get("/health").json()
        assert body["status"] == "degraded"
        assert body["capabilities"]["messages_db"] == "unreadable"
