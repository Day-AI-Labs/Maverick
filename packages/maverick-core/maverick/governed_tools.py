"""Govern enterprise-connector WRITES in the live tool path (opt-in).

The enterprise REST connectors expose a service as a ``confirm=true``-gated tool
-- but the AGENT can set ``confirm`` itself, so a consequential write to a system
of record has no human in the loop. When ``[governed_connectors] enable`` is on,
this replaces each configured connector's tool with a wrapper that routes its
writes through :class:`~maverick.governed_actions.GovernedActions`: the write is
previewed (simulate, no side effect) and **approval-gated** against a standing
operator approver (``[governed_connectors] approver`` /
``MAVERICK_GOVERNED_APPROVER``) -- the agent cannot self-approve. Reads pass
through unchanged.

The governed ``apply`` reuses the ORIGINAL tool's write path (the same env auth +
SSRF-safe request), so wrapping never changes *where* a write goes -- only that
it must clear the approval gate first. Off by default (kernel rule 1): with the
feature disabled, the registry is untouched.

Connectors whose tool exposes an ``op`` plus ``confirm`` schema are wrapped,
including the ``make_rest_tool`` family and bespoke Salesforce/ServiceNow
connectors. The wrapper derives a stable resource label from ``path`` when
available, or from connector-specific record identifiers for bespoke tools.
"""
from __future__ import annotations

import logging
import os

from .tools import Tool

log = logging.getLogger(__name__)

_WRITE_OPS = (
    "post", "put", "patch", "delete",
    "record_create", "record_update", "record_delete",
    "create", "update",
)


def _approver() -> str:
    """The standing approver of record for governed connector writes."""
    a = os.environ.get("MAVERICK_GOVERNED_APPROVER", "").strip()
    if a:
        return a
    try:
        from .config import get_governed_connectors
        return str(get_governed_connectors().get("approver", "")).strip()
    except Exception:  # pragma: no cover -- config must never break tool assembly
        return ""


def _is_governable_op_tool(tool: Tool) -> bool:
    """Whether ``tool`` speaks an op/confirm schema we can govern.

    ``make_rest_tool`` connectors include ``path``; Salesforce and ServiceNow
    use bespoke record identifiers. In all cases, governance can safely force
    ``confirm=True`` only after approval because the original tool keeps full
    responsibility for validating and applying the requested write.
    """
    props = (tool.input_schema or {}).get("properties", {})
    return isinstance(props, dict) and "op" in props and "confirm" in props


def _resource_label(tool_name: str, args: dict) -> str:
    """Return a stable, non-secret label for the governed write preview."""
    path = str(args.get("path") or "").strip()
    if path:
        return path
    if tool_name == "salesforce":
        sobject = str(args.get("sobject") or "").strip()
        rid = str(args.get("id") or "").strip()
        return "/".join(part for part in ("sobjects", sobject, rid) if part)
    if tool_name == "servicenow":
        table = str(args.get("table") or "").strip()
        sys_id = str(args.get("sys_id") or "").strip()
        return "/".join(part for part in ("table", table, sys_id) if part)
    return str(args.get("op") or "write")


def wrap_connector_tool(tool: Tool) -> Tool:
    """Return a Tool whose WRITES are previewed + approval-gated via
    GovernedActions; reads pass through. The original write is the governed
    ``apply``, so the request path is unchanged."""
    from .governed_actions import ActionError, ActionSpec, GovernedActions

    def _fn(args: dict) -> str:
        op = str(args.get("op", "")).strip().lower()
        if op not in _WRITE_OPS:
            return tool.fn(args)
        approver = _approver()
        path = _resource_label(tool.name, args)
        ga = GovernedActions()
        action = f"{tool.name}.write"
        ga.register(ActionSpec(
            name=action, params={"op": str, "path": str}, risk="high",
            simulate=lambda p: f"would {p['op'].upper()} {tool.name} {p['path']}".rstrip(),
            # apply reuses the connector's own write path (confirm satisfied).
            apply=lambda p, a=dict(args): tool.fn({**a, "confirm": True}),
        ))
        params = {"op": op, "path": path}
        try:
            preview = ga.simulate(action, params)
            if preview.requires_approval and not approver:
                return (
                    f"REFUSED (governed): {preview.effect}. A governed write needs an "
                    "approver of record; the agent cannot self-approve. Set "
                    "[governed_connectors] approver or MAVERICK_GOVERNED_APPROVER.")
            return ga.commit(action, params, approver=approver,
                             sources=(f"tool:{tool.name}",))
        except ActionError as e:
            return f"ERROR (governed): {e}"

    note = " [governed: writes previewed + approval-gated by an operator approver]"
    return Tool(name=tool.name, description=(tool.description + note)[:1024],
                input_schema=tool.input_schema, fn=_fn)


def governance_enabled() -> bool:
    """Whether the live tool path governs connector writes. Off by default;
    ``[governed_connectors] enable`` / ``MAVERICK_GOVERNED_CONNECTORS`` turns it on."""
    try:
        from .config import env_flag, get_governed_connectors
        ov = env_flag("MAVERICK_GOVERNED_CONNECTORS")
        if ov is not None:
            return ov
        return bool(get_governed_connectors().get("enable", False))
    except Exception:  # pragma: no cover
        return False


def apply_governed_connectors(reg) -> list[str]:
    """Replace each configured connector's tool with a governed wrapper when the
    feature is on. Returns the wrapped names. Fail-open no-op when disabled,
    unconfigured, or on any error -- never breaks tool assembly."""
    if not governance_enabled():
        return []
    try:
        from .config import get_governed_connectors
        names = get_governed_connectors().get("connectors", [])
    except Exception:  # pragma: no cover
        return []
    wrapped: list[str] = []
    for name in names:
        try:
            tool = reg.get(name)
        except Exception:  # noqa: BLE001 -- unknown/ACL'd name: skip
            continue
        if not _is_governable_op_tool(tool):
            log.info("governed_connectors: %s is not an op/confirm tool; left ungoverned", name)
            continue
        reg.register(wrap_connector_tool(tool))
        wrapped.append(name)
    return wrapped


__all__ = ["wrap_connector_tool", "apply_governed_connectors", "governance_enabled"]
