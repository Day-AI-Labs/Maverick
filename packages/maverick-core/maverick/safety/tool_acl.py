"""Tool allow-list / deny-list ACLs.

Global, per-channel, and per-user filtering of tools.

Global (in ``~/.maverick/config.toml``):

    [security]
    allowed_tools = ["shell", "read_file", "write_file"]   # whitelist
    denied_tools  = ["computer", "browser"]                # blacklist

Per-channel (the channel a goal arrived from):

    [security.channels.telegram]
    denied_tools = ["computer", "shell"]   # no destructive ops over Telegram

    [security.channels.slack]
    allowed_tools = ["read_file", "web_search", "recall_past_goals"]

Per-user (the channel-side user id):

    [security.users."tg:12345"]
    allowed_tools = ["shell", "read_file", "write_file"]   # this user is trusted

Composition rule: for a (channel, user) pair, we intersect the
configured allow-lists and union the deny-lists. The most-restrictive
wins, so anyone with both channel-allow and user-deny gets the deny.

This lets a deployment lock down what an agent can do per-context
without touching the kernel.
"""
from __future__ import annotations

import logging
from typing import Iterable

log = logging.getLogger(__name__)


def _load_lists() -> tuple[set[str], set[str]]:
    """Load global (allowed, denied) sets from ~/.maverick/config.toml."""
    try:
        from ..config import load_config
        cfg = load_config()
    except Exception as e:
        log.debug("tool_acl: cannot load config: %s", e)
        return set(), set()
    sec = (cfg or {}).get("security") or {}
    allowed = sec.get("allowed_tools") or []
    denied = sec.get("denied_tools") or []
    return set(allowed), set(denied)


def _load_lists_for_channel(channel: str) -> tuple[set[str], set[str]]:
    """Per-channel ACL: ``[security.channels.<channel>]``."""
    try:
        from ..config import load_config
        cfg = load_config() or {}
    except Exception:
        return set(), set()
    sec = ((cfg.get("security") or {}).get("channels") or {}).get(channel) or {}
    return set(sec.get("allowed_tools") or []), set(sec.get("denied_tools") or [])


def _load_lists_for_user(user_id: str) -> tuple[set[str], set[str]]:
    """Per-user ACL: ``[security.users."channel:id"]``.

    ``user_id`` should be the channel-qualified form (``tg:12345``,
    ``slack:U02ABC``) so two channels' user-ids can't collide.
    """
    try:
        from ..config import load_config
        cfg = load_config() or {}
    except Exception:
        return set(), set()
    users = (cfg.get("security") or {}).get("users") or {}
    sec = users.get(user_id) or {}
    return set(sec.get("allowed_tools") or []), set(sec.get("denied_tools") or [])


def resolve_lists(
    *,
    channel: str | None = None,
    user_id: str | None = None,
) -> tuple[set[str], set[str]]:
    """Compose global + channel + user ACLs for a (channel, user_id) pair.

    Composition:
      - allowed = intersection of all non-empty allow-lists
        (most restrictive across layers wins; an empty allow-list means
        "all" at that layer and is a no-op in the intersection).
      - denied  = union of all deny-lists.

    Returns (allowed, denied) for downstream filter_tools().
    """
    g_allow, g_deny = _load_lists()
    layers_allow: list[set[str]] = [g_allow] if g_allow else []
    layers_deny: list[set[str]] = [g_deny]

    if channel:
        c_allow, c_deny = _load_lists_for_channel(channel)
        if c_allow:
            layers_allow.append(c_allow)
        layers_deny.append(c_deny)
    if user_id:
        u_allow, u_deny = _load_lists_for_user(user_id)
        if u_allow:
            layers_allow.append(u_allow)
        layers_deny.append(u_deny)

    if not layers_allow:
        merged_allow: set[str] = set()
    else:
        merged_allow = set.intersection(*layers_allow)
    merged_deny = set.union(*layers_deny) if layers_deny else set()
    return merged_allow, merged_deny


def filter_tools(
    tool_names: Iterable[str],
    *,
    allowed: set[str] | None = None,
    denied: set[str] | None = None,
) -> set[str]:
    """Apply the allow/deny lists to ``tool_names``. Returns the kept set.

    Override the lists explicitly via kwargs; if both kwargs are None,
    the config is consulted.
    """
    if allowed is None and denied is None:
        allowed, denied = _load_lists()
    else:
        allowed = allowed or set()
        denied = denied or set()
    names = set(tool_names)
    if allowed:
        names = names & allowed
    if denied:
        names = names - denied
    return names


def apply_to_registry(
    reg,
    *,
    channel: str | None = None,
    user_id: str | None = None,
) -> None:
    """Mutate a ToolRegistry in place per the resolved (global + channel +
    user) ACL. Passing both ``channel`` and ``user_id`` applies the most
    restrictive composition.

    Called once at registry construction (channel/user None) and may be
    called again at dispatch time when a goal arrives from a channel
    (just pass the channel + user id; the registry mutates in place).
    """
    allowed, denied = resolve_lists(channel=channel, user_id=user_id)
    if not allowed and not denied:
        return
    reg.set_acl(allowed=allowed, denied=denied)
    current = {t.name for t in reg.all()}
    keep = filter_tools(current, allowed=allowed, denied=denied)
    drop = current - keep
    for name in drop:
        # ToolRegistry exposes _tools; we use the private API
        # because there's no public remove() yet -- adding one as
        # part of this change.
        reg._tools.pop(name, None)
    if drop:
        log.info(
            "tool_acl: dropped %d tool(s) (channel=%s user=%s): %s",
            len(drop), channel, user_id, sorted(drop),
        )
