"""Tests for the Q1 2026 batch.

Covers:
  - audit log writer (rotation, perms, tail, grep)
  - killswitch (file trigger, in-process trigger, check())
  - secret detector (scan, redact, all patterns)
  - http_fetch tool (URL validation, private IP refusal, render modes)
  - read_pdf tool (page parsing, no-deps error path)
  - view_image tool (source loading, schema)
  - new CLI commands surfacing (smoke import only)
"""
from __future__ import annotations

import stat
from unittest.mock import patch

import pytest

# ---------- audit log ----------

def test_audit_log_writes_ndjson(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.audit import AuditEvent, AuditLog, EventKind

    al = AuditLog(audit_dir=tmp_path / ".maverick" / "audit")
    import time
    ok = al.record(AuditEvent(
        ts=time.time(), kind=EventKind.GOAL_START,
        agent="orchestrator", goal_id=1,
        payload={"title": "test", "description": None},
    ))
    assert ok
    # File exists with mode 0600.
    files = list((tmp_path / ".maverick" / "audit").glob("*.ndjson"))
    assert len(files) == 1
    import os
    if os.name != "nt":  # NTFS reports 0o666 regardless of chmod
        assert stat.S_IMODE(files[0].stat().st_mode) == 0o600


def test_audit_log_tail_and_grep(tmp_path):
    from maverick.audit import AuditEvent, AuditLog, EventKind
    al = AuditLog(audit_dir=tmp_path / "audit")
    import time
    for i in range(10):
        al.record(AuditEvent(
            ts=time.time() + i * 0.001,
            kind=EventKind.TOOL_CALL if i % 2 == 0 else EventKind.TOOL_RESULT,
            agent="coder", goal_id=1,
            payload={"name": f"tool{i}"},
        ))
    last5 = al.tail(5)
    assert len(last5) == 5
    # Only TOOL_CALL events should match the grep.
    hits = al.grep('"kind": "tool_call"')
    assert len(hits) == 5
    assert all(h["kind"] == "tool_call" for h in hits)


def test_audit_log_failsafe_on_bad_dir(tmp_path):
    """If audit_dir can't be created, record() returns False, doesn't raise."""
    from maverick.audit import AuditEvent, AuditLog, EventKind
    # Point to a path under a file (cannot create a subdir of a file).
    bad_parent = tmp_path / "blocking_file"
    bad_parent.write_text("x")
    al = AuditLog(audit_dir=bad_parent / "audit")
    import time
    ok = al.record(AuditEvent(ts=time.time(), kind=EventKind.HALT))
    assert ok is False  # graceful


def test_audit_record_module_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Force re-resolution of the default audit log.
    import maverick.audit.writer as w
    w._default = None
    from maverick.audit import EventKind, record
    ok = record(EventKind.GOAL_START, goal_id=42, title="test goal")
    assert ok


# ---------- killswitch ----------

def test_killswitch_no_halt_initially(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HALT_FILE", str(tmp_path / "HALT"))
    import maverick.killswitch as ks
    ks._last_file_check_ts = 0.0  # bust the cache
    ks.clear()
    ks.check()  # should not raise


def test_killswitch_file_trigger(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HALT_FILE", str(tmp_path / "HALT"))
    import maverick.killswitch as ks
    ks._last_file_check_ts = 0.0
    ks.clear()
    (tmp_path / "HALT").write_text("operator stop")
    with pytest.raises(ks.Halted) as exc:
        ks.check()
    assert exc.value.source == "file"


def test_killswitch_in_process_trigger(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HALT_FILE", str(tmp_path / "HALT"))
    import maverick.killswitch as ks
    ks._last_file_check_ts = 0.0
    ks.clear()
    ks.halt("budget exceeded", source="manual")
    try:
        with pytest.raises(ks.Halted) as exc:
            ks.check()
        assert exc.value.reason == "budget exceeded"
    finally:
        ks.clear()


def test_killswitch_is_active(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HALT_FILE", str(tmp_path / "HALT"))
    import maverick.killswitch as ks
    ks._last_file_check_ts = 0.0
    ks.clear()
    assert ks.is_active() is False
    ks.halt("test")
    try:
        assert ks.is_active() is True
    finally:
        ks.clear()


def test_killswitch_default_path_follows_current_home(tmp_path, monkeypatch):
    """The default HALT path must track the *current* home, not the home
    that happened to be set when the module was imported.

    Regression: ``DEFAULT_HALT_FILE`` was a module-level constant evaluated
    at import time, so a process (or test) that re-homed after import kept
    watching the stale home's HALT file -- silently defeating the killswitch
    in exactly the safety-critical module. With no ``MAVERICK_HALT_FILE``
    override, dropping a HALT file in the *new* home must halt.
    """
    import maverick.killswitch as ks

    monkeypatch.delenv("MAVERICK_HALT_FILE", raising=False)
    new_home = tmp_path / "rehomed"
    (new_home / ".maverick").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(new_home))
    monkeypatch.setenv("USERPROFILE", str(new_home))  # Windows home

    ks._last_file_check_ts = 0.0  # bust the 1s stat cache
    ks.clear()
    # Path is resolved against the new home, not a frozen import-time one.
    assert ks._halt_file_path() == new_home / ".maverick" / "HALT"

    (new_home / ".maverick" / "HALT").write_text("operator stop")
    ks._last_file_check_ts = 0.0
    with pytest.raises(ks.Halted) as exc:
        ks.check()
    assert exc.value.source == "file"


# ---------- secret detector ----------

@pytest.mark.parametrize("secret_name,secret_value", [
    ("anthropic_api_key",  "sk-ant-api03-AbCdEf1234567890abcdefghijklmno_PQRST"),
    ("openai_api_key",     "sk-proj-AbCdEf1234567890abcdefghijklmno"),
    ("aws_access_key_id",  "AKIAIOSFODNN7EXAMPLE"),
    ("github_pat_classic", "ghp_AbCdEf1234567890AbCdEf1234567890abcd"),
    ("google_api_key",     "AIzaSyB6CdEf1234567890abcdefghijklmnopq"),
    ("stripe_live_key",    "sk_live_1234567890abcdefghijklmnop"),
    ("jwt",                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.signature"),
])
def test_secret_detector_finds(secret_name, secret_value):
    from maverick.safety.secret_detector import scan
    matches = scan(f"hello {secret_value} world")
    assert any(m.name == secret_name for m in matches), \
        f"expected to find {secret_name} in: {[m.name for m in matches]}"


def test_secret_detector_redact_replaces_secret():
    from maverick.safety.secret_detector import redact
    text = "MY KEY: sk-ant-api03-AbCdEf1234567890abcdefghijklmno_PQRST end."
    out, matches = redact(text)
    assert "sk-ant-api03" not in out
    assert "[REDACTED:anthropic_api_key]" in out
    assert len(matches) == 1


def test_secret_detector_redact_no_secrets_returns_unchanged():
    from maverick.safety.secret_detector import redact
    text = "no secrets here, just words and numbers like 12345"
    out, matches = redact(text)
    assert out == text
    assert matches == []


def test_secret_detector_redact_multiple():
    from maverick.safety.secret_detector import redact
    text = (
        "first sk-ant-api03-AbCdEf1234567890abcdefghijklmno_PQRST "
        "then AKIAIOSFODNN7EXAMPLE and "
        "ghp_AbCdEf1234567890AbCdEf1234567890abcd done"
    )
    out, matches = redact(text)
    assert "sk-ant" not in out
    assert "AKIA" not in out
    assert "ghp_" not in out
    assert "[REDACTED:anthropic_api_key]" in out
    assert "[REDACTED:aws_access_key_id]" in out
    assert "[REDACTED:github_pat_classic]" in out
    assert len(matches) >= 3


def test_secret_detector_empty():
    from maverick.safety.secret_detector import redact, scan
    assert scan("") == []
    assert redact("") == ("", [])


# ---------- http_fetch ----------

def test_http_fetch_rejects_empty_url():
    from maverick.tools.http_fetch import http_fetch
    assert "url is required" in http_fetch().fn({"url": ""}).lower()


def test_http_fetch_rejects_non_http_scheme():
    from maverick.tools.http_fetch import http_fetch
    out = http_fetch().fn({"url": "file:///etc/passwd"})
    assert "only http/https" in out.lower()


def test_http_fetch_rejects_private_ip_by_default(monkeypatch):
    monkeypatch.delenv("MAVERICK_FETCH_ALLOW_PRIVATE", raising=False)
    from maverick.tools.http_fetch import _is_private_ip
    # 127.0.0.1 / localhost should be detected as private.
    assert _is_private_ip("127.0.0.1") is True


def test_http_fetch_allow_private_override(monkeypatch):
    """With MAVERICK_FETCH_ALLOW_PRIVATE=1, private addrs are not rejected."""
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")
    from maverick.tools import http_fetch as hf

    class _Resp:
        status_code = 200
        reason_phrase = "OK"
        encoding = "utf-8"
        url = "http://localhost/"
        headers = {"content-type": "text/plain"}
        content = b"hello"

        def raise_for_status(self): pass
        def iter_bytes(self): yield self.content
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Client:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def stream(self, *a, **kw): return _Resp()

    import httpx
    with patch.object(httpx, "Client", _Client):
        out = hf.http_fetch().fn({"url": "http://127.0.0.1/", "render": "raw"})
    assert "hello" in out


def test_http_fetch_markdown_render(monkeypatch):
    monkeypatch.setenv("MAVERICK_FETCH_ALLOW_PRIVATE", "1")
    from maverick.tools import http_fetch as hf

    html = "<h1>Title</h1><p>Hello <a href='https://x.example'>x</a></p>"

    class _Resp:
        status_code = 200
        reason_phrase = "OK"
        encoding = "utf-8"
        url = "http://localhost/"
        headers = {"content-type": "text/html"}
        content = html.encode()

        def raise_for_status(self): pass
        def iter_bytes(self): yield self.content
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Client:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def stream(self, *a, **kw): return _Resp()

    import httpx
    with patch.object(httpx, "Client", _Client):
        out = hf.http_fetch().fn({"url": "http://127.0.0.1/", "render": "markdown"})
    assert "# Title" in out
    assert "[x](https://x.example)" in out


# ---------- read_pdf ----------

def test_read_pdf_rejects_empty_source():
    from maverick.tools.pdf_reader import read_pdf
    assert "source is required" in read_pdf().fn({"source": ""}).lower()


def test_read_pdf_missing_file():
    from maverick.tools.pdf_reader import read_pdf
    out = read_pdf().fn({"source": "/definitely/does/not/exist.pdf"})
    assert "could not read" in out.lower()


def test_pdf_parse_pages_ranges():
    from maverick.tools.pdf_reader import _parse_pages
    assert _parse_pages("", 10) == list(range(10))
    assert _parse_pages("1-3", 10) == [0, 1, 2]
    assert _parse_pages("5", 10) == [4]
    assert _parse_pages("1,3,5", 10) == [0, 2, 4]
    assert _parse_pages("8-", 10) == [7, 8, 9]


# ---------- view_image ----------

def test_view_image_rejects_empty_source():
    from maverick.tools.view_image import view_image
    assert "source is required" in view_image().fn({"source": ""}).lower()


def test_view_image_missing_file():
    from maverick.tools.view_image import view_image
    out = view_image().fn({"source": "/no/such/image.png"})
    assert "could not load" in out.lower()


# ---------- new tools registered ----------

def test_q1_tools_in_base_registry():
    """http_fetch, read_pdf, view_image must register by default."""
    from maverick.tools import base_registry

    class _FakeSandbox:
        pass

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    names = {t.name for t in reg.all()}
    assert "http_fetch" in names
    assert "read_pdf" in names
    assert "view_image" in names


# ---------- CLI surface (smoke import) ----------

def test_cli_imports_with_new_commands():
    """Ensure the new commands attached to main don't break import."""
    from maverick.cli import main
    cmds = main.commands.keys()
    assert "audit" in cmds
    assert "halt" in cmds
    assert "unhalt" in cmds
    assert "cost" in cmds
    assert "export" in cmds
    assert "logs" in cmds


def test_cli_audit_subgroup_has_tail_grep():
    from maverick.cli import main
    audit = main.commands["audit"]
    assert "tail" in audit.commands
    assert "grep" in audit.commands
