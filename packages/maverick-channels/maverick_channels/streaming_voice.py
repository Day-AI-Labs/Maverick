"""Voice channel v2 — streaming ASR session with endpointing and barge-in.

Protocol layer only, like the other channel adapters' pure cores: this module
consumes *events* from an injected streaming transcriber (the operator's
``on_partial``/``on_final`` callbacks feed :meth:`StreamingVoiceSession.feed_partial`
/ :meth:`feed_final`) and tracks playback through injected
``is_speaking()`` / ``stop_speaking()`` seams. No audio dependencies; fully
offline-testable with scripted event sequences and an injected clock.

What it does:

* **Endpointing** — an utterance closes when the transcriber emits a final
  hypothesis, or when the partial hypothesis has been stable for
  ``stability_timeout_s`` (checked on :meth:`poll`, against the injected
  monotonic clock).
* **Barge-in** — when user speech onset (the first non-empty partial or an
  unheralded final) arrives while the bot is speaking, ``stop_speaking()`` is
  called immediately and the floor passes to the user; the interrupted reply
  is preserved with its full text and marked ``"interrupted"``
  (= partially delivered), so the caller can offer to repeat it.

The real ASR adapter is the operator's: a faster-whisper streaming loop or a
cloud streaming ASR (Deepgram, AssemblyAI, ...) sits behind the seam and
simply calls ``feed_partial``/``feed_final`` plus a periodic ``poll()``.
Likewise the playback engine owns the audio device and exposes the two
playback seams.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

# Bound the partial hypothesis so a runaway ASR stream can't grow memory
# without limit; bound how many finished replies a session retains.
MAX_UTTERANCE_CHARS = 4000
MAX_REPLY_HISTORY = 64

DEFAULT_STABILITY_TIMEOUT_S = 1.2


@dataclass
class PlaybackSeams:
    """How the session sees the operator's playback engine."""
    is_speaking: Callable[[], bool]
    stop_speaking: Callable[[], None]


@dataclass
class Utterance:
    """A closed user utterance."""
    text: str
    final: bool          # True: closed by an ASR final; False: stability timeout
    started_at: float
    ended_at: float


@dataclass
class Reply:
    """One bot reply and its delivery state."""
    text: str
    started_at: float
    status: str = "speaking"  # "speaking" | "delivered" | "interrupted"

    @property
    def partially_delivered(self) -> bool:
        return self.status == "interrupted"


class StreamingVoiceSession:
    """One streaming-voice conversation: endpointing + barge-in state machine.

    ``playback`` provides the ``is_speaking``/``stop_speaking`` seams;
    ``clock`` is a monotonic-seconds callable (injected for tests);
    ``on_utterance`` (optional) is called with each closed :class:`Utterance`.
    """

    def __init__(
        self,
        playback: PlaybackSeams,
        *,
        clock: Callable[[], float] = time.monotonic,
        stability_timeout_s: float = DEFAULT_STABILITY_TIMEOUT_S,
        on_utterance: Callable[[Utterance], object] | None = None,
    ):
        self.playback = playback
        self.clock = clock
        self.stability_timeout_s = max(0.0, float(stability_timeout_s))
        self.on_utterance = on_utterance
        # Open-utterance state.
        self._hypothesis: str | None = None
        self._opened_at = 0.0
        self._last_change = 0.0
        # Reply tracking.
        self.replies: deque[Reply] = deque(maxlen=MAX_REPLY_HISTORY)
        self._current_reply: Reply | None = None

    # ----- transcriber events -----
    def feed_partial(self, text: str) -> None:
        """A partial hypothesis from the streaming transcriber.

        The first non-empty partial is speech onset: if the bot is speaking,
        this is barge-in — playback halts immediately and the user takes the
        floor. Later partials just refresh the hypothesis (a changed
        hypothesis resets the stability clock).
        """
        text = (text or "").strip()[:MAX_UTTERANCE_CHARS]
        if not text:
            return  # silence/no-speech partials never open an utterance
        now = self.clock()
        if self._hypothesis is None:
            self._barge_in_if_speaking()
            self._opened_at = now
            self._last_change = now
            self._hypothesis = text
            return
        if text != self._hypothesis:
            self._hypothesis = text
            self._last_change = now

    def feed_final(self, text: str) -> Utterance | None:
        """A final hypothesis: closes the utterance immediately.

        A final with no open utterance is still speech onset (barge-in check
        applies). An empty final falls back to the open hypothesis; an empty
        final with nothing open is ignored.
        """
        text = (text or "").strip()[:MAX_UTTERANCE_CHARS]
        if self._hypothesis is None:
            if not text:
                return None
            self._barge_in_if_speaking()
            self._opened_at = self.clock()
        closed = self._close(text or self._hypothesis or "", final=True)
        return closed

    def poll(self) -> Utterance | None:
        """Endpoint check: close the open utterance if the hypothesis has been
        stable for ``stability_timeout_s``. Call periodically (or after
        advancing the injected clock in tests)."""
        if self._hypothesis is None:
            return None
        if self.clock() - self._last_change < self.stability_timeout_s:
            return None
        return self._close(self._hypothesis, final=False)

    # ----- bot playback -----
    def begin_reply(self, text: str) -> Reply:
        """Record that the bot started speaking ``text``. The playback engine
        does the actual audio; the session only tracks delivery state."""
        reply = Reply(text=str(text or ""), started_at=self.clock())
        self._current_reply = reply
        self.replies.append(reply)
        return reply

    def reply_finished(self) -> None:
        """Playback engine reports the current reply played to completion."""
        if self._current_reply is not None and self._current_reply.status == "speaking":
            self._current_reply.status = "delivered"
        self._current_reply = None

    @property
    def interrupted_replies(self) -> list[Reply]:
        """Replies cut off by barge-in (text preserved for redelivery)."""
        return [r for r in self.replies if r.status == "interrupted"]

    # ----- internals -----
    def _barge_in_if_speaking(self) -> None:
        if not self.playback.is_speaking():
            return
        # Halt playback NOW — before any utterance bookkeeping — so the user
        # never talks over the bot.
        self.playback.stop_speaking()
        if self._current_reply is not None and self._current_reply.status == "speaking":
            self._current_reply.status = "interrupted"
        self._current_reply = None

    def _close(self, text: str, *, final: bool) -> Utterance | None:
        started = self._opened_at
        self._hypothesis = None
        self._opened_at = 0.0
        self._last_change = 0.0
        text = text.strip()
        if not text:
            return None
        utt = Utterance(
            text=text, final=final, started_at=started, ended_at=self.clock(),
        )
        if self.on_utterance is not None:
            self.on_utterance(utt)
        return utt


@dataclass
class ScriptedEvent:
    """One scripted transcriber event for offline tests/replays:
    ``kind`` is "partial", "final", or "wait" (advance time by ``seconds``)."""
    kind: str
    text: str = ""
    seconds: float = 0.0


def run_scripted(
    session: StreamingVoiceSession,
    events: list[ScriptedEvent],
    advance: Callable[[float], None],
) -> list[Utterance]:
    """Drive a session from a scripted event sequence (offline test helper).

    ``advance`` moves the injected clock forward (fake time). Returns the
    utterances the script closed, in order.
    """
    out: list[Utterance] = []
    for ev in events:
        if ev.kind == "partial":
            session.feed_partial(ev.text)
        elif ev.kind == "final":
            utt = session.feed_final(ev.text)
            if utt is not None:
                out.append(utt)
            continue
        elif ev.kind == "wait":
            advance(ev.seconds)
        else:
            raise ValueError(f"unknown scripted event kind {ev.kind!r}")
        utt = session.poll()
        if utt is not None:
            out.append(utt)
    return out


__all__ = [
    "PlaybackSeams",
    "Utterance",
    "Reply",
    "StreamingVoiceSession",
    "ScriptedEvent",
    "run_scripted",
    "MAX_UTTERANCE_CHARS",
    "MAX_REPLY_HISTORY",
    "DEFAULT_STABILITY_TIMEOUT_S",
]
