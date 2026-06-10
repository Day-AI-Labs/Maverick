"""Cross-language LSP bridge (roadmap: 2027 H1 capabilities).

Code intelligence beyond Python without writing N parsers: speak the Language
Server Protocol to operator-configured or built-in language-server binaries (pyright, gopls,
rust-analyzer, typescript-language-server, ...) and expose the queries an
agent actually uses — symbols, definition, references, hover, diagnostics.

Lifecycle is one-shot per call: spawn the server, ``initialize``, ``didOpen``
the file, run the single query, ``shutdown``/``exit``, kill on timeout. That
keeps the tool run-to-completion (no daemon to leak) at the cost of server
startup per call — the right trade for an agent that asks a handful of
questions per run.

Process model: like ``host_exec`` (see ``tools/__init__``), the server binary
is **host-bound by nature** — language servers live on the host PATH, and the
conversation is bidirectional stdio, which ``sandbox.exec``'s run-to-completion
contract can't carry. So this module spawns only built-in or operator-configured
language-server argv lists directly (never a shell), with the secret-scrubbed
child env, a hard wall-clock deadline, and a guaranteed kill in ``finally``.
Model-controlled per-call executable overrides are intentionally not supported.

ops:
  - symbols(file[, language])                  — document symbols (name/kind/line)
  - definition(file, line, character)          — where the symbol is defined
  - references(file, line, character)          — places the symbol is used
  - hover(file, line, character)               — type/doc info at a position
  - diagnostics(file)                          — server-reported errors/warnings
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from . import Tool, scrub_child_env

# Default servers per language; operators may override via [lsp.servers] {lang = [argv...]}.
# Per-call executable overrides are intentionally forbidden: tool arguments are
# model-controlled, while these argv lists execute on the host.
DEFAULT_SERVERS: dict[str, list[str]] = {
    "python":     ["pyright-langserver", "--stdio"],
    "go":         ["gopls"],
    "rust":       ["rust-analyzer"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "c":          ["clangd"],
    "cpp":        ["clangd"],
}

_EXT_LANG = {
    ".py": "python", ".go": "go", ".rs": "rust",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
}

_SYMBOL_KINDS = {
    1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class",
    6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum",
    11: "interface", 12: "function", 13: "variable", 14: "constant",
    15: "string", 16: "number", 17: "boolean", 18: "array", 19: "object",
    20: "key", 21: "null", 22: "enum-member", 23: "struct", 24: "event",
    25: "operator", 26: "type-parameter",
}
_SEVERITIES = {1: "error", 2: "warning", 3: "info", 4: "hint"}

_TIMEOUT_S = 30.0


class _LspSession:
    """Minimal LSP-over-stdio client for one query lifecycle."""

    def __init__(self, argv: list[str], root: Path, deadline_s: float = _TIMEOUT_S):
        import subprocess
        self._deadline = time.monotonic() + deadline_s
        # Host-bound by nature (see module docstring): argv list, no shell,
        # scrubbed env, killed in close().
        self._proc = subprocess.Popen(  # noqa: S603 -- argv list, never a shell
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=scrub_child_env(),
            cwd=str(root),
        )
        self._next_id = 0
        self._buf = b""
        self.notifications: list[dict] = []

    # -- framing ----------------------------------------------------------

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        frame = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        assert self._proc.stdin is not None
        self._proc.stdin.write(frame)
        self._proc.stdin.flush()

    def _read_chunk(self) -> bytes | None:
        """Read available bytes, never blocking past the session deadline.

        ``read1`` alone would block indefinitely on a hung-but-alive server,
        sailing straight past the deadline — so gate each read on ``select``
        with the remaining time (POSIX pipes; CI and supported hosts are
        POSIX — on platforms without selectable pipes this degrades to a
        blocking read).
        """
        assert self._proc.stdout is not None
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("LSP server did not answer within the deadline")
        try:
            import select
            ready, _, _ = select.select([self._proc.stdout], [], [], remaining)
        except (OSError, ValueError):  # non-selectable handle (e.g. Windows)
            ready = [self._proc.stdout]  # degrade to a blocking read
        if not ready:
            # NB: TimeoutError subclasses OSError, so this raise must live
            # OUTSIDE the except clause above or it would swallow itself.
            raise TimeoutError("LSP server did not answer within the deadline")
        return self._proc.stdout.read1(65536)  # type: ignore[attr-defined]

    def _read_message(self) -> dict | None:
        """Read one framed message, honoring the session deadline."""
        while True:
            header_end = self._buf.find(b"\r\n\r\n")
            if header_end == -1:
                chunk = self._read_chunk()
                if not chunk:
                    return None
                self._buf += chunk
                continue
            headers = self._buf[:header_end].decode("ascii", "replace")
            length = 0
            for line in headers.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1].strip())
            start = header_end + 4
            while len(self._buf) < start + length:
                chunk = self._read_chunk()
                if not chunk:
                    return None
                self._buf += chunk
            body = self._buf[start:start + length]
            self._buf = self._buf[start + length:]
            try:
                return json.loads(body)
            except ValueError:
                continue  # tolerate a garbled frame

    # -- rpc ------------------------------------------------------------

    def request(self, method: str, params: dict) -> Any:
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            msg = self._read_message()
            if msg is None:
                raise ConnectionError("LSP server closed the stream")
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(f"LSP error: {msg['error'].get('message', msg['error'])}")
                return msg.get("result")
            if "method" in msg and "id" not in msg:
                self.notifications.append(msg)
            # Server-initiated requests (registerCapability etc.): answer null.
            elif "method" in msg and "id" in msg:
                self._send({"jsonrpc": "2.0", "id": msg["id"], "result": None})

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def wait_notification(self, method: str) -> dict | None:
        for n in self.notifications:
            if n.get("method") == method:
                return n
        while True:
            msg = self._read_message()
            if msg is None:
                return None
            if msg.get("method") == method:
                return msg
            if "method" in msg and "id" not in msg:
                self.notifications.append(msg)

    def close(self) -> None:
        try:
            self.notify("exit", {})
        except Exception:
            pass
        try:
            self._proc.kill()
        except Exception:
            pass


def _server_for(language: str) -> list[str] | str:
    try:
        from ..config import load_config
        cfg = ((load_config() or {}).get("lsp") or {}).get("servers") or {}
        argv = cfg.get(language)
        if isinstance(argv, list) and argv:
            argv = [str(a) for a in argv]
        else:
            argv = DEFAULT_SERVERS.get(language)
    except Exception:
        argv = DEFAULT_SERVERS.get(language)
    if not argv:
        return (f"ERROR: no LSP server known for language {language!r} "
                f"(configure [lsp.servers] {language} = [\"<server>\", ...])")
    if shutil.which(argv[0]) is None:
        return (f"ERROR: LSP server {argv[0]!r} is not installed on the host "
                f"(install it, or configure [lsp.servers] {language})")
    return argv


def _workspace_root() -> Path:
    root = os.environ.get("MAVERICK_WORKSPACE_ROOT") or os.getcwd()
    return Path(root).resolve()


def _resolve_workspace_path(raw: Any, workspace: Path, *, label: str) -> Path | str:
    if raw is None or str(raw) == "":
        return f"ERROR: {label} is required"
    path = Path(str(raw))
    candidate = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError:
        return f"ERROR: {label} escapes the workspace: {path}"
    return candidate


def _uri(path: Path) -> str:
    return path.resolve().as_uri()


def _pos_params(path: Path, line: int, character: int) -> dict:
    return {
        "textDocument": {"uri": _uri(path)},
        "position": {"line": int(line), "character": int(character)},
    }


def _fmt_location(loc: dict) -> str:
    uri = loc.get("uri") or loc.get("targetUri") or ""
    rng = loc.get("range") or loc.get("targetRange") or {}
    start = rng.get("start") or {}
    path = uri[len("file://"):] if uri.startswith("file://") else uri
    return f"{path}:{start.get('line', 0) + 1}:{start.get('character', 0) + 1}"


def _run_query(args: dict[str, Any]) -> str:  # noqa: C901 -- one dispatch table
    op = args.get("op")
    if "server" in args:
        return "ERROR: per-call LSP server argv overrides are not allowed; configure [lsp.servers] instead"
    file_arg = args.get("file")
    workspace = _workspace_root()
    path = _resolve_workspace_path(file_arg, workspace, label="file")
    if isinstance(path, str):
        return path
    if not path.exists():
        return f"ERROR: no such file: {path}"

    language = str(args.get("language") or _EXT_LANG.get(path.suffix, "")).lower()
    if not language:
        return f"ERROR: cannot infer language from {path.suffix!r}; pass 'language'"
    argv = _server_for(language)
    if isinstance(argv, str):
        return argv

    root_arg = args.get("root") or path.parent
    root = _resolve_workspace_path(root_arg, workspace, label="root")
    if isinstance(root, str):
        return root
    if not root.is_dir():
        return f"ERROR: root is not a directory: {root}"
    timeout = float(args.get("timeout_s") or _TIMEOUT_S)

    session = _LspSession(argv, root, deadline_s=timeout)
    try:
        session.request("initialize", {
            "processId": os.getpid(),
            "rootUri": _uri(root),
            "capabilities": {},
        })
        session.notify("initialized", {})
        text = path.read_text(encoding="utf-8", errors="replace")
        session.notify("textDocument/didOpen", {
            "textDocument": {
                "uri": _uri(path), "languageId": language,
                "version": 1, "text": text,
            },
        })

        if op == "symbols":
            result = session.request("textDocument/documentSymbol",
                                     {"textDocument": {"uri": _uri(path)}}) or []
            lines = []
            def _walk(symbols, depth=0):
                for s in symbols:
                    kind = _SYMBOL_KINDS.get(s.get("kind", 0), "?")
                    rng = (s.get("selectionRange") or s.get("range")
                           or (s.get("location") or {}).get("range") or {})
                    line0 = ((rng.get("start") or {}).get("line", 0)) + 1
                    lines.append(f"{'  ' * depth}{kind} {s.get('name', '?')}  :{line0}")
                    _walk(s.get("children") or [], depth + 1)
            _walk(result)
            return "\n".join(lines) if lines else "(no symbols)"

        if op in ("definition", "references", "hover"):
            if "line" not in args or "character" not in args:
                return f"ERROR: {op} needs 'line' and 'character' (0-based)"
            params = _pos_params(path, args["line"], args["character"])
            if op == "definition":
                result = session.request("textDocument/definition", params)
                locs = result if isinstance(result, list) else [result] if result else []
                return "\n".join(_fmt_location(loc) for loc in locs) or "(no definition)"
            if op == "references":
                params["context"] = {"includeDeclaration": False}
                result = session.request("textDocument/references", params) or []
                return "\n".join(_fmt_location(loc) for loc in result) or "(no references)"
            result = session.request("textDocument/hover", params)
            contents = (result or {}).get("contents")
            if isinstance(contents, dict):
                return str(contents.get("value") or "(no hover info)")
            if isinstance(contents, list):
                return "\n".join(
                    c.get("value", str(c)) if isinstance(c, dict) else str(c)
                    for c in contents) or "(no hover info)"
            return str(contents or "(no hover info)")

        if op == "diagnostics":
            note = session.wait_notification("textDocument/publishDiagnostics")
            diags = ((note or {}).get("params") or {}).get("diagnostics") or []
            if not diags:
                return "(no diagnostics)"
            out = []
            for d in diags:
                sev = _SEVERITIES.get(d.get("severity", 3), "info")
                start = (d.get("range") or {}).get("start") or {}
                out.append(f"{sev} :{start.get('line', 0) + 1}:{start.get('character', 0) + 1} "
                           f"{d.get('message', '')}")
            return "\n".join(out)

        return f"ERROR: unknown op {op!r}"
    except (TimeoutError, ConnectionError, RuntimeError, OSError) as e:
        return f"ERROR: {e}"
    finally:
        try:
            session.request("shutdown", {})
        except Exception:
            pass
        session.close()


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {"type": "string",
               "enum": ["symbols", "definition", "references", "hover", "diagnostics"]},
        "file": {"type": "string", "description": "path to the source file"},
        "language": {"type": "string", "description": "override language detection"},
        "root": {"type": "string", "description": "workspace root (default: file's dir)"},
        "line": {"type": "integer", "description": "0-based line (definition/references/hover)"},
        "character": {"type": "integer", "description": "0-based column"},
        "timeout_s": {"type": "number", "description": "session deadline (default 30)"},
    },
    "required": ["op", "file"],
}


def lsp_bridge() -> Tool:
    return Tool(
        name="lsp_bridge",
        description=(
            "Cross-language code intelligence via the Language Server Protocol. "
            "ops: symbols / definition / references / hover (need line+character, "
            "0-based) / diagnostics, against built-in or operator-configured "
            "language servers (pyright, gopls, rust-analyzer, tsserver, clangd; "
            "override via [lsp.servers]). One-shot session per call."
        ),
        input_schema=_SCHEMA,
        fn=_run_query,
    )
