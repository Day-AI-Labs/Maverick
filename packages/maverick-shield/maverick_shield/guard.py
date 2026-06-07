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


def _collect_arg_strings(value: Any) -> list[str]:
    """Recursively collect every string leaf from a tool-args structure.

    Used so ``scan_tool_call`` can scan the bare argument values (preserving
    their real boundaries) instead of ``repr(args)``, whose quoting can break
    rule anchors. Dict keys are included too, since an injection can hide in a
    key name.
    """
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                out.append(k)
            out.extend(_collect_arg_strings(v))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            out.extend(_collect_arg_strings(item))
    elif value is not None:
        out.append(str(value))
    return out


try:  # pragma: no cover
    from agent_shield import AgentShield
    _HAVE_SDK = True
except ImportError:
    _HAVE_SDK = False
    AgentShield = None  # type: ignore

# Emit the "SDK not installed" advisory at most once per process (a Shield is
# constructed on every goal run / chat turn, which would otherwise spam it).
_WARNED_SDK_MISSING = False


def _normalize_config_token(value: Any, default: str) -> str:
    """Return a lowercase config token, tolerating hand-edited TOML types."""
    if not value:
        return default
    return str(value).strip().lower() or default


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
        scan_input: bool = True,
        scan_tool_calls: bool = True,
        scan_output: bool = True,
    ):
        # Normalize: profile/threshold/backend come from user-typed TOML, and
        # the comparisons below (== "off"/"none", the {"strict": ...} sensitivity
        # lookup) plus SEVERITY_ORDER are case-sensitive -- a config like
        # profile = "Off" or "Strict" otherwise silently misapplies (safety
        # stays on, or "Strict" falls through to medium sensitivity). Coerce
        # before strip/lower so truthy non-string TOML values (for example
        # profile = true or block_threshold = 1) cannot crash Shield startup.
        profile = _normalize_config_token(profile, "balanced")
        block_threshold = _normalize_config_token(block_threshold, "high")
        backend = _normalize_config_token(backend, "auto")
        self.profile = profile
        self.block_threshold = block_threshold
        # Per-sink enable flags ([safety] scan_input/scan_tool_calls/
        # scan_output). Enforced centrally here so every call site honors the
        # config — previously these keys existed but no consumer read them, so
        # a user who set scan_tool_calls=false got no effect. All default True;
        # disabling a sink is the user's explicit choice on their own instance.
        self._scan_input_enabled = scan_input
        self._scan_tool_calls_enabled = scan_tool_calls
        self._scan_output_enabled = scan_output

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
        # A Shield is built once per goal run, so warning every time spams the
        # CLI output (and every `chat` turn). Warn once per process.
        global _WARNED_SDK_MISSING
        if warn_if_missing and not _HAVE_SDK and not _WARNED_SDK_MISSING:
            _WARNED_SDK_MISSING = True
            log.warning(
                "Shield: agent-shield SDK not installed; using built-in rules "
                "(~20 high-impact patterns vs. ~115 in the full SDK). "
                "For full protection: pip install agent-shield"
            )

    @property
    def enabled(self) -> bool:
        return self.backend != self.BACKEND_NONE

    @classmethod
    def from_config(cls, *, warn_if_missing: bool = True) -> Shield:
        # ``warn_if_missing`` lets read-only status commands (``maverick
        # version`` / ``doctor``) resolve the backend WITHOUT emitting the
        # "agent-shield SDK not installed" log line -- they already render the
        # shield status in their own formatted output, so the raw warning is
        # redundant and bleeds onto stderr mid-table. Run paths keep the
        # default (warn once per process).
        try:
            from maverick.config import get_safety
            safety = get_safety()
        except Exception:
            safety = {"profile": "balanced", "block_threshold": "high"}
        if safety.get("profile") == "off":
            return cls(profile="off", backend="none", warn_if_missing=False)
        return cls(
            profile=safety["profile"],
            block_threshold=safety["block_threshold"],
            scan_input=safety.get("scan_input", True),
            scan_tool_calls=safety.get("scan_tool_calls", True),
            scan_output=safety.get("scan_output", True),
            warn_if_missing=warn_if_missing,
        )

    def _scan_via_backend(self, text: str) -> ShieldVerdict:
        # Coerce non-str input to text BEFORE scanning. Previously a bytes /
        # dict / None payload made the builtin regex `re.search` raise
        # TypeError, which the except-clauses below swallowed into a fail-OPEN
        # allow -- so `scan_input(b"ignore all previous instructions")` slipped
        # a live payload straight through. Decode/stringify so the content is
        # actually inspected.
        if not isinstance(text, str):
            if isinstance(text, (bytes, bytearray)):
                text = bytes(text).decode("utf-8", errors="replace")
            else:
                text = str(text)
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
        if not self._scan_input_enabled:
            return ShieldVerdict.allow()
        return self._scan_via_backend(text)

    def scan_tool_call(self, tool_name: str, args: dict) -> ShieldVerdict:
        if not self._scan_tool_calls_enabled:
            return ShieldVerdict.allow()
        # Scan the raw string leaves of ``args`` rather than ``repr(args)``.
        # repr() wraps each value in quotes, so a payload like
        # ``{'cmd': 'rm -rf /'}`` rendered the command as ``'rm -rf /'`` —
        # the closing quote immediately after ``/`` defeated rules whose
        # anchor expects ``/`` to be followed by whitespace/EOL/slash (e.g.
        # ``rm_rf_root``), letting the exact destructive commands the rules
        # target slip through this chokepoint. Joining the bare leaf strings
        # with newlines preserves each value's real boundaries.
        leaves = _collect_arg_strings(args)
        payload = "\n".join([f"tool={tool_name}", *leaves])
        return self._scan_via_backend(payload)

    def scan_output(self, text: str, known_prompt: str | None = None) -> ShieldVerdict:
        if not self._scan_output_enabled:
            return ShieldVerdict.allow()
        verdict = self._scan_via_backend(text)
        # Output-side detectors the input rule pack can't see: verbatim
        # system-prompt regurgitation and refusal-then-leak. Fail-open.
        if self.backend == self.BACKEND_NONE:
            return verdict
        threshold_idx = SEVERITY_ORDER.get(self.block_threshold, SEVERITY_ORDER["high"])
        extra_sev = "none"
        extra_reasons: list[str] = []

        # Output-policy detectors: verbatim system-prompt regurgitation,
        # refusal-then-leak. Fail-open.
        try:
            policy = output_policy_scan(text, known_prompt=known_prompt)
        except Exception as e:  # pragma: no cover -- detector bug must not block
            log.error("Shield output-policy scan failed (fail-open): %s", e)
            policy = None
        if (policy is not None and policy.blocked
                and SEVERITY_ORDER.get(policy.severity, -1) >= threshold_idx):
            extra_sev = _max_severity(extra_sev, policy.severity)
            extra_reasons += policy.reasons

        # Phishing-content detector: credential harvesting + deceptive links,
        # whether the agent fetched the content or is about to emit it. Fail-open.
        try:
            from .phishing import detect_phishing
            ph = detect_phishing(text)
        except Exception as e:  # pragma: no cover -- detector bug must not block
            log.error("Shield phishing scan failed (fail-open): %s", e)
            ph = None
        if (ph is not None and ph.suspicious
                and SEVERITY_ORDER.get(ph.severity, -1) >= threshold_idx):
            extra_sev = _max_severity(extra_sev, ph.severity)
            extra_reasons += [f"phishing: {r}" for r in ph.reasons]

        if not extra_reasons:
            return verdict
        if not verdict.allowed:
            return ShieldVerdict.block(
                severity=_max_severity(verdict.severity, extra_sev),
                reason="; ".join(verdict.reasons + extra_reasons),
            )
        return ShieldVerdict.block(severity=extra_sev, reason="; ".join(extra_reasons))


def _max_severity(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.get(a, -1) >= SEVERITY_ORDER.get(b, -1) else b
