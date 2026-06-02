"""The stdio JSON-RPC server must not crash on malformed `params`.

A client (which the server treats as untrusted) can send `params` as a
non-object -- a list, string, or number. Handlers call ``params.get(...)``,
so an unguarded value raised ``AttributeError``, surfaced as a scrubbed
-32603 "internal error". The server now coerces a non-dict `params` to
``{}`` so the handler returns the correct -32602 "invalid params" instead,
and never crashes the read loop.
"""
from __future__ import annotations

import io
import json
import sys

from maverick_mcp.server import MCPServer


def _run_lines(monkeypatch, *lines: str) -> list[dict]:
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(line + "\n" for line in lines)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    MCPServer().run()  # loops until stdin EOF, then returns
    return [json.loads(s) for s in out.getvalue().splitlines() if s.strip()]


def test_non_dict_params_is_invalid_params_not_crash(monkeypatch):
    req = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": ["hostile", "list"]}
    )
    msgs = _run_lines(monkeypatch, req)
    assert msgs, "server produced no response"
    resp = msgs[-1]
    assert resp.get("id") == 1
    assert "error" in resp, f"expected a JSON-RPC error, got {resp}"
    # Coerced params -> handler reports invalid params, not a scrubbed internal error.
    assert resp["error"]["code"] == -32602


def test_various_non_dict_params_never_crash(monkeypatch):
    for bad in ("[1,2]", '"str"', "42", "true", "null"):
        req = f'{{"jsonrpc":"2.0","id":7,"method":"tools/list","params":{bad}}}'
        msgs = _run_lines(monkeypatch, req)
        # tools/list ignores params, so this should succeed (result), never crash.
        assert msgs and msgs[-1].get("id") == 7
        assert "result" in msgs[-1] or "error" in msgs[-1]
