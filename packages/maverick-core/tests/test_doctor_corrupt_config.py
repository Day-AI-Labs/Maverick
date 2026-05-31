"""`maverick doctor` must flag a corrupt config.toml.

load_config() fails soft (returns {} on a TOML syntax error), so doctor's old
check went through it and always reported config OK -- even though every user
setting was being silently dropped. _check_config now parses the TOML directly.
"""
from __future__ import annotations

from pathlib import Path

from maverick.health import _check_config


def test_doctor_flags_corrupt_config(tmp_path: Path, capsys):
    # conftest's autouse fixture points HOME at tmp_path.
    (tmp_path / ".maverick").mkdir()
    (tmp_path / ".maverick" / "config.toml").write_text("[budget\nmax_dollars = oops\n")

    cfg = _check_config()
    out = capsys.readouterr().out
    assert "invalid TOML" in out
    assert "IGNORED" in out
    assert cfg == {}


def test_doctor_passes_valid_config(tmp_path: Path, capsys):
    (tmp_path / ".maverick").mkdir()
    (tmp_path / ".maverick" / "config.toml").write_text("[budget]\nmax_dollars = 5.0\n")

    cfg = _check_config()
    out = capsys.readouterr().out
    assert "invalid TOML" not in out
    assert cfg.get("budget", {}).get("max_dollars") == 5.0
