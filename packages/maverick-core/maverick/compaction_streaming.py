"""Streaming (incremental) compaction (roadmap: 2028 H1 perf, v7).

Digest-style compaction re-summarizes the WHOLE prefix every time it runs —
O(history) summarizer input per compaction. This strategy instead maintains a
*running summary* plus a *cursor* per conversation, persisted to a small
sidecar (``data_dir("compaction_stream.json")``, atomic write, chmod 600 —
the async_compaction scheduler is stateless, so the sidecar is the store).
Each call folds only the turns the cursor hasn't seen yet:

    summary' = fold(summary, new_turns)        # O(new) per call

The fold goes through the injected ``llm`` seam (configured summarizer role
model) when available; without one it appends deterministic one-line digests
of the new turns, so the strategy is fully offline-capable. A shrunk or
unrecognised turn list (the caller restarted the conversation) resets the
cursor and refolds from scratch rather than guessing.

API: :meth:`StreamingCompactor.fold` (incremental call-per-batch),
:meth:`StreamingCompactor.folder` (coroutine: ``send()`` new turns, receive
the running summary), and :func:`compact_streaming` (message-list strategy
entry used by ``compaction_strategies``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Generator
from pathlib import Path

from .compaction import KEEP_RECENT_TURNS
from .context_compactor import _message_text
from .llm import model_for_role
from .paths import data_dir

log = logging.getLogger(__name__)

SIDECAR_BASENAME = "compaction_stream.json"

# The sidecar holds one entry per conversation_id; without a reaper it grows
# one row per conversation forever on a long-running ``maverick serve``. Each
# entry carries a ``last`` write timestamp, so we prune entries untouched for
# longer than this TTL on every save. 0 disables pruning (durable forever).
_DEFAULT_TTL_DAYS = 30.0


def _ttl_seconds() -> float:
    """Stale-entry TTL for the sidecar, from ``[context]
    compaction_stream_ttl_days`` (default 30; <=0 disables pruning)."""
    try:
        from .config import load_config

        raw = load_config().get("context", {}).get(
            "compaction_stream_ttl_days", _DEFAULT_TTL_DAYS)
        days = float(raw)
    except Exception:
        days = _DEFAULT_TTL_DAYS
    return days * 86400.0 if days > 0 else 0.0

_FOLD_SYSTEM = (
    "You maintain a running summary of an agent conversation. Merge the new "
    "turns into the summary: keep every fact, file path, decision and error "
    "already there, add the new ones, drop chit-chat. Return only the updated "
    "summary."
)
_FOLD_MAX_TOKENS = 768
# Heuristic (no-llm) fold bounds, so the running summary stays a summary.
_LINE_CHARS = 160
_MAX_SUMMARY_LINES = 200


def _sidecar_path() -> Path:
    return data_dir(SIDECAR_BASENAME)


def _turn_line(turn: dict) -> str:
    text = " ".join(_message_text(turn).split())
    if len(text) > _LINE_CHARS:
        text = text[:_LINE_CHARS].rstrip() + "..."
    return f"{turn.get('role', '?')}: {text}"


def _turns_fingerprint(turns: list[dict]) -> str:
    """Stable digest of the exact folded prefix stored in the sidecar."""
    blob = json.dumps(turns, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()


class StreamingCompactor:
    """Per-conversation running summary + cursor, persisted across calls."""

    def __init__(
        self, llm=None, *, path: Path | None = None, clock=None, budget=None,
        ttl_seconds: float | None = None,
    ):
        self.llm = llm
        self.budget = budget
        self.path = path if path is not None else _sidecar_path()
        self._clock = clock if clock is not None else time.time
        self.ttl_seconds = _ttl_seconds() if ttl_seconds is None else float(ttl_seconds)

    # ---- sidecar I/O (fail-safe, atomic, 0600) ----

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            log.warning("compaction stream sidecar: cannot read %s: %s", self.path, e)
            return {}

    def _prune_stale(self, data: dict) -> dict:
        """Drop entries untouched for longer than the TTL (one per stale
        conversation), bounding the sidecar on a long-running deployment.
        Entries missing/with an unreadable ``last`` are kept (fail-safe)."""
        if not self.ttl_seconds:
            return data
        cutoff = self._clock() - self.ttl_seconds
        kept = {}
        for cid, st in data.items():
            try:
                last = float(st.get("last")) if isinstance(st, dict) else None
            except (TypeError, ValueError):
                last = None
            if last is None or last >= cutoff:
                kept[cid] = st
        return kept

    def _save(self, data: dict) -> None:
        data = self._prune_stale(data)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".stream-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as e:
            log.warning("compaction stream sidecar: cannot write %s: %s", self.path, e)

    def _state_entry(self, conversation_id: str) -> tuple[int, str, str]:
        """The persisted ``(cursor, summary, fingerprint)`` for a conversation."""
        st = self._load().get(conversation_id)
        if not isinstance(st, dict):
            return 0, "", ""
        try:
            cursor = max(int(st.get("cursor", 0)), 0)
        except (TypeError, ValueError):
            cursor = 0
        fingerprint = st.get("fingerprint", "")
        if not isinstance(fingerprint, str):
            fingerprint = ""
        return cursor, str(st.get("summary", "") or ""), fingerprint

    def state(self, conversation_id: str) -> tuple[int, str]:
        """The persisted ``(cursor, summary)`` for a conversation."""
        cursor, summary, _fingerprint = self._state_entry(conversation_id)
        return cursor, summary

    def reset(self, conversation_id: str) -> None:
        data = self._load()
        if conversation_id in data:
            del data[conversation_id]
            self._save(data)

    # ---- folding ----

    def _fold_once(self, summary: str, new_turns: list[dict]) -> str:
        rendered = "\n".join(_turn_line(t) for t in new_turns)
        if self.llm is not None:
            try:
                resp = self.llm.complete(
                    system=_FOLD_SYSTEM,
                    messages=[{
                        "role": "user",
                        "content": (
                            f"<summary>\n{summary}\n</summary>\n"
                            f"<new-turns>\n{rendered}\n</new-turns>"
                        ),
                    }],
                    max_tokens=_FOLD_MAX_TOKENS,
                    model=model_for_role("summarizer"),
                    budget=self.budget,
                )
                folded = (getattr(resp, "text", "") or "").strip()
                if folded:
                    return folded
            except Exception as e:
                log.warning("streaming compaction fold failed (%s); heuristic fold", e)
        lines = [ln for ln in summary.splitlines() if ln.strip()]
        lines.extend(_turn_line(t) for t in new_turns)
        return "\n".join(lines[-_MAX_SUMMARY_LINES:])

    def fold(self, conversation_id: str, turns: list[dict]) -> str:
        """Fold the turns the cursor hasn't seen into the running summary.

        ``turns`` is the conversation prefix so far (oldest first); only
        ``turns[cursor:]`` are summarized. Returns the updated summary and
        persists ``(cursor=len(turns), summary)``. A ``turns`` list shorter
        than the cursor means the conversation was rewound: state resets and
        everything is refolded.
        """
        cursor, summary, fingerprint = self._state_entry(conversation_id)
        prefix_matches = (
            cursor == 0
            or (fingerprint and fingerprint == _turns_fingerprint(turns[:cursor]))
        )
        if cursor > len(turns) or not prefix_matches:
            cursor, summary = 0, ""
        new_turns = turns[cursor:]
        if new_turns:
            summary = self._fold_once(summary, new_turns)
        data = self._load()
        data[conversation_id] = {
            "cursor": len(turns),
            "summary": summary,
            "fingerprint": _turns_fingerprint(turns),
            "last": self._clock(),
        }
        self._save(data)
        return summary

    def folder(self, conversation_id: str) -> Generator[str, list[dict], None]:
        """Coroutine API: prime with ``next()``, then ``send(new_turns)``.

        Each ``send`` folds the sent turns (they are appended after the
        cursor, i.e. callers send only NEW turns) and yields the updated
        running summary.
        """
        cursor, summary = self.state(conversation_id)
        folded_turns: list[dict] = []
        while True:
            sent = yield summary
            if not sent:
                continue
            cursor += len(sent)
            folded_turns.extend(sent)
            summary = self._fold_once(summary, sent)
            data = self._load()
            data[conversation_id] = {
                "cursor": cursor,
                "summary": summary,
                "fingerprint": _turns_fingerprint(folded_turns),
                "last": self._clock(),
            }
            self._save(data)


def _default_key(messages: list[dict]) -> str:
    """Stable conversation key: hash of the first message (preserved verbatim
    by every compaction pass, so it identifies the episode across calls)."""
    first = messages[0] if messages else {}
    blob = json.dumps(first, sort_keys=True, default=str)
    return "msg:" + hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()[:16]


def compact_streaming(
    messages: list[dict], *,
    conversation_id: str | None = None,
    keep_recent: int = KEEP_RECENT_TURNS,
    llm=None,
    path: Path | None = None,
    budget=None,
) -> list[dict]:
    """Strategy entry: replace the old middle with the running summary.

    The first message and the last ``keep_recent`` pass through verbatim;
    ``messages[1:cutoff]`` are folded incrementally (only turns beyond the
    persisted cursor cost a fold).
    """
    if len(messages) <= keep_recent + 1:
        return list(messages)
    cutoff = len(messages) - keep_recent
    key = conversation_id or _default_key(messages)
    compactor = StreamingCompactor(llm=llm, path=path, budget=budget)
    summary = compactor.fold(key, messages[1:cutoff])
    summary_msg = {
        "role": "user",
        "content": (
            f'<stream-summary turns="{cutoff - 1}">\n{summary}\n</stream-summary>'
        ),
    }
    return [messages[0], summary_msg, *messages[cutoff:]]


__all__ = ["SIDECAR_BASENAME", "StreamingCompactor", "compact_streaming"]
