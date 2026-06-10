"""Compaction plug-in API: registry, dispatch, fail-safe to built-in."""
from __future__ import annotations

import pytest
from maverick import compaction_plugins as cp


@pytest.fixture(autouse=True)
def _restore_registry():
    saved = dict(cp._REGISTRY)
    yield
    cp._REGISTRY.clear()
    cp._REGISTRY.update(saved)


class _Marker:
    name = "marker"

    def compact(self, messages, **kw):
        return [{"role": "system", "content": f"compacted {len(messages)}"}]


def _msgs(n):
    return [{"role": "user", "content": f"m{i}"} for i in range(n)]


def test_builtin_registered_by_default():
    assert "heuristic" in cp.available()
    assert cp.get("heuristic") is not None


def test_register_and_dispatch():
    cp.register(_Marker())
    out = cp.compact_with(_msgs(5), strategy="marker")
    assert out == [{"role": "system", "content": "compacted 5"}]


def test_default_uses_heuristic(monkeypatch):
    monkeypatch.delenv("MAVERICK_COMPACTION_STRATEGY", raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda: {})
    # short message list -> heuristic returns it unchanged
    msgs = _msgs(3)
    assert cp.compact_with(msgs) == msgs


def test_unknown_strategy_fails_safe_to_builtin(monkeypatch):
    monkeypatch.setenv("MAVERICK_COMPACTION_STRATEGY", "does-not-exist")
    msgs = _msgs(3)
    # falls back to heuristic (returns short list unchanged), not an error
    assert cp.compact_with(msgs) == msgs


def test_config_selects_strategy(monkeypatch):
    cp.register(_Marker())
    monkeypatch.delenv("MAVERICK_COMPACTION_STRATEGY", raising=False)
    monkeypatch.setattr("maverick.config.load_config",
                        lambda: {"context": {"compaction_strategy": "marker"}})
    out = cp.compact_with(_msgs(2))
    assert out[0]["content"] == "compacted 2"


def test_env_overrides_config(monkeypatch):
    cp.register(_Marker())
    monkeypatch.setenv("MAVERICK_COMPACTION_STRATEGY", "marker")
    monkeypatch.setattr("maverick.config.load_config",
                        lambda: {"context": {"compaction_strategy": "heuristic"}})
    assert cp.compact_with(_msgs(2))[0]["content"] == "compacted 2"


def test_register_duplicate_rejected():
    cp.register(_Marker())
    with pytest.raises(ValueError, match="already registered"):
        cp.register(_Marker())
    cp.register(_Marker(), replace=True)  # replace is allowed


def test_register_validates_strategy():
    class _NoName:
        compact = lambda self, m, **k: m  # noqa: E731

    with pytest.raises(ValueError, match="non-empty string"):
        cp.register(_NoName())


def test_heuristic_strategy_actually_compacts():
    # a long list with a big tool_result should get digested by the built-in
    big = "x" * 100000
    msgs = [{"role": "user", "content": "brief"}]
    for i in range(20):
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": big}]})
    out = cp.compact_with(msgs, strategy="heuristic", max_tool_bytes=1000,
                          keep_recent=3)
    # the body shrank (older tool_results digested)
    assert sum(len(str(m)) for m in out) < sum(len(str(m)) for m in msgs)
