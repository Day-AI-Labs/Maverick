"""Maverick's safety chokepoints, backed by Agent Shield.

The agent wraps three sinks through this module:
  - on every user input    -> Shield.scan_input
  - on every tool call     -> Shield.scan_tool_call
  - on every final output  -> Shield.scan_output

If ``agent-shield`` is not installed, all methods become no-ops with a
single startup warning. This keeps the kernel usable as a research tool
while making the safe path the default for end users installed via the
wizard.

Design notes
------------
- Fail-open on internal errors. A broken scanner must not stop the agent.
- Scans operate on strings; tool call args get serialized to a stable
  ``tool=<name> args=<repr>`` representation before scanning.
- Verdicts carry a severity and list of reasons; callers decide what to do.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

try:  # pragma: no cover - import side-effect tested separately
    from agent_shield import AgentShield  # type: ignore
    _HAVE_SHIELD = True
except ImportError:
    _HAVE_SHIELD = False
    AgentShield = None  # type: ignore


@dataclass
class ShieldVerdict:
    allowed: bool
    severity: str           # "none" | "low" | "medium" | "high" | "critical"
    reasons: list[str]
    raw: Any = None

    @classmethod
    def allow(cls) -> "ShieldVerdict":
        return cls(allowed=True, severity="none", reasons=[])

    @classmethod
    def block(cls, severity: str, reason: str, raw: Any = None) -> "ShieldVerdict":
        return cls(allowed=False, severity=severity, reasons=[reason], raw=raw)


class Shield:
    """Thin facade over AgentShield. Stable interface for the agent loop."""

    def __init__(
        self,
        profile: str = "balanced",
        block_threshold: str = "high",
        warn_if_missing: bool = True,
    ):
        self.profile = profile
        self.block_threshold = block_threshold
        if not _HAVE_SHIELD:
            if warn_if_missing:
                log.warning(
                    "agent-shield not installed; safety scans are NO-OPS. "
                    "Install with: pip install agent-shield"
                )
            self._shield = None
            return

        # Map profiles to AgentShield sensitivity.
        sens = {"strict": "high", "balanced": "medium", "permissive": "low"}.get(profile, "medium")
        try:
            self._shield = AgentShield(
                sensitivity=sens,
                blockOnThreat=True,
                blockThreshold=block_threshold,
            )
        except Exception as e:
            log.error("Failed to initialize AgentShield (fail-open): %s", e)
            self._shield = None

    @property
    def enabled(self) -> bool:
        return self._shield is not None

    @classmethod
    def from_config(cls) -> "Shield":
        """Build a Shield from ``~/.maverick/config.toml`` [safety] section."""
        try:
            from maverick.config import get_safety
            safety = get_safety()
        except Exception:
            safety = {"profile": "balanced", "block_threshold": "high"}
        if safety.get("profile") == "off":
            return cls(profile="permissive", warn_if_missing=False)
        return cls(profile=safety["profile"], block_threshold=safety["block_threshold"])

    def _interpret(self, result: Any) -> ShieldVerdict:
        if getattr(result, "blocked", False):
            threats = getattr(result, "threats", []) or []
            reasons = [getattr(t, "category", "threat") for t in threats]
            return ShieldVerdict.block(
                severity=getattr(result, "severity", "high"),
                reason="; ".join(reasons) or "blocked",
                raw=result,
            )
        return ShieldVerdict.allow()

    def scan_input(self, text: str) -> ShieldVerdict:
        if not self.enabled:
            return ShieldVerdict.allow()
        try:
            return self._interpret(self._shield.scanInput(text))  # type: ignore
        except Exception as e:
            log.error("Shield input scan failed (fail-open): %s", e)
            return ShieldVerdict.allow()

    def scan_tool_call(self, tool_name: str, args: dict) -> ShieldVerdict:
        if not self.enabled:
            return ShieldVerdict.allow()
        payload = f"tool={tool_name} args={args!r}"
        try:
            return self._interpret(self._shield.scanInput(payload))  # type: ignore
        except Exception as e:
            log.error("Shield tool-call scan failed (fail-open): %s", e)
            return ShieldVerdict.allow()

    def scan_output(self, text: str) -> ShieldVerdict:
        if not self.enabled:
            return ShieldVerdict.allow()
        try:
            scanner = getattr(self._shield, "scanOutput", None) or self._shield.scanInput  # type: ignore
            return self._interpret(scanner(text))
        except Exception as e:
            log.error("Shield output scan failed (fail-open): %s", e)
            return ShieldVerdict.allow()
