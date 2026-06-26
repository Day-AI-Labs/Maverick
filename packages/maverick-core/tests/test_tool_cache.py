"""Tool-output cache: memoize side-effect-free tool calls (ROADMAP 2028 H1)."""
from __future__ import annotations

import asyncio

import pytest
from maverick.cache import tool as tool_cache
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


class TestWarmOnStart:
    """Cache-warm-on-start: snapshot persistence + reload (roadmap 2027-H1 perf)."""

    def _tool(self):
        import types
        return types.SimpleNamespace(name="repo_map", parallel_safe=True)

    def test_snapshot_roundtrip(self, monkeypatch, tmp_path):
        from maverick.cache import tool as tc
        snap = tmp_path / "snap.jsonl"
        monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
        monkeypatch.setenv("MAVERICK_TOOL_CACHE_SNAPSHOT", "1")
        monkeypatch.setenv("MAVERICK_TOOL_CACHE_SNAPSHOT_PATH", str(snap))
        tc.reset()
        tool = self._tool()
        tc.store_cached(tool, {"path": "."}, "the map")
        assert tc.save_snapshot() == 1
        # New "process": clear memory, then a lookup warms from disk.
        tc.reset()
        hit, value = tc.get_cached(tool, {"path": "."})
        assert hit and value == "the map"
        tc.reset()

    def test_snapshot_off_means_no_warm(self, monkeypatch, tmp_path):
        from maverick.cache import tool as tc
        snap = tmp_path / "snap.jsonl"
        snap.write_text('{"k": "repo_map:abc", "v": "x", "t": 0}\n')
        monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
        monkeypatch.delenv("MAVERICK_TOOL_CACHE_SNAPSHOT", raising=False)
        monkeypatch.setenv("MAVERICK_TOOL_CACHE_SNAPSHOT_PATH", str(snap))
        tc.reset()
        assert tc.warm_on_start() == 0
        tc.reset()

    def test_warm_respects_ttl_and_corrupt_lines(self, monkeypatch, tmp_path):
        import json as _json
        import time as _time

        from maverick.cache import tool as tc
        snap = tmp_path / "snap.jsonl"
        fresh = {"k": "repo_map:fresh", "v": "ok", "t": _time.time()}
        stale = {"k": "repo_map:stale", "v": "old", "t": _time.time() - 9999}
        snap.write_text(
            _json.dumps(fresh) + "\n" + _json.dumps(stale) + "\nnot-json\n"
        )
        monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
        monkeypatch.setenv("MAVERICK_TOOL_CACHE_SNAPSHOT", "1")
        monkeypatch.setenv("MAVERICK_TOOL_CACHE_SNAPSHOT_PATH", str(snap))
        # TTL 60s: 'stale' is expired at load; corrupt line skipped.
        monkeypatch.setattr(tc, "_cfg", lambda: {"output_cache_ttl_s": 60})
        tc.reset()
        assert tc.warm_on_start() == 1
        assert tc.stats()["size"] == 1
        tc.reset()

    def test_warm_is_idempotent_per_process(self, monkeypatch, tmp_path):
        import json as _json
        import time as _time

        from maverick.cache import tool as tc
        snap = tmp_path / "snap.jsonl"
        snap.write_text(_json.dumps({"k": "a:1", "v": "x", "t": _time.time()}) + "\n")
        monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
        monkeypatch.setenv("MAVERICK_TOOL_CACHE_SNAPSHOT", "1")
        monkeypatch.setenv("MAVERICK_TOOL_CACHE_SNAPSHOT_PATH", str(snap))
        tc.reset()
        assert tc.warm_on_start() == 1
        assert tc.warm_on_start() == 0  # second call no-ops
        tc.reset()
