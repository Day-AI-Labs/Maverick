"""Structured logging for production deployments.

Set ``MAVERICK_LOG_FORMAT=json`` to emit one JSON object per line --
parseable by Loki/CloudWatch/Datadog/etc. Default stays human-readable.

Set ``MAVERICK_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR`` (default INFO).

Per-goal trace context is propagated through ``contextvars`` so every
log line emitted inside ``run_goal`` is automatically tagged with the
goal id, conversation id, and channel without callers passing it
through every function.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
from typing import Any

_goal_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "maverick_goal_id", default=None,
)
_conversation_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "maverick_conversation_id", default=None,
)
_channel_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "maverick_channel", default=None,
)


def set_goal_context(
    goal_id: int | None = None,
    conversation_id: int | None = None,
    channel: str | None = None,
) -> None:
    """Bind context for log lines emitted in this async/sync task."""
    if goal_id is not None:
        _goal_id_var.set(goal_id)
    if conversation_id is not None:
        _conversation_id_var.set(conversation_id)
    if channel is not None:
        _channel_var.set(channel)


def clear_goal_context() -> None:
    _goal_id_var.set(None)
    _conversation_id_var.set(None)
    _channel_var.set(None)


class _ContextFilter(logging.Filter):
    """Attach goal/conversation/channel context to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.goal_id = _goal_id_var.get()
        record.conversation_id = _conversation_id_var.get()
        record.channel = _channel_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    # Skip these stdlib LogRecord attrs; everything else (custom extras
    # + context) is included automatically.
    _STDLIB = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message",
    }

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        # Add filter-attached context + any caller-passed extras.
        for k, v in record.__dict__.items():
            if k in self._STDLIB or k.startswith("_"):
                continue
            if k in ("goal_id", "conversation_id", "channel") and v is None:
                continue
            try:
                json.dumps(v)
                out[k] = v
            except (TypeError, ValueError):
                out[k] = str(v)
        return json.dumps(out, separators=(",", ":"))


_configured = False


def configure_logging(
    level: str | None = None,
    fmt: str | None = None,
) -> None:
    """Configure root logging. Idempotent.

    Reads from env:
      MAVERICK_LOG_LEVEL  default INFO
      MAVERICK_LOG_FORMAT json|text  default text
    """
    global _configured
    if _configured:
        return

    level_name = (level or os.environ.get("MAVERICK_LOG_LEVEL", "INFO")).upper()
    fmt_name = (fmt or os.environ.get("MAVERICK_LOG_FORMAT", "text")).lower()

    handler = logging.StreamHandler(stream=sys.stderr)
    if fmt_name == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
        ))
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    # Don't double-handle if user already configured logging.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level_name, logging.INFO))

    _configured = True
