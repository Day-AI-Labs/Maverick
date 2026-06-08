"""Anonymous mode: strip user-identifying content from logs.

When ``MAVERICK_ANON=1`` (env) or ``[privacy] anonymous = true``
(config), structured logs + audit events have their identifying
fields replaced with hashes or sentinels.

Categories scrubbed:
  - goal text (title + description)
  - user_id / channel
  - file paths under user's home (keep just the basename)
  - email addresses, phone numbers, SSNs (via pii_detector)

Use:

    from maverick.privacy import anonymize_field, anonymize_dict, anon_enabled

    if anon_enabled():
        log_line = anonymize_dict(log_line)
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


_SENSITIVE_KEYS = frozenset({
    # "text" covers Anthropic/OpenAI content blocks ({"type": "text",
    # "text": ...}) nested under a message's "content" list -- without it the
    # actual message text leaked unscrubbed in anon mode.
    "goal_text", "title", "description", "content", "text",
    "prompt", "system", "messages", "answer", "msg", "message",
    "input_summary", "output_summary", "detail", "reason",
    "channel", "user_id", "goal_id", "conversation_id", "from", "to",
    "email", "username", "result", "summary",
})

_OPAQUE_TEXT_KEYS = frozenset({"goal_text", "title", "description"})


def _home_pattern() -> re.Pattern[str]:
    return re.compile(re.escape(str(Path.home())))


def anon_enabled() -> bool:
    """True if anonymous mode is on (env or config)."""
    val = os.environ.get("MAVERICK_ANON", "").strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("privacy") or {}
        val = cfg.get("anonymous")
        # A TOML string "false"/"no" is truthy under bool(); honor it the way
        # a2a_enabled does so an explicit off-string disables anon mode.
        if isinstance(val, str):
            return val.strip().lower() in {"1", "true", "yes", "on"}
        return bool(val)
    except Exception:
        return False


def _hash_id(value: str, prefix: str = "") -> str:
    """Stable but non-reversible 12-char hash; prefix tags the field type."""
    if not value:
        return "(empty)"
    h = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}#{h}" if prefix else f"#{h}"


def anonymize_text(text: str) -> str:
    """Strip home-path, PII, and obviously-identifying strings."""
    if not text:
        return text
    out = _home_pattern().sub("~", text)
    # Replace email-like patterns + phones via pii_detector if available.
    try:
        from .safety.pii_detector import redact
        out, _ = redact(out)
    except Exception:
        pass
    return out


def anonymize_field(key: str, value: Any) -> Any:
    """Apply per-field anonymization rules.

    - Identity fields (user_id / channel / email / etc.): hash.
    - Goal text fields (title / description / goal_text): hash.
    - Other sensitive text fields (content / summary / msg): scrub PII + paths.
    - Path fields: keep only the basename.
    - Anything else: return as-is.
    """
    lower = key.lower()
    if lower in (
        "user_id", "username", "channel", "goal_id", "conversation_id",
        "from", "to", "email",
    ):
        return _hash_id(value, prefix=lower)
    if lower in _OPAQUE_TEXT_KEYS:
        return _hash_id(value, prefix=lower)
    if lower in ("path", "filepath", "filename"):
        try:
            return Path(str(value)).name
        except (TypeError, ValueError):
            return value
    if lower in _SENSITIVE_KEYS:
        if isinstance(value, str):
            return anonymize_text(value)
        if isinstance(value, list):
            return [
                anonymize_text(v) if isinstance(v, str)
                else (anonymize_dict(v) if isinstance(v, dict) else v)
                for v in value
            ]
        if isinstance(value, dict):
            return anonymize_dict(value)
    if isinstance(value, dict):
        return anonymize_dict(value)
    if isinstance(value, list):
        return [anonymize_dict(v) if isinstance(v, dict) else v for v in value]
    return value


def anonymize_dict(d: dict) -> dict:
    """Return a new dict with sensitive fields scrubbed."""
    if not d:
        return d
    return {k: anonymize_field(k, v) for k, v in d.items()}


def anonymize_iter(items: Iterable[dict]) -> list[dict]:
    return [anonymize_dict(d) for d in items]


__all__ = [
    "anon_enabled",
    "anonymize_text",
    "anonymize_field",
    "anonymize_dict",
    "anonymize_iter",
]
