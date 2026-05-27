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


def get_session_client(name: str, *, simulate_tools: bool = False) -> Any:
    """Lazy-instantiate the named session client.

    If ``simulate_tools=True``, the returned client is wrapped in
    ``SimulatedToolCallClient`` so callers can pass ``tools=[...]``
    even though the underlying consumer-chat endpoint has no native
    tool support.
    """
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
