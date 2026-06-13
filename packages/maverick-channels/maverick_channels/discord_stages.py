"""Discord Stages voice channel v2 (roadmap: 2027 H1 UX — "voice in
channels v2 (Discord stages)").

Drive Maverick from a Discord **Stage channel**: the bot joins the stage,
listens to speakers, transcribes utterances, routes them through the normal
handler, and answers — as speech when it holds a speaker slot, else as text
in the stage's chat. The voice plumbing (gateway voice, Opus decode,
PyNaCl) is *heavy and optional*; this module is the **session/protocol
layer** with every Discord interaction behind an injected ``stage`` seam, so
the logic — turn-taking, utterance assembly, reply routing, the
speaker-request etiquette — is fully unit-tested offline, and the real
discord.py-voice binding plugs into the same seam (``[discord] extra +
PyNaCl``; documented, not required).

Etiquette rules built in:
* the bot NEVER auto-promotes itself to speaker — it requests, a human
  moderator approves (Discord's own stage model);
* it answers as text when not a speaker (graceful degradation);
* an utterance is bounded (max seconds/chars) before it reaches the handler.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .base import IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

MAX_UTTERANCE_CHARS = 2000


@dataclass
class StageSeam:
    """Everything the session needs from Discord, injected.

    ``request_speaker()`` asks for a slot (moderator approves out-of-band);
    ``is_speaker()`` reflects the current slot state; ``speak(text)`` plays
    TTS into the stage; ``send_text(text)`` posts to the stage chat.
    """

    request_speaker: Callable[[], Awaitable[None]]
    is_speaker: Callable[[], bool]
    speak: Callable[[str], Awaitable[None]]
    send_text: Callable[[str], Awaitable[None]]


@dataclass
class StageSession:
    """One stage-listening session: utterance assembly + reply routing."""

    handler: Callable[..., Awaitable[str]]
    seam: StageSeam
    transcriber: Callable[[bytes], str]
    channel_name: str = "discord-stage"
    wake_word: str | None = None  # only react when addressed, if set
    allowed_user_ids: set[str] | None = None
    _buffer: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Discord Stage speakers can trigger the normal Maverick handler, so
        # require the same explicit Discord allowlist used by the text adapter.
        self.allowed_user_ids = normalize_allowlist(
            self.allowed_user_ids,
            "DISCORD_ALLOWED_USER_IDS",
        )
        if not self.allowed_user_ids:
            raise ValueError("Set DISCORD_ALLOWED_USER_IDS to restrict access")

    async def on_audio_segment(self, speaker_id: str, audio: bytes, *, final: bool) -> str | None:
        """Feed one speaker's audio segment; on a final segment, transcribe
        the assembled utterance and (maybe) handle it. Returns the reply
        text when one was produced (for tests/telemetry)."""
        if not is_allowed(speaker_id, self.allowed_user_ids):
            log.warning("unauthorized discord stage access: speaker_id=%s", speaker_id)
            self._buffer.pop(speaker_id, None)
            return None
        text = (self.transcriber(audio) or "").strip()
        if text:
            self._buffer.setdefault(speaker_id, []).append(text)
        if not final:
            return None
        utterance = " ".join(self._buffer.pop(speaker_id, []))[:MAX_UTTERANCE_CHARS]
        if not utterance:
            return None
        if self.wake_word and self.wake_word.lower() not in utterance.lower():
            return None  # not addressed to the bot
        return await self._respond(speaker_id, utterance)

    async def _respond(self, speaker_id: str, utterance: str) -> str:
        msg = IncomingMessage(
            user_id=speaker_id, text=utterance, channel=self.channel_name, sender_id=speaker_id
        )
        try:
            reply = await self.handler(msg)
        except Exception:
            log.exception("stage handler failed")
            reply = "Sorry — that request failed."
        reply_text = getattr(reply, "text", reply) or ""
        await self.deliver(reply_text)
        return reply_text

    async def deliver(self, text: str) -> None:
        """Speak when holding a speaker slot; degrade to stage chat text."""
        if not text:
            return
        if self.seam.is_speaker():
            try:
                await self.seam.speak(text)
                return
            except Exception:
                log.exception("stage TTS failed; falling back to text")
        await self.seam.send_text(text)

    async def ensure_speaker_requested(self) -> bool:
        """Request a speaker slot (never self-promotes). Returns whether the
        bot currently holds one."""
        if self.seam.is_speaker():
            return True
        try:
            await self.seam.request_speaker()
        except Exception:
            log.exception("speaker request failed")
        return self.seam.is_speaker()


__all__ = ["StageSeam", "StageSession", "MAX_UTTERANCE_CHARS"]
