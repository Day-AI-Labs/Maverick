"""Email channel: IMAP poll for incoming, SMTP for outgoing.

v0.1.1 fix: both IMAP and SMTP calls now have a 30-second connect
timeout. A wedged Gmail connection no longer pins the channel thread
forever.

Set up:
  1. Use an account with an app password (Gmail / Fastmail / etc.)
  2. Set in config:
        [channels.email]
        enabled = true
        imap_host = "imap.gmail.com"
        imap_user = "${EMAIL_USER}"
        imap_password = "${EMAIL_APP_PASSWORD}"
        smtp_host = "smtp.gmail.com"
        smtp_port = 465
        smtp_user = "${EMAIL_USER}"
        smtp_password = "${EMAIL_APP_PASSWORD}"

No extra dependencies needed (uses stdlib `imaplib` + `smtplib`).
"""
from __future__ import annotations

import asyncio
import email
import email.utils
import imaplib
import logging
import smtplib
from email.message import EmailMessage

from .base import Channel, IncomingMessage, backoff_delay, is_allowed, normalize_allowlist

log = logging.getLogger(__name__)

IMAP_TIMEOUT = 30.0
SMTP_TIMEOUT = 30.0


class EmailChannel(Channel):
    name = "email"

    def __init__(
        self,
        handler,
        imap_host: str,
        imap_user: str,
        imap_password: str,
        smtp_host: str,
        smtp_user: str,
        smtp_password: str,
        smtp_port: int = 465,
        poll_interval: int = 30,
        allowed_user_ids=None,
    ):
        super().__init__(handler)
        # Without an allowlist, ANY inbound sender could drive the agent.
        # Addresses compared case-insensitively. Require one.
        self.allowed_user_ids = {
            a.lower() for a in normalize_allowlist(allowed_user_ids, "EMAIL_ALLOWED_USER_IDS")
        }
        if not self.allowed_user_ids:
            raise ValueError("Set EMAIL_ALLOWED_USER_IDS to restrict access")
        self.imap_host = imap_host
        self.imap_user = imap_user
        self.imap_password = imap_password
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.poll_interval = poll_interval
        self._stop = False

    async def start(self) -> None:
        log.info("Email channel polling %s every %ds", self.imap_host, self.poll_interval)
        errors = 0
        while not self._stop:
            try:
                messages = await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_unseen),
                    timeout=IMAP_TIMEOUT * 2,
                )
                errors = 0
            except asyncio.TimeoutError:
                log.warning("IMAP poll timed out; continuing")
                messages = []
                errors += 1
            except Exception:  # pragma: no cover
                log.exception("email poll failed")
                messages = []
                errors += 1
            for from_addr, subject, body in messages:
                if not is_allowed((from_addr or "").lower(), self.allowed_user_ids):
                    log.warning("unauthorized email access: from=%s", from_addr)
                    continue
                text = f"Subject: {subject}\n\n{body}" if subject else body
                msg = IncomingMessage(
                    user_id=from_addr, text=text, channel="email",
                )
                try:
                    reply = await self.dispatch_text(msg)
                except Exception as e:  # pragma: no cover
                    log.exception("handler error")
                    reply = f"⚠ error: {e}"
                reply_subject = f"Re: {subject}" if subject else "Maverick"
                # A single SMTP send failure must not abort the batch —
                # otherwise already-handled messages get reprocessed (and
                # re-run the swarm) on the next poll.
                try:
                    await self.send(from_addr, reply, subject=reply_subject)
                except Exception:
                    log.exception("email send failed for %s", from_addr)
            await asyncio.sleep(backoff_delay(self.poll_interval, errors))

    def _fetch_unseen(self) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        with imaplib.IMAP4_SSL(self.imap_host, timeout=IMAP_TIMEOUT) as mail:
            mail.login(self.imap_user, self.imap_password)
            mail.select("INBOX")
            _, data = mail.search(None, "UNSEEN")
            for num in data[0].split():
                # BODY.PEEK does NOT implicitly set \Seen; we mark it explicitly
                # below so the message is never re-fetched by a second poller or
                # after a restart (which would re-drive the swarm at real cost).
                _, msg_data = mail.fetch(num, "(BODY.PEEK[])")
                if not msg_data or not msg_data[0]:
                    continue
                payload = msg_data[0][1]
                if not isinstance(payload, (bytes, bytearray)):
                    continue
                m = email.message_from_bytes(payload)
                from_addr = email.utils.parseaddr(m.get("From", ""))[1]
                subject = m.get("Subject", "")
                body = self._extract_body(m)
                # Claim the message before handing it off: at-most-once delivery
                # (a crash mid-dispatch drops one message rather than looping the
                # swarm forever). Mirrors the dedup the other channels do.
                try:
                    mail.store(num, "+FLAGS", "\\Seen")
                except Exception:  # pragma: no cover - flag store best-effort
                    log.warning("email: could not mark message %s seen", num)
                if from_addr and body:
                    out.append((from_addr, subject, body))
        return out

    def _extract_body(self, msg) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, (bytes, bytearray)):
                        return payload.decode(errors="replace").strip()
            return ""
        payload = msg.get_payload(decode=True)
        if isinstance(payload, (bytes, bytearray)):
            return payload.decode(errors="replace").strip()
        return str(payload or "").strip()

    async def send(self, user_id: str, text: str, subject: str = "Maverick") -> None:
        await asyncio.to_thread(self._send_sync, user_id, text, subject)

    def _send_sync(self, to_addr: str, text: str, subject: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.smtp_user
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(text)
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
            smtp.login(self.smtp_user, self.smtp_password)
            smtp.send_message(msg)

    async def stop(self) -> None:
        self._stop = True
