"""MCP server for Maverick."""
from __future__ import annotations

import json
import logging
import sys
import traceback
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
SERVER_NAME = "maverick"
SERVER_VERSION = "0.2.0"


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
    },
    {
        "name": "maverick_status",
        "description": "List recent goals and any open questions.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "maverick_resume",
        "description": "Resume a paused goal by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"goal_id": {"type": "integer"}},
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
    },
    {
        "name": "maverick_skill_install",
        "description": "Install a SKILL.md from a URL or gh:org/repo[:path].",
        "inputSchema": {
            "type": "object",
            "properties": {"source": {"type": "string"}},
            "required": ["source"],
        },
    },
    {
        "name": "maverick_skills_list",
        "description": "List installed / distilled skills.",
        "inputSchema": {"type": "object", "properties": {}},
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
    },
    {
        "name": "maverick_facts_get",
        "description": "Get all known facts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_TOOL_NAMES = {t["name"] for t in TOOLS}


class MCPServer:
    def __init__(self):
        self._initialized = False

    def handle_initialize(self, params: dict) -> dict:
        self._initialized = True
        # Negotiate down if the client only speaks the older spec.
        client_ver = params.get("protocolVersion", "")
        version = PROTOCOL_VERSION
        if client_ver and client_ver < "2025-11-25":
            version = PROTOCOL_VERSION_FALLBACK
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
                # Elicitation: server can ask the user a follow-up question
                # (replaces our ask_user tool in 2025-11-25-aware clients).
                # We declare it; the actual call falls back to tool-result
                # when the client doesn't support it.
                "elicitation": {},
            },
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def handle_tools_list(self, params: dict) -> dict:
        return {"tools": TOOLS}

    # ---- 2025-11-25 Resources -----------------------------------------

    def handle_resources_list(self, params: dict) -> dict:
        """Expose Maverick state as MCP Resources.

        - maverick://goals/{id}     — single goal status + result
        - maverick://goals          — list of active/recent goals
        - maverick://skills         — installed skills
        - maverick://facts          — known facts about the user
        """
        try:
            from maverick.world_model import DEFAULT_DB, WorldModel
            wm = WorldModel(DEFAULT_DB)
            goals = wm.list_goals()[-20:]
        except Exception:
            goals = []
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
            {
                "uri": "maverick://facts",
                "name": "Facts about the user",
                "mimeType": "application/json",
            },
        ]
        for g in goals:
            resources.append({
                "uri": f"maverick://goals/{g.id}",
                "name": f"goal #{g.id} ({g.status}): {g.title[:60]}",
                "mimeType": "application/json",
            })
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
        elif path.startswith("goals/"):
            try:
                gid = int(path.split("/", 1)[1])
            except ValueError as e:
                raise _ProtocolError(-32602, f"bad goal id in {uri}") from e
            g = wm.get_goal(gid)
            if g is None:
                raise _ProtocolError(-32602, f"no such goal: {uri}")
            data = {
                "id": g.id, "status": g.status, "title": g.title,
                "description": g.description, "result": g.result,
            }
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
        elif path == "facts":
            data = wm.get_facts()
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
        try:
            result = self._dispatch_tool(name, arguments)
        except Exception as e:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
            }
        return {
            "isError": False,
            "content": [{"type": "text", "text": result}],
        }

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

    def _tool_start(self, args: dict) -> str:
        from maverick.budget import Budget
        from maverick.llm import LLM
        from maverick.orchestrator import run_goal_sync
        from maverick.sandbox import build_sandbox
        from maverick.world_model import WorldModel
        title = args["title"]
        description = args.get("description", "")
        budget = Budget(
            max_dollars=float(args.get("max_dollars", 5.0)),
            max_wall_seconds=float(args.get("max_wall_seconds", 3600)),
        )
        world = WorldModel()
        goal_id = world.create_goal(title, description)
        llm = LLM()
        sandbox = build_sandbox()
        return run_goal_sync(
            llm, world, budget, goal_id, sandbox=sandbox,
            max_depth=int(args.get("max_depth", 3)),
        )

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
        from maverick.world_model import WorldModel
        w = WorldModel()
        goal_id = args.get("goal_id")
        if goal_id is None:
            g = w.active_goal()
            if not g:
                return "no active or blocked goal to resume"
            goal_id = g.id
        return run_goal_sync(LLM(), w, Budget(), int(goal_id))

    def _tool_answer(self, args: dict) -> str:
        from maverick.world_model import WorldModel
        w = WorldModel()
        w.answer(int(args["question_id"]), str(args["answer"]))
        return f"answered #{args['question_id']}"

    def _tool_skill_install(self, args: dict) -> str:
        from maverick.skills import install_skill
        s = install_skill(args["source"], trusted_local=True)
        return f"installed: {s.name} -> {s.path}"

    def _tool_skills_list(self) -> str:
        from maverick.skills import load_skills
        items = load_skills()
        if not items:
            return "no skills installed"
        return "\n".join(f"{s.name}: {', '.join(s.triggers[:3])}" for s in items)

    def _tool_fact_set(self, args: dict) -> str:
        from maverick.world_model import WorldModel
        w = WorldModel()
        w.upsert_fact(args["key"], args["value"])
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
                log.exception("handler error")
                if not is_notification:
                    self._send_error(
                        request_id, -32603,
                        f"internal error: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                    )


def main() -> None:
    MCPServer().run()


if __name__ == "__main__":
    main()
