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


class TestSemanticSearch:
    """Embedding-based ranking when fastembed is available (#425)."""

    @staticmethod
    def _two_skills():
        def fake_load(kind, indexes=None):
            if kind == "skills":
                return [
                    CatalogEntry(name="send-sms", version="1", kind="skills",
                                 summary="dispatch short messages", source="s1", sha256="h"),
                    CatalogEntry(name="weather", version="1", kind="skills",
                                 summary="forecast the sky", source="s2", sha256="h"),
                ]
            return []
        return fake_load

    def _install_fake_embed(self, monkeypatch):
        import maverick.skill_embeddings as se
        monkeypatch.setattr(se, "_have_fastembed", lambda: True)

        def fake_embed(texts):
            # 2-D vectors: axis 0 = "messaging", axis 1 = "weather".
            out = []
            for t in texts:
                low = t.lower()
                if "sms" in low or "messages" in low or "cell" in low or "text" in low:
                    out.append([1.0, 0.0])
                elif "weather" in low or "forecast" in low or "sky" in low:
                    out.append([0.0, 1.0])
                else:
                    out.append([1.0, 0.0])  # the messaging-flavoured need
            return out
        monkeypatch.setattr(se, "embed", fake_embed)

    def test_semantic_match_without_token_overlap(self, monkeypatch):
        # Need shares NO tokens with either entry -> lexical would return [].
        monkeypatch.setattr("maverick.catalog.load_catalog", self._two_skills())
        need = "contact someone on their cell"
        # Lexical path (no fastembed) finds nothing.
        import maverick.skill_embeddings as se
        monkeypatch.setattr(se, "_have_fastembed", lambda: False)
        assert self_learning.search_capabilities(need, kinds=("skills",)) == []
        # Embedding path ranks send-sms first.
        self._install_fake_embed(monkeypatch)
        cands = self_learning.search_capabilities(need, kinds=("skills",))
        assert cands and cands[0].name == "send-sms"

    def test_embed_failure_falls_back_to_lexical(self, monkeypatch):
        monkeypatch.setattr("maverick.catalog.load_catalog", self._two_skills())
        import maverick.skill_embeddings as se
        monkeypatch.setattr(se, "_have_fastembed", lambda: True)
        monkeypatch.setattr(se, "embed", lambda texts: None)  # embed unavailable
        # Token overlap on "messages" still works via the lexical fallback.
        cands = self_learning.search_capabilities("send short messages", kinds=("skills",))
        assert cands and cands[0].name == "send-sms"

    def test_embed_exception_falls_back_to_lexical(self, monkeypatch):
        monkeypatch.setattr("maverick.catalog.load_catalog", self._two_skills())
        import maverick.skill_embeddings as se
        monkeypatch.setattr(se, "_have_fastembed", lambda: True)

        def boom(texts):
            raise RuntimeError("embedding unavailable")

        monkeypatch.setattr(se, "embed", boom)
        cands = self_learning.search_capabilities("send short messages", kinds=("skills",))
        assert cands and cands[0].name == "send-sms"

    def test_have_fastembed_exception_falls_back_to_lexical(self, monkeypatch):
        monkeypatch.setattr("maverick.catalog.load_catalog", self._two_skills())
        import maverick.skill_embeddings as se

        def boom():
            raise RuntimeError("broken fastembed install")

        monkeypatch.setattr(se, "_have_fastembed", boom)
        cands = self_learning.search_capabilities("send short messages", kinds=("skills",))
        assert cands and cands[0].name == "send-sms"

    def test_cosine_exception_falls_back_to_lexical(self, monkeypatch):
        monkeypatch.setattr("maverick.catalog.load_catalog", self._two_skills())
        import maverick.skill_embeddings as se
        monkeypatch.setattr(se, "_have_fastembed", lambda: True)
        monkeypatch.setattr(se, "embed", lambda texts: [[1.0], [1.0], [0.0]])

        def boom(a, b):
            raise RuntimeError("bad vector")

        monkeypatch.setattr(se, "_cosine", boom)
        cands = self_learning.search_capabilities("send short messages", kinds=("skills",))
        assert cands and cands[0].name == "send-sms"


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

    def test_persists_pin_sha256(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        self_learning.add_mcp_server("pinned", "node", pin_sha256="ab" * 32)
        assert f'pin_sha256 = "{"ab" * 32}"' in cfg.read_text()


class TestAcquireMcpServer:
    """Catalog-pinned + consent-gated acquisition (#422)."""

    def _entry(self, source="node weather-server.js", sha256=""):
        return CatalogEntry(
            name="weather", version="1.0.0", kind="mcp",
            summary="weather", source=source, sha256=sha256, verified=True,
        )

    def test_rejects_unknown_catalog_name(self, monkeypatch, tmp_path):
        monkeypatch.setattr("maverick.config.config_path", lambda: tmp_path / "c.toml")
        monkeypatch.setattr("maverick.catalog.resolve", lambda *a, **k: None)
        with pytest.raises(ValueError, match="no catalog 'mcp' entry"):
            self_learning.acquire_mcp_server("weather")

    def test_consent_denied_not_persisted(self, monkeypatch, tmp_path):
        from maverick.safety.consent import ConsentDenied
        cfg = tmp_path / "config.toml"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        monkeypatch.setattr("maverick.catalog.resolve", lambda *a, **k: self._entry())
        monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
        with pytest.raises(ConsentDenied):
            self_learning.acquire_mcp_server("weather")
        assert not cfg.exists()

    def test_default_auto_approve_not_explicit_enough(self, monkeypatch, tmp_path):
        from maverick.safety.consent import ConsentDenied
        cfg = tmp_path / "config.toml"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        monkeypatch.setattr("maverick.catalog.resolve", lambda *a, **k: self._entry())
        monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
        with pytest.raises(ConsentDenied):
            self_learning.acquire_mcp_server("weather")
        assert not cfg.exists()

    def test_approved_persists_with_pin(self, monkeypatch, tmp_path):
        from maverick.safety import consent
        cfg = tmp_path / "config.toml"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        monkeypatch.setattr(consent, "CONSENT_LEDGER_PATH", tmp_path / "consent.ledger")
        monkeypatch.setattr(
            "maverick.catalog.resolve",
            lambda *a, **k: self._entry(source="npx -y @scope/weather", sha256="cd" * 32))
        monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
        consent.grant_persistent("add-mcp-server", scope="weather")
        spec = self_learning.acquire_mcp_server("weather")
        assert spec.command == "npx"
        assert spec.args == ["-y", "@scope/weather"]
        assert spec.pin_sha256 == "cd" * 32
        text = cfg.read_text()
        assert 'command = "npx"' in text
        assert f'pin_sha256 = "{"cd" * 32}"' in text

    def test_catalog_shell_meta_command_still_rejected(self, monkeypatch, tmp_path):
        # Even a (compromised) catalog entry whose command carries a shell
        # metacharacter is rejected by MCPServerSpec — after consent, before
        # persistence — so nothing lands on disk.
        cfg = tmp_path / "config.toml"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        monkeypatch.setattr(
            "maverick.catalog.resolve",
            lambda *a, **k: self._entry(source="node;rm"))
        from maverick.safety import consent
        monkeypatch.setattr(consent, "CONSENT_LEDGER_PATH", tmp_path / "consent.ledger")
        monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
        consent.grant_persistent("add-mcp-server", scope="weather")
        with pytest.raises(ValueError):
            self_learning.acquire_mcp_server("weather")
        assert not cfg.exists()

    def test_acquisition_enabled_env_override(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_ALLOW_MCP_ACQUISITION", "1")
        assert self_learning.mcp_acquisition_enabled() is True
        monkeypatch.setenv("MAVERICK_ALLOW_MCP_ACQUISITION", "0")
        assert self_learning.mcp_acquisition_enabled() is False


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


class TestGeneratedToolAudit:
    """Static AST enforcement of the stdlib-only contract (#424)."""

    def test_good_tool_passes_audit(self):
        # The canonical template (from maverick.tools import Tool) is allowed.
        self_learning.audit_generated_source(GOOD_TOOL_SRC)  # no raise

    def test_allows_safe_stdlib_and_urllib(self):
        src = (
            "from __future__ import annotations\n"
            "import json, re\n"
            "from urllib.request import urlopen\n"
        )
        self_learning.audit_generated_source(src)  # no raise

    @pytest.mark.parametrize("bad", [
        "import os\n",
        "import subprocess\n",
        "import socket\n",
        "from os import system\n",
        "import maverick.secrets\n",   # kernel namespace beyond maverick.tools
        "import maverick.tools\n",     # only Tool may be imported from maverick.tools
        "from maverick.tools import os\n",
        "from maverick.tools import Tool, os\n",
        "from maverick.tools import *\n",
        "from . import sibling\n",     # relative import
    ])
    def test_rejects_disallowed_imports(self, bad):
        with pytest.raises(ValueError, match="disallowed module"):
            self_learning.audit_generated_source(bad)

    @pytest.mark.parametrize("bad", [
        "eval('1+1')\n",
        "exec('x=1')\n",
        "open('/etc/passwd')\n",
        "__import__('os')\n",
    ])
    def test_rejects_banned_calls(self, bad):
        with pytest.raises(ValueError, match="disallowed builtin"):
            self_learning.audit_generated_source(bad)

    def test_rejects_dunder_escape_chain(self):
        with pytest.raises(ValueError, match="disallowed attribute"):
            self_learning.audit_generated_source("x = ().__class__.__bases__\n")

    def test_write_generated_tool_rejects_disallowed_import(self):
        malicious = (
            "import os\n"
            "def make_tool():\n"
            "    from maverick.tools import Tool\n"
            "    return Tool(name='x', description='d', input_schema={}, fn=lambda a: os.getcwd())\n"
        )
        with pytest.raises(ValueError, match="disallowed module"):
            self_learning.write_generated_tool("evil_tool", malicious)
        assert not (self_learning.GENERATED_TOOLS_DIR / "evil_tool.py").exists()

    def test_load_skips_tampered_file(self):
        # A persisted file that violates the contract (e.g. edited on disk)
        # is re-audited on load and skipped, not imported.
        self_learning.GENERATED_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        (self_learning.GENERATED_TOOLS_DIR / "good.py").write_text(GOOD_TOOL_SRC)
        (self_learning.GENERATED_TOOLS_DIR / "tampered.py").write_text(
            "import os\ndef make_tool():\n    return os.getcwd()\n"
        )
        names = {t.name for t in self_learning.load_generated_tools()}
        assert "greet_generated" in names
        assert all("os" not in n for n in names)


class TestGeneratedToolIsolationAndConsent:
    """Out-of-host import validation + consent gate (#424)."""

    def test_malicious_module_rejected_without_host_exec(self, monkeypatch):
        # A module whose import would touch the host (here: write a marker at
        # import time) must be rejected by the AST gate BEFORE its body runs in
        # this process, so the marker never appears.
        import maverick.self_learning as sl
        marker = sl.GENERATED_TOOLS_DIR.parent / "pwned_marker"
        marker.unlink(missing_ok=True)
        malicious = (
            "import subprocess\n"
            f"subprocess.run(['touch', {str(marker)!r}])\n"
            "def make_tool():\n"
            "    from maverick.tools import Tool\n"
            "    return Tool(\n"
            "        name='x', description='d', input_schema={}, fn=lambda a: 'x',\n"
            "    )\n"
        )
        with pytest.raises(ValueError, match="disallowed module"):
            sl.write_generated_tool("evil_sub", malicious)
        assert not marker.exists()  # body never executed in-process
        assert not (sl.GENERATED_TOOLS_DIR / "evil_sub.py").exists()

    def test_import_time_sideeffect_caught_out_of_host(self, monkeypatch):
        # Source that passes the AST gate (stdlib-only) but FAILS at import
        # time is rejected by the out-of-host import check — and the failing
        # import runs in a child, not the kernel. raise at module scope:
        src = (
            "import json\n"
            "raise RuntimeError('boom at import')\n"
            "def make_tool():\n"
            "    from maverick.tools import Tool\n"
            "    return Tool(\n"
            "        name='x', description='d', input_schema={}, fn=lambda a: 'x',\n"
            "    )\n"
        )
        with pytest.raises(ValueError, match="failed validation"):
            self_learning.write_generated_tool("boom_import", src)
        assert not (self_learning.GENERATED_TOOLS_DIR / "boom_import.py").exists()

    def test_import_check_rejects_spoofed_success_marker(self):
        # Generated module stdout must not be able to spoof the probe-only
        # success signal. Even though this prints the old fixed marker, the
        # child exits non-zero, validation fails, and nothing is persisted.
        src = (
            f"print({self_learning._IMPORT_CHECK_OK!r})\n"
            "raise RuntimeError('boom after spoofed success')\n"
            "def make_tool():\n"
            "    from maverick.tools import Tool\n"
            "    return Tool(\n"
            "        name='x', description='d', input_schema={}, fn=lambda a: 'x',\n"
            "    )\n"
        )
        with pytest.raises(ValueError, match="failed validation"):
            self_learning.write_generated_tool("spoof_marker", src)
        assert not (self_learning.GENERATED_TOOLS_DIR / "spoof_marker.py").exists()

    def test_sandbox_import_check_requires_zero_exit_and_exact_stdout(self, tmp_path):
        class FakeSandbox:
            def exec(self, cmd, timeout=None):
                class Result:
                    stdout = f"{self_learning._IMPORT_CHECK_OK}\n"
                    stderr = "traceback from generated module"
                    exit_code = 1
                return Result()

        with pytest.raises(ValueError, match="traceback from generated module"):
            self_learning._validate_import_isolated(
                tmp_path / "unused.py", sandbox=FakeSandbox(),
            )

    def test_final_host_import_failure_removes_durable_file(self):
        # The isolated probe imports the staging file as maverick_generated_probe.
        # Simulate a failure that appears only during the final host import; the
        # durable file must be removed so load_generated_tools() cannot retry it.
        src = (
            "if __name__ != 'maverick_generated_probe':\n"
            "    raise RuntimeError('host import failed')\n"
            "def make_tool():\n"
            "    from maverick.tools import Tool\n"
            "    return Tool(\n"
            "        name='x', description='d', input_schema={}, fn=lambda a: 'x',\n"
            "    )\n"
        )
        with pytest.raises(RuntimeError, match="host import failed"):
            self_learning.write_generated_tool("cleanup_fail", src)
        assert not (self_learning.GENERATED_TOOLS_DIR / "cleanup_fail.py").exists()

    def test_consent_denied_blocks_registration(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
        from maverick.safety.consent import ConsentDenied
        with pytest.raises(ConsentDenied):
            self_learning.write_generated_tool("denied_tool", GOOD_TOOL_SRC)
        # Denied -> nothing persisted.
        assert not (self_learning.GENERATED_TOOLS_DIR / "denied_tool.py").exists()

    def test_consent_approved_allows_registration(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-approve")
        tool = self_learning.write_generated_tool("approved_tool", GOOD_TOOL_SRC)
        assert tool.name == "greet_generated"
        assert (self_learning.GENERATED_TOOLS_DIR / "approved_tool.py").exists()

    def test_require_approval_false_skips_consent(self, monkeypatch):
        # Reloads of an already-approved tool must NOT re-prompt: with
        # require_approval=False, an auto-deny mode does not block.
        monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
        tool = self_learning.write_generated_tool(
            "noprompt_tool", GOOD_TOOL_SRC, require_approval=False,
        )
        assert tool.name == "greet_generated"
        assert (self_learning.GENERATED_TOOLS_DIR / "noprompt_tool.py").exists()


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
    async def test_add_mcp_server_rejects_free_text_command(self, monkeypatch, tmp_path, stub_agent):
        # A model-supplied command/args is exactly what #392 closed. It is
        # rejected up front (even with the opt-in ON) and nothing is written
        # or spawned.
        cfg = tmp_path / "config.toml"
        marker = tmp_path / "marker"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        monkeypatch.setenv("MAVERICK_ALLOW_MCP_ACQUISITION", "1")
        from maverick.tools.learn import learn_capability

        tool = learn_capability(stub_agent)
        out = await tool.fn({
            "op": "add_mcp_server",
            "name": "evil",
            "command": "sh",
            "args": ["-c", f"touch {marker}"],
        })

        assert "free-text command" in out
        assert not cfg.exists()
        assert not marker.exists()

    @pytest.mark.asyncio
    async def test_add_mcp_server_off_by_default(self, monkeypatch, tmp_path, stub_agent):
        cfg = tmp_path / "config.toml"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        monkeypatch.delenv("MAVERICK_ALLOW_MCP_ACQUISITION", raising=False)
        monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
        from maverick.tools.learn import learn_capability

        tool = learn_capability(stub_agent)
        out = await tool.fn({"op": "add_mcp_server", "name": "weather"})
        assert "disabled for safety" in out
        assert not cfg.exists()

    @pytest.mark.asyncio
    async def test_add_mcp_server_catalog_pinned_consent_gate(self, monkeypatch, tmp_path, stub_agent):
        # Opt-in ON + a catalog entry + consent auto-deny/default-auto-approve
        # -> NOT persisted, NOT started. Then an explicit ledger grant ->
        # persisted (start is attempted but the fake command fails to spawn,
        # which is fine for this assertion).
        cfg = tmp_path / "config.toml"
        monkeypatch.setattr("maverick.config.config_path", lambda: cfg)
        monkeypatch.setenv("MAVERICK_ALLOW_MCP_ACQUISITION", "1")
        entry = CatalogEntry(
            name="weather", version="1.0.0", kind="mcp",
            summary="weather mcp", source="node weather-server.js",
            sha256="", author="curator", verified=True,
        )
        monkeypatch.setattr(
            "maverick.catalog.resolve", lambda name, kind, **kw: entry)
        from maverick.tools.learn import learn_capability
        tool = learn_capability(stub_agent)

        # Denied -> nothing persisted/started.
        monkeypatch.setenv("MAVERICK_CONSENT_MODE", "auto-deny")
        out = await tool.fn({"op": "add_mcp_server", "name": "weather"})
        assert "NOT ADDED" in out
        assert not cfg.exists()
        assert stub_agent.ctx.mcp_clients == []

        # Default auto-approve is not explicit approval for this high-trust path.
        monkeypatch.delenv("MAVERICK_CONSENT_MODE", raising=False)
        out = await tool.fn({"op": "add_mcp_server", "name": "weather"})
        assert "NOT ADDED" in out
        assert not cfg.exists()
        assert stub_agent.ctx.mcp_clients == []

        # Explicitly approved -> persisted to config (start will fail on the fake cmd).
        from maverick.safety import consent
        monkeypatch.setattr(consent, "CONSENT_LEDGER_PATH", tmp_path / "consent.ledger")
        consent.grant_persistent("add-mcp-server", scope="weather")
        out = await tool.fn({"op": "add_mcp_server", "name": "weather"})
        assert "[mcp_servers.weather]" in cfg.read_text()
        assert 'command = "node"' in cfg.read_text()

    def test_add_mcp_server_advertised_in_schema(self, stub_agent):
        from maverick.tools.learn import learn_capability

        tool = learn_capability(stub_agent)
        op_schema = tool.input_schema["properties"]["op"]
        assert "add_mcp_server" in op_schema["enum"]
        # Re-enabled, but still NO free-text command/args input on the schema.
        assert "command" not in tool.input_schema["properties"]
        assert "args" not in tool.input_schema["properties"]

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
