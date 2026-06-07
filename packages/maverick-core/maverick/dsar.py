"""Data-subject access request (DSAR) export — GDPR Art. 15 / 20.

The erase side of GDPR (``maverick.audit.erase`` + ``maverick erase``) already
covers Art. 17 right-to-erasure. This module is its read-only mirror: the
right of access / portability. :func:`export_subject_data` gathers everything
Maverick holds for one subject (a channel ``user_id``) into a single
JSON-serializable bundle a controller can hand back to the data subject.

It only ever *reads*. Every store is consulted defensively: a missing or empty
world DB / audit dir yields an empty section, never an exception — an export
must not be the thing that crashes on a half-provisioned install.

Two stores are covered:

  - the **world model** (conversations + turns, and the goals/episodes those
    turns reference), read via the existing :class:`maverick.world_model.WorldModel`
    read APIs and tenant-resolved through
    :func:`maverick.world_model.world_for_tenant`;
  - the **audit log** NDJSON, scoped to rows whose structured ``channel`` /
    ``user_id`` fields identify the subject — the same exact-field rule the
    erase path (:func:`maverick.audit.erase._event_matches`) uses, so export
    and erase agree on what "this subject's data" means.

Isolation is the load-bearing property: this is subject data, so the bundle
must contain the requested subject's rows and *only* those. Matching is on
exact ``user_id`` equality (optionally narrowed to a channel); we never
substring-match a serialized value, which would leak co-tenants whose ids
share a prefix.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _iso(ts: Any) -> Any:
    """Best-effort epoch-seconds -> ISO-8601 UTC string.

    World-model timestamps are ``REAL`` epoch seconds; rendering them as ISO
    strings keeps the bundle human-readable and, more importantly, free of raw
    floats that a downstream consumer might misread as a different unit. A
    non-numeric value is returned untouched (already a string, or ``None``).
    """
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return ts
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):  # pragma: no cover - exotic ts
        return str(ts)


def _resolve_world(tenant: str | None) -> Any:
    """Open the tenant's ``WorldModel`` (or the default/shared one).

    ``world_for_tenant`` already maps ``tenant=None`` to the legacy shared
    ``~/.maverick/world.db`` and a tenant ``t`` to its isolated DB, resolving
    the active tenant from the environment / contextvar when not given — so we
    pass ``tenant`` straight through. Returns ``None`` (a fail-soft empty
    section) if the world cannot be opened at all.
    """
    try:
        from .world_model import world_for_tenant

        return world_for_tenant(tenant)
    except Exception as e:  # pragma: no cover - defensive (corrupt/locked DB)
        log.warning("dsar: could not open world model: %s", e)
        return None


def _matches_user(conv_user_id: str, user_id: str, channel: str | None) -> bool:
    """Whether a conversation belongs to the requested subject.

    Exact ``user_id`` equality only. This deliberately does NOT replicate the
    CLI's ``local:`` family-match (``--channel cli --user local`` ->
    ``local:<uuid>``); an exact rule cannot over-match and so cannot leak
    another subject's data, which is the priority for a DSAR. The CLI export
    remains the place that understands that local-chat convenience alias.
    """
    return conv_user_id == user_id


def _export_world(world: Any, user_id: str, channel: str | None) -> dict[str, Any]:
    """Collect the subject's conversations + turns and the goals they touch.

    Uses only existing read APIs: ``list_conversations`` to find the subject's
    threads, ``recent_turns`` for their content, and — because goals carry no
    per-user attribution of their own — the ``goal_id`` set referenced by those
    turns to pull each ``get_goal`` + its ``list_episodes``. A goal reachable
    only through a sibling subject's turn is therefore never included.
    """
    empty = {"conversations": [], "goals": []}
    if world is None:
        return empty

    # --- conversations + turns -------------------------------------------
    try:
        all_convs = world.list_conversations(channel)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("dsar: list_conversations failed: %s", e)
        return empty

    convs = [c for c in all_convs if _matches_user(c.user_id, user_id, channel)]

    conversations: list[dict[str, Any]] = []
    goal_ids: list[int] = []
    seen_goal_ids: set[int] = set()
    for c in convs:
        try:
            # limit high enough to capture full history; export must be complete.
            turns = world.recent_turns(c.id, limit=1_000_000)
        except Exception as e:  # pragma: no cover - defensive
            log.warning("dsar: recent_turns failed for conv %s: %s", c.id, e)
            turns = []
        turn_dicts: list[dict[str, Any]] = []
        for t in turns:
            turn_dicts.append(
                {
                    "id": t.id,
                    "role": t.role,
                    "content": t.content,
                    "ts": _iso(t.ts),
                    "goal_id": t.goal_id,
                }
            )
            if t.goal_id is not None and t.goal_id not in seen_goal_ids:
                seen_goal_ids.add(t.goal_id)
                goal_ids.append(t.goal_id)
        conversations.append(
            {
                "id": c.id,
                "channel": c.channel,
                "user_id": c.user_id,
                "created_at": _iso(c.created_at),
                "last_seen": _iso(c.last_seen),
                "turns": turn_dicts,
            }
        )

    # --- goals + episodes (only those the subject's turns reference) ------
    goals: list[dict[str, Any]] = []
    for gid in goal_ids:
        try:
            goal = world.get_goal(gid)
        except Exception as e:  # pragma: no cover - defensive
            log.warning("dsar: get_goal failed for %s: %s", gid, e)
            continue
        if goal is None:
            continue
        try:
            episodes = world.list_episodes(limit=1_000_000, goal_id=gid)
        except Exception as e:  # pragma: no cover - defensive
            log.warning("dsar: list_episodes failed for goal %s: %s", gid, e)
            episodes = []
        goals.append(
            {
                "id": goal.id,
                "parent_id": goal.parent_id,
                "title": goal.title,
                "description": goal.description,
                "status": goal.status,
                "created_at": _iso(goal.created_at),
                "updated_at": _iso(goal.updated_at),
                "deadline": _iso(goal.deadline),
                "result": goal.result,
                "episodes": [
                    {
                        "id": e.id,
                        "started_at": _iso(e.started_at),
                        "ended_at": _iso(e.ended_at),
                        "outcome": e.outcome,
                        "cost_dollars": e.cost_dollars,
                        "input_tokens": e.input_tokens,
                        "output_tokens": e.output_tokens,
                        "tool_calls": e.tool_calls,
                    }
                    for e in episodes
                ],
            }
        )

    return {"conversations": conversations, "goals": goals}


def _export_audit(user_id: str, channel: str | None, tenant: str | None) -> list[dict[str, Any]]:
    """Return the subject's audit rows from every day-file in the audit dir.

    The audit log has no per-subject reader, so we iterate the tenant's
    ``*.ndjson`` files directly and keep rows whose structured ``user_id`` (and,
    when supplied, ``channel``) fields match — exactly the rule
    :func:`maverick.audit.erase._event_matches` erases on, so a row that
    *would* be erased is a row that *is* exported. Each kept row is JSON-safe by
    construction (it was parsed from JSON); we round-trip with ``default=str``
    only to neutralise any value json can't emit. Fail-soft: a missing dir,
    unreadable file, or malformed line is skipped, never raised.
    """
    try:
        from .paths import data_dir

        audit_dir = data_dir("audit", tenant=tenant) if tenant else data_dir("audit")
    except Exception as e:  # pragma: no cover - defensive
        log.warning("dsar: could not resolve audit dir: %s", e)
        return []

    if not audit_dir.exists() or not audit_dir.is_dir():
        return []

    out: list[dict[str, Any]] = []
    try:
        files = sorted(audit_dir.glob("*.ndjson"))
    except OSError as e:  # pragma: no cover - defensive
        log.warning("dsar: could not list audit dir %s: %s", audit_dir, e)
        return []

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:  # pragma: no cover - defensive
            log.warning("dsar: could not read %s: %s", path, e)
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("user_id") != user_id:
                continue
            if channel is not None and event.get("channel") != channel:
                continue
            # Render ts to ISO for consistency with the world section; keep the
            # rest of the event verbatim so nothing the subject is owed is lost.
            if "ts" in event:
                event = {**event, "ts": _iso(event["ts"])}
            # Round-trip through json with default=str so any stray
            # non-serializable value (shouldn't happen for parsed JSON) is
            # stringified rather than poisoning the whole bundle.
            out.append(json.loads(json.dumps(event, default=str)))
    return out


def export_subject_data(user_id: str, *, tenant: str | None = None) -> dict[str, Any]:
    """Gather everything Maverick holds for ``user_id`` into one JSON bundle.

    GDPR Art. 15 (right of access) / Art. 20 (portability), and a SOC 2 Privacy
    expectation. Read-only and fail-soft: a missing world DB or audit dir
    produces an empty section rather than an error.

    ``user_id`` is the channel-scoped subject identifier (the same value the
    world model stores on ``conversations.user_id`` and that audit events carry
    as their ``user_id`` field). ``tenant`` selects the data plane: when given,
    the subject's world DB and audit chain are read from that tenant's isolated
    directory via :func:`maverick.world_model.world_for_tenant` /
    :func:`maverick.paths.data_dir`; when ``None`` the active tenant (env /
    contextvar) is used, falling back to the legacy shared store.

    The returned dict is guaranteed ``json.dumps``-able (timestamps are
    stringified to ISO-8601; no bytes leak through). Its shape::

        {
          "subject":      {"user_id": str, "channel": str | None},
          "tenant":       str | None,
          "generated_at": str,        # ISO-8601 UTC, when this export ran
          "world":        {"conversations": [...], "goals": [...]},
          "audit":        [ {...}, ... ],
          "counts":       {"conversations", "turns", "goals",
                           "episodes", "audit_events"},
        }
    """
    # Channel is not a separate argument: a DSAR is keyed on the subject id.
    # ``None`` means "this user_id across every channel"; callers wanting a
    # single channel can post-filter, and the audit/world matchers already
    # honour an explicit channel when one is threaded through. We keep it None
    # here so the export is complete by default.
    channel: str | None = None

    world = _resolve_world(tenant)
    world_section = _export_world(world, user_id, channel)
    audit_section = _export_audit(user_id, channel, tenant)

    turn_count = sum(len(c["turns"]) for c in world_section["conversations"])
    episode_count = sum(len(g["episodes"]) for g in world_section["goals"])

    return {
        "subject": {"user_id": user_id, "channel": channel},
        "tenant": tenant,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "world": world_section,
        "audit": audit_section,
        "counts": {
            "conversations": len(world_section["conversations"]),
            "turns": turn_count,
            "goals": len(world_section["goals"]),
            "episodes": episode_count,
            "audit_events": len(audit_section),
        },
    }


__all__ = ["export_subject_data"]
