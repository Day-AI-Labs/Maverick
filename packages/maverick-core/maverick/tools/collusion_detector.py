"""Multi-agent voting-collusion detector (roadmap: 2027 H1 safety —
"multi-agent collusion detector").

Independent-quorum guarantees (N agents must *independently* approve a high-risk
action) are defeated if a bloc of agents always votes together — a Sybil/voting-
collusion ring controlled by one source only looks like independent approvals.
This finds those blocs: given each agent's vote sequence across rounds, it links
any pair whose votes agree at or above a threshold and reports the connected
blocs, flagging any large enough to swing a quorum. Pure counting — deterministic
and offline.

ops:
  - detect(votes, [threshold], [quorum])  — ``votes`` is ``{agent: [v, ...]}``
    with equal-length sequences. Links agent pairs whose agreement fraction is
    >= ``threshold`` (default 1.0 = perfectly correlated) and reports each bloc
    of >=2 agents with its cohesion (min pairwise agreement). With ``quorum``,
    a bloc of >= quorum agents is flagged as quorum-defeating.
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

from . import Tool


def _agreement(a: list, b: list) -> float:
    rounds = len(a)
    matches = sum(1 for x, y in zip(a, b) if x == y)
    return matches / rounds


def _detect(votes: dict, threshold: float, quorum: int | None) -> str:
    agents = list(votes.keys())
    seqs: dict[str, list] = {}
    length = None
    for name in agents:
        seq = votes[name]
        if not isinstance(seq, list) or not seq:
            return f"ERROR: agent {name!r} must have a non-empty list of votes"
        if length is None:
            length = len(seq)
        elif len(seq) != length:
            return "ERROR: all agents must have the same number of rounds"
        seqs[name] = [str(v) for v in seq]

    # Union-find over agent pairs that agree at/above the threshold.
    parent = {name: name for name in agents}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pair_agree: dict[tuple[str, str], float] = {}
    for a, b in combinations(agents, 2):
        ag = _agreement(seqs[a], seqs[b])
        pair_agree[(a, b)] = ag
        if ag >= threshold:
            parent[find(a)] = find(b)

    blocs: dict[str, list[str]] = {}
    for name in agents:
        blocs.setdefault(find(name), []).append(name)

    flagged = []
    for members in blocs.values():
        if len(members) < 2:
            continue
        members = sorted(members)
        cohesion = min(
            pair_agree[(a, b)] if (a, b) in pair_agree else pair_agree[(b, a)]
            for a, b in combinations(members, 2)
        )
        flagged.append((members, cohesion))

    flagged.sort(key=lambda x: (-len(x[0]), x[0]))

    header = f"{len(agents)} agents, {length} rounds, threshold {threshold:g}"
    if not flagged:
        return f"CLEAR: no collusion blocs ({header})"

    quorum_hits = [m for m, _ in flagged if quorum is not None and len(m) >= quorum]
    verdict = "COLLUSION" if quorum_hits else "SUSPECT"
    lines = [f"{verdict}: {len(flagged)} bloc(s) ({header}):"]
    for members, cohesion in flagged:
        tag = ""
        if quorum is not None and len(members) >= quorum:
            tag = f" -- quorum-defeating (>= {quorum})"
        lines.append(f"  {{{', '.join(members)}}} cohesion {cohesion:g}{tag}")
    return "\n".join(lines)


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "detect"):
        return f"ERROR: unknown op {args.get('op')!r}"
    votes = args.get("votes")
    if not isinstance(votes, dict) or len(votes) < 2:
        return "ERROR: votes must be an object of >=2 agents -> [votes]"
    threshold = args.get("threshold", 1.0)
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return "ERROR: threshold must be a number in [0, 1]"
    if not 0.0 <= threshold <= 1.0:
        return "ERROR: threshold must be in [0, 1]"
    quorum = args.get("quorum")
    if quorum is not None:
        try:
            quorum = int(quorum)
        except (TypeError, ValueError):
            return "ERROR: quorum must be an integer"
        if quorum < 2:
            return "ERROR: quorum must be >= 2"
    return _detect(votes, threshold, quorum)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["detect"]},
        "votes": {
            "type": "object",
            "description": "agent -> equal-length list of that agent's votes across rounds",
        },
        "threshold": {
            "type": "number",
            "description": "agreement fraction [0,1] to link two agents (default 1.0 = identical)",
        },
        "quorum": {
            "type": "integer",
            "description": "if set, a bloc of >= quorum agents is flagged as quorum-defeating",
        },
    },
    "required": ["votes"],
}


def collusion_detector() -> Tool:
    return Tool(
        name="collusion_detector",
        description=(
            "Detect voting-collusion blocs among agents that defeat independent-"
            "quorum guarantees. op=detect with 'votes' ({agent: [votes]}, equal-"
            "length). Links agent pairs whose agreement fraction >= 'threshold' "
            "(default 1.0 = identical votes) and reports each bloc of >=2 agents "
            "with its cohesion; with 'quorum', flags blocs large enough to swing "
            "it. Deterministic, offline."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
