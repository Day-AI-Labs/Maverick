"""open_world() backend-selection factory.

Verifies the factory returns the SQLite WorldModel by default and the
PostgresWorldModel when the postgres backend is configured, without ever
opening a real Postgres connection.
"""
from __future__ import annotations

import importlib.util

import pytest

_HAS_PSYCOPG = importlib.util.find_spec("psycopg") is not None


def test_open_world_defaults_to_sqlite(tmp_path, monkeypatch):
    """No config / env -> SQLite WorldModel, using the given path."""
    monkeypatch.delenv("MAVERICK_WORLD_BACKEND", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no config.toml here

    from maverick.world_model import WorldModel, open_world

    db = tmp_path / "world.db"
    world = open_world(db)
    try:
        assert isinstance(world, WorldModel)
        assert world.path == db
    finally:
        world.close()


def test_open_world_selects_postgres_when_configured(monkeypatch):
    """backend=postgres -> PostgresWorldModel, via the lazily-imported
    factory, without opening SQLite or a real PG connection."""
    import maverick.world_model_backends as backends

    sentinel = object()
    monkeypatch.setattr(backends, "is_postgres_configured", lambda: True)
    monkeypatch.setattr(backends, "open_postgres_world", lambda: sentinel)

    from maverick.world_model import open_world

    # path is ignored for the postgres branch.
    assert open_world() is sentinel


@pytest.mark.skipif(not _HAS_PSYCOPG, reason="psycopg not installed")
def test_open_world_returns_real_postgres_model(monkeypatch):
    """End-to-end branch with psycopg present: open_world() builds a real
    PostgresWorldModel. The connection + migration are mocked so no live
    database is required."""
    monkeypatch.setenv("MAVERICK_WORLD_BACKEND", "postgres")
    monkeypatch.setenv("MAVERICK_PG_DSN", "postgres://test")

    from maverick.world_model_backends import PostgresWorldModel

    monkeypatch.setattr(PostgresWorldModel, "_migrate", lambda self: None)
    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: object())

    from maverick.world_model import open_world

    world = open_world()
    assert isinstance(world, PostgresWorldModel)


def test_postgres_model_has_message_attachment_dedup_parity():
    """Guard the #469 parity surface without needing a live DB: importing the
    class is lazy (psycopg only loads in __init__), so a missing method here
    would AttributeError on the server/orchestrator hot paths under
    MAVERICK_WORLD_BACKEND=postgres. Checked in the normal matrix, not just
    the DSN-gated round-trip job."""
    from maverick.world_model_backends.postgres import PostgresWorldModel
    for name in (
        "append_message", "search_messages",
        "add_attachment", "list_attachments",
        "mark_message_processed", "lookup_processed_message",
        "is_processed_message", "prune_processed_messages",
    ):
        assert callable(getattr(PostgresWorldModel, name, None)), f"missing {name}"
