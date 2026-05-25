"""Matrix channel via matrix-nio (federated, end-to-end encryptable).

Set up:
  1. Create an account on a Matrix homeserver (matrix.org, self-hosted, etc.)
  2. Get an access token (via Element > Settings > Help & About)
  3. Set in config:
        [channels.matrix]
        enabled = true
        homeserver = "https://matrix.org"
        user_id = "@you:matrix.org"
        access_token = "${MATRIX_ACCESS_TOKEN}"

Requires::

    pip install 'maverick-channels[matrix]'
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .base import Channel, IncomingMessage

log = logging.getLogger(__name__)

try:
    from nio import AsyncClient, MatrixRoom, RoomMessageText
    _HAVE_MATRIX = True
except ImportError:
    _HAVE_MATRIX = False
    AsyncClient = MatrixRoom = RoomMessageText = None  # type: ignore


class MatrixChannel(Channel):
    name = "matrix"

    def __init__(
        self,
        handler,
        homeserver: str,
        user_id: str,
        access_token: Optional[str] = None,
    ):
        super().__init__(handler)
        if not _HAVE_MATRIX:
            raise ImportError(
                "matrix-nio not installed. Run: pip install 'maverick-channels[matrix]'"
            )
        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token or os.environ.get("MATRIX_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("MATRIX_ACCESS_TOKEN not set")
        self._client = AsyncClient(homeserver, user_id)
        self._client.access_token = self.access_token
        self._client.add_event_callback(self._on_message, RoomMessageText)

    async def _on_message(self, room: "MatrixRoom", event: "RoomMessageText") -> None:
        if event.sender == self.user_id:
            return
        msg = IncomingMessage(
            user_id=room.room_id,
            text=event.body,
            channel="matrix",
            raw=event,
        )
        try:
            reply = await self.handler(msg)
        except Exception as e:  # pragma: no cover
            log.exception("handler error")
            reply = f"⚠ error: {e}"
        await self.send(room.room_id, reply)

    async def start(self) -> None:
        log.info("Matrix channel syncing")
        await self._client.sync_forever(timeout=30000, full_state=True)

    async def send(self, user_id: str, text: str) -> None:
        await self._client.room_send(
            room_id=user_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": text},
        )

    async def stop(self) -> None:
        await self._client.close()
