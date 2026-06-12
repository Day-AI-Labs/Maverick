"""`maverick config-lint` must FAIL on a corrupt config, not say "config OK".

Platform-test finding (round 4): config-lint called load_config(), which is
deliberately fail-soft -- a TOMLDecodeError is swallowed and {} returned with
only a warning log. So linting a syntactically broken config.toml linted an
empty dict, found nothing, and printed "config OK" with exit 0. The one tool
whose entire job is to validate the config silently blessed a file in which
every user setting is being dropped. (maverick doctor's _check_config already
guards this by parsing the raw file; config-lint now does the same.)
"""
from __future__ import annotations

from click.testing import CliRunner


def _invoke(tmp_path, monkeypatch, text: str):
    cfg = tmp_path / "config.toml"
    cfg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.cli import main
    return CliRunner().invoke(main, ["config-lint"])


def test_corrupt_toml_fails(tmp_path, monkeypatch):
    res = _invoke(tmp_path, monkeypatch, "[budget\nmax_dollars = \n")
    assert res.exit_code == 1, res.output
    assert "config OK" not in res.output
    low = res.output.lower()
    assert "toml" in low or "parse" in low or "invalid" in low or "syntax" in low


def test_valid_config_still_ok(tmp_path, monkeypatch):
    res = _invoke(tmp_path, monkeypatch, "[budget]\nmax_dollars = 5.0\n")
    assert res.exit_code == 0, res.output
    assert "OK" in res.output


def test_absent_config_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_CONFIG", str(tmp_path / "nope.toml"))
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.cli import main
    res = CliRunner().invoke(main, ["config-lint"])
    assert res.exit_code == 0, res.output
    # An absent config is a legitimate (built-in defaults) state -- but it must
    # SAY so, not bless a non-existent file with a misleading "config OK" as if
    # a real file had been validated (user-testing finding).
    assert "config OK" not in res.output
    assert "built-in defaults" in res.output
