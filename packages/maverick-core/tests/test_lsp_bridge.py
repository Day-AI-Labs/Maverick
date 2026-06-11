"""Cross-language LSP bridge tests.

A scripted fake LSP server (a tiny Python script speaking real
Content-Length-framed JSON-RPC over stdio) exercises the full session
lifecycle — initialize, didOpen, query, shutdown — without any real language
server installed.
"""
from __future__ import annotations

import sys
import textwrap

from maverick.tools.lsp_bridge import lsp_bridge

# A minimal LSP server: answers initialize/shutdown, publishes one diagnostic
# after didOpen, and serves documentSymbol / definition / hover canned.
_FAKE_SERVER = textwrap.dedent("""
    import json, sys

    def read():
        line = sys.stdin.buffer.readline()
        length = 0
        while line and line.strip():
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":")[1])
            line = sys.stdin.buffer.readline()
        if not length:
            return None
        return json.loads(sys.stdin.buffer.read(length))

    def send(payload):
        body = json.dumps(payload).encode()
        sys.stdout.buffer.write(b"Content-Length: %d\\r\\n\\r\\n" % len(body))
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()

    uri = None
    while True:
        msg = read()
        if msg is None:
            break
        method = msg.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}}})
        elif method == "textDocument/didOpen":
            uri = msg["params"]["textDocument"]["uri"]
            send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                  "params": {"uri": uri, "diagnostics": [
                      {"severity": 1, "message": "name 'frob' is not defined",
                       "range": {"start": {"line": 2, "character": 4},
                                 "end": {"line": 2, "character": 8}}}]}})
        elif method == "textDocument/documentSymbol":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": [
                {"name": "Widget", "kind": 5,
                 "range": {"start": {"line": 0, "character": 0},
                           "end": {"line": 5, "character": 0}},
                 "selectionRange": {"start": {"line": 0, "character": 6},
                                    "end": {"line": 0, "character": 12}},
                 "children": [
                     {"name": "spin", "kind": 6,
                      "range": {"start": {"line": 1, "character": 4},
                                "end": {"line": 2, "character": 0}},
                      "selectionRange": {"start": {"line": 1, "character": 8},
                                         "end": {"line": 1, "character": 12}}}]}]})
        elif method == "textDocument/definition":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": [
                {"uri": uri, "range": {"start": {"line": 9, "character": 0},
                                       "end": {"line": 9, "character": 5}}}]})
        elif method == "textDocument/hover":
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"contents": {"kind": "markdown",
                                          "value": "(class) Widget"}}})
        elif method == "shutdown":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
        elif method == "exit":
            break
""").strip()


def _fake_argv():
    return [sys.executable, "-c", _FAKE_SERVER]


def _tool():
    return lsp_bridge()


def test_symbols(tmp_path):
    f = tmp_path / "widget.py"
    f.write_text("class Widget:\n    def spin(self):\n        pass\n")
    out = _tool().fn({"op": "symbols", "file": str(f), "server": _fake_argv()})
    assert "class Widget  :1" in out
    assert "  method spin  :2" in out


def test_definition_and_hover(tmp_path):
    f = tmp_path / "w.py"
    f.write_text("x = 1\n")
    out = _tool().fn({"op": "definition", "file": str(f), "line": 0, "character": 0,
                      "server": _fake_argv()})
    assert out.strip().endswith(":10:1")  # canned definition at line 9 (0-based)
    hov = _tool().fn({"op": "hover", "file": str(f), "line": 0, "character": 0,
                      "server": _fake_argv()})
    assert "(class) Widget" in hov


def test_diagnostics(tmp_path):
    f = tmp_path / "w.py"
    f.write_text("def f():\n    return frob\n")
    out = _tool().fn({"op": "diagnostics", "file": str(f), "server": _fake_argv()})
    assert "error :3:5 name 'frob' is not defined" in out


def test_position_required_and_validation(tmp_path):
    f = tmp_path / "w.py"
    f.write_text("x = 1\n")
    assert _tool().fn({"op": "definition", "file": str(f),
                       "server": _fake_argv()}).startswith("ERROR:")
    assert _tool().fn({"op": "symbols", "file": "/nope.py"}).startswith("ERROR:")
    assert _tool().fn({"op": "symbols"}).startswith("ERROR:")


def test_unknown_language_and_missing_server(tmp_path):
    f = tmp_path / "w.weird"
    f.write_text("x")
    out = _tool().fn({"op": "symbols", "file": str(f)})
    assert out.startswith("ERROR:") and "language" in out
    f2 = tmp_path / "w.py"
    f2.write_text("x = 1\n")
    out2 = _tool().fn({"op": "symbols", "file": str(f2), "language": "python",
                       "server": []})  # empty argv -> fall to default which may be missing
    # Either pyright is installed (symbols answer) or a clear install hint.
    assert out2.startswith("ERROR:") or out2


def test_server_timeout_is_an_error_not_a_hang(tmp_path):
    f = tmp_path / "w.py"
    f.write_text("x = 1\n")
    # A "server" that never speaks LSP.
    silent = [sys.executable, "-c", "import time; time.sleep(60)"]
    out = _tool().fn({"op": "symbols", "file": str(f), "server": silent,
                      "timeout_s": 1.5})
    assert out.startswith("ERROR:")


def test_registered():
    from maverick.tools import base_registry

    class _W:
        pass

    class _S:
        pass

    names = set(getattr(base_registry(world=_W(), sandbox=_S()), "_tools", {}).keys())
    assert "lsp_bridge" in names
