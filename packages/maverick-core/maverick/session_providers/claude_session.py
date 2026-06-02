"""Claude.ai browser-session adapter.

Drives claude.ai using the user's own sessionKey cookie. Replays the
cookie against the same internal endpoints the web UI uses.

Best-effort: claude.ai's internal API is not a stable contract. When
it changes (and it has, multiple times), this adapter breaks loudly.
Fall back to BYOK (ANTHROPIC_API_KEY) is always available.

Limitations:
  - Text completions only. Native tool-use isn't exposed to consumer
    chat; tools=[...] raises NotImplementedError.
  - Cookies expire (~weeks for claude.ai, much longer than ChatGPT).
  - Token usage isn't returned by the consumer endpoint; Budget gets
    a best-effort approximation from output length.

ToS reality: Anthropic's claude.ai usage policy restricts programmatic
access to claude.ai for consumer accounts. Maverick only operates on
the user's own session against their own account; what they do with
that is their call. We never bypass CAPTCHA / rate limits / Cloudflare
or any other security control.
"""
from __future__ import annotations

import json
import logging
import uuid

from ..budget import Budget
from ..llm import LLMResponse
from . import cookie_store
from .base import (
    approx_record_budget,
    iter_sse_data_payloads,
    stringify_messages,
    tool_use_unsupported,
)

log = logging.getLogger(__name__)


_BASE_URL = "https://claude.ai"
_ORGS_PATH = "/api/organizations"
_CONV_CREATE_TEMPLATE = "/api/organizations/{org_id}/chat_conversations"
_COMPLETION_TEMPLATE = (
    "/api/organizations/{org_id}/chat_conversations/{conv_uuid}/completion"
)

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
    "Referer": f"{_BASE_URL}/chats",
    "anthropic-client-platform": "web_claude_ai",
}


def _parse_sse_response(stream_text: str) -> str:
    """Concatenate incremental ``completion`` deltas from a Claude SSE stream.

    Unlike ChatGPT's cumulative format, Claude streams ``data: {...}``
    events where each carries an additional CHUNK of text in
    ``completion``. We concatenate, not overwrite.
    """
    pieces: list[str] = []
    for payload in iter_sse_data_payloads(stream_text):
        payload = payload.strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        # Modern delta format.
        delta = event.get("completion")
        if isinstance(delta, str):
            pieces.append(delta)
            continue
        # Newer "content_block_delta" style emits text under
        # delta.text or delta.partial_json.
        d = event.get("delta") or {}
        text = d.get("text") or d.get("partial_json")
        if isinstance(text, str):
            pieces.append(text)
    return "".join(pieces)


class ClaudeSessionClient:
    """Replays a captured claude.ai sessionKey cookie against claude.ai."""

    PROVIDER_KEY = "claude-session"
    DEFAULT_MODEL = "claude-sonnet-4-6"

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
                "No Claude session stored. Run `maverick init` and pick "
                "'browser session' for the Claude provider, or paste your "
                "session cookie via `maverick session import claude`."
            )

    def _cookie_header(self) -> str:
        cookies = self._session.get("cookies") or {}
        if not cookies:
            raise RuntimeError(
                "Claude session has no cookies. Re-capture from your browser."
            )
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    def _headers(self) -> dict:
        headers = dict(_BASE_HEADERS)
        headers["Cookie"] = self._cookie_header()
        return headers

    def _resolve_org_id(self, client) -> str:
        """Discover the user's organization id. Cached in the session
        blob across calls so we don't re-fetch it on every request."""
        cached = self._session.get("org_id")
        if cached:
            return cached
        resp = client.get(
            _BASE_URL + _ORGS_PATH,
            headers=self._headers(),
            timeout=_DEFAULT_TIMEOUT,
        )
        if resp.status_code == 401:
            raise RuntimeError(
                "Claude session cookie rejected (401). Cookie has likely "
                "expired -- re-capture from your browser and re-import."
            )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            raise RuntimeError(
                "Claude /api/organizations returned no organizations. "
                "Endpoint may have changed; consider BYOK fallback."
            )
        # Pick the first org with chat capability (consumer accounts have
        # exactly one org with capability 'chat').
        for org in data:
            caps = org.get("capabilities") or []
            if "chat" in caps:
                org_id = org.get("uuid") or org.get("id")
                if org_id:
                    # Cache for the session lifetime (in-memory only;
                    # we don't persist to disk since this is cheap).
                    self._session["org_id"] = org_id
                    return org_id
        # Fall back to first org if capabilities aren't reported.
        first = data[0]
        org_id = first.get("uuid") or first.get("id")
        if not org_id:
            raise RuntimeError(
                "Claude /api/organizations: no uuid/id in response."
            )
        self._session["org_id"] = org_id
        return org_id

    def _create_conversation(self, client, org_id: str, model: str) -> str:
        """Create an ephemeral conversation. Returns the conversation uuid.

        Each completion call is paired with a fresh conversation so we
        don't pollute the user's chat history with agent runs.
        """
        body = {
            "uuid": str(uuid.uuid4()),
            "name": "",  # blank name -> invisible-ish in the UI
            "model": model,
        }
        resp = client.post(
            _BASE_URL + _CONV_CREATE_TEMPLATE.format(org_id=org_id),
            headers=self._headers(),
            json=body,
            timeout=_DEFAULT_TIMEOUT,
        )
        if resp.status_code == 401:
            raise RuntimeError(
                "Claude session rejected (401) creating conversation."
            )
        if resp.status_code == 403:
            raise RuntimeError(
                "Claude session forbidden (403) creating conversation. "
                "Your account may not have access to this model."
            )
        resp.raise_for_status()
        data = resp.json()
        conv_uuid = data.get("uuid") or body["uuid"]
        return conv_uuid

    def _build_completion_body(self, prompt: str, model: str) -> dict:
        return {
            "prompt": prompt,
            "timezone": "UTC",
            "model": model,
            "rendering_mode": "messages",
            "parent_message_uuid": "00000000-0000-4000-8000-000000000000",
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
            raise tool_use_unsupported("Claude", "ANTHROPIC_API_KEY")
        if thinking_budget:
            log.debug("Claude session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        with httpx.Client(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            org_id = self._resolve_org_id(client)
            conv_uuid = self._create_conversation(client, org_id, target_model)
            resp = client.post(
                _BASE_URL + _COMPLETION_TEMPLATE.format(
                    org_id=org_id, conv_uuid=conv_uuid,
                ),
                headers=self._headers(),
                json=self._build_completion_body(prompt, target_model),
            )
            if resp.status_code == 401:
                raise RuntimeError(
                    "Claude rejected the session (401) on completion. "
                    "Cookie likely expired -- re-capture."
                )
            if resp.status_code == 429:
                raise RuntimeError(
                    "Claude rate-limited (429). Your subscription's quota "
                    "is exhausted; try again later or use BYOK."
                )
            resp.raise_for_status()
            text = _parse_sse_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "claude-session", "model": target_model},
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
            raise tool_use_unsupported("Claude", "ANTHROPIC_API_KEY")
        if thinking_budget:
            log.debug("Claude session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            cached_org = self._session.get("org_id")
            if cached_org:
                org_id = cached_org
            else:
                orgs_resp = await client.get(
                    _BASE_URL + _ORGS_PATH,
                    headers=self._headers(),
                )
                if orgs_resp.status_code == 401:
                    raise RuntimeError(
                        "Claude session rejected (401). Cookie expired."
                    )
                orgs_resp.raise_for_status()
                data = orgs_resp.json()
                if not isinstance(data, list) or not data:
                    raise RuntimeError(
                        "Claude /api/organizations returned no orgs."
                    )
                org_id = data[0].get("uuid") or data[0].get("id")
                if not org_id:
                    raise RuntimeError("Claude orgs response missing uuid.")
                self._session["org_id"] = org_id

            conv_body = {
                "uuid": str(uuid.uuid4()),
                "name": "",
                "model": target_model,
            }
            conv_resp = await client.post(
                _BASE_URL + _CONV_CREATE_TEMPLATE.format(org_id=org_id),
                headers=self._headers(),
                json=conv_body,
            )
            if conv_resp.status_code in (401, 403):
                raise RuntimeError(
                    f"Claude session rejected ({conv_resp.status_code}) "
                    "creating conversation."
                )
            conv_resp.raise_for_status()
            conv_uuid = conv_resp.json().get("uuid") or conv_body["uuid"]

            resp = await client.post(
                _BASE_URL + _COMPLETION_TEMPLATE.format(
                    org_id=org_id, conv_uuid=conv_uuid,
                ),
                headers=self._headers(),
                json=self._build_completion_body(prompt, target_model),
            )
            if resp.status_code == 401:
                raise RuntimeError("Claude session rejected (401). Re-capture.")
            if resp.status_code == 429:
                raise RuntimeError("Claude rate-limited (429).")
            resp.raise_for_status()
            text = _parse_sse_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "claude-session", "model": target_model},
        )
