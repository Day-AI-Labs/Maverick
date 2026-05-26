"""EU AI Act Article 50 transparency disclosure for channel users.

The EU AI Act becomes enforceable Aug 2 2026 — see May 2026 Commission
guidelines covering agentic AI as a single high-risk system. Article 50
mandates that users interacting with a chatbot must be informed they
are talking to AI unless that fact is obvious from context.

This module gives the channel server a single function:

    disclosure = first_turn_disclosure(channel, user_id)

It returns the disclosure string to PREPEND to the agent's first reply
on each new conversation, or None if the user has already seen it (we
track via the world model's conversations.last_seen vs created_at).
"""
from __future__ import annotations

import os
from typing import Optional


# Default text. Can be overridden via:
#   MAVERICK_AI_DISCLOSURE="<your custom text>"
# or [compliance] disclosure_text in ~/.maverick/config.toml.
DEFAULT_DISCLOSURE = (
    "Hi -- I'm Maverick, an AI assistant. Conversations may be reviewed "
    "for safety. Reply STOP to end."
)


_UNSET = object()


def _custom_disclosure():
    """Return a 3-state result:
      - explicit non-empty string  -> use it
      - explicit empty string      -> opt-out (return "")
      - not configured at all      -> _UNSET (caller uses default)
    """
    env = os.environ.get("MAVERICK_AI_DISCLOSURE")
    if env is not None:
        return env
    try:
        from .config import load_config
        text = load_config().get("compliance", {}).get("disclosure_text")
        if text is not None:
            return text
    except Exception:
        pass
    return _UNSET


def first_turn_disclosure(
    world,
    channel: str,
    user_id: str,
) -> Optional[str]:
    """Return the AI disclosure string for the user's first turn, or None.

    "First turn" = no prior conversation row OR the conversation has
    zero assistant turns yet. Subsequent turns on the same conversation
    return None so we don't spam the user. Per Article 50 the user
    must be informed at the start of the interaction.

    The conversation row is created/updated as a side effect to keep
    this idempotent across retries.
    """
    conv = world.get_or_create_conversation(channel=channel, user_id=user_id)
    # If any prior assistant turn exists, the user has already seen
    # the disclosure (or the operator opted out via empty text). Skip.
    prior = world.recent_turns(conv.id, limit=1)
    for t in prior:
        if t.role == "assistant":
            return None
    text = _custom_disclosure()
    if text is _UNSET:
        text = DEFAULT_DISCLOSURE
    if not text or not text.strip():
        # Operator explicitly opted out (empty string). Don't disclose.
        return None
    return text
