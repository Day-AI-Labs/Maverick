"""Maverick's safety chokepoints, backed by Agent Shield with a built-in fallback.

The agent wraps three sinks through this module:
  - on every user input    -> Shield.scan_input
  - on every tool call     -> Shield.scan_tool_call
  - on every final output  -> Shield.scan_output

Backends (chosen automatically in order):
  1. ``agent_shield`` SDK if installed (full F1 0.988 rule pack)
  2. ``builtin_rules`` (~20 high-impact rules bundled with maverick-shield)
  3. No-op (only if the user explicitly disabled safety via [safety] profile=off)

Fail-open on internal errors -- a broken scanner must not stop the agent --
but never fail-open SILENTLY; the constructor logs which backend is active.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .builtin_rules import SEVERITY_ORDER
from .builtin_rules import scan as builtin_scan
from .output_policy import scan_output as output_policy_scan

log = logging.getLogger(__name__)

try:  # pragma: no cover
    from agent_shield import AgentShield
    _HAVE_SDK = True
except ImportError:
    _HAVE_SDK = False
    AgentShield = None  # type: ignore


@dataclass
class ShieldVerdict:
    allowed: bool
    severity: str           # "none" | "low" | "medium" | "high" | "critical"
    reasons: list[str]
    raw: Any = None

    @classmethod
    def allow(cls) -> ShieldVerdict:
        return cls(allowed=True, severity="none", reasons=[])

    @classmethod
    def block(cls, severity: str, reason: str, raw: Any = None) -> ShieldVerdict:
        return cls(allowed=False, severity=severity, reasons=[reason], raw=raw)


class Shield:
    """Facade over AgentShield SDK + built-in fallback."""

    BACKEND_SDK = "agent-shield"
    BACKEND_BUILTIN = "builtin"
    BACKEND_NONE = "none"

    def __init__(
        self,
        profile: str = "balanced",
        block_threshold: str = "high",
        backend: str = "auto",
        warn_if_missing: bool = True,
    ):
        self.profile = profile
        self.block_threshold = block_threshold

        if backend == "none" or profile == "off":
            self.backend = self.BACKEND_NONE
            self._sdk = None
            return

        # Auto: prefer SDK, fall back to builtin.
        if backend in ("auto", "agent-shield") and _HAVE_SDK:
            sens = {"strict": "high", "balanced": "medium", "permissive": "low"}.get(
                profile, "medium"
            )
            try:
                self._sdk = AgentShield(
                    sensitivity=sens, blockOnThreat=True, blockThreshold=block_threshold,
                )
                self.backend = self.BACKEND_SDK
                log.info("Shield: using agent-shield SDK (full ruleset)")
                return
            except Exception as e:
                log.error("Shield: agent-shield SDK init failed (%s); falling back to builtin", e)

        # Built-in fallback
        self._sdk = None
        self.backend = self.BACKEND_BUILTIN
        if warn_if_missing and not _HAVE_SDK:
            log.warning(
                "Shield: agent-shield SDK not installed; using built-in rules "
                "(~20 high-impact patterns vs. ~115 in the full SDK). "
                "For full protection: pip install agent-shield"
            )

    @property
    def enabled(self) -> bool:
        return self.backend != self.BACKEND_NONE

    @classmethod
    def from_config(cls) -> Shield:
        try:
            from maverick.config import get_safety
            safety = get_safety()
        except Exception:
            safety = {"profile": "balanced", "block_threshold": "high"}
        if safety.get("profile") == "off":
            return cls(profile="off", backend="none", warn_if_missing=False)
        return cls(profile=safety["profile"], block_threshold=safety["block_threshold"])

    def _scan_via_backend(self, text: str) -> ShieldVerdict:
        if self.backend == self.BACKEND_NONE:
            return ShieldVerdict.allow()
        if self.backend == self.BACKEND_SDK:
            try:
                result = self._sdk.scanInput(text)  # type: ignore
                if getattr(result, "blocked", False):
                    threats = getattr(result, "threats", []) or []
                    reasons = [getattr(t, "category", "threat") for t in threats]
                    return ShieldVerdict.block(
                        severity=getattr(result, "severity", "high"),
                        reason="; ".join(reasons) or "blocked",
                        raw=result,
                    )
                return ShieldVerdict.allow()
            except Exception as e:
                log.error("Shield SDK scan failed (fail-open): %s", e)
                return ShieldVerdict.allow()
        # builtin
        try:
            blocked, severity, names = builtin_scan(text, block_threshold=self.block_threshold)
            if blocked:
                return ShieldVerdict.block(
                    severity=severity, reason="; ".join(names) or "builtin-rule",
                )
            return ShieldVerdict.allow()
        except Exception as e:  # pragma: no cover
            log.error("Shield builtin scan failed (fail-open): %s", e)
            return ShieldVerdict.allow()

    def scan_input(self, text: str) -> ShieldVerdict:
        return self._scan_via_backend(text)

    def scan_tool_call(self, tool_name: str, args: dict) -> ShieldVerdict:
        payload = f"tool={tool_name} args={args!r}"
        return self._scan_via_backend(payload)

    def scan_output(self, text: str, known_prompt: str | None = None) -> ShieldVerdict:
        verdict = self._scan_via_backend(text)
        # Output-side detectors the input rule pack can't see: verbatim
        # system-prompt regurgitation and refusal-then-leak. Fail-open.
        if self.backend == self.BACKEND_NONE:
            return verdict
        try:
            policy = output_policy_scan(text, known_prompt=known_prompt)
        except Exception as e:  # pragma: no cover -- detector bug must not block
            log.error("Shield output-policy scan failed (fail-open): %s", e)
            return verdict
        if not policy.blocked:
            return verdict
        threshold_idx = SEVERITY_ORDER.get(self.block_threshold, SEVERITY_ORDER["high"])
        if SEVERITY_ORDER.get(policy.severity, -1) < threshold_idx:
            return verdict
        if not verdict.allowed:
            return ShieldVerdict.block(
                severity=_max_severity(verdict.severity, policy.severity),
                reason="; ".join(verdict.reasons + policy.reasons),
            )
        return ShieldVerdict.block(
            severity=policy.severity, reason="; ".join(policy.reasons),
        )


def _max_severity(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.get(a, -1) >= SEVERITY_ORDER.get(b, -1) else b
