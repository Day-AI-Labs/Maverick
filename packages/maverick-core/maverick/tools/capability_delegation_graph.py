"""Capability delegation graph (roadmap: 2027 H1 safety).

When an agent hands a capability to a sub-agent, and that one hands it on
again, the chain of who-can-do-what grows past anyone's head. This tool reads
the list of delegations and answers the questions a reviewer actually asks:
is anyone delegating a capability they were never granted (privilege
escalation), are there delegation cycles, and who can ultimately exercise a
given capability (the transitive reach).

Pairs with ``capability.py`` (which mints/checks the tokens); this is the
offline static analysis over a set of grants. Deterministic, no model.

ops:
  - analyze(delegations[, roots])  — delegations: [{from, to, capability}].
    'roots' (optional): {capability: [agents]} the capability's true holders.
    Reports cycles, escalation (delegating an ungranted capability), and the
    transitive holder set per capability.
"""
from __future__ import annotations

from typing import Any

from . import Tool


def _parse(delegations: Any) -> tuple[list[tuple[str, str, str]] | None, str]:
    if not isinstance(delegations, list) or not delegations:
        return None, "ERROR: delegations must be a non-empty array of {from, to, capability}"
    out: list[tuple[str, str, str]] = []
    for d in delegations:
        if not isinstance(d, dict) or not all(k in d for k in ("from", "to", "capability")):
            return None, "ERROR: each delegation needs 'from', 'to', 'capability'"
        out.append((str(d["from"]), str(d["to"]), str(d["capability"])))
    return out, ""


def _find_cycles(edges: list[tuple[str, str]]) -> list[list[str]]:
    """Return simple cycles in a directed graph (DFS, dedup by node set)."""
    adj: dict[str, list[str]] = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
    cycles: list[list[str]] = []
    seen: set[frozenset[str]] = set()

    def dfs(node: str, stack: list[str], onstack: set[str]) -> None:
        for nxt in adj.get(node, []):
            if nxt in onstack:
                cyc = stack[stack.index(nxt):]
                key = frozenset(cyc)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cyc + [nxt])
            elif nxt not in visited:
                stack.append(nxt)
                onstack.add(nxt)
                dfs(nxt, stack, onstack)
                stack.pop()
                onstack.discard(nxt)

    visited: set[str] = set()
    for n in list(adj):
        if n not in visited:
            dfs(n, [n], {n})
            visited |= {n}
            for s in adj:
                visited.add(s)
    return cycles


def _analyze(args: dict[str, Any]) -> str:
    dels, err = _parse(args.get("delegations"))
    if err:
        return err
    assert dels is not None

    roots = args.get("roots", {})
    if not isinstance(roots, dict):
        return "ERROR: roots must be a map {capability: [agents]}"

    by_cap: dict[str, list[tuple[str, str]]] = {}
    for frm, to, cap in dels:
        by_cap.setdefault(cap, []).append((frm, to))

    lines: list[str] = []
    escalations: list[str] = []
    all_cycles: list[str] = []

    for cap in sorted(by_cap):
        edges = by_cap[cap]
        holders: set[str] = set(str(a) for a in roots.get(cap, []))
        # Transitive closure: anyone reachable from a true holder.
        changed = True
        while changed:
            changed = False
            for frm, to in edges:
                if frm in holders and to not in holders:
                    holders.add(to)
                    changed = True
        # Escalation: a delegator that is not (transitively) a holder, when
        # roots were supplied for this capability.
        if cap in roots:
            for frm, to in edges:
                if frm not in holders:
                    escalations.append(f"{frm} delegated '{cap}' to {to} but never held it")
        for cyc in _find_cycles(edges):
            all_cycles.append(f"'{cap}': " + " -> ".join(cyc))
        reach = ", ".join(sorted(holders)) if holders else "(unknown — no roots given)"
        lines.append(f"{cap}: holders={reach}")

    out = [f"delegations: {len(dels)}  capabilities: {len(by_cap)}"]
    out.extend(lines)
    if all_cycles:
        out.append(f"CYCLES ({len(all_cycles)}):")
        out.extend(f"  - {c}" for c in all_cycles)
    if escalations:
        out.append(f"ESCALATION ({len(escalations)}):")
        out.extend(f"  - {e}" for e in escalations)
    if not all_cycles and not escalations:
        out.append("verdict: OK (no cycles, no escalation)")
    return "\n".join(out)


def _run(args: dict[str, Any]) -> str:
    op = args.get("op", "analyze")
    if op != "analyze":
        return f"ERROR: unknown op {op!r}"
    return _analyze(args)


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["analyze"]},
        "delegations": {
            "type": "array",
            "description": "[{from, to, capability}]",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "capability": {"type": "string"},
                },
                "required": ["from", "to", "capability"],
            },
        },
        "roots": {
            "type": "object",
            "description": "optional true holders per capability: {capability: [agents]}",
        },
    },
    "required": ["delegations"],
}


def capability_delegation_graph() -> Tool:
    return Tool(
        name="capability_delegation_graph",
        description=(
            "Static analysis over capability delegations. op=analyze with "
            "'delegations' ([{from, to, capability}]) and optional 'roots' "
            "({capability: [agents]}) reports delegation cycles, privilege "
            "escalation (delegating an ungranted capability), and the "
            "transitive holder set per capability. Deterministic; no model."
        ),
        input_schema=_SCHEMA,
        fn=_run,
        parallel_safe=True,
    )
