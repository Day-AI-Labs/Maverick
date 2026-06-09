"""Multi-agent collusion detector (roadmap: 2027 H1 safety).

Heuristic scan over an inter-agent message log for collusion signatures: a pair
of agents exchanging far more with each other than with the rest of the swarm
(back-channel), repeated identical payloads (coordination on a fixed script),
and reciprocal approval loops (A approves B's risky action, B approves A's).
Deterministic and offline — flags candidates for a human to review; it does not
itself block.

ops:
  - scan(messages, [threshold])  — messages: [{from, to, content, [approves]}].
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from . import Tool


def _scan(messages: list[dict], threshold: float) -> str:
    pair_counts: Counter = Counter()
    agent_totals: Counter = Counter()
    payloads: defaultdict[tuple, list] = defaultdict(list)
    approvals: set[tuple] = set()

    for m in messages:
        src = str(m.get("from", "")).strip()
        dst = str(m.get("to", "")).strip()
        if not src or not dst:
            continue
        key = tuple(sorted((src, dst)))
        pair_counts[key] += 1
        agent_totals[src] += 1
        agent_totals[dst] += 1
        content = m.get("content")
        if content:
            payloads[key].append(str(content))
        if m.get("approves"):
            approvals.add((src, dst))

    findings: list[str] = []
    total_msgs = sum(pair_counts.values())

    for (a, b), n in pair_counts.most_common():
        share = n / total_msgs if total_msgs else 0.0
        if share >= threshold and total_msgs >= 4:
            findings.append(
                f"back-channel: {a}<->{b} carry {share:.0%} of all traffic "
                f"({n}/{total_msgs})")

    for key, msgs in payloads.items():
        if len(msgs) >= 3:
            dupes = Counter(msgs).most_common(1)[0]
            if dupes[1] >= 3:
                findings.append(
                    f"scripted: {key[0]}<->{key[1]} repeated an identical "
                    f"payload {dupes[1]}x")

    for a, b in sorted(approvals):
        if (b, a) in approvals:
            findings.append(f"reciprocal-approval loop: {a}->{b} and {b}->{a}")

    if not findings:
        return "CLEAN: no collusion signatures detected"
    # Reciprocal loops are double-listed (a,b)+(b,a); dedupe the report.
    uniq = sorted(set(findings))
    return f"SUSPECT ({len(uniq)} signature(s)):\n- " + "\n- ".join(uniq)


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "scan"):
        return f"ERROR: unknown op {args.get('op')!r}"
    messages = args.get("messages")
    if not isinstance(messages, list) or not messages:
        return "ERROR: messages (list of {from,to,content}) is required"
    threshold = args.get("threshold", 0.6)
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return "ERROR: threshold must be a number in (0,1]"
    return _scan(messages, threshold)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["scan"]},
        "messages": {
            "type": "array",
            "description": "Inter-agent messages: {from, to, content, approves?}",
            "items": {"type": "object"},
        },
        "threshold": {
            "type": "number",
            "description": "Back-channel traffic-share trip point (default 0.6)",
        },
    },
    "required": ["messages"],
}


def collusion_detector() -> Tool:
    return Tool(
        name="collusion_detector",
        description=(
            "Heuristic multi-agent collusion scan over a message log: detects "
            "back-channels (a pair hogging traffic), scripted identical "
            "payloads, and reciprocal-approval loops. op=scan with 'messages' "
            "([{from,to,content,approves?}]) and optional 'threshold'. Returns "
            "CLEAN or SUSPECT with signatures. Flags for human review; offline."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
