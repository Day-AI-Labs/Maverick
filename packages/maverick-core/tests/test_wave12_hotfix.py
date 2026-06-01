"""Wave 12 hotfix tests: corrected Opus pricing, adaptive-thinking
gating per model family, low-cache-prompt observability, and the
harness side of the MAVERICK_GOLD_PATCH plumbing.
"""
from __future__ import annotations

import logging

from maverick.budget import Budget
from maverick.llm import MODEL_OPUS


class TestOpusPricingHotfix:
    """Opus 4.7 is $5/$25 per Mtok — NOT $15/$75 (those were legacy
    Opus 4.0/4.1 rates). Wave 12 commit bfae341 incorrectly raised
    Maverick to $15/$75; this hotfix reverts to the correct value.
    Cross-check: vals.ai measures Opus 4.7 at $2.42/test on SWE-bench
    Verified, which reconciles ONLY with $5/$25 pricing.
    """

    def test_opus_input_priced_at_5_per_mtok(self):
        b = Budget(max_dollars=100.0, max_input_tokens=10_000_000)
        b.record_tokens(1_000_000, 0, model=MODEL_OPUS)
        assert abs(b.dollars - 5.0) < 0.001

    def test_opus_output_priced_at_25_per_mtok(self):
        b = Budget(max_dollars=100.0, max_input_tokens=10_000_000, max_output_tokens=10_000_000)
        b.record_tokens(0, 1_000_000, model=MODEL_OPUS)
        assert abs(b.dollars - 25.0) < 0.001

    def test_opus_cache_read_at_one_tenth_5(self):
        b = Budget(max_dollars=100.0, max_input_tokens=10_000_000)
        b.record_tokens(0, 0, model=MODEL_OPUS, cache_read_tok=1_000_000)
        # $5 input × 0.1 = $0.50
        assert abs(b.dollars - 0.5) < 0.001


class TestOpus47AdaptiveThinking:
    """Opus 4.7+ rejects manual `thinking={"type":"enabled"}` with 400.
    Must use `adaptive`. Verified at platform.claude.com/docs/.../adaptive-thinking."""

    def test_opus_47_with_budget_uses_adaptive(self):
        from maverick.providers.anthropic_provider import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=8000,
            model="claude-opus-4-7",
        )
        assert kwargs.get("thinking", {}).get("type") == "adaptive"
        # No budget_tokens — adaptive auto-sizes.
        assert "budget_tokens" not in kwargs.get("thinking", {})

    def test_opus_47_without_budget_still_adaptive(self):
        from maverick.providers.anthropic_provider import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=None,
            model="claude-opus-4-7",
        )
        assert kwargs.get("thinking", {}).get("type") == "adaptive"

    def test_opus_48_with_budget_uses_adaptive(self):
        from maverick.providers.anthropic_provider import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=8000,
            model="claude-opus-4-8",
        )
        thinking = kwargs.get("thinking", {})
        assert thinking.get("type") == "adaptive"
        assert "budget_tokens" not in thinking
        assert kwargs.get("max_tokens") >= 9024

    def test_opus_48_without_budget_still_adaptive(self):
        from maverick.providers.anthropic_provider import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=None,
            model="claude-opus-4-8",
        )
        assert kwargs.get("thinking", {}).get("type") == "adaptive"
        assert kwargs.get("max_tokens") >= 16384

    def test_opus_48_fast_uses_adaptive(self):
        from maverick.providers.anthropic_provider import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=8000,
            model="claude-opus-4-8-fast",
        )
        assert kwargs.get("thinking", {}).get("type") == "adaptive"

    def test_sonnet_46_uses_enabled_mode(self):
        """Sonnet 4.6 supports both 'enabled' and 'adaptive'; we use
        explicit 'enabled' with budget_tokens for callsites that pass
        thinking_budget."""
        from maverick.providers.anthropic_provider import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        kwargs = client._build_request(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            max_tokens=4096,
            thinking_budget=8000,
            model="claude-sonnet-4-6",
        )
        thinking = kwargs.get("thinking", {})
        assert thinking.get("type") == "enabled"
        assert thinking.get("budget_tokens") == 8000


class TestLowCacheWarning:
    """The 4096-token min cacheable block on Sonnet 4.6 / Opus 4.7 means
    Maverick's current ~1085-tok system + ~716-tok tools won't actually
    cache. Operators need to see this in logs."""

    def test_min_cache_tokens_for_modern_models(self):
        from maverick.providers.anthropic_provider import _min_cache_tokens
        assert _min_cache_tokens("claude-opus-4-8") == 4096
        assert _min_cache_tokens("claude-opus-4-7") == 4096
        assert _min_cache_tokens("claude-opus-4-6") == 4096
        assert _min_cache_tokens("claude-opus-4-5") == 4096
        assert _min_cache_tokens("claude-sonnet-4-6") == 4096
        assert _min_cache_tokens("claude-sonnet-4-5") == 4096
        assert _min_cache_tokens("claude-haiku-4-5") == 4096

    def test_min_cache_tokens_for_legacy_models(self):
        from maverick.providers.anthropic_provider import _min_cache_tokens
        assert _min_cache_tokens("claude-3-5-sonnet-20241022") == 1024
        assert _min_cache_tokens("claude-opus-4-1") == 1024

    def test_warning_emitted_for_small_prompt(self, caplog):
        from maverick.providers import anthropic_provider as ap
        # Reset the once-per-process flag for this test.
        ap._LOW_CACHE_WARNING_EMITTED.clear()
        client = ap.AnthropicClient.__new__(ap.AnthropicClient)
        with caplog.at_level(logging.WARNING, logger=ap.__name__):
            client._build_request(
                system="short system prompt",
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"name": "x", "input_schema": {}}],
                max_tokens=1024,
                thinking_budget=None,
                model="claude-sonnet-4-6",
            )
        assert any("prompt cache no-op" in r.message for r in caplog.records), (
            "expected low-cache warning to be logged"
        )
        ap._LOW_CACHE_WARNING_EMITTED.clear()

    def test_warning_emitted_only_once_per_model(self, caplog):
        from maverick.providers import anthropic_provider as ap
        ap._LOW_CACHE_WARNING_EMITTED.clear()
        client = ap.AnthropicClient.__new__(ap.AnthropicClient)
        with caplog.at_level(logging.WARNING, logger=ap.__name__):
            for _ in range(5):
                client._build_request(
                    system="short",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=None,
                    max_tokens=1024,
                    thinking_budget=None,
                    model="claude-sonnet-4-6",
                )
        cache_warnings = [r for r in caplog.records if "prompt cache" in r.message]
        assert len(cache_warnings) == 1
        ap._LOW_CACHE_WARNING_EMITTED.clear()


class TestHarnessSetsGoldPatch:
    """Wave 12 hotfix: complete the env plumbing the agent side already
    expects. Without this, defensive_validate's cheating detector never
    has a gold to compare against and silently never fires."""

    def test_run_maverick_sets_gold_patch_env(self, monkeypatch, tmp_path):
        """We can't run a real instance here without an API key, but we
        can inspect the env-set behaviour by reading the harness source."""
        monkeypatch.delenv("MAVERICK_GOLD_PATCH", raising=False)
        # Verify the harness module sets the env var when given a
        # `gold_patch` kwarg. We do this by reading the source.
        from pathlib import Path
        src = (Path(__file__).resolve().parents[3] / "benchmarks" / "swe_bench.py").read_text(
            encoding="utf-8",
        )
        assert 'os.environ["MAVERICK_GOLD_PATCH"] = gold_patch' in src, (
            "harness must set MAVERICK_GOLD_PATCH from manifest gold_patch"
        )
        assert "reset_gold_patch_cache" in src, (
            "harness must reset coding_mode's gold-patch cache per instance"
        )
