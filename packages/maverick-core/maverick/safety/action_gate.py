"""Per-action approval gate for the computer-use and browser tools.

The computer and browser tools actuate real input -- clicks, keystrokes, form
fills -- that can submit a payment, send a message, or delete data. Tool-level
risk (``safety/tool_risk.py`` marks both ``high``) only decides whether the
tool is *registered*; it does not gate an individual click. This module gates
the *action*: a mutating actuation is routed through
:func:`maverick.safety.consent.require_consent` exactly the way the ``shell``
tool routes a command, so the existing approval queue, dashboard ``/approvals``
page, TTY prompt, and signed audit events all apply with no new machinery.

Only the explicit mutating actions are gated; observation actions (screenshot,
extract_text, cursor_position, scroll, ...) and unknown/typo actions are
no-ops. A mutating action defaults to ``medium`` risk; one whose target,
typed text, or key chord matches a high-impact verb (pay, submit, transfer,
delete, ...) escalates to ``high`` so the operator console and the audit trail
record *why* it was flagged.

Privacy: the high-risk classifier inspects typed *values* in memory, but the
audit ``detail`` records selectors/coordinates and value *lengths* only -- a
typed password or PII value must never land in the (potentially exported)
audit log. Click/key targets are recorded verbatim because they are the
operator-visible label that makes an approval meaningful.

Gating is opt-in by the same switch as every other consent gate: with the
default ``MAVERICK_CONSENT_MODE=auto-approve`` this is a logged no-op; ``ask``
/ ``dashboard`` (and enterprise mode, which flips the default to ``ask``) make
it bite. Kernel rule 1 holds -- disengaged, the gate never blocks.
"""
from __future__ import annotations

import re
from typing import Any

from .consent import ConsentDenied, require_consent

# Explicit allowlists of actuating (state-mutating) actions. Everything else --
# observation actions, ``close``, and any unknown/typo action -- is a no-op, so
# the gate can never accidentally block a read or an unrecognised verb.
_COMPUTER_MUTATING = frozenset({
    "left_click", "right_click", "middle_click", "double_click",
    "left_click_drag", "type", "key",
})
_BROWSER_MUTATING = frozenset({
    "navigate", "click", "type", "fill_form", "press",
})

# High-impact verbs/nouns. A mutating action whose visible target text matches
# escalates medium -> high. Word boundaries so "approve" hits but "approximate"
# does not. Over-flagging here is the safe direction: a false ``high`` only adds
# a label, while a missed ``high`` understates a real risk.
_HIGH_RISK = re.compile(
    r"\b(pay|payment|purchase|buy|checkout|order|submit|send|transfer|wire|"
    r"remit|withdraw|approve|confirm|authori[sz]e|sign|delete|destroy|remove|"
    r"drop|wipe|erase|deactivate|disable|terminate|publish|deploy|merge|"
    r"execute)\b",
    re.IGNORECASE,
)
# Key chords that typically commit a form / fire the default action.
_SUBMIT_KEYS = ("enter", "return")

_MAX_DETAIL = 200


def _short(text: str | None) -> str | None:
    """Collapse whitespace and bound length for an audit label."""
    if not text:
        return None
    out = " ".join(str(text).split())[:_MAX_DETAIL]
    return out or None


def _matches_high_risk(*texts: str | None, key: str | None = None) -> bool:
    if key and any(k in key.lower() for k in _SUBMIT_KEYS):
        return True
    return any(t and _HIGH_RISK.search(t) for t in texts)


def _require(name: str, risk: str, scope: str | None, detail: str | None) -> str | None:
    """Route through consent; return the tool ERROR string on denial, else None.

    ``name`` is built from the validated action enum (never free model text), so
    it is safe to reuse as ``provenance`` for the operator console label.
    """
    try:
        require_consent(
            name,
            risk=risk,
            scope=_short(scope),
            detail=_short(detail),
            provenance=name,
            raise_on_deny=True,
        )
    except ConsentDenied:
        return f"ERROR: {name} denied by approval gate (MAVERICK_CONSENT_MODE)"
    return None


def gate_computer_action(action: str, args: dict[str, Any]) -> str | None:
    """Gate one computer-use action.

    Returns an ``ERROR:`` string if the action is denied (for the tool to
    return verbatim), or ``None`` to proceed. A no-op for non-mutating actions.
    """
    if action not in _COMPUTER_MUTATING:
        return None
    text = args.get("text")
    coord = args.get("coordinate")
    high = _matches_high_risk(text, key=text if action == "key" else None)
    scope = f"{action} at {coord}" if coord else action
    # Value-bearing actions log a length, not the value (could be a secret).
    if action == "type":
        detail = f"type {len(str(text or ''))} chars"
    elif action == "key":
        detail = f"key {text}"  # a key chord ('ctrl+v', 'Return') is not secret
    else:
        detail = f"at {coord}" if coord else action
    return _require(f"computer.{action}", "high" if high else "medium", scope, detail)


def gate_browser_action(action: str, args: dict[str, Any]) -> str | None:
    """Gate one browser action.

    Returns an ``ERROR:`` string if the action is denied, or ``None`` to
    proceed. A no-op for non-mutating actions.
    """
    if action not in _BROWSER_MUTATING:
        return None
    selector = args.get("selector")
    text = args.get("text")
    url = args.get("url")
    raw_fields = args.get("fields")
    fields = raw_fields if isinstance(raw_fields, dict) else None
    # Scan selectors *and* values for the risk signal, but only ever log keys.
    field_keys = list(fields.keys()) if fields else []
    field_values = list(fields.values()) if fields else []
    key = text if action == "press" else None
    high = _matches_high_risk(
        selector, url, *(str(k) for k in field_keys),
        *(str(v) for v in field_values), key=key,
    )

    if action == "navigate":
        scope = detail = url or action
    elif action == "fill_form":
        scope = "fill_form"
        shown = ", ".join(str(k) for k in field_keys[:5])
        detail = f"fill {len(field_keys)} field(s): {shown}" if field_keys else "fill_form"
    elif action == "type":
        scope = selector or action
        detail = f"type {len(str(text or ''))} chars into {selector}"
    elif action == "press":
        scope = selector or "page"
        detail = f"press {text} on {selector or 'page'}"
    else:  # click -- the selector is the operator-visible target, safe to log
        scope = selector or action
        detail = f"click {selector}" if selector else action
    return _require(f"browser.{action}", "high" if high else "medium", scope, detail)


__all__ = ["gate_computer_action", "gate_browser_action"]
