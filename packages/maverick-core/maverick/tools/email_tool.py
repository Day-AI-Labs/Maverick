"""Email send/read tool.

Send via SMTP, read via IMAP. Both use Python's stdlib (smtplib +
imaplib + email parsers) — no extra dependencies.

Config (env first, then ~/.maverick/config.toml [email]):
  EMAIL_USER          / [email] user
  EMAIL_APP_PASSWORD  / [email] app_password   (use an app password,
                                                NOT your account password)
  EMAIL_SMTP_HOST     / [email] smtp_host    (default smtp.gmail.com)
  EMAIL_SMTP_PORT     / [email] smtp_port    (default 465 for SSL)
  EMAIL_IMAP_HOST     / [email] imap_host    (default imap.gmail.com)

The tool refuses to send when MAVERICK_EMAIL_DISABLE=1.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_EMAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["send", "list_inbox", "fetch"],
            "description": "Operation.",
        },
        "to": {"type": "string", "description": "Recipient address (send)."},
        "cc": {"type": "string", "description": "CC addresses, comma-separated."},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "limit": {"type": "integer", "description": "Max messages (list_inbox)."},
        "uid": {"type": "string", "description": "Message UID (fetch)."},
        "folder": {"type": "string", "description": "IMAP folder (default INBOX)."},
        "unread_only": {"type": "boolean"},
    },
    "required": ["op"],
}


def _cfg(key: str, env: str, default: str = "") -> str:
    val = os.environ.get(env, "").strip()
    if val:
        return val
    try:
        from ..config import load_config
        cfg = (load_config() or {}).get("email") or {}
        return str(cfg.get(key, default)).strip()
    except Exception:
        return default


def _send(args: dict[str, Any]) -> str:
    if os.environ.get("MAVERICK_EMAIL_DISABLE") == "1":
        return "ERROR: email send disabled by MAVERICK_EMAIL_DISABLE=1"
    import smtplib
    from email.message import EmailMessage

    user = _cfg("user", "EMAIL_USER")
    pw = _cfg("app_password", "EMAIL_APP_PASSWORD")
    host = _cfg("smtp_host", "EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(_cfg("smtp_port", "EMAIL_SMTP_PORT", "465"))
    if not user or not pw:
        return (
            "ERROR: email requires EMAIL_USER + EMAIL_APP_PASSWORD "
            "(use an app password, NOT your account password)."
        )

    to = (args.get("to") or "").strip()
    subject = args.get("subject") or ""
    body = args.get("body") or ""
    if not to or not subject:
        return "ERROR: send requires `to` and `subject`"

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    if args.get("cc"):
        msg["Cc"] = args["cc"]
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls()
                s.login(user, pw)
                s.send_message(msg)
    except Exception as e:
        return f"ERROR: smtp send failed: {type(e).__name__}: {e}"
    log.info("email.send: %s subject=%r", to, subject)
    return f"sent to {to} (subject: {subject[:60]})"


def _list_inbox(args: dict[str, Any]) -> str:
    import imaplib
    from email import message_from_bytes
    from email.header import decode_header, make_header

    user = _cfg("user", "EMAIL_USER")
    pw = _cfg("app_password", "EMAIL_APP_PASSWORD")
    host = _cfg("imap_host", "EMAIL_IMAP_HOST", "imap.gmail.com")
    if not user or not pw:
        return "ERROR: list_inbox requires EMAIL_USER + EMAIL_APP_PASSWORD"
    folder = args.get("folder") or "INBOX"
    limit = max(1, min(int(args.get("limit") or 20), 200))
    criterion = "UNSEEN" if args.get("unread_only") else "ALL"

    try:
        with imaplib.IMAP4_SSL(host) as m:
            m.login(user, pw)
            m.select(folder)
            status, data = m.search(None, criterion)
            if status != "OK":
                return f"ERROR: imap search failed: {status}"
            ids = (data[0] or b"").split()[-limit:]
            ids.reverse()  # newest first
            rows: list[str] = []
            for uid in ids:
                status, data = m.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                if status != "OK" or not data:
                    continue
                raw = data[0][1] if isinstance(data[0], tuple) else data[0]
                msg = message_from_bytes(raw)
                subj = str(make_header(decode_header(msg.get("Subject", ""))))
                frm = str(make_header(decode_header(msg.get("From", ""))))
                date = msg.get("Date", "")
                rows.append(f"{uid.decode()}  {date[:25]}  {frm[:40]}  {subj[:60]}")
    except Exception as e:
        return f"ERROR: imap list failed: {type(e).__name__}: {e}"
    if not rows:
        return f"(no messages in {folder} matching {criterion})"
    return "\n".join(rows)


def _fetch(args: dict[str, Any]) -> str:
    import imaplib
    from email import message_from_bytes

    user = _cfg("user", "EMAIL_USER")
    pw = _cfg("app_password", "EMAIL_APP_PASSWORD")
    host = _cfg("imap_host", "EMAIL_IMAP_HOST", "imap.gmail.com")
    if not user or not pw:
        return "ERROR: fetch requires EMAIL_USER + EMAIL_APP_PASSWORD"
    uid = (args.get("uid") or "").strip()
    if not uid:
        return "ERROR: fetch requires uid"
    folder = args.get("folder") or "INBOX"

    try:
        with imaplib.IMAP4_SSL(host) as m:
            m.login(user, pw)
            m.select(folder)
            status, data = m.fetch(uid.encode(), "(BODY.PEEK[])")
            if status != "OK" or not data:
                return f"ERROR: fetch failed: {status}"
            raw = data[0][1] if isinstance(data[0], tuple) else data[0]
            msg = message_from_bytes(raw)
    except Exception as e:
        return f"ERROR: imap fetch failed: {type(e).__name__}: {e}"

    body_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body_parts.append(
                        part.get_payload(decode=True).decode("utf-8", errors="replace")
                    )
                except Exception:
                    pass
    else:
        try:
            body_parts.append(
                msg.get_payload(decode=True).decode("utf-8", errors="replace")
            )
        except Exception:
            pass
    body = "\n".join(body_parts).strip()
    return (
        f"From: {msg.get('From', '')}\n"
        f"To: {msg.get('To', '')}\n"
        f"Date: {msg.get('Date', '')}\n"
        f"Subject: {msg.get('Subject', '')}\n\n"
        f"{body[:20_000]}"
    )


def _run(args: dict[str, Any]) -> str:
    op = args.get("op")
    if not op:
        return "ERROR: op is required"
    if op == "send":
        return _send(args)
    if op == "list_inbox":
        return _list_inbox(args)
    if op == "fetch":
        return _fetch(args)
    return f"ERROR: unknown op {op!r}"


def email_tool() -> Tool:
    return Tool(
        name="email",
        description=(
            "Send / list / fetch email via SMTP + IMAP. ops: send "
            "(to, subject, body, optional cc), list_inbox (limit, "
            "unread_only, folder), fetch (uid, folder). Config via "
            "EMAIL_USER + EMAIL_APP_PASSWORD env (use an app password). "
            "MAVERICK_EMAIL_DISABLE=1 blocks sending."
        ),
        input_schema=_EMAIL_SCHEMA,
        fn=_run,
    )
