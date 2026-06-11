"""Channel auto-routing (roadmap: 2028 H2 UX — "channel auto-routing").

An inbound message can arrive on one channel but be best *answered* on another:
a three-paragraph question with a stack-trace attachment wants an email/ticket
reply, not a one-line SMS; an "URGENT, prod is down" ping wants a pager profile.
This is the routing brain for that: given a message's signals (length, detected
language, urgency keywords, attachment types, plus an optional injected
classifier label) it scores a **configurable** routing table (``[channels.routing]``)
and returns the best-fit reply channel / handler profile, with an :func:`explain`
that shows exactly which rule won and why.

Pure and deterministic — signals in, a :class:`RouteDecision` out — so it is
unit-tested with no I/O. **Opt-in and fail-open**: with no table configured the
decision is a ``passthrough`` (reply on the channel the message arrived on), so
wiring this in never changes behaviour until an operator writes rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# A "rule" matches when EVERY condition it declares holds. Conditions are all
# optional; an empty rule matches anything (a catch-all default). Recognised
# condition keys (others are ignored, so a future key never crashes an old
# kernel):
#   min_length / max_length : int, message char length bounds (inclusive)
#   languages               : list[str], detected language must be one of these
#   urgency                 : "low" | "normal" | "high" | "critical" (>= this)
#   any_keyword             : list[str], any appears (case-insensitive substring)
#   attachments             : list[str], message must carry one of these types
#   label                   : str, the injected classifier label must equal this
_URGENCY_ORDER = ("low", "normal", "high", "critical")

# Default urgency keyword lexicon, used only when the caller does not pass an
# explicit urgency and lets us infer one from the text. Deliberately small and
# unsurprising; operators tune routing via the table, not this list.
_URGENCY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "critical": ("outage", "down", "sev1", "sev 1", "p0", "data loss", "breach"),
    "high": ("urgent", "asap", "immediately", "critical", "emergency", "blocker"),
}


def _urgency_rank(level: str) -> int:
    try:
        return _URGENCY_ORDER.index((level or "").strip().lower())
    except ValueError:
        return 0


@dataclass(frozen=True)
class MessageSignals:
    """What we know about an inbound message, independent of any channel."""

    text: str = ""
    language: str = ""                 # ISO-ish code, e.g. "en"; "" = unknown
    urgency: str = ""                  # explicit override; "" = infer from text
    attachments: tuple[str, ...] = ()  # type hints, e.g. ("image", "log", "pdf")
    label: str = ""                    # optional injected-classifier verdict

    @property
    def length(self) -> int:
        return len(self.text or "")

    def effective_urgency(self) -> str:
        """The explicit urgency, else the highest urgency inferred from text."""
        if self.urgency:
            return self.urgency.strip().lower()
        low = (self.text or "").lower()
        for level in ("critical", "high"):
            if any(kw in low for kw in _URGENCY_KEYWORDS[level]):
                return level
        return "normal"


@dataclass(frozen=True)
class RouteRule:
    """One row of the routing table: conditions + the channel to route to."""

    channel: str
    min_length: int | None = None
    max_length: int | None = None
    languages: tuple[str, ...] = ()
    urgency: str = ""                  # minimum urgency (>=) to match
    any_keyword: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    label: str = ""
    name: str = ""                     # human label for explain()

    def reasons(self, sig: MessageSignals) -> list[str] | None:
        """Return the satisfied-condition strings if this rule matches ``sig``,
        else ``None``. A rule with no conditions matches anything (catch-all)."""
        why: list[str] = []
        if self.min_length is not None:
            if sig.length < self.min_length:
                return None
            why.append(f"length>={self.min_length}")
        if self.max_length is not None:
            if sig.length > self.max_length:
                return None
            why.append(f"length<={self.max_length}")
        if self.languages:
            if (sig.language or "").strip().lower() not in self.languages:
                return None
            why.append(f"language in {list(self.languages)}")
        if self.urgency:
            if _urgency_rank(sig.effective_urgency()) < _urgency_rank(self.urgency):
                return None
            why.append(f"urgency>={self.urgency}")
        if self.any_keyword:
            low = (sig.text or "").lower()
            hit = next((k for k in self.any_keyword if k in low), None)
            if hit is None:
                return None
            why.append(f"keyword:{hit!r}")
        if self.attachments:
            have = {a.strip().lower() for a in sig.attachments}
            hit = next((a for a in self.attachments if a in have), None)
            if hit is None:
                return None
            why.append(f"attachment:{hit}")
        if self.label:
            if (sig.label or "").strip().lower() != self.label:
                return None
            why.append(f"label=={self.label}")
        if not why:
            why.append("catch-all (no conditions)")
        return why


@dataclass(frozen=True)
class RouteDecision:
    channel: str
    rule: str            # the winning rule's name, or "passthrough"
    reasons: list[str] = field(default_factory=list)
    passthrough: bool = False


def _norm_list(v) -> tuple[str, ...]:
    if isinstance(v, str):
        items = [v]
    elif isinstance(v, (list, tuple)):
        items = list(v)
    else:
        return ()
    return tuple(str(x).strip().lower() for x in items if str(x).strip())


def parse_rules(raw: list[dict]) -> list[RouteRule]:
    """Build rules from ``[[channels.routing.rules]]`` dicts.

    Rules are tried in order; the first match wins. A row without a ``channel``
    is skipped (rather than raising) so one typo can't break routing.
    """
    out: list[RouteRule] = []
    for i, r in enumerate(raw or []):
        if not isinstance(r, dict):
            continue
        channel = str(r.get("channel") or "").strip()
        if not channel:
            continue

        def _int(key):
            v = r.get(key)
            try:
                return int(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        urg = str(r.get("urgency") or "").strip().lower()
        if urg and urg not in _URGENCY_ORDER:
            urg = ""
        out.append(RouteRule(
            channel=channel,
            min_length=_int("min_length"),
            max_length=_int("max_length"),
            languages=_norm_list(r.get("languages")),
            urgency=urg,
            any_keyword=_norm_list(r.get("any_keyword")),
            attachments=_norm_list(r.get("attachments")),
            label=str(r.get("label") or "").strip().lower(),
            name=str(r.get("name") or f"rule[{i}]"),
        ))
    return out


def load_rules() -> list[RouteRule]:
    """Rules from ``[channels.routing] rules`` in config (empty when unset)."""
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("channels") or {}
        routing = cfg.get("routing") or {}
        return parse_rules(routing.get("rules") or [])
    except Exception:  # pragma: no cover -- config never blocks routing
        return []


def route(
    sig: MessageSignals,
    *,
    rules: list[RouteRule] | None = None,
    inbound_channel: str = "",
    classifier=None,
) -> RouteDecision:
    """Pick the best-fit reply channel for ``sig``.

    ``classifier`` (optional, injected) is called as ``classifier(sig)`` and may
    return a label string; it overrides ``sig.label`` for this decision only,
    letting a learned model feed the same rule table a heuristic would. With no
    rules (or no match), the result is a ``passthrough`` onto ``inbound_channel``
    — the safe default that changes nothing until rules exist.
    """
    rules = rules if rules is not None else load_rules()
    if classifier is not None:
        try:
            label = classifier(sig)
            if isinstance(label, str) and label.strip():
                sig = MessageSignals(
                    text=sig.text, language=sig.language, urgency=sig.urgency,
                    attachments=sig.attachments, label=label.strip(),
                )
        except Exception:  # pragma: no cover -- a bad classifier never blocks
            pass
    for rule in rules:
        why = rule.reasons(sig)
        if why is not None:
            return RouteDecision(channel=rule.channel, rule=rule.name, reasons=why)
    return RouteDecision(
        channel=inbound_channel or "passthrough",
        rule="passthrough",
        reasons=["no routing rule matched"],
        passthrough=True,
    )


def explain(
    sig: MessageSignals,
    *,
    rules: list[RouteRule] | None = None,
    inbound_channel: str = "",
    classifier=None,
) -> str:
    """A one-line, human-readable account of the routing decision."""
    d = route(sig, rules=rules, inbound_channel=inbound_channel, classifier=classifier)
    why = "; ".join(d.reasons) if d.reasons else "—"
    if d.passthrough:
        return (f"route -> {d.channel} (passthrough: {why}); "
                f"urgency={sig.effective_urgency()}, length={sig.length}")
    return (f"route -> {d.channel} via {d.rule} ({why}); "
            f"urgency={sig.effective_urgency()}, length={sig.length}")


__all__ = [
    "MessageSignals",
    "RouteRule",
    "RouteDecision",
    "parse_rules",
    "load_rules",
    "route",
    "explain",
]
