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
        return {"access_token": "supersecrettoken123", "token_type": "bearer",  # pragma: allowlist secret
                "expires_in": 3600, "refresh_token": "refreshsecret",  # pragma: allowlist secret
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


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        pass

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "oauth_helper" in names
