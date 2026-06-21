"""CPU-trainable Bradley-Terry reward model for the RLAIF flywheel.

Pure + deterministic: learns real weights from verifier-reward preference pairs
on a CPU in milliseconds. These tests assert it actually LEARNS (pairwise
accuracy rises, the right features get the right sign) rather than just runs.
"""
from __future__ import annotations

import json

from maverick.training import reward_model as rm
from maverick.training.reward_model import (
    PreferenceRewardModel,
    featurize,
    train_reward_model,
)


def _row(rid, family, reward, *, n_msgs=2, n_err=0, conf=1.0):
    msgs = []
    for i in range(n_msgs):
        msgs.append({"role": "worker", "type": "tool_call", "name": "grep",
                     "error": "boom" if i < n_err else None})
    return {
        "id": rid, "task_family": family, "terminal_reward": reward,
        "messages": msgs, "meta": {"verifier_confidence": conf},
    }


class TestFeaturize:
    def test_counts(self):
        f = featurize(_row("x", "fam", 1.0, n_msgs=4, n_err=2))
        assert f["n_messages"] == 4.0
        assert f["n_errors"] == 2.0
        assert f["error_rate"] == 0.5
        assert f["n_tool_calls"] == 4.0
        assert f["distinct_tools"] == 1.0

    def test_empty_row(self):
        f = featurize({"messages": []})
        assert f["n_messages"] == 0.0 and f["error_rate"] == 0.0


class TestLearning:
    def _dataset(self):
        # In every family, the higher-reward attempt has FEWER errors. A correct
        # reward model must learn that errors are bad (negative weight).
        rows = []
        for fam in range(8):
            rows.append(_row(f"{fam}-good", f"fam{fam}", 1.0, n_msgs=3, n_err=0))
            rows.append(_row(f"{fam}-bad", f"fam{fam}", 0.0, n_msgs=3, n_err=3))
        return rows

    def test_learns_error_is_bad(self):
        model, report = train_reward_model(self._dataset(), min_margin=0.5,
                                           epochs=300, lr=0.2)
        assert report["pairs"] == 8
        # Perfect separability -> the model orders every pair correctly.
        assert report["accuracy"] == 1.0
        # Error features pull the score DOWN.
        assert model.weights["n_errors"] < 0
        assert model.weights["error_rate"] < 0

    def test_scores_prefer_clean_trajectory(self):
        model, _ = train_reward_model(self._dataset(), epochs=300, lr=0.2)
        good = _row("g", "f", 1.0, n_msgs=3, n_err=0)
        bad = _row("b", "f", 0.0, n_msgs=3, n_err=3)
        assert model.score(good) > model.score(bad)

    def test_deterministic(self):
        a, _ = train_reward_model(self._dataset(), epochs=100, lr=0.2)
        b, _ = train_reward_model(self._dataset(), epochs=100, lr=0.2)
        assert a.weights == b.weights  # zero-init + fixed order => reproducible

    def test_no_pairs_is_safe(self):
        # A single-attempt family yields no pairs; fit must no-op cleanly.
        model, report = train_reward_model([_row("solo", "fam", 1.0)])
        assert report["pairs"] == 0 and report["accuracy"] == 0.0
        assert all(v == 0.0 for v in model.weights.values())


class TestPersistence:
    def test_roundtrip(self, tmp_path):
        model, _ = train_reward_model(
            [_row(f"{f}-g", f"f{f}", 1.0, n_err=0) for f in range(4)]
            + [_row(f"{f}-b", f"f{f}", 0.0, n_err=2) for f in range(4)],
            epochs=50)
        p = tmp_path / "rm.json"
        model.save(p)
        data = json.loads(p.read_text())
        assert data["type"] == "bradley_terry_linear"
        loaded = PreferenceRewardModel.load(p)
        assert loaded.weights == model.weights

    def test_load_validates(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text('{"weights": "notadict"}')
        import pytest
        with pytest.raises(ValueError):
            PreferenceRewardModel.load(p)


class TestCLI:
    def test_main_trains_and_writes(self, tmp_path):
        rows = [_row(f"{f}-g", f"f{f}", 1.0, n_err=0) for f in range(5)]
        rows += [_row(f"{f}-b", f"f{f}", 0.0, n_err=3) for f in range(5)]
        data = tmp_path / "traj.jsonl"
        data.write_text("\n".join(json.dumps(r) for r in rows))
        out = tmp_path / "rm.json"
        assert rm.main(["--data", str(data), "--out", str(out), "--epochs", "200"]) == 0
        loaded = PreferenceRewardModel.load(out)
        assert loaded.weights["n_errors"] < 0
