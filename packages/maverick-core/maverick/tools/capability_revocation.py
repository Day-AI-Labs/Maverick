"""Capability revocation propagation (roadmap: 2028 H2 safety).

When a capability is revoked from a principal, every principal that holds that
capability *only* by transitive delegation from the revoked holder must lose it
too. Given a delegation graph (grants: principal -> grantee : capability) and a
revocation (principal, capability), compute the full set of principals that
transitively lose the capability via BFS over the grant edges for that
capability. Deterministic and offline.

ops:
  - propagate(grants, principal, capability)  — grants: [{from,to,capability}].
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from . import Tool


def _propagate(grants: list[dict], principal: str, capability: str) -> str:
    # Build the delegation adjacency for THIS capability only: who did each
    # principal grant the capability to.
    edges: defaultdict[str, set[str]] = defaultdict(set)
    for g in grants:
        if not isinstance(g, dict):
            continue
        cap = str(g.get("capability", "")).strip()
        if cap != capability:
            continue
        src = str(g.get("from", "")).strip()
        dst = str(g.get("to", "")).strip()
        if not src or not dst:
            continue
        edges[src].add(dst)

    # BFS from the revoked holder's direct grantees. The revoked principal is
    # the root of the revocation, not itself a "downstream loser".
    lost: set[str] = set()
    queue: deque[str] = deque(sorted(edges.get(principal, set())))
    while queue:
        node = queue.popleft()
        if node in lost or node == principal:
            continue
        lost.add(node)
        for nxt in sorted(edges.get(node, set())):
            if nxt not in lost:
                queue.append(nxt)

    if not lost:
        return (f"REVOKED {capability!r} from {principal}: "
                f"no downstream principals affected")
    affected = sorted(lost)
    return (f"REVOKED {capability!r} from {principal}: "
            f"{len(affected)} principal(s) transitively lose it:\n- "
            + "\n- ".join(affected))


def _run(args: dict[str, Any]) -> str:
    if args.get("op") not in (None, "propagate"):
        return f"ERROR: unknown op {args.get('op')!r}"
    grants = args.get("grants")
    if not isinstance(grants, list):
        return "ERROR: grants (list of {from,to,capability}) is required"
    principal = str(args.get("principal") or "").strip()
    if not principal:
        return "ERROR: principal (the revoked holder) is required"
    capability = str(args.get("capability") or "").strip()
    if not capability:
        return "ERROR: capability is required"
    return _propagate(grants, principal, capability)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["propagate"]},
        "grants": {
            "type": "array",
            "description": "Delegation grants: {from, to, capability}",
            "items": {"type": "object"},
        },
        "principal": {"type": "string", "description": "Holder the capability is revoked from"},
        "capability": {"type": "string", "description": "Capability being revoked"},
    },
    "required": ["grants", "principal", "capability"],
}


def capability_revocation() -> Tool:
    return Tool(
        name="capability_revocation",
        description=(
            "Propagate a capability revocation through a delegation graph. "
            "op=propagate with 'grants' ([{from,to,capability}]), 'principal' "
            "(the revoked holder), and 'capability'. Returns every principal "
            "that transitively loses the capability (BFS over that capability's "
            "grant edges). Deterministic, offline."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
