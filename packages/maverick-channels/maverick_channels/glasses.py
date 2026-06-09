"""Glasses / wearable channel — Even Realities G2 "bring your own agent" bridge.

Smart glasses do on-device speech-to-text and render short text on a HUD, but
impose a hard request deadline (~30 s on the G2). This adapter implements the
**ack-then-run** pattern that makes a long-horizon agent usable on such a device:

  - a **quick** utterance (a fact, the weather, short chat) is answered
    synchronously within the deadline and shown on the HUD;
  - a **long** task (write code, research, deploy) is **acked immediately**
    ("Got it — working on it; I'll send the result to <channel>"), run in the
    background, and the full result is delivered to a **secondary channel**
    (e.g. Telegram) when done.

The classifier and the deadline split are the whole point and are pure +
unit-tested. The transport is a thin shim over the existing inbound
``POST /webhook/start`` (self-hostable as a small edge service or a Worker), and
long-task results ride the existing outbound delivery — no new server surface.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from .base import Channel, IncomingMessage, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

_DEFAULT_DEADLINE_S = 22.0   # under the G2's ~30s timeout, leaving headroom
_HUD_MAX_CHARS = 240          # the HUD shows short text; keep acks/answers tight

# An utterance is a *long* task if it asks for work that can't finish in the
# deadline. Conservative: only clear "do work" verbs trip it; everything else is
# answered synchronously.
_LONG_TASK_RE = re.compile(
    r"\b(write|build|create|generate|implement|code|program|"
    r"research|investigate|analy[sz]e|deploy|ship|release|"
    r"refactor|migrate|scrape|crawl|compile|train)\b",
    re.IGNORECASE,
)


def classify_utterance(text: str) -> str:
    """``"long"`` if the utterance asks for background work, else ``"quick"``."""
    return "long" if _LONG_TASK_RE.search(text or "") else "quick"


def ack_message(secondary: str | None) -> str:
    """The immediate HUD ack for a long task."""
    where = f" I'll send the result to {secondary}." if secondary else \
        " I'll send the result when it's done."
    return f"Got it — working on it.{where}"[:_HUD_MAX_CHARS]


def hud_trim(text: str) -> str:
    """Fit a reply to the HUD's short-text constraint."""
    text = (text or "").strip()
    return text if len(text) <= _HUD_MAX_CHARS else text[: _HUD_MAX_CHARS - 1] + "…"


class GlassesChannel(Channel):
    name = "glasses"

    def __init__(
        self,
        handler: Callable[[IncomingMessage], Awaitable[str]],
        *,
        deadline_s: float = _DEFAULT_DEADLINE_S,
        secondary_channel: str | None = None,
        deliver: Callable[[str, str], Awaitable[None]] | None = None,
        spawn: Callable[[Awaitable], object] | None = None,
        allowed_user_ids=None,
    ):
        super().__init__(handler)
        self.deadline_s = float(deadline_s)
        self.secondary_channel = secondary_channel
        # Where a finished long-task result is delivered (the secondary channel).
        self._deliver = deliver
        self._spawn = spawn or asyncio.create_task
        self.allowed_user_ids = normalize_allowlist(allowed_user_ids, "GLASSES_ALLOWED_USER_IDS")
        if not self.allowed_user_ids:
            raise ValueError("Set GLASSES_ALLOWED_USER_IDS to restrict who can drive the agent")

    async def handle_utterance(self, user_id: str, text: str) -> str:
        """Process one HUD utterance and return the text to show **now**.

        Quick → the answer (within the deadline; a slow quick answer degrades to
        an ack-then-run). Long → an immediate ack while the task runs in the
        background and its result is delivered to the secondary channel.
        """
        if not is_allowed(user_id, self.allowed_user_ids):
            return "Sorry, you're not authorized to drive this agent."
        msg = IncomingMessage(user_id=user_id, text=text, channel=self.name)
        if classify_utterance(text) == "quick":
            try:
                reply = await asyncio.wait_for(self.handler(msg), timeout=self.deadline_s)
                return hud_trim(reply)
            except asyncio.TimeoutError:
                # Took too long for the HUD: fall back to ack-then-run.
                self._spawn(self._run_and_deliver(msg))
                return ack_message(self.secondary_channel)
        # Long task: ack now, run in the background, deliver the full result.
        self._spawn(self._run_and_deliver(msg))
        return ack_message(self.secondary_channel)

    async def _run_and_deliver(self, msg: IncomingMessage) -> None:
        try:
            result = await self.handler(msg)
        except Exception:  # pragma: no cover -- delivery never crashes the bridge
            log.exception("glasses: background task failed")
            return
        if self._deliver is not None and result:
            try:
                await self._deliver(msg.user_id, result)
            except Exception:  # pragma: no cover
                log.exception("glasses: secondary delivery failed")

    async def start(self) -> None:  # pragma: no cover -- transport fronts /webhook/start
        raise NotImplementedError(
            "GlassesChannel is driven by the inbound webhook bridge; it does not "
            "run its own loop. Front POST /webhook/start with the glasses shim.")

    async def send(self, user_id: str, text: str) -> None:
        if self._deliver is not None:
            await self._deliver(user_id, hud_trim(text))

    async def stop(self) -> None:
        return None


__all__ = ["GlassesChannel", "classify_utterance", "ack_message", "hud_trim"]
