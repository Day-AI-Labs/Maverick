"""The Hippocampus: consolidate causally-beneficial habits, reinforce ones that
keep proving themselves, and FORGET ones that stop -- without losing the good.
"""
from __future__ import annotations

from maverick import procedural_memory as pm
from maverick.trajectory_store import TrajectoryStep


def _ep(eid, domain, tool, outcome):
    return [
        TrajectoryStep(ts=1.0, goal_id=1, episode_id=eid, step=0, role="coder",
                       tool=tool, domain=domain),
        TrajectoryStep(ts=1.0, goal_id=1, episode_id=eid, step=1, role="coder",
                       tool="log", domain=domain, is_final=True, outcome=outcome),
    ]


def _corpus(good_tool="Y"):
    """`good_tool` causally helps (+0.5) in both domains; `slow` does nothing."""
    steps, eid = [], 0
    for domain in ("fin", "ops"):
        for _ in range(12):
            eid += 1
            steps += _ep(eid, domain, good_tool, 0.9)
        for _ in range(12):
            eid += 1
            steps += _ep(eid, domain, "slow", 0.4)
    return steps


def test_consolidate_keeps_only_causally_beneficial():
    mems = pm.consolidate(_corpus("Y"))
    assert [m.action for m in mems] == ["Y"]
    assert mems[0].benefit > 0 and mems[0].strength == pm._BASE


def test_reinforcement_strengthens_a_recurring_habit():
    first = pm.consolidate(_corpus("Y"))
    second = pm.consolidate(_corpus("Y"), prior=first)   # Y proves itself again
    assert second[0].action == "Y"
    assert second[0].strength > first[0].strength         # climbed


def test_unreinforced_memory_decays_and_is_forgotten():
    # Y is strong, then the corpus stops showing Y as beneficial -> it fades.
    mems = pm.consolidate(_corpus("Y"))
    neutral = []  # nothing beneficial in an empty corpus
    cycle1 = pm.consolidate(neutral, prior=mems)
    assert pm.MemoryStore(path=None) is not None  # store import smoke
    # base 0.5 - decay 0.25 = 0.25 (survives one cycle)...
    assert any(m.action == "Y" for m in cycle1)
    cycle2 = pm.consolidate(neutral, prior=cycle1)
    # ...0.25 - 0.25 = 0.0 < retire floor -> forgotten (no catastrophic loss of
    # anything still useful; only the stale habit fades).
    assert not any(m.action == "Y" for m in cycle2)


def test_store_recall_and_roundtrip(tmp_path):
    store = pm.MemoryStore(path=tmp_path / "m.json")
    store.update(pm.consolidate(_corpus("Y")))
    assert store.recall()[0].action == "Y"
    assert store.strength_of("Y") == pm._BASE
    assert pm.MemoryStore(path=tmp_path / "m.json").recall()[0].action == "Y"  # persisted


def test_recall_empty_store_is_noop(tmp_path):
    assert pm.MemoryStore(path=tmp_path / "m.json").recall() == []


def test_recall_prompt_surfaces_habits(tmp_path):
    store = pm.MemoryStore(path=tmp_path / "m.json")
    assert pm.recall_prompt(store=store) == ""        # empty -> no prompt change
    store.update(pm.consolidate(_corpus("Y")))
    prompt = pm.recall_prompt(store=store)
    assert "Learned habits" in prompt and "prefer 'Y'" in prompt
