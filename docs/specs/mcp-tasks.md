# Design Spec: MCP Tasks (async, pollable tool execution)

**Status:** Phase 1 shipped (stdio server, basic lifecycle); `input_required` + status-notifications + HTTP deferred · **Roadmap ref:** [`ROADMAP.md`](../ROADMAP.md) → "Current state & gap analysis" (B1, async tasks) · **Spec:** [MCP Tasks 2025-11-25 (experimental)](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks) · **Date:** June 2026

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
  `tasks: { list:{}, cancel:{}, requests:{ tools:{ call:{} } } }`, but only on
  stdio (`self._stdio`). The HTTP transport doesn't advertise it, so per the spec
  a `task` field there is ignored and the call runs normally.
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
  mutates its task record and **never writes the transport**, so the main loop
  stays the sole writer. Status → `completed`, or `failed` when the
  `CallToolResult` has `isError`.
- **Methods** — `tasks/get` (poll), `tasks/result` (blocks until terminal, returns
  exactly the `CallToolResult` with `_meta["io.modelcontextprotocol/related-task"]`),
  `tasks/cancel` (best-effort; `-32602` on an already-terminal task), `tasks/list`
  (opaque-cursor pagination).
- **Store** (`tasks.py`, `TaskStore`) — in-memory registry + a bounded
  `ThreadPoolExecutor`; lazy TTL purge on access; registry size cap; crypto-random
  task ids (no auth context on stdio). Env knobs: `MAVERICK_MCP_TASK_WORKERS`,
  `MAVERICK_MCP_MAX_TASKS`, `MAVERICK_MCP_TASK_TTL_MS`,
  `MAVERICK_MCP_TASK_MAX_TTL_MS`, `MAVERICK_MCP_TASK_POLL_MS`.

## 3. Deferred (intentional slices)

- **`input_required`** — task-driven elicitation (the spec's marquee
  tool-call-needs-elicitation flow). Our elicitation (`specs/mcp-elicitation.md`)
  is synchronous within a foreground tool call; combining it with the async task
  state machine is its own slice. A task that parks a question today simply leaves
  it for the async `maverick_answer` flow.
- **`notifications/tasks/status`** — optional server→client push. We don't send it;
  requestors poll (which the spec requires them to support regardless), keeping all
  transport writes on the main thread.
- **HTTP transport** — tasks are stdio-only for now. The HTTP path already returns
  results synchronously per request; task support there (with its own registry and
  auth-context binding for multi-client isolation) is a follow-up.

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
