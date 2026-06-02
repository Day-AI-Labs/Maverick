"""Shared utilities for browser-session adapters.

Free functions, no base class. Each session adapter is small enough to
stand on its own; pulling these out avoids verbatim duplication of the
message-flattening and budget-estimation logic.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from ..budget import Budget, BudgetExceeded

log = logging.getLogger(__name__)


def _looks_complete(buffered: list[str]) -> bool:
    """Whether the accumulated ``data:`` lines already form one JSON value.

    Used to split streams that omit the spec-mandated blank line between
    events (which these consumer providers do -- they emit one
    ``data: {json}`` per line). A buffer that already parses on its own is
    a finished single-line event, so the next ``data:`` line begins a new
    one rather than being glued on.
    """
    if not buffered:
        return False
    text = "\n".join(buffered).strip()
    if not text:
        return False
    if text == "[DONE]":
        return True
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def iter_sse_data_payloads(stream_text: str) -> Iterator[str]:
    """Yield each SSE event's joined ``data:`` payload.

    Per the SSE spec a single event may carry multiple ``data:`` lines;
    the field value is the lines joined with ``"\\n"`` and the event is
    dispatched on a blank line. Splitting on physical lines and decoding
    each one drops any event whose ``data:`` spans multiple lines (e.g.
    pretty-printed JSON), so we accumulate and flush on the blank line.

    These consumer endpoints also stream without the blank-line separator,
    one complete ``data: {json}`` per line, so we additionally flush before
    starting a new ``data:`` line once the buffer already parses as one
    value -- handling both framings without dropping multi-line events.
    """
    data_lines: list[str] = []

    def _flush() -> Iterator[str]:
        if data_lines:
            yield "\n".join(data_lines)
            data_lines.clear()

    for line in stream_text.splitlines():
        if line == "":
            yield from _flush()
            continue
        if line.startswith("data:"):
            # A single leading space after the colon is part of the
            # framing, not the value; strip only that.
            value = line[len("data:"):]
            if value.startswith(" "):
                value = value[1:]
            # No blank-line separator was emitted but the buffer is already
            # a complete event: dispatch it before starting the next.
            if _looks_complete(data_lines):
                yield from _flush()
            data_lines.append(value)
        # Other SSE fields (event:, id:, retry:, comments) terminate any
        # implicit framing only at the blank line, so we ignore them here.
    yield from _flush()


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
    budget: Budget | None,
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
