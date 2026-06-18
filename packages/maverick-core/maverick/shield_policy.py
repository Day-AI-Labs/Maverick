"""Shield policy — make the safety shield MANDATORY for regulated deployments.

By kernel rule 1 the shield is optional and fails OPEN: when ``maverick-shield``
isn't installed, external content is admitted unscreened. That's the right
default for a personal agent and the wrong one for a regulated client whose
security review will not accept a control that silently disappears if a
dependency is missing.

This module centralizes the "is the shield required, and what's the block
reason for this text" decision so every external-facing surface (federation
inbound, A2A) screens consistently and **fails toward the gate** when the shield
is required:

* ``shield_required()`` — on via ``MAVERICK_REQUIRE_SHIELD``, ``[safety]
  require_shield = true``, or enterprise mode.
* ``scan_block(text)`` — returns a block reason or ``None`` (allow). A shield
  *scan error* always blocks (fail-toward-gate). A *missing* shield blocks only
  when required (so non-enterprise installs keep the fail-open default).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def shield_required() -> bool:
    """Must the safety shield be present + screen external traffic?"""
    import os
    env = os.environ.get("MAVERICK_REQUIRE_SHIELD")
    if env is not None and env.strip() != "":
        return env.strip().lower() in _TRUE
    try:
        from .enterprise import enterprise_enabled
        if enterprise_enabled():
            return True
    except Exception:  # pragma: no cover
        pass
    try:
        from .config import load_config
        return str(((load_config() or {}).get("safety") or {}).get("require_shield")
                   or "").strip().lower() in _TRUE
    except Exception:
        return False


def shield_available() -> bool:
    try:
        import maverick_shield  # noqa: F401
        return True
    except Exception:
        return False


def scan_block(text: str) -> str | None:
    """Screen ``text``; a block reason, or ``None`` to allow.

    - shield not installed: block iff :func:`shield_required` (else allow,
      preserving the fail-open default for personal installs);
    - shield installed but the scan errors: block (fail-toward-gate);
    - shield installed and a detector fires: block with its reasons.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        from maverick_shield import Shield  # type: ignore
    except Exception:
        if shield_required():
            return ("safety shield is required but not installed "
                    "([safety] require_shield / enterprise mode)")
        return None
    try:
        verdict = Shield().scan_input(text)
    except Exception as e:  # pragma: no cover - fail toward the gate
        log.warning("shield scan failed (blocking): %s", e)
        return "shield scan error"
    if not getattr(verdict, "allowed", True):
        return "; ".join(getattr(verdict, "reasons", []) or ["blocked by shield"])
    return None


__all__ = ["shield_required", "shield_available", "scan_block"]
