"""Kimi (Moonshot) browser-session adapter.

Drives kimi.com using the user's own access_token cookie. Replays it
against the same internal endpoints the web UI uses.

Best-effort: kimi.com's internal API isn't a stable contract. BYOK
fallback (MOONSHOT_API_KEY) is always available.

Cookie: ``access_token`` (JWT). Refresh handled by Moonshot's web
client; we re-import on expiry.
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


_BASE_URL = "https://kimi.com"
_CHAT_CREATE_PATH = "/api/chat"
_COMPLETION_TEMPLATE = "/api/chat/{chat_id}/completion/stream"

_DEFAULT_TIMEOUT = 180.0

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/event-stream, application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": _BASE_URL,
    "Referer": f"{_BASE_URL}/",
    "x-language": "en-US",
}


def _parse_sse_response(stream_text: str) -> str:
    """Concatenate ``text`` deltas from a Kimi SSE stream."""
    pieces: list[str] = []
    for payload in iter_sse_data_payloads(stream_text):
        payload = payload.strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "cmpl":
            text = event.get("text")
            if isinstance(text, str):
                pieces.append(text)
        elif "text" in event and isinstance(event["text"], str):
            pieces.append(event["text"])
    return "".join(pieces)


class KimiSessionClient:
    PROVIDER_KEY = "kimi-session"
    DEFAULT_MODEL = "kimi-k2"

    def __init__(self, session: dict | None = None):
        require_httpx()
        self._session = resolve_session(
            session,
            self.PROVIDER_KEY,
            "No Kimi session stored. Run `maverick init` and pick "
            "'browser session' for Kimi, or paste your access_token "
            "via `maverick session import kimi`.",
        )

    def _cookie_header(self) -> str:
        return cookie_header(
            self._session.get("cookies") or {},
            "Kimi session has no cookies. Re-capture.",
        )

    def _headers(self) -> dict:
        headers = dict(_BASE_HEADERS)
        # Kimi uses Bearer auth header derived from access_token cookie.
        cookies = self._session.get("cookies") or {}
        token = cookies.get("access_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["Cookie"] = self._cookie_header()
        return headers

    def _create_chat(self, client, model: str) -> str:
        body = {
            "name": "Maverick session",
            "is_example": False,
            "born_from": "home",
            "kimiplus_id": "kimi",
            "tags": [],
        }
        resp = client.post(
            _BASE_URL + _CHAT_CREATE_PATH,
            headers=self._headers(),
            json=body,
            timeout=_DEFAULT_TIMEOUT,
        )
        if resp.status_code == 401:
            raise RuntimeError(
                "Kimi session rejected (401). Cookie likely expired -- "
                "re-capture via `maverick session import kimi`."
            )
        resp.raise_for_status()
        data = resp.json()
        chat_id = data.get("id") or str(uuid.uuid4())
        return chat_id

    def _build_completion_body(self, prompt: str, model: str) -> dict:
        return {
            "messages": [{"role": "user", "content": prompt}],
            "model": model,
            "use_search": False,
            "extend": {"sidebar": True},
            "kimiplus_id": "kimi",
            "use_research": False,
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
            raise tool_use_unsupported("Kimi", "MOONSHOT_API_KEY")
        if thinking_budget:
            log.debug("Kimi session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        with httpx.Client(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            chat_id = self._create_chat(client, target_model)
            resp = client.post(
                _BASE_URL + _COMPLETION_TEMPLATE.format(chat_id=chat_id),
                headers=self._headers(),
                json=self._build_completion_body(prompt, target_model),
            )
            if resp.status_code == 401:
                raise RuntimeError("Kimi rejected the session (401). Re-capture.")
            if resp.status_code == 429:
                raise RuntimeError(
                    "Kimi rate-limited (429). Subscription quota exhausted."
                )
            resp.raise_for_status()
            text = _parse_sse_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "kimi-session", "model": target_model},
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
            raise tool_use_unsupported("Kimi", "MOONSHOT_API_KEY")
        if thinking_budget:
            log.debug("Kimi session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            create_resp = await client.post(
                _BASE_URL + _CHAT_CREATE_PATH,
                headers=self._headers(),
                json={
                    "name": "Maverick session", "is_example": False,
                    "born_from": "home", "kimiplus_id": "kimi",
                    "tags": [],
                },
            )
            if create_resp.status_code == 401:
                raise RuntimeError("Kimi session rejected (401).")
            create_resp.raise_for_status()
            chat_id = create_resp.json().get("id") or str(uuid.uuid4())

            resp = await client.post(
                _BASE_URL + _COMPLETION_TEMPLATE.format(chat_id=chat_id),
                headers=self._headers(),
                json=self._build_completion_body(prompt, target_model),
            )
            if resp.status_code == 401:
                raise RuntimeError("Kimi rejected (401). Re-capture.")
            if resp.status_code == 429:
                raise RuntimeError("Kimi rate-limited (429).")
            resp.raise_for_status()
            text = _parse_sse_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "kimi-session", "model": target_model},
        )
