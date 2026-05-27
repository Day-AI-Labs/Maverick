"""Q2 2026 batch 1: cross-agent bus, kv_memory, clipboard, preview_diff,
PII detector, arxiv tool, voice tools, push notifications, cookbook."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------- cross-agent bus ----------

def test_agent_bus_send_and_recv():
    from maverick import agent_bus
    agent_bus.clear()
    ok = agent_bus.send("alice", "bob", {"hello": 1})
    assert ok
    msg = agent_bus.recv("bob")
    assert msg is not None
    assert msg.sender == "alice"
    assert msg.payload == {"hello": 1}
    # Inbox now empty.
    assert agent_bus.recv("bob") is None


def test_agent_bus_recv_with_timeout():
    from maverick import agent_bus
    agent_bus.clear()
    import threading
    import time

    def _send_later():
        time.sleep(0.05)
        agent_bus.send("alice", "bob", "later")

    threading.Thread(target=_send_later, daemon=True).start()
    msg = agent_bus.recv("bob", timeout=1.0)
    assert msg is not None
    assert msg.payload == "later"


def test_agent_bus_correlation_id_filter():
    from maverick import agent_bus
    agent_bus.clear()
    agent_bus.send("alice", "bob", "wrong", correlation_id="x1")
    agent_bus.send("alice", "bob", "right", correlation_id="x2")
    msg = agent_bus.recv("bob", correlation_id="x2", timeout=0.5)
    assert msg is not None
    assert msg.payload == "right"


def test_agent_bus_peek():
    from maverick import agent_bus
    agent_bus.clear()
    assert agent_bus.peek("bob") == 0
    agent_bus.send("a", "bob", 1)
    agent_bus.send("a", "bob", 2)
    assert agent_bus.peek("bob") == 2


# ---------- kv_memory ----------

@pytest.fixture
def world_with_goal(tmp_path):
    from maverick.world_model import WorldModel
    w = WorldModel(Path(tmp_path) / "wm.sqlite")
    gid = w.create_goal("test goal", "for kv_memory tests")
    yield w, gid
    w.close()


def test_kv_memory_set_get_round_trip(world_with_goal):
    from maverick.tools.kv_memory import kv_memory
    world, gid = world_with_goal
    tool = kv_memory(world, gid)
    assert "set 'key1'" in tool.fn({"op": "set", "key": "key1", "value": "v1"})
    assert tool.fn({"op": "get", "key": "key1"}) == "v1"


def test_kv_memory_missing_key_returns_sentinel(world_with_goal):
    from maverick.tools.kv_memory import kv_memory
    world, gid = world_with_goal
    out = kv_memory(world, gid).fn({"op": "get", "key": "nope"})
    assert "no fact stored" in out


def test_kv_memory_upsert(world_with_goal):
    from maverick.tools.kv_memory import kv_memory
    world, gid = world_with_goal
    tool = kv_memory(world, gid)
    tool.fn({"op": "set", "key": "k", "value": "first"})
    tool.fn({"op": "set", "key": "k", "value": "second"})
    assert tool.fn({"op": "get", "key": "k"}) == "second"


def test_kv_memory_list(world_with_goal):
    from maverick.tools.kv_memory import kv_memory
    world, gid = world_with_goal
    tool = kv_memory(world, gid)
    tool.fn({"op": "set", "key": "a", "value": "1"})
    tool.fn({"op": "set", "key": "b", "value": "22"})
    out = tool.fn({"op": "list"})
    assert "a" in out and "b" in out


def test_kv_memory_search(world_with_goal):
    from maverick.tools.kv_memory import kv_memory
    world, gid = world_with_goal
    tool = kv_memory(world, gid)
    tool.fn({"op": "set", "key": "auth.password", "value": "secret"})
    tool.fn({"op": "set", "key": "auth.user", "value": "alice"})
    tool.fn({"op": "set", "key": "config.port", "value": "8080"})
    out = tool.fn({"op": "search", "query": "auth"})
    assert "auth.password" in out
    assert "auth.user" in out
    assert "config.port" not in out


def test_kv_memory_delete(world_with_goal):
    from maverick.tools.kv_memory import kv_memory
    world, gid = world_with_goal
    tool = kv_memory(world, gid)
    tool.fn({"op": "set", "key": "k", "value": "v"})
    out = tool.fn({"op": "delete", "key": "k"})
    assert "deleted 1" in out
    assert "no fact stored" in tool.fn({"op": "get", "key": "k"})


def test_kv_memory_requires_active_goal():
    from maverick.tools.kv_memory import kv_memory
    out = kv_memory(world=None, goal_id=None).fn({"op": "get", "key": "x"})
    assert "ERROR" in out and "active goal" in out


# ---------- clipboard ----------

def test_clipboard_kill_switch(monkeypatch):
    monkeypatch.setenv("MAVERICK_CLIPBOARD_DISABLE", "1")
    from maverick.tools.clipboard import clipboard
    assert "disabled" in clipboard().fn({"op": "read"}).lower()


def test_clipboard_read_via_pyperclip(monkeypatch):
    monkeypatch.delenv("MAVERICK_CLIPBOARD_DISABLE", raising=False)
    fake_pyperclip = MagicMock()
    fake_pyperclip.paste.return_value = "from clipboard"
    with patch.dict("sys.modules", {"pyperclip": fake_pyperclip}):
        # Force reload to pick up the mock.
        import importlib
        import maverick.tools.clipboard as _clip_mod
        importlib.reload(_clip_mod)
        out = _clip_mod.clipboard().fn({"op": "read"})
    assert out == "from clipboard"


def test_clipboard_unknown_op():
    from maverick.tools.clipboard import clipboard
    assert "unknown op" in clipboard().fn({"op": "explode"}).lower()


# ---------- preview_diff ----------

def test_preview_diff_not_a_git_repo(tmp_path):
    from maverick.tools.preview_diff import preview_diff

    class _Sandbox:
        workdir = str(tmp_path)

    out = preview_diff(_Sandbox()).fn({})
    assert "not a git repo" in out


def test_preview_diff_no_changes(tmp_path):
    # Init a git repo with one committed file, no changes.
    if not _git_available():
        pytest.skip("git not installed")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    # Test env may force commit signing; disable it for the throwaway repo.
    subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "tag.gpgsign", "false"], check=True)
    (tmp_path / "a.txt").write_text("hi\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"],
        check=True,
    )

    from maverick.tools.preview_diff import preview_diff

    class _Sandbox:
        workdir = str(tmp_path)

    out = preview_diff(_Sandbox()).fn({})
    assert "(no changes)" in out


def test_preview_diff_shows_unstaged_changes(tmp_path):
    if not _git_available():
        pytest.skip("git not installed")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    # Test env may force commit signing; disable it for the throwaway repo.
    subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "tag.gpgsign", "false"], check=True)
    (tmp_path / "a.txt").write_text("line1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"],
        check=True,
    )
    # Modify file in worktree (unstaged).
    (tmp_path / "a.txt").write_text("line1\nline2\n")
    from maverick.tools.preview_diff import preview_diff

    class _Sandbox:
        workdir = str(tmp_path)

    out = preview_diff(_Sandbox()).fn({})
    assert "+line2" in out


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


# ---------- PII detector ----------

@pytest.mark.parametrize("name,sample", [
    ("email", "Contact me at alice@example.com please."),
    ("ssn", "SSN: 123-45-6789"),
    ("phone_us", "Call me at (415) 555-2671."),
    ("ipv4", "Server at 192.168.1.100."),
    ("street_address", "Mail to 123 Main Street."),
])
def test_pii_detector_finds(name, sample):
    from maverick.safety.pii_detector import scan
    found = [m.kind for m in scan(sample)]
    assert name in found, f"expected {name} in {found}"


def test_pii_detector_luhn_validates_credit_cards():
    from maverick.safety.pii_detector import scan
    # Real Luhn-valid Visa test number.
    valid = "Card: 4532-0151-1283-0366"
    matches = [m.kind for m in scan(valid)]
    assert "credit_card" in matches
    # Random 16-digit string that fails Luhn -> not flagged.
    invalid = "Order #: 1234-5678-9012-3456"
    matches2 = [m.kind for m in scan(invalid)]
    assert "credit_card" not in matches2


def test_pii_detector_redact_replaces():
    from maverick.safety.pii_detector import redact
    text = "Hello alice@example.com, your SSN 123-45-6789 is on file."
    out, matches = redact(text)
    assert "alice@example.com" not in out
    assert "123-45-6789" not in out
    assert "[REDACTED:email]" in out
    assert "[REDACTED:ssn]" in out
    assert len(matches) == 2


def test_pii_detector_empty():
    from maverick.safety.pii_detector import redact, scan
    assert scan("") == []
    assert redact("") == ("", [])


# ---------- arxiv tool ----------

def test_arxiv_search_requires_query():
    from maverick.tools.arxiv import arxiv
    out = arxiv().fn({"op": "search", "query": ""})
    assert "requires query" in out


def test_arxiv_fetch_requires_id():
    from maverick.tools.arxiv import arxiv
    out = arxiv().fn({"op": "fetch", "arxiv_id": ""})
    assert "requires arxiv_id" in out


def test_arxiv_parser_handles_real_atom():
    from maverick.tools.arxiv import _parse_atom
    # A trimmed-down arxiv-shaped response.
    xml = """
    <feed>
      <entry>
        <id>http://arxiv.org/abs/2106.09685v3</id>
        <title>LoRA: Low-Rank Adaptation of Large Language Models</title>
        <summary>We propose Low-Rank Adaptation, or LoRA, which freezes...</summary>
        <published>2021-06-17T17:01:48Z</published>
        <name>Edward J. Hu</name>
        <name>Yelong Shen</name>
      </entry>
    </feed>
    """
    entries = _parse_atom(xml)
    assert len(entries) == 1
    e = entries[0]
    assert e["arxiv_id"] == "2106.09685"
    assert "LoRA" in e["title"]
    assert "Hu" in e["authors"]


# ---------- voice tools ----------

def test_voice_transcribe_requires_source():
    from maverick.tools.voice import transcribe_audio
    out = transcribe_audio().fn({"source": ""})
    assert "source is required" in out


def test_voice_transcribe_missing_file():
    from maverick.tools.voice import transcribe_audio
    out = transcribe_audio().fn({"source": "/no/such/audio.mp3"})
    assert "not found" in out


def test_voice_speak_requires_text():
    from maverick.tools.voice import speak
    out = speak().fn({"text": ""})
    assert "text is required" in out


def test_voice_speak_caps_text_length():
    from maverick.tools.voice import speak
    out = speak().fn({"text": "x" * 5000})
    assert "too long" in out


# ---------- notifications ----------

def test_notifications_no_backends_no_op():
    from maverick.notifications import notify
    assert notify("hi", backends=["none"]) == 0


def test_notifications_unknown_backend_logs(monkeypatch):
    from maverick.notifications import notify
    fired = notify("hi", backends=["garbage"], async_dispatch=False)
    assert fired == 0  # nothing succeeded


def test_notifications_dispatch_with_ntfy_topic_env(monkeypatch):
    """With MAVERICK_NTFY_TOPIC + no SDK, dispatch attempts the call."""
    monkeypatch.setenv("MAVERICK_NTFY_TOPIC", "test-topic")
    from maverick import notifications

    posted: list[tuple[str, str]] = []

    def _fake_post(url, content=None, headers=None, timeout=None):
        posted.append((url, headers.get("Title", "")))
        resp = MagicMock()
        resp.status_code = 200
        return resp

    with patch("httpx.post", side_effect=_fake_post):
        fired = notifications.notify(
            "test body", title="Hello", backends=["ntfy"], async_dispatch=False,
        )
    assert fired == 1
    assert len(posted) == 1
    assert "test-topic" in posted[0][0]


# ---------- cookbook + failure-modes docs ----------

@pytest.mark.parametrize("name", [
    "index.md", "pr-review.md", "dep-migrate.md",
    "repo-onboarding.md", "issue-triage.md", "research.md",
])
def test_cookbook_recipe_exists(name):
    p = REPO_ROOT / "docs" / "cookbook" / name
    assert p.is_file(), f"missing cookbook recipe: {name}"
    body = p.read_text()
    # Each recipe must have a "Goal text" or be the index.
    if name == "index.md":
        return
    assert "## Goal text" in body or "Goal text" in body


def test_failure_modes_doc_exists():
    p = REPO_ROOT / "docs" / "performance" / "failure-modes.md"
    assert p.is_file()
    body = p.read_text()
    # Must enumerate every ErrorClass.
    for cls in (
        "rate_limit", "transient_network", "server_5xx",
        "content_filter", "auth", "context_overflow",
        "malformed_response", "unknown",
    ):
        assert cls in body


# ---------- tool registry ----------

def test_q2_tools_registered():
    """All Q2 batch tools must appear in the default registry."""
    from maverick.tools import base_registry

    class _FakeSandbox:
        workdir = "."

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    names = {t.name for t in reg.all()}
    for expected in (
        "clipboard", "preview_diff", "arxiv",
        "transcribe_audio", "speak",
        # kv_memory needs a non-None world+goal_id; skip in this no-goal test.
    ):
        assert expected in names, f"missing tool: {expected}"
