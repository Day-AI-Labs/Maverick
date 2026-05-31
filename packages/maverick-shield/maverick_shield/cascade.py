"""Constitutional Classifier v2 cascaded scan tier.

Anthropic's Jan 2026 paper (Constitutional Classifiers v2) ships a
two-tier defense: a CHEAP first-pass classifier flags candidates, and
only flagged texts get the EXPENSIVE second-pass classifier. The cheap
pass uses lightweight features (regex hits, n-gram heuristics, length,
unicode anomalies); the expensive pass is an LLM-based judge. Cut
jailbreak success 86% -> 4.4% with much lower compute than v1.

This module wraps the existing Shield's scan_* methods with that
cascade. When `MAVERICK_CASCADE_SHIELD=1`, every call goes through
the cheap probe first; ONLY on probe-flagged texts do we invoke the
LLM-based deep scan. Default OFF (back-compat).

The expensive scanner is pluggable: pass a callable returning
ShieldVerdict at construction. When None, deep-pass falls back to the
existing builtin/Shield rules.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


# Cheap-pass signals. These are heuristics tuned to maximize RECALL
# (false positive is fine -- the expensive pass filters); they should
# NEVER be the sole defense.
_PROBE_REGEX = re.compile(
    r"""
    (ignore\s+(?:\w+\s+){0,3}(instructions?|prompts?|directives?))
    | (system\s*(prompt|message)\s*[:=])
    | ((</?system>)|(\[INST\])|(<\|im_start\|>))   # ChatML / Llama markers
    | (rm\s+-rf\s+/(?:\s|$|\*))
    | (curl\s+[^|]+\|\s*(sh|bash|python))
    | (eval\s*\(\s*request|exec\s*\(\s*(stdin|input))
    | (\.env\b|\.aws/credentials|id_rsa\b|\.ssh/id_)
    | (drop\s+table|;\s*drop\s+)
    | (jailbreak|DAN\s+mode|developer\s+mode)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Unicode tag block U+E0000–U+E007F (steganographic invisible chars).
_TAG_RE = re.compile(r"[\U000E0000-\U000E007F]")
# Zero-width / format chars.
_INVISIBLE_RE = re.compile(r"[​-‏‪-‮⁠-⁯]")


@dataclass
class ProbeSignal:
    flagged: bool
    score: float
    reasons: list[str]


def cheap_probe(text: str) -> ProbeSignal:
    """Constitutional v2-style cheap classifier.

    Returns a ProbeSignal with score in [0,1] and reasons. Threshold for
    "flagged" is 0.3 by default -- intentionally low so we err toward
    sending more texts to the deep scan. The deep scan can still pass.
    """
    if not text:
        return ProbeSignal(flagged=False, score=0.0, reasons=[])

    score = 0.0
    reasons: list[str] = []
    text_l = text.lower()

    # Regex hits.
    m = _PROBE_REGEX.search(text_l)
    if m:
        score += 0.5
        reasons.append(f"pattern: {m.group(0)[:40]}")

    # Unicode tag smuggling.
    if _TAG_RE.search(text):
        score += 0.4
        reasons.append("unicode tag chars")
    if _INVISIBLE_RE.search(text):
        score += 0.2
        reasons.append("zero-width / bidi chars")

    # Heavy obfuscation: very long unbroken non-ASCII run.
    non_ascii = sum(1 for c in text if ord(c) > 127)
    if non_ascii > 100 and non_ascii / max(len(text), 1) > 0.5:
        score += 0.15
        reasons.append("majority non-ASCII")

    # Base64-shaped block of suspicious length.
    if re.search(r"[A-Za-z0-9+/]{200,}={0,2}", text):
        score += 0.15
        reasons.append("base64-shaped large blob")

    # Encoded payload markers: \x.., \u....
    if re.search(r"\\x[0-9a-fA-F]{2}.{0,10}\\x[0-9a-fA-F]{2}", text):
        score += 0.15
        reasons.append("hex-escape payload")

    flagged = score >= 0.3
    return ProbeSignal(flagged=flagged, score=min(score, 1.0), reasons=reasons)


@dataclass
class CascadedShield:
    """Wraps the existing Shield in a cheap-then-deep cascade.

    Usage::

        shield = CascadedShield(base=Shield.from_config())
        shield.scan_input(text)   # cheap probe -> base scan if flagged

    `base` is the existing Shield (or any object exposing scan_input /
    scan_tool_call / scan_output). When probe says "clean", we short-
    circuit allow without paying the deep-scan cost.
    """
    base: object
    deep_threshold: float = 0.3
    deep_scan_input: Callable | None = None
    deep_scan_output: Callable | None = None

    @classmethod
    def from_config(cls) -> CascadedShield:
        from .guard import Shield  # local import to avoid cycle
        return cls(base=Shield.from_config())

    @property
    def backend(self) -> str:
        return f"cascade({getattr(self.base, 'backend', 'unknown')})"

    @property
    def enabled(self) -> bool:
        return getattr(self.base, "enabled", True)

    def scan_input(self, text: str):
        probe = cheap_probe(text)
        if probe.flagged or probe.score >= self.deep_threshold:
            verdict = (
                self.deep_scan_input(text) if self.deep_scan_input
                else self.base.scan_input(text)
            )
            # Cascade reasons annotate the verdict.
            if probe.reasons and getattr(verdict, "reasons", None) is not None:
                try:
                    verdict.reasons = list(verdict.reasons) + [
                        f"cheap-probe: {r}" for r in probe.reasons
                    ]
                except Exception:  # pragma: no cover
                    pass
            return verdict
        # Probe says clean -> short-circuit accept.
        from .guard import ShieldVerdict
        return ShieldVerdict(allowed=True, severity="info", reasons=[])

    def scan_tool_call(self, tool_name: str, args: dict):
        # Tool calls always go through the base scanner because the
        # call pattern (tool name + args) is small + structured; no
        # cheap-probe step saves measurable compute.
        return self.base.scan_tool_call(tool_name, args)

    def scan_output(self, text: str):
        probe = cheap_probe(text)
        if probe.flagged or probe.score >= self.deep_threshold:
            verdict = (
                self.deep_scan_output(text) if self.deep_scan_output
                else self.base.scan_output(text)
            )
            if probe.reasons and getattr(verdict, "reasons", None) is not None:
                try:
                    verdict.reasons = list(verdict.reasons) + [
                        f"cheap-probe: {r}" for r in probe.reasons
                    ]
                except Exception:  # pragma: no cover
                    pass
            return verdict
        from .guard import ShieldVerdict
        return ShieldVerdict(allowed=True, severity="info", reasons=[])


def cascade_enabled() -> bool:
    if os.environ.get("MAVERICK_CASCADE_SHIELD", "").lower() in ("1", "true", "yes"):
        return True
    try:
        from maverick.config import load_config
        return bool(load_config().get("safety", {}).get("cascade", False))
    except Exception:
        return False


def normalize_for_probe(text: str) -> str:
    """NFKC + strip invisible chars before probing. Defends against
    obfuscation that uses Unicode normalization round-tripping."""
    if not text:
        return text
    normalized = unicodedata.normalize("NFKC", text)
    return _INVISIBLE_RE.sub("", _TAG_RE.sub("", normalized))
