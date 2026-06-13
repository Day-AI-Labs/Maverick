"""Federated audit-log verification (roadmap: 2028 H2 safety).

Each node/tenant keeps its own signed, hash-chained audit log
(``audit/signing.py``: per-file ``verify_chain`` + cross-file
``verify_anchors``). In a federation — multi-tenant hosting, a fleet of
workers, A2A-delegated peers — those logs *reference each other*: node A
records "delegated task T to node B", node B records "accepted task T from
node A". Single-node verification can't catch a node that **drops its half**
of a cross-node event to hide an action.

This adds the federation layer:

* :func:`collect_node` — verify ONE node's chain (reusing ``verify_chain`` /
  ``verify_anchors``) and extract its **cross-references** (events naming a
  peer node + a correlation id).
* :func:`cross_verify` — over a set of verified nodes, confirm every
  cross-reference is **reciprocated**: if A claims a link to B for correlation
  C, B's log must carry the matching counterpart. An unreciprocated reference
  (a dropped/forged half) is reported with which node is missing it.
* :func:`verify_federation` — the operator entry point: per-node integrity +
  cross-node reciprocity into one report.

Pure over already-extracted event rows (no signing key needed beyond what
``verify_chain`` already does); deterministic and offline. A node whose own
chain is broken is reported and excluded from reciprocity (you can't trust its
references).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Audit event fields that mark a cross-node reference. An event is a
# cross-reference when it names a peer node and a correlation id; ``direction``
# (sent/received) lets reciprocity pair the two halves.
_PEER_FIELDS = ("peer_node", "peer", "to_node", "from_node")
_CORR_FIELDS = ("correlation_id", "corr_id", "task_id", "delegation_id")


@dataclass
class CrossRef:
    node: str               # the node whose log this row came from
    peer: str               # the node it references
    correlation: str        # the shared id linking the two halves
    direction: str          # "sent" | "received" | "unknown"
    line_no: int = 0


@dataclass
class NodeReport:
    node: str
    intact: bool
    breaks: list = field(default_factory=list)     # list[ChainBreak]
    crossrefs: list[CrossRef] = field(default_factory=list)


@dataclass
class FederationReport:
    nodes: dict[str, NodeReport] = field(default_factory=dict)
    # (node, peer, correlation, direction) references whose counterpart is
    # absent from the peer's log.
    unreciprocated: list[CrossRef] = field(default_factory=list)
    # references into a node whose own chain is broken (can't be trusted).
    untrusted_peer: list[CrossRef] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return (all(n.intact for n in self.nodes.values())
                and not self.unreciprocated and not self.untrusted_peer)


def _first(d: dict, fields) -> str | None:
    for f in fields:
        v = d.get(f)
        if v not in (None, ""):
            return str(v)
    return None


def _opposite(direction: str) -> str:
    return {"sent": "received", "received": "sent"}.get(direction, direction)


def extract_crossrefs(node: str, rows: list[dict]) -> list[CrossRef]:
    """Pull cross-node references out of one node's audit rows.

    A row is a reference when it names a peer node AND a correlation id. The
    ``direction`` is read from a ``direction``/``dir`` field (sent/received),
    defaulting to "unknown" — reciprocity still pairs on (peer, correlation).
    """
    out: list[CrossRef] = []
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        peer = _first(row, _PEER_FIELDS)
        corr = _first(row, _CORR_FIELDS)
        if not peer or not corr:
            continue
        direction = str(row.get("direction") or row.get("dir") or "unknown").lower()
        if direction not in ("sent", "received", "unknown"):
            direction = "unknown"
        out.append(CrossRef(node=node, peer=peer, correlation=corr,
                            direction=direction, line_no=i))
    return out


def collect_node(node: str, audit_dir: Path, rows: list[dict], *,
                 pubkey_hex: str | None = None) -> NodeReport:
    """Verify one node's chain integrity and extract its cross-references.

    ``rows`` are the node's decoded audit events (the caller reads them; this
    stays offline). ``audit_dir`` is verified with the real chain/anchor
    checks when it exists.
    """
    breaks: list = []
    try:
        from .signing import ChainBreak, verify_anchors, verify_chain
        d = Path(audit_dir)
        if not d.is_dir():
            breaks.append(ChainBreak(0, "missing_audit_dir", str(d)))
        else:
            audit_files = [
                f for f in sorted(d.glob("*.ndjson"))
                if not f.name.startswith(".")
            ]
            if not audit_files:
                breaks.append(ChainBreak(0, "missing_audit_logs", str(d)))
            for f in audit_files:
                breaks.extend(verify_chain(f, pubkey_hex))
            breaks.extend(verify_anchors(d, pubkey_hex))
    except Exception as e:  # pragma: no cover -- verification never crashes the report
        from .signing import ChainBreak
        breaks = [ChainBreak(0, "verify_error", str(e))]
    return NodeReport(
        node=node, intact=not breaks, breaks=breaks,
        crossrefs=extract_crossrefs(node, rows),
    )


def cross_verify(nodes: dict[str, NodeReport]) -> tuple[list[CrossRef], list[CrossRef]]:
    """Confirm every cross-reference is reciprocated by the named peer.

    Returns ``(unreciprocated, untrusted_peer)``. A reference is reciprocated
    when the peer's log holds a row with the same correlation that names this
    node back (opposite direction when both declare one). A reference into a
    node whose own chain is broken is ``untrusted_peer`` (its absence proves
    nothing — the log can't be trusted).
    """
    # Index each node's refs by (correlation) -> set of peers it names.
    by_node_corr: dict[str, dict[str, list[CrossRef]]] = {}
    for name, rep in nodes.items():
        per_corr: dict[str, list[CrossRef]] = {}
        for ref in rep.crossrefs:
            per_corr.setdefault(ref.correlation, []).append(ref)
        by_node_corr[name] = per_corr

    unreciprocated: list[CrossRef] = []
    untrusted: list[CrossRef] = []
    for name, rep in nodes.items():
        for ref in rep.crossrefs:
            peer_rep = nodes.get(ref.peer)
            if peer_rep is None or not peer_rep.intact:
                untrusted.append(ref)
                continue
            # The peer must hold a counterpart row: same correlation, naming us.
            counterparts = [
                r for r in by_node_corr.get(ref.peer, {}).get(ref.correlation, [])
                if r.peer == name
            ]
            if ref.direction in ("sent", "received"):
                counterparts = [r for r in counterparts
                                if r.direction in (_opposite(ref.direction), "unknown")]
            if not counterparts:
                unreciprocated.append(ref)
    return unreciprocated, untrusted


def verify_federation(node_inputs: dict[str, tuple[Path, list[dict]]], *,
                      pubkey_hex: str | None = None) -> FederationReport:
    """Operator entry point: per-node integrity + cross-node reciprocity.

    ``node_inputs`` maps node name -> ``(audit_dir, rows)``. Returns a
    :class:`FederationReport`; ``consistent`` is True iff every chain is intact
    and every cross-reference is reciprocated.
    """
    report = FederationReport()
    for name, (audit_dir, rows) in node_inputs.items():
        report.nodes[name] = collect_node(name, audit_dir, rows, pubkey_hex=pubkey_hex)
    report.unreciprocated, report.untrusted_peer = cross_verify(report.nodes)
    return report


def render(report: FederationReport) -> str:
    lines = [f"federation: {len(report.nodes)} node(s); "
             + ("CONSISTENT" if report.consistent else "INCONSISTENT")]
    for name, rep in sorted(report.nodes.items()):
        status = "intact" if rep.intact else f"BROKEN ({len(rep.breaks)} break(s))"
        lines.append(f"  {name}: {status}, {len(rep.crossrefs)} cross-ref(s)")
    for ref in report.unreciprocated:
        lines.append(f"  UNRECIPROCATED: {ref.node} -> {ref.peer} "
                     f"(corr={ref.correlation}, {ref.direction}) has no counterpart")
    for ref in report.untrusted_peer:
        lines.append(f"  UNTRUSTED PEER: {ref.node} -> {ref.peer} "
                     f"(corr={ref.correlation}) — peer chain is broken")
    return "\n".join(lines)


__all__ = [
    "CrossRef", "NodeReport", "FederationReport", "extract_crossrefs",
    "collect_node", "cross_verify", "verify_federation", "render",
]
