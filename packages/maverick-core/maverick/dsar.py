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
    """Open the selected tenant's ``WorldModel``.

    ``world_for_tenant(None)`` deliberately forces the legacy shared
    ``~/.maverick/world.db``. A DSAR export with no explicit tenant, however,
    should follow the active tenant (environment / contextvar) just like audit
    export does. Pass the ``data_dir`` active-tenant sentinel through the world
    factory when ``tenant`` is omitted, falling back to the shared DB only when
    no tenant is active. Returns ``None`` (a fail-soft empty section) if the
    world cannot be opened at all.
    """
    try:
        from .world_model import world_for_tenant

        world_tenant = tenant if tenant else "__active__"
        return world_for_tenant(world_tenant)
    except Exception as e:  # pragma: no cover - defensive (corrupt/locked DB)
        log.warning("dsar: could not open world model: %s", e)
        return None


def _matches_user(conv_user_id: str, user_id: str) -> bool:
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
    if channel is None:
        # User ids are channel-scoped.  Exporting without a concrete channel is
        # ambiguous once another channel reuses the same id, so fail closed
        # rather than list every channel and risk cross-subject disclosure.
        return empty

    try:
        all_convs = world.list_conversations(channel)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("dsar: list_conversations failed: %s", e)
        return empty

    convs = [c for c in all_convs if _matches_user(c.user_id, user_id)]

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


def _audit_dir_for_tenant(tenant: str | None) -> Any:
    """Resolve the audit directory for ``tenant`` fail-softly."""
    try:
        from .paths import data_dir

        return data_dir("audit", tenant=tenant) if tenant else data_dir("audit")
    except Exception as e:  # pragma: no cover - defensive
        log.warning("dsar: could not resolve audit dir: %s", e)
        return None


def _iter_audit_events(tenant: str | None) -> list[dict[str, Any]]:
    """Read audit NDJSON rows as dicts, skipping malformed/unreadable input."""
    audit_dir = _audit_dir_for_tenant(tenant)
    if audit_dir is None or not audit_dir.exists() or not audit_dir.is_dir():
        return []

    try:
        files = sorted(audit_dir.glob("*.ndjson"))
    except OSError as e:  # pragma: no cover - defensive
        log.warning("dsar: could not list audit dir %s: %s", audit_dir, e)
        return []

    events: list[dict[str, Any]] = []
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
            if isinstance(event, dict):
                events.append(event)
    return events


def _audit_channels_for_user(user_id: str, tenant: str | None) -> set[str]:
    """Return structured audit channels observed for ``user_id``."""
    return {
        event["channel"]
        for event in _iter_audit_events(tenant)
        if event.get("user_id") == user_id and isinstance(event.get("channel"), str)
    }


def _resolve_subject_channel(
    world: Any, user_id: str, channel: str | None, tenant: str | None
) -> str | None:
    """Return the concrete channel for a DSAR, or ``None`` if ambiguous.

    ``channel`` is part of Maverick's subject identity.  For backward
    compatibility with callers that exported a user id from a single-channel
    install, an omitted channel is inferred only when the user's structured
    world/audit rows identify exactly one channel.  If multiple channels reuse
    the same ``user_id``, the export fails closed so one subject's DSAR cannot
    disclose another subject's data.
    """
    if channel is not None:
        if channel.strip() == "":
            log.warning(
                "dsar: refusing export with blank channel for user_id %r", user_id
            )
            return None
        return channel

    channels: set[str] = set()
    if world is not None:
        try:
            channels.update(
                c.channel
                for c in world.list_conversations(None)
                if _matches_user(c.user_id, user_id) and isinstance(c.channel, str)
            )
        except Exception as e:  # pragma: no cover - defensive
            log.warning("dsar: list_conversations failed while resolving channel: %s", e)

    channels.update(_audit_channels_for_user(user_id, tenant))
    if len(channels) == 1:
        return next(iter(channels))
    if len(channels) > 1:
        log.warning(
            "dsar: refusing ambiguous export for user_id %r across channels %s",
            user_id,
            sorted(channels),
        )
    return None


def _export_audit(user_id: str, channel: str | None, tenant: str | None) -> list[dict[str, Any]]:
    """Collect audit rows for the subject.

    Audit events are plain dicts (``AuditEvent.to_dict`` spreads the payload),
    and GDPR erasure keys off top-level ``channel`` + ``user_id``. That is exactly
    the rule :func:`maverick.audit.erase._event_matches` erases on, so a row
    that *would* be erased is a row that *is* exported. Each kept row is
    JSON-safe by construction (it was parsed from JSON); we round-trip with
    ``default=str`` only to neutralise any value json can't emit. Fail-soft: a
    missing dir, unreadable file, or malformed line is skipped, never raised.
    """
    if channel is None:
        # Channel is part of the subject identity.  Without one we cannot match
        # the erase path's exact-field rule, so do not export audit rows.
        return []

    out: list[dict[str, Any]] = []
    for event in _iter_audit_events(tenant):
        if event.get("user_id") != user_id:
            continue
        if event.get("channel") != channel:
            continue
        # Render ts to ISO for consistency with the world section; keep the
        # rest of the event verbatim so nothing the subject is owed is lost.
        if "ts" in event:
            event = {**event, "ts": _iso(event["ts"])}
        # Round-trip through json with default=str so any stray non-serializable
        # value (shouldn't happen for parsed JSON) is stringified rather than
        # poisoning the whole bundle.
        out.append(json.loads(json.dumps(event, default=str)))
    return out


def export_subject_data(
    user_id: str, *, channel: str | None = None, tenant: str | None = None
) -> dict[str, Any]:
    """Gather everything Maverick holds for ``user_id`` into one JSON bundle.

    GDPR Art. 15 (right of access) / Art. 20 (portability), and a SOC 2 Privacy
    expectation. Read-only and fail-soft: a missing world DB or audit dir
    produces an empty section rather than an error.

    ``user_id`` plus ``channel`` identify the subject (the same pair the world
    model stores on ``conversations`` and that audit events carry as structured
    fields). For compatibility, ``channel`` may be omitted only when existing
    world/audit rows make it unambiguous; if the same ``user_id`` appears on
    multiple channels, the export fails closed instead of over-exporting.
    ``tenant`` selects the data plane: when given, the subject's world DB and
    audit chain are read from that tenant's isolated directory via
    :func:`maverick.world_model.world_for_tenant` / :func:`maverick.paths.data_dir`;
    when ``None`` the active tenant (env / contextvar) is used, falling back to
    the legacy shared store.

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
    world = _resolve_world(tenant)
    channel = _resolve_subject_channel(world, user_id, channel, tenant)
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
