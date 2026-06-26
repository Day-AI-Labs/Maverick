"""Tests for the torch-free CPU verifier-head training (judgment rung)."""
from __future__ import annotations

import random

from maverick.self_improvement import PromotionLedger, SelfImprovementController
from maverick.verifier_head import LinearHead


def _ctrl(tmp_path):
    return SelfImprovementController(
        frozen_fn=lambda: False, audit_fn=lambda **k: None,
        ledger=PromotionLedger(path=tmp_path / "led.json"))


def _linear_examples(n=80, seed=0):
    """Promise is a clean linear function of the features -> learnable."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        x = [rng.uniform(-1, 1) for _ in range(12)]
        promise = 0.5 * x[0] - 0.3 * x[3]
        out.append({"features": x, "promise": promise, "progress": 0.0})
    return out


def test_head_learns_a_linear_signal():
    from maverick.verifier_head import train_and_evaluate
    res = train_and_evaluate(_linear_examples(), split=0.3, seed=1)
    # A trained linear head should beat the trivial mean predictor on held-out.
    assert res["test_mse"] < res["baseline_test_mse"]
    # And it should separate promising from unpromising steps.
    assert res["discrimination"] > 0.0


def test_predict_and_save_load_roundtrip(tmp_path):
    from maverick.verifier_head import train
    head = train(_linear_examples(40), seed=2)
    p = tmp_path / "head.json"
    head.save(p)
    reloaded = LinearHead.load(p)
    x = [0.5] + [0.0] * 11
    assert abs(reloaded.promise(x) - head.promise(x)) < 1e-9


def test_save_is_atomic_no_torn_read(tmp_path):
    """A serving process re-loading the head while a training run writes it must
    never see a half-written file. With the atomic temp+replace save, a reader
    concurrent with repeated saves always loads a valid head."""
    import threading

    from maverick.verifier_head import train

    p = tmp_path / "head.json"
    train(_linear_examples(20), seed=3).save(p)  # seed a valid file
    errors: list[Exception] = []
    stop = threading.Event()

    def writer():
        for s in range(150):
            train(_linear_examples(20), seed=s).save(p)

    def reader():
        while not stop.is_set():
            try:
                LinearHead.load(p)  # must never see a torn file
            except (ValueError, OSError) as e:
                errors.append(e)

    rt = threading.Thread(target=reader)
    wt = threading.Thread(target=writer)
    rt.start()
    wt.start()
    wt.join()
    stop.set()
    rt.join()
    assert not errors, errors[:3]
    assert list(tmp_path.glob("*.tmp")) == []


def test_empty_examples_is_safe():
    from maverick.verifier_head import discrimination, train
    head = train([])
    assert head.promise([0.0] * 12) == 0.0
    assert discrimination(head, []) == 0.0


# -- end-to-end: trajectory store -> trained head -> governed adoption -------

class _Store:
    """Yields varied trajectory steps so build_prm_examples produces signal."""

    def __init__(self, n):
        from maverick.trajectory_store import TrajectoryStep
        rng = random.Random(0)
        roles = ["coder", "researcher", "writer", "verifier"]
        self._steps = []
        for i in range(n):
            ok = rng.random() > 0.5
            self._steps.append(TrajectoryStep(
                ts=float(i), goal_id=1, episode_id=0, step=i,
                role=rng.choice(roles), tool="shell" if ok else "",
                tool_succeeded=ok, is_final=(i % 7 == 0),
                error="" if ok else "boom",
                promise=(0.8 if ok else 0.2), progress=(0.1 if ok else -0.1)))

    def iter_steps(self, *, limit=10_000):
        return iter(self._steps)


def test_train_and_propose_too_few_examples(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    from maverick.verifier_head import train_and_propose
    assert train_and_propose(_Store(5), controller=_ctrl(tmp_path)) is None


def test_train_and_propose_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_SELF_IMPROVEMENT", "1")
    from maverick.verifier_head import train_and_propose
    verdict = train_and_propose(_Store(60), controller=_ctrl(tmp_path))
    assert verdict is not None
    assert verdict.rung == "policy"  # verifier updates ride the policy rung
