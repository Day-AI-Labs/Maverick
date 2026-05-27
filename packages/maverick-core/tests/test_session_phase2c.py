"""Phase 2c: Kimi/Grok/Gemini session adapters + tool simulator + new tools.

Mirrors the patterns in test_session_providers.py with adapter-specific
SSE formats and request shapes.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------- shared fakes ----------

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
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(self.status_code),
            )


class _MultiResponseFakeClient:
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

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append(("GET", url, headers or {}, None))
        return self._pop()

    def post(self, url, headers=None, json=None, data=None, timeout=None, params=None):
        self.calls.append(("POST", url, headers or {}, json or data))
        return self._pop()


def _stub_session(tmp_path, monkeypatch, provider: str, cookies: dict, extra: dict | None = None):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    blob = {"cookies": cookies}
    if extra:
        blob.update(extra)
    cookie_store.save_session(provider, blob)


# ---------- registry ----------

def test_phase2c_aliases():
    from maverick.session_providers import is_session_provider, KNOWN_SESSION_PROVIDERS
    for p in ("kimi-session", "grok-session", "gemini-session"):
        assert p in KNOWN_SESSION_PROVIDERS
    assert is_session_provider("kimi")
    assert is_session_provider("moonshot-session")
    assert is_session_provider("grok")
    assert is_session_provider("xai-session")
    assert is_session_provider("x-grok")
    assert is_session_provider("gemini")
    assert is_session_provider("google-session")
    assert is_session_provider("bard-session")


def test_phase2c_no_session_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import get_session_client
    for prov, name in [
        ("kimi-session", "Kimi"), ("grok-session", "Grok"),
        ("gemini-session", "Gemini"),
    ]:
        with pytest.raises(RuntimeError, match=f"No {name} session"):
            get_session_client(prov)


# ---------- Kimi ----------

def _kimi_sse(*deltas: str) -> str:
    import json
    return "\n".join(
        ["data: " + json.dumps({"event": "cmpl", "text": d}) for d in deltas]
        + ["data: [DONE]"]
    )


def test_kimi_session_sse_concat(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, "kimi-session", {"access_token": "jwt-x"})
    from maverick.session_providers.kimi_session import KimiSessionClient

    create = _FakeResponse(200, json_data={"id": "chat-123"})
    completion = _FakeResponse(200, text=_kimi_sse("Hi ", "there", "!"))
    fake = _MultiResponseFakeClient([create, completion])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = KimiSessionClient()
        resp = client.complete(system="", messages=[{"role": "user", "content": "hi"}])
    assert resp.text == "Hi there!"
    assert resp.tool_calls == []
    # First POST creates chat, second runs completion.
    assert "/api/chat" in fake.calls[0][1]
    assert "/api/chat/chat-123/completion/stream" in fake.calls[1][1]


def test_kimi_session_bearer_header(tmp_path, monkeypatch):
    """access_token cookie should also be sent as Authorization: Bearer."""
    _stub_session(tmp_path, monkeypatch, "kimi-session", {"access_token": "jwt-x"})
    from maverick.session_providers.kimi_session import KimiSessionClient

    create = _FakeResponse(200, json_data={"id": "c"})
    completion = _FakeResponse(200, text=_kimi_sse("ok"))
    fake = _MultiResponseFakeClient([create, completion])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = KimiSessionClient()
        client.complete(system="", messages=[{"role": "user", "content": "x"}])

    create_headers = fake.calls[0][2]
    assert create_headers.get("Authorization") == "Bearer jwt-x"


def test_kimi_session_rejects_tool_use(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, "kimi-session", {"access_token": "j"})
    from maverick.session_providers.kimi_session import KimiSessionClient
    with pytest.raises(NotImplementedError, match="tool-use"):
        KimiSessionClient().complete(
            system="", messages=[{"role": "user", "content": "x"}],
            tools=[{"name": "t", "input_schema": {}}],
        )


# ---------- Grok ----------

def _grok_ndjson(*messages: str) -> str:
    import json
    return "\n".join(
        json.dumps({"result": {"message": m}}) for m in messages
    )


def test_grok_session_ndjson_concat(tmp_path, monkeypatch):
    _stub_session(
        tmp_path, monkeypatch, "grok-session",
        {"auth_token": "a", "ct0": "csrf-x"},
    )
    from maverick.session_providers.grok_session import GrokSessionClient

    resp = _FakeResponse(200, text=_grok_ndjson("Hello, ", "world!"))
    fake = _MultiResponseFakeClient([resp])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = GrokSessionClient()
        out = client.complete(system="", messages=[{"role": "user", "content": "hi"}])
    assert out.text == "Hello, world!"


def test_grok_session_requires_ct0(tmp_path, monkeypatch):
    """Grok needs both auth_token AND ct0 for the CSRF header."""
    _stub_session(tmp_path, monkeypatch, "grok-session", {"auth_token": "a"})  # no ct0
    from maverick.session_providers.grok_session import GrokSessionClient
    client = GrokSessionClient()
    with pytest.raises(RuntimeError, match="ct0"):
        client.complete(system="", messages=[{"role": "user", "content": "x"}])


def test_grok_session_sends_csrf_header(tmp_path, monkeypatch):
    _stub_session(
        tmp_path, monkeypatch, "grok-session",
        {"auth_token": "a", "ct0": "the-csrf-token"},
    )
    from maverick.session_providers.grok_session import GrokSessionClient

    resp = _FakeResponse(200, text=_grok_ndjson("ok"))
    fake = _MultiResponseFakeClient([resp])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = GrokSessionClient()
        client.complete(system="", messages=[{"role": "user", "content": "x"}])

    headers = fake.calls[0][2]
    assert headers.get("x-csrf-token") == "the-csrf-token"


# ---------- Gemini ----------

def test_gemini_session_requires_psid(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, "gemini-session", {"SOMETHING": "x"})
    from maverick.session_providers.gemini_session import GeminiSessionClient
    client = GeminiSessionClient()
    with pytest.raises(RuntimeError, match="__Secure-1PSID"):
        client.complete(system="", messages=[{"role": "user", "content": "x"}])


def test_gemini_session_extracts_at_token(tmp_path, monkeypatch):
    """First call fetches the app HTML and extracts SNlM0e token."""
    _stub_session(
        tmp_path, monkeypatch, "gemini-session",
        {"__Secure-1PSID": "psid", "SAPISID": "sapi"},
    )
    from maverick.session_providers.gemini_session import GeminiSessionClient

    app_html = _FakeResponse(200, text='var x = {"SNlM0e":"AT_TOKEN_123"};')
    # Build the cumulative response in Gemini's nested format.
    # Outer: [[null, null, inner_json_string]]
    # Inner: [_, _, _, _, candidates] where candidates=[[uniq_id, [text]]]
    import json
    inner_payload = json.dumps(
        [None, None, None, None, [["uniq-1", ["the-answer"]]]]
    )
    outer = json.dumps([[None, None, inner_payload]])
    stream_body = ")]}'\n" + str(len(outer)) + "\n" + outer
    query_resp = _FakeResponse(200, text=stream_body)
    fake = _MultiResponseFakeClient([app_html, query_resp])

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = GeminiSessionClient()
        out = client.complete(system="", messages=[{"role": "user", "content": "x"}])
    # Token was extracted and used as 'at' form param.
    assert fake.calls[0][0] == "GET"
    assert "SNlM0e" in fake.calls[0][1] or fake.calls[1][3].get("at") == "AT_TOKEN_123"
    assert out.text == "the-answer"


def test_gemini_session_rejects_tool_use(tmp_path, monkeypatch):
    _stub_session(
        tmp_path, monkeypatch, "gemini-session",
        {"__Secure-1PSID": "p"},
    )
    from maverick.session_providers.gemini_session import GeminiSessionClient
    with pytest.raises(NotImplementedError, match="tool-use"):
        GeminiSessionClient().complete(
            system="", messages=[{"role": "user", "content": "x"}],
            tools=[{"name": "t", "input_schema": {}}],
        )


# ---------- tool simulator ----------

def test_simulator_passes_through_when_no_tools():
    """No tools -> wrapper is a pure pass-through."""
    from maverick.session_providers.tool_simulator import SimulatedToolCallClient
    from maverick.llm import LLMResponse

    class _Inner:
        DEFAULT_MODEL = "x"

        def complete(self, **kw):
            assert kw.get("tools") is None
            return LLMResponse(text="hi", thinking=None, tool_calls=[], stop_reason="end_turn")

    sim = SimulatedToolCallClient(_Inner())
    resp = sim.complete(system="s", messages=[], tools=None)
    assert resp.text == "hi"
    assert resp.tool_calls == []


def test_simulator_renders_tools_to_prompt():
    """With tools, the wrapper augments system prompt with markdown protocol."""
    from maverick.session_providers.tool_simulator import SimulatedToolCallClient
    from maverick.llm import LLMResponse

    captured_system: dict = {}

    class _Inner:
        DEFAULT_MODEL = "x"

        def complete(self, **kw):
            captured_system["s"] = kw["system"]
            return LLMResponse(text="ok", thinking=None, tool_calls=[], stop_reason="end_turn")

    sim = SimulatedToolCallClient(_Inner())
    sim.complete(
        system="base", messages=[],
        tools=[{"name": "calc", "description": "do math", "input_schema": {"properties": {"x": {"type": "int"}}}}],
    )
    # Augmented system contains the protocol + tool description.
    assert "## Tools available" in captured_system["s"]
    assert "calc" in captured_system["s"]
    assert "do math" in captured_system["s"]


def test_simulator_parses_named_tool_calls():
    """Model emits <tool name="calc">{"a":1}</tool> -> parsed into ToolCall."""
    from maverick.session_providers.tool_simulator import SimulatedToolCallClient
    from maverick.llm import LLMResponse

    class _Inner:
        DEFAULT_MODEL = "x"

        def complete(self, **kw):
            return LLMResponse(
                text='Let me calculate. <tool name="calc">{"a": 1, "b": 2}</tool> Done.',
                thinking=None, tool_calls=[], stop_reason="end_turn",
            )

    sim = SimulatedToolCallClient(_Inner())
    resp = sim.complete(
        system="", messages=[],
        tools=[{"name": "calc", "input_schema": {}}],
    )
    assert resp.stop_reason == "tool_use"
    assert len(resp.tool_calls) == 1
    call = resp.tool_calls[0]
    assert call.name == "calc"
    assert call.input == {"a": 1, "b": 2}
    # Text retained, just with the tool block removed.
    assert "calculate" in resp.text
    assert "<tool" not in resp.text


def test_simulator_parses_inline_tool_calls():
    """Older protocol: <tool>name({"a":1})</tool> also parsed."""
    from maverick.session_providers.tool_simulator import SimulatedToolCallClient
    from maverick.llm import LLMResponse

    class _Inner:
        DEFAULT_MODEL = "x"

        def complete(self, **kw):
            return LLMResponse(
                text='<tool>add({"x": 1, "y": 2})</tool>',
                thinking=None, tool_calls=[], stop_reason="end_turn",
            )

    sim = SimulatedToolCallClient(_Inner())
    resp = sim.complete(
        system="", messages=[], tools=[{"name": "add", "input_schema": {}}],
    )
    assert resp.stop_reason == "tool_use"
    assert resp.tool_calls[0].name == "add"
    assert resp.tool_calls[0].input == {"x": 1, "y": 2}


def test_simulator_handles_malformed_json():
    """Malformed tool args don't crash; the call is dropped."""
    from maverick.session_providers.tool_simulator import SimulatedToolCallClient
    from maverick.llm import LLMResponse

    class _Inner:
        DEFAULT_MODEL = "x"

        def complete(self, **kw):
            return LLMResponse(
                text='<tool name="x">{not valid json}</tool>',
                thinking=None, tool_calls=[], stop_reason="end_turn",
            )

    sim = SimulatedToolCallClient(_Inner())
    resp = sim.complete(
        system="", messages=[], tools=[{"name": "x", "input_schema": {}}],
    )
    # No valid tool calls extracted -> falls through to plain response.
    assert resp.tool_calls == []
    assert resp.stop_reason == "end_turn"


def test_simulator_auto_wraps_via_llm_facade(tmp_path, monkeypatch):
    """LLM('chatgpt-session:gpt-4o').complete(tools=[...]) must NOT raise
    NotImplementedError thanks to auto-wrapping in _get_client."""
    _stub_session(tmp_path, monkeypatch, "chatgpt-session",
                  {"__Secure-next-auth.session-token": "t"})
    from maverick.session_providers.tool_simulator import SimulatedToolCallClient
    from maverick.llm import LLM

    llm = LLM(model="chatgpt-session:gpt-4o")
    client = llm._get_client("chatgpt-session")
    assert isinstance(client, SimulatedToolCallClient)


# ---------- computer-use tool ----------

def test_computer_tool_kill_switch(monkeypatch):
    """MAVERICK_COMPUTER_DISABLE=1 disables the tool regardless of action."""
    monkeypatch.setenv("MAVERICK_COMPUTER_DISABLE", "1")
    from maverick.tools.computer import computer
    tool = computer()
    out = tool.fn({"action": "screenshot"})
    assert "disabled" in out.lower()


def test_computer_tool_schema_matches_anthropic_spec():
    """Schema must include all actions Claude's computer_20250124 emits."""
    from maverick.tools.computer import computer
    tool = computer()
    actions = tool.input_schema["properties"]["action"]["enum"]
    required = {
        "key", "type", "mouse_move", "left_click", "left_click_drag",
        "right_click", "middle_click", "double_click", "screenshot",
        "cursor_position", "scroll", "wait",
    }
    assert required.issubset(set(actions))


def test_computer_tool_rejects_unknown_action(monkeypatch):
    monkeypatch.setenv("MAVERICK_COMPUTER_DISABLE", "0")
    from maverick.tools.computer import _run_computer_action
    out = _run_computer_action({"action": "explode"})
    assert "unknown action" in out.lower()


# ---------- browser tool ----------

def test_browser_tool_kill_switch(monkeypatch):
    monkeypatch.setenv("MAVERICK_BROWSER_DISABLE", "1")
    from maverick.tools.browser import browser
    tool = browser()
    out = tool.fn({"action": "screenshot"})
    assert "disabled" in out.lower()


def test_browser_tool_rejects_unsafe_url(monkeypatch):
    """navigate must refuse non-http(s) URLs."""
    monkeypatch.setenv("MAVERICK_BROWSER_DISABLE", "0")
    # Mock the session so we don't actually try to start playwright.
    from maverick.tools import browser as browser_mod

    class _FakePage:
        url = "about:blank"

    class _FakeSession:
        @property
        def page(self):
            return _FakePage()

    monkeypatch.setattr(browser_mod, "_get_session", lambda: _FakeSession())
    out = browser_mod._run_browser_action({"action": "navigate", "url": "file:///etc/passwd"})
    assert "must start with http" in out.lower()


def test_browser_tool_schema_lists_all_actions():
    from maverick.tools.browser import browser
    tool = browser()
    actions = tool.input_schema["properties"]["action"]["enum"]
    required = {
        "navigate", "click", "type", "press", "scroll", "screenshot",
        "extract_text", "extract_html", "find_text", "wait_for",
        "go_back", "go_forward", "current_url", "list_links", "close",
    }
    assert required.issubset(set(actions))


# ---------- base_registry capabilities flags ----------

def test_base_registry_default_excludes_optional_tools():
    """Without flags, computer + browser aren't registered."""
    from maverick.tools import base_registry

    # Use cheap stand-ins; we never call the tools.
    class _FakeSandbox:
        pass

    class _FakeWorld:
        pass

    reg = base_registry(world=_FakeWorld(), sandbox=_FakeSandbox())
    names = {t.name for t in reg.all()}
    assert "computer" not in names
    assert "browser" not in names
    # Core tools still present.
    assert "shell" in names
    assert "read_file" in names


def test_base_registry_enables_computer_and_browser():
    from maverick.tools import base_registry

    class _FakeSandbox:
        pass

    class _FakeWorld:
        pass

    reg = base_registry(
        world=_FakeWorld(), sandbox=_FakeSandbox(),
        enable_computer_use=True, enable_browser=True,
    )
    names = {t.name for t in reg.all()}
    assert "computer" in names
    assert "browser" in names
