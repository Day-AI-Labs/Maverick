"""Channel adapters for Maverick.

A channel normalizes incoming messages from any platform into a shared
``IncomingMessage`` shape, hands it to the orchestrator, and routes the
response back. This is the surface Maverick uses to power phone-companion
mode — the agent itself runs on Desktop or VPS, and channels give a
phone (or any other client) a way to talk to it.

Available channels (18 wired adapters; each requires its provider's
credentials and a per-sender allowlist, default-deny):
  - cli, telegram, discord, slack, signal, email, matrix
  - bluesky, mastodon, irc, threads, rcs, voice
  - whatsapp + sms (Twilio + public webhook), whatsapp_cloud (Meta Graph API)
  - imessage (macOS only)
Enhanced variants layer on these: email_v2 (IMAP IDLE + threading),
discord_stages (Stage voice), streaming_voice (barge-in), rich_render
(KaTeX/Mermaid). signal needs signal-cli on PATH; matrix needs matrix-nio.
"""
from .base import Channel, Handler, IncomingMessage, Reply, as_reply

__version__ = "0.1.6"
__all__ = ["Channel", "IncomingMessage", "Handler", "Reply", "as_reply"]
