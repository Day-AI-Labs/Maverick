"""Tests for per-model usage cards: aggregation math, role accumulation,
markdown rendering (disclaimer + per-model sections), the no-invented-facts
cutoff table, and the duck-typed world adapter."""
from __future__ import annotations

from types import SimpleNamespace

from maverick import model_cards as mc
from maverick.llm import MODEL_PRICES, ROLE_MODELS


def _row(model, **kw):
    return {"model": model, **kw}


class TestBuildCards:
    def test_aggregation_math(self):
        rows = [
            _row("claude-opus-4-8", in_tokens=100, out_tokens=10,
                 cost_dollars=0.5, ts=100.0),
            _row("claude-opus-4-8", in_tokens=200, out_tokens=20,
                 cost_dollars=0.25, ts=50.0),
            _row("claude-haiku-4-5", in_tokens=7, out_tokens=3,
                 cost_dollars=0.01, ts=75.0),
        ]
        cards = mc.build_cards(rows)
        assert set(cards) == {"claude-opus-4-8", "claude-haiku-4-5"}
        opus = cards["claude-opus-4-8"]
        assert opus.calls == 2
        assert opus.total_in_tokens == 300
        assert opus.total_out_tokens == 30
        assert opus.total_dollars == 0.75
        assert opus.first_seen == 50.0 and opus.last_seen == 100.0

    def test_role_accumulation(self):
        rows = [
            _row("m", role="coder"), _row("m", role="verifier"),
            _row("m", role="coder"), _row("m"),
        ]
        card = mc.build_cards(rows)["m"]
        assert card.roles == {"coder", "verifier"}
        assert card.calls == 4

    def test_provider_spec_prefix_is_split(self):
        cards = mc.build_cards([_row("anthropic:claude-opus-4-8")])
        assert set(cards) == {"claude-opus-4-8"}
        assert cards["claude-opus-4-8"].provider == "anthropic"

    def test_explicit_provider_field_wins(self):
        cards = mc.build_cards([_row("openrouter:deepseek-chat", provider="openrouter")])
        assert cards["deepseek-chat"].provider == "openrouter"

    def test_rows_without_model_or_with_junk_numbers_are_tolerated(self):
        rows = [{"role": "coder"}, _row(""), _row("m", in_tokens="junk",
                                                  cost_dollars=None, ts="bad")]
        cards = mc.build_cards(rows)
        assert set(cards) == {"m"}
        assert cards["m"].total_in_tokens == 0
        assert cards["m"].total_dollars == 0.0
        assert cards["m"].first_seen is None

    def test_attribute_style_rows_work(self):
        rows = [SimpleNamespace(model="m", provider=None, role="writer",
                                ts=None, in_tokens=5, out_tokens=1,
                                cost_dollars=0.1)]
        card = mc.build_cards(rows)["m"]
        assert card.roles == {"writer"} and card.total_in_tokens == 5


class TestKnowledgeCutoffs:
    def test_table_only_names_ids_known_to_llm_module(self):
        # No invented vendor facts: every key must be an id visible in llm.py.
        known = set(MODEL_PRICES) | set(ROLE_MODELS.values())
        assert set(mc.KNOWN_KNOWLEDGE_CUTOFFS) <= known
        # No id in llm.py currently encodes a date, so the table is empty.
        assert mc.KNOWN_KNOWLEDGE_CUTOFFS == {}

    def test_unknown_models_get_none(self):
        card = mc.build_cards([_row("claude-opus-4-8"), _row("mystery-9000")])
        assert card["claude-opus-4-8"].knowledge_cutoff is None
        assert card["mystery-9000"].knowledge_cutoff is None


class TestRender:
    def test_card_section_contents(self):
        card = mc.build_cards([_row("claude-opus-4-8", provider="anthropic",
                                    role="orchestrator", in_tokens=10,
                                    out_tokens=2, cost_dollars=1.5,
                                    ts=1750000000.0)])["claude-opus-4-8"]
        text = mc.render_card(card)
        assert text.startswith("## claude-opus-4-8")
        assert "- provider: anthropic" in text
        assert "- roles: orchestrator" in text
        assert "- calls: 1" in text
        assert "- input tokens: 10" in text
        assert "- spend: $1.5000" in text
        assert "- knowledge cutoff: not asserted (no vendor claims)" in text

    def test_document_has_disclaimer_and_sorted_sections(self):
        cards = mc.build_cards([_row("zeta-model"), _row("alpha-model")])
        doc = mc.render_cards(cards)
        assert doc.startswith("# Model cards")
        assert "own ledger, not vendor claims" in doc
        assert "## alpha-model" in doc and "## zeta-model" in doc
        assert doc.index("## alpha-model") < doc.index("## zeta-model")

    def test_empty_document_still_carries_disclaimer(self):
        doc = mc.render_cards({})
        assert "own ledger, not vendor claims" in doc
        assert "(no model usage recorded)" in doc


class _FakeWorld:
    """Duck-typed world: episode rows that DO carry model attribution, plus a
    stock-schema row (no model) that must be skipped."""

    def __init__(self):
        self.requested_limit = None
        self.episodes = [
            SimpleNamespace(  # extended row: model + role recorded
                id=1, goal_id=1, started_at=10.0, ended_at=20.0,
                outcome="success", cost_dollars=0.5, input_tokens=100,
                output_tokens=10, tool_calls=3, model="claude-opus-4-8",
                role="orchestrator"),
            SimpleNamespace(  # live episode: no ended_at yet
                id=2, goal_id=1, started_at=30.0, ended_at=None,
                outcome=None, cost_dollars=0.25, input_tokens=50,
                output_tokens=5, tool_calls=1, model="claude-opus-4-8",
                role="coder"),
            SimpleNamespace(  # stock EpisodeSpend shape: no model -> skipped
                id=3, goal_id=2, started_at=40.0, ended_at=41.0,
                outcome="success", cost_dollars=9.0, input_tokens=999,
                output_tokens=99, tool_calls=0),
        ]

    def list_episodes(self, limit=50):
        self.requested_limit = limit
        return self.episodes


class TestGatherFromWorld:
    def test_pulls_attributed_rows_and_skips_stock_rows(self):
        world = _FakeWorld()
        rows = mc.gather_from_world(world, limit=123)
        assert world.requested_limit == 123
        assert len(rows) == 2
        cards = mc.build_cards(rows)
        card = cards["claude-opus-4-8"]
        assert card.calls == 2
        assert card.total_in_tokens == 150
        assert card.total_dollars == 0.75
        assert card.roles == {"coder", "orchestrator"}
        # ended_at preferred, started_at fallback for the live episode
        assert card.first_seen == 20.0 and card.last_seen == 30.0

    def test_world_without_list_episodes_yields_nothing(self):
        assert mc.gather_from_world(object()) == []

    def test_raising_world_fails_open(self):
        class Broken:
            def list_episodes(self, limit=50):
                raise RuntimeError("db locked")
        assert mc.gather_from_world(Broken()) == []

    def test_world_with_limitless_signature(self):
        class Legacy:
            def list_episodes(self):
                return [{"model": "m", "cost_dollars": 1.0}]
        rows = mc.gather_from_world(Legacy(), limit=10)
        assert rows and rows[0]["model"] == "m"
