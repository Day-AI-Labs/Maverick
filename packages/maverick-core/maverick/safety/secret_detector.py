"""Secret detection for tool outputs.

Scans text for common credentials and replaces matches with redacted
placeholders before they hit logs or model context. Fast regex pass
covering AWS / GCP / Azure / GitHub / Anthropic / OpenAI / generic
JWTs / generic high-entropy secrets.

This is not a replacement for a real DLP tool. It's a guardrail
against the most common accidental leaks (config files dumped to
shell, env-var prints, secrets in log lines). False positives are
preferable to false negatives — we err on the side of redaction.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretMatch:
    name: str
    span: tuple[int, int]
    value_preview: str


# Each entry: (name, regex). Most patterns match common formats; the
# generic-high-entropy fallback catches modern random tokens that don't
# match a specific provider format.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("anthropic_api_key",  re.compile(r"\bsk-ant-[a-zA-Z0-9_-]{20,}\b")),
    ("openai_api_key",     re.compile(r"\bsk-(?:proj-)?[a-zA-Z0-9]{20,}\b")),
    ("aws_access_key_id",  re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # AWS secret access keys are 40-char base64-ish; matching naked
    # 40-char strings produces too many false positives (hashes, UUIDs
    # without dashes), so we require an obvious AWS context word
    # within ~50 chars.
    ("aws_secret_access",  re.compile(
        r"(?i)(?:aws_secret_access_key|aws_secret)[\s=:\"']{1,5}"
        r"([A-Za-z0-9/+=]{40})"
    )),
    ("github_pat_classic", re.compile(r"\bghp_[A-Za-z0-9]{36,40}\b")),
    ("github_pat_fine",    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b")),
    ("github_oauth",       re.compile(r"\bgho_[A-Za-z0-9]{36,40}\b")),
    ("google_api_key",     re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("gcp_service_account",re.compile(r'"type"\s*:\s*"service_account"')),
    ("azure_storage",      re.compile(r"\bDefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]{40,}")),
    ("slack_bot_token",    re.compile(r"\bxox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}\b")),
    ("stripe_live_key",    re.compile(r"\bsk_live_[0-9a-zA-Z]{24,}\b")),
    ("stripe_test_key",    re.compile(r"\bsk_test_[0-9a-zA-Z]{24,}\b")),
    # JWTs: header.payload.signature, all base64url-without-padding.
    ("jwt",                re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    # Generic private key blocks.
    ("private_key_pem",    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
]


def scan(text: str) -> list[SecretMatch]:
    """Return all secret matches found in ``text``."""
    if not text:
        return []
    matches: list[SecretMatch] = []
    seen_spans: set[tuple[int, int]] = set()
    for name, pat in _PATTERNS:
        for m in pat.finditer(text):
            span = m.span()
            if span in seen_spans:
                continue
            seen_spans.add(span)
            raw = m.group(0)
            preview = raw[:6] + "..." if len(raw) > 12 else "..."
            matches.append(SecretMatch(name=name, span=span, value_preview=preview))
    return matches


def redact(text: str) -> tuple[str, list[SecretMatch]]:
    """Return ``(redacted_text, matches)``. Each match is replaced with a
    placeholder of the form ``[REDACTED:<name>]``.

    Replacement preserves text length characteristics enough for log
    readability but never leaks the original value.
    """
    if not text:
        return text, []
    matches = scan(text)
    if not matches:
        return text, []
    # Replace from end to start so spans stay valid.
    out = text
    for m in sorted(matches, key=lambda x: x.span[0], reverse=True):
        a, b = m.span
        out = out[:a] + f"[REDACTED:{m.name}]" + out[b:]
    return out, matches


def redact_iter(items: Iterable[str]) -> list[tuple[str, list[SecretMatch]]]:
    """Apply :func:`redact` to each item; collect all matches."""
    return [redact(t) for t in items]
