"""Shared utilities for browser-session adapters.

Free functions, no base class. Each session adapter is small enough to
stand on its own; pulling these out avoids verbatim duplication of the
message-flattening and budget-estimation logic.
"""
from __future__ import annotations

import logging
from typing import Optional

from ..budget import Budget, BudgetExceeded

log = logging.getLogger(__name__)


def stringify_messages(system: str, messages: list[dict]) -> str:
    """Flatten Anthropic-format messages into a single prompt string.

    Consumer chat endpoints don't accept multi-turn history the way the
    official APIs do; the safest cross-version approach is to render
    the conversation as a single prompt the model sees as
    'context + new instruction'.
    """
    parts: list[str] = []
    if system:
        parts.append(f"[SYSTEM]\n{system}\n")
    for msg in messages:
        role = (msg.get("role") or "user").upper()
        content = msg.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text_buf: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_buf.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_buf.append(block)
            text = "\n".join(text_buf)
        else:
            text = str(content) if content is not None else ""
        parts.append(f"[{role}]\n{text}\n")
    return "\n".join(parts).strip()


def approx_record_budget(
    prompt: str,
    output: str,
    budget: Optional[Budget],
    model: str,
) -> None:
    """Best-effort token accounting from char counts (~4 chars/token).

    Consumer chat endpoints don't report usage, so this is the most we
    can do. Worth something for budget caps; not for billing accuracy.
    Failures here must never break the response path.
    """
    if budget is None:
        return
    in_tok = max(1, len(prompt) // 4)
    out_tok = max(1, len(output) // 4)
    try:
        budget.record_tokens(in_tok, out_tok, model=model)
    except BudgetExceeded:
        raise
    except Exception:
        log.exception("budget.record_tokens failed (non-fatal)")
