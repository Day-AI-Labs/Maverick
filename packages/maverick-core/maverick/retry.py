"""Retry with exponential backoff for transient LLM provider errors.

Tier 1 (SRE reviewer): a single 429 / 503 / connection-reset used to
fail the entire goal. Provider calls now retry with exponential backoff
(1s, 2s, 4s, 8s, max 5 attempts), honoring ``Retry-After`` when the
provider returns one.

Errors we retry:
  - anthropic.RateLimitError, anthropic.APIConnectionError,
    anthropic.InternalServerError, anthropic.APITimeoutError
  - openai.RateLimitError, openai.APIConnectionError,
    openai.InternalServerError, openai.APITimeoutError
  - httpx.ReadTimeout, httpx.ConnectError (transport-level)

Anything else propagates immediately so a bug in our code isn't silently
re-tried.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ._envparse import env_float, env_int

log = logging.getLogger(__name__)

T = TypeVar("T")


MAX_ATTEMPTS = env_int("MAVERICK_LLM_RETRY_ATTEMPTS", 5)
BASE_DELAY = env_float("MAVERICK_LLM_RETRY_BASE_DELAY", 1.0)
MAX_DELAY = env_float("MAVERICK_LLM_RETRY_MAX_DELAY", 30.0)


def _retryable_exception_classes() -> tuple[type, ...]:
    """Resolve retryable exception classes lazily. Optional deps may be missing."""
    classes: list[type] = []
    try:
        import anthropic
        for n in ("RateLimitError", "APIConnectionError", "InternalServerError",
                  "APITimeoutError", "APIStatusError"):
            cls = getattr(anthropic, n, None)
            if cls is not None:
                classes.append(cls)
    except ImportError:
        pass
    try:
        import openai
        for n in ("RateLimitError", "APIConnectionError", "InternalServerError",
                  "APITimeoutError"):
            cls = getattr(openai, n, None)
            if cls is not None:
                classes.append(cls)
    except ImportError:
        pass
    try:
        import httpx
        classes.append(httpx.ReadTimeout)
        classes.append(httpx.ConnectError)
    except ImportError:
        pass
    return tuple(classes) or (Exception,)


def _retry_after_from(exc: Exception) -> float | None:
    """Extract Retry-After (seconds) from a provider exception, if present."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _compute_delay(attempt: int, exc: Exception) -> float:
    """Honor Retry-After if present; else exponential backoff with jitter.

    Council finding: a hostile/buggy server returning `Retry-After: -1`
    would feed time.sleep / asyncio.sleep a negative value and raise
    ValueError, killing the retry loop. We clamp to [0, MAX_DELAY].
    """
    explicit = _retry_after_from(exc)
    if explicit is not None:
        return max(0.0, min(explicit, MAX_DELAY))
    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
    return max(0.0, delay * (0.5 + random.random() * 0.5))


def _is_retryable_status_error(exc: Exception) -> bool:
    """Anthropic APIStatusError covers 429+5xx+4xx; only retry 429/5xx."""
    status = getattr(exc, "status_code", None)
    if status is None:
        return True  # Non-status retryable types are always transient.
    return status == 429 or 500 <= status < 600


def sync_retry(fn: Callable[[], T]) -> T:
    """Run a sync callable, retrying transient provider errors."""
    retryable = _retryable_exception_classes()
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return fn()
        except retryable as e:
            if not _is_retryable_status_error(e):
                raise
            last = e
            if attempt == MAX_ATTEMPTS - 1:
                break
            delay = _compute_delay(attempt, e)
            log.warning(
                "LLM call failed (attempt %d/%d): %s; retry in %.1fs",
                attempt + 1, MAX_ATTEMPTS, type(e).__name__, delay,
            )
            time.sleep(delay)
    assert last is not None
    raise last


async def async_retry(fn: Callable[[], Awaitable[T]]) -> T:
    """Run an async callable, retrying transient provider errors."""
    retryable = _retryable_exception_classes()
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return await fn()
        except retryable as e:
            if not _is_retryable_status_error(e):
                raise
            last = e
            if attempt == MAX_ATTEMPTS - 1:
                break
            delay = _compute_delay(attempt, e)
            log.warning(
                "LLM call failed (attempt %d/%d): %s; retry in %.1fs",
                attempt + 1, MAX_ATTEMPTS, type(e).__name__, delay,
            )
            await asyncio.sleep(delay)
    assert last is not None
    raise last
