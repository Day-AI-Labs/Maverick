"""P1 multi-tenancy: per-tenant ``world.db`` isolation.

Completes the world-model leg of per-user tenancy. Cross-session memory and the
audit log already resolve their dirs via :func:`maverick.paths.data_dir`; this
gives each tenant its OWN world.db the same way. Default off -> single-tenant
behaviour (one shared ``~/.maverick/world.db``) is unchanged.

HOME is isolated per test by the autouse ``_isolate_maverick_home`` conftest
fixture, so these are hermetic (no real ``~/.maverick`` touched, no network).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from maverick.paths import maverick_home
from maverick.world_model import world_for_tenant


@pytest.fixture(autouse=True)
def _clear_world_cache():
    """Drop the process-wide per-tenant WorldModel cache around each test.

    The cache is keyed by resolved DB path; HOME is per-test so paths already
    differ, but clearing (and closing) keeps SQLite FDs from leaking across the
    suite and makes instance-identity assertions deterministic.
    """
    import maverick.world_model as wm

    def _drain():
        for w in list(wm._tenant_worlds.values()):
            try:
                w.close()
            except Exception:
                pass
        wm._tenant_worlds.clear()

    _drain()
    yield
    _drain()


# --- path resolution -------------------------------------------------------

def test_no_tenant_is_legacy_world_db(monkeypatch):
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    w = world_for_tenant(None)
    assert w.path == maverick_home() / "world.db"
    assert "tenants" not in w.path.parts


def test_tenant_world_db_under_tenants_dir(monkeypatch):
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    w = world_for_tenant("acme")
    assert w.path == maverick_home() / "tenants" / "acme" / "world.db"


def test_same_tenant_returns_cached_instance(monkeypatch):
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    assert world_for_tenant("acme") is world_for_tenant("acme")
    # None (shared default) is likewise cached/stable.
    assert world_for_tenant(None) is world_for_tenant(None)


def test_different_tenants_get_different_worlds(monkeypatch):
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    a = world_for_tenant("acme")
    b = world_for_tenant("globex")
    assert a is not b
    assert a.path != b.path
    assert world_for_tenant(None) is not a  # shared default distinct from a tenant


# --- data isolation --------------------------------------------------------

def test_goals_are_isolated_across_tenants(monkeypatch):
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    world_a = world_for_tenant("tenant-a")
    world_b = world_for_tenant("tenant-b")

    gid = world_a.create_goal("a-only", "secret for tenant a")

    # Tenant A sees its goal; tenant B's world is empty -> no cross-tenant leak.
    assert world_a.get_goal(gid) is not None
    assert world_a.get_goal(gid).title == "a-only"
    assert world_b.get_goal(gid) is None
    assert world_b.list_goals() == []


# --- server routing (the actual wiring) ------------------------------------

@dataclass
class _Msg:
    text: str
    channel: str
    user_id: str


def _build_server(monkeypatch):
    """A minimal Server whose shared world is the legacy ~/.maverick/world.db."""
    from maverick import server as server_mod
    from maverick.world_model import WorldModel

    monkeypatch.setattr("maverick.config.load_config", dict)
    shared = WorldModel(maverick_home() / "world.db")
    srv = server_mod.Server.__new__(server_mod.Server)
    srv.world = shared
    srv.llm = object()
    srv.sandbox = object()
    srv.max_depth = 3
    srv._channels = []
    srv._tasks = []
    srv._shield = None  # shield off -> input/output scans skipped
    return server_mod, srv, shared


def test_handle_message_routes_goal_to_user_tenant(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT_BY_USER", "1")
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    server_mod, srv, shared = _build_server(monkeypatch)

    captured = {}

    async def _fake_run_goal(llm, world, budget, goal_id, **kwargs):
        # Prove run_goal is handed the per-tenant world, not the shared one.
        captured["world"] = world
        captured["goal_id"] = goal_id
        return "done"

    monkeypatch.setattr(server_mod, "run_goal", _fake_run_goal)

    msg = _Msg(text="hello from X", channel="tg", user_id="X")
    out = asyncio.run(srv._handle_message(msg))
    assert "done" in out  # disclosure may be prepended on the first turn

    tenant_world = world_for_tenant("tg:X")
    # The goal landed in user X's tenant world...
    assert captured["world"] is tenant_world
    assert tenant_world.get_goal(captured["goal_id"]) is not None
    assert tenant_world.get_goal(captured["goal_id"]).title == "hello from X"
    # ...and the conversation + user turn did too.
    convs = tenant_world.list_conversations()
    assert [(c.channel, c.user_id) for c in convs] == [("tg", "X")]
    turns = tenant_world.recent_turns(convs[0].id)
    assert [(t.role, t.content) for t in turns] == [("user", "hello from X")]

    # The shared default world is untouched -- nothing leaked there.
    assert shared.list_goals() == []
    assert shared.list_conversations() == []


def test_world_for_tenant_rejects_overlong_tenant(monkeypatch):
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)

    with pytest.raises(ValueError, match="tenant id is too long"):
        world_for_tenant("x" * 201)


def test_world_for_tenant_caps_cached_tenant_worlds(monkeypatch):
    # Reaching MAX_TENANT_WORLDS rejects new tenants so tenant_by_user cannot
    # create unbounded tenant world.db files.
    import maverick.world_model as wm

    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    wm._tenant_worlds.clear()
    monkeypatch.setattr(wm, "MAX_TENANT_WORLDS", 2)

    first = world_for_tenant("tenant-1")
    assert world_for_tenant("tenant-2") is not first
    assert world_for_tenant("tenant-1") is first
    with pytest.raises(wm.TenantWorldLimitError):
        world_for_tenant("tenant-3")
    keys = list(wm._tenant_worlds)
    assert len(wm._tenant_worlds) == 2
    assert any(k.endswith("tenant-1/world.db") for k in keys)
    assert any(k.endswith("tenant-2/world.db") for k in keys)
    assert not any(k.endswith("tenant-3/world.db") for k in keys)
    wm._tenant_worlds.clear()


def test_handle_message_rejects_tenant_resolution_failure(monkeypatch):
    monkeypatch.setenv("MAVERICK_TENANT_BY_USER", "1")
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    server_mod, srv, shared = _build_server(monkeypatch)

    async def _fake_run_goal(*args, **kwargs):
        raise AssertionError("run_goal must not run without an isolated tenant")

    monkeypatch.setattr(server_mod, "run_goal", _fake_run_goal)

    msg = _Msg(text="do not fall back", channel="tg", user_id="X" * 201)
    out = asyncio.run(srv._handle_message(msg))

    assert "Tenant isolation is unavailable" in out
    assert shared.list_goals() == []
    assert shared.list_conversations() == []


def test_handle_message_uses_shared_world_when_tenancy_off(monkeypatch):
    monkeypatch.delenv("MAVERICK_TENANT_BY_USER", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    server_mod, srv, shared = _build_server(monkeypatch)

    captured = {}

    async def _fake_run_goal(llm, world, budget, goal_id, **kwargs):
        captured["world"] = world
        return "ok"

    monkeypatch.setattr(server_mod, "run_goal", _fake_run_goal)

    msg = _Msg(text="hi", channel="tg", user_id="Y")
    asyncio.run(srv._handle_message(msg))

    # Tenancy off: the message-scoped world IS the server's shared self.world
    # instance (``world is self.world``), and the goal lives there -- legacy
    # single-tenant behaviour, unchanged, no second connection opened.
    assert captured["world"] is shared
    assert len(shared.list_goals()) == 1
    # No per-tenant dir was created.
    assert not (maverick_home() / "tenants").exists()


# --- CLI routing (the actual wiring) ---------------------------------------
# The channel server isolates world.db per tenant via world_for_tenant; the CLI
# must too, or `MAVERICK_TENANT=acme maverick start ...` would pool one
# business's run history into the shared world.db. The `--db` default resolves
# to Workspace.current().db_path (== the legacy path when no tenant is set).

def test_cli_defaults_world_db_to_active_tenant(monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main

    monkeypatch.delenv("MAVERICK_HOME", raising=False)
    monkeypatch.setenv("MAVERICK_TENANT", "acme")

    # `status` opens the world at the resolved default db (no --db passed).
    result = CliRunner().invoke(main, ["status"])
    assert result.exit_code == 0, result.output

    # The run history landed in acme's OWN world.db, not the shared default.
    assert (maverick_home() / "tenants" / "acme" / "world.db").exists()
    assert not (maverick_home() / "world.db").exists()


def test_cli_no_tenant_uses_legacy_world_db(monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main

    monkeypatch.delenv("MAVERICK_HOME", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)

    result = CliRunner().invoke(main, ["status"])
    assert result.exit_code == 0, result.output

    # Single-tenant unchanged: the legacy shared world.db, no per-tenant dir.
    assert (maverick_home() / "world.db").exists()
    assert not (maverick_home() / "tenants").exists()


def test_cli_explicit_db_overrides_tenant(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from maverick.cli import main

    monkeypatch.delenv("MAVERICK_HOME", raising=False)
    monkeypatch.setenv("MAVERICK_TENANT", "acme")
    explicit = tmp_path / "explicit" / "world.db"

    result = CliRunner().invoke(main, ["--db", str(explicit), "status"])
    assert result.exit_code == 0, result.output

    # An explicit --db always wins over the tenant default.
    assert explicit.exists()
    assert not (maverick_home() / "tenants" / "acme" / "world.db").exists()
