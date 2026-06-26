"""Gemini (gemini.google.com) browser-session adapter.

Drives gemini.google.com using the user's Google account session cookies.
This is the most fragile session adapter -- Google's internal RPC uses
SAPISIDHASH-derived auth, multipart-form payloads, and aggressive
Cloudflare/reCAPTCHA on suspicious traffic.

Best-effort. If this breaks, BYOK fallback (GEMINI_API_KEY) against the
free-tier-generous official API is always available.

Cookies needed: ``__Secure-1PSID``, ``__Secure-1PSIDTS``, ``__Secure-1PSIDCC``.
All three must be captured from gemini.google.com (NOT from google.com
proper -- the gemini subdomain has scoped cookies).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time

from ..budget import Budget
from ..llm import LLMResponse
from .base import (
    approx_record_budget,
    cookie_header,
    require_httpx,
    resolve_session,
    stringify_messages,
    tool_use_unsupported,
)

log = logging.getLogger(__name__)


_BASE_URL = "https://gemini.google.com"
_INIT_PATH = "/app"
_QUERY_PATH = (
    "/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
)

_DEFAULT_TIMEOUT = 180.0

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": _BASE_URL,
    "Referer": f"{_BASE_URL}/app",
    "X-Same-Domain": "1",
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
}


def _sapisid_hash(sapisid: str, origin: str = _BASE_URL) -> str:
    """Compute Google's SAPISIDHASH for the Authorization header.

    Format: SAPISIDHASH <timestamp>_<sha1(timestamp + " " + sapisid + " " + origin)>
    The SHA1 is hex-encoded.
    """
    ts = str(int(time.time()))
    raw = f"{ts} {sapisid} {origin}".encode()
    # SAPISIDHASH is Google's protocol: the token IS SHA1(ts + sapisid + origin).
    # The SHA1 is a wire-format requirement, not a security primitive we chose --
    # usedforsecurity=False documents that (and satisfies bandit B324).
    digest = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def _extract_token(html: str, key: str) -> str | None:
    """Pull a JS-assigned token (e.g. SNlM0e -> 'at' token) out of the
    Gemini app HTML on first load."""
    m = re.search(rf'"{re.escape(key)}":"([^"]+)"', html)
    return m.group(1) if m else None


def _extract_text(node: object) -> str:
    """Pull the model text out of Gemini's candidate-content node.

    The text usually arrives as a plain string, but richer responses nest it
    as a one-element list (``["text"]``), a deeper nested list, or a dict with
    a ``text`` key (multimodal frames). Walk those shapes instead of assuming
    a string — the old code returned ``""`` for the dict shape (dropping the
    whole answer) and stringified a nested list as ``"['x']"``.
    """
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        val = node.get("text")
        return val if isinstance(val, str) else ""
    if isinstance(node, list):
        for item in node:
            text = _extract_text(item)
            if text:
                return text
    return ""


def _parse_stream_response(stream_text: str) -> str:
    """Gemini's StreamGenerate emits ``)]}\\\\n`` chunked JSON arrays.

    Each chunk is a JSON array. The model output lives at a fixed
    nested path inside one of those arrays.
    """
    text = stream_text
    text = text.removeprefix(")]}'")
    pieces: list[str] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx] in " \n\r\t":
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            # Some chunks are size prefixes (e.g. "94"); skip non-JSON lines.
            nl = text.find("\n", idx)
            if nl == -1:
                break
            idx = nl + 1
            continue
        idx = end
        # The outer obj is an array; the response candidates are nested
        # inside obj[0][2] as a JSON-encoded string (Google's RPC quirk).
        try:
            if isinstance(obj, list) and obj and obj[0] and len(obj[0]) > 2:
                inner_raw = obj[0][2]
                if isinstance(inner_raw, str):
                    inner = json.loads(inner_raw)
                    # inner[4][0][1][0] is the model's main text.
                    candidates = inner[4] if len(inner) > 4 else []
                    for cand in candidates:
                        if isinstance(cand, list) and len(cand) > 1:
                            content = cand[1]
                            if isinstance(content, list) and content:
                                # Use a distinct name: reassigning `text` here
                                # would clobber the stream buffer the outer
                                # `while idx < len(text)` loop iterates over,
                                # so only the first chunk would ever parse.
                                cand_text = _extract_text(content[0])
                                if cand_text:
                                    pieces.append(cand_text)
                                    break
        except (json.JSONDecodeError, IndexError, TypeError):
            continue
    # Multiple chunks may contain the same incremental update; the LAST
    # piece is the final cumulative answer in Gemini's protocol.
    return pieces[-1] if pieces else ""


class GeminiSessionClient:
    PROVIDER_KEY = "gemini-session"
    DEFAULT_MODEL = "gemini-3-pro"

    def __init__(self, session: dict | None = None):
        require_httpx()
        self._session = resolve_session(
            session,
            self.PROVIDER_KEY,
            "No Gemini session stored. Capture via "
            "`maverick session import gemini`. Note: Gemini's free BYOK "
            "tier is generous; if session capture flakes, use BYOK.",
        )

    def _cookie_header(self) -> str:
        return cookie_header(
            self._session.get("cookies") or {},
            "Gemini session missing __Secure-1PSID cookie. Re-capture from "
            "gemini.google.com (NOT google.com).",
            require_key="__Secure-1PSID",
        )

    def _headers(self) -> dict:
        headers = dict(_BASE_HEADERS)
        cookies = self._session.get("cookies") or {}
        sapisid = cookies.get("SAPISID") or cookies.get("__Secure-1PSID")
        if sapisid:
            headers["Authorization"] = _sapisid_hash(sapisid)
        headers["Cookie"] = self._cookie_header()
        return headers

    def _ensure_at_token(self, client) -> str:
        """Lazy-fetch the 'at' (anti-CSRF) token from the app HTML.

        Cached in the in-memory session dict to avoid re-fetching every
        call. If it expires mid-session, we re-fetch on demand.
        """
        cached = self._session.get("at_token")
        if cached:
            return cached
        resp = client.get(
            _BASE_URL + _INIT_PATH,
            headers={**_BASE_HEADERS, "Cookie": self._cookie_header()},
            timeout=_DEFAULT_TIMEOUT,
        )
        if resp.status_code == 401 or resp.status_code == 403:
            raise RuntimeError(
                "Gemini rejected the session cookie (HTTP "
                f"{resp.status_code}). Cookies likely expired -- re-capture "
                "from gemini.google.com."
            )
        resp.raise_for_status()
        token = _extract_token(resp.text, "SNlM0e")
        if not token:
            raise RuntimeError(
                "Gemini app HTML missing SNlM0e token. Endpoint may have "
                "changed; fall back to GEMINI_API_KEY BYOK."
            )
        self._session["at_token"] = token
        return token

    def _build_form(self, prompt: str, at_token: str) -> dict:
        # Gemini's RPC encodes the prompt as a nested JSON-in-form-field.
        f_req_inner = [None, json.dumps([[prompt], None, None])]
        f_req = json.dumps(f_req_inner)
        return {
            "f.req": f_req,
            "at": at_token,
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
            raise tool_use_unsupported("Gemini", "GEMINI_API_KEY")
        if thinking_budget:
            log.debug("Gemini session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        with httpx.Client(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            at_token = self._ensure_at_token(client)
            params = {
                "bl": "boq_assistant-bard-web-server_20260101.00_p0",
                # Uniform 7-digit id. `str(uuid4().int)[:7]` took the LEADING
                # digits of a 39-digit decimal, which are heavily biased (top
                # digit almost always 1-3) -> far less than 7 digits of entropy
                # and realistic in-session collisions that Gemini's batchexecute
                # can reject (parser then returns "").
                "_reqid": f"{secrets.randbelow(10_000_000):07d}",
                "rt": "c",
            }
            resp = client.post(
                _BASE_URL + _QUERY_PATH,
                headers=self._headers(),
                params=params,
                data=self._build_form(prompt, at_token),
            )
            if resp.status_code == 401:
                raise RuntimeError(
                    "Gemini rejected (401). Cookies expired -- re-capture."
                )
            if resp.status_code == 429:
                raise RuntimeError(
                    "Gemini rate-limited (429). Quota exhausted."
                )
            resp.raise_for_status()
            text = _parse_stream_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "gemini-session", "model": target_model},
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
            raise tool_use_unsupported("Gemini", "GEMINI_API_KEY")
        if thinking_budget:
            log.debug("Gemini session ignores thinking_budget=%s", thinking_budget)
        import httpx

        prompt = stringify_messages(system, messages)
        target_model = model or self.DEFAULT_MODEL
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            cached = self._session.get("at_token")
            if cached:
                at_token = cached
            else:
                init_resp = await client.get(
                    _BASE_URL + _INIT_PATH,
                    headers={**_BASE_HEADERS, "Cookie": self._cookie_header()},
                )
                if init_resp.status_code in (401, 403):
                    raise RuntimeError(
                        f"Gemini rejected session (HTTP {init_resp.status_code})."
                    )
                init_resp.raise_for_status()
                at_token = _extract_token(init_resp.text, "SNlM0e")
                if not at_token:
                    raise RuntimeError(
                        "Gemini app HTML missing SNlM0e token."
                    )
                self._session["at_token"] = at_token

            params = {
                "bl": "boq_assistant-bard-web-server_20260101.00_p0",
                # Uniform 7-digit id. `str(uuid4().int)[:7]` took the LEADING
                # digits of a 39-digit decimal, which are heavily biased (top
                # digit almost always 1-3) -> far less than 7 digits of entropy
                # and realistic in-session collisions that Gemini's batchexecute
                # can reject (parser then returns "").
                "_reqid": f"{secrets.randbelow(10_000_000):07d}",
                "rt": "c",
            }
            resp = await client.post(
                _BASE_URL + _QUERY_PATH,
                headers=self._headers(),
                params=params,
                data=self._build_form(prompt, at_token),
            )
            if resp.status_code == 401:
                raise RuntimeError("Gemini rejected (401). Re-capture.")
            if resp.status_code == 429:
                raise RuntimeError("Gemini rate-limited (429).")
            resp.raise_for_status()
            text = _parse_stream_response(resp.text)

        approx_record_budget(prompt, text, budget, target_model)
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=[],
            stop_reason="end_turn",
            raw={"provider": "gemini-session", "model": target_model},
        )
