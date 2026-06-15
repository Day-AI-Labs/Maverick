"""PII detector for tool outputs.

Pattern-based: emails, US phone numbers, SSN, IP addresses, credit
card numbers (Luhn-validated), street addresses (heuristic). Lighter
than presidio but covers the common categories. Used by the audit
log + shield to redact when the user opts in.

Returns the same kind of (text, matches) tuple as secret_detector so
callers can compose them.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)


# Non-revealing preview persisted in the audit log. PIIMatch previews are
# written to disk, so they must NOT embed any raw PII (the old code stored the
# first 4 chars of the value -- leaking SSN area numbers, partial phones/emails/
# IPs into the very log the redactor is meant to protect).
_MASK = "[…]"


@dataclass(frozen=True)
class PIIMatch:
    kind: str
    span: tuple[int, int]
    value_preview: str


_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
# US phone: 555-555-5555, (555) 555-5555, +1 555 555 5555, 5555555555.
# The leading (?<!\d) stops the pattern from matching a 10-digit *sub-run* of a
# longer number (e.g. a 13-19 digit string), which otherwise produced a partial
# redaction that leaked the leading digits.
_PHONE_US = re.compile(
    r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)
# SSN: NNN-NN-NNNN with reasonable bounds (no 000/666/9xx area, etc).
_SSN = re.compile(
    r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"
)
_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
_IPV6 = re.compile(
    # Full AND ::-compressed forms -- the old pattern required 8 written
    # hextets, so it missed every real-world compressed address (2001:db8::1,
    # fe80::1, ::1), i.e. IPv6 PII was essentially never redacted.
    #
    # Order matters: Python's `|` is leftmost-match, NOT longest-match, so every
    # form that ends in a hextet MUST precede the bare "trailing ::" form. The
    # old order put `(?:hex:){1,7}:` first, so "2001:db8::1" matched only
    # "2001:db8::" and leaked the final hextet (user-testing finding).
    # Alternatives are ordered by DESCENDING count of hextets after "::" so the
    # longest match always wins under leftmost-match. A 1-trailing-hextet form
    # ahead of a 2-trailing one would leak the tail (2001:db8::dead:beef ->
    # "...::dead" leaving ":beef").
    r"(?:"
    r"(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}"
    r"|:(?::[0-9a-fA-F]{1,4}){1,7}"
    r"|[0-9a-fA-F]{1,4}:(?::[0-9a-fA-F]{1,4}){1,6}"
    r"|(?:[0-9a-fA-F]{1,4}:){1,2}(?::[0-9a-fA-F]{1,4}){1,5}"
    r"|(?:[0-9a-fA-F]{1,4}:){1,3}(?::[0-9a-fA-F]{1,4}){1,4}"
    r"|(?:[0-9a-fA-F]{1,4}:){1,4}(?::[0-9a-fA-F]{1,4}){1,3}"
    r"|(?:[0-9a-fA-F]{1,4}:){1,5}(?::[0-9a-fA-F]{1,4}){1,2}"
    r"|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}"
    r"|(?:[0-9a-fA-F]{1,4}:){1,7}:"
    r"|::"
    r")"
)
# Credit card candidates (13-19 digits with optional spaces / dashes).
_CC = re.compile(
    r"\b(?:\d[ -]*?){13,19}\b"
)
# US street address heuristic: number + 1-3 words + street suffix.
_STREET = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Lane|Ln|"
    r"Drive|Dr|Court|Ct|Way|Parkway|Pkwy|Place|Pl)\b",
)


def _luhn_valid(digits: str) -> bool:
    """Standard Luhn check. Filters out non-card 16-digit strings."""
    s = re.sub(r"[^\d]", "", digits)
    if not 13 <= len(s) <= 19:
        return False
    total = 0
    parity = len(s) % 2
    for i, c in enumerate(s):
        d = int(c)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan(text: str) -> list[PIIMatch]:
    """Return non-overlapping PII matches found in ``text``."""
    if not text:
        return []
    found: list[PIIMatch] = []

    for name, pat in (
        ("email", _EMAIL),
        ("ssn", _SSN),
        ("ipv4", _IPV4),
        ("ipv6", _IPV6),
        ("phone_us", _PHONE_US),
        ("street_address", _STREET),
    ):
        for m in pat.finditer(text):
            found.append(PIIMatch(kind=name, span=m.span(), value_preview=_MASK))

    # Credit cards: extra step. Test candidates with Luhn so we don't
    # tag random 16-digit strings (UUIDs without dashes, hashes).
    for m in _CC.finditer(text):
        if _luhn_valid(m.group(0)):
            found.append(PIIMatch(kind="credit_card", span=m.span(), value_preview=_MASK))

    # Coalesce overlapping spans into one redaction range per cluster. Two kinds
    # can match overlapping regions (e.g. a credit-card span and a phone sub-run
    # of the same digits); reverse-order splicing of overlapping spans corrupts
    # output, while dropping later overlaps can leave the later match's tail
    # exposed. Redacting the union ensures no portion of an overlap cluster leaks.
    found.sort(key=lambda m: (m.span[0], -(m.span[1] - m.span[0])))
    out: list[PIIMatch] = []
    for m in found:
        if not out or m.span[0] >= out[-1].span[1]:
            out.append(m)
            continue

        prev = out[-1]
        merged_end = max(prev.span[1], m.span[1])
        if merged_end != prev.span[1]:
            out[-1] = PIIMatch(
                kind=prev.kind,
                span=(prev.span[0], merged_end),
                value_preview=prev.value_preview,
            )
    return out


def redact(text: str) -> tuple[str, list[PIIMatch]]:
    """Replace PII with placeholders of the form ``[REDACTED:<kind>]``."""
    if not text:
        return text, []
    matches = scan(text)
    if not matches:
        return text, []
    out = text
    for m in sorted(matches, key=lambda x: x.span[0], reverse=True):
        a, b = m.span
        out = out[:a] + f"[REDACTED:{m.kind}]" + out[b:]
    return out, matches


# NOTE on the native engine: rust/mvk-scan ships a byte-for-byte port of this
# scanner (maverick_native.pii_scan_spans), but it is NOT wired into this Python
# hot path -- CPython's compiled `re` measured at parity / slightly faster than
# the native port here (see rust/README.md). The native build serves the
# TypeScript / edge runtimes that have no `re`; tests/test_native_detect_parity.py
# keeps it byte-for-byte identical to this module.

__all__ = ["scan", "redact", "PIIMatch"]
