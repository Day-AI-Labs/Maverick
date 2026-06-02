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
from collections.abc import Iterable
from dataclasses import dataclass

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
    # Body allows `_` and `-`: real sk-proj- keys contain them, and a
    # `[a-zA-Z0-9]`-only body stopped at the first separator, detecting
    # (and thus redacting) only a prefix and leaking the rest of the key.
    ("openai_api_key",     re.compile(r"\bsk-(?:proj-)?[a-zA-Z0-9_-]{20,}")),
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
    # Council finding #14: coverage gaps that fed the tool-output exfil class.
    ("gitlab_pat",         re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("twilio_api_key",     re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    ("slack_webhook",      re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+")),
    # Connection strings carrying inline creds (postgres/mysql/mongodb/redis).
    ("db_connection_uri",  re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://"
        r"[^:@/\s]+:[^@/\s]+@[^\s]+"
    )),
    # Authorization: Bearer <token> headers (require a token-ish length to
    # avoid flagging the literal word "Bearer").
    # Bearer token charset includes +/= so base64 tokens are fully covered.
    ("bearer_header",      re.compile(r"(?i)\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9._\-+/=]{12,}")),
    # .env-style KEY=value lines whose name contains TOKEN/KEY/SECRET/
    # PASSWORD/PASS/CREDENTIAL. The module's docstring advertised "generic
    # high-entropy" coverage but no such rule existed, so a generically
    # named secret (INTERNAL_API_TOKEN=..., DB_PASSWORD=...) was written to
    # the audit log and fed back to the model in plaintext. Mirrors the
    # `env_secret` rule in maverick.secrets so both redactors agree. Only the
    # value (named group ``val``) is redacted, keeping the var name readable.
    ("env_secret",         re.compile(
        # Leading indentation is `[^\S\n]*` (horizontal whitespace), NOT `\s*`:
        # `\s` matches `\n`, and with re.MULTILINE the `(?:^|\n)` anchor fires
        # at every line start, so on a long newline run `\s*` backtracks O(N^2)
        # -- a ReDoS, since this scans attacker-influenced tool output. The
        # newline is already consumed by the `(?:^|\n)` anchor.
        r"(?:^|\n)[^\S\n]*(?:export\s+)?[A-Z][A-Z0-9_]*"
        r"(?:TOKEN|KEY|SECRET|PASSWORD|PASS|CREDENTIAL)[A-Z0-9_]*\s*=\s*"
        r"(?P<val>[^\s\n]+)",
        re.MULTILINE,
    )),
]


def scan(text: str) -> list[SecretMatch]:
    """Return all secret matches found in ``text``."""
    if not text:
        return []
    matches: list[SecretMatch] = []
    seen_spans: set[tuple[int, int]] = set()
    for name, pat in _PATTERNS:
        for m in pat.finditer(text):
            # Patterns may redact only a value sub-group (named ``val``),
            # e.g. ``env_secret`` keeps the ``NAME=`` prefix visible.
            grp = "val" if "val" in m.re.groupindex else 0
            span = m.span(grp)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            raw = m.group(grp)
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
