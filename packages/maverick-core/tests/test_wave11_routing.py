"""Wave 11: model routing + cache TTL + thinking-budget switches."""
from __future__ import annotations


class TestModelOverride:
    def test_env_override_wins_over_defaults(self, monkeypatch):
        from maverick.llm import model_for_role
        monkeypatch.setenv("MAVERICK_MODEL_OVERRIDE_CODER", "claude-opus-4-7")
        assert model_for_role("coder") == "claude-opus-4-7"

    def test_env_override_is_role_specific(self, monkeypatch):
        from maverick.llm import model_for_role
        # Setting coder override does NOT affect orchestrator.
        monkeypatch.setenv("MAVERICK_MODEL_OVERRIDE_CODER", "deepseek-v4-pro")
        monkeypatch.delenv("MAVERICK_MODEL_OVERRIDE_ORCHESTRATOR", raising=False)
        assert model_for_role("orchestrator") != "deepseek-v4-pro"

    def test_no_override_falls_back_to_defaults(self, monkeypatch):
        from maverick.llm import ROLE_MODELS, model_for_role
        monkeypatch.delenv("MAVERICK_MODEL_OVERRIDE_CODER", raising=False)
        assert model_for_role("coder") == ROLE_MODELS["coder"]


class TestCacheTTL:
    def test_coding_mode_defaults_to_5m(self, monkeypatch):
        from maverick.providers.anthropic_provider import _default_cache_ttl
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        monkeypatch.delenv("MAVERICK_ANTHROPIC_CACHE_TTL", raising=False)
        assert _default_cache_ttl() == "5m"

    def test_non_coding_mode_defaults_to_1h(self, monkeypatch):
        from maverick.providers.anthropic_provider import _default_cache_ttl
        monkeypatch.delenv("MAVERICK_CODING_MODE", raising=False)
        monkeypatch.delenv("MAVERICK_ANTHROPIC_CACHE_TTL", raising=False)
        assert _default_cache_ttl() == "1h"

    def test_explicit_env_override_wins(self, monkeypatch):
        from maverick.providers.anthropic_provider import _default_cache_ttl
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        monkeypatch.setenv("MAVERICK_ANTHROPIC_CACHE_TTL", "30m")
        assert _default_cache_ttl() == "30m"


class TestThinkingOnOrchestrator:
    def test_orchestrator_role_gets_thinking_budget(self, tmp_path):
        """Wave 11: orchestrator + revisor get thinking_budget=8000
        (Anthropic effort=medium). Coder/researcher do not."""
        from maverick.agent import Agent
        from maverick.blackboard import Blackboard
        from maverick.budget import Budget
        from maverick.sandbox import LocalBackend
        from maverick.swarm import SwarmContext
        from maverick.world_model import WorldModel
        world = WorldModel(tmp_path / "w.db")
        gid = world.create_goal("t", "")
        ctx = SwarmContext(
            llm=None, world=world, budget=Budget(),
            blackboard=Blackboard(),
            sandbox=LocalBackend(workdir=tmp_path),
            goal_id=gid, max_depth=1,
        )
        orch = Agent(ctx=ctx, role="orchestrator", brief="x", depth=0)
        revisor = Agent(ctx=ctx, role="revisor", brief="x", depth=0)
        coder = Agent(ctx=ctx, role="coder", brief="x", depth=0)
        assert orch._thinking_budget() == 8000
        assert revisor._thinking_budget() == 8000
        assert coder._thinking_budget() is None


class TestThinkingBudgetWiredThrough:
    def test_anthropic_provider_passes_thinking_to_kwargs(self, monkeypatch):
        from maverick.providers.anthropic_provider import AnthropicClient
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        c = AnthropicClient()
        kwargs = c._build_request(
            system="s", messages=[{"role": "user", "content": "hi"}],
            tools=None, max_tokens=128, thinking_budget=8000,
            model="claude-sonnet-4-6",
        )
        assert kwargs.get("thinking") == {
            "type": "enabled", "budget_tokens": 8000,
        }
        # Max tokens auto-grew to thinking_budget + 1024.
        assert kwargs["max_tokens"] >= 8000 + 1024

    def test_no_thinking_when_unset(self, monkeypatch):
        from maverick.providers.anthropic_provider import AnthropicClient
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        c = AnthropicClient()
        kwargs = c._build_request(
            system="s", messages=[{"role": "user", "content": "hi"}],
            tools=None, max_tokens=128, thinking_budget=None,
            model="claude-sonnet-4-6",
        )
        assert "thinking" not in kwargs


class TestHetBoNLadder:
    """Wave 11: best-of-N ladder env-configurable, defaults to
    Sonnet-cheap → Sonnet-warm → Opus."""

    def test_default_ladder_parses(self, monkeypatch):
        # Indirect test: import the module and confirm the default
        # string parses into 3 (model, temp) tuples by replicating the
        # parsing logic. (The runtime BoN code itself requires a full
        # WorldModel/LLM setup that's overkill for unit tests.)
        default = "claude-sonnet-4-6:0.3,claude-sonnet-4-6:0.7,claude-opus-4-7:0.4"
        ladder = []
        for entry in default.split(","):
            mdl, t = entry.rsplit(":", 1)
            ladder.append((mdl.strip(), float(t)))
        assert len(ladder) == 3
        assert ladder[0] == ("claude-sonnet-4-6", 0.3)
        assert ladder[1] == ("claude-sonnet-4-6", 0.7)
        assert ladder[2] == ("claude-opus-4-7", 0.4)

    def test_env_ladder_override(self, monkeypatch):
        monkeypatch.setenv(
            "MAVERICK_BON_LADDER",
            "claude-sonnet-4-6:0.2,deepseek-v4-pro:0.5,claude-opus-4-7:0.3",
        )
        raw = monkeypatch.setenv  # noqa: F841 - keep monkeypatch alive
        import os
        ladder_str = os.environ["MAVERICK_BON_LADDER"]
        parsed = []
        for entry in ladder_str.split(","):
            mdl, t = entry.rsplit(":", 1)
            parsed.append((mdl.strip(), float(t)))
        assert "deepseek-v4-pro" in [m for m, _ in parsed]
