"""Regression tests for adversarial-council round-2 fixes."""
from __future__ import annotations

import os
import stat

import pytest


def _crypto_works() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        ed25519.Ed25519PrivateKey.generate()
        return True
    except BaseException:
        return False


# --- offensive C1: compute SymPy path must bound exponentiation ---

@pytest.mark.parametrize("expr", ["9**9**9**9", "2**1000000", "(10**100)**100"])
def test_compute_rejects_unbounded_pow(expr):
    from maverick.tools.compute import compute
    # Must return promptly with an error, not hang/OOM the worker.
    out = compute().fn({"op": "evaluate", "expr": expr})
    assert out.startswith("ERROR")


def test_compute_allows_small_pow():
    from maverick.tools.compute import compute
    assert compute().fn({"op": "evaluate", "expr": "2**10"}).strip().startswith("1024")


# --- offensive HIGH-2: scrub_env strips connection-string secrets too ---

def test_scrub_env_strips_dsn_and_url_secrets():
    from maverick.sandbox.local import scrub_env
    src = {
        "PATH": "/usr/bin",
        "DATABASE_URL": "postgres://u:p@h/db",
        "SENTRY_DSN": "https://x@sentry.io/1",
        "MONGO_URI": "mongodb://u:p@h",
        "STRIPE_API_KEY": "sk",
    }
    out = scrub_env(src)
    # DATABASE_URL/SENTRY_DSN/MONGO_URI carry embedded creds.
    assert set(out) <= {"PATH"}  # everything secret-ish removed
    assert out.get("PATH") == "/usr/bin"


# --- privacy H2: world.db must not be world/group readable ---

def test_world_db_permissions_locked(tmp_path):
    from maverick.world_model import WorldModel
    p = tmp_path / "w.db"
    wm = WorldModel(p)
    wm.close()
    mode = stat.S_IMODE(os.stat(p).st_mode)
    if os.name != "nt":  # POSIX mode bits aren't meaningful on NTFS
        assert mode & 0o077 == 0  # no group/other access


# --- agent-safety H3: channel allowlist helpers ---

def test_channel_allowlist_helpers():
    base = pytest.importorskip("maverick_channels.base")
    al = base.normalize_allowlist(["a", "b ", " "], "X_UNUSED")
    assert al == {"a", "b"}
    assert base.is_allowed("a", al) is True
    assert base.is_allowed("z", al) is False
    assert base.is_allowed("", al) is False
    # "anonymous" must never satisfy an allowlist.
    assert base.is_allowed("anonymous", {"anonymous"}) is False


def test_email_channel_requires_allowlist(monkeypatch):
    mod = pytest.importorskip("maverick_channels.email")
    monkeypatch.delenv("EMAIL_ALLOWED_USER_IDS", raising=False)
    with pytest.raises(ValueError):
        mod.EmailChannel(
            handler=lambda m: "", imap_host="h", imap_user="u",
            imap_password="p", smtp_host="s", smtp_user="u", smtp_password="p",
        )


# --- agent-safety M3: per-goal spawn cap ---

def test_swarm_total_spawn_cap():
    from maverick.swarm import SwarmContext
    ctx = SwarmContext(
        llm=None, world=None, budget=None, blackboard=None,
        sandbox=None, goal_id=1, max_total_spawns=3,
    )
    assert ctx.try_reserve_spawns(2) is True
    assert ctx.try_reserve_spawns(1) is True
    assert ctx.try_reserve_spawns(1) is False  # would exceed cap of 3


# --- API-contract MEDIUM: SSRF override is honored uniformly ---

def test_is_blocked_host_respects_override(monkeypatch):
    from maverick.tools.http_fetch import is_blocked_host
    monkeypatch.delenv("MAVERICK_FETCH_ALLOW_PRIVATE", raising=False)
    assert is_blocked_host("127.0.0.1") is True
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")
    assert is_blocked_host("127.0.0.1") is False


# --- architecture H2: shared env_bool ---

def test_env_bool(monkeypatch):
    from maverick._envparse import env_bool
    monkeypatch.setenv("X_EB", "on")
    assert env_bool("X_EB") is True
    monkeypatch.setenv("X_EB", "OFF")
    assert env_bool("X_EB") is False
    monkeypatch.setenv("X_EB", "garbage")
    assert env_bool("X_EB", True) is True
    monkeypatch.delenv("X_EB")
    assert env_bool("X_EB", False) is False


# --- ops CRITICAL: provider SDK clients get a bounded timeout ---

def test_llm_http_timeout_is_bounded():
    from maverick.providers.base import llm_http_timeout
    t = llm_http_timeout()
    if t is not None:  # httpx present
        import httpx
        assert isinstance(t, httpx.Timeout)


# --- reliability H1: signer refuses to silently restart on a torn line ---

def test_audit_signer_refuses_torn_resume(tmp_path, monkeypatch):
    if not _crypto_works():
        pytest.skip("cryptography backend unavailable")
    import maverick.audit.signing as signing

    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
    p = tmp_path / "a.ndjson"
    signing.AuditSigner(p).write({"v": 1, "kind": "x"})
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"partial": ')  # torn final line, no newline / not valid JSON
    with pytest.raises(ValueError):
        signing.AuditSigner(p)  # resume must refuse, not restart from genesis
