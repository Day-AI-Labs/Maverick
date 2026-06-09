"""ChatGPT browser-session adapter.

Drives chat.openai.com / chatgpt.com using the user's own session cookie
captured from their browser. Replays the cookie against the same
internal endpoints the web UI uses.

This is a best-effort adapter: OpenAI's internal API is not a stable
contract. When it changes (and it has, multiple times), this adapter
breaks loudly. Fall back to BYOK (OPENAI_API_KEY) is always available.

Limitations:
  - Text completions only. Native tool-use isn't exposed via consumer
    chat; tools=[...] raises NotImplementedError.
  - No thinking blocks. ``thinking_budget`` is ignored.
  - Token usage isn't reported by the consumer endpoint; Budget gets a
    best-effort approximation from output length.
"""
from __future__ import annotations

import json
import logging
import uuid

from ..budget import Budget
from ..llm import LLMResponse
from .base import (
    approx_record_budget,
    cookie_header,
    iter_sse_data_payloads,
    require_httpx,
    resolve_session,
    stringify_messages,
    tool_use_unsupported,
)

log = logging.getLogger(__name__)


# Endpoint constants. Update here if OpenAI restructures the routes.
_BASE_URL = "https://chatgpt.com"
_AUTH_PATH = "/api/auth/session"
_CONVERSATION_PATH = "/backend-api/conversation"

_DEFAULT_TIMEOUT = 120.0

# Browser-like UA + headers reduce false-positive bot detection. We do
# NOT defeat CAPTCHA, rate limits, or any active security control --
# this is just the standard set a real browser sends.
_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/event-stream",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": _BASE_URL,
    "Referer": f"{_BASE_URL}/",
}


def _parse_sse_response(stream_text: str) -> str:
    """Pull the final assistant text out of a ChatGPT SSE stream.

    The stream is a sequence of ``data: {...}`` lines terminated by
    ``data: [DONE]``. Each event carries a 'message' with the current
    cumulative content. We return the last non-empty content seen.
    """
    last_text = ""
    for payload in iter_sse_data_payloads(stream_text):
        payload = payload.strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        msg = event.get("message") or {}
        content = msg.get("content") or {}
        # Only accept assistant TEXT frames. ChatGPT's stream interleaves
        # thoughts / moderation / status frames, and emits trailing assistant
        # frames with an empty part (parts=[""]); the old code accepted any
        # string part, so an empty trailing frame clobbered the real answer.
        author_role = (msg.get("author") or {}).get("role")
        parts = content.get("parts") or []
        if (
            author_role in (None, "assistant")
            and content.get("content_type") in (None, "text")
            and parts and isinstance(parts[0], str) and parts[0]
        ):
            last_text = "".join(p for p in parts if isinstance(p, str))
    return last_text


class ChatGPTSessionClient:
    """Replays a captured ChatGPT session cookie against chatgpt.com."""

    PROVIDER_KEY = "chatgpt-session"
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, session: dict | None = None):
        require_httpx()
        self._session = resolve_session(
            session,
            self.PROVIDER_KEY,
            "No ChatGPT session stored. Run `maverick init` and pick "
            "'browser session' for the ChatGPT provider, or paste your "
            "session cookie via `maverick session import chatgpt`.",
        )

    def _cookie_header(self) -> str:
        return cookie_header(
            self._session.get("cookies") or {},
            "ChatGPT session has no cookies. Re-capture from your browser.",
        )

    def _auth_headers(self, access_token: str | None = None) -> dict:
        headers = dict(_BASE_HEADERS)
        headers["Cookie"] = self._cookie_header()
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def _fetch_access_token(self, client) -> str:
        """ChatGPT requires a bearer token derived from the session cookie.

        The /api/auth/session endpoint returns the current access token
        for the signed-in cookie.
        """
        # Cached token may still be valid; try it first to save a round trip.
        cached = self._session.get("access_token")
        if cached:
            return cached
        resp = client.get(
            _BASE_URL + _AUTH_PATH,
            headers=self._auth_headers(),
            timeout=_DEFAULT_TIMEOUT,
        )
        if resp.status_code == 401:
            raise RuntimeError(
                "ChatGPT session cookie rejected (401). Cookie has likely "
                "expired -- re-capture from your browser and re-import."
            )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("accessToken") or data.get("access_token")
        if not token:
            raise RuntimeError(
                "ChatGPT /api/auth/session returned no accessToken. "
                "Endpoint may have changed; consider BYOK fallback."
            )
        return token

    def _build_request_body(self, prompt: str, model: str) -> dict:
        msg_id = str(uuid.uuid4())
        return {
            "action": "next",
            "messages": [
                {
                    "id": msg_id,
                    "author": {"role": "user"},
                    "content": {
                        "content_type": "text",
                        "parts": [prompt],
                    },
                }
            ],
            "parent_message_id": str(uuid.uuid4()),
            "model": model,
            "timezone_offset_min": 0,
            # Don't persist agent runs to the user's ChatGPT history or feed them
            # to model training -- these prompts carry the user's private goals
            # and data (matches claude_session's no-history behavior).
            "history_and_training_disabled": True,
        }

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        if tools:
            raise tool_use_unsupported("ChatGPT", "OPENAI_API_KEY")
        if thinking_budget:
            log.debug("ChatGPT session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        with httpx.Client(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            token = self._fetch_access_token(client)
            resp = client.post(
                _BASE_URL + _CONVERSATION_PATH,
                headers=self._auth_headers(token),
                json=self._build_request_body(prompt, target_model),
            )
            if resp.status_code == 401:
                raise RuntimeError(
                    "ChatGPT rejected the session (401) on /backend-api/"
                    "conversation. Cookie likely expired -- re-capture."
                )
            if resp.status_code == 429:
                raise RuntimeError(
                    "ChatGPT rate-limited (429). Your subscription's hourly "
                    "quota is exhausted; try again later or use BYOK."
                )
            resp.raise_for_status()
            text = _parse_sse_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "chatgpt-session", "model": target_model},
        )

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        if tools:
            raise tool_use_unsupported("ChatGPT", "OPENAI_API_KEY")
        if thinking_budget:
            log.debug("ChatGPT session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            cached = self._session.get("access_token")
            if cached:
                token = cached
            else:
                auth_resp = await client.get(
                    _BASE_URL + _AUTH_PATH,
                    headers=self._auth_headers(),
                )
                if auth_resp.status_code == 401:
                    raise RuntimeError(
                        "ChatGPT session rejected (401). Cookie expired."
                    )
                auth_resp.raise_for_status()
                data = auth_resp.json()
                token = data.get("accessToken") or data.get("access_token")
                if not token:
                    raise RuntimeError(
                        "ChatGPT /api/auth/session returned no accessToken."
                    )
            resp = await client.post(
                _BASE_URL + _CONVERSATION_PATH,
                headers=self._auth_headers(token),
                json=self._build_request_body(prompt, target_model),
            )
            if resp.status_code == 401:
                raise RuntimeError("ChatGPT session rejected (401). Re-capture.")
            if resp.status_code == 429:
                raise RuntimeError("ChatGPT rate-limited (429).")
            resp.raise_for_status()
            text = _parse_sse_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "chatgpt-session", "model": target_model},
        )
