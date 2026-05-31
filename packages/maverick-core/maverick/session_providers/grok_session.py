"""Grok (xAI via x.com) browser-session adapter.

Drives x.com/i/grok using the user's X (Twitter) session. Requires an
X Premium / Premium+ subscription on the account.

Best-effort: x.com's internal API isn't a stable contract. BYOK
fallback (XAI_API_KEY against api.x.ai) is always available.

Cookies needed: ``auth_token`` and ``ct0`` (the CSRF token). x.com's
internal API requires ``x-csrf-token`` header to match the ct0 cookie.
"""
from __future__ import annotations

import json
import logging
import uuid

from ..budget import Budget
from ..llm import LLMResponse
from . import cookie_store
from .base import approx_record_budget, stringify_messages

log = logging.getLogger(__name__)


_BASE_URL = "https://x.com"
_GROK_PATH = "/i/api/2/grok/add_response.json"

_DEFAULT_TIMEOUT = 180.0

# Bearer token x.com's web client uses for unauthenticated requests +
# user-cookie auth on top. This is a public constant (visible in the
# bundled JS); it's not a secret.
_X_WEB_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": _BASE_URL,
    "Referer": f"{_BASE_URL}/i/grok",
    "Authorization": f"Bearer {_X_WEB_BEARER}",
    "x-twitter-active-user": "yes",
    "x-twitter-auth-type": "OAuth2Session",
    "x-twitter-client-language": "en",
}


def _parse_sse_response(stream_text: str) -> str:
    """Concatenate text deltas from a Grok streamed response.

    x.com's grok endpoint returns NDJSON (one JSON object per line),
    not classic SSE. Each line has a ``result.message`` chunk.
    """
    pieces: list[str] = []
    for line in stream_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Some chunks are framed as "data: {...}" (SSE-style) and
        # others as raw JSON (NDJSON). Handle both.
        if line.startswith("data:"):
            line = line[len("data:"):].strip()
        if line == "[DONE]":
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = event.get("result") or {}
        message = result.get("message")
        if isinstance(message, str):
            pieces.append(message)
        elif isinstance(result.get("text"), str):
            pieces.append(result["text"])
    return "".join(pieces)


class GrokSessionClient:
    PROVIDER_KEY = "grok-session"
    DEFAULT_MODEL = "grok-4-latest"

    def __init__(self, session: dict | None = None):
        try:
            import httpx  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "httpx not installed. Run: pip install 'maverick-agent[session]'"
            ) from e
        self._session = session or cookie_store.load_session(self.PROVIDER_KEY)
        if not self._session:
            raise RuntimeError(
                "No Grok session stored. Capture via `maverick session import grok`."
            )

    def _cookie_header(self) -> str:
        cookies = self._session.get("cookies") or {}
        if not cookies:
            raise RuntimeError("Grok session has no cookies. Re-capture.")
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    def _headers(self) -> dict:
        headers = dict(_BASE_HEADERS)
        cookies = self._session.get("cookies") or {}
        ct0 = cookies.get("ct0")
        if not ct0:
            raise RuntimeError(
                "Grok session missing 'ct0' cookie (CSRF token). "
                "Re-capture both auth_token AND ct0 from x.com cookies."
            )
        headers["x-csrf-token"] = ct0
        headers["Cookie"] = self._cookie_header()
        return headers

    def _build_body(self, prompt: str, model: str) -> dict:
        return {
            "responses": [{
                "message": prompt,
                "sender": 1,
                "promptSource": "",
                "fileAttachments": [],
            }],
            "systemPromptName": "",
            "grokModelOptionId": model,
            "conversationId": str(uuid.uuid4()),
            "returnSearchResults": False,
            "returnCitations": False,
            "promptMetadata": {"promptSource": "NATURAL", "action": "INPUT"},
            "imageGenerationCount": 0,
            "requestFeatures": {"eagerTweets": True, "serverHistory": False},
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
            raise NotImplementedError(
                "Grok session adapter does not support native tool-use. "
                "Use XAI_API_KEY BYOK for tool-using roles."
            )
        if thinking_budget:
            log.debug("Grok session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        with httpx.Client(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            resp = client.post(
                _BASE_URL + _GROK_PATH,
                headers=self._headers(),
                json=self._build_body(prompt, target_model),
            )
            if resp.status_code == 401:
                raise RuntimeError(
                    "Grok rejected the session (401). auth_token/ct0 "
                    "expired -- re-capture from x.com cookies."
                )
            if resp.status_code == 403:
                raise RuntimeError(
                    "Grok forbidden (403). Account may not have Premium "
                    "access; check x.com/i/premium."
                )
            if resp.status_code == 429:
                raise RuntimeError(
                    "Grok rate-limited (429). Subscription quota exhausted."
                )
            resp.raise_for_status()
            text = _parse_sse_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "grok-session", "model": target_model},
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
            raise NotImplementedError("Grok session does not support tool-use.")
        if thinking_budget:
            log.debug("Grok session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            resp = await client.post(
                _BASE_URL + _GROK_PATH,
                headers=self._headers(),
                json=self._build_body(prompt, target_model),
            )
            if resp.status_code == 401:
                raise RuntimeError("Grok rejected (401). Re-capture.")
            if resp.status_code == 403:
                raise RuntimeError("Grok forbidden (403). Check Premium access.")
            if resp.status_code == 429:
                raise RuntimeError("Grok rate-limited (429).")
            resp.raise_for_status()
            text = _parse_sse_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "grok-session", "model": target_model},
        )
