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
from typing import Optional

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

    def __init__(self, handler, token: Optional[str] = None):
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

    async def _on_message(self, update: "Update", _ctx: "ContextTypes.DEFAULT_TYPE") -> None:
        if not update.message or not update.message.text:
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
