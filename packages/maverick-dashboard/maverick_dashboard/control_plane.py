"""View-models for the agent control-plane dashboard pages.

Two read-only surfaces over primitives that already exist in the kernel:

* :func:`build_replay` -- reconstructs a run's action timeline from the signed
  audit log (:func:`maverick.audit.iter_events`), classifies each event, and
  reports whether the tamper-evident hash chain covering the run verifies
  (:func:`maverick.audit.verify_chain`). This is the "flight recorder" view, and
  :func:`evidence_packet` wraps it into a one-click, exportable evidence bundle.
* :func:`trust_overview` -- enumerates the configured external agents from the
  Agent Trust Plane (:func:`maverick.agent_trust.load_trust_state`) with their
  tool/risk/budget ceilings and lifecycle status: the cross-agent permission
  graph.

Both are pure reads; neither mutates state. Everything degrades fail-soft -- a
missing audit dir, an unreadable day-file, or an absent trust registry yields an
empty/neutral view rather than an error, so the pages never 500 on a fresh box.
"""
from __future__ import annotations

import datetime
import math
from typing import Any

# ---- replay / flight recorder ----------------------------------------------

# Audit kinds the operator should see on a run timeline, mapped to a friendly
# label and a coarse "lane" used for styling/grouping. Kinds not listed still
# render (with their raw kind as the label) unless they are in _SKIP_KINDS.
_KIND_LABELS: dict[str, tuple[str, str]] = {
    "goal_start": ("Run started", "lifecycle"),
    "goal_end": ("Run ended", "lifecycle"),
    "tool_call": ("Tool call", "action"),
    "tool_result": ("Tool result", "action"),
    "token_exchange": ("Capability token minted", "capability"),
    "consent_prompt": ("Approval requested", "approval"),
    "consent_result": ("Approval decision", "approval"),
    "autonomy_gated": ("Autonomy gated", "approval"),
    "autonomy_escalated": ("Autonomy escalated", "approval"),
    "shield_block": ("Shield blocked", "block"),
    "capability_denied": ("Capability denied", "block"),
    "governance_denied": ("Governance denied", "block"),
    "egress_blocked": ("Egress blocked", "block"),
    "agent_trust_denied": ("Agent-trust denied", "block"),
    "memory_guard": ("Memory guard", "block"),
    "secret_redacted": ("Secret redacted", "redaction"),
    "evidence_capture": ("Evidence captured", "evidence"),
    "config_remediated": ("Config remediated", "lifecycle"),
    "halt": ("Killswitch halt", "block"),
}
# Lifecycle noise an operator does not need on a review timeline.
_SKIP_KINDS = frozenset({"episode_start", "episode_end"})
# Kinds that represent a governance *block* (for the run summary counters).
_BLOCK_KINDS = frozenset({
    "shield_block", "capability_denied", "governance_denied", "egress_blocked",
    "agent_trust_denied", "memory_guard", "halt",
})
_MAX_WINDOW_DAYS = 32


def _utc(ts: float | None) -> datetime.datetime | None:
    if ts is None:
        return None
    try:
        return datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _fmt_time(ts: float | None) -> str:
    d = _utc(ts)
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else ""


def _day_of(ts: float | None) -> str | None:
    d = _utc(ts)
    return d.date().isoformat() if d else None


def _window_days(window: tuple[float, float] | None) -> list[str]:
    """Distinct UTC day strings spanned by ``(start_ts, end_ts)`` (capped)."""
    if not window:
        return []
    start = _utc(window[0])
    end = _utc(window[1] or window[0])
    if start is None:
        return []
    if end is None or end < start:
        end = start
    days: list[str] = []
    d = start.date()
    last = end.date()
    while d <= last and len(days) < _MAX_WINDOW_DAYS:
        days.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return days


def _summarize(ev: dict[str, Any]) -> str:
    """A short, privacy-safe operator label for one event."""
    kind = ev.get("kind")
    if kind in ("tool_call", "tool_result"):
        name = ev.get("name") or ev.get("tool") or "?"
        extra = ev.get("status") or ev.get("input_summary") or ev.get("output_summary") or ""
        return f"{name} {extra}".strip()
    if kind == "consent_prompt":
        return f"{ev.get('action', '?')} ({ev.get('scope') or 'n/a'})"
    if kind == "consent_result":
        who = ev.get("source") or "?"
        return f"{ev.get('action') or ''} -> {ev.get('decision', '?')} [{who}]".strip()
    if kind == "shield_block":
        return f"{ev.get('stage', '')}: {ev.get('reason', '')}".strip(": ")
    if kind in ("capability_denied", "governance_denied"):
        return ev.get("reason") or ev.get("tool") or ev.get("rule") or ""
    if kind == "agent_trust_denied":
        return f"{ev.get('peer', '?')} {ev.get('direction', '')}: {ev.get('reason', '')}".strip()
    if kind == "egress_blocked":
        return ev.get("host") or ev.get("provider") or ev.get("reason") or "egress denied"
    if kind == "evidence_capture":
        sha = str(ev.get("sha256", ""))[:12]
        return f"{ev.get('phase', '')} {ev.get('action', '')} · {ev.get('file', '')} (sha256 {sha})".strip()
    if kind == "secret_redacted":
        return "secret value redacted before it reached disk"
    if kind in ("goal_start", "goal_end"):
        return ev.get("title") or ev.get("status") or ev.get("result") or ""
    skip = {"v", "ts", "kind", "agent", "goal_id"}
    return ", ".join(f"{k}={v}" for k, v in ev.items() if k not in skip)[:200]


def _entry(ev: dict[str, Any]) -> dict[str, Any]:
    kind = str(ev.get("kind") or "")
    label, lane = _KIND_LABELS.get(kind, (kind or "event", "other"))
    return {
        "ts": ev.get("ts"),
        "time": _fmt_time(ev.get("ts")),
        "kind": kind,
        "label": label,
        "lane": lane,
        "summary": _summarize(ev),
        "risk": ev.get("risk"),
        "decision": ev.get("decision"),
        "agent": ev.get("agent") or "system",
    }


def _verify_days(days: list[str]) -> dict[str, Any]:
    """Verify the signed hash chain for each day-file the run touched.

    Mirrors ``maverick audit verify``: a clean signed chain is ``verified``; any
    structural/signature break is ``broken``; a chain that was simply never
    signed (every row flagged ``unsigned``) reports ``unsigned`` (not tamper);
    no day-file present is ``no_log``.
    """
    from maverick.audit import verify_chain
    from maverick.paths import data_dir

    audit_dir = data_dir("audit")
    real_breaks: list[Any] = []
    unsigned = 0
    present: list[str] = []
    for d in days:
        path = audit_dir / f"{d}.ndjson"
        if not path.exists():
            continue
        present.append(d)
        try:
            breaks = verify_chain(path)
        except Exception:  # unreadable/locked -- treat as a break, never crash
            real_breaks.append(type("B", (), {"line_no": 0, "reason": "unreadable", "detail": d})())
            continue
        for b in breaks:
            if getattr(b, "reason", "") == "unsigned":
                unsigned += 1
            else:
                real_breaks.append(b)

    if not present:
        return {"status": "no_log", "break_count": 0, "days": [], "signed": False, "breaks": []}
    if real_breaks:
        return {
            "status": "broken",
            "break_count": len(real_breaks),
            "days": present,
            "signed": True,
            "breaks": [
                {"line": getattr(b, "line_no", 0), "reason": getattr(b, "reason", "?"),
                 "detail": getattr(b, "detail", "")}
                for b in real_breaks[:50]
            ],
        }
    if unsigned:
        return {"status": "unsigned", "break_count": 0, "days": present, "signed": False, "breaks": []}
    return {"status": "verified", "break_count": 0, "days": present, "signed": True, "breaks": []}


def build_replay(goal_id: int, *, window: tuple[float, float] | None = None) -> dict[str, Any]:
    """Reconstruct a run's signed-audit timeline + chain-verification status."""
    from maverick.audit import iter_events

    days = _window_days(window)
    raw: list[dict[str, Any]] = []
    if days:
        for d in days:
            try:
                raw.extend(e for e in iter_events(day=d) if e.get("goal_id") == goal_id)
            except Exception:
                continue
    else:
        try:
            raw.extend(e for e in iter_events(all_days=True) if e.get("goal_id") == goal_id)
        except Exception:
            raw = []
        days = sorted({d for e in raw if (d := _day_of(e.get("ts")))})

    raw.sort(key=lambda e: e.get("ts") or 0.0)
    entries = [_entry(e) for e in raw if e.get("kind") not in _SKIP_KINDS]

    summary = {
        "total": len(entries),
        "tool_calls": sum(1 for e in raw if e.get("kind") == "tool_call"),
        "approvals": sum(1 for e in raw if e.get("kind") == "consent_prompt"),
        "approved": sum(1 for e in raw if e.get("kind") == "consent_result"
                        and e.get("decision") == "approve"),
        "denied": sum(1 for e in raw if e.get("kind") == "consent_result"
                      and e.get("decision") == "deny"),
        "blocks": sum(1 for e in raw if e.get("kind") in _BLOCK_KINDS),
    }
    return {"entries": entries, "chain": _verify_days(days), "summary": summary}


def _version() -> str:
    try:
        from maverick import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def evidence_packet(goal: Any, replay: dict[str, Any]) -> dict[str, Any]:
    """A self-contained, exportable evidence bundle for one run.

    JSON-serializable: goal identity, the chain-verification verdict, the run
    summary counters, and the full classified timeline. This is the artifact a
    CISO / auditor downloads -- it stands alone without the dashboard.
    """
    return {
        "artifact": "maverick.run_evidence",
        "maverick_version": _version(),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "goal": {
            "id": getattr(goal, "id", None),
            "title": getattr(goal, "title", ""),
            "status": getattr(goal, "status", ""),
            "owner": getattr(goal, "owner", ""),
            "created_at": getattr(goal, "created_at", None),
            "updated_at": getattr(goal, "updated_at", None),
        },
        "chain": replay["chain"],
        "summary": replay["summary"],
        "timeline": replay["entries"],
    }


# ---- agent trust plane / permission graph ----------------------------------

def _trust_graph(
    agents: list[dict[str, Any]], *, width: int = 760, height: int = 360,
) -> dict[str, Any]:
    """Radial layout for the permission graph: this deployment at the centre,
    each external agent on a ring, edges directed by who may initiate.

    Colour encodes posture: red = revoked/expired, amber = high tool-risk
    ceiling, blue = active and bounded. Pure geometry so it is unit-testable.
    """
    cx, cy = width / 2, height / 2
    radius = min(width, height) / 2 - 70
    n = len(agents)
    nodes: list[dict[str, Any]] = []
    for i, a in enumerate(agents):
        angle = (2 * math.pi * i / n - math.pi / 2) if n else 0.0
        if a["revoked"] or not a["active"]:
            color = "#dc2626"
        elif a["max_risk"] == "high":
            color = "#d97706"
        else:
            color = "#2563eb"
        direction = a["direction"]
        nodes.append({
            "id": a["id"],
            "x": round(cx + radius * math.cos(angle), 1),
            "y": round(cy + radius * math.sin(angle), 1),
            "color": color,
            "inbound": direction in ("inbound", "both"),
            "outbound": direction in ("outbound", "both"),
        })
    return {"width": width, "height": height, "cx": cx, "cy": cy, "nodes": nodes}


def trust_overview() -> dict[str, Any]:
    """Enumerate configured external agents with their ceilings + lifecycle.

    Reads the Agent Trust Plane registry. Fail-soft: an unconfigured/unreadable
    registry yields ``enforced=False`` and an empty list, so the page renders an
    empty-state rather than erroring on a fresh deployment.
    """
    try:
        from maverick.agent_trust import load_trust_state
        enforced, registry = load_trust_state()
    except Exception:
        return {"enforced": False, "agents": [], "available": False}

    agents: list[dict[str, Any]] = []
    for _id, a in sorted(registry.items()):
        try:
            active, reason = a.is_active()
        except Exception:
            active, reason = True, "active"
        agents.append({
            "id": getattr(a, "id", _id),
            "direction": getattr(a, "direction", "both"),
            "allow_tools": sorted(a.allow_tools) if getattr(a, "allow_tools", None) else ["*"],
            "deny_tools": sorted(getattr(a, "deny_tools", []) or []),
            "max_risk": getattr(a, "max_risk", None) or "unbounded",
            "max_dollars": getattr(a, "max_dollars", None),
            "max_wall_seconds": getattr(a, "max_wall_seconds", None),
            "data_scopes": sorted(getattr(a, "data_scopes", []) or []),
            "active": bool(active),
            "status": reason,
            "expires_at": getattr(a, "expires_at", None),
            "revoked": bool(getattr(a, "revoked", False)),
        })
    return {
        "enforced": bool(enforced),
        "agents": agents,
        "available": True,
        "graph": _trust_graph(agents),
    }


# ---- discovery (what this deployment exposes) ------------------------------

def _discover_tools() -> dict[str, Any]:
    try:
        from maverick.safety.tool_risk import risk_map
        from maverick.tools import CORE_TOOL_NAMES
        names = sorted(CORE_TOOL_NAMES)
        risks = risk_map(names)
        # key is "entries" not "items": dict.items is a method, and Jinja
        # attribute access (discovery.tools.items) would resolve the method.
        entries = [{"name": n, "risk": risks.get(n, "medium")} for n in names]
        by_tier = {"high": 0, "medium": 0, "low": 0}
        for it in entries:
            by_tier[it["risk"]] = by_tier.get(it["risk"], 0) + 1
        return {"entries": entries, "by_tier": by_tier, "count": len(entries)}
    except Exception:
        return {"entries": [], "by_tier": {}, "count": 0}


def _discover_mcp() -> list[dict[str, Any]]:
    try:
        from maverick.mcp_registry import load_mcp_registry
        out = []
        for e in load_mcp_registry():
            spec = getattr(e, "spec", None)
            pin = (getattr(spec, "pin_sha256", None) if spec else None) or ""
            out.append({
                "name": getattr(e, "name", "?"),
                "command": getattr(spec, "command", "") if spec else "",
                "pin_sha256": pin,
                "pinned": bool(pin),
            })
        return out
    except Exception:
        return []


def _discover_providers() -> list[str]:
    try:
        from maverick.config import load_config
        cfg = load_config() or {}
        return sorted((cfg.get("providers") or {}).keys())
    except Exception:
        return []


def _discover_channels() -> list[str]:
    try:
        from maverick.plugins import discover_channels
        return sorted(name for name, _ in discover_channels())
    except Exception:
        return []


def discovery_overview() -> dict[str, Any]:
    """Inventory the governable surfaces this deployment exposes: tools (by
    risk), MCP servers (with supply-chain pins), configured LLM providers (names
    only, never keys), channels, and external agents. Fail-soft per section so a
    missing optional registry yields an empty list, never a 500."""
    agents = trust_overview()
    return {
        "tools": _discover_tools(),
        "mcp_servers": _discover_mcp(),
        "providers": _discover_providers(),
        "channels": _discover_channels(),
        "agents": {"enforced": agents["enforced"], "count": len(agents["agents"])},
    }


# ---- pre-action simulation (dry-run, no execution) -------------------------

def _consent_mode() -> str:
    try:
        from maverick.safety.consent import _resolve_mode
        return _resolve_mode()
    except Exception:
        return "auto-approve"


def simulate_action(surface: str, action: str, target: str = "") -> dict[str, Any]:
    """Classify a proposed action's risk and report whether it WOULD be gated,
    without executing anything -- the 'why allowed / why blocked' preview."""
    surface = (surface or "").strip().lower()
    action = (action or "").strip()
    mode = _consent_mode()

    if surface == "computer":
        from maverick.safety.action_gate import computer_action_risk
        risk = computer_action_risk(action, {"text": target, "coordinate": [0, 0]})
    elif surface == "browser":
        from maverick.safety.action_gate import browser_action_risk
        risk = browser_action_risk(action, {"selector": target, "url": target})
    elif surface == "tool":
        from maverick.safety.tool_risk import tool_risk
        risk = tool_risk(action) if action else None
    elif surface:
        return {"error": f"unknown surface {surface!r}; use computer | browser | tool"}
    else:
        return {}

    if surface in ("computer", "browser"):
        if risk is None:
            decision, why = "not gated", "read-only / non-mutating action runs freely"
        elif mode == "auto-deny":
            decision, why = "DENY", f"consent mode '{mode}': gated and denied"
        elif mode in ("ask", "dashboard"):
            decision, why = "REQUIRES APPROVAL", f"consent mode '{mode}': routed to a human ({risk} risk)"
        else:
            decision, why = "allow (logged)", f"consent mode '{mode}': gated but auto-granted ({risk} risk)"
    else:  # tool
        if risk is None:
            decision, why = "unknown tool", "no built-in or configured risk classification"
        else:
            decision = "exposed"
            why = f"tool risk '{risk}': dropped from the registry under a max_risk ceiling below it"
    return {
        "surface": surface, "action": action, "target": target,
        "risk": risk or "n/a", "consent_mode": mode, "decision": decision, "why": why,
    }


# ---- deployment compliance packet ------------------------------------------

def _recent_audit_chain(days_back: int = 7) -> dict[str, Any]:
    today = datetime.datetime.now(datetime.timezone.utc).date()
    days = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days_back)]
    return _verify_days(days)


def compliance_packet() -> dict[str, Any]:
    """One-click compliance evidence bundle: the SOC 2 control snapshot, the
    GDPR / EU AI Act control report, and the audit-chain verdict over the recent
    window -- assembled into a single downloadable JSON artifact. Fail-soft."""
    packet: dict[str, Any] = {
        "artifact": "maverick.compliance_packet",
        "maverick_version": _version(),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    try:
        from maverick.soc2 import collect_soc2_evidence
        packet["soc2"] = collect_soc2_evidence()
    except Exception as e:  # noqa: BLE001 -- evidence is fail-soft
        packet["soc2"] = {"error": str(e)}
    try:
        from dataclasses import asdict

        from maverick.compliance import compliance_report
        packet["controls"] = [asdict(c) for c in compliance_report()]
    except Exception as e:  # noqa: BLE001
        packet["controls"] = {"error": str(e)}
    packet["audit_chain"] = _recent_audit_chain()
    return packet


__all__ = [
    "build_replay",
    "evidence_packet",
    "trust_overview",
    "discovery_overview",
    "simulate_action",
    "compliance_packet",
]
