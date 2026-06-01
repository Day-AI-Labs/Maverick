"""Self-learning: capability acquisition, generated tools, the in-loop tool.

The feature is off by default (kernel rule 1). These tests cover the
gating, the learned-capability ledger, catalog search, MCP-server
persistence, generated-tool validation/loading, and the
``learn_capability`` tool's dispatch — all without network or a real LLM.
"""
from __future__ import annotations

import pytest
from maverick import self_learning
from maverick.blackboard import Blackboard
from maverick.budget import Budget
from maverick.catalog import CatalogEntry
from maverick.llm import LLMResponse
from maverick.tools import Tool, ToolRegistry


def make_response(text: str = "") -> LLMResponse:
    return LLMResponse(text=text, thinking=None, tool_calls=[], stop_reason="end_turn")


class FakeLLM:
    """Scripted stand-in for maverick.llm.LLM (async complete only)."""

    def __init__(self, scripted: list | None = None):
        self.scripted = list(scripted or [])
        self.model = "fake:test"

    async def complete_async(self, **kwargs) -> LLMResponse:
        if self.scripted:
            return self.scripted.pop(0)
        return make_response("FINAL: (exhausted)")


# A minimal, valid generated tool module.
GOOD_TOOL_SRC = '''
def make_tool():
    from maverick.tools import Tool

    def fn(args):
        return "hi " + str(args.get("who", "world"))

    return Tool(
        name="greet_generated",
        description="Greet someone.",
        input_schema={"type": "object", "properties": {"who": {"type": "string"}}},
        fn=fn,
    )
'''


class TestGating:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_SELF_LEARNING", raising=False)
        assert self_learning.enabled() is False

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_SELF_LEARNING", "1")
        assert self_learning.enabled() is True

    def test_env_can_force_off_over_config(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_SELF_LEARNING", "off")
        assert self_learning.enabled() is False

    def test_settings_defaults(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_SELF_LEARNING", raising=False)
        st = self_learning.settings()
        assert st["enable"] is False
        assert st["create_tools"] is True
        assert st["max_acquisitions"] == 5
        # The retired add_mcp_servers knob is no longer surfaced.
        assert "add_mcp_servers" not in st

    def test_legacy_add_mcp_servers_key_tolerated(self, monkeypatch, tmp_path):
        # An old config that still carries add_mcp_servers must not error.
        cfg = tmp_path / "config.toml"
        cfg.write_text("[self_learning]\nenable = true\nadd_mcp_servers = true\n")
        monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
        monkeypatch.delenv("MAVERICK_SELF_LEARNING", raising=False)
        st = self_learning.settings()
        assert st["enable"] is True
        assert "add_mcp_servers" not in st


class TestLedger:
    def test_record_then_history(self, tmp_path):
        path = tmp_path / "learned.ndjson"
        self_learning.record("send sms", "skill", "twilio-sms",
                             source="gh:x/y", path=path)
        self_learning.record("query db", "tool", "pg_query", path=path)
        items = self_learning.history(path=path)
        assert [i.name for i in items] == ["pg_query", "twilio-sms"]  # newest first
        assert items[1].kind == "skill"
        assert items[1].need == "send sms"

    def test_history_empty_when_no_file(self, tmp_path):
        assert self_learning.history(path=tmp_path / "nope.ndjson") == []


class TestCatalogSearch:
    def test_ranks_by_token_overlap(self, monkeypatch):
        def fake_load(kind, indexes=None):
            if kind == "skills":
                return [
                    CatalogEntry(name="send-sms", version="1", kind="skills",
                                 summary="send an sms text message", source="s1", sha256="h"),
                    CatalogEntry(name="weather", version="1", kind="skills",
                                 summary="get the weather", source="s2", sha256="h"),
                ]
            return []
        monkeypatch.setattr("maverick.catalog.load_catalog", fake_load)
        cands = self_learning.search_capabilities("send an sms", kinds=("skills",))
        assert cands
        assert cands[0].name == "send-sms"
        assert cands[0].kind == "skill"

    def test_no_match_returns_empty(self, monkeypatch):
        monkeypatch.setattr("maverick.catalog.load_catalog", lambda k, indexes=None: [])
        assert self_learning.search_capabilities("anything") == []

    def test_unreachable_catalog_degrades(self, monkeypatch):
        def boom(kind, indexes=None):
            raise RuntimeError("network down")
        monkeypatch.setattr("maverick.catalog.load_catalog", boom)
        assert self_learning.search_capabilities("x") == []


class TestAddMcpServer:
    def test_writes_block_and_returns_spec(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        spec = self_learning.add_mcp_server(
            "weathermcp", "node", args=["server.js"],
            env={"API_KEY": "x"}, need="weather",
        )
        assert spec.name == "weathermcp"
        text = cfg.read_text()
        assert "[mcp_servers.weathermcp]" in text
        assert 'command = "node"' in text
        assert 'args = ["server.js"]' in text

    def test_rejects_duplicate(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        self_learning.add_mcp_server("dup", "node")
        with pytest.raises(ValueError, match="already configured"):
            self_learning.add_mcp_server("dup", "node")

    def test_rejects_bad_name(self, monkeypatch, tmp_path):
        monkeypatch.setattr("maverick.config.config_path", lambda: tmp_path / "c.toml")
        with pytest.raises(ValueError, match="lowercase id"):
            self_learning.add_mcp_server("Bad Name!", "node")

    def test_rejects_shell_meta_command(self, monkeypatch, tmp_path):
        # MCPServerSpec input validation must fire before anything is written.
        monkeypatch.setattr("maverick.config.config_path", lambda: tmp_path / "c.toml")
        with pytest.raises(ValueError):
            self_learning.add_mcp_server("evil", "node; rm -rf /")


class TestGeneratedTools:
    def test_write_validate_and_load(self, monkeypatch):
        tool = self_learning.write_generated_tool("greet_gen", GOOD_TOOL_SRC)
        assert isinstance(tool, Tool)
        assert tool.name == "greet_generated"
        # Persisted; a fresh load picks it up.
        loaded = self_learning.load_generated_tools()
        assert any(t.name == "greet_generated" for t in loaded)

    def test_strips_markdown_fences(self):
        fenced = "```python\n" + GOOD_TOOL_SRC + "\n```"
        tool = self_learning.write_generated_tool("greet_fenced", fenced)
        assert tool.name == "greet_generated"

    def test_invalid_module_rejected_and_leaves_nothing(self):
        with pytest.raises(ValueError):
            self_learning.write_generated_tool("broken", "def make_tool(:\n  pass")
        target = self_learning.GENERATED_TOOLS_DIR / "broken.py"
        assert not target.exists()

    def test_module_without_make_tool_rejected(self):
        with pytest.raises(ValueError, match="make_tool"):
            self_learning.write_generated_tool("nofac", "x = 1\n")

    def test_bad_name_rejected(self):
        with pytest.raises(ValueError, match="lowercase id"):
            self_learning.write_generated_tool("Bad-Name", GOOD_TOOL_SRC)

    def test_load_skips_broken_file(self):
        self_learning.GENERATED_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        (self_learning.GENERATED_TOOLS_DIR / "ok.py").write_text(GOOD_TOOL_SRC)
        (self_learning.GENERATED_TOOLS_DIR / "bad.py").write_text("import nonexistent_xyz")
        names = {t.name for t in self_learning.load_generated_tools()}
        assert "greet_generated" in names


# --- the learn_capability tool ---------------------------------------------

class _StubCtx:
    def __init__(self, llm):
        self.llm = llm
        self.budget = Budget()
        self.blackboard = Blackboard()
        self.mcp_clients: list = []


class _StubAgent:
    def __init__(self, llm):
        self.ctx = _StubCtx(llm)
        self.tools = ToolRegistry()
        self.name = "tester-0-abc123"


def _fake_tool(name: str, result: str) -> Tool:
    async def fn(args):
        return result
    return Tool(name=name, description=name, input_schema={"type": "object"}, fn=fn)


@pytest.fixture
def stub_agent():
    return _StubAgent(FakeLLM())


class TestLearnTool:
    @pytest.mark.asyncio
    async def test_unknown_op(self, stub_agent):
        from maverick.tools.learn import learn_capability
        tool = learn_capability(stub_agent)
        out = await tool.fn({"op": "frobnicate"})
        assert out.startswith("ERROR: unknown op")

    @pytest.mark.asyncio
    async def test_search(self, stub_agent, monkeypatch):
        from maverick import self_learning as sl
        monkeypatch.setattr(sl, "search_capabilities", lambda need, **kw: [
            sl.Candidate(kind="skill", name="send-sms", summary="sms", source="s", score=0.9),
        ])
        from maverick.tools.learn import learn_capability
        tool = learn_capability(stub_agent)
        out = await tool.fn({"op": "search", "need": "send a text"})
        assert "send-sms" in out

    @pytest.mark.asyncio
    async def test_acquire_skill_injects_body(self, stub_agent, monkeypatch):
        from maverick import self_learning as sl
        monkeypatch.setattr(sl, "acquire_skill",
                            lambda name, need="": "# Steps\n1. do the thing")
        from maverick.tools.learn import learn_capability
        tool = learn_capability(stub_agent)
        out = await tool.fn({"op": "acquire_skill", "name": "send-sms"})
        assert "do the thing" in out


    @pytest.mark.asyncio
    async def test_add_mcp_server_is_not_agent_callable(self, monkeypatch, tmp_path, stub_agent):
        cfg = tmp_path / "config.toml"
        marker = tmp_path / "marker"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        from maverick.tools.learn import learn_capability

        tool = learn_capability(stub_agent)
        out = await tool.fn({
            "op": "add_mcp_server",
            "name": "evil",
            "command": "sh",
            "args": ["-c", f"touch {marker}"],
        })

        assert "disabled for safety" in out
        assert not cfg.exists()
        assert not marker.exists()

    def test_add_mcp_server_not_advertised_in_schema(self, stub_agent):
        from maverick.tools.learn import learn_capability

        tool = learn_capability(stub_agent)
        op_schema = tool.input_schema["properties"]["op"]
        assert "add_mcp_server" not in op_schema["enum"]
        assert "command" not in tool.input_schema["properties"]

    @pytest.mark.asyncio
    async def test_create_tool_registers_live(self, monkeypatch):
        llm = FakeLLM(scripted=[make_response(text=GOOD_TOOL_SRC)])
        agent = _StubAgent(llm)
        from maverick.tools.learn import learn_capability
        tool = learn_capability(agent)
        out = await tool.fn({
            "op": "create_tool", "name": "greet_live",
            "spec": "greet a person by name",
        })
        assert "greet_generated" in out
        # Registered into the live registry the agent's next turn will see.
        assert "greet_generated" in {t.name for t in agent.tools.all()}

    @pytest.mark.asyncio
    async def test_create_tool_disabled(self, monkeypatch, stub_agent):
        from maverick import self_learning as sl
        monkeypatch.setattr(sl, "settings", lambda: {
            "enable": True, "preflight": True, "create_tools": False,
            "max_acquisitions": 5,
        })
        from maverick.tools.learn import learn_capability
        tool = learn_capability(stub_agent)
        out = await tool.fn({"op": "create_tool", "name": "x", "spec": "y"})
        assert "disabled" in out

    @pytest.mark.asyncio
    async def test_find_api_points_at_openapi_runner(self, stub_agent):
        from maverick.tools.learn import learn_capability
        tool = learn_capability(stub_agent)
        out = await tool.fn({"op": "find_api", "need": "call the stripe api"})
        assert "openapi_runner" in out

    @pytest.mark.asyncio
    async def test_find_api_with_base_url_lists_ops(self, stub_agent, monkeypatch):
        from maverick import self_learning as sl
        spec = "https://api.example.com/openapi.json"
        monkeypatch.setattr(sl, "probe_openapi_spec", lambda base, **kw: spec)
        stub_agent.tools.register(_fake_tool("openapi_runner", "GET /widgets — list widgets"))
        from maverick.tools.learn import learn_capability
        tool = learn_capability(stub_agent)
        out = await tool.fn({"op": "find_api", "need": "widgets api",
                             "base_url": "https://api.example.com"})
        assert spec in out
        assert "GET /widgets" in out          # ops preview surfaced
        assert sl.history()[0].kind == "api"   # recorded to the ledger

    @pytest.mark.asyncio
    async def test_find_api_via_web_search(self, stub_agent, monkeypatch):
        from maverick import self_learning as sl
        spec = "https://api.example.com/openapi.json"
        stub_agent.tools.register(_fake_tool("web_search", f"docs at {spec}"))
        monkeypatch.setattr(sl, "discover_openapi_spec",
                            lambda **kw: spec if "openapi.json" in kw.get("search_text", "") else None)
        from maverick.tools.learn import learn_capability
        tool = learn_capability(stub_agent)
        out = await tool.fn({"op": "find_api", "need": "example api"})
        assert spec in out

    @pytest.mark.asyncio
    async def test_find_api_no_spec_suggests_web_search(self, stub_agent):
        from maverick.tools.learn import learn_capability
        tool = learn_capability(stub_agent)
        out = await tool.fn({"op": "find_api", "need": "obscure api"})
        assert "web_search" in out  # no web_search tool loaded -> hint to enable it


class TestPreflight:
    @pytest.mark.asyncio
    async def test_pre_acquires_matching_skill(self, monkeypatch):
        from maverick import self_learning as sl
        llm = FakeLLM(scripted=[make_response(text='["send an sms message"]')])
        monkeypatch.setattr(sl, "search_capabilities", lambda need, **kw: [
            sl.Candidate(kind="skill", name="send-sms", summary="sms", source="s", score=0.8),
        ])
        acquired_calls = []
        monkeypatch.setattr(sl, "acquire_skill",
                            lambda name, need="": acquired_calls.append(name) or "body")
        bb = Blackboard()
        got = await sl.preflight(llm, "text my mom", Budget(), bb, max_acquisitions=5)
        assert got == ["send-sms"]
        assert acquired_calls == ["send-sms"]

    @pytest.mark.asyncio
    async def test_no_needs_acquires_nothing(self, monkeypatch):
        from maverick import self_learning as sl
        llm = FakeLLM(scripted=[make_response(text="[]")])
        got = await sl.preflight(llm, "say hello", Budget(), Blackboard())
        assert got == []

    @pytest.mark.asyncio
    async def test_llm_failure_degrades_gracefully(self, monkeypatch):
        from maverick import self_learning as sl

        class BoomLLM:
            async def complete_async(self, **kw):
                raise RuntimeError("provider down")

        got = await sl.preflight(BoomLLM(), "anything", Budget(), Blackboard())
        assert got == []


# --- OpenAPI spec discovery (pure functions) --------------------------------

_SPEC_JSON = '{"openapi": "3.0.0", "info": {"title": "X"}, "paths": {"/p": {}}}'


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode()

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(mapping):
    """Build an opener over {url: (status, body)}; unknown urls 404."""
    def opener(url, *, timeout=None):
        status, body = mapping.get(url, (404, ""))
        return _FakeResp(status, body)
    return opener


class TestApiDiscovery:
    def test_is_openapi_text(self):
        from maverick import self_learning as sl
        assert sl._is_openapi_text(_SPEC_JSON) is True
        assert sl._is_openapi_text('{"openapi": "3.0.0"}') is False  # no paths
        assert sl._is_openapi_text('{"hello": "world"}') is False
        assert sl._is_openapi_text("openapi: 3.0.0\npaths: {}\n") is True  # yaml
        assert sl._is_openapi_text("not a spec") is False

    def test_validate_spec_url(self):
        from maverick import self_learning as sl
        op = _opener({"https://api.x.com/openapi.json": (200, _SPEC_JSON)})
        assert sl.validate_spec_url("https://api.x.com/openapi.json", opener=op)
        assert sl.validate_spec_url("https://api.x.com/missing.json", opener=op) is None
        assert sl.validate_spec_url("ftp://x", opener=op) is None  # scheme guard

    def test_probe_finds_well_known_under_origin(self):
        from maverick import self_learning as sl
        op = _opener({"https://api.x.com/openapi.json": (200, _SPEC_JSON)})
        # Given a deep page URL, probing should still find the origin's spec.
        assert sl.probe_openapi_spec("https://api.x.com/docs/guide", opener=op) == \
            "https://api.x.com/openapi.json"

    def test_probe_returns_none_when_absent(self):
        from maverick import self_learning as sl
        assert sl.probe_openapi_spec("https://api.x.com", opener=_opener({})) is None

    def test_discover_from_search_text(self):
        from maverick import self_learning as sl
        spec = "https://api.x.com/v3/api-docs"
        text = f"Try the API. Spec lives at {spec} (json)."
        op = _opener({spec: (200, _SPEC_JSON)})
        assert sl.discover_openapi_spec(search_text=text, opener=op) == spec

    def test_discover_prefers_base_url(self):
        from maverick import self_learning as sl
        op = _opener({"https://api.x.com/swagger.json": (200, _SPEC_JSON)})
        assert sl.discover_openapi_spec(
            base_url="https://api.x.com", opener=op,
        ) == "https://api.x.com/swagger.json"

    def test_discover_none_when_nothing_matches(self):
        from maverick import self_learning as sl
        assert sl.discover_openapi_spec(search_text="no urls here", opener=_opener({})) is None
