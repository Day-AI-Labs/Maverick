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
Tool-call scans happen inside the agent loop (see agent.py). All scans
fail open with a warning if shield isn't available.

Resilience: each channel runs in its own asyncio task. A single channel
crashing logs an error but doesn't take the others down.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from .budget import Budget
from .config import load_config
from .llm import LLM
from .orchestrator import run_goal
from .sandbox import build_sandbox
from .world_model import WorldModel

log = logging.getLogger(__name__)


class Server:
    def __init__(
        self,
        world: WorldModel,
        llm: LLM,
        sandbox=None,
        max_depth: int = 3,
    ):
        self.world = world
        self.llm = llm
        self.sandbox = sandbox or build_sandbox()
        self.max_depth = max_depth
        self._channels: list = []
        self._tasks: list[asyncio.Task] = []
        self._shield = None
        try:
            from maverick_shield import Shield
            self._shield = Shield.from_config()
            if self._shield.enabled:
                log.info("Agent Shield enabled (profile=%s)", self._shield.profile)
        except ImportError:
            log.warning("maverick-shield not installed; running without safety scans")

    async def _handle_message(self, msg) -> str:
        if self._shield is not None:
            verdict = self._shield.scan_input(msg.text)
            if not verdict.allowed:
                return f"⚠ Blocked: {'; '.join(verdict.reasons)}"

        # Multi-turn: a single (channel, user_id) gets one conversation
        # row. Every inbound message becomes a 'user' turn; the
        # orchestrator's final answer is appended as 'assistant' turn
        # inside run_goal so future messages have history.

        # EU AI Act Article 50: disclose AI to new channel users on
        # first turn. `first_turn_disclosure` checks the conversation
        # row (creates if needed) and returns None on follow-up turns.
        from .compliance import first_turn_disclosure
        disclosure = first_turn_disclosure(
            self.world,
            channel=msg.channel or "unknown",
            user_id=msg.user_id,
        )

        conversation = self.world.get_or_create_conversation(
            channel=msg.channel or "unknown",
            user_id=msg.user_id,
        )
        self.world.append_turn(conversation.id, "user", msg.text)

        title = msg.text[:80]
        goal_id = self.world.create_goal(title, msg.text)

        budget = Budget()
        try:
            result = await run_goal(
                self.llm, self.world, budget, goal_id,
                sandbox=self.sandbox, max_depth=self.max_depth,
                conversation_id=conversation.id,
                channel=msg.channel or "unknown",
                user_id=f"{msg.channel or 'unknown'}:{msg.user_id}",
            )
        except Exception:
            log.exception("goal #%s run failed", goal_id)
            try:
                self.world.set_goal_status(goal_id, "blocked", result="internal error")
            except Exception:  # pragma: no cover
                pass
            # Don't leak internal error details to untrusted channel users.
            return "⚠ An internal error occurred. Try again or check the logs."

        if self._shield is not None:
            verdict = self._shield.scan_output(result)
            if not verdict.allowed:
                return f"⚠ Output blocked: {'; '.join(verdict.reasons)}"

        if disclosure is not None:
            return f"{disclosure}\n\n{result}"
        return result

    def add_channel(self, channel) -> None:
        self._channels.append(channel)

    async def run(self) -> None:
        """Run all channels concurrently. One channel crashing logs but doesn't kill others."""
        if not self._channels:
            raise ValueError("no channels registered")
        # Reclaim any goals stuck in 'active'/'pending' from a prior
        # crash. Without this, SIGKILL/OOM mid-run leaves ghosts that
        # show in /goals forever.
        try:
            reclaimed = self.world.reclaim_orphan_goals()
            if reclaimed:
                log.warning("reclaimed %d orphan goal(s) from prior crash", reclaimed)
        except Exception:  # pragma: no cover
            log.exception("orphan goal reclaim failed on serve startup")
        log.info(
            "starting %d channel(s): %s",
            len(self._channels),
            ", ".join(c.name for c in self._channels),
        )
        self._tasks = [
            asyncio.create_task(c.start(), name=f"channel-{c.name}")
            for c in self._channels
        ]
        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        for c, result in zip(self._channels, results):
            if isinstance(result, Exception):
                log.error("channel %s crashed: %s", c.name, result)

    async def stop(self) -> None:
        for t in self._tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(
            *(c.stop() for c in self._channels), return_exceptions=True,
        )


def _wire_telegram(server, cfg):
    from maverick_channels.telegram import TelegramChannel
    token = cfg.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
    allowed_user_ids = cfg.get("allowed_user_ids")
    allowed_chat_ids = cfg.get("allowed_chat_ids")
    server.add_channel(TelegramChannel(
        handler=server._handle_message,
        token=token,
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids else None,
        allowed_chat_ids={str(v) for v in allowed_chat_ids} if allowed_chat_ids else None,
    ))


def _wire_discord(server, cfg):
    from maverick_channels.discord import DiscordChannel
    token = cfg.get("bot_token") or os.environ.get("DISCORD_BOT_TOKEN")
    allowed = cfg.get("allowed_user_ids")
    server.add_channel(DiscordChannel(
        handler=server._handle_message,
        token=token,
        allowed_user_ids={str(v) for v in allowed} if allowed else None,
    ))


def _wire_slack(server, cfg):
    from maverick_channels.slack import SlackChannel
    allowed = cfg.get("allowed_user_ids")
    server.add_channel(SlackChannel(
        handler=server._handle_message,
        app_token=cfg.get("app_token") or os.environ.get("SLACK_APP_TOKEN"),
        bot_token=cfg.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN"),
        allowed_user_ids={str(v) for v in allowed} if allowed else None,
    ))


def _wire_signal(server, cfg):
    from maverick_channels.signal import SignalChannel
    phone = cfg.get("phone_number")
    if not phone:
        raise RuntimeError("signal channel requires phone_number in config")
    allowed = cfg.get("allowed_user_ids")
    server.add_channel(SignalChannel(
        handler=server._handle_message,
        phone_number=phone,
        signal_cli_path=cfg.get("signal_cli_path"),
        allowed_user_ids={str(v) for v in allowed} if allowed else None,
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
    allowed = cfg.get("allowed_user_ids")
    server.add_channel(MatrixChannel(
        handler=server._handle_message,
        homeserver=cfg["homeserver"],
        user_id=cfg["user_id"],
        access_token=cfg.get("access_token") or os.environ.get("MATRIX_ACCESS_TOKEN"),
        allowed_user_ids={str(v) for v in allowed} if allowed else None,
    ))




def _wire_bluesky(server, cfg):
    from maverick_channels.bluesky import BlueskyChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(BlueskyChannel(
        handler=server._handle_message,
        handle=cfg.get("handle") or os.environ.get("BLUESKY_HANDLE"),
        password=cfg.get("password") or os.environ.get("BLUESKY_PASSWORD"),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids else None,
        poll_interval=cfg.get("poll_interval", 30),
    ))


def _wire_mastodon(server, cfg):
    from maverick_channels.mastodon import MastodonChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(MastodonChannel(
        handler=server._handle_message,
        instance=cfg.get("instance") or os.environ.get("MASTODON_INSTANCE"),
        access_token=cfg.get("access_token") or os.environ.get("MASTODON_ACCESS_TOKEN"),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids else None,
        poll_interval=cfg.get("poll_interval", 30),
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


def _wire_voice(server, cfg):
    from maverick_channels.voice import VoiceChannel
    server.add_channel(VoiceChannel(
        handler=server._handle_message,
        api_key=cfg.get("api_key") or os.environ.get("VAPI_API_KEY"),
        phone_number=cfg.get("phone_number"),
        port=cfg.get("port", 8770),
        assistant_id=cfg.get("assistant_id"),
        provider=cfg.get("provider", "vapi"),
        webhook_token=cfg.get("webhook_token") or os.environ.get("VAPI_WEBHOOK_TOKEN"),
        allowed_callers=cfg.get("allowed_callers"),
    ))


_WIRES = {
    "telegram": _wire_telegram,
    "discord":  _wire_discord,
    "slack":    _wire_slack,
    "signal":   _wire_signal,
    "email":    _wire_email,
    "matrix":   _wire_matrix,
    "bluesky":  _wire_bluesky,
    "mastodon": _wire_mastodon,
    "whatsapp": _wire_whatsapp,
    "sms":      _wire_sms,
    "imessage": _wire_imessage,
    "voice":    _wire_voice,
}


def build_from_config() -> Server:
    cfg = load_config()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to ~/.maverick/.env or export it."
        )

    world = WorldModel()
    llm = LLM()
    sandbox_cfg = cfg.get("sandbox", {})
    backend = sandbox_cfg.get("backend")
    workdir = Path(sandbox_cfg.get("workdir", str(Path.cwd()))).expanduser()
    sandbox = build_sandbox(workdir=workdir, backend=backend)
    server = Server(world=world, llm=llm, sandbox=sandbox)

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
