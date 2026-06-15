"""Speech-to-action live mic (roadmap: 2027 H1 capabilities,
"speech-to-action live-mic").

A hardware-free loop: an **injected** chunk source (any iterable of audio
chunks — a mic adapter, a test script, a file splitter) feeds an **injected**
transcriber; each utterance is matched against the deterministic
:mod:`maverick.tools.voice_command_grammar` templates and matched intents are
dispatched to an **injected** action callback. Risky intents pass a strict
confirmation gate first (``tools.as_bool`` semantics: only a real ``True``
authorises — a stringy "yes" fails closed to denied).

The real adapters are optional and never required here:

* **Mic capture** is the caller's adapter — any callable producing audio
  chunks (e.g. ``sounddevice``/``pyaudio`` reads, a websocket, an ffmpeg
  pipe). The loop only sees an iterable of ``bytes``.
* **Transcription**: :func:`whisper_transcriber` builds a chunk transcriber
  on local faster-whisper when the ``[voice]`` extra is installed
  (``pip install 'maverick-agent[voice]'``); model size comes from
  ``MAVERICK_WHISPER_MODEL`` (default ``small``), matching tools/voice.py.

Deterministic by construction: no thread, no clock, no model in the loop.
"""
from __future__ import annotations

import io
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .tools import as_bool
from .tools.voice_command_grammar import _WS, _compile, _match

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MicEvent:
    """One non-silent utterance and what the loop did with it."""
    utterance: str
    intent: str | None
    slots: dict[str, str] = field(default_factory=dict)
    status: str = "no_match"  # dispatched | denied | error | no_match


def match_utterance(
    grammar: list[dict[str, Any]],
    utterance: str,
) -> tuple[str, dict[str, str]] | None:
    """Match an utterance against ``[{intent, pattern}]`` templates.

    Reuses voice_command_grammar's compiler (loose whitespace,
    case-insensitive, ``{slot}`` capture). Returns ``(intent, slots)`` for
    the first matching rule, or ``None``.
    """
    text = _WS.sub(" ", utterance.strip())
    for rule in grammar:
        if not isinstance(rule, dict) or "intent" not in rule or "pattern" not in rule:
            raise ValueError("each grammar rule needs 'intent' and 'pattern'")
        compiled = _compile(str(rule["pattern"]))
        if compiled is None:
            raise ValueError(f"duplicate slot in pattern {rule['pattern']!r}")
        captures = _match(compiled, text)
        if captures is not None:
            return str(rule["intent"]), captures
    return None


def run_live_mic(
    chunks: Iterable[bytes],
    transcriber: Callable[[bytes], str],
    grammar: list[dict[str, Any]],
    on_intent: Callable[[str, dict[str, str]], Any],
    *,
    risky_intents: Iterable[str] = (),
    confirm: Callable[[str, dict[str, str]], Any] | None = None,
) -> list[MicEvent]:
    """Drive the speech-to-action loop until the chunk source is exhausted.

    Silence (a transcription that is empty/whitespace) produces no event.
    An intent in ``risky_intents`` is dispatched only when ``confirm`` returns
    a real ``True`` (strict ``as_bool`` gate); with no confirm hook risky
    intents fail closed to ``denied``. An action callback that raises is
    logged and recorded as ``error`` — one bad action must not kill a live
    mic session.
    """
    risky = set(risky_intents)
    events: list[MicEvent] = []
    for chunk in chunks:
        utterance = (transcriber(chunk) or "").strip()
        if not utterance:
            continue
        match = match_utterance(grammar, utterance)
        if match is None:
            events.append(MicEvent(utterance=utterance, intent=None))
            continue
        intent, slots = match
        if intent in risky:
            confirmed = confirm is not None and as_bool(confirm(intent, slots))
            if not confirmed:
                events.append(MicEvent(utterance, intent, slots, "denied"))
                continue
        try:
            on_intent(intent, slots)
        except Exception:
            log.exception("live-mic action for intent %r failed", intent)
            events.append(MicEvent(utterance, intent, slots, "error"))
            continue
        events.append(MicEvent(utterance, intent, slots, "dispatched"))
    return events


def whisper_transcriber(model_size: str | None = None) -> Callable[[bytes], str]:
    """Build the real chunk transcriber on local faster-whisper.

    Optional — the loop itself never needs it (inject any
    ``bytes -> str``). Loads the model once; each call transcribes one
    audio chunk (a self-contained container like WAV bytes).
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise ImportError(
            "live-mic transcription needs faster-whisper. "
            "Run: pip install 'maverick-agent[voice]'"
        ) from e
    size = model_size or os.environ.get("MAVERICK_WHISPER_MODEL", "small")
    model = WhisperModel(size, device="cpu", compute_type="int8")

    def _transcribe(chunk: bytes) -> str:
        segments, _info = model.transcribe(io.BytesIO(chunk))
        return " ".join(s.text for s in segments).strip()

    return _transcribe
