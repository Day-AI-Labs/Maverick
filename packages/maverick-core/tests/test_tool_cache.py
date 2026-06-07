"""Tool-output cache: memoize side-effect-free tool calls (ROADMAP 2028 H1)."""
from __future__ import annotations

import asyncio

import pytest
from maverick import tool_cache
from maverick.tools import Tool, ToolRegistry


@pytest.fixture(autouse=True)
def _clean_cache():
    tool_cache.reset()
    yield
    tool_cache.reset()


def _counting_tool(name="read_file", parallel_safe=True):
    calls = {"n": 0}

    def _fn(args):
        calls["n"] += 1
        return f"result-for-{args.get('path', '')}-{calls['n']}"

    return Tool(name=name, description="x", input_schema={"type": "object"},
                fn=_fn, parallel_safe=parallel_safe), calls


def _run(reg, name, args):
    return asyncio.run(reg.run(name, args))


def test_disabled_by_default_no_caching(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TOOL_CACHE", raising=False)
    tool, calls = _counting_tool()
    reg = ToolRegistry()
    reg.register(tool)
    _run(reg, "read_file", {"path": "a"})
    _run(reg, "read_file", {"path": "a"})
    assert calls["n"] == 2  # no memoization when off


def test_hit_serves_cache_without_reinvoking(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
    tool, calls = _counting_tool()
    reg = ToolRegistry()
    reg.register(tool)
    r1 = _run(reg, "read_file", {"path": "a"})
    r2 = _run(reg, "read_file", {"path": "a"})
    assert r1 == r2
    assert calls["n"] == 1  # second call served from cache
    assert tool_cache.stats()["hits"] == 1


def test_distinct_args_miss(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
    tool, calls = _counting_tool()
    reg = ToolRegistry()
    reg.register(tool)
    _run(reg, "read_file", {"path": "a"})
    _run(reg, "read_file", {"path": "b"})
    assert calls["n"] == 2  # different args -> distinct keys


def test_non_parallel_safe_never_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
    tool, calls = _counting_tool(name="write_file", parallel_safe=False)
    reg = ToolRegistry()
    reg.register(tool)
    _run(reg, "write_file", {"path": "a"})
    _run(reg, "write_file", {"path": "a"})
    assert calls["n"] == 2  # writes are never memoized


def test_error_results_not_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")

    def _boom(args):
        raise RuntimeError("kaboom")

    reg = ToolRegistry()
    reg.register(Tool(name="read_file", description="x",
                      input_schema={"type": "object"}, fn=_boom,
                      parallel_safe=True))
    r1 = _run(reg, "read_file", {"path": "a"})
    assert r1.startswith("ERROR:")
    assert tool_cache.stats()["size"] == 0  # error not stored


def test_lru_eviction(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
    monkeypatch.setattr(tool_cache, "_maxsize", lambda: 2)
    tool, calls = _counting_tool()
    reg = ToolRegistry()
    reg.register(tool)
    _run(reg, "read_file", {"path": "a"})  # store a
    _run(reg, "read_file", {"path": "b"})  # store b
    _run(reg, "read_file", {"path": "c"})  # store c, evict a (LRU)
    assert tool_cache.stats()["size"] == 2
    _run(reg, "read_file", {"path": "a"})  # a was evicted -> recompute
    assert calls["n"] == 4


def test_ttl_expiry(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
    monkeypatch.setattr(tool_cache, "_ttl_s", lambda: 10.0)
    clock = {"t": 1000.0}
    monkeypatch.setattr(tool_cache.time, "monotonic", lambda: clock["t"])
    tool, calls = _counting_tool()
    reg = ToolRegistry()
    reg.register(tool)
    _run(reg, "read_file", {"path": "a"})  # stored at t=1000
    clock["t"] = 1005.0
    _run(reg, "read_file", {"path": "a"})  # within TTL -> hit
    assert calls["n"] == 1
    clock["t"] = 1020.0
    _run(reg, "read_file", {"path": "a"})  # past TTL -> recompute
    assert calls["n"] == 2
