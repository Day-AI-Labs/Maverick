"""Secret scrubber for logs + error messages.

Privacy reviewer flagged that LLM exceptions, MCP stderr drains, and
`subprocess.run` stdout were being logged verbatim — any of which could
contain API keys / bearer tokens / .env values. This module gives a
single ``scrub(text)`` that pattern-matches the common shapes and
redacts them to ``[REDACTED:<kind>]``.

The patterns aren't exhaustive (a determined exfiltrator can wrap
secrets in something unusual), but they cover what people accidentally
paste into goal descriptions, what shell tools echo by mistake, and
what LLM error payloads tend to include.
"""
from __future__ import annotations

import re

# Each entry: (kind, regex). Order matters -- longer / more specific
# patterns run first so they don't get partially matched by generic ones.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Anthropic API key (sk-ant-...)
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    # Stripe secret/restricted key (sk_live_, sk_test_, rk_live_, rk_test_).
    # Underscore-delimited, so the openai `sk-` pattern never matches it.
    ("stripe_key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    # OpenAI / OpenRouter key (sk-...)
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    # Google / GCP API key (AIza...)
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    # AWS access key id
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # GitHub PAT (ghp_/gho_/ghu_/ghr_/ghs_ prefix)
    ("github_token", re.compile(r"\bgh[ps]_[A-Za-z0-9_]{30,}\b|\bghu_[A-Za-z0-9_]{30,}\b|\bgho_[A-Za-z0-9_]{30,}\b|\bghr_[A-Za-z0-9_]{30,}\b")),
    # Slack tokens (xoxb-, xoxp-, xapp-)
    ("slack_token", re.compile(r"\bxox[bpaors]-[A-Za-z0-9-]{10,}\b")),
    # Generic bearer header (Authorization: Bearer ...)
    ("bearer", re.compile(r"(?i)\b(authorization\s*:\s*bearer\s+)([A-Za-z0-9._\-+/=]{16,})")),
    # .env-style KEY=value lines (only the value part; only redact when key
    # contains TOKEN / KEY / SECRET / PASSWORD / PASS / CREDENTIAL). Tolerates
    # a leading `export ` so shell-style `export FOO_TOKEN=...` is covered too.
    ("env_secret", re.compile(
        r"((?:^|\n)\s*(?:export\s+)?[A-Z][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASS|CREDENTIAL)[A-Z0-9_]*\s*=\s*)"
        # Value: a single- or double-quoted string (which may contain
        # spaces) OR a bare run of non-space chars. Without the quoted
        # alternatives a value like FOO_SECRET="a b c" matched only "a,
        # leaving `b c"` -- the real secret -- unredacted.
        r"(\"[^\"\n]*\"|'[^'\n]*'|[^\s\n]+)",
        re.MULTILINE,
    )),
    # JWT (three base64url segments separated by dots, common shape)
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    # Credential carried in a URL query string (?access_token=..., &api_key=...,
    # presigned-URL ?sig=..., webhook ?token=...). The env_secret pattern only
    # matches uppercase KEY=value at line start, so these slipped through into
    # logs / audit / replay exports verbatim. Group 1 keeps the "?key=" prefix.
    ("url_secret", re.compile(
        r"(?i)([?&](?:access_token|api_key|apikey|auth_token|token|secret|"
        r"password|passwd|sig|signature|client_secret)=)([^&#\s\"']+)",
    )),
]


def scrub(text: str) -> str:
    """Return a copy of ``text`` with detected secrets replaced.

    The replacement preserves enough structure that the redacted result
    is still useful for debugging (you can see WHAT got redacted), but
    the actual secret value is gone.
    """
    if not text:
        return text
    out = text
    for kind, pat in _PATTERNS:
        if kind in ("bearer", "env_secret", "url_secret"):
            out = pat.sub(lambda m: m.group(1) + f"[REDACTED:{kind}]", out)
        else:
            out = pat.sub(f"[REDACTED:{kind}]", out)
    return out
