"""Torch-free CPU training for the judgment rung (Phase 1), end to end.

Karpathy's note on the self-improvement architecture: it's "an empty gym" until
a real reward model trains on real trajectories. This is the cheapest possible
proof that the gym works -- a tiny linear head over the 12-dim PRM step features
that trains on captured trajectories with plain gradient descent (no torch, no
GPU, no numpy), is evaluated by how well it *separates* promising from
unpromising steps, and is adopted only through the governed ``propose_verifier``
gate. It is the verifier rung made real on a laptop; the torch MLP in
``training/prm_train.py`` is the scale-up, not the prerequisite.

Deterministic (seeded) and offline -- a unit test trains it on synthetic
trajectories and checks it both learns and gets gated correctly.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

FEATURE_DIM = 12   # must match prm.step_features
OUT_DIM = 2        # (promise, progress)


@dataclass
class LinearHead:
    """A 12 -> 2 linear map: predicts (promise, progress) from step features."""

    w: list[list[float]] = field(
        default_factory=lambda: [[0.0] * FEATURE_DIM for _ in range(OUT_DIM)])
    b: list[float] = field(default_factory=lambda: [0.0] * OUT_DIM)

    def predict(self, features: list[float]) -> list[float]:
        out = []
        for o in range(OUT_DIM):
            row = self.w[o]
            out.append(self.b[o] + sum(row[i] * features[i] for i in range(FEATURE_DIM)))
        return out

    def promise(self, features: list[float]) -> float:
        return self.predict(features)[0]

    def to_dict(self) -> dict:
        return {"w": self.w, "b": self.b, "feature_dim": FEATURE_DIM, "out_dim": OUT_DIM}

    @classmethod
    def from_dict(cls, d: dict) -> LinearHead:
        return cls(w=[list(map(float, row)) for row in d["w"]], b=list(map(float, d["b"])))

    def save(self, path: str | Path) -> None:
        # Atomic temp+replace: a bare write_text truncates in place, so a serving
        # process re-loading the head while a training run writes it would see a
        # half-written file and json.load would raise. Each save writes a
        # complete head, so atomic replace is sufficient (no lock needed).
        from .file_lock import atomic_write_text
        atomic_write_text(path, json.dumps(self.to_dict(), sort_keys=True))

    @classmethod
    def load(cls, path: str | Path) -> LinearHead:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _target(ex: dict) -> list[float]:
    return [float(ex.get("promise", 0.0)), float(ex.get("progress", 0.0))]


def train(examples: list[dict], *, epochs: int = 300, lr: float = 0.05,
          seed: int = 0) -> LinearHead:
    """Plain SGD on MSE. Pure Python; deterministic for a given seed."""
    head = LinearHead()
    if not examples:
        return head
    rng = random.Random(seed)
    idx = list(range(len(examples)))
    for _ in range(epochs):
        rng.shuffle(idx)
        for j in idx:
            ex = examples[j]
            x = ex["features"]
            pred = head.predict(x)
            tgt = _target(ex)
            for o in range(OUT_DIM):
                err = pred[o] - tgt[o]
                for i in range(FEATURE_DIM):
                    head.w[o][i] -= lr * err * x[i]
                head.b[o] -= lr * err
    return head


def mse(head: LinearHead, examples: list[dict]) -> float:
    if not examples:
        return 0.0
    total = 0.0
    for ex in examples:
        pred = head.predict(ex["features"])
        tgt = _target(ex)
        total += sum((pred[o] - tgt[o]) ** 2 for o in range(OUT_DIM)) / OUT_DIM
    return total / len(examples)


def baseline_mse(train_ex: list[dict], test_ex: list[dict]) -> float:
    """MSE of the trivial predictor (mean target from train) on the test set."""
    if not train_ex or not test_ex:
        return 0.0
    n = len(train_ex)
    mean = [sum(_target(e)[o] for e in train_ex) / n for o in range(OUT_DIM)]
    total = 0.0
    for ex in test_ex:
        tgt = _target(ex)
        total += sum((mean[o] - tgt[o]) ** 2 for o in range(OUT_DIM)) / OUT_DIM
    return total / len(test_ex)


def discrimination(head: LinearHead, examples: list[dict]) -> float:
    """Mean predicted promise on genuinely-promising steps minus on unpromising
    ones (split at the median actual promise). 0 for a constant predictor; the
    signal the ``propose_verifier`` gate scores."""
    if len(examples) < 4:
        return 0.0
    promises = sorted(float(e.get("promise", 0.0)) for e in examples)
    median = promises[len(promises) // 2]
    hi = [head.promise(e["features"]) for e in examples if float(e.get("promise", 0.0)) >= median]
    lo = [head.promise(e["features"]) for e in examples if float(e.get("promise", 0.0)) < median]
    if not hi or not lo:
        return 0.0
    return (sum(hi) / len(hi)) - (sum(lo) / len(lo))


def train_and_evaluate(examples: list[dict], *, split: float = 0.3, seed: int = 0) -> dict:
    """Train on a split, report held-out MSE, the trivial baseline, and the
    discrimination the trained head achieves on the test set."""
    rng = random.Random(seed)
    ex = list(examples)
    rng.shuffle(ex)
    cut = max(1, int(len(ex) * (1.0 - split))) if len(ex) > 1 else 1
    train_ex, test_ex = ex[:cut], ex[cut:] or ex[:1]
    head = train(train_ex, seed=seed)
    return {
        "head": head,
        "n": len(ex),
        "train_mse": round(mse(head, train_ex), 6),
        "test_mse": round(mse(head, test_ex), 6),
        "baseline_test_mse": round(baseline_mse(train_ex, test_ex), 6),
        "discrimination": round(discrimination(head, test_ex), 6),
    }


def train_and_propose(store, *, controller=None, rollback: str = "verifier-head-v0",
                      split: float = 0.3, seed: int = 0, min_examples: int = 20):
    """End-to-end: captured trajectories -> trained head -> governed adoption.

    Builds examples from the trajectory store, trains a head on CPU, and offers
    it via ``propose_verifier`` -- promoted only if it discriminates better than
    the trivial (constant) baseline, which has discrimination 0. Returns the
    controller verdict, or None when there isn't enough data yet.
    """
    from .self_improvement_runner import build_prm_examples
    from .si_producers import propose_verifier

    examples = build_prm_examples(store)
    if len(examples) < min_examples:
        return None
    result = train_and_evaluate(examples, split=split, seed=seed)
    return propose_verifier(
        f"linear head trained on {result['n']} steps "
        f"(test_mse {result['test_mse']} vs baseline {result['baseline_test_mse']})",
        baseline_discrimination=0.0,
        candidate_discrimination=result["discrimination"],
        samples=result["n"],
        rollback=rollback,
        controller=controller,
    )


__all__ = [
    "LinearHead", "train", "mse", "baseline_mse", "discrimination",
    "train_and_evaluate", "train_and_propose",
]
