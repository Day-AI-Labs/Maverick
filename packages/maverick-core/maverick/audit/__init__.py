"""Audit log for Maverick.

Append-only NDJSON sink at ``~/.maverick/audit/YYYY-MM-DD.ndjson``.
Daily rotation. Each line is a versioned JSON event.

Event types (see ``events.py``):
  - goal_start / goal_end       — goal lifecycle
  - episode_start / episode_end — best-of-N attempt lifecycle
  - tool_call / tool_result     — every tool invocation
  - shield_block                — Shield denied an input/output/tool call
  - consent_prompt / consent_result — destructive-action gates
  - secret_redacted             — secret detector hit
  - erase                       — GDPR Art.17 erasure
  - halt                        — killswitch fired

This module is intentionally minimal. The writer is fail-safe: if
something goes wrong inside the audit path, we log a warning and keep
the agent running. Audit failures should NEVER crash the swarm.
"""
from __future__ import annotations

from .erase import delete_user, scrub_user  # noqa: F401
from .events import AuditEvent, EventKind  # noqa: F401
from .signing import (  # noqa: F401
    AuditSigner,
    ChainBreak,
    ensure_anchors,
    reanchor_file,
    verify_anchors,
    verify_chain,
)
from .writer import (  # noqa: F401
    AuditLog,
    default_audit_log,
    reanchor_after_erase,
    record,
)

__all__ = [
    "AuditEvent",
    "EventKind",
    "AuditLog",
    "default_audit_log",
    "record",
    "reanchor_after_erase",
    "scrub_user",
    "delete_user",
    "AuditSigner",
    "ChainBreak",
    "verify_chain",
    "reanchor_file",
    "ensure_anchors",
    "verify_anchors",
]
