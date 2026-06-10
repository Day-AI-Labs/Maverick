"""TypeScript plugin host: tools served by an external process over NDJSON stdio.

Maverick's native plugins are Python entry points (see ``plugins``). The
TypeScript plugin SDK (``sdks/plugin-ts``, npm ``@maverick/plugin-sdk``) lets an
author ship tools as a Node script instead; this module is the Python side of
that seam. The wire protocol is NDJSON, one JSON object per line:

  - ``<command> --describe`` prints a one-line manifest and exits::

        {"protocol": "maverick-plugin/1",
         "tools": [{"name": ..., "description": ..., "inputSchema": {...}}]}

  - otherwise the child reads requests on stdin and answers on stdout::

        {"id": 1, "tool": "echo", "args": {...}}
        -> {"id": 1, "result": "..."}  |  {"id": 1, "error": "..."}

``load_ts_plugin(command)`` runs the describe step and returns one
``maverick.tools.Tool`` per manifest entry; calls share a single persistent
child, started lazily on first use. This is host-level plugin loading driven by
operator config -- like the MCP stdio client (``mcp_client``), not model-driven
shell -- so it spawns the child directly rather than through ``sandbox.exec``,
always with a scrubbed env (``scrub_child_env``) so provider keys and connector
tokens never reach plugin code. Failures follow the built-in tool convention:
the model sees an ``"ERROR: ..."`` string, never an exception. A child that
dies mid-call is restarted and the call retried once; a call that exceeds the
timeout kills the child (a late reply would desync the stream) so the next
call gets a fresh process.
"""
from __future__ import annotations

import atexit
import json
import logging
import re
import subprocess
import threading
import time
from typing import IO, Any

from .tools import Tool, scrub_child_env

log = logging.getLogger(__name__)

DESCRIBE_TIMEOUT = 10.0
DEFAULT_CALL_TIMEOUT = 60.0

# Same constraint the model-facing tool catalog imposes (Anthropic tool names).
_TOOL_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class TsPluginError(Exception):
    """The plugin command couldn't be run or produced no usable manifest."""


class _ChildDied(Exception):
    """Child exited / closed its pipes mid-call (retried once by ``call``)."""


class _PluginChild:
    """One persistent NDJSON child shared by every tool of a plugin.

    Calls are serialized under a lock (the tools share one stdio pipe). The
    child starts lazily on first call and is restarted at most once per call
    if it dies mid-request.
    """

    def __init__(self, command: list[str], call_timeout: float):
        self.command = list(command)
        self.call_timeout = call_timeout
        self._proc: subprocess.Popen | None = None
        self._req_id = 0
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # DEVNULL, not PIPE: nothing drains stderr here, so a chatty
                # plugin would fill the pipe buffer and deadlock mid-call.
                stderr=subprocess.DEVNULL,
                env=scrub_child_env(),
                text=True,
            )

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def _read_line(stdout: IO[str], timeout: float) -> str | None:
        """Blocking readline in a side thread; None on timeout.

        After a timeout the caller kills the child, which EOFs the orphaned
        readline so the thread exits instead of leaking.
        """
        got: list[str] = []

        def _read() -> None:
            try:
                got.append(stdout.readline())
            except (ValueError, OSError):
                got.append("")

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout)
        return got[0] if got else None

    def _roundtrip(self, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        """Send one request; return the matching response, or None on timeout."""
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None
        self._req_id += 1
        rid = self._req_id
        try:
            proc.stdin.write(json.dumps({"id": rid, "tool": tool, "args": args}) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise _ChildDied from e
        deadline = time.monotonic() + self.call_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            reply = self._read_line(proc.stdout, remaining)
            if reply is None:
                return None
            if reply == "":
                raise _ChildDied  # EOF: child exited
            try:
                resp = json.loads(reply)
            except ValueError:
                continue  # not protocol output (e.g. a stray console.log); skip
            if isinstance(resp, dict) and resp.get("id") == rid:
                return resp

    def call(self, tool: str, args: dict[str, Any]) -> str:
        with self._lock:
            for attempt in (1, 2):
                try:
                    self._ensure_started()
                    resp = self._roundtrip(tool, args)
                except _ChildDied:
                    self.close()
                    if attempt == 1:
                        log.warning(
                            "ts plugin %s died during %r; restarting once",
                            self.command, tool,
                        )
                        continue
                    return f"ERROR: ts plugin tool {tool!r} crashed (child exited twice)"
                except OSError as e:
                    self.close()
                    return f"ERROR: ts plugin {self.command} failed to start: {e}"
                if resp is None:
                    self.close()  # stream is desynced; next call gets a fresh child
                    return (
                        f"ERROR: ts plugin tool {tool!r} timed out "
                        f"after {self.call_timeout}s"
                    )
                if "error" in resp:
                    return f"ERROR: ts plugin tool {tool!r}: {resp['error']}"
                result = resp.get("result")
                return result if isinstance(result, str) else json.dumps(result)
        return f"ERROR: ts plugin tool {tool!r} failed"  # pragma: no cover


# Children live as long as the process (tools have no lifecycle hooks); kill
# them at interpreter exit so none outlive the host.
_CHILDREN: list[_PluginChild] = []


def _close_all_children() -> None:
    for c in _CHILDREN:
        c.close()


atexit.register(_close_all_children)


def _fetch_manifest(command: list[str]) -> list[Any]:
    try:
        r = subprocess.run(
            [*command, "--describe"],
            capture_output=True, text=True,
            timeout=DESCRIBE_TIMEOUT, env=scrub_child_env(),
        )
    except OSError as e:
        raise TsPluginError(f"ts plugin {command} failed to run: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise TsPluginError(f"ts plugin {command} --describe timed out") from e
    if r.returncode != 0:
        raise TsPluginError(
            f"ts plugin {command} --describe exited {r.returncode}: {r.stderr.strip()[:500]}"
        )
    for line in r.stdout.splitlines():
        try:
            manifest = json.loads(line)
        except ValueError:
            continue
        if isinstance(manifest, dict) and isinstance(manifest.get("tools"), list):
            return manifest["tools"]
    raise TsPluginError(f"ts plugin {command} --describe printed no manifest")


def load_ts_plugin(
    command: list[str], *, call_timeout: float = DEFAULT_CALL_TIMEOUT,
) -> list[Tool]:
    """Load an NDJSON plugin; one Tool per manifest entry.

    ``command`` is the operator-configured argv, e.g. ``["node", "/abs/plugin.js"]``.
    Raises TsPluginError when the manifest can't be fetched or parsed; entries
    with an invalid name are skipped with a warning.
    """
    child = _PluginChild(command, call_timeout)
    tools: list[Tool] = []
    for entry in _fetch_manifest(command):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not (isinstance(name, str) and _TOOL_NAME_RE.fullmatch(name)):
            log.warning("ts plugin %s: invalid tool name %r; skipping", command, name)
            continue
        schema = entry.get("inputSchema")
        if not isinstance(schema, dict):
            schema = {"type": "object"}

        def fn(args: dict[str, Any], _name: str = name) -> str:
            return child.call(_name, dict(args or {}))

        tools.append(Tool(
            name=name,
            description=str(entry.get("description") or ""),
            input_schema=schema,
            fn=fn,
        ))
    if tools:
        _CHILDREN.append(child)
    return tools


def load_configured_ts_plugins() -> list[Tool]:
    """Tools from ``[plugins] ts = [["node", "/abs/plugin.js"], ...]`` in config.

    Listing a command there is the opt-in. Forgiving like the entry-point
    loaders in ``plugins``: a broken entry logs and is skipped. Returns the
    Tools for the integrator to register -- this module never touches the
    registry itself.
    """
    try:
        from .config import load_config
        configured = load_config().get("plugins", {}).get("ts", [])
    except Exception as e:
        log.warning(
            "ts plugin config read failed (%s: %s); none loaded",
            type(e).__name__, e,
        )
        return []
    if not isinstance(configured, list):
        log.warning("[plugins] ts must be a list of argv lists; none loaded")
        return []
    out: list[Tool] = []
    for cmd in configured:
        if not (
            isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd)
        ):
            log.warning("[plugins] ts entry %r is not a list of strings; skipping", cmd)
            continue
        try:
            out.extend(load_ts_plugin(cmd))
        except TsPluginError as e:
            log.warning("ts plugin %s failed to load: %s", cmd, e)
    return out
