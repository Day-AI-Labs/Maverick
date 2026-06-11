"""Onboarding personalization v2 (roadmap: 2028 H2 UX).

v1 personalizes the *wizard* (mode picker, deployment branching). v2
personalizes **after** install, from how the deployment is actually used in
its first days: it reads early usage and produces ranked, concrete
suggestions — each tied to the observation that justifies it, with the exact
config edit or command. Suggestions only; nothing is applied.

Heuristics (each fires only when its observation holds):

* long conversations → enable history compaction / a streaming strategy;
* repeated same-verb goals → point at the matching starter template flow;
* high approval-denial ratio → suggest the ``supervised`` director profile
  and a review checkpoint;
* several failed goals sharing a failure class → surface the self-healing
  remedy for that class;
* multi-channel use → channel niceties (threading, rich render).

``suggest(world)`` is pure over an injected world; empty history returns an
honest "not enough usage yet" instead of generic tips.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Suggestion:
    observation: str      # the data that justifies this
    suggestion: str       # what to do
    action: str           # the exact config/command


def _usage(world) -> dict:
    out: dict = {"goals": [], "turns_per_conv": [], "channels": set(),
                 "approvals": {"approved": 0, "denied": 0},
                 "failures": Counter()}
    try:
        out["goals"] = list(world.list_goals(limit=10_000))
    except Exception:
        pass
    try:
        for c in world.list_conversations():
            out["channels"].add(getattr(c, "channel", "?"))
            try:
                turns = world.recent_turns(c.id, limit=1000)
                out["turns_per_conv"].append(len(turns))
            except Exception:
                continue
    except Exception:
        pass
    try:
        for a in world.list_approvals(limit=10_000):
            s = (getattr(a, "status", "") or "").lower()
            if s in out["approvals"]:
                out["approvals"][s] += 1
    except Exception:
        pass
    from .self_healing import diagnose
    for g in out["goals"]:
        if getattr(g, "status", "") in ("failed", "blocked"):
            out["failures"][diagnose(getattr(g, "result", "") or "")] += 1
    return out


def suggest(world, *, min_goals: int = 3) -> list[Suggestion]:
    u = _usage(world)
    if len(u["goals"]) < min_goals:
        return []
    out: list[Suggestion] = []

    long_convs = [n for n in u["turns_per_conv"] if n >= 30]
    if long_convs:
        out.append(Suggestion(
            observation=f"{len(long_convs)} conversation(s) ran past 30 turns",
            suggestion="enable history compaction so long chats stay cheap",
            action='[context] compact = true; compaction_strategy = "streaming"',
        ))

    verbs = Counter()
    for g in u["goals"]:
        first = ((getattr(g, "title", "") or "").strip().lower().split() or [""])[0]
        if first.isalpha():
            verbs[first] += 1
    if verbs:
        verb, n = verbs.most_common(1)[0]
        if n >= 3:
            out.append(Suggestion(
                observation=f"{n} goals start with {verb!r}",
                suggestion="start these from a template instead of free text",
                action="maverick template browse  # pick the matching starter",
            ))

    ap = u["approvals"]
    decided = ap["approved"] + ap["denied"]
    if decided >= 5 and ap["denied"] / decided > 0.4:
        out.append(Suggestion(
            observation=(f"{ap['denied']}/{decided} approvals denied — the agent "
                         "is overreaching your comfort level"),
            suggestion="run new goals under the supervised director profile",
            action="director_mode.direct(outcome, profile=\"supervised\")",
        ))

    for cls, n in u["failures"].most_common(1):
        if n >= 2 and cls != "unknown":
            from .self_healing import remedies
            top = remedies(cls)[0]
            out.append(Suggestion(
                observation=f"{n} runs failed with {cls.replace('_', ' ')}",
                suggestion=top.summary,
                action=top.command,
            ))

    if len(u["channels"]) >= 2:
        out.append(Suggestion(
            observation=f"you drive Maverick from {len(u['channels'])} channels",
            suggestion="turn on channel niceties (threaded replies, rich render)",
            action="[channels] rich_render = true; [channels.slack] "
                   "thread_replies = true",
        ))
    return out


def render(world) -> str:
    suggestions = suggest(world)
    if not suggestions:
        return ("onboarding: not enough usage yet to personalize — "
                "run a few goals and check back.")
    lines = ["personalized setup suggestions (from your actual usage; "
             "nothing applied automatically):"]
    for i, s in enumerate(suggestions, 1):
        lines.append(f"  {i}. {s.suggestion}")
        lines.append(f"     because: {s.observation}")
        lines.append(f"     how: {s.action}")
    return "\n".join(lines)


__all__ = ["Suggestion", "suggest", "render"]
