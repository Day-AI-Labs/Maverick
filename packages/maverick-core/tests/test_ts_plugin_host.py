"""NDJSON plugin host tests (ts_plugin_host).

The child is a tiny Python script speaking the same NDJSON wire protocol as
the TypeScript SDK (sdks/plugin-ts), so CI needs no Node. It embeds the value
of a canary secret env var into the manifest and an `env` tool, which is how
the scrubbed-env tests observe what reached the child.
"""
from __future__ import annotations

import sys
import textwrap

import pytest
from maverick.tools import Tool
from maverick.ts_plugin_host import (
    TsPluginError,
    load_configured_ts_plugins,
    load_ts_plugin,
)

# argv: fake_plugin.py <sentinel-path> [--describe]
FAKE_PLUGIN = textwrap.dedent('''
    import json, os, sys, time

    CANARY = os.environ.get("MAVERICK_TEST_CANARY_TOKEN", "MISSING")
    MANIFEST = {
        "protocol": "maverick-plugin/1",
        "tools": [
            {"name": "echo", "description": "echo text; canary=" + CANARY,
             "inputSchema": {"type": "object",
                             "properties": {"text": {"type": "string"}}}},
            {"name": "env", "description": "read canary", "inputSchema": {"type": "object"}},
            {"name": "boom", "description": "protocol error", "inputSchema": {"type": "object"}},
            {"name": "crash", "description": "always exits", "inputSchema": {"type": "object"}},
            {"name": "flaky", "description": "exits on first run only",
             "inputSchema": {"type": "object"}},
            {"name": "sleep", "description": "sleep", "inputSchema": {"type": "object"}},
            {"name": "bad name!", "description": "skipped", "inputSchema": {"type": "object"}},
        ],
    }

    def main():
        if "--describe" in sys.argv[1:]:
            print(json.dumps(MANIFEST))
            return
        sentinel = sys.argv[1]
        for line in sys.stdin:
            req = json.loads(line)
            rid, tool, args = req["id"], req["tool"], req.get("args") or {}
            if tool == "crash":
                sys.exit(1)
            if tool == "flaky" and not os.path.exists(sentinel):
                open(sentinel, "w").write("x")
                sys.exit(1)
            if tool == "echo":
                resp = {"id": rid, "result": "echo:" + str(args.get("text", ""))}
            elif tool == "env":
                resp = {"id": rid, "result": CANARY}
            elif tool == "boom":
                resp = {"id": rid, "error": "boom exploded"}
            elif tool == "flaky":
                resp = {"id": rid, "result": "recovered"}
            elif tool == "sleep":
                time.sleep(float(args.get("seconds", 30)))
                resp = {"id": rid, "result": "slept"}
            else:
                resp = {"id": rid, "error": "unknown tool"}
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()

    main()
''')


@pytest.fixture
def fake_cmd(tmp_path):
    script = tmp_path / "fake_plugin.py"
    script.write_text(FAKE_PLUGIN)
    return [sys.executable, str(script), str(tmp_path / "flaky.sentinel")]


def _by_name(tools):
    return {t.name: t for t in tools}


def test_manifest_builds_tools(fake_cmd):
    tools = load_ts_plugin(fake_cmd)
    assert all(isinstance(t, Tool) for t in tools)
    by_name = _by_name(tools)
    # "bad name!" fails the tool-name check and is skipped.
    assert set(by_name) == {"echo", "env", "boom", "crash", "flaky", "sleep"}
    echo = by_name["echo"]
    assert echo.description.startswith("echo text")
    assert echo.input_schema["properties"]["text"] == {"type": "string"}


def test_round_trip_call(fake_cmd):
    by_name = _by_name(load_ts_plugin(fake_cmd))
    assert by_name["echo"].fn({"text": "hi"}) == "echo:hi"
    assert by_name["echo"].fn({"text": "again"}) == "echo:again"  # same child


def test_protocol_error_maps_to_error_string(fake_cmd):
    by_name = _by_name(load_ts_plugin(fake_cmd))
    out = by_name["boom"].fn({})
    assert out.startswith("ERROR:")
    assert "boom exploded" in out


def test_timeout_returns_error(fake_cmd):
    by_name = _by_name(load_ts_plugin(fake_cmd, call_timeout=0.5))
    out = by_name["sleep"].fn({"seconds": 30})
    assert out.startswith("ERROR:")
    assert "timed out" in out


def test_crashed_child_restarted_once(fake_cmd):
    by_name = _by_name(load_ts_plugin(fake_cmd))
    # First request kills the child before it replies; the host restarts the
    # child and retries, and the fresh child (sentinel now present) succeeds.
    assert by_name["flaky"].fn({}) == "recovered"


def test_persistently_crashing_child_is_error(fake_cmd):
    by_name = _by_name(load_ts_plugin(fake_cmd))
    out = by_name["crash"].fn({})
    assert out.startswith("ERROR:")
    assert "crashed" in out
    # The plugin still works afterwards on a fresh child.
    assert by_name["echo"].fn({"text": "alive"}) == "echo:alive"


def test_child_env_is_scrubbed(fake_cmd, monkeypatch):
    monkeypatch.setenv("MAVERICK_TEST_CANARY_TOKEN", "supersecret")
    by_name = _by_name(load_ts_plugin(fake_cmd))
    # --describe subprocess: the canary would be embedded in the description.
    assert "canary=MISSING" in by_name["echo"].description
    # Persistent call child: the canary would be returned by the env tool.
    assert by_name["env"].fn({}) == "MISSING"


def test_bad_manifest_raises():
    with pytest.raises(TsPluginError):
        load_ts_plugin([sys.executable, "-c", "print('not a manifest')"])


def test_load_configured_ts_plugins(fake_cmd, monkeypatch):
    monkeypatch.setattr(
        "maverick.config.load_config",
        lambda *a, **k: {"plugins": {"ts": [
            fake_cmd,
            ["/nonexistent-ts-plugin-xyz"],  # broken entry: logged + skipped
            "not-an-argv-list",              # malformed entry: logged + skipped
        ]}},
    )
    by_name = _by_name(load_configured_ts_plugins())
    assert "echo" in by_name
    assert by_name["echo"].fn({"text": "cfg"}) == "echo:cfg"


def test_load_configured_ts_plugins_default_empty(monkeypatch):
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
    assert load_configured_ts_plugins() == []


def test_plugin_file_change_after_manifest_is_blocked(fake_cmd):
    by_name = _by_name(load_ts_plugin(fake_cmd))
    script = fake_cmd[1]
    with open(script, "a", encoding="utf-8") as f:
        f.write("\n# modified after manifest discovery\n")

    out = by_name["echo"].fn({"text": "hi"})
    assert out.startswith("ERROR:")
    assert "changed after manifest discovery" in out
