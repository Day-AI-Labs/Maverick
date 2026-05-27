"""Telegram bot channel.

The simplest path to phone-companion mode. Set ``[channels.telegram]
enabled = true`` in ``~/.maverick/config.toml`` and provide a bot token,
and any message you send to your bot reaches the orchestrator.

Requires::

    pip install maverick-channels[telegram]
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Set

from .base import Channel, IncomingMessage

log = logging.getLogger(__name__)

try:
    from telegram import Update
    from telegram.ext import Application, ContextTypes, MessageHandler, filters
    _HAVE_TELEGRAM = True
except ImportError:
    _HAVE_TELEGRAM = False
    Update = ContextTypes = Application = MessageHandler = filters = None  # type: ignore


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(
        self,
        handler,
        token: Optional[str] = None,
        allowed_user_ids: Optional[set[str]] = None,
        allowed_chat_ids: Optional[set[str]] = None,
    ):
        super().__init__(handler)
        if not _HAVE_TELEGRAM:
            raise ImportError(
                "python-telegram-bot not installed. Install with: "
                "pip install maverick-channels[telegram]"
            )
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        self._app: Optional[Application] = None
        self.allowed_user_ids = self._normalize_allowlist(
            allowed_user_ids,
            env_name="TELEGRAM_ALLOWED_USER_IDS",
        )
        self.allowed_chat_ids = self._normalize_allowlist(
            allowed_chat_ids,
            env_name="TELEGRAM_ALLOWED_CHAT_IDS",
        )
        if not self.allowed_user_ids and not self.allowed_chat_ids:
            raise ValueError(
                "Set TELEGRAM_ALLOWED_USER_IDS or TELEGRAM_ALLOWED_CHAT_IDS to restrict access"
            )

    @staticmethod
    def _normalize_allowlist(values: Optional[set[str]], env_name: str) -> Set[str]:
        if values is not None:
            return {str(v).strip() for v in values if str(v).strip()}
        raw = os.environ.get(env_name, "")
        return {item.strip() for item in raw.split(",") if item.strip()}

    def _is_authorized(self, update: "Update") -> bool:
        user_id = str(update.effective_user.id) if update.effective_user else ""
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        if self.allowed_user_ids and user_id in self.allowed_user_ids:
            return True
        if self.allowed_chat_ids and chat_id in self.allowed_chat_ids:
            return True
        return False

    async def _on_message(self, update: "Update", _ctx: "ContextTypes.DEFAULT_TYPE") -> None:
        if not update.message or not update.message.text:
            return
        if not self._is_authorized(update):
            log.warning("unauthorized telegram access: user_id=%s chat_id=%s",
                        getattr(update.effective_user, "id", None),
                        getattr(update.effective_chat, "id", None))
            return
        msg = IncomingMessage(
            user_id=str(update.effective_user.id),
            text=update.message.text,
            channel="telegram",
            raw=update,
        )
        try:
            reply = await self.handler(msg)
        except Exception as e:  # pragma: no cover
            log.exception("handler error")
            reply = f"⚠ error: {e}"
        await update.message.reply_text(reply)

    async def start(self) -> None:
        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))
        log.info("Telegram channel started")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def send(self, user_id: str, text: str) -> None:
        if self._app is None:
            raise RuntimeError("channel not started")
        await self._app.bot.send_message(chat_id=int(user_id), text=text)

    async def stop(self) -> None:
        if self._app is None:
            return
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
