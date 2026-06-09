"""Counterfactual swarm credit assignment (CSCA): the novel primitive."""
from __future__ import annotations

import pytest
from maverick import credit


class TestCounterfactualCredit:
    @pytest.mark.asyncio
    async def test_loo_marginal_credit(self):
        # Truth: only "alice"'s finding matters; the score = 1.0 iff it's present.
        async def score(subset):
            return 1.0 if any("KEY" in s for s in subset) else 0.0

        contribs = {"alice": "the KEY fact", "bob": "filler", "carol": "noise"}
        cmap = await credit.counterfactual_credit(contribs, score)
        # Removing alice drops the score 1->0 (credit 1); removing bob/carol
        # leaves KEY present (credit 0).
        assert cmap["alice"] == 1.0
        assert cmap["bob"] == 0.0 and cmap["carol"] == 0.0

    @pytest.mark.asyncio
    async def test_harmful_agent_gets_negative_credit(self):
        # "spoiler" present => score drops; removing it raises the score.
        async def score(subset):
            base = 0.8
            if any("SPOIL" in s for s in subset):
                base -= 0.5
            return base

        contribs = {"good": "solid work", "spoiler": "SPOIL the answer"}
        cmap = await credit.counterfactual_credit(contribs, score)
        assert cmap["spoiler"] < 0  # removing it would have helped

    @pytest.mark.asyncio
    async def test_single_contributor_trivial(self):
        async def score(subset):
            return 0.7

        cmap = await credit.counterfactual_credit({"solo": "x"}, score)
        assert cmap == {"solo": 0.7}

    @pytest.mark.asyncio
    async def test_empty(self):
        async def score(subset):
            return 0.0

        assert await credit.counterfactual_credit({}, score) == {}

    @pytest.mark.asyncio
    async def test_pass_count(self):
        calls = {"n": 0}

        async def score(subset):
            calls["n"] += 1
            return 0.5

        await credit.counterfactual_credit({"a": "1", "b": "2", "c": "3"}, score)
        assert calls["n"] == credit.passes_required(3) == 4  # full + 3 ablations


class TestNormalize:
    def test_positive_shares_sum_to_one(self):
        out = credit.normalize_credit({"a": 0.6, "b": 0.2, "c": 0.0})
        assert abs(sum(out.values()) - 1.0) < 1e-6
        assert out["a"] > out["b"] and out["c"] == 0.0

    def test_negatives_floored(self):
        out = credit.normalize_credit({"a": 1.0, "b": -0.5})
        assert out["b"] == 0.0 and out["a"] == 1.0

    def test_all_nonpositive_equal_split(self):
        out = credit.normalize_credit({"a": 0.0, "b": -0.1})
        assert abs(out["a"] - 0.5) < 1e-6 and abs(out["b"] - 0.5) < 1e-6


class TestCreditIsSignal:
    """Eval-first: prove the credit ranking tracks true contribution before any
    consumer learns from it. Planted contributions of known value; credit must
    rank them in the same order (the property the donation/routing consumers
    rely on)."""

    @pytest.mark.asyncio
    async def test_credit_rank_correlates_with_true_value(self):
        # Ground truth: each agent's marginal value is the integer in its text;
        # the score is the (normalized) sum of values present.
        true_value = {"a": 5, "b": 3, "c": 1, "d": 0}

        async def score(subset):
            return sum(int(s) for s in subset) / 10.0

        contribs = {k: str(v) for k, v in true_value.items()}
        cmap = await credit.counterfactual_credit(contribs, score)
        ranked = [k for k, _ in sorted(cmap.items(), key=lambda x: -x[1])]
        assert ranked == ["a", "b", "c", "d"]  # exact rank match with truth
        # And a zero-value contributor gets ~zero credit.
        assert abs(cmap["d"]) < 1e-9


class TestDonationCarriesCredit:
    @pytest.mark.asyncio
    async def test_agent_credit_persisted_in_record(self, tmp_path, monkeypatch):
        from maverick import donation
        from maverick.donation import TrajectoryRecord

        monkeypatch.setattr(donation, "_donations_enabled", lambda: True)
        monkeypatch.setattr(donation, "_text_donations_enabled", lambda: False)
        monkeypatch.setattr("maverick.calibration.learning_frozen", lambda: False)
        rec = TrajectoryRecord(
            task_brief_hash="h", outcome="success",
            verifier_confidence=0.95, disagreement_entropy=0.9,
            agent_credit={"researcher-1": 0.6, "coder-2": -0.1},
        )
        path = donation.write_record(rec, outbox=tmp_path / "outbox")
        assert path is not None
        import json
        data = json.loads(path.read_text())
        assert data["agent_credit"]["researcher-1"] == 0.6


class TestEnabled:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("MAVERICK_CREDIT", raising=False)
        monkeypatch.setattr(credit, "_settings", lambda: dict(credit._DEFAULTS))
        assert credit.enabled() is False

    def test_env_enables(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_CREDIT", "1")
        assert credit.enabled() is True
