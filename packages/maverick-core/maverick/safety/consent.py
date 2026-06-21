"""Consent prompts for destructive actions.

Tools that mutate user state (rm, force-push, mass-send, dd, mkfs)
call ``require_consent(action, risk_level)`` which:

  1. Checks the consent ledger -- a previously-granted consent for the
     same (action, scope) returns immediately.
  2. Checks ``MAVERICK_CONSENT_MODE`` env var:
        - "auto-approve" (default) -> grant + log (no friction out of the box)
        - "auto-deny"              -> deny + log
        - "ask"                    -> ask the user; in non-tty contexts, deny
        - "dashboard"              -> park in the approvals queue + poll
  3. Logs an audit event for prompt + result.

Threading: prompts serialize through a lock so two parallel agents
don't both pop a prompt simultaneously on the same TTY.

Note: this is the *primitive*. Tools wire it in themselves (the ``shell``
tool does). The base mode is ``auto-approve``, but under **secure-by-default**
**high-** and **critical-risk** actions fail closed to ``ask`` (routing to the
approvals queue / dashboard) instead of auto-approving; low/medium stay
non-interactive out of the box. An operator can widen or narrow this via
``MAVERICK_CONSENT_MODE`` (or per-action config), and ``[security]
secure_defaults = false`` / ``MAVERICK_SECURE_DEFAULT=0`` restores the old
fully-opt-in behavior.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass

from ..paths import data_dir

log = logging.getLogger(__name__)


CONSENT_LEDGER_PATH = data_dir("consent.ledger")


class ConsentDenied(Exception):
    """Raised when ``require_consent(..., raise_on_deny=True)`` is denied."""

    def __init__(self, action: str):
        super().__init__(f"consent denied for action: {action}")
        self.action = action


@dataclass(frozen=True)
class ConsentDecision:
    granted: bool
    source: str           # "ledger" | "auto" | "prompt" | "non-tty-deny"
    risk: str             # "low" | "medium" | "high" | "critical"
    ts: float


_prompt_lock = threading.Lock()


def _resolve_mode(risk: str | None = None) -> str:
    # Explicit operator setting always wins (any risk level).
    env = os.environ.get("MAVERICK_CONSENT_MODE")
    if env:
        return env.strip().lower()
    # Enterprise mode flips the default to 'ask' so destructive actions are gated
    # (and denied in non-interactive contexts) when handling sensitive data.
    try:
        from ..enterprise import enterprise_enabled
        if enterprise_enabled():
            return "ask"
    except Exception:
        pass
    # Secure-by-default: gate HIGH/CRITICAL-risk actions (an autonomous run can't
    # take a destructive action without an explicit decision -> 'ask', which
    # denies in a non-interactive context). Low/medium stay frictionless so
    # normal goals are unaffected. An explicit MAVERICK_CONSENT_MODE opts out.
    if str(risk or "").strip().lower() in ("high", "critical"):
        try:
            from ..security_defaults import secure_by_default
            if secure_by_default():
                return "ask"
        except Exception:
            pass
    return "auto-approve"


def _ledger_lines() -> list[str]:
    if not CONSENT_LEDGER_PATH.exists():
        return []
    try:
        return CONSENT_LEDGER_PATH.read_text().splitlines()
    except OSError:
        return []


def _append_ledger(line: str) -> None:
    try:
        CONSENT_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONSENT_LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        try:
            os.chmod(CONSENT_LEDGER_PATH, 0o600)
        except OSError:
            pass
    except OSError as e:
        log.warning("consent: cannot append to ledger: %s", e)


def _check_ledger(action: str, scope: str | None) -> bool:
    """True if a prior ``grant`` for ``(action, scope)`` is recorded."""
    key = f"grant\t{action}\t{scope or ''}"
    # Compare the stored record verbatim. ``_ledger_lines`` already stripped the
    # line terminator via splitlines(); a blanket .strip() here ate the trailing
    # TAB of a scope-less grant (``grant\taction\t``), so a scope-less
    # grant_persistent() never matched and was silently re-prompted forever.
    return any(line.split("|", 1)[-1] == key for line in _ledger_lines())


def grant_persistent(action: str, scope: str | None = None) -> None:
    """Record a forever-grant; subsequent require_consent() returns immediately.

    Use sparingly; the more we ledger, the less the prompts matter.
    """
    ts = time.time()
    _append_ledger(f"{ts}|grant\t{action}\t{scope or ''}")


def revoke(action: str, scope: str | None = None) -> bool:
    """Remove all matching grants. Returns True if anything was removed."""
    lines = _ledger_lines()
    if not lines:
        return False
    key = f"grant\t{action}\t{scope or ''}"
    kept = [line for line in lines if line.split("|", 1)[-1] != key]
    if len(kept) == len(lines):
        return False
    try:
        CONSENT_LEDGER_PATH.write_text("\n".join(kept) + "\n" if kept else "")
        os.chmod(CONSENT_LEDGER_PATH, 0o600)
        return True
    except OSError as e:
        log.warning("consent: cannot rewrite ledger: %s", e)
        return False


def list_grants() -> list[tuple[str, str]]:
    """Return [(action, scope), ...] of all current grants."""
    out: list[tuple[str, str]] = []
    for line in _ledger_lines():
        body = line.split("|", 1)[-1]
        parts = body.split("\t")
        if len(parts) >= 3 and parts[0] == "grant":
            out.append((parts[1], parts[2]))
    return out


def require_consent(
    action: str,
    *,
    risk: str = "medium",
    scope: str | None = None,
    detail: str | None = None,
    provenance: str | None = None,
    raise_on_deny: bool = False,
    allow_auto_approve: bool = True,
    consult_ledger: bool = True,
) -> ConsentDecision:
    """Gate a destructive action through user (or env) approval.

    ``action`` is a short identifier (e.g. "rm-rf", "force-push",
    "mass-dm"). ``scope`` is the resource being acted on (e.g.
    "/tmp/build", "main", "channel:#general"). ``detail`` is a
    human-readable description shown in the prompt. ``provenance`` is trusted
    caller-supplied metadata for dashboard labels; never derive it from
    user/model-controlled ``detail`` text.

    Returns a ConsentDecision. If ``raise_on_deny``, denials raise
    ConsentDenied instead.

    ``allow_auto_approve=False`` is for high-trust paths that require an
    explicit operator decision even though the consent primitive defaults to
    ``auto-approve`` for backwards compatibility. Ledger grants, dashboard
    approvals, and TTY prompts still work; silent auto-approval is treated as
    a denial.

    ``consult_ledger=False`` additionally disables the prior-grant fast-path, so
    a *fresh* decision is required even when a persistent grant for this
    ``(action, scope)`` exists. Used by the governance EU AI Act Art-14 gate
    when an operator opts into per-action human oversight
    (``[governance] require_fresh_human_approval``).
    """
    ts = time.time()
    # 1) Ledger fast-path (skipped when a fresh decision is demanded).
    if consult_ledger and _check_ledger(action, scope):
        return _emit(ConsentDecision(True, "ledger", risk, ts), action, scope, detail)
    # 2) Mode override (risk-aware: secure-by-default gates high/critical risk).
    mode = _resolve_mode(risk)
    if mode == "auto-approve":
        d = _emit(
            ConsentDecision(allow_auto_approve, "auto", risk, ts),
            action, scope, detail,
        )
        if not d.granted and raise_on_deny:
            raise ConsentDenied(action)
        return d
    if mode == "auto-deny":
        d = _emit(ConsentDecision(False, "auto", risk, ts), action, scope, detail)
        if raise_on_deny:
            raise ConsentDenied(action)
        return d
    if mode == "dashboard":
        d = _decide_via_dashboard(action, risk, scope, detail, provenance)
        if d is not None:
            d = _emit(d, action, scope, detail)
            if not d.granted and raise_on_deny:
                raise ConsentDenied(action)
            return d
        # Dashboard unavailable -> fall through to the interactive/non-tty
        # path below (fail-open: the kernel never *requires* the dashboard).
    # 3) Interactive prompt (or non-tty deny).
    if not sys.stdin.isatty():
        d = _emit(ConsentDecision(False, "non-tty-deny", risk, ts), action, scope, detail)
        if raise_on_deny:
            raise ConsentDenied(action)
        return d
    with _prompt_lock:
        msg = _format_prompt(action, risk, scope, detail)
        sys.stderr.write(msg)
        sys.stderr.flush()
        try:
            reply = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            reply = ""
    granted = reply in {"y", "yes"}
    d = _emit(ConsentDecision(granted, "prompt", risk, ts), action, scope, detail)
    if not granted and raise_on_deny:
        raise ConsentDenied(action)
    return d


def _dashboard_timeout() -> float:
    """How long (seconds) to wait for a dashboard approval before giving up.

    A timeout falls through to the interactive/non-tty path (fail-open),
    so a dashboard that's never opened doesn't wedge the agent forever.
    """
    try:
        return max(0.0, float(os.environ.get("MAVERICK_CONSENT_DASHBOARD_TIMEOUT", "300")))
    except ValueError:
        return 300.0


def _decide_via_dashboard(
    action: str,
    risk: str,
    scope: str | None,
    detail: str | None,
    provenance: str | None,
) -> ConsentDecision | None:
    """Park the action in the world model and poll for a dashboard decision.

    Returns a ConsentDecision once the operator approves/denies via the
    dashboard /approvals page, or ``None`` if the world model is
    unavailable or the wait times out -- the caller then falls back to
    the interactive/non-tty path (fail-open per the kernel contract).
    """
    try:
        from ..world_model import open_world
        wm = open_world()  # client/tenant-floored: the same DB the dashboard reads
    except Exception as e:  # world model missing/unwritable -> fail-open
        log.warning("consent: dashboard mode unavailable, falling back: %s", e)
        return None
    # Approval-delegation routing (opt-in via [governance.delegation] rules):
    # a risk/tool rule can route this approval to a specific delegate. No-op
    # (route returns None) when no rules are configured, so the default queue
    # behaviour is unchanged. The delegate is recorded in detail for the
    # operator console.
    try:
        from ..approval_delegation import route as _delegate_route
        delegate = _delegate_route({"risk": risk, "tool": action})
        if delegate:
            detail = f"{detail or ''}\n[delegated to: {delegate}]".strip()
    except Exception:  # pragma: no cover -- delegation never blocks consent
        pass
    try:
        approval_id = wm.create_approval(
            action, risk=risk, scope=scope, detail=detail, provenance=provenance,
        )
    except Exception as e:
        log.warning("consent: cannot queue approval, falling back: %s", e)
        return None

    # monotonic for the elapsed-time window: a wall-clock jump must not collapse
    # the human-approval window (timing out a risky-action prompt early) or
    # extend it (stalling the agent). The decision record below keeps wall time.
    deadline = time.monotonic() + _dashboard_timeout()
    while time.monotonic() < deadline:
        try:
            row = wm.get_approval(approval_id)
        except Exception:
            return None
        if row is not None and row.status != "pending":
            granted = row.status == "approved"
            return ConsentDecision(granted, "dashboard", risk, time.time())
        time.sleep(1.0)
    return None  # timed out: caller falls back


def _format_prompt(action: str, risk: str, scope: str | None, detail: str | None) -> str:
    risk_tag = {"low": "?", "medium": "!", "high": "!!", "critical": "!!!"}.get(risk, "?")
    parts = [
        f"\n[CONSENT {risk_tag}] {action}",
    ]
    if scope:
        parts.append(f"  scope: {scope}")
    if detail:
        parts.append(f"  detail: {detail}")
    parts.append("Allow? [y/N]: ")
    return "\n".join(parts)


def _emit(
    decision: ConsentDecision,
    action: str,
    scope: str | None,
    detail: str | None,
) -> ConsentDecision:
    """Log the consent decision to the audit log (fail-safe)."""
    try:
        from ..audit import EventKind, record
        record(
            EventKind.CONSENT_PROMPT,
            action=action, risk=decision.risk,
            scope=scope, detail=detail,
        )
        record(
            EventKind.CONSENT_RESULT,
            action=action,
            decision="approve" if decision.granted else "deny",
            source=decision.source,
        )
    except Exception:  # pragma: no cover -- never crash on audit
        pass
    return decision


__all__ = [
    "ConsentDecision",
    "ConsentDenied",
    "require_consent",
    "grant_persistent",
    "revoke",
    "list_grants",
]
