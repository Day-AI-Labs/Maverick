# Design Spec: MCP Tasks (async, pollable tool execution)

**Status:** Shipped — stdio (full lifecycle + `notifications/tasks/status` push) **and** HTTP transport (opt-in via `MAVERICK_MCP_HTTP_TASKS`, poll-only); `input_required` deferred · **Roadmap ref:** [`ROADMAP.md`](../ROADMAP.md) → "Current state & gap analysis" (B1, async tasks) · **Spec:** [MCP Tasks 2025-11-25 (experimental)](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks) · **Date:** June 2026

## 1. Problem

`maverick_start` runs the whole swarm to completion synchronously and is
explicitly **long-running**. Over the stdio transport the server is a single
`readline()` loop, so a long start **wedges the connection**: the client can't
check status, cancel, or call another tool until it returns.

MCP **Tasks** (2025-11-25, experimental) is the protocol-native fix. A
task-augmented request returns a `CreateTaskResult` immediately and runs in the
background; the requestor polls `tasks/get` and retrieves the result via
`tasks/result` once terminal — a uniform async pattern across request types.

## 2. What shipped

Server side, **stdio only** (`packages/maverick-mcp/maverick_mcp/`):

- **Capability** — `handle_initialize` advertises
  `tasks: { list:{}, cancel:{}, requests:{ tools:{ call:{} } } }` when the
  transport enabled tasks. A transport-neutral `self._tasks_enabled` flag gates it
  (kept distinct from `self._stdio`, which still gates *elicitation* — that needs
  the bidirectional pipe). `run()` sets it on stdio; `build_app` sets it on HTTP
  from `MAVERICK_MCP_HTTP_TASKS`. When tasks are disabled the capability is absent,
  a `task` field is ignored, and `tasks/*` return `-32601`, per the spec.
- **Tool opt-in** — `maverick_start` and `maverick_resume` (the long ones) declare
  `execution.taskSupport: "optional"` in `tools/list`. A `task`-augmented call to a
  tool that didn't opt in gets `-32601` (method not found).
- **Create** — a `tools/call` carrying `params.task` (`{ "ttl": <ms> }`) returns a
  `CreateTaskResult` (`{ "task": { taskId, status:"working", createdAt,
  lastUpdatedAt, ttl, pollInterval } }`). The status in the ack is a frozen
  creation snapshot, so it's always `working` even if a fast tool finished first.
- **Execution** — the worker runs the tool on a **fresh `MCPServer` instance**
  (`_task_runner`). That isolates the main server's per-call state
  (`_structured_override`, `_pending_updates`) and its stdio: the worker only
  mutates its task record and the one push it emits (below). Status →
  `completed`, or `failed` when the `CallToolResult` has `isError`.
- **Methods** — `tasks/get` (poll), `tasks/result` (blocks until terminal, returns
  exactly the `CallToolResult` with `_meta["io.modelcontextprotocol/related-task"]`),
  `tasks/cancel` (best-effort; `-32602` on an already-terminal task), `tasks/list`
  (opaque-cursor pagination).
- **Notifications** — `notifications/tasks/status` is pushed on each status
  transition (`completed` / `failed` / `cancelled`), carrying the full Task, so a
  client learns of completion without polling. Optional per spec (clients still
  poll). Transport writes go through a send lock, so a worker's push can't splice
  into the middle of the main loop's response line.
- **Store** (`tasks.py`, `TaskStore`) — in-memory registry + a bounded
  `ThreadPoolExecutor`; lazy TTL purge on access; registry size cap; crypto-random
  task ids (no auth context on stdio). Env knobs: `MAVERICK_MCP_TASK_WORKERS`,
  `MAVERICK_MCP_MAX_TASKS`, `MAVERICK_MCP_TASK_TTL_MS`,
  `MAVERICK_MCP_TASK_MAX_TTL_MS`, `MAVERICK_MCP_TASK_POLL_MS`.

## 3. Deferred (intentional slices)

- **`input_required`** — task-driven elicitation (the spec's marquee
  tool-call-needs-elicitation flow). Our elicitation (`specs/mcp-elicitation.md`)
  is synchronous within a foreground tool call; combining it with the async task
  state machine is its own slice (the worker would park its question, flip the task
  to `input_required`, and `tasks/result` on the main thread would drive the
  elicitation + resume). A task that parks a question today simply leaves it for
  the async `maverick_answer` flow.
- **Per-caller task isolation over HTTP** — HTTP task support shipped (opt-in;
  see §6), but the store is **bearer-scoped, not per-caller**: every request
  authenticated with the one `MAVERICK_MCP_TOKEN` shares the same task registry.
  That's correct for single-tenant / trusted-bearer deployments; a multi-tenant
  version that binds each task to a distinct auth context is the follow-up. This is
  why HTTP tasks are opt-in rather than on by default.

## 4. Security / resource notes

- **Isolation** — no auth context on stdio (one client owns the pipe), so task ids
  are `secrets.token_hex(16)`. The single-client assumption is why `tasks.list` is
  safe to advertise here; an HTTP/multi-client version must bind tasks to an auth
  context first.
- **Bounded** — concurrent workers, registry size, and `ttl` are all capped;
  expired tasks are purged. `tasks/result` blocks the main loop until the task is
  terminal, which is acceptable: the client chose to wait (it can poll `tasks/get`
  instead), and the underlying run is budget/wall-clock bounded.

## 5. Test plan (`tests/test_server_tasks.py`)

`TaskStore` lifecycle with a controllable fake runner (no swarm/LLM): create →
working → completed (+ related-task meta); tool-`isError` → failed; runner
exception → failed; cancel transitions + double-cancel `-32602`; cancel-while-
running keeps `cancelled`; unknown id `-32602`; cursor pagination; invalid cursor;
TTL purge. Server wiring: capability advertised only on stdio; `taskSupport` on the
long tools; `CreateTaskResult` shape; `-32601` for augmenting a non-task tool;
`task` ignored over HTTP; runner isolation (main state untouched); and a full
`run()`-loop create-then-result.

HTTP wiring (`tests/test_http_transport.py::TestHTTPTasks`): capability advertised
only when `MAVERICK_MCP_HTTP_TASKS` is set; task-augmented `tools/call` →
`CreateTaskResult`; `tasks/result` blocks (in the dispatch worker thread, not the
event loop) and returns the `CallToolResult` + related-task meta; `tasks/get` /
`tasks/list` / `tasks/cancel`; unknown id → `-32602`; with tasks disabled the
`task` field is ignored (synchronous result) and `tasks/*` → `-32601`.

## 6. HTTP transport (opt-in)

Tasks now work over the Streamable-HTTP transport, gated by `MAVERICK_MCP_HTTP_TASKS`
(default off). The `TaskStore` is transport-agnostic, so the HTTP path reuses it
with no new state machine:

- `build_app` sets `server._tasks_enabled` from the env knob. The store lives on
  the single `server` instance `build_app` wraps, so it persists across requests:
  a task-augmented `tools/call` returns a `CreateTaskResult`, and the client polls
  `tasks/get` / `tasks/result` / `tasks/cancel` / `tasks/list` on subsequent POSTs.
- The four `tasks/*` methods are routed through shared `MCPServer.handle_tasks_*`
  methods (used by both transports — stdio's `run()` now calls them too) that
  self-gate on `_tasks_enabled`. `_error_envelope` maps `TaskError` to its JSON-RPC
  `(code, message)` so an HTTP client sees the same wire codes as stdio.
- `tasks/result` blocks until terminal, but the HTTP dispatch already runs in a
  worker thread (`asyncio.to_thread`), so it never wedges the FastAPI event loop.
- **No push over HTTP:** `notifications/tasks/status` is stdio-only
  (`_emit_task_status` no-ops when not stdio); HTTP clients poll, which the spec
  requires them to support regardless.
- **Off by default** because the store is bearer-scoped (see §3) — opt-in keeps the
  safe single-client default and preserves the prior "ignore the task field"
  behavior byte-for-byte.
