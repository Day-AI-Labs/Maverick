"""Crash-robustness for parsers that consume untrusted structured input.

Session-provider stream parsers read bytes from an untrusted upstream
(x.com / gemini.google.com), and the MCP client reads JSON-RPC from a
server that may be hostile or buggy. A malformed-but-valid-JSON message --
the right keys with the wrong *types* -- used to reach an unguarded
``.get()`` and raise ``AttributeError``, crashing the response parse
(session) or killing the read loop and failing every in-flight call (MCP).

These tests fuzz each parser with type-confused / truncated / deeply
wrong shapes and assert it degrades gracefully (no unexpected exception)
rather than crashing.
"""
from __future__ import annotations

import pytest
from maverick.mcp_client import MCPClient, _format_rpc_error
from maverick.session_providers.gemini_session import _parse_stream_response
from maverick.session_providers.grok_session import _parse_sse_response

# Shapes a hostile/buggy upstream can emit: the expected key with a wrong-typed
# value, a non-object top level, truncated/garbage, and nested type confusion.
_HOSTILE_JSON_LINES = [
    '{"result": "not-a-dict"}',
    '{"result": [1, 2, 3]}',
    '{"result": null}',
    '{"result": 12345}',
    '{"result": {"message": null}}',
    '{"result": {"message": ["x"]}}',
    '{"error": "string-not-object"}',
    '[1, 2, 3]',
    '"just a string"',
    "42",
    "true",
    "null",
    "{}",
    '{"unexpected": {"deeply": {"nested": [null, {}]}}}',
]


@pytest.mark.parametrize("line", _HOSTILE_JSON_LINES)
def test_grok_stream_parser_never_crashes(line):
    out = _parse_sse_response(line)
    assert isinstance(out, str)
    # SSE "data:" framing must not change that.
    assert isinstance(_parse_sse_response(f"data: {line}"), str)


@pytest.mark.parametrize("line", _HOSTILE_JSON_LINES)
def test_gemini_stream_parser_never_crashes(line):
    assert isinstance(_parse_stream_response(line), str)
    # Gemini strips a leading ")]}'" XSSI guard; feed that path too.
    assert isinstance(_parse_stream_response(")]}'\n" + line), str)


def test_grok_parser_still_extracts_well_formed_text():
    # The hardening must not break the happy path.
    good = '{"result": {"message": "hello "}}\n{"result": {"message": "world"}}'
    assert _parse_sse_response(good) == "hello world"


def test_grok_parser_handles_multiline_garbage_mix():
    mixed = "\n".join(
        ['garbage', '{"result": "bad"}', '{"result": {"message": "ok"}}', "[DONE]"]
    )
    assert _parse_sse_response(mixed) == "ok"


# --- MCP client: a hostile server can send a malformed JSON-RPC `error` ------
def _client_stub() -> MCPClient:
    c = MCPClient.__new__(MCPClient)  # skip __init__/subprocess; _dispatch only
    c._pending = {}                   # needs _pending + spec.name
    c.spec = type("S", (), {"name": "evil"})()
    return c


@pytest.mark.parametrize(
    "msg",
    [
        {"id": None, "error": "hostile-string"},     # id:null broadcast path
        {"id": None, "error": [1, 2]},
        {"id": None, "error": None},
        {"id": None, "error": 500},
        {"id": None, "error": {"code": -1, "message": "real"}},
    ],
)
def test_mcp_dispatch_survives_malformed_error(msg):
    # Must not raise (previously AttributeError killed the read loop).
    _client_stub()._dispatch(msg)


def test_format_rpc_error_is_total():
    assert _format_rpc_error({"code": -1, "message": "m"}) == "-1: m"
    assert _format_rpc_error("oops") == "'oops'"
    assert _format_rpc_error(None) == "None"
    assert _format_rpc_error([1, 2]) == "[1, 2]"


def test_mcp_dispatch_unknown_id_is_dropped_not_crashed():
    # A reply for an id we don't track must be ignored, not crash.
    _client_stub()._dispatch({"id": 9999, "result": {"ok": True}})
    _client_stub()._dispatch({"id": 9999, "error": "whatever"})
