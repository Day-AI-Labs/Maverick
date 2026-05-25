"""MCP client: let Maverick consume external MCP servers as tools.

The complement to ``maverick-mcp`` (which exposes Maverick as an MCP
server to Claude Code etc.). With this module, Maverick can SPAWN
third-party MCP servers (filesystem, GitHub, Postgres, fetch, browser,
etc.) and route their tools into the agent's tool registry.

Config::

    [mcp_servers.filesystem]
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "/home/me/projects"]

    [mcp_servers.github]
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-github"]
    env = { GITHUB_PERSONAL_ACCESS_TOKEN = "${GITHUB_TOKEN}" }

    [mcp_servers.postgres]
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-postgres",
            "postgres://localhost/mydb"]

At agent startup, each enabled MCP server is spawned as a child
process. The agent issues ``tools/list`` to discover that server's
tools, and registers each one as a Maverick ``Tool`` with the prefix
``mcp_<server>__<tool>``. Tool calls go through stdio JSON-RPC; the
responses come back as text and are surfaced through the same
Shield ``scan_tool_call`` chokepoint as built-in tools.

Protocol: MCP 2024-11-05 (initialize -> tools/list -> tools/call).
No external Python dependency -- pure stdio JSON-RPC over subprocess.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 30.0


class MCPClientError(Exception):
    pass


@dataclass
class MCPServerSpec:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_config(cls, name: str, cfg: dict) -> "MCPServerSpec":
        return cls(
            name=name,
            command=cfg["command"],
            args=list(cfg.get("args", [])),
            env={k: str(v) for k, v in (cfg.get("env", {}) or {}).items()},
        )


class MCPClient:
    """Async stdio JSON-RPC 2.0 client for one MCP server.

    Lifecycle:
      1. ``start()`` spawns the server subprocess and runs initialize +
         tools/list. Populates ``self.tools``.
      2. ``call_tool(name, args)`` issues tools/call, awaits the
         response, returns the textual content.
      3. ``stop()`` terminates the subprocess.

    Not thread-safe; one MCPClient per server, owned by the SwarmContext.
    """

    def __init__(self, spec: MCPServerSpec, timeout: float = DEFAULT_TIMEOUT):
        self.spec = spec
        self.timeout = timeout
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._req_id = 0
        self._lock = asyncio.Lock()
        self.tools: list[dict[str, Any]] = []

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def start(self) -> None:
        env = {**os.environ, **self.spec.env}
        log.info("MCP client starting server %r (%s %s)",
                 self.spec.name, self.spec.command, " ".join(self.spec.args))
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.spec.command, *self.spec.args,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise MCPClientError(
                f"MCP server {self.spec.name!r} command not found: {self.spec.command}. "
                "Is it installed? (e.g., `npm install -g @modelcontextprotocol/server-*`)"
            ) from e

        # Handshake
        init_resp = await self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "maverick", "version": "0.1.0"},
        })
        log.debug("MCP %s initialized: %s", self.spec.name,
                  init_resp.get("serverInfo", {}))
        await self._notify("notifications/initialized", {})

        # Tool discovery
        tools_resp = await self._request("tools/list", {})
        self.tools = tools_resp.get("tools", [])
        log.info("MCP %s ready (%d tool(s))", self.spec.name, len(self.tools))

    async def _request(self, method: str, params: dict) -> dict:
        async with self._lock:
            req_id = self._next_id()
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            await self._send(payload)
            return await asyncio.wait_for(self._read_response(req_id), timeout=self.timeout)

    async def _notify(self, method: str, params: dict) -> None:
        async with self._lock:
            await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, payload: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPClientError("server not started")
        line = (json.dumps(payload) + "\n").encode()
        self._proc.stdin.write(line)
        await self._proc.stdin.drain()

    async def _read_response(self, expected_id: int) -> dict:
        if self._proc is None or self._proc.stdout is None:
            raise MCPClientError("server not started")
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                raise MCPClientError(f"MCP server {self.spec.name!r} closed stdout")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                log.debug("MCP %s non-JSON line: %s", self.spec.name, line[:200])
                continue
            # Skip notifications (no id) and unrelated responses.
            if msg.get("id") != expected_id:
                continue
            if "error" in msg:
                err = msg["error"]
                raise MCPClientError(
                    f"MCP {self.spec.name!r} error {err.get('code')}: {err.get('message')}"
                )
            return msg.get("result", {})

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call an MCP tool and return its content as a single string."""
        resp = await self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if resp.get("isError"):
            content = resp.get("content", [])
            return "ERROR: " + _content_to_str(content)
        return _content_to_str(resp.get("content", []))

    async def stop(self) -> None:
        if self._proc is None:
            return
        if self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:  # pragma: no cover
                self._proc.kill()
        self._proc = None


def _content_to_str(content: Any) -> str:
    """MCP content is a list of {type:'text',text:...} blocks; flatten."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content is not None else ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block))
        else:
            parts.append(str(block))
    return "\n".join(parts)


async def start_mcp_clients(specs: list[MCPServerSpec]) -> list[MCPClient]:
    """Spawn every spec's server in parallel. Returns the started clients.

    Servers that fail to start are skipped with an error log; we don't
    let one bad MCP server take down the whole agent.
    """
    clients = [MCPClient(spec) for spec in specs]

    async def _try_start(c: MCPClient) -> Optional[MCPClient]:
        try:
            await c.start()
            return c
        except Exception as e:
            log.error("MCP server %r failed to start: %s", c.spec.name, e)
            return None

    results = await asyncio.gather(*(_try_start(c) for c in clients))
    return [c for c in results if c is not None]


async def stop_mcp_clients(clients: list[MCPClient]) -> None:
    await asyncio.gather(*(c.stop() for c in clients), return_exceptions=True)


def load_mcp_specs_from_config() -> list[MCPServerSpec]:
    """Read [mcp_servers.<name>] tables from ~/.maverick/config.toml."""
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
