"""Channel-driven server mode.

``maverick serve`` starts a long-running process that:
  - reads enabled channels from config (Telegram, Discord, Slack, Signal,
    WhatsApp, SMS, Email, Matrix, iMessage)
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
        goal_id = self.world.create_goal(title, msg.text)

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
        except Exception as e:  # pragma: no cover
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
        log.info("starting %d channel(s): %s", len(self._channels),
                 ", ".join(c.name for c in self._channels))
        await asyncio.gather(*(c.start() for c in self._channels))

    async def stop(self) -> None:
        await asyncio.gather(
            *(c.stop() for c in self._channels), return_exceptions=True
        )


def _wire_telegram(server, cfg):
    from maverick_channels.telegram import TelegramChannel
    token = cfg.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
    server.add_channel(TelegramChannel(handler=server._handle_message, token=token))


def _wire_discord(server, cfg):
    from maverick_channels.discord import DiscordChannel
    token = cfg.get("bot_token") or os.environ.get("DISCORD_BOT_TOKEN")
    server.add_channel(DiscordChannel(handler=server._handle_message, token=token))


def _wire_slack(server, cfg):
    from maverick_channels.slack import SlackChannel
    server.add_channel(SlackChannel(
        handler=server._handle_message,
        app_token=cfg.get("app_token") or os.environ.get("SLACK_APP_TOKEN"),
        bot_token=cfg.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN"),
    ))


def _wire_signal(server, cfg):
    from maverick_channels.signal import SignalChannel
    phone = cfg.get("phone_number")
    if not phone:
        raise RuntimeError("signal channel requires phone_number in config")
    server.add_channel(SignalChannel(
        handler=server._handle_message,
        phone_number=phone,
        signal_cli_path=cfg.get("signal_cli_path"),
    ))


def _wire_email(server, cfg):
    from maverick_channels.email import EmailChannel
    server.add_channel(EmailChannel(
        handler=server._handle_message,
        imap_host=cfg["imap_host"],
        imap_user=cfg["imap_user"],
        imap_password=cfg["imap_password"],
        smtp_host=cfg["smtp_host"],
        smtp_user=cfg["smtp_user"],
        smtp_password=cfg["smtp_password"],
        smtp_port=cfg.get("smtp_port", 465),
        poll_interval=cfg.get("poll_interval", 30),
    ))


def _wire_matrix(server, cfg):
    from maverick_channels.matrix import MatrixChannel
    server.add_channel(MatrixChannel(
        handler=server._handle_message,
        homeserver=cfg["homeserver"],
        user_id=cfg["user_id"],
        access_token=cfg.get("access_token") or os.environ.get("MATRIX_ACCESS_TOKEN"),
    ))


def _wire_whatsapp(server, cfg):
    from maverick_channels.whatsapp import WhatsAppChannel
    server.add_channel(WhatsAppChannel(
        handler=server._handle_message,
        account_sid=cfg.get("account_sid") or os.environ.get("TWILIO_ACCOUNT_SID"),
        auth_token=cfg.get("auth_token") or os.environ.get("TWILIO_AUTH_TOKEN"),
        from_number=cfg.get("from_number"),
        port=cfg.get("port", 8765),
    ))


def _wire_sms(server, cfg):
    from maverick_channels.sms import SMSChannel
    server.add_channel(SMSChannel(
        handler=server._handle_message,
        account_sid=cfg.get("account_sid") or os.environ.get("TWILIO_ACCOUNT_SID"),
        auth_token=cfg.get("auth_token") or os.environ.get("TWILIO_AUTH_TOKEN"),
        from_number=cfg.get("from_number"),
        port=cfg.get("port", 8766),
    ))


def _wire_imessage(server, cfg):
    from maverick_channels.imessage import iMessageChannel
    server.add_channel(iMessageChannel(
        handler=server._handle_message,
        poll_interval=cfg.get("poll_interval", 5),
    ))


_WIRES = {
    "telegram": _wire_telegram,
    "discord":  _wire_discord,
    "slack":    _wire_slack,
    "signal":   _wire_signal,
    "email":    _wire_email,
    "matrix":   _wire_matrix,
    "whatsapp": _wire_whatsapp,
    "sms":      _wire_sms,
    "imessage": _wire_imessage,
}


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
    for name, wire in _WIRES.items():
        ch_cfg = channels_cfg.get(name, {})
        if not ch_cfg.get("enabled"):
            continue
        try:
            wire(server, ch_cfg)
            log.info("enabled %s channel", name)
        except ImportError as e:
            log.error("channel %s enabled but optional deps missing: %s", name, e)
        except Exception as e:
            log.error("channel %s failed to initialize: %s", name, e)

    if not server._channels:
        raise RuntimeError(
            "No channels enabled (or all failed to initialize). Edit "
            "~/.maverick/config.toml and set [channels.<name>] enabled = true."
        )

    return server
