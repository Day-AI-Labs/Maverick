"""Channel interface.

Normalize every platform (CLI, Telegram, iMessage, ...) to the same shape
so the agent loop doesn't have to care where a message came from.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class IncomingMessage:
    user_id: str
    text: str
    attachments: list[dict] = field(default_factory=list)
    channel: str = ""
    raw: object = None


Handler = Callable[[IncomingMessage], Awaitable[str]]
"""A handler takes a normalized message and returns the agent's reply."""


class Channel(ABC):
    """Abstract channel adapter.

    Lifecycle:
      - ``start()`` blocks (or runs in background) accepting messages.
      - For each message it dispatches to the registered ``Handler``.
      - ``send(user_id, text)`` pushes a reply back to that user.
      - ``stop()`` cleans up.
    """

    name: str

    def __init__(self, handler: Handler):
        self.handler = handler

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def send(self, user_id: str, text: str) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
