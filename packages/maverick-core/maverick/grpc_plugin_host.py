"""gRPC plugin host: tools served by an external process over gRPC.

``ts_plugin_host`` hosts NDJSON-over-stdio plugins (the TypeScript SDK); this
module is the same seam for every other language — anything that can serve two
gRPC methods can ship Maverick tools. The contract lives in
``grpc_api/plugin_host.proto``::

    service MaverickPlugin {
      rpc Describe(DescribeRequest) returns (Manifest);  // the tool manifest
      rpc Call(ToolCall) returns (ToolResult);           // one invocation
    }

``load_grpc_plugin(target)`` dials the plugin server (``localhost:50051`` or
``unix:///path.sock``), runs ``Describe`` and returns one
``maverick.tools.Tool`` per manifest entry; pass ``command`` to have the host
spawn the server process first. This is host-level plugin loading driven by
operator config — like the MCP stdio client (``mcp_client``), not model-driven
shell — so it spawns the child directly rather than through ``sandbox.exec``,
always with a scrubbed env (``scrub_child_env``) so provider keys and connector
tokens never reach plugin code, and kills it at interpreter exit. Failures
follow the built-in tool convention: the model sees an ``"ERROR: ..."`` string,
never an exception. Every ``Call`` carries a deadline (a gRPC deadline,
mirrored in ``deadline_ms``); a dropped channel is rebuilt — and a spawned
server that died is respawned — and the call retried once, the analogue of the
NDJSON host's one crash-restart. grpcio is imported lazily behind the
``[grpc]`` extra; importing this module never requires it.
"""
from __future__ import annotations

import atexit
import json
import logging
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from .tools import Tool, scrub_child_env

log = logging.getLogger(__name__)

DESCRIBE_TIMEOUT = 10.0
DEFAULT_CALL_TIMEOUT = 60.0

# Same constraint the model-facing tool catalog imposes (Anthropic tool names).
_TOOL_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

_PROTO = Path(__file__).with_name("grpc_api") / "plugin_host.proto"


class GrpcPluginError(Exception):
    """The plugin server couldn't be spawned/reached or gave no manifest."""


def _require_grpc():
    try:
        import grpc
    except ImportError as e:
        raise ImportError(
            "grpc not installed (needed for gRPC plugins). "
            "Run: pip install 'maverick-agent[grpc]'"
        ) from e
    return grpc


def _load_stubs():
    """Import the generated pb2 modules, generating them first if absent.

    Same scheme as ``grpc_api.server._load_stubs``: stubs compile on demand
    from the bundled ``plugin_host.proto`` so no generated code is checked in.
    """
    try:
        from .grpc_api import plugin_host_pb2, plugin_host_pb2_grpc  # type: ignore
        return plugin_host_pb2, plugin_host_pb2_grpc
    except ImportError:
        _generate_stubs()
        from .grpc_api import plugin_host_pb2, plugin_host_pb2_grpc  # type: ignore
        return plugin_host_pb2, plugin_host_pb2_grpc


def _generate_stubs() -> None:
    """Compile plugin_host.proto into the grpc_api package via grpc_tools.

    Rooted at the directory *containing* ``maverick/`` (site-packages in an
    installed wheel) so protoc emits package-qualified imports
    (``from maverick.grpc_api import plugin_host_pb2 ...``) and the generated
    pair is importable from anywhere.
    """
    try:
        from grpc_tools import protoc
    except ImportError as e:
        raise ImportError(
            "grpcio-tools not installed (needed to generate stubs). "
            "Run: pip install 'maverick-agent[grpc]'"
        ) from e
    root = _PROTO.parents[2]
    rc = protoc.main([
        "protoc",
        f"-I{root}",
        f"--python_out={root}",
        f"--grpc_python_out={root}",
        str(_PROTO),
    ])
    if rc != 0:  # pragma: no cover -- only on a broken protoc toolchain
        raise RuntimeError(f"protoc failed to generate gRPC plugin stubs (rc={rc})")


class _PluginChannel:
    """One plugin-server connection shared by every tool of a plugin.

    Calls are serialized under a lock (reconnecting mutates the channel). The
    optional server process and the channel are built on first use; a channel
    that drops mid-call is rebuilt — respawning a spawned server that died —
    at most once per call.
    """

    def __init__(self, target: str, command: list[str] | None, call_timeout: float):
        self.target = target
        self.command = list(command) if command else None
        self.call_timeout = call_timeout
        self._proc: subprocess.Popen | None = None
        self._channel: Any = None
        self._stub: Any = None
        self._lock = threading.Lock()

    def _connect(self):
        """(stub, pb2), spawning the server / dialing the channel as needed."""
        grpc = _require_grpc()
        pb2, pb2_grpc = _load_stubs()
        if self.command and (self._proc is None or self._proc.poll() is not None):
            self._proc = subprocess.Popen(
                self.command,
                # DEVNULL, not PIPE: stdio is not the protocol here and
                # nothing drains it, so a chatty server would fill the pipe
                # buffer and stall.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=scrub_child_env(),
            )
        if self._stub is None:
            self._channel = grpc.insecure_channel(self.target)
            self._stub = pb2_grpc.MaverickPluginStub(self._channel)
        return self._stub, pb2

    def _drop_channel(self) -> None:
        channel, self._channel, self._stub = self._channel, None, None
        if channel is not None:
            try:
                channel.close()
            except Exception:  # pragma: no cover -- close is best-effort
                pass

    def close(self) -> None:
        self._drop_channel()
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def describe(self) -> list[Any]:
        """The manifest's ToolSpecs. Raises GrpcPluginError (or ImportError)."""
        try:
            stub, pb2 = self._connect()
        except OSError as e:
            raise GrpcPluginError(f"grpc plugin {self.command} failed to run: {e}") from e
        try:
            # wait_for_ready: a just-spawned server needs a moment to bind.
            manifest = stub.Describe(
                pb2.DescribeRequest(), timeout=DESCRIBE_TIMEOUT, wait_for_ready=True,
            )
        except Exception as e:
            raise GrpcPluginError(
                f"grpc plugin at {self.target}: Describe failed: {e}"
            ) from e
        return list(manifest.tools)

    def call(self, tool: str, args: dict[str, Any]) -> str:
        grpc = _require_grpc()
        with self._lock:
            for attempt in (1, 2):
                try:
                    stub, pb2 = self._connect()
                except OSError as e:
                    self.close()
                    return f"ERROR: grpc plugin {self.command} failed to start: {e}"
                request = pb2.ToolCall(
                    tool=tool,
                    args_json=json.dumps(args),
                    deadline_ms=int(self.call_timeout * 1000),
                )
                try:
                    resp = stub.Call(
                        request,
                        timeout=self.call_timeout,
                        # On the retry the channel was just rebuilt (and a
                        # spawned server possibly restarted): queue the RPC
                        # until the connection is up rather than failing the
                        # retry on the same race.
                        wait_for_ready=attempt == 2,
                    )
                except grpc.RpcError as e:
                    code = getattr(e, "code", None)
                    if callable(code) and code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                        # A per-call deadline doesn't desync the channel (unlike
                        # the NDJSON stream): keep it and don't retry a slow tool.
                        return (
                            f"ERROR: grpc plugin tool {tool!r} timed out "
                            f"after {self.call_timeout}s"
                        )
                    self._drop_channel()
                    if attempt == 1:
                        log.warning(
                            "grpc plugin at %s dropped during %r; reconnecting once",
                            self.target, tool,
                        )
                        continue
                    return f"ERROR: grpc plugin tool {tool!r} failed: {e}"
                if resp.error:
                    return f"ERROR: grpc plugin tool {tool!r}: {resp.error}"
                return str(resp.result)
        return f"ERROR: grpc plugin tool {tool!r} failed"  # pragma: no cover


# Channels (and any spawned servers) live as long as the process (tools have
# no lifecycle hooks); close them at interpreter exit so none outlive the host.
_CHANNELS: list[_PluginChannel] = []


def _close_all_channels() -> None:
    for c in _CHANNELS:
        c.close()


atexit.register(_close_all_channels)


def load_grpc_plugin(
    target: str,
    *,
    command: list[str] | None = None,
    call_timeout: float = DEFAULT_CALL_TIMEOUT,
) -> list[Tool]:
    """Load a gRPC plugin; one Tool per manifest entry.

    ``target`` is the gRPC target to dial, e.g. ``localhost:50051`` or
    ``unix:///run/plugin.sock``. ``command`` is an optional operator-configured
    argv the host spawns first (the server side of ``target``), e.g.
    ``["/usr/local/bin/my-plugin", "--port", "50051"]``. Raises ImportError
    without the [grpc] extra and GrpcPluginError when the manifest can't be
    fetched; entries with an invalid name are skipped with a warning.
    """
    chan = _PluginChannel(target, command, call_timeout)
    try:
        specs = chan.describe()
    except Exception:
        chan.close()  # never leak a spawned server on a failed load
        raise
    tools: list[Tool] = []
    for spec in specs:
        name = str(spec.name or "")
        if not _TOOL_NAME_RE.fullmatch(name):
            log.warning("grpc plugin at %s: invalid tool name %r; skipping", target, name)
            continue
        try:
            schema = json.loads(spec.input_schema_json or "")
        except ValueError:
            schema = None
        if not isinstance(schema, dict):
            schema = {"type": "object"}

        def fn(args: dict[str, Any], _name: str = name) -> str:
            return chan.call(_name, dict(args or {}))

        tools.append(Tool(
            name=name,
            description=str(spec.description or ""),
            input_schema=schema,
            fn=fn,
        ))
    if tools:
        _CHANNELS.append(chan)
    else:
        chan.close()
    return tools


def load_configured_grpc_plugins() -> list[Tool]:
    """Tools from ``[plugins] grpc = [{ target = "...", command = ["..."] }]``.

    Listing an entry there is the opt-in; ``command`` is optional (the host
    then spawns the server too). Forgiving like the entry-point loaders in
    ``plugins``: a broken entry — including a missing [grpc] extra — logs and
    is skipped. Returns the Tools for the integrator to register — this module
    never touches the registry itself.
    """
    try:
        from .config import load_config
        configured = load_config().get("plugins", {}).get("grpc", [])
    except Exception as e:
        log.warning(
            "grpc plugin config read failed (%s: %s); none loaded",
            type(e).__name__, e,
        )
        return []
    if not isinstance(configured, list):
        log.warning("[plugins] grpc must be a list of {target, command} tables; none loaded")
        return []
    out: list[Tool] = []
    for entry in configured:
        target = entry.get("target") if isinstance(entry, dict) else None
        command = entry.get("command") if isinstance(entry, dict) else None
        if not (isinstance(target, str) and target.strip()):
            log.warning("[plugins] grpc entry %r has no target; skipping", entry)
            continue
        if command is not None and not (
            isinstance(command, list) and command and all(isinstance(c, str) for c in command)
        ):
            log.warning(
                "[plugins] grpc entry %r command is not a list of strings; skipping", entry,
            )
            continue
        try:
            out.extend(load_grpc_plugin(target.strip(), command=command))
        except (GrpcPluginError, ImportError) as e:
            log.warning("grpc plugin %s failed to load: %s", target, e)
    return out
