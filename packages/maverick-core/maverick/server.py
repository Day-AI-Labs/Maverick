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

from .budget import budget_from_config
from .config import load_config
from .llm import LLM
from .orchestrator import run_goal
from .sandbox import build_sandbox
from .world_model import WorldModel, open_world, world_for_tenant

log = logging.getLogger(__name__)


def _reclaim_tenant_orphans() -> int:
    """Reclaim orphan goals across every per-tenant ``world.db`` on startup.

    The default-world reclaim in :meth:`Server.run` only sweeps
    ``~/.maverick/world.db``. With per-user tenancy on, each tenant has its own
    ``~/.maverick/tenants/<t>/world.db`` whose goals left ``active``/``pending``
    by a crash would otherwise never be reclaimed.

    No-op (returns 0) when ``tenant_by_user_enabled()`` is off -- single-tenant
    behaviour is unchanged. Otherwise enumerate the existing tenant dirs and
    reclaim each tenant's world through a temporary ``WorldModel`` instance,
    summing the counts without populating the live tenant cache.

    Fail-soft: a missing tenants dir or a bad/unreadable tenant entry is
    skipped, never crashing startup.
    """
    from .paths import maverick_home, tenant_by_user_enabled

    if not tenant_by_user_enabled():
        return 0
    tenants_dir = maverick_home() / "tenants"
    try:
        entries = list(tenants_dir.iterdir())
    except OSError:  # missing dir (no tenant has run yet) or unreadable -> nothing to sweep
        return 0
    total = 0
    for entry in entries:
        try:
            if not entry.is_dir():
                continue
            world_db = entry / "world.db"
            if not world_db.is_file():
                continue
            with WorldModel(world_db) as world:
                total += world.reclaim_orphan_goals()
        except Exception:  # one bad tenant dir must not abort the sweep
            log.exception("orphan reclaim failed for tenant dir %s", entry.name)
    return total


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

    def _tenant_door_refusal(self, tenant: str) -> str | None:
        """Read-only admission check for a per-tenant message at the channel door.

        Returns a user-facing refusal string, or None to admit. Covers the
        roster (suspended), the provisioned daily-spend cap, and plan feature
        gating (the ``channels`` entitlement). Registry read errors fail soft
        (admit); a suspension/over-quota/plan denial is a deliberate refusal.
        """
        try:
            from .tenant_registry import (
                TenantSuspended,
                assert_tenant_active,
                tenant_over_quota,
            )
        except Exception:  # pragma: no cover -- registry module optional
            TenantSuspended = None  # type: ignore[assignment]
        if TenantSuspended is not None:
            try:
                assert_tenant_active(tenant)
            except TenantSuspended:
                log.warning("message refused: tenant %s suspended", tenant)
                return "⚠ This workspace is suspended. Contact your administrator."
            except Exception:  # pragma: no cover -- fail-soft on reads
                log.exception("tenant roster check failed; allowing")
            try:
                quota_reason = tenant_over_quota(tenant)
            except Exception:  # pragma: no cover -- fail-soft on reads
                quota_reason = None
            if quota_reason:
                log.warning("message refused: %s", quota_reason)
                return f"⚠ {quota_reason}"

        # Plan feature gating: a registered tenant whose plan lacks the
        # "channels" entitlement may not drive the agent over a channel. No-op
        # for unprovisioned per-user tenant ids (feature_allowed admits anything
        # not in the registry), so the default tenant_by_user path is unaffected.
        from .billing import feature_allowed
        if not feature_allowed("channels", tenant=tenant):
            log.warning("message refused: tenant %s plan lacks channel access", tenant)
            return ("⚠ This workspace's plan does not include channel access. "
                    "Contact your administrator to upgrade.")
        return None

    async def _handle_message(self, msg) -> str:
        if self._shield is not None:
            verdict = self._shield.scan_input(msg.text)
            if not verdict.allowed:
                return f"⚠ Blocked: {'; '.join(verdict.reasons)}"

        from .oidc import OIDCError, oidc_enabled, verify_oidc_token
        from .paths import tenant_by_user_enabled, tenant_scope

        # The authenticated sender. Room-based adapters keep msg.user_id as the
        # reply target and expose the human via msg.principal_id; the tenant, the
        # conversation key, and run_goal's user_id must ALL agree on it -- else a
        # user's world.db lands under a different tenant than their memory/audit.
        # When OIDC is enabled, do not trust the channel-provided principal:
        # fail closed unless a verified ID token supplies the Maverick principal.
        if oidc_enabled():
            try:
                principal_id = verify_oidc_token(_extract_oidc_token(msg)).principal
            except OIDCError:
                log.warning(
                    "OIDC authentication failed for inbound %s message",
                    msg.channel or "unknown",
                )
                return "⚠ Authentication failed: OIDC token is missing or invalid."
        else:
            principal_id = getattr(msg, "principal_id", msg.user_id)

        # Resolve the per-tenant world ONCE. When per-user tenancy is on, this
        # message's goal/conversation/turns land in that user's own world.db
        # (~/.maverick/tenants/<channel>:<principal_id>/world.db) -- the SAME
        # tenant the tenant_scope() below pins for cross-session memory + audit,
        # so all three stores stay co-located. Off (default) -> tenant is None and
        # we reuse the SHARED self.world unchanged (``world is self.world``), so
        # the legacy single-tenant path is byte-for-byte identical and we never
        # open a second connection to ~/.maverick/world.db. self.world also still
        # backs startup orphan-reclaim and the dashboard. If per-user tenant
        # resolution fails, reject the message rather than running attacker input
        # against the shared world and breaking tenant isolation.
        tenant = None
        if tenant_by_user_enabled():
            tenant = f"{msg.channel or 'unknown'}:{principal_id}"
        try:
            world = self.world if tenant is None else world_for_tenant(tenant)
        except Exception:
            log.exception("tenant world resolution failed; rejecting message")
            return "⚠ Tenant isolation is unavailable for this message. Try again later."

        # Multi-tenant serve: enforce the tenant roster + plan at the channel
        # door BEFORE any goal is created. No-op until an operator provisions
        # tenants. Read-only refusal reasons (suspended / over daily-spend cap /
        # plan lacks channel access) are returned as a message; None = admit.
        if tenant is not None:
            refusal = self._tenant_door_refusal(tenant)
            if refusal:
                return refusal

        # Per-tenant concurrency ceiling (noisy-neighbor protection). Derived
        # from the tenant's plan entitlement; no-op when tenant is None or the
        # plan is unlimited. Held across the whole goal run and released in the
        # finally below so a crash never leaks a slot.
        from . import tenant_concurrency
        if not tenant_concurrency.acquire(tenant):
            log.warning("message refused: tenant %s at concurrency ceiling", tenant)
            return ("⚠ This workspace is at its concurrent-task limit. "
                    "Try again once a running task finishes.")

        try:
            # Multi-turn: a single (channel, user_id) gets one conversation
            # row. Every inbound message becomes a 'user' turn; the
            # orchestrator's final answer is appended as 'assistant' turn
            # inside run_goal so future messages have history.

            # EU AI Act Article 50: disclose AI to new channel users on
            # first turn. `first_turn_disclosure` checks the conversation
            # row (creates if needed) and returns None on follow-up turns.
            from .compliance import first_turn_disclosure
            disclosure = first_turn_disclosure(
                world,
                channel=msg.channel or "unknown",
                user_id=principal_id,
            )

            conversation = world.get_or_create_conversation(
                channel=msg.channel or "unknown",
                user_id=principal_id,
            )
            world.append_turn(conversation.id, "user", msg.text)

            from .deployment import require_enterprise_or_die
            require_enterprise_or_die()

            title = msg.text[:80]
            goal_id = world.create_goal(title, msg.text)

            budget = budget_from_config()
            try:
                # Per-user tenant isolation when enabled (no-op otherwise): scopes
                # the run's cross-session memory to the authenticated sender, then
                # restores. Room-based adapters keep msg.user_id as the reply target
                # and expose the sender via msg.principal_id.
                with tenant_scope(channel=msg.channel, user_id=principal_id):
                    result = await run_goal(
                        self.llm, world, budget, goal_id,
                        sandbox=self.sandbox, max_depth=self.max_depth,
                        conversation_id=conversation.id,
                        channel=msg.channel or "unknown",
                        user_id=f"{msg.channel or 'unknown'}:{principal_id}",
                    )
            except Exception:
                log.exception("goal #%s run failed", goal_id)
                try:
                    world.set_goal_status(goal_id, "blocked", result="internal error")
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
        finally:
            # Always free the tenant's concurrency slot, on every exit path.
            tenant_concurrency.release(tenant)

    def add_channel(self, channel) -> None:
        self._channels.append(channel)

    async def run(self) -> None:
        """Run all channels concurrently. One channel crashing logs but doesn't kill others."""
        if not self._channels:
            raise ValueError("no channels registered")
        # Reclaim any goals stuck in 'active'/'pending' from a prior
        # crash. Without this, SIGKILL/OOM mid-run leaves ghosts that
        # show in /goals forever. Sweeps the default world; with per-user
        # tenancy on, _reclaim_tenant_orphans() also sweeps every tenant's
        # own world.db (a crash strands goals there too).
        try:
            reclaimed = self.world.reclaim_orphan_goals()
            reclaimed += _reclaim_tenant_orphans()
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
        for c, result in zip(self._channels, results, strict=False):
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
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
        allowed_chat_ids={str(v) for v in allowed_chat_ids} if allowed_chat_ids is not None else None,
    ))


def _wire_discord(server, cfg):
    from maverick_channels.discord import DiscordChannel
    token = cfg.get("bot_token") or os.environ.get("DISCORD_BOT_TOKEN")
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(DiscordChannel(
        handler=server._handle_message,
        token=token,
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))


def _wire_slack(server, cfg):
    from maverick_channels.slack import SlackChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(SlackChannel(
        handler=server._handle_message,
        app_token=cfg.get("app_token") or os.environ.get("SLACK_APP_TOKEN"),
        bot_token=cfg.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN"),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
        # [channels.slack] thread_replies: answers post under the asking
        # message's thread instead of interleaving into the channel.
        thread_replies=cfg.get("thread_replies"),
    ))


def _wire_signal(server, cfg):
    from maverick_channels.signal import SignalChannel
    phone = cfg.get("phone_number")
    if not phone:
        raise RuntimeError("signal channel requires phone_number in config")
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(SignalChannel(
        handler=server._handle_message,
        phone_number=phone,
        signal_cli_path=cfg.get("signal_cli_path"),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))


def _wire_email(server, cfg):
    from maverick_channels.email import EmailChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
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
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))


def _wire_matrix(server, cfg):
    from maverick_channels.matrix import MatrixChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(MatrixChannel(
        handler=server._handle_message,
        homeserver=cfg["homeserver"],
        user_id=cfg["user_id"],
        access_token=cfg.get("access_token") or os.environ.get("MATRIX_ACCESS_TOKEN"),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))




def _wire_bluesky(server, cfg):
    from maverick_channels.bluesky import BlueskyChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(BlueskyChannel(
        handler=server._handle_message,
        handle=cfg.get("handle") or os.environ.get("BLUESKY_HANDLE"),
        password=cfg.get("password") or os.environ.get("BLUESKY_PASSWORD"),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
        poll_interval=cfg.get("poll_interval", 30),
    ))


def _wire_mastodon(server, cfg):
    from maverick_channels.mastodon import MastodonChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(MastodonChannel(
        handler=server._handle_message,
        instance=cfg.get("instance") or os.environ.get("MASTODON_INSTANCE"),
        access_token=cfg.get("access_token") or os.environ.get("MASTODON_ACCESS_TOKEN"),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
        poll_interval=cfg.get("poll_interval", 30),
    ))

def _wire_whatsapp(server, cfg):
    from maverick_channels.whatsapp import WhatsAppChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(WhatsAppChannel(
        handler=server._handle_message,
        account_sid=cfg.get("account_sid") or os.environ.get("TWILIO_ACCOUNT_SID"),
        auth_token=cfg.get("auth_token") or os.environ.get("TWILIO_AUTH_TOKEN"),
        from_number=cfg.get("from_number"),
        port=cfg.get("port", 8765),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))


def _wire_whatsapp_cloud(server, cfg):
    from maverick_channels.whatsapp_cloud import WhatsAppCloudChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(WhatsAppCloudChannel(
        handler=server._handle_message,
        access_token=cfg.get("access_token") or os.environ.get("WHATSAPP_CLOUD_ACCESS_TOKEN"),
        phone_number_id=cfg.get("phone_number_id")
        or os.environ.get("WHATSAPP_CLOUD_PHONE_NUMBER_ID"),
        verify_token=cfg.get("verify_token") or os.environ.get("WHATSAPP_CLOUD_VERIFY_TOKEN"),
        app_secret=cfg.get("app_secret") or os.environ.get("WHATSAPP_CLOUD_APP_SECRET"),
        port=cfg.get("port", 8767),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))


def _wire_threads(server, cfg):
    from maverick_channels.threads import ThreadsChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(ThreadsChannel(
        handler=server._handle_message,
        access_token=cfg.get("access_token") or os.environ.get("THREADS_ACCESS_TOKEN"),
        user_id=cfg.get("user_id") or os.environ.get("THREADS_USER_ID"),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
        poll_seconds=cfg.get("poll_seconds", 30),
    ))


def _wire_rcs(server, cfg):
    from maverick_channels.rcs import RcsChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(RcsChannel(
        handler=server._handle_message,
        agent_id=cfg.get("agent_id") or os.environ.get("RCS_AGENT_ID"),
        service_account_json=cfg.get("service_account_json")
        or os.environ.get("RCS_SERVICE_ACCOUNT_JSON"),
        webhook_token=cfg.get("webhook_token") or os.environ.get("RCS_WEBHOOK_TOKEN"),
        port=cfg.get("port", 8768),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))


def _wire_sms(server, cfg):
    from maverick_channels.sms import SMSChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(SMSChannel(
        handler=server._handle_message,
        account_sid=cfg.get("account_sid") or os.environ.get("TWILIO_ACCOUNT_SID"),
        auth_token=cfg.get("auth_token") or os.environ.get("TWILIO_AUTH_TOKEN"),
        from_number=cfg.get("from_number"),
        port=cfg.get("port", 8766),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))


def _wire_imessage(server, cfg):
    from maverick_channels.imessage import iMessageChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(iMessageChannel(
        handler=server._handle_message,
        poll_interval=cfg.get("poll_interval", 5),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))


def _wire_irc(server, cfg):
    from maverick_channels.irc import IRCChannel
    allowed_user_ids = cfg.get("allowed_user_ids")
    server.add_channel(IRCChannel(
        server._handle_message,
        cfg.get("server") or os.environ.get("IRC_SERVER"),
        nick=cfg.get("nick", "maverick"),
        port=cfg.get("port", 6697),
        tls=cfg.get("tls", True),
        channels=cfg.get("channels"),
        password=cfg.get("password") or os.environ.get("IRC_PASSWORD"),
        allowed_user_ids={str(v) for v in allowed_user_ids} if allowed_user_ids is not None else None,
    ))


def _wire_voice(server, cfg):
    from maverick_channels.voice import VoiceChannel
    server.add_channel(VoiceChannel(
        handler=server._handle_message,
        # Let VoiceChannel resolve the key from the provider-specific env
        # var (VAPI/RETELL/BLAND) when config doesn't pin one explicitly.
        api_key=cfg.get("api_key"),
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
    "whatsapp_cloud": _wire_whatsapp_cloud,
    "threads": _wire_threads,
    "rcs": _wire_rcs,
    "sms":      _wire_sms,
    "imessage": _wire_imessage,
    "voice":    _wire_voice,
    "irc":      _wire_irc,
}


def _advise_channel_tenancy(server) -> None:
    """Warn when a multi-tenant deployment shares one global channel identity.

    Channels are global listeners built once from ``[channels.*]``: a single
    Slack/Telegram/email bot identity per process. Inbound replies still route
    back to the originating channel (no cross-tenant reply leak), but every
    tenant shares that one bot identity and its allow-lists. When distinct
    per-tenant bot identities are required, run one Maverick instance per tenant
    (the Helm chart + per-tenant ``tenants/<id>/config.toml`` overlay make this
    cheap) rather than many tenants behind one process. Advisory only; never
    blocks boot.
    """
    try:
        from .paths import tenant_by_user_enabled
        from .tenant_registry import list_tenants
        multi = tenant_by_user_enabled() or len(list_tenants()) > 1
        if multi and server._channels:
            log.warning(
                "multi-tenant deployment detected with %d global channel(s) (%s): "
                "all tenants share one bot identity per channel. For distinct "
                "per-tenant bot identities, run one instance per tenant "
                "(see deploy/helm + per-tenant config). See docs/multi-tenancy.md.",
                len(server._channels),
                ", ".join(c.name for c in server._channels),
            )
    except Exception:  # pragma: no cover -- advisory must never block boot
        pass


def build_from_config() -> Server:
    cfg = load_config()
    # Shared predicate (maverick.config): env keys, base-url envs, or a
    # [providers.<name>] table all count. This was the last hard-coded
    # ANTHROPIC_API_KEY-only gate -- `start` and the dashboard already
    # accepted config-only self-hosted setups that `serve` refused.
    from .config import any_provider_configured
    if not any_provider_configured():
        raise RuntimeError(
            "No LLM provider configured. Run 'maverick init', export "
            "ANTHROPIC_API_KEY (or another provider key), or add a "
            "[providers.<name>] api_key/base_url to ~/.maverick/config.toml."
        )

    world = open_world()
    llm = LLM()
    sandbox_cfg = cfg.get("sandbox", {})
    backend = sandbox_cfg.get("backend")
    # Default workdir mirrors config.get_sandbox()'s documented ~/maverick-workspace
    # default rather than Path.cwd(), so `serve` and the rest of the kernel agree.
    from .config import get_sandbox
    workdir = Path(sandbox_cfg.get("workdir", get_sandbox()["workdir"])).expanduser()
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

    _advise_channel_tenancy(server)

    # If [queue] backend selects a task queue, run goals out-of-process on a
    # worker pool instead of in this channel-server process. No-op by default.
    try:
        from .queue_dispatcher import install_from_config
        queue_installed = install_from_config()
    except Exception:  # pragma: no cover -- never block server boot
        log.exception("queue dispatcher install failed (running in-process)")
        queue_installed = False
    # [grpc_dispatch] target: execute goals on a remote gRPC worker. The
    # queue backend wins when both are configured (it already owns dispatch).
    if not queue_installed:
        try:
            from .grpc_dispatcher import install_from_config as install_grpc
            install_grpc()
        except Exception:  # pragma: no cover -- never block server boot
            log.exception("gRPC dispatcher install failed (running in-process)")

    return server


def _extract_oidc_token(msg) -> str:
    """Best-effort extraction of an OIDC ID token from a channel message.

    Channel adapters can pass the token explicitly as ``id_token``/``oidc_token``
    or as a bearer token in ``authorization``. Webhook-style adapters may keep
    the original request/dict on ``raw``; support those header shapes too.
    """
    for attr in ("id_token", "oidc_token"):
        value = getattr(msg, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()

    authorization = getattr(msg, "authorization", None)
    if not authorization:
        raw = getattr(msg, "raw", None)
        headers = getattr(raw, "headers", None)
        if headers is None and isinstance(raw, dict):
            headers = raw.get("headers")
        if headers is not None:
            try:
                authorization = (
                    headers.get("authorization") or headers.get("Authorization")
                )
            except AttributeError:
                authorization = None
        if not authorization and isinstance(raw, dict):
            value = raw.get("id_token") or raw.get("oidc_token")
            if isinstance(value, str) and value.strip():
                return value.strip()

    if isinstance(authorization, str):
        prefix = "Bearer "
        if authorization.startswith(prefix):
            return authorization[len(prefix):].strip()
        return authorization.strip()
    return ""
