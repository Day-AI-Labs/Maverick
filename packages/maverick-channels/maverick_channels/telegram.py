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
        token: str | None = None,
        allowed_user_ids: set[str] | None = None,
        allowed_chat_ids: set[str] | None = None,
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
        self._app: Application | None = None
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
    def _normalize_allowlist(values: set[str] | None, env_name: str) -> set[str]:
        if values is not None:
            return {str(v).strip() for v in values if str(v).strip()}
        raw = os.environ.get(env_name, "")
        return {item.strip() for item in raw.split(",") if item.strip()}

    def _is_authorized(self, update: Update) -> bool:
        user_id = str(update.effective_user.id) if update.effective_user else ""
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        chat_type = getattr(update.effective_chat, "type", None)

        # An allowlisted sender is always authorized, in any chat.
        if self.allowed_user_ids and user_id in self.allowed_user_ids:
            return True

        # A chat allowlist must NOT authorize every member of a group: any
        # participant of an allowlisted group could otherwise drive the agent.
        # A private (1:1) chat has a single sender, so an allowlisted private
        # chat is equivalent to an allowlisted user -- honour it there only.
        # In groups, require the sender to be on TELEGRAM_ALLOWED_USER_IDS.
        if (
            chat_type == "private"
            and self.allowed_chat_ids
            and chat_id in self.allowed_chat_ids
        ):
            return True
        return False

    async def _on_message(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        if not self._is_authorized(update):
            log.warning("unauthorized telegram access: user_id=%s chat_id=%s",
                        getattr(update.effective_user, "id", None),
                        getattr(update.effective_chat, "id", None))
            return
        # effective_user is None for channel posts / anonymous admins;
        # _is_authorized denies those (they can't be attributed to an
        # allowlisted sender), but guard here too rather than AttributeError.
        msg = IncomingMessage(
            user_id=str(update.effective_user.id) if update.effective_user else "",
            text=update.message.text,
            channel="telegram",
            raw=update,
            message_id=str(update.message.message_id),
        )
        try:
            reply = await self.dispatch_text(msg)
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

    async def send_threaded(
        self, user_id: str, text: str, *, reply_to: str | None = None,
    ) -> None:
        if self._app is None:
            raise RuntimeError("channel not started")
        kwargs = {"chat_id": int(user_id), "text": text}
        if reply_to:
            try:
                kwargs["reply_to_message_id"] = int(reply_to)
            except (TypeError, ValueError):
                pass  # un-threadable id -> plain send
        await self._app.bot.send_message(**kwargs)

    async def stop(self) -> None:
        if self._app is None:
            return
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
