"""AutoGen + CrewAI adapters: both directions, with fake frameworks."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from maverick.agent_framework_adapters import (
    maverick_autogen_callable,
    maverick_autogen_tool,
    maverick_crewai_tool,
    wrap_autogen_tool,
    wrap_crewai_tool,
)


def _fake_delegation(monkeypatch, result="swarm did it"):
    calls = {}

    def fake_run(goal, description="", **kw):
        calls["goal"] = goal
        calls["kw"] = kw
        return result

    import maverick.agent_framework_adapters as mod
    monkeypatch.setattr(mod, "run_maverick_goal", fake_run)
    return calls


# ---- Maverick -> AutoGen ----

def test_autogen_callable_delegates(monkeypatch):
    calls = _fake_delegation(monkeypatch)
    fn = maverick_autogen_callable(max_dollars=1.5, user_id="u1")
    out = fn("ship the feature", "with tests")
    assert out == "swarm did it"
    assert calls["goal"] == "ship the feature"
    assert calls["kw"]["max_dollars"] == 1.5 and calls["kw"]["user_id"] == "u1"
    assert fn.__name__ == "run_maverick" and fn.__doc__


def test_autogen_tool_wraps_in_functiontool(monkeypatch):
    _fake_delegation(monkeypatch)
    captured = {}

    class _FunctionTool:
        def __init__(self, func, description="", name=""):
            captured["func"] = func
            captured["name"] = name

    fake = types.ModuleType("autogen_core.tools")
    fake.FunctionTool = _FunctionTool
    monkeypatch.setitem(sys.modules, "autogen_core", types.ModuleType("autogen_core"))
    monkeypatch.setitem(sys.modules, "autogen_core.tools", fake)
    tool = maverick_autogen_tool()
    assert isinstance(tool, _FunctionTool)
    assert captured["name"] == "run_maverick"
    assert captured["func"]("g") == "swarm did it"


def test_autogen_tool_missing_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "autogen_core", None)
    monkeypatch.setitem(sys.modules, "autogen_core.tools", None)
    with pytest.raises(ImportError, match="autogen-core not installed"):
        maverick_autogen_tool()


# ---- Maverick -> CrewAI ----

def test_crewai_tool_delegates(monkeypatch):
    _fake_delegation(monkeypatch)

    class _BaseTool:
        pass

    crewai_tools = types.ModuleType("crewai.tools")
    crewai_tools.BaseTool = _BaseTool
    monkeypatch.setitem(sys.modules, "crewai", types.ModuleType("crewai"))
    monkeypatch.setitem(sys.modules, "crewai.tools", crewai_tools)
    tool = maverick_crewai_tool(max_dollars=3.0)
    assert tool.name == "run_maverick"
    assert tool._run("do the thing") == "swarm did it"


def test_crewai_missing_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "crewai", None)
    monkeypatch.setitem(sys.modules, "crewai.tools", None)
    with pytest.raises(ImportError, match="crewai not installed"):
        maverick_crewai_tool()


# ---- AutoGen tool -> Maverick ----

def test_wrap_autogen_run_style():
    class _Args:
        def __init__(self, **kw):
            self.kw = kw

    class _AutogenTool:
        name = "search"
        description = "search things"

        @staticmethod
        def args_type():
            return _Args

        async def run(self, payload, token=None):
            return f"found {payload.kw['query']}"

    t = wrap_autogen_tool(_AutogenTool())
    assert t.name == "search"
    assert t.fn({"query": "docs"}) == "found docs"


def test_wrap_autogen_func_style_and_schema():
    class _Model:
        @staticmethod
        def model_json_schema():
            return {"type": "object", "properties": {"q": {"type": "string"}},
                    "required": ["q"]}

    tool = types.SimpleNamespace(
        name="adder", description="adds", args_schema=_Model,
        func=lambda q: {"answer": q + "!"},
    )
    t = wrap_autogen_tool(tool)
    assert t.input_schema["required"] == ["q"]
    assert t.fn({"q": "two"}) == '{"answer": "two!"}'


def test_wrap_autogen_no_callable():
    t = wrap_autogen_tool(types.SimpleNamespace(name="x", description="d"))
    assert t.fn({}).startswith("ERROR")


# ---- CrewAI tool -> Maverick ----

def test_wrap_crewai_tool():
    tool = MagicMock()
    tool.name = "scraper"
    tool.description = "scrapes"
    tool.args_schema = None
    tool._run = lambda url: f"scraped {url}"
    t = wrap_crewai_tool(tool)
    assert t.name == "scraper"
    assert t.fn({"url": "https://x"}) == "scraped https://x"
    # Default schema when none is exposed.
    assert t.input_schema["properties"].get("input")
