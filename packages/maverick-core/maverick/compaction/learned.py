"""Learned LLM summarizer for context compaction (roadmap: 2027 H1 perf, v3).

``compaction.compact_messages`` shrinks blocks structurally; this strategy
folds the old middle of a trajectory into one LLM-written digest — and it
*learns* which digest style works, with no trained weights. Mechanism:

* A small fixed set of prompt templates (:data:`TEMPLATES`).
* A local outcome ledger (``data_dir("compaction_ledger.json")``, written
  atomically and chmod 600) scoring each ``(context kind, template)`` pair by
  downstream signal: did the run continue successfully after compaction, and
  for how many turns.
* A deterministic bandit-lite picker per context kind: untried templates
  first (in fixed order), then epsilon-greedy over mean reward with an
  injectable PRNG so tests and replays are exact.

The summarize call goes through the injected ``llm`` seam only, with the
configured summarizer role model (``llm.model_for_role`` — users own model
choice; nothing here names a model). No llm, or any error, falls back to
``compact_messages`` — fail-open, like every compaction path.
"""
from __future__ import annotations

import json
import logging
import os
import random
import tempfile
import time
from pathlib import Path

from ..context_compactor import _message_text
from ..llm import model_for_role
from ..paths import data_dir
from . import KEEP_RECENT_TURNS, compact_messages

log = logging.getLogger(__name__)

LEDGER_BASENAME = "compaction_ledger.json"

# The fixed template set the bandit picks among. Keys are stable ids the
# ledger scores; values are the summarizer system prompts.
TEMPLATES: dict[str, str] = {
    "facts": (
        "Summarize this agent trajectory as a dense bullet list of FACTS: "
        "files/paths touched, commands run, errors seen, decisions made, and "
        "open questions. No prose, no praise. Keep every identifier verbatim."
    ),
    "narrative": (
        "Summarize this agent trajectory as a short narrative: what was the "
        "goal, what has been tried so far (and what happened), and what the "
        "obvious next step is. Keep file paths and error messages verbatim."
    ),
    "decisions": (
        "Summarize this agent trajectory as a decision log: each line is "
        "'decided X because Y' or 'learned X'. End with the current blocker "
        "or next action. Keep identifiers and paths verbatim."
    ),
}

# Context kinds the picker learns separately. Classification is a cheap
# deterministic heuristic over which tools the trajectory used.
KINDS = ("code", "research", "chat", "mixed")

_CODE_TOOLS = frozenset({
    "shell", "read_file", "write_file", "edit_file", "list_dir", "git", "python",
})
_RESEARCH_TOOLS = frozenset({
    "web_search", "fetch_url", "browser", "http_request", "youtube_transcript",
})

EPSILON = 0.1
# Continuation length saturates the reward at this many post-compaction turns.
CONTINUATION_NORM_TURNS = 20
MAX_TRANSCRIPT_CHARS = 24_000
_DIGEST_MAX_TOKENS = 768


def _ledger_path() -> Path:
    return data_dir(LEDGER_BASENAME)


def classify_kind(messages: list[dict]) -> str:
    """Deterministic context kind for ``messages`` (one of :data:`KINDS`)."""
    code = research = total = 0
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                total += 1
                name = str(blk.get("name", "") or "")
                if name in _CODE_TOOLS:
                    code += 1
                elif name in _RESEARCH_TOOLS:
                    research += 1
    if total == 0:
        return "chat"
    if code * 2 > total:
        return "code"
    if research * 2 > total:
        return "research"
    return "mixed"


def reward(success: bool, continuation_turns: int) -> float:
    """Downstream-signal reward in [0, 1]: half outcome, half continuation length."""
    length = min(max(continuation_turns, 0), CONTINUATION_NORM_TURNS)
    return 0.5 * (1.0 if success else 0.0) + 0.5 * (length / CONTINUATION_NORM_TURNS)


class OutcomeLedger:
    """``kind -> template -> {trials, reward_sum, last}`` on disk, fail-safe.

    The file lives under the (tenant-aware) data dir, is written atomically
    (unique temp file + ``os.replace``) and chmod 600 — same discipline as the
    quota ledger. Any I/O error degrades to "no signal"; it never blocks a run.
    """

    def __init__(self, path: Path | None = None, clock=None):
        self.path = path if path is not None else _ledger_path()
        self._clock = clock if clock is not None else time.time

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            log.warning("compaction ledger: cannot read %s: %s", self.path, e)
            return {}

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".compaction-", suffix=".tmp")
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
            log.warning("compaction ledger: cannot write %s: %s", self.path, e)

    def stats(self, kind: str) -> dict[str, dict]:
        entry = self._load().get(kind)
        return entry if isinstance(entry, dict) else {}

    def record(
        self, kind: str, template_id: str, *,
        success: bool, continuation_turns: int = 0,
    ) -> None:
        """Score one compaction by its downstream signal. Fail-safe no-op on error."""
        if template_id not in TEMPLATES:
            return
        data = self._load()
        by_template = data.setdefault(kind, {})
        if not isinstance(by_template, dict):  # corrupt entry: rebuild
            by_template = data[kind] = {}
        st = by_template.get(template_id)
        if not isinstance(st, dict):
            st = by_template[template_id] = {"trials": 0, "reward_sum": 0.0}
        try:
            st["trials"] = int(st.get("trials", 0)) + 1
            st["reward_sum"] = float(st.get("reward_sum", 0.0)) + reward(
                success, continuation_turns)
        except (TypeError, ValueError):
            st["trials"], st["reward_sum"] = 1, reward(success, continuation_turns)
        st["last"] = self._clock()
        self._save(data)

    def pick_template(self, kind: str, rng: random.Random) -> str:
        """Bandit-lite pick: untried first (fixed order), then epsilon-greedy.

        Deterministic given the ledger state and the injected ``rng``; ties on
        mean reward break toward template declaration order.
        """
        ids = list(TEMPLATES)
        stats = self.stats(kind)

        def _trials(tid: str) -> int:
            st = stats.get(tid)
            try:
                return int(st.get("trials", 0)) if isinstance(st, dict) else 0
            except (TypeError, ValueError):
                return 0

        untried = [tid for tid in ids if _trials(tid) == 0]
        if untried:
            return untried[0]
        if rng.random() < EPSILON:
            return ids[rng.randrange(len(ids))]

        def _mean(tid: str) -> float:
            st = stats.get(tid, {})
            try:
                return float(st.get("reward_sum", 0.0)) / max(_trials(tid), 1)
            except (TypeError, ValueError):
                return 0.0

        return max(ids, key=_mean)  # max() keeps the first of tied ids


def _transcript(messages: list[dict]) -> str:
    lines = [f"{m.get('role', '?')}: {_message_text(m)}" for m in messages]
    text = "\n".join(lines)
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = text[-MAX_TRANSCRIPT_CHARS:]
    return text


class LearnedSummarizer:
    """v3 strategy: digest the old middle with the best-scoring template.

    ``llm`` is the injected seam (anything with a ``complete(system, messages,
    ...)`` returning an object with ``.text``). ``rng`` and ``clock`` are
    injectable for deterministic tests; the defaults are themselves
    deterministic (a fixed-seed PRNG).
    """

    def __init__(
        self, llm=None, *,
        ledger: OutcomeLedger | None = None,
        rng: random.Random | None = None,
        clock=None,
        budget=None,
        scope: str | None = None,
    ):
        self.llm = llm
        self.budget = budget
        self.ledger = ledger if ledger is not None else OutcomeLedger(clock=clock)
        self._rng = rng if rng is not None else random.Random(0)
        self.last_pick: tuple[str, str] | None = None  # (kind, template_id)
        # Department scope: a domain agent's outcomes train that department's
        # own (scope|kind) ledger rows -- a finance digest prompt that wins on
        # finance transcripts stops competing with the global pool. None keeps
        # the original kind keys, so existing ledgers read unchanged.
        self.scope = (scope or "").strip() or None

    def compact(
        self, messages: list[dict], *, keep_recent: int = KEEP_RECENT_TURNS,
    ) -> list[dict]:
        """Fold ``messages[1:-keep_recent]`` into one learned digest message.

        The first message (the brief) and the recent tail pass through
        verbatim, mirroring ``compact_messages``. Without an llm, or on any
        llm error, falls back to ``compact_messages`` unchanged.
        """
        if len(messages) <= keep_recent + 1:
            return list(messages)
        if self.llm is None:
            return compact_messages(messages, keep_recent=keep_recent)
        cutoff = len(messages) - keep_recent
        middle = messages[1:cutoff]
        kind = classify_kind(middle)
        if self.scope:
            kind = f"{self.scope}|{kind}"
        template_id = self.ledger.pick_template(kind, self._rng)
        try:
            resp = self.llm.complete(
                system=TEMPLATES[template_id],
                messages=[{"role": "user", "content": _transcript(middle)}],
                max_tokens=_DIGEST_MAX_TOKENS,
                model=model_for_role("summarizer"),
                budget=self.budget,
            )
            digest = (getattr(resp, "text", "") or "").strip()
        except Exception as e:
            log.warning("learned compaction summarize failed (%s); using default", e)
            return compact_messages(messages, keep_recent=keep_recent)
        if not digest:
            return compact_messages(messages, keep_recent=keep_recent)
        self.last_pick = (kind, template_id)
        digest_msg = {
            "role": "user",
            "content": (
                f'<learned-digest kind="{kind}" template="{template_id}" '
                f'turns="{len(middle)}">\n{digest}\n</learned-digest>'
            ),
        }
        return [messages[0], digest_msg, *messages[cutoff:]]

    def record_outcome(
        self, *, success: bool, continuation_turns: int = 0,
        kind: str | None = None, template_id: str | None = None,
    ) -> None:
        """Feed the downstream signal for the last (or a named) compaction back
        into the ledger. No-op when nothing was compacted yet."""
        if kind is None or template_id is None:
            if self.last_pick is None:
                return
            kind, template_id = self.last_pick
        self.ledger.record(
            kind, template_id, success=success, continuation_turns=continuation_turns,
        )


__all__ = [
    "TEMPLATES",
    "KINDS",
    "LEDGER_BASENAME",
    "classify_kind",
    "reward",
    "OutcomeLedger",
    "LearnedSummarizer",
]
