"""Generic OAuth helper: PKCE authorize URL, code exchange, refresh — with a
fake transport; tokens are never echoed."""
from __future__ import annotations

from maverick.tools.oauth_helper import oauth_helper


def _t():
    return oauth_helper()


def test_authorize_url_includes_pkce():
    out = _t().fn({"op": "authorize_url", "authorize_url": "https://x/auth",
                   "client_id": "cid", "redirect_uri": "https://app/cb",
                   "scope": "repo read:user", "state": "s1"})
    assert out.startswith("open: https://x/auth?")
    assert "response_type=code" in out and "code_challenge_method=S256" in out
    assert "scope=repo+read%3Auser" in out and "state=s1" in out
    assert "pkce_verifier: " in out


def test_exchange_summarises_never_echoes(monkeypatch, tmp_path):
    import maverick.tools.oauth_helper as mod
    captured = {}

    def fake_post(url, data):
        captured["url"] = url
        captured["data"] = data
        return {"access_token": "supersecrettoken123", "token_type": "bearer",
                "expires_in": 3600, "refresh_token": "refreshsecret",
                "scope": "repo"}

    monkeypatch.setattr(mod, "_post_form", fake_post)
    monkeypatch.setenv("MAVERICK_OAUTH_OUT", str(tmp_path / "tokens.json"))
    out = _t().fn({"op": "exchange", "token_url": "https://x/token",
                   "client_id": "cid", "code": "abc",
                   "redirect_uri": "https://app/cb", "verifier": "v1"})
    assert "supersecrettoken123" not in out         # never echoed
    assert "access_token: <redacted>" in out and "sha256:" in out
    assert "refresh_token: <redacted> (present)" in out
    assert "tokens.json" in out
    assert captured["data"]["code_verifier"] == "v1"
    import json
    saved = json.loads((tmp_path / "tokens.json").read_text())
    assert saved["access_token"] == "supersecrettoken123"


def test_exchange_without_outfile_hints(monkeypatch):
    import maverick.tools.oauth_helper as mod
    monkeypatch.setattr(mod, "_post_form",
                        lambda url, data: {"access_token": "tok"})
    monkeypatch.delenv("MAVERICK_OAUTH_OUT", raising=False)
    out = _t().fn({"op": "exchange", "token_url": "https://x/t",
                   "client_id": "c", "code": "k", "redirect_uri": "https://r"})
    assert "set MAVERICK_OAUTH_OUT" in out


def test_refresh(monkeypatch):
    import maverick.tools.oauth_helper as mod
    captured = {}

    def fake_post(url, data):
        captured["data"] = data
        return {"access_token": "newtok", "expires_in": 60}

    monkeypatch.setattr(mod, "_post_form", fake_post)
    monkeypatch.delenv("MAVERICK_OAUTH_OUT", raising=False)
    out = _t().fn({"op": "refresh", "token_url": "https://x/t",
                   "client_id": "c", "refresh_token": "r1"})
    assert captured["data"]["grant_type"] == "refresh_token"
    assert "newtok" not in out and "expires_in: 60s" in out


def test_exchange_seals_to_vault_when_enabled(monkeypatch, tmp_path):
    import importlib.util

    import pytest
    if importlib.util.find_spec("cryptography") is None:
        pytest.skip("cryptography extra not installed")
    import maverick.tools.oauth_helper as mod
    from maverick.tenant import kms
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_KMS_KEK", "cd" * 32)
    monkeypatch.setenv("MAVERICK_OAUTH_VAULT", "1")
    monkeypatch.delenv("MAVERICK_OAUTH_OUT", raising=False)
    kms._clear_cache()
    monkeypatch.setattr(mod, "_post_form",
                        lambda url, data: {"access_token": "vaulted-secret",
                                           "refresh_token": "rt", "expires_in": 3600})
    out = _t().fn({"op": "exchange", "token_url": "https://x/t", "client_id": "c",
                   "code": "k", "redirect_uri": "https://r", "provider": "notion"})
    assert "vaulted-secret" not in out          # never echoed
    assert "sealed in the per-tenant OAuth vault" in out
    # Stored sealed and retrievable via the vault, not via a plaintext file.
    from maverick.oauth_vault import get_vault
    assert get_vault().get("notion")["access_token"] == "vaulted-secret"


def test_errors_shaped(monkeypatch):
    import maverick.tools.oauth_helper as mod
    t = _t()
    assert t.fn({"op": "authorize_url"}).startswith("ERROR")
    assert t.fn({"op": "exchange", "token_url": "u"}).startswith("ERROR")
    assert t.fn({"op": "bogus"}).startswith("ERROR")
    monkeypatch.setattr(mod, "_post_form",
                        lambda url, data: (_ for _ in ()).throw(RuntimeError("503")))
    out = t.fn({"op": "refresh", "token_url": "u", "client_id": "c",
                "refresh_token": "r"})
    assert out.startswith("ERROR: token refresh failed")


def test_no_access_token_error_does_not_echo_response(monkeypatch):
    import maverick.tools.oauth_helper as mod

    monkeypatch.setattr(mod, "_post_form",
                        lambda url, data: {"internal_secret": "IMDS-ROLE-CREDS-ABC123"})  # pragma: allowlist secret
    out = _t().fn({"op": "exchange", "token_url": "https://x/t",
                   "client_id": "c", "code": "k", "redirect_uri": "https://r"})
    assert out == "ERROR: no access_token in response"
    assert "IMDS-ROLE-CREDS-ABC123" not in out


def test_token_post_requires_https_before_network():
    import maverick.tools.oauth_helper as mod
    import pytest

    with pytest.raises(ValueError, match="token_url must be https"):
        mod._post_form("http://127.0.0.1/token", {"grant_type": "refresh_token"})


def test_token_post_rejects_private_resolved_host(monkeypatch):
    import socket

    import maverick.tools.oauth_helper as mod
    import pytest
    from maverick.tools._ssrf import BlockedHost

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(BlockedHost):
        mod._post_form("https://localhost/token", {"grant_type": "refresh_token"})


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        pass

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "oauth_helper" in names
