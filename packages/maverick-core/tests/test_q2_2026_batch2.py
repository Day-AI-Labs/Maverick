"""Q2 2026 batch 2: per-channel/user ACLs, file_cache, observability,
canaries, audit erase, skill-index spec doc."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------- tool_acl: per-channel + per-user ----------

def _write_config(tmp_path, body: str) -> None:
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "config.toml").write_text(body)
    import maverick.config as cfg_mod
    importlib.reload(cfg_mod)


def test_tool_acl_per_channel_deny(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '''
[security.channels.telegram]
denied_tools = ["computer", "shell"]
''')
    from maverick.safety.tool_acl import resolve_lists
    allowed, denied = resolve_lists(channel="telegram")
    assert "computer" in denied
    assert "shell" in denied


def test_tool_acl_per_user_allow_intersects(tmp_path, monkeypatch):
    """Per-user allow intersects with global allow -- most restrictive wins."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '''
[security]
allowed_tools = ["shell", "read_file", "write_file", "web_search"]

[security.users."tg:42"]
allowed_tools = ["read_file", "web_search"]
''')
    from maverick.safety.tool_acl import resolve_lists
    allowed, _ = resolve_lists(user_id="tg:42")
    # Intersection of global + user allow lists.
    assert allowed == {"read_file", "web_search"}


def test_tool_acl_deny_union(tmp_path, monkeypatch):
    """Deny lists union across global + channel + user."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '''
[security]
denied_tools = ["computer"]

[security.channels.slack]
denied_tools = ["browser"]

[security.users."slack:U1"]
denied_tools = ["shell"]
''')
    from maverick.safety.tool_acl import resolve_lists
    _, denied = resolve_lists(channel="slack", user_id="slack:U1")
    assert denied == {"computer", "browser", "shell"}


def test_tool_acl_no_channel_or_user_is_global_only(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '''
[security]
denied_tools = ["x"]

[security.channels.telegram]
denied_tools = ["y"]
''')
    from maverick.safety.tool_acl import resolve_lists
    _, denied = resolve_lists()
    assert "x" in denied
    # Channel-scoped y NOT applied when channel is None.
    assert "y" not in denied


def test_tool_acl_apply_to_registry_with_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path, '''
[security.channels.telegram]
denied_tools = ["computer", "browser"]
''')
    from maverick.tools import base_registry

    class _FakeSandbox:
        workdir = "."

    class _FakeWorld:
        pass

    # Register with optional tools, then drop them via channel ACL.
    reg = base_registry(
        world=_FakeWorld(), sandbox=_FakeSandbox(),
        enable_computer_use=True, enable_browser=True,
    )
    # Initial state: computer + browser present.
    names_before = {t.name for t in reg.all()}
    assert "computer" in names_before
    assert "browser" in names_before

    from maverick.safety.tool_acl import apply_to_registry
    apply_to_registry(reg, channel="telegram")
    names_after = {t.name for t in reg.all()}
    assert "computer" not in names_after
    assert "browser" not in names_after




def test_server_passes_channel_user_to_run_goal(monkeypatch):
    import maverick.server as server_mod

    class _World:
        def __init__(self):
            self._cid = 1
            self._gid = 1
        def get_or_create_conversation(self, channel, user_id):
            class C:
                pass
            c = C()
            c.id = self._cid
            return c
        def append_turn(self, conversation_id, role, text):
            return None
        def create_goal(self, title, text):
            return self._gid
        def set_goal_status(self, *args, **kwargs):
            return None

    captured = {}
    async def _fake_run_goal(*args, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(server_mod, "run_goal", _fake_run_goal)
    monkeypatch.setattr(server_mod, "build_sandbox", lambda: object())
    monkeypatch.setattr("maverick.compliance.first_turn_disclosure", lambda *a, **k: None)

    srv = server_mod.Server(world=_World(), llm=object(), sandbox=object())

    class _Msg:
        channel = "telegram"
        user_id = "42"
        text = "hello"

    import asyncio
    out = asyncio.run(srv._handle_message(_Msg()))
    assert out == "ok"
    assert captured["channel"] == "telegram"
    assert captured["user_id"] == "telegram:42"

# ---------- file_cache ----------

def test_file_cache_read_round_trip(tmp_path):
    from maverick.file_cache import (
        clear_read_cache,
        read_cache_stats,
        read_file_cached,
    )
    clear_read_cache()
    f = tmp_path / "f.txt"
    f.write_text("hello world")
    out = read_file_cached(f)
    assert out == "hello world"
    # Cache hit on second read.
    out2 = read_file_cached(f)
    assert out2 == "hello world"
    stats = read_cache_stats()
    assert stats["entries"] == 1
    clear_read_cache()


def test_file_cache_invalidates_on_mtime_change(tmp_path):
    import time as _time

    from maverick.file_cache import clear_read_cache, read_file_cached
    clear_read_cache()
    f = tmp_path / "f.txt"
    f.write_text("v1")
    assert read_file_cached(f) == "v1"
    # Bump mtime + content.
    _time.sleep(0.02)
    f.write_text("v2")
    assert read_file_cached(f) == "v2"
    clear_read_cache()


def test_file_cache_missing_file_returns_none(tmp_path):
    from maverick.file_cache import read_file_cached
    assert read_file_cached(tmp_path / "nope") is None


def test_repo_map_cache_invalidates_on_workdir_change(tmp_path):
    from maverick.file_cache import clear_repo_cache, repo_map_cached
    clear_repo_cache()
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "a.py").write_text("hi")
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return f"map-{calls['n']}"

    assert repo_map_cached(workdir, build) == "map-1"
    assert repo_map_cached(workdir, build) == "map-1"  # cached
    # Modify workdir -- new file changes signature.
    import time as _time
    _time.sleep(0.02)
    (workdir / "b.py").write_text("hi")
    assert repo_map_cached(workdir, build) == "map-2"
    clear_repo_cache()


# ---------- observability ----------

def test_observability_no_op_when_disabled(monkeypatch):
    monkeypatch.delenv("MAVERICK_OTEL_EXPORTER", raising=False)
    monkeypatch.delenv("MAVERICK_PROMETHEUS_PORT", raising=False)
    from maverick.observability import is_enabled, record_metric, trace_span
    assert not is_enabled()
    # trace_span and record_metric should be no-ops, not raise.
    with trace_span("test", attributes={"x": 1}) as span:
        assert span is None
    record_metric("nonexistent", 1.0, labels={"a": "b"})  # no-op


def test_observability_is_enabled_flag(monkeypatch):
    monkeypatch.setenv("MAVERICK_PROMETHEUS_PORT", "9999")
    from maverick.observability import is_enabled
    assert is_enabled()


# ---------- sandbox canaries ----------

def test_canaries_register_check(tmp_path):
    from maverick.safety.canaries import (
        SandboxCanaryFired,
        check,
        clear,
        is_canary,
        register,
    )
    clear()
    canary = tmp_path / "canary"
    register(canary)
    assert is_canary(canary)
    with pytest.raises(SandboxCanaryFired):
        check(canary, action="read")
    clear()


def test_canaries_no_op_when_unregistered(tmp_path):
    from maverick.safety.canaries import check, clear
    clear()
    # No canaries registered -> check() is a no-op.
    check(tmp_path / "file.txt")


def test_canaries_plant_and_verify(tmp_path):
    from maverick.safety.canaries import (
        clear,
        plant_session_canaries,
        verify_canaries,
    )
    clear()
    planted = plant_session_canaries(tmp_path)
    assert len(planted) == 3
    # All canary files exist with expected content.
    for p in planted:
        assert Path(p).exists()
    violations = verify_canaries(planted)
    assert violations == []
    # Tamper with one.
    Path(planted[0]).write_text("MUWAHAHAHA")
    violations = verify_canaries(planted)
    assert planted[0] in violations
    clear()


def test_canaries_unregister(tmp_path):
    from maverick.safety.canaries import clear, register, unregister
    clear()
    p = tmp_path / "c"
    register(p)
    assert unregister(p) is True
    assert unregister(p) is False


# ---------- audit erase ----------

def test_audit_erase_scrubs_matching(tmp_path):
    from maverick.audit import AuditEvent, AuditLog, EventKind
    from maverick.audit.erase import scrub_user
    audit_dir = tmp_path / "audit"
    al = AuditLog(audit_dir=audit_dir)
    import time as _time
    # 3 events: 2 for the target user, 1 for another.
    al.record(AuditEvent(ts=_time.time(), kind=EventKind.GOAL_START,
                          agent="orch", goal_id=1,
                          payload={"channel": "tg", "user_id": "alice", "title": "t1"}))
    al.record(AuditEvent(ts=_time.time(), kind=EventKind.GOAL_END,
                          agent="orch", goal_id=1,
                          payload={"channel": "tg", "user_id": "alice", "status": "succeeded"}))
    al.record(AuditEvent(ts=_time.time(), kind=EventKind.GOAL_START,
                          agent="orch", goal_id=2,
                          payload={"channel": "tg", "user_id": "bob", "title": "t3"}))

    matched, scanned = scrub_user("tg", "alice", audit_dir=audit_dir)
    assert matched == 2
    assert scanned == 3

    # Re-read the file: alice tombstoned, bob intact.
    rows = al.tail(20)
    target_rows = [r for r in rows if r.get("user_id") in ("alice", "[REDACTED]")]
    bob_rows = [r for r in rows if r.get("user_id") == "bob"]
    assert len(target_rows) == 2
    assert all(r.get("user_id") == "[REDACTED]" for r in target_rows)
    assert len(bob_rows) == 1


def test_audit_erase_delete_user(tmp_path):
    from maverick.audit import AuditEvent, AuditLog, EventKind
    from maverick.audit.erase import delete_user
    audit_dir = tmp_path / "audit"
    al = AuditLog(audit_dir=audit_dir)
    import time as _time
    al.record(AuditEvent(ts=_time.time(), kind=EventKind.GOAL_START,
                          agent="orch", goal_id=1,
                          payload={"channel": "tg", "user_id": "alice"}))
    al.record(AuditEvent(ts=_time.time(), kind=EventKind.GOAL_START,
                          agent="orch", goal_id=2,
                          payload={"channel": "tg", "user_id": "bob"}))

    matched, scanned = delete_user("tg", "alice", audit_dir=audit_dir)
    assert matched == 1
    assert scanned == 1  # only bob's row remains

    rows = al.tail(20)
    assert len(rows) == 1
    assert rows[0]["user_id"] == "bob"


def test_audit_erase_missing_dir_no_crash(tmp_path):
    from maverick.audit.erase import scrub_user
    # Audit dir doesn't exist -> 0, 0; no exception.
    matched, scanned = scrub_user("tg", "alice", audit_dir=tmp_path / "nope")
    assert (matched, scanned) == (0, 0)


def test_audit_erase_logs_only_redacted_subject(tmp_path, caplog):
    import logging
    import time as _time

    from maverick.audit import AuditEvent, AuditLog, EventKind
    from maverick.audit.erase import delete_user, scrub_user

    audit_dir = tmp_path / "audit"
    al = AuditLog(audit_dir=audit_dir)
    secret_user = "alice-secret-123"
    al.record(AuditEvent(ts=_time.time(), kind=EventKind.GOAL_START,
                          agent="orch", goal_id=1,
                          payload={"channel": "tg", "user_id": secret_user}))

    with caplog.at_level(logging.INFO, logger="maverick.audit.erase"):
        scrub_user("tg", secret_user, audit_dir=audit_dir)
        delete_user("tg", secret_user, audit_dir=audit_dir)

    log_output = caplog.text
    assert secret_user not in log_output
    assert "channel=tg" not in log_output
    assert "user_id=" not in log_output
    assert "subject_hash=" in log_output


# ---------- skill-index spec doc ----------

def test_skill_index_spec_doc_exists():
    p = REPO_ROOT / "docs" / "specs" / "skill-index.md"
    assert p.is_file()
    body = p.read_text()
    for section in ("Top-level shape", "Required fields", "Client behavior",
                    "Federation", "Trust model"):
        assert section in body


def test_skill_index_example_parses_as_json():
    """The example JSON in the spec should be valid JSON the client can read."""
    p = REPO_ROOT / "docs" / "specs" / "skill-index.md"
    body = p.read_text()
    # Extract the first ```json block.
    import re
    m = re.search(r"```json\s*\n(.*?)```", body, flags=re.DOTALL)
    assert m is not None, "no ```json block found in skill-index.md"
    data = json.loads(m.group(1))
    assert data["v"] == 1
    assert isinstance(data["skills"], list)
    assert len(data["skills"]) >= 1
    skill = data["skills"][0]
    for required in ("name", "version", "summary", "source", "sha256", "triggers"):
        assert required in skill
