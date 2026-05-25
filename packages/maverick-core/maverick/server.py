"""Channel-driven server mode.

``maverick serve`` starts a long-running process that:
  - reads enabled channels from config (Telegram, iMessage, etc.)
  - listens on each one
  - for each incoming message, creates a goal and runs the swarm
  - sends the response back via the same channel

Each user gets their own goal/episode in the world model so context is
preserved across messages. Budget caps still apply per-message.

Safety: input and output are run through Agent Shield if installed.
Fails open with a warning if shield isn't available.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from .budget import Budget
from .config import load_config
from .llm import LLM
from .orchestrator import run_goal
from .sandbox import LocalBackend
from .world_model import WorldModel

log = logging.getLogger(__name__)


class Server:
    """Long-running channel server.

    Each incoming message becomes a goal in the world model and is run
    through the swarm. Responses are routed back via the same channel.
    """

    def __init__(
        self,
        world: WorldModel,
        llm: LLM,
        workdir: Optional[Path] = None,
        max_depth: int = 3,
    ):
        self.world = world
        self.llm = llm
        self.workdir = workdir or Path.cwd()
        self.max_depth = max_depth
        self._channels: list = []
        self._shield = None
        try:
            from maverick_shield import Shield
            self._shield = Shield.from_config()
            if self._shield.enabled:
                log.info("Agent Shield enabled (profile=%s)", self._shield.profile)
        except ImportError:
            log.warning("maverick-shield not installed; running without safety scans")

    async def _handle_message(self, msg) -> str:
        """Handler invoked by every channel for each incoming message."""
        if self._shield is not None:
            verdict = self._shield.scan_input(msg.text)
            if not verdict.allowed:
                return f"⚠ Blocked: {'; '.join(verdict.reasons)}"

        title = msg.text[:80]
        description = msg.text
        goal_id = self.world.create_goal(title, description)

        budget = Budget()
        sandbox = LocalBackend(workdir=self.workdir)

        try:
            result = await run_goal(
                self.llm,
                self.world,
                budget,
                goal_id,
                sandbox=sandbox,
                max_depth=self.max_depth,
            )
        except Exception as e:  # pragma: no cover - top-level safety net
            log.exception("goal run failed")
            return f"⚠ Error: {e}"

        if self._shield is not None:
            verdict = self._shield.scan_output(result)
            if not verdict.allowed:
                return f"⚠ Output blocked: {'; '.join(verdict.reasons)}"

        return result

    def add_channel(self, channel) -> None:
        self._channels.append(channel)

    async def run(self) -> None:
        if not self._channels:
            raise ValueError("no channels registered")
        log.info("starting %d channel(s)", len(self._channels))
        await asyncio.gather(*(c.start() for c in self._channels))

    async def stop(self) -> None:
        await asyncio.gather(
            *(c.stop() for c in self._channels), return_exceptions=True
        )


def build_from_config() -> Server:
    """Construct a Server with channels enabled in ~/.maverick/config.toml.

    Raises if no channels are enabled or required env vars are missing.
    """
    cfg = load_config()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to ~/.maverick/.env or export it."
        )

    world = WorldModel()
    llm = LLM()
    sandbox_cfg = cfg.get("sandbox", {})
    workdir = Path(sandbox_cfg.get("workdir", str(Path.cwd()))).expanduser()
    server = Server(world=world, llm=llm, workdir=workdir)

    channels_cfg = cfg.get("channels", {})

    # Telegram
    tg_cfg = channels_cfg.get("telegram", {})
    if tg_cfg.get("enabled"):
        try:
            from maverick_channels.telegram import TelegramChannel
        except ImportError as e:
            raise RuntimeError(
                "Telegram channel enabled in config but maverick-channels[telegram] "
                "is not installed. Run:  pip install 'maverick-channels[telegram]'"
            ) from e
        token = tg_cfg.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
        ch = TelegramChannel(handler=server._handle_message, token=token)
        server.add_channel(ch)
        log.info("enabled Telegram channel")

    if not server._channels:
        raise RuntimeError(
            "No channels enabled in config. Edit ~/.maverick/config.toml "
            "and set [channels.<name>] enabled = true."
        )

    return server
