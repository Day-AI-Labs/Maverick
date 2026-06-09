"""`maverick-evolve` CLI.

Without args, prints how to use the package programmatically. With ``--demo`` it
runs a real continuous-evolution loop against a SYNTHETIC, no-LLM fitness
landscape -- so you can watch the archive accumulate and the best score climb
across rounds without spending tokens. The real path is identical but with an
``agent_factory`` that builds a live Maverick agent from a config.
"""
from __future__ import annotations

import argparse
import asyncio
import random

from .eval_harness import EvalCase
from .loop import evolve_continuous


def _demo(rounds: int, generations: int) -> int:
    # Synthetic, GRADED landscape (no model): one case per threshold, so fitness
    # rises smoothly with the knob and evolution has a gradient to climb -- a
    # realistic fitness shape, not a flat step. Exercises the full
    # loop/archive/persist machinery deterministically.
    thresholds = [2, 4, 6, 8, 10, 12, 14, 16]
    cases = [EvalCase(prompt=str(t), check=lambda o: o == "GOOD") for t in thresholds]

    def agent_factory(config: dict):
        async def agent(prompt: str) -> str:
            return "GOOD" if config.get("max_swarm_fanout", 0) >= int(prompt) else "BAD"
        return agent

    seed = {"max_swarm_fanout": 4}
    space = {"max_swarm_fanout": ("int", 1, 16)}
    best, history = asyncio.run(evolve_continuous(
        seed, cases, agent_factory,
        rounds=rounds, generations_per_round=generations,
        space=space, rng=random.Random(0),
    ))
    print("continuous evolution (synthetic, no LLM):")
    for h in history:
        print(f"  {h}")
    if best is not None:
        print(f"BEST: score={best.score} config={best.config}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="maverick-evolve")
    p.add_argument("--demo", action="store_true",
                   help="Run a no-LLM synthetic continuous-evolution loop.")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--generations", type=int, default=20)
    args = p.parse_args(argv)
    if not args.demo:
        print(
            "maverick-evolve: governed config-evolution.\n"
            "  --demo            run a no-LLM synthetic evolution loop\n"
            "Programmatic: maverick_evolve.evolve_continuous(seed, cases, agent_factory, ...)"
        )
        return 0
    return _demo(args.rounds, args.generations)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
