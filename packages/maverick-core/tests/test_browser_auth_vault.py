"""Browser auth vault (ROADMAP 2027 H2)."""
from __future__ import annotations

import pytest

# cryptography ships via the audit-signing extra and is present in the test env;
# skip cleanly if it ever isn't, since the vault is gated behind that extra.
pytest.importorskip("cryptography")

from maverick.browser_auth_vault import (  # noqa: E402
    Vault,
    decrypt_entry,
    encrypt_entry,
    generate_key,
    resolve_key,
)


def test_encrypt_decrypt_roundtrip():
    key = generate_key()
    data = {"cookie": "abc123", "expires": 9999}
    token = encrypt_entry(key, data)
    assert token != str(data)  # actually encrypted
    assert decrypt_entry(key, token) == data


def test_wrong_key_fails():
    token = encrypt_entry(generate_key(), {"x": 1})
    with pytest.raises(ValueError):
        decrypt_entry(generate_key(), token)


def test_vault_store_load_list_delete(tmp_path):
    key = generate_key()
    v = Vault(key, tmp_path / "vault.json")
    v.store("github", {"session": "tok-1"})
    v.store("gitlab", {"session": "tok-2"})
    assert v.list_entries() == ["github", "gitlab"]
    assert v.load("github") == {"session": "tok-1"}
    assert v.delete("github") is True
    assert v.list_entries() == ["gitlab"]
    assert v.delete("github") is False


def test_load_missing_entry_raises(tmp_path):
    v = Vault(generate_key(), tmp_path / "v.json")
    with pytest.raises(KeyError):
        v.load("nope")


def test_data_file_holds_only_ciphertext(tmp_path):
    key = generate_key()
    path = tmp_path / "vault.json"
    Vault(key, path).store("acct", {"password": "hunter2"})  # pragma: allowlist secret
    raw = path.read_text(encoding="utf-8")
    assert "hunter2" not in raw  # secret never stored in cleartext


def test_resolve_key_from_env(tmp_path, monkeypatch):
    key = generate_key()
    monkeypatch.setenv("MAVERICK_VAULT_KEY", key.decode("ascii"))
    assert resolve_key(tmp_path / "key") == key


def test_resolve_key_generates_and_persists(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_VAULT_KEY", raising=False)
    kf = tmp_path / "key"
    k1 = resolve_key(kf)
    assert kf.exists()
    assert resolve_key(kf) == k1  # stable across calls
