"""`maverick doctor` must exit nonzero when a check fails, and report the
world DB the runtime actually opens.

User-testing findings: (1) doctor printed red ✗ rows but always exited 0, so
`maverick doctor && deploy` and CI health gates could not detect a broken
install; (2) the world-db row used the frozen ~/.maverick/world.db, so under
MAVERICK_HOME or a tenant it reported a path the runtime never touches.
"""
from __future__ import annotations

import maverick.health as h
from click.testing import CliRunner
from maverick.cli import main


def test_doctor_exits_nonzero_when_a_check_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MAVERICK_CONFIG", raising=False)
    res = CliRunner().invoke(main, ["doctor"])
    # No provider key configured -> at least one ✗ row -> nonzero exit.
    assert res.exit_code == 1, res.output
    assert "need attention" in res.output


def test_diagnose_returns_zero_when_every_check_is_green(monkeypatch):
    # Force every check to emit no ✗ row; diagnose() must return 0 (exit 0).
    monkeypatch.setattr(h, "_check_config", lambda: {})
    monkeypatch.setattr(h, "_check_anthropic", lambda: h._row(h.GREEN, "anthropic", "ok"))
    monkeypatch.setattr(h, "_check_openai", lambda: None)
    monkeypatch.setattr(h, "_check_sandbox", lambda cfg: None)
    monkeypatch.setattr(h, "_check_channels", lambda cfg: None)
    monkeypatch.setattr(h, "_check_world_db", lambda: None)
    monkeypatch.setattr(h, "_check_shield", lambda: None)
    assert h.diagnose() == 0


def test_diagnose_counts_each_failed_check(monkeypatch):
    monkeypatch.setattr(h, "_check_config", lambda: {})
    monkeypatch.setattr(h, "_check_anthropic", lambda: h._row(h.RED, "anthropic", "no key"))
    monkeypatch.setattr(h, "_check_openai", lambda: None)
    monkeypatch.setattr(h, "_check_sandbox", lambda cfg: h._row(h.RED, "sandbox", "broken"))
    monkeypatch.setattr(h, "_check_channels", lambda cfg: None)
    monkeypatch.setattr(h, "_check_world_db", lambda: None)
    monkeypatch.setattr(h, "_check_shield", lambda: None)
    assert h.diagnose() == 2  # two ✗ rows


def test_doctor_world_db_row_follows_maverick_home(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    res = CliRunner().invoke(main, ["doctor"])
    # The world-db row must point under MAVERICK_HOME, not ~/.maverick.
    assert f"{tmp_path}" in res.output
