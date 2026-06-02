"""MCP server for Maverick."""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from typing import Any

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


class MCPServer:
    def __init__(self):
        self._initialized = False
        self._shield = self._build_shield()

    @staticmethod
    def _build_shield():
        try:
            from maverick_shield import Shield
            return Shield.from_config()
        except Exception:
            return None

    def handle_initialize(self, params: dict) -> dict:
        self._initialized = True
        # MCP negotiation: echo the client's requested version if we support
        # it, else respond with our latest. The old `< "2025-11-25"`
        # lexicographic check downgraded EVERY pre-latest client -- including
        # modern ones like "2025-06-18" -- all the way to "2024-11-05".
        client_ver = params.get("protocolVersion", "")
        version = client_ver if client_ver in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                # Resources: goals/skills/facts exposed as URI-addressable
                # objects for clients (Claude Desktop, Cursor) that support
                # the 2025-11-25 spec.
                "resources": {"subscribe": False, "listChanged": False},
                # Prompts: ship templated goal patterns so clients can
                # surface "start a research run" / "plan a trip" without
                # the user typing the prompt themselves.
                "prompts": {"listChanged": False},
                # Elicitation (server-initiated follow-up questions) is not
                # wired yet — clients use the ask_user tool instead. Don't
                # advertise the capability until a handler exists, or
                # 2025-11-25-aware clients will wait on a request we never send.
            },
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
        # Side-effectful action tools (start/resume) can't be re-derived, so
        # they stash their structured result here during dispatch; reset per
        # call so a prior call's value can't leak.
        self._structured_override = None
        try:
            result = self._dispatch_tool(name, arguments)
        except Exception as e:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
            }
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
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    def _send_error(self, request_id: Any, code: int, message: str) -> None:
        self._send({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        })

    def _send_result(self, request_id: Any, result: dict) -> None:
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def run(self) -> None:
        log.info("Maverick MCP server starting (protocol %s)", PROTOCOL_VERSION)
        for line in sys.stdin:
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
                elif method == "resources/list":
                    self._send_result(request_id, self.handle_resources_list(params))
                elif method == "resources/read":
                    self._send_result(request_id, self.handle_resources_read(params))
                elif method == "prompts/list":
                    self._send_result(request_id, self.handle_prompts_list(params))
                elif method == "prompts/get":
                    self._send_result(request_id, self.handle_prompts_get(params))
                elif method == "notifications/initialized":
                    pass
                elif method == "ping":
                    if not is_notification:
                        self._send_result(request_id, {})
                else:
                    if not is_notification:
                        self._send_error(request_id, -32601, f"method not found: {method}")
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
