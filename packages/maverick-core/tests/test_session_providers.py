"""Session-provider unit tests.

Covers:
  - cookie_store round-trip + perms enforcement
  - registry dispatch + aliases
  - ChatGPTSessionClient request shape + SSE parsing (mocked httpx)
  - tool-use rejection (consumer chat doesn't support tools)
  - LLM facade routes chatgpt-session:* specs to the session client
"""
from __future__ import annotations

import os
import stat
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _enable_session_providers(monkeypatch):
    # The session-provider factory is gated off by default (ToS/ban risk);
    # these tests exercise it, so opt in for the whole module.
    monkeypatch.setenv("MAVERICK_ENABLE_SESSION_PROVIDERS", "1")


# ---------- cookie_store ----------

def test_cookie_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store

    blob = {"cookies": {"__Secure-next-auth.session-token": "abc123"}}
    path = cookie_store.save_session("chatgpt-session", blob)
    assert path.exists()
    # Mode 0600 enforced (POSIX only; NTFS reports 0o666 regardless of chmod).
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = cookie_store.load_session("chatgpt-session")
    assert loaded["cookies"]["__Secure-next-auth.session-token"] == "abc123"
    assert "saved_at" in loaded


def test_cookie_store_no_session_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    assert cookie_store.load_session("chatgpt-session") is None


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX file-mode perms aren't enforced on NTFS (load_session skips the check on Windows)",
)
def test_cookie_store_rejects_world_readable(tmp_path, monkeypatch):
    """Refuses to load a session file with relaxed perms (POSIX only)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store

    path = cookie_store.save_session("chatgpt-session", {"cookies": {"k": "v"}})
    os.chmod(path, 0o644)
    with pytest.raises(PermissionError, match="mode"):
        cookie_store.load_session("chatgpt-session")


def test_cookie_store_clear_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    cookie_store.save_session("chatgpt-session", {"cookies": {"a": "1"}})
    cookie_store.save_session("kimi-session", {"cookies": {"b": "2"}})
    assert sorted(cookie_store.list_sessions()) == ["chatgpt-session", "kimi-session"]
    assert cookie_store.clear_session("chatgpt-session") is True
    assert cookie_store.clear_session("chatgpt-session") is False
    assert cookie_store.list_sessions() == ["kimi-session"]


def test_cookie_store_atomic_write(tmp_path, monkeypatch):
    """No half-written temp file should remain after save."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    cookie_store.save_session("chatgpt-session", {"cookies": {"k": "v"}})
    leftovers = list(tmp_path.glob("**/*.tmp"))
    assert leftovers == [], f"temp files leaked: {leftovers}"


def test_cookie_store_rejects_path_traversal(tmp_path, monkeypatch):
    """Provider names with slashes / .. can't escape the session dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    # Should not write outside ~/.maverick/sessions/
    p = cookie_store.save_session("../../evil", {"cookies": {"k": "v"}})
    sessions_dir = tmp_path / ".maverick" / "sessions"
    assert sessions_dir in p.parents


# ---------- registry ----------

def test_is_session_provider():
    from maverick.session_providers import is_session_provider
    assert is_session_provider("chatgpt-session")
    assert is_session_provider("chatgpt")
    assert is_session_provider("openai-session")
    assert is_session_provider("CHATGPT-SESSION")  # case-insensitive
    assert is_session_provider("claude-session")
    assert is_session_provider("claude")
    assert is_session_provider("anthropic-session")
    assert is_session_provider("claude-ai")
    assert not is_session_provider("openai")  # BYOK, not session
    assert not is_session_provider("anthropic")
    assert not is_session_provider("")


def test_get_session_client_unknown_raises():
    from maverick.session_providers import get_session_client
    with pytest.raises(ValueError, match="Available"):
        get_session_client("not-a-real-session")


def test_get_session_client_requires_stored_session(tmp_path, monkeypatch):
    """No cookie file -> instantiation fails with actionable message."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import get_session_client
    with pytest.raises(RuntimeError, match="No ChatGPT session stored"):
        get_session_client("chatgpt-session")


# ---------- ChatGPTSessionClient ----------

class _FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            req = httpx.Request("GET", "http://x")
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=req,
                response=httpx.Response(self.status_code),
            )


class _FakeClient:
    """Drop-in for httpx.Client inside the adapter."""
    def __init__(self, *, auth_response=None, conv_response=None):
        self._auth = auth_response
        self._conv = conv_response
        self.calls: list[tuple[str, str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, headers or {}))
        return self._auth

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, headers or {}))
        self.last_post_body = json
        return self._conv


def _stub_session(tmp_path, monkeypatch, *, access_token=None):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    blob = {"cookies": {"__Secure-next-auth.session-token": "fake-cookie"}}
    if access_token:
        blob["access_token"] = access_token
    cookie_store.save_session("chatgpt-session", blob)


def _sse(*chunks: str) -> str:
    """Build an SSE response body from text chunks (each a cumulative reply)."""
    import json
    lines = []
    for chunk in chunks:
        event = {"message": {"content": {"parts": [chunk]}}}
        lines.append("data: " + json.dumps(event))
    lines.append("data: [DONE]")
    return "\n".join(lines)


def test_chatgpt_session_text_completion(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch)
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    auth_resp = _FakeResponse(200, json_data={"accessToken": "token-xyz"})
    conv_resp = _FakeResponse(200, text=_sse("Hi", "Hi there", "Hi there, friend!"))
    fake = _FakeClient(auth_response=auth_resp, conv_response=conv_resp)

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        resp = client.complete(
            system="be brief",
            messages=[{"role": "user", "content": "say hi"}],
        )

    assert resp.text == "Hi there, friend!"  # last cumulative chunk wins
    assert resp.tool_calls == []
    assert resp.stop_reason == "end_turn"


def test_chatgpt_session_uses_cached_access_token(tmp_path, monkeypatch):
    """If access_token is in the session blob, don't hit /api/auth/session."""
    _stub_session(tmp_path, monkeypatch, access_token="cached-token-9")
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    conv_resp = _FakeResponse(200, text=_sse("ok"))
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        client.complete(system="", messages=[{"role": "user", "content": "yo"}])

    # No GET to /api/auth/session.
    methods = [c[0] for c in fake.calls]
    assert methods == ["POST"]
    # POST carried the cached bearer.
    post_headers = fake.calls[0][2]
    assert post_headers["Authorization"] == "Bearer cached-token-9"


def test_chatgpt_session_rejects_tool_use(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient
    client = ChatGPTSessionClient()
    with pytest.raises(NotImplementedError, match="tool-use"):
        client.complete(
            system="", messages=[{"role": "user", "content": "x"}],
            tools=[{"name": "calc", "input_schema": {}}],
        )


def test_chatgpt_session_401_actionable_error(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch)
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    auth_resp = _FakeResponse(401)
    fake = _FakeClient(auth_response=auth_resp)
    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        with pytest.raises(RuntimeError, match="(expired|re-capture)"):
            client.complete(system="", messages=[{"role": "user", "content": "x"}])


def test_chatgpt_session_429_rate_limit(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    conv_resp = _FakeResponse(429)
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)
    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        with pytest.raises(RuntimeError, match="rate-limited"):
            client.complete(system="", messages=[{"role": "user", "content": "x"}])


def test_chatgpt_session_request_body_shape(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    conv_resp = _FakeResponse(200, text=_sse("ok"))
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)
    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        client.complete(
            system="sys", messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
        )

    body = fake.last_post_body
    assert body["action"] == "next"
    assert body["model"] == "gpt-4o-mini"
    assert len(body["messages"]) == 1
    msg = body["messages"][0]
    assert msg["author"]["role"] == "user"
    assert msg["content"]["content_type"] == "text"
    # Prompt flattening preserved system + user content.
    flat = msg["content"]["parts"][0]
    assert "[SYSTEM]" in flat
    assert "sys" in flat
    assert "hello" in flat




def test_chatgpt_session_budget_exceeded_propagates(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.budget import Budget, BudgetExceeded
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    conv_resp = _FakeResponse(200, text=_sse("hello there, friend"))
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)
    budget = Budget(max_input_tokens=1, max_output_tokens=1)

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        with pytest.raises(BudgetExceeded):
            client.complete(
                system="", messages=[{"role": "user", "content": "hi"}],
                budget=budget,
            )
def test_chatgpt_session_budget_recorded(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.budget import Budget
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    conv_resp = _FakeResponse(200, text=_sse("hello there, friend"))
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)
    budget = Budget(max_dollars=10.0)

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        client.complete(
            system="", messages=[{"role": "user", "content": "hi"}],
            budget=budget,
        )

    # Best-effort: output_tokens should be >0 (approximated from char count).
    assert budget.output_tokens > 0


# ---------- LLM facade integration ----------

def test_llm_facade_routes_chatgpt_session(tmp_path, monkeypatch):
    """LLM('chatgpt-session:gpt-4o').complete() must dispatch to the
    session client, not the regular openai client."""
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.llm import LLM

    llm = LLM(model="chatgpt-session:gpt-4o")
    conv_resp = _FakeResponse(200, text=_sse("routed!"))
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        resp = llm.complete(system="", messages=[{"role": "user", "content": "go"}])
    assert resp.text == "routed!"
    # The cached client is a SimulatedToolCallClient wrapping a
    # ChatGPTSessionClient -- the LLM facade auto-wraps session
    # providers so tool-using roles work transparently.
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient
    from maverick.session_providers.tool_simulator import SimulatedToolCallClient
    cached = llm._clients["chatgpt-session"]
    assert isinstance(cached, SimulatedToolCallClient)
    assert isinstance(cached._inner, ChatGPTSessionClient)


# ---------- ClaudeSessionClient ----------

class _MultiResponseFakeClient:
    """Multi-call fake: returns queued responses in order, records calls."""
    def __init__(self, responses: list):
        self._queue = list(responses)
        self.calls: list[tuple[str, str, dict, dict | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _pop(self):
        if not self._queue:
            raise AssertionError("Fake client out of queued responses")
        return self._queue.pop(0)

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, headers or {}, None))
        return self._pop()

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, headers or {}, json))
        return self._pop()


def _stub_claude_session(tmp_path, monkeypatch, *, org_id=None):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    blob = {"cookies": {"sessionKey": "sk-ant-sid01-fake"}}
    if org_id:
        blob["org_id"] = org_id
    cookie_store.save_session("claude-session", blob)


def _claude_sse(*deltas: str) -> str:
    """Build a Claude-style INCREMENTAL SSE body (concat, not overwrite)."""
    import json
    lines = []
    for d in deltas:
        lines.append("data: " + json.dumps({"completion": d}))
    lines.append("data: [DONE]")
    return "\n".join(lines)


def test_claude_session_dispatches(tmp_path, monkeypatch):
    """get_session_client('claude-session') -> ClaudeSessionClient."""
    _stub_claude_session(tmp_path, monkeypatch, org_id="org-1")
    from maverick.session_providers import get_session_client
    from maverick.session_providers.claude_session import ClaudeSessionClient
    client = get_session_client("claude-session")
    assert isinstance(client, ClaudeSessionClient)
    # Alias routes too.
    client2 = get_session_client("claude")
    assert isinstance(client2, ClaudeSessionClient)


def test_claude_session_requires_stored_session(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import get_session_client
    with pytest.raises(RuntimeError, match="No Claude session stored"):
        get_session_client("claude-session")


def test_claude_session_sse_concatenates_deltas(tmp_path, monkeypatch):
    """Claude streams INCREMENTAL deltas; final text is concatenation
    of all completion fragments, not the last one alone."""
    _stub_claude_session(tmp_path, monkeypatch, org_id="org-1")
    from maverick.session_providers.claude_session import ClaudeSessionClient

    conv_create = _FakeResponse(200, json_data={"uuid": "conv-uuid-1"})
    completion = _FakeResponse(
        200, text=_claude_sse("Hello", ", ", "world!"),
    )
    fake = _MultiResponseFakeClient([conv_create, completion])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ClaudeSessionClient()
        resp = client.complete(
            system="be brief",
            messages=[{"role": "user", "content": "say hi"}],
        )

    assert resp.text == "Hello, world!"  # concat, not last-only
    assert resp.tool_calls == []
    assert resp.stop_reason == "end_turn"


def test_claude_session_caches_org_id(tmp_path, monkeypatch):
    """If org_id is in the session blob, /api/organizations isn't hit."""
    _stub_claude_session(tmp_path, monkeypatch, org_id="cached-org")
    from maverick.session_providers.claude_session import ClaudeSessionClient

    conv_create = _FakeResponse(200, json_data={"uuid": "c-1"})
    completion = _FakeResponse(200, text=_claude_sse("ok"))
    fake = _MultiResponseFakeClient([conv_create, completion])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ClaudeSessionClient()
        client.complete(system="", messages=[{"role": "user", "content": "yo"}])

    methods = [c[0] for c in fake.calls]
    # Only 2 POSTs (create + completion); no GET to /api/organizations.
    assert methods == ["POST", "POST"]


def test_claude_session_resolves_org_id_on_first_call(tmp_path, monkeypatch):
    """No cached org_id -> fetch from /api/organizations."""
    _stub_claude_session(tmp_path, monkeypatch)
    from maverick.session_providers.claude_session import ClaudeSessionClient

    orgs_resp = _FakeResponse(200, json_data=[
        {"uuid": "discovered-org", "capabilities": ["chat"]},
    ])
    conv_create = _FakeResponse(200, json_data={"uuid": "c-1"})
    completion = _FakeResponse(200, text=_claude_sse("ok"))
    fake = _MultiResponseFakeClient([orgs_resp, conv_create, completion])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ClaudeSessionClient()
        client.complete(system="", messages=[{"role": "user", "content": "y"}])

    # First call must be GET /api/organizations.
    assert fake.calls[0][0] == "GET"
    assert "/api/organizations" in fake.calls[0][1]
    # Conversation create POST hit the discovered org.
    assert "/api/organizations/discovered-org/chat_conversations" in fake.calls[1][1]


def test_claude_session_rejects_tool_use(tmp_path, monkeypatch):
    _stub_claude_session(tmp_path, monkeypatch, org_id="o")
    from maverick.session_providers.claude_session import ClaudeSessionClient
    client = ClaudeSessionClient()
    with pytest.raises(NotImplementedError, match="tool-use"):
        client.complete(
            system="", messages=[{"role": "user", "content": "x"}],
            tools=[{"name": "calc", "input_schema": {}}],
        )


def test_claude_session_401_actionable_error(tmp_path, monkeypatch):
    _stub_claude_session(tmp_path, monkeypatch)
    from maverick.session_providers.claude_session import ClaudeSessionClient

    orgs_resp = _FakeResponse(401)
    fake = _MultiResponseFakeClient([orgs_resp])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ClaudeSessionClient()
        with pytest.raises(RuntimeError, match="(expired|re-capture)"):
            client.complete(system="", messages=[{"role": "user", "content": "x"}])


def test_claude_session_429_rate_limit(tmp_path, monkeypatch):
    _stub_claude_session(tmp_path, monkeypatch, org_id="o")
    from maverick.session_providers.claude_session import ClaudeSessionClient

    conv_create = _FakeResponse(200, json_data={"uuid": "c"})
    completion = _FakeResponse(429)
    fake = _MultiResponseFakeClient([conv_create, completion])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ClaudeSessionClient()
        with pytest.raises(RuntimeError, match="rate-limited"):
            client.complete(system="", messages=[{"role": "user", "content": "x"}])


def test_claude_session_request_body_shape(tmp_path, monkeypatch):
    """Completion POST sends prompt + model in the body claude.ai expects."""
    _stub_claude_session(tmp_path, monkeypatch, org_id="o")
    from maverick.session_providers.claude_session import ClaudeSessionClient

    conv_create = _FakeResponse(200, json_data={"uuid": "conv-x"})
    completion = _FakeResponse(200, text=_claude_sse("ok"))
    fake = _MultiResponseFakeClient([conv_create, completion])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ClaudeSessionClient()
        client.complete(
            system="sys", messages=[{"role": "user", "content": "hello"}],
            model="claude-haiku-4-5",
        )

    # Last POST is the completion call.
    completion_call = fake.calls[-1]
    assert completion_call[0] == "POST"
    assert "/completion" in completion_call[1]
    body = completion_call[3]
    assert body["model"] == "claude-haiku-4-5"
    assert "[SYSTEM]" in body["prompt"]
    assert "hello" in body["prompt"]
    assert body.get("rendering_mode") == "messages"


def test_llm_facade_routes_claude_session(tmp_path, monkeypatch):
    _stub_claude_session(tmp_path, monkeypatch, org_id="o")
    from maverick.llm import LLM

    llm = LLM(model="claude-session:claude-sonnet-4-6")
    conv_create = _FakeResponse(200, json_data={"uuid": "c"})
    completion = _FakeResponse(200, text=_claude_sse("routed-to-claude"))
    fake = _MultiResponseFakeClient([conv_create, completion])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        resp = llm.complete(system="", messages=[{"role": "user", "content": "go"}])
    assert resp.text == "routed-to-claude"
    from maverick.session_providers.claude_session import ClaudeSessionClient
    from maverick.session_providers.tool_simulator import SimulatedToolCallClient
    cached = llm._clients["claude-session"]
    assert isinstance(cached, SimulatedToolCallClient)
    assert isinstance(cached._inner, ClaudeSessionClient)


def test_tool_use_unsupported_helper_is_typed_and_actionable():
    from maverick.session_providers.base import (
        SessionToolUseUnsupported,
        tool_use_unsupported,
    )
    err = tool_use_unsupported("Grok", "XAI_API_KEY")
    # Typed so callers can detect the capability gap, but still a
    # NotImplementedError so any existing handler keeps catching it.
    assert isinstance(err, SessionToolUseUnsupported)
    assert isinstance(err, NotImplementedError)
    msg = str(err)
    assert "Grok" in msg and "XAI_API_KEY" in msg and "tool-use" in msg


def test_chatgpt_session_raises_typed_capability_error(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.session_providers.base import SessionToolUseUnsupported
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient
    client = ChatGPTSessionClient()
    # Tighter than the legacy NotImplementedError check: the de-scope now
    # raises the typed subclass on the (unwrapped) tool-use path.
    with pytest.raises(SessionToolUseUnsupported):
        client.complete(
            system="", messages=[{"role": "user", "content": "x"}],
            tools=[{"name": "calc", "input_schema": {}}],
        )
