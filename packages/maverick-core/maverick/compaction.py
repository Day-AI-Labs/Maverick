"""Long-context compaction for the agent's running message list.

Karpathy SOTA-review item: 100k-token persistent episodes will choke
and pay full price every turn. The compaction policy:

* **Drop**: raw tool output blocks > MAX_TOOL_OUTPUT_BYTES (default
  2 KiB) older than KEEP_RECENT_TURNS turns; keep a one-line digest.
* **Summarize**: every DIGEST_EVERY turns, fold prior turns into one
  ``<digest>`` block prepended to the messages list; raw turns are
  removed.
* **Vector-index** (v0.3): episode digests get embedded so RAG can
  recover deep history. Not in this commit -- needs an embedding
  model wired through the provider layer first.

The "drop vs keep" boundary is hardcoded for now per the Karpathy
review: "start hardcoded ... then learn the what-to-keep gate from
outcome reward". That second half lands when we have outcome reward
signal end-to-end.

This module is pure-function: input is the current ``messages`` list
(Anthropic content-block format) plus a turn counter; output is the
new messages list. No I/O, no LLM calls (digest text uses a cheap
heuristic summary; the LLM-summarize variant is a follow-up).
"""
from __future__ import annotations

import os


# Tunables.
def _env_int(name: str, default: int) -> int:
    # A non-numeric env value used to raise ValueError at import, killing the
    # compaction path with an opaque traceback instead of using the default.
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


MAX_TOOL_OUTPUT_BYTES = _env_int("MAVERICK_COMPACT_MAX_TOOL_BYTES", 2 * 1024)
KEEP_RECENT_TURNS = _env_int("MAVERICK_COMPACT_KEEP_RECENT", 4)
DIGEST_EVERY = _env_int("MAVERICK_COMPACT_DIGEST_EVERY", 10)


def _block_size(block: dict) -> int:
    """Rough byte size of a content block."""
    if isinstance(block, dict):
        if block.get("type") == "text":
            return len(block.get("text", "") or "")
        if block.get("type") == "tool_result":
            content = block.get("content", "")
            if isinstance(content, list):
                return sum(_block_size(c) for c in content if isinstance(c, dict))
            return len(str(content))
        if block.get("type") == "tool_use":
            import json
            return len(json.dumps(block.get("input", {})))
        if block.get("type") == "image":
            src = block.get("source", {})
            return len(src.get("data", "")) if isinstance(src, dict) else 0
    return 0


def _shrink_tool_result(block: dict, max_bytes: int) -> dict:
    """Replace a large tool_result block with a one-line digest."""
    if not isinstance(block, dict) or block.get("type") != "tool_result":
        return block
    content = block.get("content", "")
    if isinstance(content, list):
        # Anthropic supports content as a list of blocks; join + measure.
        text_parts = [
            c.get("text", "") if isinstance(c, dict) else str(c)
            for c in content
        ]
        joined = "\n".join(text_parts)
    else:
        joined = str(content)
    if len(joined) <= max_bytes:
        return block
    digest = (
        joined[:200].rstrip()
        + f" ... [tool_result {len(joined)}B truncated; full output dropped from context]"
    )
    new_block = dict(block)
    new_block["content"] = digest
    return new_block


def _shrink_text_block(block: dict, max_bytes: int) -> dict:
    """Hint-and-truncate large 'text' blocks the agent emitted earlier."""
    if not isinstance(block, dict) or block.get("type") != "text":
        return block
    text = block.get("text", "") or ""
    if len(text) <= max_bytes:
        return block
    new_block = dict(block)
    new_block["text"] = (
        text[:max_bytes].rstrip()
        + f" ... [{len(text)}B truncated to {max_bytes}B]"
    )
    return new_block


def compact_messages(
    messages: list[dict],
    *,
    keep_recent: int = KEEP_RECENT_TURNS,
    max_tool_bytes: int = MAX_TOOL_OUTPUT_BYTES,
) -> list[dict]:
    """Return a compacted copy of ``messages``.

    Behavior:
    1. The last ``keep_recent`` messages pass through unchanged.
    2. Older messages have any tool_result block > ``max_tool_bytes``
       replaced with a digest, and any text block > ``max_tool_bytes``
       truncated.
    3. The first message (the user brief) is always preserved verbatim
       so the agent never loses the goal.
    """
    if len(messages) <= keep_recent + 1:
        return list(messages)

    out: list[dict] = []
    cutoff = len(messages) - keep_recent
    for i, msg in enumerate(messages):
        if i == 0 or i >= cutoff:
            out.append(msg)
            continue
        content = msg.get("content")
        if isinstance(content, list):
            new_content = []
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "tool_result":
                    new_content.append(_shrink_tool_result(blk, max_tool_bytes))
                elif isinstance(blk, dict) and blk.get("type") == "text":
                    new_content.append(_shrink_text_block(blk, max_tool_bytes))
                else:
                    new_content.append(blk)
            new_msg = dict(msg)
            new_msg["content"] = new_content
            out.append(new_msg)
        elif isinstance(content, str) and len(content) > max_tool_bytes:
            new_msg = dict(msg)
            new_msg["content"] = (
                content[:max_tool_bytes].rstrip()
                + f" ... [{len(content)}B truncated]"
            )
            out.append(new_msg)
        else:
            out.append(msg)
    return out


def should_digest(step: int, every: int = DIGEST_EVERY) -> bool:
    """Returns True when the agent should fold prior turns into a digest.

    Called at the top of every loop iteration; the agent uses this to
    decide whether to call the LLM-summarizer for an episode digest
    (separate code path, since it spends budget).
    """
    return step > 0 and step % every == 0


def make_heuristic_digest(messages: list[dict]) -> str:
    """Build a structural digest of prior turns without calling an LLM.

    Used when budget is too tight to spend a summarizer call. The
    digest preserves: count of turns, tool names invoked + counts,
    and the original user brief. Keeps the agent oriented even after
    aggressive truncation.
    """
    if not messages:
        return ""
    n = len(messages)
    tool_counts: dict[str, int] = {}
    first_user = ""
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") == "user" and not first_user:
            if isinstance(content, str):
                first_user = content[:400]
            elif isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        first_user = (blk.get("text", "") or "")[:400]
                        break
        if isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    name = blk.get("name", "?")
                    tool_counts[name] = tool_counts.get(name, 0) + 1
    tools_summary = ", ".join(
        f"{n}({c})" for n, c in sorted(tool_counts.items(), key=lambda kv: -kv[1])
    ) or "(no tools used)"
    return (
        f"<digest>\n"
        f"original brief: {first_user}\n"
        f"prior turns: {n}\n"
        f"tools invoked: {tools_summary}\n"
        f"</digest>"
    )
