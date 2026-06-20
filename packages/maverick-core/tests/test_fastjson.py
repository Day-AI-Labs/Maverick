"""fastjson: stdlib-compatible fast JSON seam (orjson when present)."""
from __future__ import annotations

import json

from maverick import fastjson


def test_roundtrip_basic():
    obj = {"b": 1, "a": [1, 2, {"x": "y"}], "n": None, "f": 1.5, "t": True}
    assert fastjson.loads(fastjson.dumps(obj)) == obj


def test_loads_accepts_bytes_and_str():
    assert fastjson.loads('{"a": 1}') == {"a": 1}
    assert fastjson.loads(b'{"a": 1}') == {"a": 1}


def test_dumps_returns_str():
    assert isinstance(fastjson.dumps({"a": 1}), str)


def test_sort_keys():
    out = fastjson.dumps({"b": 1, "a": 2}, sort_keys=True)
    # key order is a..b regardless of backend (whitespace may differ)
    assert out.index('"a"') < out.index('"b"')
    assert fastjson.loads(out) == {"a": 2, "b": 1}


def test_falls_back_for_nonstandard_types():
    # a set isn't JSON-serializable by orjson OR stdlib; default=str in the
    # stdlib fallback stringifies it rather than raising.
    out = fastjson.dumps({"s": {1, 2}})
    assert isinstance(out, str)
    assert "s" in fastjson.loads(out)


def test_output_is_valid_json_for_stdlib_consumers():
    # whatever backend produced it, stdlib json can parse it back
    assert json.loads(fastjson.dumps({"a": [1, 2], "b": "x"})) == {"a": [1, 2], "b": "x"}


def test_backend_name():
    assert fastjson.backend() in ("orjson", "stdlib")


def test_tool_cache_snapshot_roundtrips_via_fastjson(tmp_path, monkeypatch):
    # The wired site: save_snapshot writes rows with fastjson; warm_on_start
    # parses them back. A full round-trip through the fastjson seam.
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MAVERICK_TOOL_CACHE", "1")
    monkeypatch.setenv("MAVERICK_TOOL_CACHE_SNAPSHOT", "1")
    from maverick.cache import tool as tool_cache

    class _Tool:
        name = "toolX"
        parallel_safe = True

    tool_cache.reset()
    tool_cache.store_cached(_Tool(), {"q": 1}, "result-value")
    assert tool_cache.save_snapshot() == 1

    tool_cache.reset()
    loaded = tool_cache.warm_on_start()
    assert loaded == 1
    hit, val = tool_cache.get_cached(_Tool(), {"q": 1})
    assert hit and val == "result-value"
