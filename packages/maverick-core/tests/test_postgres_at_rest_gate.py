"""open_world fails closed on Postgres + encryption-at-rest.

The Postgres backend does not seal content at rest yet (the SQLite backend
does), so selecting it with encryption-at-rest on must refuse rather than
silently store regulated data as plaintext. The gate fires BEFORE psycopg is
imported, so it's verifiable without a live Postgres.
"""
from __future__ import annotations

import pytest
from maverick import world_model as wm


def test_open_world_refuses_postgres_when_encryption_at_rest(monkeypatch):
    monkeypatch.setattr("maverick.world_model_backends.is_postgres_configured", lambda: True)
    monkeypatch.setattr("maverick.crypto_at_rest.at_rest_enabled", lambda: True)
    with pytest.raises(wm.PostgresAtRestUnsupported):
        wm.open_world()


def test_open_world_allows_postgres_without_encryption(monkeypatch):
    # Encryption off -> the gate must NOT fire; it proceeds to open Postgres.
    sentinel = object()
    monkeypatch.setattr("maverick.world_model_backends.is_postgres_configured", lambda: True)
    monkeypatch.setattr("maverick.crypto_at_rest.at_rest_enabled", lambda: False)
    monkeypatch.setattr("maverick.world_model_backends.open_postgres_world", lambda: sentinel)
    assert wm.open_world() is sentinel


def test_open_world_sqlite_is_unaffected(tmp_path, monkeypatch):
    # The gate is Postgres-only; the default SQLite path is untouched.
    monkeypatch.setattr("maverick.world_model_backends.is_postgres_configured", lambda: False)
    w = wm.open_world(tmp_path / "world.db")
    try:
        assert isinstance(w, wm.WorldModel)
    finally:
        w.close()
