"""Q2 2026 batch 4: theme presets, Postgres world-model adapter, Semantic Scholar tool."""
from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock, patch

import pytest

# ---------- semantic_scholar tool ----------

def test_semantic_scholar_requires_op():
    from maverick.tools.semantic_scholar import semantic_scholar
    out = semantic_scholar().fn({})
    assert "ERROR" in out
    assert "op is required" in out


def test_semantic_scholar_unknown_op():
    from maverick.tools.semantic_scholar import semantic_scholar
    out = semantic_scholar().fn({"op": "garbage"})
    assert "unknown op" in out


def test_semantic_scholar_search_requires_query():
    from maverick.tools.semantic_scholar import semantic_scholar
    out = semantic_scholar().fn({"op": "search", "query": ""})
    assert "requires query" in out


def test_semantic_scholar_paper_requires_id():
    from maverick.tools.semantic_scholar import semantic_scholar
    out = semantic_scholar().fn({"op": "paper", "paper_id": ""})
    assert "requires paper_id" in out


def test_semantic_scholar_search_hits_api(monkeypatch):
    from maverick.tools.semantic_scholar import semantic_scholar
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value={
        "data": [
            {
                "title": "Attention Is All You Need",
                "year": 2017,
                "authors": [{"name": "Vaswani et al."}],
                "citationCount": 100000,
                "abstract": "We propose the Transformer...",
                "url": "https://www.semanticscholar.org/paper/abc",
            },
        ],
    })
    with patch("httpx.get", return_value=fake_resp) as mock_get:
        out = semantic_scholar().fn({"op": "search", "query": "transformer"})
    assert "Attention Is All You Need" in out
    assert "100000" in out
    # API URL hit, fields requested.
    call = mock_get.call_args
    assert "/paper/search" in call.args[0]
    assert "fields" in call.kwargs["params"]


def test_semantic_scholar_paper_by_doi(monkeypatch):
    from maverick.tools.semantic_scholar import semantic_scholar
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value={
        "title": "T",
        "year": 2024,
        "authors": [{"name": "A"}],
        "citationCount": 1,
        "abstract": "x" * 500,
        "url": "u",
    })
    with patch("httpx.get", return_value=fake_resp) as mock_get:
        out = semantic_scholar().fn({"op": "paper", "paper_id": "10.1234/abc"})
    call = mock_get.call_args
    # DOI without explicit prefix gets prefixed automatically.
    assert "DOI:10.1234/abc" in call.args[0]
    assert "T" in out


def test_semantic_scholar_404_actionable():
    from maverick.tools.semantic_scholar import semantic_scholar
    fake_resp = MagicMock()
    fake_resp.status_code = 404
    fake_resp.raise_for_status = MagicMock()
    with patch("httpx.get", return_value=fake_resp):
        out = semantic_scholar().fn({
            "op": "paper", "paper_id": "arxiv:0000.0000",
        })
    assert "no paper found" in out


def test_semantic_scholar_in_registry():
    from maverick.tools import base_registry

    class _FakeSandbox:
        workdir = "."

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    names = {t.name for t in reg.all()}
    assert "semantic_scholar" in names


# ---------- Postgres world-model ----------

_HAS_PSYCOPG = importlib.util.find_spec("psycopg") is not None


def test_postgres_is_configured_default_false(monkeypatch):
    monkeypatch.delenv("MAVERICK_WORLD_BACKEND", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-for-this-test")
    from maverick.world_model_backends import is_postgres_configured
    # No env, no config -> False.
    assert is_postgres_configured() is False


def test_postgres_is_configured_via_env(monkeypatch):
    monkeypatch.setenv("MAVERICK_WORLD_BACKEND", "postgres")
    from maverick.world_model_backends import is_postgres_configured
    assert is_postgres_configured() is True


def test_postgres_is_configured_via_config(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_WORLD_BACKEND", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".maverick"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        '[world_model]\nbackend = "postgres"\n'
    )
    from maverick.world_model_backends import is_postgres_configured
    assert is_postgres_configured() is True


def test_postgres_without_dep_raises_actionable():
    """If psycopg isn't installed, instantiation raises a clear error."""
    if _HAS_PSYCOPG:
        pytest.skip("psycopg IS installed; can't test the missing-dep path")
    from maverick.world_model_backends import PostgresWorldModel
    with pytest.raises(ImportError, match="maverick-agent\\[postgres\\]"):
        PostgresWorldModel(dsn="postgres://test")


def test_postgres_requires_dsn(monkeypatch):
    """No DSN -> actionable RuntimeError."""
    monkeypatch.delenv("MAVERICK_PG_DSN", raising=False)
    if not _HAS_PSYCOPG:
        # Constructor raises ImportError before checking DSN; create
        # an instance via a lightly mocked psycopg.
        import sys
        import types
        fake = types.ModuleType("psycopg")

        def _connect(*args, **kwargs):
            raise NotImplementedError

        fake.connect = _connect
        monkeypatch.setitem(sys.modules, "psycopg", fake)

    from maverick.world_model_backends import PostgresWorldModel
    with pytest.raises(RuntimeError, match="MAVERICK_PG_DSN"):
        PostgresWorldModel(dsn=None)


def test_postgres_schema_constants_exist():
    """The migration SQL list is present and has the expected tables."""
    from maverick.world_model_backends.postgres import SCHEMA
    joined = " ".join(SCHEMA)
    for tbl in ("goals", "episodes", "goal_events", "facts"):
        assert f"CREATE TABLE IF NOT EXISTS {tbl}" in joined


# ---------- dashboard theme presets ----------

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def dashboard_client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.world_model import WorldModel
    w = WorldModel(tmp_path / "world.db")
    w.create_goal("hello", "")
    from maverick_dashboard import app as app_mod
    monkeypatch.setattr(app_mod, "_world", lambda: w)
    yield TestClient(app_mod.app)
    w.close()


def test_dashboard_default_theme_is_dark(dashboard_client):
    resp = dashboard_client.get("/")
    assert resp.status_code == 200
    assert 'class="theme-dark"' in resp.text


@pytest.mark.parametrize("theme", ["dark", "light", "solarized", "hicontrast"])
def test_dashboard_theme_query_param(dashboard_client, theme):
    resp = dashboard_client.get(f"/?theme={theme}")
    assert resp.status_code == 200
    assert f'class="theme-{theme}"' in resp.text


def test_dashboard_invalid_theme_falls_back(dashboard_client):
    resp = dashboard_client.get("/?theme=garbage-not-a-theme")
    assert resp.status_code == 200
    # Falls back to dark (the default).
    assert 'class="theme-dark"' in resp.text


def test_dashboard_theme_cookie_persists(dashboard_client):
    # First visit with ?theme=light should set the cookie.
    resp = dashboard_client.get("/?theme=light")
    assert resp.status_code == 200
    cookies = resp.cookies
    assert cookies.get("mvk_theme") == "light"
    # Next visit without the query param should pick up the cookie.
    resp2 = dashboard_client.get("/", cookies={"mvk_theme": "light"})
    assert 'class="theme-light"' in resp2.text


def test_dashboard_theme_switcher_options_in_header(dashboard_client):
    """Council UX pass replaced the 4-coloured-dots switcher with a single
    ``<select>`` element (accessibility + cleaner UI). All four themes
    must still be present as options."""
    resp = dashboard_client.get("/")
    body = resp.text
    for theme in ("dark", "light", "solarized", "hicontrast"):
        # Either as the new <option value="X"> or, transitionally, as
        # a hand-coded link still in the header.
        assert (f'value="{theme}"' in body) or (f"?theme={theme}" in body), (
            f"theme {theme} not exposed via the theme switcher"
        )


class _CapturingCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), tuple(params)))

    def fetchall(self):
        return []

    def fetchone(self):
        return (0, 0, 0, 0)


class _CursorTx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *exc):
        return False


def _postgres_model_with_cursor(cursor):
    from maverick.world_model_backends import PostgresWorldModel

    world = PostgresWorldModel.__new__(PostgresWorldModel)
    world._tx = lambda: _CursorTx(cursor)
    return world


def test_postgres_recall_candidates_are_tenant_scoped(monkeypatch):
    from maverick.paths import reset_tenant, set_tenant

    monkeypatch.setenv("MAVERICK_STRICT_TENANT_ISOLATION", "1")
    token = set_tenant("tenant-a")
    try:
        cursor = _CapturingCursor()
        _postgres_model_with_cursor(cursor).candidate_goals(False, limit=7)
    finally:
        reset_tenant(token)

    sql, params = cursor.calls[-1]
    assert "FROM goals WHERE" in sql
    assert "tenant_id = %s" in sql
    assert params == ("tenant-a", 7)


def test_postgres_spend_reads_join_tenant_scoped_goals(monkeypatch):
    from maverick.paths import reset_tenant, set_tenant

    monkeypatch.setenv("MAVERICK_STRICT_TENANT_ISOLATION", "1")
    token = set_tenant("tenant-a")
    try:
        cursor = _CapturingCursor()
        world = _postgres_model_with_cursor(cursor)
        world.total_spend()
        world.list_episodes(limit=30)
    finally:
        reset_tenant(token)

    total_sql, total_params = cursor.calls[0]
    list_sql, list_params = cursor.calls[1]
    assert "FROM episodes e JOIN goals g ON g.id = e.goal_id" in total_sql
    assert "g.tenant_id = %s" in total_sql
    assert total_params == ("tenant-a",)
    assert "FROM episodes e JOIN goals g ON g.id = e.goal_id" in list_sql
    assert "g.tenant_id = %s" in list_sql
    assert list_params == ("tenant-a", 30)


def test_postgres_goal_child_reads_join_tenant_scoped_goals(monkeypatch):
    from maverick.paths import reset_tenant, set_tenant

    monkeypatch.setenv("MAVERICK_STRICT_TENANT_ISOLATION", "1")
    token = set_tenant("tenant-a")
    try:
        cursor = _CapturingCursor()
        world = _postgres_model_with_cursor(cursor)
        world.goal_events(42)
        world.search_messages("secret")
        world.list_attachments(42)
    finally:
        reset_tenant(token)

    events_sql, events_params = cursor.calls[0]
    messages_sql, messages_params = cursor.calls[1]
    attachments_sql, attachments_params = cursor.calls[2]
    assert "FROM goal_events ge JOIN goals g ON g.id = ge.goal_id" in events_sql
    assert "g.tenant_id = %s" in events_sql
    assert events_params == (42, 0, "tenant-a", 200)
    assert "FROM messages m JOIN goals g ON g.id = m.goal_id" in messages_sql
    assert "g.tenant_id = %s" in messages_sql
    assert messages_params == ("secret", "tenant-a", 10)
    assert "FROM attachments a JOIN goals g ON g.id = a.goal_id" in attachments_sql
    assert "g.tenant_id = %s" in attachments_sql
    assert attachments_params == (42, "tenant-a")
