"""Audit event schema. Versioned, additive-only.

To add a new event kind:
  1. Add it to ``EventKind`` here.
  2. Bump ``SCHEMA_VERSION`` if the payload shape changes for an
     EXISTING kind (new kinds are additive — no bump needed).
  3. Document the payload shape in this file's module docstring.

Payload shapes (kind -> required fields, all events also carry
``ts``, ``goal_id``, ``agent``, ``kind``):

  goal_start:        title:str, description:str|None
  goal_end:          status:str (succeeded|failed|cancelled), result:str|None
  episode_start:     attempt:int, model:str
  episode_end:       outcome:str, cost_dollars:float, in_tok:int, out_tok:int
  tool_call:         name:str, input_summary:str (truncated)
  tool_result:       name:str, status:str, output_summary:str
  shield_block:      stage:str (input|tool|output), reason:str, score:float|None
  capability_denied: tool:str, principal:str, channel:str|None, user_id:str|None
  egress_blocked:    provider:str (enterprise-mode egress lock denial)
  consent_prompt:    action:str, risk:str (low|medium|high|critical)
  consent_result:    decision:str (approve|deny|timeout)
  secret_redacted:   tool_name:str, pattern:str, count:int
  erase:             channel:str, erasure_id:str (random token, never subject-derived)
  halt:              source:str (file|signal|manual), detail:str|None
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_valid_day(day: Any) -> bool:
    """True iff ``day`` is a literal ``YYYY-MM-DD`` string.

    An audit ``day`` becomes a filesystem path component
    (``<audit_dir>/<day>.ndjson``), so anything that isn't this exact shape
    -- ``..``, a path separator, an absolute path, a NUL -- could escape the
    audit dir. Every code path that builds a day-file path from an untrusted
    ``day`` must gate on this first. (Mirrors the dashboard's own
    ``safe_audit_day`` HTTP-boundary guard.)
    """
    return isinstance(day, str) and bool(_DAY_RE.match(day))


class EventKind:
    """Stringly-typed event kinds. Use these constants, not bare strings."""
    GOAL_START      = "goal_start"
    GOAL_END        = "goal_end"
    EPISODE_START   = "episode_start"
    EPISODE_END     = "episode_end"
    TOOL_CALL       = "tool_call"
    TOOL_RESULT     = "tool_result"
    SHIELD_BLOCK    = "shield_block"
    CAPABILITY_DENIED = "capability_denied"
    GOVERNANCE_DENIED = "governance_denied"
    AUTONOMY_ESCALATED = "autonomy_escalated"
    AUTONOMY_GATED = "autonomy_gated"
    EGRESS_BLOCKED  = "egress_blocked"
    CONSENT_PROMPT  = "consent_prompt"
    CONSENT_RESULT  = "consent_result"
    SECRET_REDACTED = "secret_redacted"
    ERASE           = "erase"
    HALT            = "halt"
    CONFIG_REMEDIATED = "config_remediated"


@dataclass
class AuditEvent:
    """One audit log row. ``payload`` is event-specific (see module doc)."""
    ts: float
    kind: str
    agent: str = "system"
    goal_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        # Strip reserved keys from payload before the spread: a payload key
        # named v/ts/kind/agent/goal_id would otherwise clobber the canonical
        # structural field, losing it and corrupting the signed-hash input.
        _reserved = {"v", "ts", "kind", "agent", "goal_id"}
        safe_payload = {k: val for k, val in self.payload.items() if k not in _reserved}
        return {
            "v": self.schema_version,
            "ts": self.ts,
            "kind": self.kind,
            "agent": self.agent,
            "goal_id": self.goal_id,
            **safe_payload,
        }
