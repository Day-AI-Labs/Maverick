"""Cluster-wide killswitch (council C4): a halt armed in the shared world store
propagates to every replica's killswitch, not just the one that served the
arm request. On the default SQLite (single-host) backend the shared consult is
skipped -- the local HALT file already covers it and a per-call DB read would be
hot-path cost for no benefit.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest
from maverick import killswitch, world_model


@pytest.fixture
def world(monkeypatch, tmp_path):
    db = Path(tempfile.mkdtemp()) / "w.db"
    monkeypatch.setattr(world_model, "DEFAULT_DB", db)
    w = world_model.WorldModel(db)
    # Isolate the local HALT file to a clean path so a sibling test's file (or its
    # cached presence) can't make check() raise with the file source instead of
    # the cluster source we're asserting.
    monkeypatch.setenv("MAVERICK_HALT_FILE", str(tmp_path / "HALT"))
    # Reset killswitch module state between tests (file cache + shared throttle
    # cache + handle + in-process flag).
    killswitch._last_file_check_ts = 0.0
    killswitch._last_file_present = False
    killswitch._last_shared_check_ts = 0.0
    killswitch._last_shared_halt = None
    killswitch._shared_world = None
    killswitch.clear()
    yield w


def test_world_halt_roundtrip(world):
    assert world.active_halt() is None
    world.arm_halt("budget blown", source="dashboard", armed_by="user:alice")
    st = world.active_halt()
    assert st["reason"] == "budget blown"
    assert st["source"] == "dashboard"
    assert st["armed_by"] == "user:alice"
    assert isinstance(st["armed_at"], (int, float))
    # Re-arm replaces the single global row (no duplicate).
    world.arm_halt("second reason", source="cli")
    assert world.active_halt()["reason"] == "second reason"
    world.disarm_halt()
    assert world.active_halt() is None


def test_shared_consult_skipped_on_sqlite(world):
    world.arm_halt("stop", source="dashboard")
    with mock.patch(
        "maverick.world_model_backends.is_postgres_configured", return_value=False
    ):
        killswitch._last_shared_check_ts = 0.0
        assert killswitch._shared_halt_active() is None  # not consulted on SQLite


def test_check_raises_on_shared_halt_when_postgres(world):
    world.arm_halt("cluster stop", source="dashboard")
    with mock.patch(
        "maverick.world_model_backends.is_postgres_configured", return_value=True
    ), mock.patch("maverick.world_model.open_world", return_value=world):
        killswitch._last_shared_check_ts = 0.0
        with pytest.raises(killswitch.Halted) as ei:
            killswitch.check()
        assert ei.value.reason == "cluster stop"


def test_shared_halt_throttled(world):
    # Within the throttle window the cached value is returned without re-querying.
    world.arm_halt("x", source="dashboard")
    calls = {"n": 0}

    class _Probe:
        def active_halt(self):
            calls["n"] += 1
            return {"reason": "x", "source": "dashboard", "armed_by": "", "armed_at": 1.0}

    with mock.patch(
        "maverick.world_model_backends.is_postgres_configured", return_value=True
    ), mock.patch("maverick.world_model.open_world", return_value=_Probe()):
        killswitch._last_shared_check_ts = 0.0
        killswitch._shared_world = None
        killswitch._shared_halt_active(min_interval=1000.0)
        killswitch._shared_halt_active(min_interval=1000.0)  # cached, no 2nd query
        assert calls["n"] == 1


def test_shared_consult_fails_open(world):
    # A shared-store error must not wedge the run: _shared_halt_active swallows it.
    with mock.patch(
        "maverick.world_model_backends.is_postgres_configured", return_value=True
    ), mock.patch("maverick.world_model.open_world", side_effect=RuntimeError("db down")):
        killswitch._last_shared_check_ts = 0.0
        killswitch._shared_world = None
        assert killswitch._shared_halt_active() is None  # fail-open, no raise
