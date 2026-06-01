"""MCP client: let Maverick consume external MCP servers as tools.

v0.1.6 hardening (council review):
  - Env passed to the child process is now an EXPLICIT allowlist, not
    full ``os.environ``. Compromised npm MCP servers no longer exfil
    ANTHROPIC_API_KEY / MAVERICK_DASHBOARD_TOKEN / GITHUB_TOKEN / AWS_*.
  - stderr is drained by a background task so the pipe buffer never fills
    (was deadlocking the server after sustained logging).
  - returncode is checked before sending each request; we fail loudly
    instead of hanging on a dead pipe.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 30.0

# Env vars that we'll pass through to MCP server subprocesses by default.
# Everything else (API keys, dashboard tokens, AWS creds, etc.) stays
# in the parent process unless the spec explicitly opts a key in via
# its own [mcp_servers.<name>] env table.
DEFAULT_ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TZ", "TMPDIR", "TEMP", "TMP",
    "NODE_PATH", "NVM_DIR", "NPM_CONFIG_PREFIX",
    "SHELL", "PWD",
)


class MCPClientError(Exception):
    pass


@dataclass
class MCPServerSpec:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    inherit_env: bool = False  # opt-in to full os.environ inheritance
    # SHA-256 of the executable / NPM package SHASUM / image digest the
    # operator expects. When set, MCPClient.start() refuses to spawn if
    # the actual command resolves to a different hash. Defends the
    # supply-chain attack class shipped to STDIO MCP in April 2026
    # (CVE-2026-30615 et al). Default None = no pin (legacy behavior).
    pin_sha256: str | None = None

    @classmethod
    def from_config(cls, name: str, cfg: dict) -> MCPServerSpec:
        spec = cls(
            name=name,
            command=cfg["command"],
            args=list(cfg.get("args", [])),
            env={k: str(v) for k, v in (cfg.get("env", {}) or {}).items()},
            inherit_env=bool(cfg.get("inherit_env", False)),
            pin_sha256=cfg.get("pin_sha256"),
        )
        _validate_subprocess_inputs(spec)
        return spec

    def __post_init__(self):
        # Allow direct construction (tests / programmatic use) but still
        # apply the input validation. The dataclass default args don't
        # call from_config so we hook __post_init__.
        _validate_subprocess_inputs(self)


_DENY_CHARS = ("\n", "\r", "\0")
_DENY_SHELL_METAS = (";", "|", "&", "$(", "`", ">", "<")


def _validate_subprocess_inputs(spec: MCPServerSpec) -> None:
    """Defend against the CVE-2026-30615 STDIO Trifecta and friends.

    Hostile MCP server listings embedded newlines / shell metas in
    `command` or `args`, causing client launchers to spawn unintended
    processes (200k vulnerable clients across Cursor, VS Code, Windsurf,
    Claude Code, LangChain, LangFlow, LiteLLM, Flowise per April 2026
    OX Security advisory).

    Rules:
      - command must be a simple program name or absolute path; no
        shell metacharacters, no embedded NUL / newline.
      - each arg must not contain NUL / newline / CR.
      - env keys must match [A-Z][A-Z0-9_]*; values must not contain
        NUL / newline / CR.
    """
    for ch in _DENY_CHARS:
        if ch in spec.command:
            raise ValueError(
                f"MCP server {spec.name!r} command contains illegal char {ch!r}"
            )
    # The command itself is allowed to include path slashes / dots /
    # dashes; reject only shell metacharacters that would re-enter a
    # shell parse.
    for meta in _DENY_SHELL_METAS:
        if meta in spec.command:
            raise ValueError(
                f"MCP server {spec.name!r} command contains shell metacharacter "
                f"{meta!r}; pass it through args instead"
            )
    for i, arg in enumerate(spec.args):
        if not isinstance(arg, str):
            raise ValueError(
                f"MCP server {spec.name!r} arg #{i} is not a string"
            )
        for ch in _DENY_CHARS:
            if ch in arg:
                raise ValueError(
                    f"MCP server {spec.name!r} arg #{i} contains illegal char {ch!r}"
                )
    import re as _re
    key_re = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    for k, v in (spec.env or {}).items():
        if not key_re.match(k):
            raise ValueError(
                f"MCP server {spec.name!r} env key {k!r} is not a valid identifier"
            )
        if not isinstance(v, str):
            raise ValueError(
                f"MCP server {spec.name!r} env[{k}] is not a string"
            )
        for ch in _DENY_CHARS:
            if ch in v:
                raise ValueError(
                    f"MCP server {spec.name!r} env[{k}] contains illegal char {ch!r}"
                )


def _command_looks_like_path(command: str, on_windows: bool | None = None) -> bool:
    """Heuristic: does `command` look like a filesystem path (so we
    should NOT send it through `shutil.which`)?

    Backslash counts as a separator only on Windows; on POSIX it's a
    legal filename character. Split out so tests can pass `on_windows`
    explicitly without monkeypatching `os.name`, which has process-wide
    side effects (it changes which pathlib class `Path()` instantiates).
    """
    if on_windows is None:
        on_windows = os.name == "nt"
    return "/" in command or (on_windows and "\\" in command)


def _verify_command_pin(spec: MCPServerSpec) -> None:
    """If spec.pin_sha256 is set, hash the resolved executable and refuse
    to spawn on mismatch. Resolution uses shutil.which for argv[0].
    Treat backslash as a path separator only on Windows so verifier
    resolution matches subprocess execution semantics on each platform.
    """
    if not spec.pin_sha256:
        return
    import hashlib as _hashlib
    import shutil as _shutil
    from pathlib import Path as _Path
    looks_like_path = _command_looks_like_path(spec.command)
    resolved = spec.command if looks_like_path else _shutil.which(spec.command)
    if not resolved or not _Path(resolved).exists():
        raise MCPClientError(
            f"MCP server {spec.name!r}: cannot resolve {spec.command!r} to "
            f"verify pin_sha256"
        )
    h = _hashlib.sha256()
    with open(resolved, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != spec.pin_sha256:
        raise MCPClientError(
            f"MCP server {spec.name!r}: pin_sha256 mismatch. "
            f"Expected {spec.pin_sha256}, got {actual} for {resolved}"
        )


def _build_env(spec: MCPServerSpec) -> dict[str, str]:
    """Build the env dict for a child MCP server.

    Default: minimal allowlist (PATH/HOME/etc.) + spec.env explicit overrides.
    Opt-in via spec.inherit_env=True for the legacy full-inherit behavior.
    """
    if spec.inherit_env:
        base = dict(os.environ)
    else:
        base = {k: os.environ[k] for k in DEFAULT_ENV_ALLOWLIST if k in os.environ}
    base.update(spec.env)
    return base


class MCPClient:
    def __init__(self, spec: MCPServerSpec, timeout: float = DEFAULT_TIMEOUT):
        self.spec = spec
        self.timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._req_id = 0
        self._lock = asyncio.Lock()
        self._stderr_task: asyncio.Task | None = None
        self.tools: list[dict[str, Any]] = []

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def start(self) -> None:
        # Verify pinned hash before doing anything. This catches the
        # CVE-2026-30615 / Postmark / Smithery supply-chain class --
        # if the binary was replaced under us, refuse to launch.
        _verify_command_pin(self.spec)
        env = _build_env(self.spec)
        log.info("MCP client starting server %r (command=%s, args=%d, env keys=%d)",
                 self.spec.name, self.spec.command, len(self.spec.args), len(env))
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.spec.command, *self.spec.args,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Raise the StreamReader buffer well above the 64 KB default:
                # MCP tools/call results (file reads, search hits, base64
                # images) and big tools/list responses routinely exceed 64 KB,
                # and readline() raises LimitOverrunError on a longer line --
                # crashing the request (or dropping the whole server at start).
                limit=8 * 1024 * 1024,
            )
        except FileNotFoundError as e:
            raise MCPClientError(
                f"MCP server {self.spec.name!r} command not found: {self.spec.command}. "
                "Is it installed? (e.g., `npm install -g @modelcontextprotocol/server-*`)"
            ) from e

        # Drain stderr in the background so the pipe buffer (~64KB on Linux)
        # never fills and blocks the child on write. Without this, MCP
        # servers that log heavily deadlock mid-tool-call.
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        init_resp = await self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "maverick", "version": "0.1.0"},
        })
        log.debug("MCP %s initialized: %s", self.spec.name,
                  init_resp.get("serverInfo", {}))
        await self._notify("notifications/initialized", {})

        tools_resp = await self._request("tools/list", {})
        self.tools = tools_resp.get("tools", [])
        log.info("MCP %s ready (%d tool(s))", self.spec.name, len(self.tools))

    async def _drain_stderr(self) -> None:
        """Forward stderr lines to log.debug so the pipe never fills."""
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            from .secrets import scrub
        except ImportError:  # pragma: no cover -- secrets is in-tree
            scrub = lambda s: s  # noqa: E731
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    return
                try:
                    # A hostile / buggy MCP server can echo bearer tokens or
                    # .env values to stderr; scrub before they hit the log.
                    log.debug("MCP[%s] stderr: %s", self.spec.name,
                              scrub(line.decode("utf-8", errors="replace").rstrip()))
                except Exception:  # noqa: BLE001
                    # Never let a scrub/logging error kill the drain task --
                    # if it dies the ~64KB stderr pipe fills and the child
                    # blocks mid tool-call, the exact deadlock this prevents.
                    pass
        except asyncio.CancelledError:
            return

    def _check_alive(self) -> None:
        if self._proc is None:
            raise MCPClientError("server not started")
        if self._proc.returncode is not None:
            raise MCPClientError(
                f"MCP server {self.spec.name!r} exited with code "
                f"{self._proc.returncode}"
            )

    async def _request(self, method: str, params: dict) -> dict:
        async with self._lock:
            self._check_alive()
            req_id = self._next_id()
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            await self._send(payload)
            try:
                return await asyncio.wait_for(
                    self._read_response(req_id), timeout=self.timeout)
            except asyncio.TimeoutError:
                # req_id is already on the wire; without a cancel the server
                # runs the call to completion and leaves its late reply in the
                # pipe (drained only by the next request). Tell it to stop.
                # We still hold _lock here, so send directly -- asyncio.Lock
                # isn't reentrant and _notify would deadlock.
                await self._send_cancel(req_id)
                raise

    async def _notify(self, method: str, params: dict) -> None:
        async with self._lock:
            self._check_alive()
            await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send_cancel(self, request_id: int) -> None:
        """Best-effort MCP cancellation for a request we've given up on.

        Called from _request's timeout path while _lock is held, so it sends
        directly rather than via _notify (the lock isn't reentrant). A failure
        here must not mask the timeout the caller is about to see."""
        try:
            await self._send({
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": request_id, "reason": "client timeout"},
            })
        except Exception:  # noqa: BLE001 -- the request is already lost
            pass

    async def _send(self, payload: dict) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        line = (json.dumps(payload) + "\n").encode()
        self._proc.stdin.write(line)
        await self._proc.stdin.drain()

    async def _read_response(self, expected_id: int) -> dict:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                raise MCPClientError(f"MCP server {self.spec.name!r} closed stdout")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                log.debug("MCP %s non-JSON line: %s", self.spec.name, line[:200])
                continue
            # A JSON-RPC error with id:null (parse error / invalid request)
            # never matches expected_id, so without this it would be skipped and
            # the read would block until the timeout. Surface it immediately.
            if msg.get("id") is None and "error" in msg:
                err = msg["error"]
                raise MCPClientError(
                    f"MCP {self.spec.name!r} protocol error "
                    f"{err.get('code')}: {err.get('message')}"
                )
            # Drop notifications + responses for other requests.
            if msg.get("id") != expected_id:
                continue
            if "error" in msg:
                err = msg["error"]
                raise MCPClientError(
                    f"MCP {self.spec.name!r} error {err.get('code')}: {err.get('message')}"
                )
            return msg.get("result", {})

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        resp = await self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        # A tool error is a real failure -> raise, so it rides the same path
        # as transport/protocol errors (the wrapper in mcp_tools.py turns any
        # exception into the agent-visible "ERROR: ..." string). The old
        # "ERROR: " text prefix was ambiguous: a successful result whose text
        # merely started with "ERROR:" was indistinguishable from a failure.
        if resp.get("isError"):
            raise MCPClientError(
                f"MCP {self.spec.name!r} tool {tool_name!r} failed: "
                + _content_to_str(resp.get("content", []))
            )
        text = _content_to_str(resp.get("content", []))
        # A spec-compliant server mirrors structuredContent in a text block,
        # but one that returns only structured output would otherwise come
        # back empty -- fall back to the serialized structured result so the
        # data still reaches the model.
        if not text and resp.get("structuredContent") is not None:
            return json.dumps(resp["structuredContent"])
        return text

    async def stop(self) -> None:
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass
            self._stderr_task = None
        if self._proc is None:
            return
        if self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:  # pragma: no cover
                self._proc.kill()
                # Reap the killed child so it isn't left a zombie (the only
                # handle is dropped on the next line).
                try:
                    await self._proc.wait()
                except Exception:
                    pass
        self._proc = None


def _content_to_str(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content is not None else ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "resource":
                # Embedded resource: surface its text directly (a text file's
                # contents) instead of a JSON dump; fall back to JSON for a
                # binary blob / bare uri so nothing is silently lost.
                res = block.get("resource")
                if isinstance(res, dict) and isinstance(res.get("text"), str):
                    parts.append(res["text"])
                else:
                    parts.append(json.dumps(block))
            else:
                parts.append(json.dumps(block))
        else:
            parts.append(str(block))
    return "\n".join(parts)


async def start_mcp_clients(specs: list[MCPServerSpec]) -> list[MCPClient]:
    clients = [MCPClient(spec) for spec in specs]

    async def _try_start(c: MCPClient) -> MCPClient | None:
        try:
            await c.start()
            return c
        except Exception as e:
            log.error("MCP server %r failed to start: %s", c.spec.name, e)
            # start() spawns the subprocess + a stderr-drain task BEFORE
            # the initialize/tools-list calls that can fail. A failed
            # client is dropped from the returned list, so nothing else
            # will ever reap it — clean it up here to avoid a zombie
            # process + orphaned task per failed start.
            try:
                await c.stop()
            except Exception:  # pragma: no cover -- best-effort cleanup
                pass
            return None

    results = await asyncio.gather(*(_try_start(c) for c in clients))
    return [c for c in results if c is not None]


async def stop_mcp_clients(clients: list[MCPClient]) -> None:
    await asyncio.gather(*(c.stop() for c in clients), return_exceptions=True)


def load_mcp_specs_from_config() -> list[MCPServerSpec]:
    try:
        from .config import load_config
        cfg = load_config()
    except Exception:
        return []
    servers = cfg.get("mcp_servers", {}) or {}
    out: list[MCPServerSpec] = []
    for name, server_cfg in servers.items():
        if not isinstance(server_cfg, dict):
            continue
        if not server_cfg.get("enabled", True):
            continue
        if "command" not in server_cfg:
            log.warning("mcp_servers.%s missing 'command'; skipping", name)
            continue
        try:
            out.append(MCPServerSpec.from_config(name, server_cfg))
        except Exception as e:  # pragma: no cover
            log.error("mcp_servers.%s invalid: %s", name, e)
    return out
