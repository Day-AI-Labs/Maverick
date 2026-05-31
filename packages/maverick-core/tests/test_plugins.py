"""Plugin SDK discovery tests.

Uses a stub entry_points iterator monkey-patched into
`maverick.plugins._entry_points` so we don't need to actually install a
sibling plugin package in CI.

v0.2 (council Tier 0 fix): plugin discovery now requires an explicit
allowlist. These tests set MAVERICK_PLUGINS_ALLOW=* to preserve the
pre-0.2 "everything loads" behavior so they keep testing the
discovery / contract semantics specifically. The allowlist itself is
tested in test_tier0_security.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from maverick import plugins


@pytest.fixture(autouse=True)
def _allow_all_plugins(monkeypatch):
    monkeypatch.setenv("MAVERICK_PLUGINS_ALLOW", "*")


@dataclass
class _FakeEP:
    name: str
    target: object

    def load(self):
        if isinstance(self.target, Exception):
            raise self.target
        return self.target


def _set_eps(monkeypatch, mapping):
    def fake(group: str):
        return mapping.get(group, [])
    monkeypatch.setattr(plugins, "_entry_points", fake)


def test_discover_tools_returns_factories(monkeypatch):
    def factory():
        return "fake-tool-instance"

    _set_eps(monkeypatch, {"maverick.tools": [_FakeEP("weather", factory)]})
    out = plugins.discover_tools()
    assert len(out) == 1
    name, fac = out[0]
    assert name == "weather"
    assert fac() == "fake-tool-instance"


def test_discover_skips_failing_plugin(monkeypatch):
    """A plugin that raises at load time logs and is skipped."""
    def factory():
        return "ok"

    _set_eps(monkeypatch, {
        "maverick.tools": [
            _FakeEP("bad", RuntimeError("import boom")),
            _FakeEP("good", factory),
        ],
    })
    out = plugins.discover_tools()
    assert [name for name, _ in out] == ["good"]


def test_discover_skips_non_callable_tool(monkeypatch):
    _set_eps(monkeypatch, {
        "maverick.tools": [_FakeEP("notcallable", "just a string")],
    })
    assert plugins.discover_tools() == []


def test_discover_channels_returns_classes(monkeypatch):
    class FakeChannel: ...
    _set_eps(monkeypatch, {
        "maverick.channels": [_FakeEP("custom", FakeChannel)],
    })
    out = plugins.discover_channels()
    assert out == [("custom", FakeChannel)]


def test_discover_channels_rejects_string(monkeypatch):
    _set_eps(monkeypatch, {
        "maverick.channels": [_FakeEP("oops", "telegram.foo")],
    })
    assert plugins.discover_channels() == []


def test_discover_skills_passes_through(monkeypatch):
    class Skill:
        name = "weather"
    inst = Skill()
    _set_eps(monkeypatch, {"maverick.skills": [_FakeEP("weather", inst)]})
    assert plugins.discover_skills() == [inst]


def test_discover_personas_returns_renderers(monkeypatch):
    def render():
        return "\nYou are a pirate."
    _set_eps(monkeypatch, {"maverick.personas": [_FakeEP("pirate", render)]})
    out = plugins.discover_personas()
    assert "pirate" in out
    assert out["pirate"]() == "\nYou are a pirate."


def test_installed_plugins_snapshot(monkeypatch):
    def make_tool():
        return None

    class ChanX: ...

    class SkillObj:
        name = "weather"

    def persona():
        return ""

    _set_eps(monkeypatch, {
        "maverick.tools":    [_FakeEP("t1", make_tool)],
        "maverick.channels": [_FakeEP("c1", ChanX)],
        "maverick.skills":   [_FakeEP("s1", SkillObj())],
        "maverick.personas": [_FakeEP("p1", persona)],
    })
    snap = plugins.installed_plugins()
    assert snap == {
        "tools": ["t1"],
        "channels": ["c1"],
        "skills": ["weather"],
        "personas": ["p1"],
    }


def test_base_registry_loads_plugin_tools(monkeypatch, tmp_path):
    """Plugin tool factories are invoked when building the agent registry."""
    from maverick.sandbox import LocalBackend
    from maverick.tools import Tool, base_registry
    from maverick.world_model import WorldModel

    sentinel = Tool(
        name="weather",
        description="fake",
        input_schema={"type": "object"},
        fn=lambda _: "sunny",
    )

    def factory():
        return sentinel

    _set_eps(monkeypatch, {"maverick.tools": [_FakeEP("weather", factory)]})

    wm = WorldModel(path=tmp_path / "w.db")
    reg = base_registry(wm, LocalBackend(workdir=tmp_path))
    assert "weather" in {t.name for t in reg.all()}
