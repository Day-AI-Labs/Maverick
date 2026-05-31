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
        assert st["add_mcp_servers"] is True
        assert st["max_acquisitions"] == 5


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
            "add_mcp_servers": True, "max_acquisitions": 5,
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
