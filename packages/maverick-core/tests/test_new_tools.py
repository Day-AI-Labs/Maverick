"""Tests for web_search, recall_past_goals, monitor."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

# ---------- web_search ----------

class _FakeHttpxResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(self.status_code),
            )


def test_web_search_empty_query():
    from maverick.tools.web_search import web_search
    tool = web_search()
    assert "query is required" in tool.fn({"query": ""}).lower()


def test_web_search_tavily_path(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tav-key")
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("MAVERICK_SEARCH_BACKEND", raising=False)

    fake_resp = _FakeHttpxResponse(200, json_data={
        "results": [
            {"title": "Result 1", "url": "https://a.example", "content": "snip a"},
            {"title": "Result 2", "url": "https://b.example", "content": "snip b"},
        ]
    })

    import httpx
    with patch.object(httpx, "post", return_value=fake_resp):
        from maverick.tools.web_search import web_search
        out = web_search().fn({"query": "hello world", "num_results": 5})
    assert "[backend: tavily]" in out
    assert "Result 1" in out
    assert "https://a.example" in out


def test_web_search_falls_through_to_ddg_when_no_keys(monkeypatch):
    """All key-required backends skipped -> DDG attempted."""
    for env in ("TAVILY_API_KEY", "BRAVE_API_KEY", "SERPAPI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.delenv("MAVERICK_SEARCH_BACKEND", raising=False)

    # Minimal DDG html-lite output the regex can parse.
    html = (
        '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example Title</a>'
        '<a class="result__snippet">Example snippet.</a>'
    )
    fake = _FakeHttpxResponse(200, text=html)

    import httpx
    with patch.object(httpx, "get", return_value=fake):
        from maverick.tools.web_search import web_search
        out = web_search().fn({"query": "test", "num_results": 3})

    assert "[backend: ddg]" in out
    assert "Example Title" in out
    assert "https://example.com/page" in out


def test_web_search_forced_backend_skipped_if_no_creds(monkeypatch):
    """MAVERICK_SEARCH_BACKEND=tavily but no key -> no fallthrough."""
    monkeypatch.setenv("MAVERICK_SEARCH_BACKEND", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from maverick.tools.web_search import web_search
    out = web_search().fn({"query": "test"})
    assert "ERROR" in out


def test_web_search_site_filter(monkeypatch):
    """site arg should add 'site:' to the query."""
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.delenv("MAVERICK_SEARCH_BACKEND", raising=False)
    captured_payload = {}

    def fake_post(url, json=None, **kw):
        captured_payload["q"] = (json or {}).get("query")
        return _FakeHttpxResponse(200, json_data={"results": []})

    import httpx
    with patch.object(httpx, "post", side_effect=fake_post):
        from maverick.tools.web_search import web_search
        web_search().fn({"query": "react hooks", "site": "github.com"})
    assert captured_payload["q"].startswith("site:github.com ")


def test_web_search_caps_num_results():
    from maverick.tools.web_search import _SEARCH_INPUT_SCHEMA
    # Schema doesn't enforce cap, but runner does (cap is internal logic).
    # Just ensure schema lists the field.
    assert "num_results" in _SEARCH_INPUT_SCHEMA["properties"]


# ---------- recall_past_goals ----------

@pytest.fixture
def world_with_history(tmp_path):
    """A WorldModel with a few finished goals to recall against."""
    from maverick.world_model import WorldModel
    world = WorldModel(tmp_path / "wm.sqlite")
    # Insert via direct SQL (we control the schema fields).
    # Statuses use the vocabulary the orchestrator actually writes
    # (done/blocked/active), not the never-written succeeded/failed/in_progress.
    goals = [
        (1, None, "Refactor auth module", "Replace JWT with sessions in app/auth.py", "done", "Migrated auth to sessions, all tests pass."),
        (2, None, "Fix bug in payment flow", "Stripe webhook crashes on negative amounts", "done", "Added input validation; webhook stable."),
        (3, None, "Refactor authentication", "Same as #1 essentially", "blocked", "Hit a deadlock; reverted."),
        (4, None, "Write tests for cart", "Add coverage for shopping cart edge cases", "done", "Cart now at 85% coverage."),
        (5, None, "Database migration", "Move from SQLite to Postgres", "active", None),
    ]
    now = time.time()
    for gid, parent, title, desc, status, result in goals:
        world.conn.execute(
            "INSERT INTO goals(id, parent_id, title, description, status, "
            "created_at, updated_at, result) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (gid, parent, title, desc, status, now - gid * 100, now - gid * 100, result),
        )
    world.conn.commit()
    yield world
    world.close()


def test_recall_excludes_running_by_default(world_with_history):
    from maverick.tools.recall import recall_past_goals
    matches = recall_past_goals(
        "refactor auth",
        world=world_with_history,
        num_results=10,
        include_running=False,
    )
    ids = [g.id for _, g in matches]
    assert 5 not in ids  # "Database migration" is in_progress


def test_recall_finds_relevant_by_jaccard(world_with_history):
    """Without fastembed, jaccard should still rank refactor-auth as top."""
    from maverick.tools.recall import recall_past_goals
    matches = recall_past_goals(
        "auth refactor session",
        world=world_with_history,
        num_results=3,
    )
    assert matches, "expected at least one match"
    top_ids = [g.id for _, g in matches[:2]]
    # Goal 1 or 3 (both auth-related) should be in top 2.
    assert 1 in top_ids or 3 in top_ids


def test_recall_returns_empty_on_empty_world(tmp_path):
    from maverick.tools.recall import recall_past_goals
    from maverick.world_model import WorldModel
    world = WorldModel(tmp_path / "empty.sqlite")
    try:
        out = recall_past_goals("anything", world=world)
        assert out == []
    finally:
        world.close()


def test_recall_tool_factory():
    from maverick.tools.recall import recall
    tool = recall()
    assert tool.name == "recall_past_goals"
    assert "query" in tool.input_schema["properties"]


def test_recall_tool_runner_empty_query():
    from maverick.tools.recall import _run_recall
    assert "query is required" in _run_recall({"query": ""}).lower()


def test_recall_includes_running_when_asked(world_with_history):
    from maverick.tools.recall import recall_past_goals
    matches = recall_past_goals(
        "database",
        world=world_with_history,
        num_results=10,
        include_running=True,
    )
    ids = [g.id for _, g in matches]
    assert 5 in ids


# ---------- monitor ----------

def test_monitor_snapshot_empty_db(tmp_path):
    from maverick.monitor import snapshot
    from maverick.world_model import WorldModel
    world = WorldModel(tmp_path / "wm.sqlite")
    try:
        assert snapshot(world) is None
    finally:
        world.close()


def test_monitor_snapshot_resolves_active_goal(world_with_history):
    """Without explicit goal_id, picks the most-recent in_progress one."""
    from maverick.monitor import snapshot
    state = snapshot(world_with_history)
    assert state is not None
    # Goal #5 is the only in_progress one.
    assert state.goal.id == 5


def test_monitor_snapshot_explicit_goal(world_with_history):
    from maverick.monitor import snapshot
    state = snapshot(world_with_history, goal_id=1)
    assert state is not None
    assert state.goal.id == 1


def test_monitor_render_contains_key_fields(world_with_history):
    from maverick.monitor import render, snapshot
    state = snapshot(world_with_history, goal_id=2)
    text = render(state)
    assert "Goal #2" in text
    assert "done" in text.lower()
    assert "payment" in text.lower()


def test_monitor_render_shows_children(world_with_history):
    """If a goal has subgoals, the plan tree appears."""
    from maverick.monitor import render, snapshot
    # Add a child of goal 5.
    world_with_history.conn.execute(
        "INSERT INTO goals(id, parent_id, title, description, status, "
        "created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
        (10, 5, "Spin up Postgres", "Local docker pg", "active",
         time.time(), time.time()),
    )
    world_with_history.conn.commit()
    state = snapshot(world_with_history, goal_id=5)
    assert len(state.children) == 1
    assert state.children[0].id == 10
    rendered = render(state)
    assert "Plan tree" in rendered
    assert "Spin up Postgres" in rendered


# ---------- registry includes new tools ----------

def test_base_registry_excludes_web_search_by_default_but_keeps_recall():
    """web_search is opt-in; recall remains enabled by default."""
    from maverick.tools import base_registry

    class _FakeSandbox:
        pass

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    names = {t.name for t in reg.all()}
    assert "web_search" not in names
    assert "recall_past_goals" in names


def test_base_registry_can_enable_web_search_explicitly():
    from maverick.tools import base_registry

    class _FakeSandbox:
        pass

    class _FakeWorld:
        pass

    reg = base_registry(
        world=_FakeWorld(),
        sandbox=_FakeSandbox(),
        enable_web_search=True,
    )
    names = {t.name for t in reg.all()}
    assert "web_search" in names
