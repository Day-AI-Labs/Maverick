"""MCP server for Maverick."""
from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
from typing import Any

from .tasks import TaskError

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] mcp: %(message)s",
)

# Protocol version. MCP 2025-11-25 ships Tasks / Resources / Elicitation /
# Sampling / MCP Apps; we negotiate down to the older spec when a client
# advertises that, but our initialize response is on the current one.
PROTOCOL_VERSION = "2025-11-25"
PROTOCOL_VERSION_FALLBACK = "2024-11-05"
# Spec revisions we can negotiate. Our behaviour is a superset of the older
# specs, so we accept the intermediate revisions too. MCP rule: echo the
# client's requested version if we support it, else respond with our latest.
SUPPORTED_PROTOCOL_VERSIONS = (
    PROTOCOL_VERSION_FALLBACK, "2025-03-26", "2025-06-18", PROTOCOL_VERSION,
)
SERVER_NAME = "maverick"
try:
    from importlib.metadata import version as _pkg_version

    # Keep serverInfo.version in lockstep with the published package version
    # rather than a hand-bumped constant that drifts (was "0.2.0" while the
    # package shipped 0.1.6).
    SERVER_VERSION = _pkg_version("maverick-mcp-server")
except Exception:  # pragma: no cover -- metadata is present once installed
    SERVER_VERSION = "0.1.6"


def _bounded_float(value: Any, *, default: float, ceiling: float) -> float:
    """Return a finite, non-negative value clamped to an operator ceiling."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    if not math.isfinite(parsed) or parsed < 0:
        parsed = float(default)

    try:
        parsed_ceiling = float(ceiling)
    except (TypeError, ValueError):
        parsed_ceiling = float(default)
    if not math.isfinite(parsed_ceiling) or parsed_ceiling < 0:
        parsed_ceiling = float(default)

    return min(parsed, parsed_ceiling)


def _bounded_int(value: Any, *, default: int, ceiling: float) -> int:
    return int(_bounded_float(value, default=float(default), ceiling=ceiling))


class _ProtocolError(Exception):
    """Raised for JSON-RPC protocol-level errors (unknown method/tool, bad params).

    The `run()` loop catches this and emits a structured JSON-RPC error
    response (per MCP 2024-11-05 spec). Surface in tests via
    pytest.raises -- it deliberately does NOT collapse into an isError
    envelope because Claude Desktop / Cursor treat those differently.
    """
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


TOOLS: list[dict[str, Any]] = [
    {
        "name": "maverick_start",
        "description": (
            "Start a new goal in Maverick's recursive multi-agent swarm. "
            "Returns the final answer after the swarm completes. Long-running."
        ),
        # Long-running, so it supports task augmentation (run async, poll for
        # the result) where the client and transport (stdio) allow it.
        "execution": {"taskSupport": "optional"},
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "max_dollars": {"type": "number", "default": 5.0},
                "max_wall_seconds": {"type": "number", "default": 3600},
                "max_depth": {"type": "integer", "default": 3},
            },
            "required": ["title"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "integer"},
                "answer": {"type": "string"},
            },
            "required": ["goal_id", "answer"],
        },
    },
    {
        "name": "maverick_status",
        "description": "List recent goals and any open questions.",
        "inputSchema": {"type": "object", "properties": {}},
        "outputSchema": {
            "type": "object",
            "properties": {
                "goals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "status": {"type": "string"},
                            "title": {"type": "string"},
                        },
                    },
                },
                "open_questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "goal_id": {"type": "integer"},
                            "question": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["goals", "open_questions"],
        },
    },
    {
        "name": "maverick_resume",
        "description": "Resume a paused goal by id.",
        "execution": {"taskSupport": "optional"},
        "inputSchema": {
            "type": "object",
            "properties": {"goal_id": {"type": "integer"}},
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "integer"},
                "answer": {"type": "string"},
            },
            "required": ["goal_id", "answer"],
        },
    },
    {
        "name": "maverick_answer",
        "description": "Answer a queued question.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question_id": {"type": "integer"},
                "answer": {"type": "string"},
            },
            "required": ["question_id", "answer"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {"question_id": {"type": "integer"}},
            "required": ["question_id"],
        },
    },
    {
        "name": "maverick_skill_install",
        "description": "Install a SKILL.md from a URL or gh:org/repo[:path].",
        "inputSchema": {
            "type": "object",
            "properties": {"source": {"type": "string"}},
            "required": ["source"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["name", "path"],
        },
    },
    {
        "name": "maverick_skills_list",
        "description": "List installed / distilled skills.",
        "inputSchema": {"type": "object", "properties": {}},
        "outputSchema": {
            "type": "object",
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "triggers": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            "required": ["skills"],
        },
    },
    {
        "name": "maverick_fact_set",
        "description": "Store a fact in the persistent world model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "maverick_facts_get",
        "description": "Get all known facts.",
        "inputSchema": {"type": "object", "properties": {}},
        "outputSchema": {
            "type": "object",
            "properties": {
                "facts": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["facts"],
        },
    },
]

_TOOL_NAMES = {t["name"] for t in TOOLS}

# Form a parked free-text ask_user question is surfaced as, when the client
# supports elicitation. A single required string keeps the round trip simple.
_ELICIT_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "title": "Your answer"}},
    "required": ["answer"],
}


def _elicit_timeout() -> float:
    """Seconds to wait for an elicitation response before giving up (and
    leaving the question parked for the async maverick_answer flow)."""
    return _bounded_float(
        os.environ.get("MAVERICK_MCP_ELICITATION_TIMEOUT", 300.0),
        default=300.0, ceiling=86400.0,
    )


def _tool_supports_tasks(tool_spec: dict) -> bool:
    """Whether a tool opted into task augmentation via execution.taskSupport."""
    return tool_spec.get("execution", {}).get("taskSupport") in ("optional", "required")


class MCPServer:
    # Resources a client may subscribe to, and which mutating tool dirties
    # each -- after such a tool call we push notifications/resources/updated.
    RESOURCE_URIS = ("maverick://goals", "maverick://skills")
    _TOOL_RESOURCE = {
        "maverick_start": "maverick://goals",
        "maverick_resume": "maverick://goals",
        "maverick_answer": "maverick://goals",
        "maverick_skill_install": "maverick://skills",
    }

    def __init__(self):
        self._initialized = False
        self._shield = self._build_shield()
        # resources/subscribe state: URIs the client wants updates for, plus
        # the updates queued by the current tools/call to flush after its
        # result (so the client sees result-then-notification).
        self._subscriptions: set[str] = set()
        self._pending_updates: list[str] = []
        # Elicitation (server-initiated forms). Capabilities the CLIENT
        # advertised at initialize -- elicitation is a *client* capability, so
        # we only emit elicitation/create when the client declared it. _stdio
        # gates it to the stdio transport (a server->client request mid-call has
        # no place in the HTTP request/response model). _elicit_seq namespaces
        # our outbound request ids so they never collide with the client's.
        self._client_capabilities: dict = {}
        self._stdio = False
        self._elicit_seq = 0
        # MCP Tasks: lazily built on first task-augmented call so a transport
        # that never uses tasks doesn't spin up an executor.
        self._tasks = None
        # Whether async tasks are offered on this transport. stdio sets it in
        # run(); the HTTP transport sets it from MAVERICK_MCP_HTTP_TASKS in
        # build_app (opt-in, since multi-client task isolation is bearer-scoped).
        # Kept distinct from _stdio because elicitation is stdio-only (it needs
        # the bidirectional pipe) while tasks are not.
        self._tasks_enabled = False
        # Serializes transport writes. A task's background worker emits
        # notifications/tasks/status while the main loop may be writing a
        # response, so the two must not interleave a half-line on stdout.
        self._send_lock = threading.Lock()

    @staticmethod
    def _build_shield():
        try:
            from maverick_shield import Shield
            return Shield.from_config()
        except Exception:
            return None

    def handle_initialize(self, params: dict) -> dict:
        self._initialized = True
        # Record the client's advertised capabilities. Elicitation is a client
        # capability: its presence here is our gate for emitting elicitation/
        # create later (see _maybe_elicit_open_questions). Coerce a non-object
        # to {} so a hostile initialize can't break the .get() gate.
        caps = params.get("capabilities")
        self._client_capabilities = caps if isinstance(caps, dict) else {}
        # MCP negotiation: echo the client's requested version if we support
        # it, else respond with our latest. The old `< "2025-11-25"`
        # lexicographic check downgraded EVERY pre-latest client -- including
        # modern ones like "2025-06-18" -- all the way to "2024-11-05".
        client_ver = params.get("protocolVersion", "")
        version = client_ver if client_ver in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        capabilities: dict = {
            "tools": {"listChanged": False},
            # Resources: goals/skills exposed as URI-addressable objects
            # for clients (Claude Desktop, Cursor) that support the
            # 2025-11-25 spec. subscribe=True: a client can watch a
            # resource and we push notifications/resources/updated when a
            # tool mutates it (see _flush_resource_updates).
            "resources": {"subscribe": True, "listChanged": False},
            # Prompts: ship templated goal patterns so clients can
            # surface "start a research run" / "plan a trip" without
            # the user typing the prompt themselves.
            "prompts": {"listChanged": False},
            # Elicitation is a *client* capability, not a server one, so it
            # isn't listed here. When the client advertises it we surface a
            # parked ask_user question as a protocol form mid-call (stdio
            # only); otherwise the async ask_user / maverick_answer flow is
            # used unchanged. See _maybe_elicit_open_questions.
        }
        # Tasks (2025-11-25): async, pollable tool execution. Advertised when the
        # transport enables tasks (stdio always; HTTP via MAVERICK_MCP_HTTP_TASKS),
        # so the long-running tools can run on a background worker while the loop
        # stays free to poll/cancel. When a transport has tasks disabled the
        # capability is absent and a `task` field is ignored (spec-compliant).
        if self._tasks_enabled:
            capabilities["tasks"] = {
                "list": {},
                "cancel": {},
                "requests": {"tools": {"call": {}}},
            }
        return {
            "protocolVersion": version,
            "capabilities": capabilities,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def handle_tools_list(self, params: dict) -> dict:
        return {"tools": TOOLS}

    # ---- 2025-11-25 Resources -----------------------------------------

    def handle_resources_list(self, params: dict) -> dict:
        """Expose Maverick state as MCP Resources.

        - maverick://goals          — list of active/recent goals
        - maverick://skills         — installed skills
        """
        resources = [
            {
                "uri": "maverick://goals",
                "name": "All recent goals",
                "mimeType": "application/json",
            },
            {
                "uri": "maverick://skills",
                "name": "Installed skills",
                "mimeType": "application/json",
            },
        ]
        return {"resources": resources}

    def handle_resources_read(self, params: dict) -> dict:
        uri = params.get("uri", "")
        if not uri.startswith("maverick://"):
            raise _ProtocolError(-32602, f"unsupported uri scheme: {uri}")
        path = uri[len("maverick://"):]
        from maverick.world_model import DEFAULT_DB, WorldModel
        wm = WorldModel(DEFAULT_DB)

        if path == "goals":
            data = [
                {"id": g.id, "status": g.status, "title": g.title}
                for g in wm.list_goals()[-20:]
            ]
        elif path == "skills":
            try:
                from maverick.skills import load_skills
                data = [
                    {"name": s.name, "triggers": s.triggers,
                     "tools_needed": s.tools_needed}
                    for s in load_skills()
                ]
            except Exception:
                data = []
        else:
            raise _ProtocolError(-32602, f"unknown resource path: {uri}")

        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(data, indent=2, default=str),
            }],
        }

    # ---- 2025-11-25 Prompts -------------------------------------------

    def handle_resources_subscribe(self, params: dict) -> dict:
        """Track a client's interest in a resource (2025-11-25 subscribe)."""
        uri = params.get("uri", "")
        if uri not in self.RESOURCE_URIS:
            raise _ProtocolError(
                -32602, f"cannot subscribe to unknown resource: {uri!r}"
            )
        self._subscriptions.add(uri)
        return {}

    def handle_resources_unsubscribe(self, params: dict) -> dict:
        """Stop notifying a client about a resource. Idempotent."""
        self._subscriptions.discard(params.get("uri", ""))
        return {}

    def _queue_resource_update(self, tool_name: str) -> None:
        """Record that ``tool_name`` dirtied a resource, to flush once the
        tool result has been sent (result-then-notification ordering)."""
        uri = self._TOOL_RESOURCE.get(tool_name)
        if uri is not None:
            self._pending_updates.append(uri)

    def drain_resource_updates(self) -> list[str]:
        """Pop the queued updates, returning those a client subscribed to.

        Shared by both transports so neither double-emits: stdio sends each as
        a notification (_flush_resource_updates); the HTTP transport yields
        them on the SSE stream after the tool result.
        """
        pending, self._pending_updates = self._pending_updates, []
        return [uri for uri in pending if uri in self._subscriptions]

    def _flush_resource_updates(self) -> None:
        """stdio: emit notifications/resources/updated for subscribed URIs."""
        for uri in self.drain_resource_updates():
            self._send({
                "jsonrpc": "2.0",
                "method": "notifications/resources/updated",
                "params": {"uri": uri},
            })

    def handle_prompts_list(self, params: dict) -> dict:
        return {"prompts": [
            {
                "name": "research_topic",
                "description": "Spawn a research swarm to investigate a topic.",
                "arguments": [
                    {"name": "topic", "description": "What to research",
                     "required": True},
                    {"name": "depth", "description": "shallow / medium / deep",
                     "required": False},
                ],
            },
            {
                "name": "draft_message",
                "description": "Draft an email / message in a given tone.",
                "arguments": [
                    {"name": "recipient", "required": True},
                    {"name": "intent", "required": True},
                    {"name": "tone", "required": False},
                ],
            },
            {
                "name": "compare_options",
                "description": "Compare 2-N options against a criterion list.",
                "arguments": [
                    {"name": "options", "required": True},
                    {"name": "criteria", "required": True},
                ],
            },
        ]}

    def handle_prompts_get(self, params: dict) -> dict:
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        templates = {
            "research_topic": (
                "Spawn a research swarm to investigate: {topic}. "
                "Depth: {depth}. Verify findings before FINAL."
            ),
            "draft_message": (
                "Draft a message to {recipient} with intent: {intent}. "
                "Tone: {tone}. Keep it concise."
            ),
            "compare_options": (
                "Compare these options: {options}. Use criteria: {criteria}. "
                "Build a table; recommend one."
            ),
        }
        if name not in templates:
            raise _ProtocolError(-32602, f"unknown prompt: {name}")
        try:
            text = templates[name].format(**{
                "topic": args.get("topic", ""),
                "depth": args.get("depth", "medium"),
                "recipient": args.get("recipient", ""),
                "intent": args.get("intent", ""),
                "tone": args.get("tone", "professional"),
                "options": args.get("options", ""),
                "criteria": args.get("criteria", ""),
            })
        except KeyError as e:
            raise _ProtocolError(-32602, f"missing argument: {e}") from e
        return {
            "description": f"Maverick prompt: {name}",
            "messages": [{
                "role": "user",
                "content": {"type": "text", "text": text},
            }],
        }

    def handle_tools_call(self, params: dict) -> dict:
        name = params.get("name")
        if name not in _TOOL_NAMES:
            raise _ProtocolError(-32602, f"unknown tool: {name!r}")
        arguments = params.get("arguments", {}) or {}
        tool_spec = next(t for t in TOOLS if t["name"] == name)
        required = tool_spec.get("inputSchema", {}).get("required", []) or []
        missing = [r for r in required if r not in arguments]
        if missing:
            raise _ProtocolError(-32602, f"missing required argument(s) for {name}: {missing}")
        # MCP task augmentation: a tools/call carrying a `task` field runs async
        # when the tool opts in (execution.taskSupport) and this transport has
        # tasks enabled. Returns a CreateTaskResult immediately; the worker runs
        # the tool on an isolated MCPServer instance and the client polls
        # tasks/get|result. When tasks are disabled the field is ignored and the
        # call runs normally, per the spec.
        task_param = params.get("task")
        if isinstance(task_param, dict) and self._tasks_enabled:
            if not _tool_supports_tasks(tool_spec):
                raise _ProtocolError(
                    -32601, f"tool {name!r} does not support task augmentation")
            task = self._task_store().create(name, arguments, task_param)
            # The frozen creation snapshot: a CreateTaskResult always reports the
            # initial `working` status, even if a fast tool already finished.
            return {"task": task.create_result}
        # Side-effectful action tools (start/resume) can't be re-derived, so
        # they stash their structured result here during dispatch; reset per
        # call so a prior call's value can't leak.
        self._structured_override = None
        self._pending_updates = []
        try:
            result = self._dispatch_tool(name, arguments)
        except Exception as e:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
            }
        # Phase 2 elicitation: if the run parked questions and the (stdio)
        # client advertised elicitation, surface them as protocol forms now,
        # record the answers, and resume -- so the caller gets the finished
        # answer in one round trip instead of the start -> answer -> resume
        # dance. A no-op for HTTP clients or those without the capability,
        # leaving the async ask_user / maverick_answer flow unchanged.
        if name in ("maverick_start", "maverick_resume"):
            elicited = self._maybe_elicit_open_questions()
            if elicited is not None:
                result = elicited
        if self._shield is not None:
            verdict = self._shield.scan_output(result)
            if not verdict.allowed:
                return {
                    "isError": True,
                    "content": [{"type": "text", "text": f"⚠ Output blocked: {'; '.join(verdict.reasons)}"}],
                }
        response: dict[str, Any] = {
            "isError": False,
            "content": [{"type": "text", "text": result}],
        }
        # Tools that declare an outputSchema (the read-only query tools) also
        # return structuredContent, so typed cross-language clients get parsed
        # JSON instead of re-parsing the text block. Additive + best-effort:
        # the text block stays for back-compat, and a structured-form failure
        # never fails the call. Structured data is scanned before it is
        # attached, because it may carry fields absent from the text block
        # (e.g. extra skill triggers) that would otherwise bypass output
        # filtering for typed cross-language clients.
        if "outputSchema" in tool_spec:
            try:
                # Action tools stash their structured result during dispatch
                # (can't be re-derived); query tools re-derive from the world
                # model.
                structured = self._structured_override
                if structured is None:
                    structured = self._structured_result(name)
            except Exception:  # pragma: no cover -- structured form is best-effort
                structured = None
            if structured is not None:
                if self._shield is not None:
                    verdict = self._shield.scan_output(
                        json.dumps(structured, default=str, sort_keys=True)
                    )
                    if not verdict.allowed:
                        return {
                            "isError": True,
                            "content": [{"type": "text", "text": f"⚠ Output blocked: {'; '.join(verdict.reasons)}"}],
                        }
                response["structuredContent"] = structured
        # A successful mutating tool dirties a resource; queue the update to
        # flush after the result is sent (run() calls _flush_resource_updates).
        self._queue_resource_update(name)
        return response

    def _dispatch_tool(self, name: str, args: dict) -> str:
        if name == "maverick_start":
            return self._tool_start(args)
        if name == "maverick_status":
            return self._tool_status()
        if name == "maverick_resume":
            return self._tool_resume(args)
        if name == "maverick_answer":
            return self._tool_answer(args)
        if name == "maverick_skill_install":
            return self._tool_skill_install(args)
        if name == "maverick_skills_list":
            return self._tool_skills_list()
        if name == "maverick_fact_set":
            return self._tool_fact_set(args)
        if name == "maverick_facts_get":
            return self._tool_facts_get()
        raise _ProtocolError(-32602, f"unknown tool {name!r}")

    def _structured_result(self, name: str) -> dict | None:
        """Structured form of a query tool's result, matching its outputSchema.

        Re-derives from the world model so the text handlers in _dispatch_tool
        stay untouched; returns None for tools without an outputSchema."""
        from maverick.world_model import WorldModel
        if name == "maverick_status":
            w = WorldModel()
            return {
                "goals": [
                    {"id": g.id, "status": g.status, "title": g.title}
                    for g in w.list_goals()[-10:]
                ],
                "open_questions": [
                    {"id": q.id, "goal_id": q.goal_id, "question": q.question}
                    for q in w.open_questions()
                ],
            }
        if name == "maverick_skills_list":
            from maverick.skills import load_skills
            return {
                "skills": [
                    {"name": s.name, "triggers": list(s.triggers)}
                    for s in load_skills()
                ],
            }
        if name == "maverick_facts_get":
            return {"facts": dict(WorldModel().get_facts())}
        return None

    def _tool_start(self, args: dict) -> str:
        from maverick.budget import Budget
        from maverick.llm import LLM
        from maverick.orchestrator import run_goal_sync
        from maverick.sandbox import build_sandbox
        from maverick.world_model import WorldModel
        title = args["title"]
        description = args.get("description", "")
        if self._shield is not None:
            verdict = self._shield.scan_input(f"{title}\n{description}")
            if not verdict.allowed:
                return f"⚠ Blocked: {'; '.join(verdict.reasons)}"
        # Clamp client-supplied limits to operator ceilings. Over the HTTP
        # transport the budget is 100% client-controlled, so without a cap
        # any authenticated caller could pass max_dollars=10000 and burn the
        # operator's provider spend. Ceilings come from env and default to
        # the schema defaults (so the common case is unchanged); raise them
        # with MAVERICK_MCP_MAX_DOLLARS / _MAX_WALL_SECONDS / _MAX_DEPTH.
        max_dollars = _bounded_float(
            args.get("max_dollars", 5.0),
            default=5.0,
            ceiling=os.environ.get("MAVERICK_MCP_MAX_DOLLARS", 5.0),
        )
        max_wall = _bounded_float(
            args.get("max_wall_seconds", 3600),
            default=3600.0,
            ceiling=os.environ.get("MAVERICK_MCP_MAX_WALL_SECONDS", 3600.0),
        )
        max_depth = _bounded_int(
            args.get("max_depth", 3),
            default=3,
            ceiling=os.environ.get("MAVERICK_MCP_MAX_DEPTH", 3),
        )
        budget = Budget(max_dollars=max_dollars, max_wall_seconds=max_wall)
        world = WorldModel()
        goal_id = world.create_goal(title, description)
        llm = LLM()
        sandbox = build_sandbox()
        answer = run_goal_sync(
            llm, world, budget, goal_id, sandbox=sandbox, max_depth=max_depth,
        )
        self._structured_override = {"goal_id": goal_id, "answer": answer}
        return answer

    def _tool_status(self) -> str:
        from maverick.world_model import WorldModel
        w = WorldModel()
        goals = w.list_goals()
        if not goals:
            return "no goals yet"
        lines = [f"#{g.id} [{g.status}] {g.title}" for g in goals[-10:]]
        for q in w.open_questions():
            lines.append(f"  open question #{q.id} (goal {q.goal_id}): {q.question}")
        return "\n".join(lines)

    def _tool_resume(self, args: dict) -> str:
        from maverick.budget import Budget
        from maverick.llm import LLM
        from maverick.orchestrator import run_goal_sync
        from maverick.sandbox import build_sandbox
        from maverick.world_model import WorldModel
        w = WorldModel()
        goal_id = args.get("goal_id")
        if goal_id is None:
            g = w.active_goal()
            if not g:
                return "no active or blocked goal to resume"
            goal_id = g.id
        else:
            try:
                goal_id = int(goal_id)
            except (TypeError, ValueError):
                raise _ProtocolError(-32602, f"invalid goal_id: {goal_id!r}")
        # Clamp to the same operator ceilings as _tool_start. Over HTTP the
        # budget is client-controlled; a bare Budget() let a resume bypass
        # the MAVERICK_MCP_MAX_* caps that _tool_start enforces.
        max_dollars = _bounded_float(
            args.get("max_dollars", 5.0),
            default=5.0,
            ceiling=os.environ.get("MAVERICK_MCP_MAX_DOLLARS", 5.0),
        )
        max_wall = _bounded_float(
            args.get("max_wall_seconds", 3600),
            default=3600.0,
            ceiling=os.environ.get("MAVERICK_MCP_MAX_WALL_SECONDS", 3600.0),
        )
        max_depth = _bounded_int(
            args.get("max_depth", 3),
            default=3,
            ceiling=os.environ.get("MAVERICK_MCP_MAX_DEPTH", 3),
        )
        budget = Budget(max_dollars=max_dollars, max_wall_seconds=max_wall)
        answer = run_goal_sync(
            LLM(), w, budget, goal_id,
            sandbox=build_sandbox(), max_depth=max_depth,
        )
        self._structured_override = {"goal_id": goal_id, "answer": answer}
        return answer

    def _tool_answer(self, args: dict) -> str:
        from maverick.world_model import WorldModel
        # A bad id is an invalid-params protocol error (-32602), not a tool
        # execution error -- mirror _tool_resume so typed clients can tell them
        # apart (the old `int(...)` surfaced an isError tool result instead).
        try:
            qid = int(args["question_id"])
        except (TypeError, ValueError):
            raise _ProtocolError(-32602, f"invalid question_id: {args.get('question_id')!r}")
        answer = str(args["answer"])
        # An answer to an open question is fed straight back into the agent loop
        # as the user's reply -- equally attacker-influenced as a fact over the
        # network-reachable HTTP transport. Scan it like _tool_fact_set does.
        if self._shield is not None:
            try:
                v = self._shield.scan_input(answer)
                if not getattr(v, "allowed", True):
                    reasons = "; ".join(getattr(v, "reasons", []) or []) or "blocked by Shield"
                    return f"⚠ answer rejected by Shield: {reasons}"
            except Exception:  # pragma: no cover -- fail open (kernel rule 1)
                pass
        w = WorldModel()
        w.answer(qid, answer)
        self._structured_override = {"question_id": qid}
        return f"answered #{qid}"

    def _tool_skill_install(self, args: dict) -> str:
        from maverick.skills import install_skill
        # MCP clients are external by definition, and the HTTP transport is
        # network-reachable behind only a shared bearer token. trusted_local
        # must be False so a bare local-path source (e.g. "/etc/passwd") is
        # rejected -- otherwise an authenticated client gets arbitrary host
        # file read, the exact hole the REST API was hardened against. Local
        # users install skills with `maverick skill install` (trusted there).
        s = install_skill(args["source"], trusted_local=False)
        self._structured_override = {"name": s.name, "path": str(s.path)}
        return f"installed: {s.name} -> {s.path}"

    def _tool_skills_list(self) -> str:
        from maverick.skills import load_skills
        items = load_skills()
        if not items:
            return "no skills installed"
        return "\n".join(f"{s.name}: {', '.join(s.triggers[:3])}" for s in items)

    def _tool_fact_set(self, args: dict) -> str:
        # Facts are concatenated into the orchestrator's system brief on every
        # future run, so a malicious fact set over MCP is a persistent prompt
        # injection. Scan the value before storing (the orchestrator also
        # redacts/re-scans facts at read time as defense-in-depth).
        if self._shield is not None:
            try:
                v = self._shield.scan_input(f"{args['key']}: {args['value']}")
                if not getattr(v, "allowed", True):
                    reasons = "; ".join(getattr(v, "reasons", []) or []) or "blocked by Shield"
                    return f"⚠ fact rejected by Shield: {reasons}"
            except Exception:  # pragma: no cover -- fail open (kernel rule 1)
                pass
        from maverick.world_model import WorldModel
        w = WorldModel()
        w.upsert_fact(args["key"], args["value"])
        self._structured_override = {"key": args["key"]}
        return f"set {args['key']}"

    def _tool_facts_get(self) -> str:
        from maverick.world_model import WorldModel
        w = WorldModel()
        facts = w.get_facts()
        if not facts:
            return "no facts known"
        return "\n".join(f"{k}: {v}" for k, v in facts.items())

    def _send(self, message: dict) -> None:
        line = json.dumps(message) + "\n"
        # Held across write+flush so a worker's status notification can't splice
        # into the middle of the main loop's response line (or vice versa).
        with self._send_lock:
            sys.stdout.write(line)
            sys.stdout.flush()

    def _send_error(self, request_id: Any, code: int, message: str) -> None:
        self._send({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        })

    def _send_result(self, request_id: Any, result: dict) -> None:
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    # ---- server-initiated elicitation (stdio, capability-gated) ----------

    def _client_supports_elicitation(self) -> bool:
        return (
            self._stdio
            and isinstance(self._client_capabilities, dict)
            and "elicitation" in self._client_capabilities
        )

    def _next_elicit_id(self) -> str:
        # String ids namespace our server->client requests so they can never be
        # confused with the client's own (integer) request ids on the wire.
        self._elicit_seq += 1
        return f"elicit-{self._elicit_seq}"

    def _elicit(self, message: str, requested_schema: dict) -> dict | None:
        """Send one elicitation/create and block for the client's response.

        Returns the MCP elicitation result ({"action": ..., "content"?: ...}),
        or None if the client can't elicit, the round trip times out, or the
        client errors -- callers fall back to the async question flow."""
        if not self._client_supports_elicitation():
            return None
        req_id = self._next_elicit_id()
        self._send({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "elicitation/create",
            "params": {"message": message, "requestedSchema": requested_schema},
        })
        return self._await_elicit_response(req_id, _elicit_timeout())

    def _await_elicit_response(self, req_id: str, timeout: float) -> dict | None:
        """Read stdin until the matching elicitation response arrives.

        The client is awaiting our tools/call result, so the only traffic we
        expect meanwhile is that response (plus the odd keep-alive ping). We
        answer pings, treat a cancelled notification as a cancel, and ignore
        anything else rather than re-entering tool dispatch from here."""
        import time as _time
        deadline = _time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                log.warning("elicitation %s timed out", req_id)
                return None
            line = self._readline_with_timeout(remaining)
            if not line:  # timeout (None) or EOF ('')
                return None
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == req_id and "method" not in msg:
                if "error" in msg:
                    return None
                result = msg.get("result")
                return result if isinstance(result, dict) else {}
            method = msg.get("method")
            if method == "ping" and msg.get("id") is not None:
                self._send_result(msg["id"], {})  # keep-alive
            elif method == "notifications/cancelled":
                return None
            # else: a stray message while we wait -- drop it (don't re-enter
            # tool dispatch from inside an in-flight tool call).

    def _readline_with_timeout(self, timeout: float | None) -> str | None:
        """Read a line from stdin, returning None if `timeout` elapses first.

        The timeout only applies when stdin is backed by a real fd (the stdio
        transport); test/StringIO streams fall through to a plain readline."""
        src = sys.stdin
        if timeout is not None and os.name == "posix":
            try:
                fd = src.fileno()
            except (AttributeError, OSError, ValueError):
                fd = None
            if fd is not None:
                import select
                ready, _, _ = select.select([src], [], [], timeout)
                if not ready:
                    return None
        return src.readline()

    def _maybe_elicit_open_questions(self) -> str | None:
        """Resolve questions the just-finished run parked, via elicitation.

        For an elicitation-capable stdio client: elicit each open question for
        the goal, record the answer (shield-screened) through the same path as
        maverick_answer, and resume so the swarm consumes it -- looping until no
        questions remain, the client declines, or a round cap is hit. Returns
        the final (resumed) answer, or None if nothing was elicited (caller
        keeps the original result; the async flow is unchanged)."""
        if not self._client_supports_elicitation():
            return None
        goal_id = (self._structured_override or {}).get("goal_id")
        if goal_id is None:
            return None
        from maverick.world_model import WorldModel
        world = WorldModel()
        max_rounds = _bounded_int(
            os.environ.get("MAVERICK_MCP_MAX_ELICIT_ROUNDS", 8),
            default=8, ceiling=64,
        )
        final_answer: str | None = None
        for _ in range(max_rounds):
            questions = [q for q in world.open_questions() if q.goal_id == goal_id]
            if not questions:
                break
            answered = False
            for q in questions:
                reply = self._elicit_question(q.question)
                if reply is None:
                    return final_answer  # declined / blocked / timed out
                world.answer(q.id, reply)
                answered = True
            if not answered:
                break
            final_answer = self._tool_resume({"goal_id": goal_id})
        return final_answer

    def _elicit_question(self, question: str) -> str | None:
        """Elicit one free-text answer, shield-screening both legs.

        Returns the answer string on accept, or None on decline/cancel, a
        shield block, or an unusable response (caller leaves it parked)."""
        # Outbound: the question is model-influenced text going to the user.
        if self._shield is not None:
            try:
                v = self._shield.scan_output(question)
                if not getattr(v, "allowed", True):
                    log.warning("elicitation prompt blocked by shield")
                    return None
            except Exception:  # pragma: no cover -- fail open (kernel rule 1)
                pass
        result = self._elicit(question, _ELICIT_ANSWER_SCHEMA)
        if not result or result.get("action") != "accept":
            return None
        content = result.get("content")
        if not isinstance(content, dict):
            return None
        answer = content.get("answer")
        if not isinstance(answer, str) or not answer:
            return None
        # Inbound: the answer is fed back into the agent loop -- scan it like
        # _tool_answer does before it becomes the user's reply.
        if self._shield is not None:
            try:
                v = self._shield.scan_input(answer)
                if not getattr(v, "allowed", True):
                    log.warning("elicited answer rejected by shield")
                    return None
            except Exception:  # pragma: no cover -- fail open (kernel rule 1)
                pass
        return answer

    # ---- MCP tasks (stdio: async, pollable tool execution) ----------------

    def _task_store(self):
        if self._tasks is None:
            from .tasks import TaskStore
            self._tasks = TaskStore(
                lambda name, arguments: self._task_runner(name, arguments),
                on_status_change=self._emit_task_status)
        return self._tasks

    # ---- task JSON-RPC methods (shared by stdio + HTTP transports) --------

    def _require_tasks_enabled(self) -> None:
        """Reject tasks/* when this transport hasn't enabled tasks.

        Mirrors "capability absent -> method not supported": a client that
        didn't see the tasks capability shouldn't be calling these, and an
        HTTP deployment with tasks off must not silently spin up a store."""
        if not self._tasks_enabled:
            raise _ProtocolError(-32601, "tasks capability not enabled on this transport")

    def handle_tasks_get(self, params: dict) -> dict:
        self._require_tasks_enabled()
        return self._task_store().get(params.get("taskId"))

    def handle_tasks_result(self, params: dict) -> dict:
        self._require_tasks_enabled()
        return self._task_store().result(params.get("taskId"))

    def handle_tasks_cancel(self, params: dict) -> dict:
        self._require_tasks_enabled()
        return self._task_store().cancel(params.get("taskId"))

    def handle_tasks_list(self, params: dict) -> dict:
        self._require_tasks_enabled()
        return self._task_store().list(params.get("cursor"))

    def _emit_task_status(self, task) -> None:
        """Push a notifications/tasks/status when a task changes status.

        stdio-only: it writes to the bidirectional pipe via _send. The HTTP
        transport has no server->client push channel here, so this is a no-op
        there and HTTP clients learn of completion by polling tasks/get (which
        the spec requires them to support regardless).

        Optional per spec. Runs on the worker thread for completed/failed and
        the main thread for cancelled; _send is locked, so either is safe. No
        related-task _meta: the taskId is already in params."""
        if not self._stdio:
            return
        self._send({
            "jsonrpc": "2.0",
            "method": "notifications/tasks/status",
            "params": task.to_dict(),
        })

    def _task_runner(self, name: str, arguments: dict) -> dict:
        """Execute a task's tool on a FRESH server instance.

        Isolation matters: a background worker must not touch the main server's
        per-call state (``_structured_override`` / ``_pending_updates``) or its
        stdio. The fresh instance has ``_stdio=False``, so it takes the normal
        synchronous path (no elicitation, no resource-update flush) and returns
        the CallToolResult the client later fetches via ``tasks/result``."""
        worker = MCPServer()
        worker._shield = self._shield  # reuse the (stateless) shield scanner
        return worker.handle_tools_call({"name": name, "arguments": arguments})

    def run(self) -> None:
        log.info("Maverick MCP server starting (protocol %s)", PROTOCOL_VERSION)
        # Mark the stdio transport: server-initiated elicitation is only valid
        # here (it needs the bidirectional pipe; the HTTP path can't do a
        # mid-call server->client request). Read via readline() rather than
        # `for line in sys.stdin` so a tool handler can do a nested read for an
        # elicitation response without the iterator's read-ahead buffer
        # swallowing the following messages.
        self._stdio = True
        self._tasks_enabled = True
        while True:
            line = sys.stdin.readline()
            if not line:  # EOF -- client closed the pipe
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                log.warning("bad JSON: %s", e)
                continue
            method = msg.get("method")
            request_id = msg.get("id")
            params = msg.get("params", {}) or {}
            # A client can send `params` as a non-object (list/string/number).
            # Handlers call `params.get(...)`, which would raise AttributeError
            # -- caught below as a scrubbed -32603 "internal error". Coerce to
            # {} so a malformed-params call yields the correct -32602 invalid-
            # params response from the handler instead.
            if not isinstance(params, dict):
                params = {}
            is_notification = request_id is None
            try:
                if method == "initialize":
                    self._send_result(request_id, self.handle_initialize(params))
                elif method == "tools/list":
                    self._send_result(request_id, self.handle_tools_list(params))
                elif method == "tools/call":
                    self._send_result(request_id, self.handle_tools_call(params))
                    # Result first, then any resources/updated notifications.
                    self._flush_resource_updates()
                elif method == "resources/list":
                    self._send_result(request_id, self.handle_resources_list(params))
                elif method == "resources/read":
                    self._send_result(request_id, self.handle_resources_read(params))
                elif method == "resources/subscribe":
                    self._send_result(request_id, self.handle_resources_subscribe(params))
                elif method == "resources/unsubscribe":
                    self._send_result(request_id, self.handle_resources_unsubscribe(params))
                elif method == "prompts/list":
                    self._send_result(request_id, self.handle_prompts_list(params))
                elif method == "prompts/get":
                    self._send_result(request_id, self.handle_prompts_get(params))
                elif method == "tasks/get":
                    self._send_result(request_id, self.handle_tasks_get(params))
                elif method == "tasks/result":
                    self._send_result(request_id, self.handle_tasks_result(params))
                elif method == "tasks/cancel":
                    self._send_result(request_id, self.handle_tasks_cancel(params))
                elif method == "tasks/list":
                    self._send_result(request_id, self.handle_tasks_list(params))
                elif method == "notifications/initialized":
                    pass
                elif method == "ping":
                    if not is_notification:
                        self._send_result(request_id, {})
                else:
                    if not is_notification:
                        self._send_error(request_id, -32601, f"method not found: {method}")
            except TaskError as e:
                if not is_notification:
                    self._send_error(request_id, e.code, e.message)
            except _ProtocolError as e:
                if not is_notification:
                    self._send_error(request_id, e.code, e.message)
            except Exception as e:
                log.exception("handler error")  # full traceback stays server-side
                if not is_notification:
                    # Do NOT ship the traceback to the client: frames/locals/args
                    # can carry secrets (DSNs, tokens, credentialed URLs). Send a
                    # scrubbed one-line message; the server log keeps the detail.
                    try:
                        from maverick.secrets import scrub
                        detail = scrub(f"{type(e).__name__}: {e}")
                    except Exception:  # pragma: no cover
                        detail = type(e).__name__
                    self._send_error(request_id, -32603, f"internal error: {detail}")


def main() -> None:
    """Entry point. Defaults to stdio transport (Claude Desktop /
    Cursor compatible). Pass `--http` for the Streamable HTTP
    transport (hosted Maverick, MCP gateways)."""
    import argparse
    ap = argparse.ArgumentParser(prog="maverick-mcp")
    ap.add_argument("--http", action="store_true",
                    help="Serve over Streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8771)
    args = ap.parse_args()
    if args.http:
        from .http_transport import serve
        serve(host=args.host, port=args.port)
    else:
        MCPServer().run()


if __name__ == "__main__":
    main()
