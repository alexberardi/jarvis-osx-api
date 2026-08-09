import cli
from auth.api_keys import ApiKeyStore


def test_generate_prints_key_once(fx, capsys):
    assert cli.main(["generate-api-key", "--scopes", "messages:read", "--name", "kitchen"]) == 0
    out = capsys.readouterr().out
    assert "joxk_" in out
    assert "messages:read" in out
    keys = ApiKeyStore().list_keys()
    assert len(keys) == 1 and keys[0].name == "kitchen"


def test_generate_rejects_bad_scope(fx, capsys):
    assert cli.main(["generate-api-key", "--scopes", "messages:write"]) == 1
    assert "invalid scopes" in capsys.readouterr().err


def test_list_and_revoke(fx, capsys):
    cli.main(["generate-api-key", "--scopes", "shortcuts:run", "--name", "hub"])
    key_id = ApiKeyStore().list_keys()[0].key_id
    capsys.readouterr()

    assert cli.main(["list-api-keys"]) == 0
    assert "hub" in capsys.readouterr().out

    assert cli.main(["revoke-api-key", key_id]) == 0
    assert ApiKeyStore().list_keys() == []
    assert cli.main(["revoke-api-key", key_id]) == 1
