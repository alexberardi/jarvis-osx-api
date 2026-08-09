import stat

import pytest

from auth.api_keys import KEY_PREFIX, ApiKeyStore, InvalidScopeError


@pytest.fixture()
def store(tmp_path):
    return ApiKeyStore(tmp_path / "api_keys.json")


def test_generate_and_verify_roundtrip(store):
    raw, key = store.generate(["messages:read", "contacts:read"], name="kitchen-node")
    assert raw.startswith(KEY_PREFIX)
    verified = store.verify(raw)
    assert verified is not None
    assert verified.key_id == key.key_id
    assert verified.scopes == ["contacts:read", "messages:read"]
    assert verified.name == "kitchen-node"


def test_raw_key_not_stored_on_disk(store):
    raw, _ = store.generate(["messages:read"])
    assert raw not in store.path.read_text()


def test_verify_rejects_unknown_and_malformed_keys(store):
    store.generate(["messages:read"])
    assert store.verify(KEY_PREFIX + "not-a-real-key") is None
    assert store.verify("totally-wrong") is None
    assert store.verify("") is None


def test_invalid_scope_rejected(store):
    with pytest.raises(InvalidScopeError):
        store.generate(["messages:write"])
    with pytest.raises(InvalidScopeError):
        store.generate([])


def test_scope_enforcement(store):
    raw, _ = store.generate(["messages:read"])
    key = store.verify(raw)
    assert key.has_scope("messages:read")
    assert not key.has_scope("messages:send")


def test_revoke(store):
    raw, key = store.generate(["messages:read"])
    assert store.revoke(key.key_id) is True
    assert store.verify(raw) is None
    assert store.revoke(key.key_id) is False


def test_list_keys(store):
    store.generate(["messages:read"], name="a")
    store.generate(["shortcuts:run"], name="b")
    assert sorted(k.name for k in store.list_keys()) == ["a", "b"]


def test_keys_file_is_owner_only(store):
    store.generate(["messages:read"])
    mode = stat.S_IMODE(store.path.stat().st_mode)
    assert mode == 0o600
