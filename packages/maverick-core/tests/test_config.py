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
