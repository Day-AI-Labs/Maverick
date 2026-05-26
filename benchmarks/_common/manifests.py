"""Manifest definitions for Maverick's benchmark suite (May 2026).

Per Karpathy: SWE-bench Verified is contaminated; SWE-bench Pro is the
new credible coding benchmark. GAIA Level 3 and OSWorld are where the
swarm wedge actually wins. Headline metric we report is the
(success_rate, $/task) Pareto frontier across all four baselines.

Each manifest declares: where the dataset comes from, the format we
expect on disk, how to score, the threshold to claim "competitive" vs
"SOTA", and the cost/wall budget we cap each pipeline at.

This file does NOT include the datasets themselves — they're large and
license-restricted. The harness expects the operator to have downloaded
them; the manifest is the contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Manifest:
    name: str
    description: str
    source_url: str
    publication_date: str  # ISO; used by contamination_guard
    instances_expected: int
    max_dollars_per_task: float
    max_wall_seconds_per_task: float
    threshold_competitive: float
    threshold_sota: float
    scoring: str   # "pytest" | "exact-match" | "llm-judge" | "vm-task-check" | ...
    notes: str = ""
    headline: bool = False  # report in the top-of-RESULTS Pareto table
    extras: dict = field(default_factory=dict)


# May 2026 frozen reference numbers. Update when leaderboards move.
MANIFESTS: dict[str, Manifest] = {
    "swebench_pro": Manifest(
        name="SWE-bench Pro",
        description=(
            "Scale's contamination-resistant successor to SWE-bench Verified. "
            "Multi-language, harder verification cost asymmetric, 1865 instances."
        ),
        source_url="https://labs.scale.com/leaderboard/swe_bench_pro_public",
        publication_date="2026-01-15",
        instances_expected=1865,
        max_dollars_per_task=5.0,
        max_wall_seconds_per_task=900.0,
        threshold_competitive=0.50,
        threshold_sota=0.65,
        scoring="pytest",
        notes=(
            "Maverick headline benchmark for coding. Run with three baselines "
            "(single_shot, single_shot_tools, self_consistency_n8) on identical "
            "infrastructure to defend the swarm number."
        ),
        headline=True,
    ),

    "gaia_l3": Manifest(
        name="GAIA Level 3",
        description=(
            "GAIA hardest split: dozens of steps, multimodal, browse+file+arithmetic. "
            "Single-shot ceiling ~65%; multi-agent verifier loops can credibly beat it."
        ),
        source_url="https://huggingface.co/datasets/gaia-benchmark/GAIA",
        publication_date="2024-11-21",
        instances_expected=85,
        max_dollars_per_task=3.0,
        max_wall_seconds_per_task=600.0,
        threshold_competitive=0.50,
        threshold_sota=0.70,
        scoring="exact-match",
        notes=(
            "Maverick's strongest wedge: long-horizon decomposable tasks where "
            "verifier-driven swarms outperform single-shot. Filter HF GAIA "
            "validation split to Level==3."
        ),
        headline=True,
    ),

    "osworld_verified": Manifest(
        name="OSWorld-Verified",
        description=(
            "Real GUI + shell tasks across Ubuntu/Windows/macOS VMs, 369 tasks. "
            "Recovery + tool-use favors verifier loops; <80% ceiling = room to win."
        ),
        source_url="https://github.com/xlang-ai/OSWorld",
        publication_date="2024-10-14",
        instances_expected=369,
        max_dollars_per_task=4.0,
        max_wall_seconds_per_task=1200.0,
        threshold_competitive=0.55,
        threshold_sota=0.75,
        scoring="vm-task-check",
        notes=(
            "Requires a Docker/Podman runtime + VM images. CI runs the harness "
            "in --dry-run only; real numbers come from operator-funded runs."
        ),
        headline=True,
    ),

    "taubench_retail": Manifest(
        name="TAU-bench Retail (pass^4)",
        description=(
            "Multi-turn customer-service tool-use, pass^k with k=4 consistency."
        ),
        source_url="https://github.com/sierra-research/tau-bench",
        publication_date="2024-08-01",
        instances_expected=115,
        max_dollars_per_task=2.0,
        max_wall_seconds_per_task=300.0,
        threshold_competitive=0.65,
        threshold_sota=0.82,
        scoring="task-check",
        notes=(
            "Anthropic stack near saturation here; report but do NOT headline."
        ),
        headline=False,
    ),

    "taubench_airline": Manifest(
        name="TAU-bench Airline (pass^4)",
        description="Harder TAU split: airline booking, partial info.",
        source_url="https://github.com/sierra-research/tau-bench",
        publication_date="2024-08-01",
        instances_expected=50,
        max_dollars_per_task=3.0,
        max_wall_seconds_per_task=600.0,
        threshold_competitive=0.55,
        threshold_sota=0.70,
        scoring="task-check",
        headline=False,
    ),

    "browsecomp": Manifest(
        name="BrowseComp",
        description=(
            "OpenAI's deep-research / browse-and-verify benchmark. 1266 Qs. "
            "Persistence + verification + path diversity → MAV (multi-agent "
            "verification) provably scales better than self-consistency."
        ),
        source_url="https://openai.com/index/browsecomp/",
        publication_date="2025-04-14",
        instances_expected=1266,
        max_dollars_per_task=2.5,
        max_wall_seconds_per_task=600.0,
        threshold_competitive=0.70,
        threshold_sota=0.85,
        scoring="llm-judge",
        notes=(
            "LLM judge uses a different model family than the proposer to "
            "avoid in-family contamination (see verifier.py cross-family guard)."
        ),
        headline=False,
    ),

    "swelancer_diamond": Manifest(
        name="SWE-Lancer Diamond",
        description=(
            "Real $1M Upwork tasks; report $ earned / $ possible as primary "
            "metric. Underexplored — sub-30% IC is the bar."
        ),
        source_url="https://arxiv.org/abs/2502.12115",
        publication_date="2025-02-17",
        instances_expected=237,
        max_dollars_per_task=10.0,
        max_wall_seconds_per_task=3600.0,
        threshold_competitive=0.30,
        threshold_sota=0.45,
        scoring="docker-e2e",
        notes="Headline metric is dollar yield, not pass rate.",
        headline=False,
    ),
}


def get(name: str) -> Manifest:
    if name not in MANIFESTS:
        raise KeyError(
            f"unknown benchmark {name!r}; available: {sorted(MANIFESTS)}"
        )
    return MANIFESTS[name]


def headline_benchmarks() -> list[str]:
    return [k for k, m in MANIFESTS.items() if m.headline]


def all_benchmarks() -> list[str]:
    return list(MANIFESTS.keys())
