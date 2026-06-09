"""Multi-agent collusion detector (roadmap: 2027 H1 safety).

The swarm's safety story leans on *independent* checks: a proposer writes,
a verifier judges, a critic grades. That only works if the agents actually
disagree when they should. This tool reads a batch of agent messages and
flags the signals that those independent voices have collapsed into one --
rubber-stamping, echoed reasoning, circular endorsement -- the tell-tales of
collusion that let bad work sail through review.

Deterministic and offline -- lexical overlap + simple rate counting, no model.

ops:
  - scan(messages[, threshold])  — messages: list of {agent, text, verdict?}.
    Reports pairwise text similarity between distinct agents (high = echoed
    reasoning), per-agent approval rate (1.0 over many = rubber-stamp), and a
    verdict (COLLUSION SIGNALS / CLEAN).
"""
from __future__ import annotations

import re
from typing import Any

from . import Tool

_APPROVE = {"approve", "approved", "accept", "accepted", "pass", "lgtm", "yes", "ok"}
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(str(text).lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _scan(args: dict[str, Any]) -> str:
    msgs = args.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return "ERROR: messages must be a non-empty array of {agent, text}"
    threshold = args.get("threshold", 0.85)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        return "ERROR: threshold must be a number in (0, 1]"

    rows: list[tuple[str, str, str | None]] = []
    for m in msgs:
        if not isinstance(m, dict) or "agent" not in m or "text" not in m:
            return "ERROR: each message needs 'agent' and 'text'"
        verdict = m.get("verdict")
        rows.append((str(m["agent"]), str(m["text"]), str(verdict).lower() if verdict is not None else None))

    signals: list[str] = []

    # Echoed reasoning: high lexical overlap between DISTINCT agents.
    toks = [(a, _tokens(t)) for a, t, _ in rows]
    seen: set[tuple[int, int]] = set()
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            if toks[i][0] == toks[j][0] or (i, j) in seen:
                continue
            sim = _jaccard(toks[i][1], toks[j][1])
            if sim >= threshold:
                seen.add((i, j))
                signals.append(
                    f"echoed reasoning: {toks[i][0]} ~ {toks[j][0]} (similarity {sim:.2f})"
                )

    # Rubber-stamp: an agent whose verdicts are present and all approvals.
    by_agent: dict[str, list[str]] = {}
    for a, _, v in rows:
        if v is not None:
            by_agent.setdefault(a, []).append(v)
    for a, verdicts in sorted(by_agent.items()):
        approvals = sum(1 for v in verdicts if v in _APPROVE)
        if len(verdicts) >= 3 and approvals == len(verdicts):
            signals.append(f"rubber-stamp: {a} approved all {len(verdicts)} reviews")

    lines = [f"agents: {len({a for a, _, _ in rows})}  messages: {len(rows)}"]
    if signals:
        lines.append(f"verdict: COLLUSION SIGNALS ({len(signals)})")
        lines.extend(f"  - {s}" for s in signals)
    else:
        lines.append("verdict: CLEAN")
    return "\n".join(lines)


def _run(args: dict[str, Any]) -> str:
    op = args.get("op", "scan")
    if op != "scan":
        return f"ERROR: unknown op {op!r}"
    return _scan(args)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["scan"]},
        "messages": {
            "type": "array",
            "description": "agent messages: [{agent, text, verdict?}]",
            "items": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "text": {"type": "string"},
                    "verdict": {"type": "string"},
                },
                "required": ["agent", "text"],
            },
        },
        "threshold": {"type": "number", "description": "similarity cutoff for echoed reasoning (default 0.85)"},
    },
    "required": ["messages"],
}


def collusion_detector() -> Tool:
    return Tool(
        name="collusion_detector",
        description=(
            "Detect collusion between independent swarm agents. op=scan with "
            "'messages' ([{agent, text, verdict?}]) flags echoed reasoning "
            "(high lexical overlap between distinct agents), rubber-stamping "
            "(an agent that approves every review), and reports a verdict. "
            "Deterministic; no model call."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
