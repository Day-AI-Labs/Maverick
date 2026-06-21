"""ELC-Bench v0 — Experiential Learning & Compounding Benchmark.

The open problem (Karpathy's "agents have no sleep / no on-the-job learning"):
an LLM agent does not get better at its job with experience. "Memory"/RAG
retrieves old text but capability does not *compound* — the 501st run is no
better than the 1st. There is also no clean way to *measure* compounding, so
the field argues with demos.

This file is a deliberately minimal, deterministic, dependency-free measuring
stick + reference mechanism. It is NOT the breakthrough; it is the honest scaffold
that makes the claim falsifiable. It answers one question with numbers:

    Given a stream of related tasks, does a learner's success rate RISE with
    experience, and does that improvement TRANSFER to genuinely novel tasks
    (new compositions never seen during training) — beating a no-learning floor,
    a memorization baseline (RAG), and a reflexion baseline?

Honesty rules baked in:
  * a no-learning FLOOR is always reported (if a learner can't beat it, it's noise);
  * the headline metric is HELD-OUT NOVEL-COMPOSITION transfer, where pure
    memorization is *structurally unable* to help — so a win there is real;
  * results are averaged over multiple seeds with std, not one lucky run;
  * everything is deterministic and re-runnable: `python3 elcbench.py`.

What a "win" here does and does NOT prove: it shows the *mechanism* (compile
verified sub-procedures into reusable, credit-assigned, consolidated skills)
produces compounding + transfer in a controlled world. It does NOT prove it
works on fuzzy real LLM-agent tasks — that's the next experiment (needs live
agents). This is the sanity floor every grand claim should have to clear first.
"""
from __future__ import annotations

import argparse
import random
import statistics
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# World: a crafting/recipe DAG. To "make" a non-base item you must craft its
# inputs (recursively) down to base items. Many items, several recipes each,
# shared intermediates -> deep goals are expensive to PLAN from scratch (the
# planner explores recipe alternatives under an expansion budget), but their
# sub-trees recur across tasks, so an agent that compiles reusable sub-plans can
# reach deeper/novel goals within the same budget. Cost = planner expansions;
# "experience" = tasks seen.
# --------------------------------------------------------------------------- #

@dataclass
class World:
    n_items: int
    n_base: int
    recipes: dict[int, list[tuple[int, ...]]]
    depth: dict[int, int]

    def is_base(self, i: int) -> bool:
        return i < self.n_base


def make_world(seed: int, *, n_items: int = 260, n_base: int = 24,
               recipes_per_item: int = 4, inputs_per_recipe: int = 3) -> World:
    rng = random.Random(seed)
    recipes: dict[int, list[tuple[int, ...]]] = {}
    for item in range(n_base, n_items):
        rs: list[tuple[int, ...]] = []
        lo = max(0, item - 40)  # inputs drawn from a recent window -> real depth
        for _ in range(recipes_per_item):
            k = min(inputs_per_recipe, item)
            rs.append(tuple(sorted(rng.sample(range(lo, item), k=k))))
        rng.shuffle(rs)
        recipes[item] = rs
    # depth = min over recipes of 1 + max input depth (base = 0)
    depth: dict[int, int] = {i: 0 for i in range(n_base)}
    for item in range(n_base, n_items):
        depth[item] = min(1 + max(depth[i] for i in r) for r in recipes[item])
    return World(n_items, n_base, recipes, depth)


class _Budget(Exception):
    pass


def plan(world: World, goal: int, skills: set[int], budget: int):
    """Deterministic AND/OR depth-first planner with a hard expansion budget.

    `skills` are items the learner can produce directly (compiled experience):
    they cost 0 expansions and prune their whole sub-tree. Returns
    (plan_or_None, expansions). Within-task SUCCESS memoization is on for every
    learner (a fair, smart baseline) — the only thing that differs between
    learners is the `skills` set they bring."""
    st = {"exp": 0}
    memo: dict[int, list | None] = {}

    def soln(item: int):
        if world.is_base(item) or item in skills:
            return []
        if item in memo:
            return memo[item]
        for recipe in world.recipes[item]:
            st["exp"] += 1
            if st["exp"] > budget:
                raise _Budget()
            sub: list = []
            ok = True
            for inp in recipe:
                r = soln(inp)
                if r is None:
                    ok = False
                    break
                sub += r
            if ok:
                memo[item] = sub + [(item, recipe)]
                return memo[item]
        memo[item] = None
        return None

    try:
        res = soln(goal)
    except _Budget:
        return None, st["exp"]
    return res, st["exp"]


def intermediates(plan_steps: list) -> list[int]:
    """The non-base items produced along a verified plan — the reusable skills."""
    return [item for (item, _recipe) in plan_steps]


# --------------------------------------------------------------------------- #
# Learners. Same planner + same budget for all; they differ only in what
# experience they carry forward.
# --------------------------------------------------------------------------- #

class Learner:
    name = "base"

    def solve(self, world: World, goal: int, budget: int) -> tuple[bool, int]:
        raise NotImplementedError

    def freeze(self):  # stop learning for held-out eval
        pass


class NoLearning(Learner):
    name = "no-learning (floor)"

    def solve(self, world, goal, budget):
        p, exp = plan(world, goal, set(), budget)
        return p is not None, exp


class MemoryReplay(Learner):
    """RAG/memorization: cache whole-goal solutions. Replays exact past goals
    for free; cannot help on a never-seen goal (no composition)."""
    name = "memory/RAG"

    def __init__(self):
        self.cache: dict[int, list] = {}
        self.frozen = False

    def freeze(self):
        self.frozen = True

    def solve(self, world, goal, budget):
        if goal in self.cache:
            return True, 0
        p, exp = plan(world, goal, set(), budget)
        if p is not None and not self.frozen:
            self.cache[goal] = p
        return p is not None, exp


class Reflexion(Learner):
    """Reflexion-style: remember which goals it failed and 'try harder' (more
    budget) on a repeat. Helps on repeated failures; no composition/transfer."""
    name = "reflexion"

    def __init__(self):
        self.fails: dict[int, int] = {}
        self.frozen = False

    def freeze(self):
        self.frozen = True

    def solve(self, world, goal, budget):
        b = int(budget * (1 + 0.6 * self.fails.get(goal, 0)))
        p, exp = plan(world, goal, set(), b)
        if p is None and not self.frozen:
            self.fails[goal] = self.fails.get(goal, 0) + 1
        return p is not None, exp


class SkillCompiler(Learner):
    """Ours. After a verified solve, compile every intermediate sub-procedure
    into a reusable skill with a usage count (credit assignment: skills that
    recur across successful plans accumulate credit). Periodic CONSOLIDATION
    ('sleep') prunes the library to the top-K by credit — keeping the *reusable*
    skills and discarding one-offs, which both generalizes and avoids the macro-
    operator 'utility problem' (too many macros slow planning). On a new task it
    plans WITH the skill set, so learned sub-procedures cost 0 and deep/novel
    goals fall within budget."""
    name = "skill-compiler (ours)"

    def __init__(self, *, capacity: int = 40, consolidate_every: int = 25):
        self.credit: dict[int, int] = {}
        self.skills: set[int] = set()
        self.capacity = capacity
        self.every = consolidate_every
        self.t = 0
        self.frozen = False

    def freeze(self):
        self.frozen = True

    def _consolidate(self):
        # keep the highest-credit skills; prune the long tail (utility problem).
        top = sorted(self.credit, key=lambda k: self.credit[k], reverse=True)[:self.capacity]
        self.skills = set(top)

    def solve(self, world, goal, budget):
        p, exp = plan(world, goal, self.skills, budget)
        ok = p is not None
        if ok and not self.frozen:
            self.t += 1
            for item in intermediates(p):
                self.credit[item] = self.credit.get(item, 0) + 1
            if self.t % self.every == 0:
                self._consolidate()
        return ok, exp


# --------------------------------------------------------------------------- #
# Benchmark harness
# --------------------------------------------------------------------------- #

def split_goals(world: World, rng: random.Random, min_depth: int):
    """Disjoint train/test goal pools, so held-out test goals are GUARANTEED
    novel (never trainable) and the test set is never empty."""
    hard = [i for i in range(world.n_base, world.n_items) if world.depth[i] >= min_depth]
    rng.shuffle(hard)
    if len(hard) < 20:
        raise RuntimeError(f"too few hard goals ({len(hard)}) at min_depth={min_depth}; "
                           "raise n_items or lower min_depth")
    cut = int(len(hard) * 0.7)
    return hard[:cut], hard[cut:]


def sparkline(xs: list[float]) -> str:
    blocks = " ▁▂▃▄▅▆▇█"
    return "".join(blocks[min(len(blocks) - 1, max(0, int(round(x * (len(blocks) - 1)))))] for x in xs)


def rolling(success: list[int], w: int) -> list[float]:
    out = []
    for i in range(len(success)):
        lo = max(0, i - w + 1)
        win = success[lo:i + 1]
        out.append(sum(win) / len(win))
    return out


@dataclass
class Result:
    train_success: float = 0.0
    final_window: float = 0.0
    test_success: float = 0.0
    test_cost: float = 0.0
    curve: list[float] = field(default_factory=list)


def run_one(seed: int, *, budget: int, n_train: int, n_test: int,
            min_depth: int) -> dict[str, Result]:
    world = make_world(seed)
    rng = random.Random(seed * 7919 + 1)
    train_pool, test_pool = split_goals(world, rng, min_depth)
    train = [rng.choice(train_pool) for _ in range(n_train)]
    # held-out goals come from a DISJOINT pool -> guaranteed novel compositions
    test = [rng.choice(test_pool) for _ in range(n_test)]

    learners = [NoLearning(), MemoryReplay(), Reflexion(), SkillCompiler()]
    out: dict[str, Result] = {}
    for lr in learners:
        succ = []
        for g in train:
            ok, _ = lr.solve(world, g, budget)
            succ.append(1 if ok else 0)
        lr.freeze()
        tcost = []
        tsucc = []
        for g in test:
            ok, exp = lr.solve(world, g, budget)
            tsucc.append(1 if ok else 0)
            tcost.append(exp)
        r = Result()
        r.train_success = sum(succ) / len(succ)
        r.final_window = sum(succ[-50:]) / min(50, len(succ))
        r.test_success = (sum(tsucc) / len(tsucc)) if tsucc else float("nan")
        r.test_cost = (sum(tcost) / len(tcost)) if tcost else float("nan")
        r.curve = rolling(succ, 25)
        out[lr.name] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--budget", type=int, default=60)
    ap.add_argument("--train", type=int, default=400)
    ap.add_argument("--test", type=int, default=120)
    ap.add_argument("--min-depth", type=int, default=6)
    args = ap.parse_args()

    agg: dict[str, list[Result]] = {}
    curves: dict[str, list[list[float]]] = {}
    for s in range(args.seeds):
        res = run_one(s, budget=args.budget, n_train=args.train,
                      n_test=args.test, min_depth=args.min_depth)
        for name, r in res.items():
            agg.setdefault(name, []).append(r)
            curves.setdefault(name, []).append(r.curve)

    def ms(vals):
        return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)

    print(f"\nELC-Bench v0  | seeds={args.seeds} budget={args.budget} "
          f"train={args.train} test={args.test} min_depth={args.min_depth}")
    print("=" * 78)
    order = ["no-learning (floor)", "memory/RAG", "reflexion", "skill-compiler (ours)"]
    header = f"{'learner':<24}{'train_succ':>12}{'final50':>10}{'TEST(novel)':>14}{'test_cost':>11}"
    print(header)
    print("-" * 78)
    for name in order:
        rs = agg[name]
        tr_m, tr_s = ms([r.train_success for r in rs])
        fw_m, _ = ms([r.final_window for r in rs])
        te_m, te_s = ms([r.test_success for r in rs])
        tc_m, _ = ms([r.test_cost for r in rs])
        print(f"{name:<24}{tr_m*100:>9.1f}%  {fw_m*100:>7.1f}% "
              f"{te_m*100:>9.1f}%±{te_s*100:>3.0f} {tc_m:>10.1f}")
    print("-" * 78)
    print("learning curves (rolling success over the training stream, mean across seeds):")
    L = min(len(c[0]) for c in curves.values())
    for name in order:
        mean_curve = [statistics.mean(c[i] for c in curves[name]) for i in range(L)]
        # downsample to ~60 cols
        step = max(1, L // 60)
        ds = mean_curve[::step]
        print(f"  {name:<24} {sparkline(ds)}  →{mean_curve[-1]*100:4.0f}%")
    print("=" * 78)
    print("Read: the floor shows the task stream is genuinely hard (deep goals\n"
          "blow the planning budget). A learner only matters if it beats the floor\n"
          "on TEST(novel) — held-out goals never seen in training, where memorizing\n"
          "past solutions cannot help and only COMPOSED skills can.")


if __name__ == "__main__":
    main()
