"""ASR meeting listener (roadmap: 2027 H1 capabilities, "ASR meeting
listener").

A long-running session that consumes an **injected** stream of transcript
segments (whatever ASR produced them — tools/voice.py, live captions, a bot
in the call) and accumulates minutes:

* rolling transcript with timestamps and speaker tags (when the source
  provides them — segments are ``{"text", "speaker"?, "ts"?}``);
* speaker turns (consecutive same-speaker segments merged);
* action items via a **deterministic heuristic** (assignment patterns like
  "Alice will send the deck" / "Bob to follow up", imperative openers,
  "action item:"/"TODO:" markers) with an optional **llm seam** — inject
  ``llm(transcript) -> "owner: task"`` lines to upgrade extraction; any llm
  failure falls back to the heuristic;
* a session summary artifact written to ``data_dir("meetings")`` with 0600
  permissions on :meth:`MeetingListener.finalize`.

The clock is injected, so sessions are fully reproducible offline.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import data_dir

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MeetingSegment:
    ts: float
    speaker: str | None
    text: str


@dataclass(frozen=True)
class ActionItem:
    owner: str | None
    text: str


# ---------- deterministic action-item heuristic ----------

_SENTENCE_SPLIT = re.compile(r"[.;!?]+")
# "Alice will send ..." / "Alice should review ..."
_ASSIGN_WILL = re.compile(r"^([A-Z][a-z]+)\s+(?:will|should)\s+\S")
# "Bob to follow up ..." — only with a known action verb after "to",
# otherwise "Yesterday to recap" style phrases false-positive.
_ASSIGN_TO = re.compile(r"^([A-Z][a-z]+)\s+to\s+([a-z]+)")
_MARKER = re.compile(r"^(?:action item|todo)\s*[:\-]\s*(.+)$", re.IGNORECASE)
_LEADIN = re.compile(r"^(?:let's|we need to|remember to)\s+\S", re.IGNORECASE)

_ACTION_VERBS = frozenset({
    "send", "schedule", "review", "update", "prepare", "share", "create",
    "write", "draft", "fix", "file", "email", "book", "ping", "follow",
})


def extract_action_items(segments: Iterable[MeetingSegment]) -> list[ActionItem]:
    """Pattern-based extraction; recall-leaning but deterministic."""
    items: list[ActionItem] = []
    seen: set[tuple[str | None, str]] = set()

    def add(owner: str | None, text: str) -> None:
        key = (owner, text.lower())
        if text and key not in seen:
            seen.add(key)
            items.append(ActionItem(owner=owner, text=text))

    for seg in segments:
        for raw in _SENTENCE_SPLIT.split(seg.text):
            sentence = raw.strip()
            if not sentence:
                continue
            m = _MARKER.match(sentence)
            if m:
                add(seg.speaker, m.group(1).strip())
                continue
            m = _ASSIGN_WILL.match(sentence)
            if m:
                add(m.group(1), sentence)
                continue
            m = _ASSIGN_TO.match(sentence)
            if m and m.group(2) in _ACTION_VERBS:
                add(m.group(1), sentence)
                continue
            first = sentence.split(None, 1)[0].lower()
            if first in _ACTION_VERBS or _LEADIN.match(sentence):
                add(seg.speaker, sentence)
    return items


def _parse_llm_items(raw: str) -> list[ActionItem]:
    """Parse llm output: one item per line, optionally ``owner: task``."""
    items: list[ActionItem] = []
    for line in (raw or "").splitlines():
        line = line.strip().lstrip("-*").strip()
        if not line:
            continue
        owner, sep, task = line.partition(":")
        if sep and owner and " " not in owner.strip():
            items.append(ActionItem(owner=owner.strip(), text=task.strip()))
        else:
            items.append(ActionItem(owner=None, text=line))
    return items


# ---------- the session ----------

class MeetingListener:
    """Accumulates minutes from a transcript-segment stream."""

    def __init__(
        self,
        *,
        session_id: str | None = None,
        clock: Callable[[], float] = time.time,
        llm: Callable[[str], str] | None = None,
    ) -> None:
        self._clock = clock
        self._llm = llm
        self.started = clock()
        raw_id = session_id or f"meeting-{int(self.started)}"
        # The id becomes a filename — keep it a single safe path segment.
        self.session_id = re.sub(r"[^A-Za-z0-9._-]", "-", raw_id).lstrip(".") or "meeting"
        self.segments: list[MeetingSegment] = []

    def feed(self, text: str, *, speaker: str | None = None, ts: float | None = None) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.segments.append(MeetingSegment(
            ts=self._clock() if ts is None else float(ts),
            speaker=speaker,
            text=text,
        ))

    def consume(self, stream: Iterable[dict[str, Any]]) -> None:
        """Feed every ``{"text", "speaker"?, "ts"?}`` segment from a stream."""
        for seg in stream:
            self.feed(seg.get("text", ""), speaker=seg.get("speaker"), ts=seg.get("ts"))

    # ----- views -----

    def transcript(self) -> str:
        return "\n".join(
            f"[{seg.ts - self.started:.1f}s] {seg.speaker or '?'}: {seg.text}"
            for seg in self.segments
        )

    def speaker_turns(self) -> list[tuple[str | None, int]]:
        """Consecutive same-speaker segments merged: [(speaker, n_segments)]."""
        turns: list[tuple[str | None, int]] = []
        for seg in self.segments:
            if turns and turns[-1][0] == seg.speaker:
                turns[-1] = (seg.speaker, turns[-1][1] + 1)
            else:
                turns.append((seg.speaker, 1))
        return turns

    def speakers(self) -> list[str]:
        out: list[str] = []
        for seg in self.segments:
            if seg.speaker and seg.speaker not in out:
                out.append(seg.speaker)
        return out

    def action_items(self) -> list[ActionItem]:
        if self._llm is not None:
            try:
                items = _parse_llm_items(self._llm(self.transcript()))
                if items:
                    return items
            except Exception:
                log.warning("meeting llm action-item extraction failed; "
                            "falling back to heuristic", exc_info=True)
        return extract_action_items(self.segments)

    def summary(self) -> str:
        # Span of captured speech (last segment ts), not wall time — summary()
        # must not advance an injected clock or drift between calls.
        duration = max(0.0, self.segments[-1].ts - self.started) if self.segments else 0.0
        return (
            f"{len(self.segments)} segments from {len(self.speakers())} speakers "
            f"across {len(self.speaker_turns())} turns over {duration:.0f}s; "
            f"{len(self.action_items())} action items"
        )

    # ----- artifact -----

    def finalize(self) -> Path:
        """Write the session minutes to data_dir('meetings'), 0600."""
        ended = self._clock()
        payload = {
            "session_id": self.session_id,
            "started": self.started,
            "ended": ended,
            "duration_seconds": max(0.0, ended - self.started),
            "speakers": self.speakers(),
            "speaker_turns": [
                {"speaker": s, "segments": n} for s, n in self.speaker_turns()
            ],
            "transcript": self.transcript(),
            "action_items": [
                {"owner": item.owner, "text": item.text} for item in self.action_items()
            ],
            "summary": self.summary(),
        }
        out_dir = data_dir("meetings")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{self.session_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)  # minutes can contain anything said in the room
        return path
