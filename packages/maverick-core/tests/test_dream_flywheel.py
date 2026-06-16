"""`maverick dream` turns the flywheel as part of the nightly cycle when the
data engine is on -- and doesn't when it's off."""
from __future__ import annotations

from click.testing import CliRunner
from maverick import flywheel
from maverick.cli import main


class _DreamRep:
    def summary(self):
        return "dream ok"


def _stub_dreaming(monkeypatch):
    monkeypatch.setattr("maverick.dreaming.enabled", lambda: True)
    monkeypatch.setattr("maverick.dreaming.settings", lambda: {"snapshots": False})
    monkeypatch.setattr("maverick.dreaming.dream_cycle", lambda *a, **k: _DreamRep())


def test_dream_runs_the_flywheel_when_enabled(tmp_path, monkeypatch):
    _stub_dreaming(monkeypatch)
    monkeypatch.setenv("MAVERICK_DATA_ENGINE", "1")
    monkeypatch.setattr(
        "maverick.flywheel.maybe_run",
        lambda: flywheel.FlywheelReport(n_episodes=5, guardrails=("g",), predicted_lift=0.5))

    res = CliRunner().invoke(main, ["--db", str(tmp_path / "w.db"), "dream"])
    assert res.exit_code == 0, res.output
    assert "dream ok" in res.output
    assert "[flywheel]" in res.output


def test_dream_skips_the_flywheel_when_data_engine_off(tmp_path, monkeypatch):
    _stub_dreaming(monkeypatch)
    monkeypatch.delenv("MAVERICK_DATA_ENGINE", raising=False)
    monkeypatch.setattr("maverick.config.get_data_engine", lambda: {"enable": False})
    # if it DID run, this would raise -- proving it was skipped
    def _boom():
        raise AssertionError("flywheel should not run when the data engine is off")
    monkeypatch.setattr("maverick.flywheel.maybe_run", _boom)

    res = CliRunner().invoke(main, ["--db", str(tmp_path / "w.db"), "dream"])
    assert res.exit_code == 0, res.output
    assert "[flywheel]" not in res.output
