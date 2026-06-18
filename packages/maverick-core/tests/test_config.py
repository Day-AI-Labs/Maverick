"""Config loader tests."""
from __future__ import annotations

import tempfile
from pathlib import Path

from maverick.config import _interp, get_safety, load_config


def test_missing_config_returns_empty_dict():
    cfg = load_config(Path("/this/path/does/not/exist.toml"))
    assert cfg == {}


def test_corrupt_config_fails_soft_to_empty_dict():
    """A corrupt/unparseable config.toml must not crash the agent loop; it
    fails soft to {} like a missing file. Regression: load_config raised
    TOMLDecodeError, which propagated through every get_role_model/get_safety
    caller. The common real-world trigger is a Windows backslash path that
    TOML reads as an invalid \\U escape."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('workdir = "C:\\Users\\x\\ws"\n[unterminated\n')  # invalid TOML
        path = Path(f.name)
    try:
        assert load_config(path) == {}
    finally:
        path.unlink()


def test_env_var_interpolation(monkeypatch):
    monkeypatch.setenv("MAVERICK_TEST_KEY", "hello")
    assert _interp("${MAVERICK_TEST_KEY}") == "hello"
    assert _interp("prefix-${MAVERICK_TEST_KEY}-suffix") == "prefix-hello-suffix"


def test_unset_env_var_becomes_empty(monkeypatch):
    monkeypatch.delenv("MAVERICK_NEVER_SET", raising=False)
    assert _interp("${MAVERICK_NEVER_SET}") == ""


def test_config_cache_avoids_reparse_but_keeps_interp_live(tmp_path, monkeypatch):
    # Uses a benign [models] key so the literal isn't flagged by detect-secrets.
    import maverick.config as cfg_mod
    cfg_mod.reset_config_cache()
    path = tmp_path / "c.toml"
    path.write_text('[models]\nsummarizer = "${MAVERICK_CFG_TEST_VAL}"\n')

    calls = {"n": 0}
    real_load = cfg_mod.tomllib.load

    def _counting_load(f):
        calls["n"] += 1
        return real_load(f)

    monkeypatch.setattr(cfg_mod.tomllib, "load", _counting_load)

    monkeypatch.setenv("MAVERICK_CFG_TEST_VAL", "first")
    assert cfg_mod.load_config(path)["models"]["summarizer"] == "first"
    # Second read: parse is cached (no new tomllib.load) ...
    monkeypatch.setenv("MAVERICK_CFG_TEST_VAL", "second")
    assert cfg_mod.load_config(path)["models"]["summarizer"] == "second"
    assert calls["n"] == 1  # parsed once, interpolation re-ran live

    # Editing the file (mtime/size changes) invalidates the cache.
    path.write_text(
        '[models]\nsummarizer = "${MAVERICK_CFG_TEST_VAL}"\norchestrator = "x"\n')
    cfg = cfg_mod.load_config(path)
    assert cfg["models"]["orchestrator"] == "x"
    assert calls["n"] == 2
    cfg_mod.reset_config_cache()


def test_load_config_with_models_section():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(
            '[models]\n'
            'orchestrator = "anthropic:claude-opus-4-7"\n'
            'summarizer = "ollama:phi3:14b"\n'
        )
        path = Path(f.name)
    try:
        cfg = load_config(path)
        assert cfg["models"]["orchestrator"] == "anthropic:claude-opus-4-7"
        assert cfg["models"]["summarizer"] == "ollama:phi3:14b"
    finally:
        path.unlink()


def test_nested_dict_interpolation(monkeypatch):
    monkeypatch.setenv("X", "42")
    data = {"a": "${X}", "b": ["${X}", "plain"], "c": {"inner": "${X}"}}
    out = _interp(data)
    assert out["a"] == "42"
    assert out["b"] == ["42", "plain"]
    assert out["c"]["inner"] == "42"


def test_get_safety_preserves_constitution_rules(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(
            '[safety]\n'
            'block_threshold = "high"\n'
            '[[safety.constitution]]\n'
            'name = "no_zephyr"\n'
            'pattern = "zephyr-token"\n'
            'severity = "high"\n'
        )
        path = Path(f.name)
    monkeypatch.setenv("MAVERICK_CONFIG", str(path))
    try:
        safety = get_safety()
        assert safety["constitution"] == [
            {"name": "no_zephyr", "pattern": "zephyr-token", "severity": "high"}
        ]
    finally:
        path.unlink()


def test_toml_cache_is_bounded(tmp_path, monkeypatch):
    """The parsed-TOML cache must not grow without bound across many distinct
    config paths (e.g. one per tenant). Oldest entries are evicted past the cap."""
    from maverick import config as cfg
    cfg.reset_config_cache()
    monkeypatch.setattr(cfg, "_TOML_CACHE_MAX", 8)
    try:
        for i in range(40):
            p = tmp_path / f"t{i}.toml"
            p.write_text(f'[budget]\nmax_dollars = {i}\n', encoding="utf-8")
            assert cfg._read_toml_raw(p) == {"budget": {"max_dollars": i}}
        assert len(cfg._toml_cache) <= 8     # bounded, not 40
    finally:
        cfg.reset_config_cache()
