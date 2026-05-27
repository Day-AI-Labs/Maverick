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
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)


_SENSITIVE_KEYS = frozenset({
    "goal_text", "title", "description", "content",
    "prompt", "system", "messages", "answer",
    "channel", "user_id", "from", "to", "email", "username",
    "result", "summary",
})

_HOME_RE = re.compile(re.escape(str(Path.home())))


def anon_enabled() -> bool:
    """True if anonymous mode is on (env or config)."""
    val = os.environ.get("MAVERICK_ANON", "").strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("privacy") or {}
        return bool(cfg.get("anonymous"))
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
    out = _HOME_RE.sub("~", text)
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
    - Text fields (title / description / content): scrub PII + paths.
    - Path fields: keep only the basename.
    - Anything else: return as-is.
    """
    lower = key.lower()
    if lower in ("user_id", "username", "channel", "from", "to", "email"):
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
                anonymize_field("content", v) if isinstance(v, str)
                else (anonymize_dict(v) if isinstance(v, dict) else v)
                for v in value
            ]
        if isinstance(value, dict):
            return anonymize_dict(value)
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
