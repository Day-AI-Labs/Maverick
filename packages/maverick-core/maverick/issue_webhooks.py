"""Linear + Jira inbound triggers — assign an issue to the bot, get a goal.

Mirrors ``github_app.py`` (label an issue, get a PR) for the two other
trackers Maverick already has read/write tools for (``tools/linear.py``,
``tools/jira.py``). When a Linear or Jira issue is *assigned to the bot*,
the receiver creates a Maverick goal from the issue title + body.

Two pure pieces, kept transport-free so they unit-test without a server
(the FastAPI routes live in ``maverick_dashboard.app`` next to
``/webhook/start`` and just call into here):

  - ``verify_signature(body, header, secret)`` — HMAC-SHA256 over the raw
    body. Linear sends a bare hex digest in ``Linear-Signature``; Jira
    automation/Connect senders commonly use a ``sha256=`` prefix. Accept
    both. Empty secret fails CLOSED (unlike github_app's dev fail-open):
    these receivers are mounted on the public dashboard app.
  - ``parse_issue_event(provider, payload)`` — normalize a Linear/Jira
    webhook into an ``IssueEvent`` IFF it is an assignment whose assignee
    is the configured bot. Returns ``None`` for anything else (non-assign
    events, assigned-to-someone-else) so the caller no-ops.

Who is "the bot": set ``MAVERICK_BOT_LINEAR_ID`` (Linear user id) and/or
``MAVERICK_BOT_JIRA_ACCOUNT_ID`` (Jira accountId, or the bot's email).
Matching is case-insensitive and also accepts the assignee's email so an
operator can configure either. With no bot id configured the receiver
fails closed: a signed tracker event alone must not be enough to trigger
Maverick unless the assignee matches an explicitly configured bot.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class IssueEvent:
    """Normalized issue-assigned event from Linear or Jira."""
    provider: str        # "linear" | "jira"
    issue_id: str        # "ENG-123" (Linear identifier) / "PROJ-7" (Jira key)
    title: str
    body: str
    assignee: str        # id/email the issue was assigned to (for logging)


def canonical_signature(signature_header: str | None) -> str | None:
    """Return the canonical HMAC digest accepted by ``verify_signature``.

    Linear sends a bare hex digest and Jira senders commonly prefix the same
    digest with ``sha256=``. Normalize those equivalent wire forms to the
    digest that is actually compared so replay-dedup keys match verification.
    """
    if not signature_header:
        return None
    sig = signature_header.strip()
    if sig.startswith("sha256="):
        sig = sig[len("sha256="):]
    return sig


def verify_signature(
    body: bytes,
    signature_header: str | None,
    secret: str | None,
) -> bool:
    """HMAC-SHA256 verification of a Linear/Jira webhook signature.

    Linear's ``Linear-Signature`` is a bare hex digest; Jira automation /
    Connect senders typically prefix ``sha256=``. Accept either. Fails
    CLOSED when no secret is configured — these routes hang off the public
    dashboard app, so an unsigned request must be rejected, not accepted.
    """
    if not secret:
        return False
    sig = canonical_signature(signature_header)
    if not sig:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


def replay_window_seconds() -> int:
    """Anti-replay freshness window (seconds).

    Shares the ``[webhooks] max_age_seconds`` knob (env
    ``MAVERICK_WEBHOOK_MAX_AGE_SECONDS``) with the Maverick-signed
    ``/webhook/start`` path so operators tune one window. Defaults to 300s.
    """
    try:
        from .webhooks import _default_max_age
        return _default_max_age()
    except Exception:  # pragma: no cover - webhooks helper unavailable
        return 300


def event_timestamp_ms(provider: str, payload: dict) -> float | None:
    """The sender's authenticated event time in ms-epoch, or ``None``.

    Linear carries ``webhookTimestamp`` and Jira ``timestamp`` at the top level
    of the body. The body is HMAC-signed, so neither field can be altered or
    stripped from a captured event without breaking the signature -- which makes
    them a trustworthy basis for a freshness (anti-replay) check.
    """
    raw = payload.get("webhookTimestamp" if provider == "linear" else "timestamp")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def is_fresh(
    provider: str,
    payload: dict,
    *,
    now: float | None = None,
    max_age_seconds: int | None = None,
) -> bool:
    """True if the event's signed timestamp is within the replay window.

    Fails CLOSED: a payload with no (or unparseable) timestamp is treated as
    NOT fresh. Real Linear/Jira events always carry one, and a replayer can't
    add or alter it without breaking the body HMAC, so the only events this
    rejects are stale captures (replays) and far-future / clock-skew stamps.
    """
    ts_ms = event_timestamp_ms(provider, payload)
    if ts_ms is None:
        return False
    # Linear/Jira send milliseconds; tolerate a seconds-valued stamp too.
    ts_sec = ts_ms / 1000.0 if ts_ms > 1e11 else ts_ms
    window = replay_window_seconds() if max_age_seconds is None else max_age_seconds
    now = time.time() if now is None else now
    return abs(now - ts_sec) <= window


def _bot_id(provider: str) -> str:
    env = (
        "MAVERICK_BOT_LINEAR_ID" if provider == "linear"
        else "MAVERICK_BOT_JIRA_ACCOUNT_ID"
    )
    return os.environ.get(env, "").strip().lower()


def _is_bot(assignee_candidates: list[str], provider: str) -> bool:
    """True if the issue is assigned to the explicitly configured bot."""
    candidates = {c.strip().lower() for c in assignee_candidates if c and c.strip()}
    if not candidates:
        return False
    bot = _bot_id(provider)
    if not bot:
        log.warning(
            "no bot id configured for %s inbound webhook (set %s); "
            "ignoring assignment",
            provider,
            "MAVERICK_BOT_LINEAR_ID" if provider == "linear"
            else "MAVERICK_BOT_JIRA_ACCOUNT_ID",
        )
        return False
    return bot in candidates


def _parse_linear(payload: dict) -> IssueEvent | None:
    # Linear fires {type, action, data}. Issue assignment is a
    # type=="Issue" update carrying an assignee object/id on data.
    if payload.get("type") != "Issue":
        return None
    if payload.get("action") not in ("create", "update"):
        return None
    data = payload.get("data") or {}
    assignee = data.get("assignee") or {}
    candidates = [
        str(data.get("assigneeId") or ""),
        str(assignee.get("id") or ""),
        str(assignee.get("email") or ""),
    ]
    if not _is_bot(candidates, "linear"):
        return None
    return IssueEvent(
        provider="linear",
        issue_id=str(data.get("identifier") or data.get("id") or ""),
        title=str(data.get("title") or ""),
        body=str(data.get("description") or ""),
        assignee=next((c for c in candidates if c), ""),
    )


def _flatten_adf(desc) -> str:
    """Flatten a Jira ADF description to text (mirror tools/jira._get)."""
    if isinstance(desc, str):
        return desc
    if not isinstance(desc, dict):
        return ""
    out = ""
    for block in desc.get("content") or []:
        for run in block.get("content") or []:
            if run.get("type") == "text":
                out += run.get("text", "")
        out += "\n"
    return out


def _parse_jira(payload: dict) -> IssueEvent | None:
    # Jira fires {webhookEvent, issue:{key, fields}}. An assignment is an
    # issue_updated whose fields.assignee is the bot.
    if payload.get("webhookEvent") not in (
        "jira:issue_updated", "jira:issue_created",
    ):
        return None
    issue = payload.get("issue") or {}
    fields = issue.get("fields") or {}
    assignee = fields.get("assignee") or {}
    candidates = [
        str(assignee.get("accountId") or ""),
        str(assignee.get("emailAddress") or ""),
    ]
    if not _is_bot(candidates, "jira"):
        return None
    return IssueEvent(
        provider="jira",
        issue_id=str(issue.get("key") or ""),
        title=str(fields.get("summary") or ""),
        body=_flatten_adf(fields.get("description")),
        assignee=next((c for c in candidates if c), ""),
    )


def parse_issue_event(provider: str, payload: dict) -> IssueEvent | None:
    """Normalize a Linear/Jira webhook to an ``IssueEvent``.

    Returns ``None`` for events we don't act on: non-assignment events,
    or an assignment to someone other than the configured bot.
    """
    if provider == "linear":
        return _parse_linear(payload)
    if provider == "jira":
        return _parse_jira(payload)
    return None


def build_brief(event: IssueEvent) -> str:
    """Render the assigned issue into a Maverick goal brief."""
    return (
        f"{event.provider.title()} issue: {event.issue_id}\n"
        f"Title: {event.title}\n\n"
        f"Issue body:\n{event.body}\n\n"
        "This issue was assigned to Maverick. Implement a minimal fix or "
        "feature satisfying it."
    )


__all__ = [
    "IssueEvent",
    "verify_signature",
    "parse_issue_event",
    "build_brief",
    "is_fresh",
    "event_timestamp_ms",
    "replay_window_seconds",
]
