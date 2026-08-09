import pytest
from fastapi.testclient import TestClient

from tests.fixtures import ChatDBFixture


class FakeContacts:
    """Stands in for ContactsService — real behavior needs a TCC-granted device."""

    def __init__(self, status: str = "authorized", names: dict | None = None, results: list | None = None):
        self._status = status
        self._names = names or {}
        self._results = results or []

    def authorization_status(self) -> str:
        return self._status

    def name_for_handle(self, handle: str) -> str | None:
        return self._names.get(handle)

    def resolve(self, query: str) -> list[dict]:
        return [r for r in self._results if query.lower() in r["name"].lower()]


@pytest.fixture()
def fx(tmp_path, monkeypatch):
    """Point the whole app at throwaway paths and hand back the chat.db fixture."""
    monkeypatch.setenv("OSX_API_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "chat.db"))
    return ChatDBFixture(tmp_path / "chat.db")


@pytest.fixture()
def fake_contacts():
    return FakeContacts(
        names={"+15551234567": "Sarah Example"},
        results=[
            {
                "name": "Sarah Example",
                "nickname": "",
                "handles": [{"value": "+15551234567", "kind": "phone"}],
            }
        ],
    )


@pytest.fixture()
def client(fx, fake_contacts):
    from api.deps import get_contacts
    from main import app

    app.dependency_overrides[get_contacts] = lambda: fake_contacts
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def key_factory(fx):
    """Mint real scoped keys against the test data dir."""
    from auth.api_keys import ApiKeyStore

    def make(*scopes: str) -> dict:
        raw, _ = ApiKeyStore().generate(list(scopes), name="test")
        return {"Authorization": f"Bearer {raw}"}

    return make
