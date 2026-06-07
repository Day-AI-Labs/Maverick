"""Long-context compaction for the agent's running message list.

Karpathy SOTA-review item: 100k-token persistent episodes will choke
and pay full price every turn. The compaction policy:

* **Drop**: raw tool output blocks > MAX_TOOL_OUTPUT_BYTES (default
  2 KiB) older than KEEP_RECENT_TURNS turns; keep a one-line digest.
* **Summarize**: every DIGEST_EVERY turns, fold prior turns into one
  ``<digest>`` block prepended to the messages list; raw turns are
  removed.
* **Vector-index** (v0.3): episode digests get embedded so RAG can
  recover deep history. See ``DigestIndex`` / ``recall_relevant_digests``
  below -- an opt-in, fail-open retrieval path. The embedder is injected
  (``Embedder`` protocol); the default one lazily wraps the repo's
  optional ``fastembed`` backend and is absent unless that lib is
  installed. ``compact_messages`` behavior is unchanged when no
  embedder/index is supplied.

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

import math
import os
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


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


_LOCATOR_KEYS = ("path", "url", "file", "filename", "target", "uri", "page")


def _source_locator(tool_use: dict | None) -> tuple[str, str]:
    """Best-effort ``(tool_name, locator)`` for the tool_use that produced a
    result, so a shrunk tool_result keeps the *identity* of what it read (the
    file path / url) instead of an opaque "output dropped". ``('', '')`` when
    unknown."""
    if not isinstance(tool_use, dict):
        return "", ""
    name = str(tool_use.get("name", "") or "")
    inp = tool_use.get("input") or {}
    locator = ""
    if isinstance(inp, dict):
        for k in _LOCATOR_KEYS:
            v = inp.get(k)
            if isinstance(v, str) and v.strip():
                locator = v.strip()
                break
    return name, locator


def _canonical_tool_result_text(text: str) -> str:
    """Return the stable tool payload for hashing/previews.

    Agent._run_tool stores model-facing results inside a ``<tool_output ...>``
    frame with a fresh random nonce per call. Structural compaction references
    should identify the underlying tool output, not that per-call frame, so
    strip the frame when it is present. Any loop-guard guidance appended after
    the closing frame is also excluded because it is not tool output.
    """
    if not text.startswith("<tool_output "):
        return text
    nl = text.find("\n")
    if nl == -1:
        return text
    inner = text[nl + 1:]
    close = inner.rfind("\n</tool_output ")
    if close == -1:
        return text
    return inner[:close]


def _shrink_tool_result(
    block: dict, max_bytes: int, source: tuple[str, str] | None = None
) -> dict:
    """Replace a large tool_result with a content-addressed structural reference.

    Rather than an opaque "full output dropped", the digest keeps a short preview
    plus a structural ref — the originating tool + locator (file path / url) and a
    ``sha256`` + byte size. So the agent retains *what* was read and can re-run the
    tool to retrieve the full output (and the hash lets it detect a change), which
    is far more useful than arbitrary truncated bytes for the common file-read /
    fetch case. Idempotent: a result already at/under ``max_bytes`` is returned
    unchanged, so a second compaction pass is a no-op.
    """
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
    canonical = _canonical_tool_result_text(joined)
    import hashlib
    sha = hashlib.sha256(canonical.encode("utf-8", "replace")).hexdigest()[:12]
    name, locator = source or ("", "")
    if name and locator:
        src = f"{name}({locator}) "
    elif name:
        src = f"{name} "
    else:
        src = ""
    digest = (
        canonical[:160].rstrip()
        + f" ... [{src}output {len(canonical)}B truncated, sha256:{sha} — dropped from"
        " context; re-run the tool to retrieve the full output]"
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

    # Index tool_use blocks by id so a shrunk tool_result can name its source
    # (the tool + the file path / url it read) in the structural reference.
    tool_use_by_id: dict[str, dict] = {}
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    bid = blk.get("id")
                    if isinstance(bid, str):
                        tool_use_by_id[bid] = blk

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
                    source = _source_locator(tool_use_by_id.get(blk.get("tool_use_id")))
                    new_content.append(_shrink_tool_result(blk, max_tool_bytes, source))
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


# --------------------------------------------------------------------------
# Vector-index (RAG) path for episode digests.
#
# Opt-in and fail-open: nothing here runs unless a caller builds a
# ``DigestIndex`` and supplies an ``Embedder``. ``compact_messages`` is
# untouched. Embedding the deep history lets a long run recall digests of
# turns that compaction has already dropped from the live context.
# --------------------------------------------------------------------------


@runtime_checkable
class Embedder(Protocol):
    """Injection seam for turning text into vectors.

    Tests pass a deterministic fake; production passes ``default_embedder()``
    (fastembed-backed) or any object with a matching ``embed``.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Returns 0.0 for mismatched/empty/zero vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@dataclass
class DigestEntry:
    text: str
    vector: list[float]
    turn: int


@dataclass
class DigestIndex:
    """In-memory store of embedded episode digests for similarity recall."""

    entries: list[DigestEntry] = field(default_factory=list)

    def add(self, text: str, turn: int, embedder: Embedder) -> None:
        """Embed and store one digest. Fail-open: skips on embed failure."""
        vectors = embedder.embed([text])
        if not vectors:
            return
        self.entries.append(DigestEntry(text=text, vector=vectors[0], turn=turn))

    def add_many(
        self, items: list[tuple[str, int]], embedder: Embedder
    ) -> None:
        """Embed and store ``(text, turn)`` pairs in one batched call."""
        if not items:
            return
        vectors = embedder.embed([t for t, _ in items])
        if not vectors:
            return
        for (text, turn), vec in zip(items, vectors):
            self.entries.append(DigestEntry(text=text, vector=vec, turn=turn))

    def retrieve(
        self, query: str, embedder: Embedder, k: int = 3
    ) -> list[DigestEntry]:
        """Return the top-``k`` digests most similar to ``query``."""
        if not self.entries or k <= 0:
            return []
        query_vecs = embedder.embed([query])
        if not query_vecs:
            return []
        query_vec = query_vecs[0]
        scored = [(_cosine(query_vec, e.vector), e) for e in self.entries]
        scored.sort(key=lambda se: -se[0])
        return [e for _, e in scored[:k]]


class _FastembedEmbedder:
    """Default embedder backed by the repo's optional fastembed util."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        from .skill_embeddings import embed as _embed
        return _embed(texts) or []


def default_embedder() -> Embedder | None:
    """Construct the fastembed-backed embedder, or ``None`` if unavailable.

    Fail-open: when ``fastembed`` isn't installed, callers must inject their
    own ``Embedder``. Never raises.
    """
    try:
        from .skill_embeddings import _have_fastembed
    except Exception:  # pragma: no cover - import guard
        return None
    if not _have_fastembed():
        return None
    return _FastembedEmbedder()


def recall_relevant_digests(
    query: str, index: DigestIndex, embedder: Embedder, k: int = 3
) -> str:
    """Format the top-``k`` recalled digests as a ``<recall>`` block.

    Returns ``""`` when nothing is retrieved, so an agent loop can safely
    prepend the result unconditionally. Wiring into the live loop is tracked
    separately; this is the tested hook.
    """
    hits = index.retrieve(query, embedder, k=k)
    if not hits:
        return ""
    body = "\n".join(f"[turn {e.turn}] {e.text}" for e in hits)
    return f"<recall>\n{body}\n</recall>"
