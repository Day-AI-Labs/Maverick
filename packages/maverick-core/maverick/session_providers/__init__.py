"""Browser-session providers.

Lets users drive Maverick agents using their existing consumer
chat subscriptions (ChatGPT Plus, Claude Pro, Kimi, Grok Premium,
Gemini Advanced) instead of (or alongside) paid API keys.

Mechanism: the user signs into the provider in their normal browser,
the wizard captures the session cookie (either via Playwright auto-
capture if available, or manual DevTools paste). The agent replays
that cookie against the same internal endpoints the web UI uses.

Tool-call simulation:
  Consumer chat endpoints don't expose native function-calling. The
  ``SimulatedToolCallClient`` wrapper renders ``tools=[...]`` as a
  markdown protocol the model can follow, then parses tool calls back
  out of the response text. ``get_session_client(..., simulate_tools=
  True)`` returns a pre-wrapped client. The LLM facade auto-wraps
  session clients so tool-using roles work transparently.

Spec format in config.toml:
    orchestrator = "chatgpt-session:gpt-4o"
    summarizer   = "claude-session:claude-haiku-4-5"

Caveats (surfaced in the wizard):
  - Programmatic use of consumer chat may violate the provider's ToS.
    Maverick only operates on the user's own session against their
    own account. We never bypass CAPTCHA, rate limits, or any other
    security control.
  - Cookies expire periodically (~1h for ChatGPT, ~weeks for Claude,
    varies for the others). Re-import via `maverick session import`.
"""
from __future__ import annotations

from typing import Any

_SESSION_PROVIDERS = {
    "chatgpt-session":  ("chatgpt", "openai-session"),
    "claude-session":   ("claude", "anthropic-session", "claude-ai"),
    "kimi-session":     ("kimi", "moonshot-session"),
    "grok-session":     ("grok", "xai-session", "x-grok"),
    "gemini-session":   ("gemini", "google-session", "bard-session"),
}


def _canonical(name: str) -> str:
    lower = (name or "").strip().lower()
    if lower in _SESSION_PROVIDERS:
        return lower
    for canon, aliases in _SESSION_PROVIDERS.items():
        if lower in aliases:
            return canon
    return lower


def is_session_provider(name: str) -> bool:
    """True if ``name`` (or one of its aliases) names a session provider."""
    return _canonical(name) in _SESSION_PROVIDERS


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _explicit_opt_in(value: Any) -> bool:
    """Return True only for explicit session-provider opt-in values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    if isinstance(value, int):
        return value == 1
    return False


def _session_providers_enabled() -> bool:
    """Session providers drive a vendor's *consumer* chat UI with captured
    login cookies -- against that vendor's Terms of Service, with real
    account-ban risk for the user. The capability is OFF unless explicitly
    opted into, so it can never run by accident. Enable with
    ``MAVERICK_ENABLE_SESSION_PROVIDERS=1`` or ``[session_providers] enabled
    = true`` in ``~/.maverick/config.toml``.
    """
    import os
    if _explicit_opt_in(os.environ.get("MAVERICK_ENABLE_SESSION_PROVIDERS", "")):
        return True
    try:
        from ..config import load_config
        sec = (load_config() or {}).get("session_providers") or {}
        return _explicit_opt_in(sec.get("enabled", False))
    except Exception:
        return False


def get_session_client(name: str, *, simulate_tools: bool = False) -> Any:
    """Lazy-instantiate the named session client.

    If ``simulate_tools=True``, the returned client is wrapped in
    ``SimulatedToolCallClient`` so callers can pass ``tools=[...]``
    even though the underlying consumer-chat endpoint has no native
    tool support.

    Gated behind an explicit opt-in (see ``_session_providers_enabled``):
    these drive consumer chat UIs against the vendor's ToS, so they must
    never run unless the operator turned them on.
    """
    if not _session_providers_enabled():
        raise RuntimeError(
            f"session provider {name!r} is disabled. Session providers drive "
            "a vendor's consumer chat UI with captured login cookies, which "
            "violates their ToS and can get your account banned. To opt in, "
            "set MAVERICK_ENABLE_SESSION_PROVIDERS=1 (or [session_providers] "
            "enabled = true in ~/.maverick/config.toml)."
        )
    canon = _canonical(name)
    inner: Any
    if canon == "chatgpt-session":
        from .chatgpt_session import ChatGPTSessionClient
        inner = ChatGPTSessionClient()
    elif canon == "claude-session":
        from .claude_session import ClaudeSessionClient
        inner = ClaudeSessionClient()
    elif canon == "kimi-session":
        from .kimi_session import KimiSessionClient
        inner = KimiSessionClient()
    elif canon == "grok-session":
        from .grok_session import GrokSessionClient
        inner = GrokSessionClient()
    elif canon == "gemini-session":
        from .gemini_session import GeminiSessionClient
        inner = GeminiSessionClient()
    else:
        raise ValueError(
            f"unknown session provider {name!r}. Available: "
            + ", ".join(KNOWN_SESSION_PROVIDERS)
        )
    if simulate_tools:
        from .tool_simulator import SimulatedToolCallClient
        return SimulatedToolCallClient(inner)
    return inner


KNOWN_SESSION_PROVIDERS = tuple(_SESSION_PROVIDERS.keys())


__all__ = [
    "get_session_client", "is_session_provider", "KNOWN_SESSION_PROVIDERS",
]
