# A2A (Agent2Agent)

Lightwork speaks [A2A](https://a2a-protocol.org) v1.0, so other agents can
**discover** this instance and **delegate** long-horizon goals to it. Two
halves:

- **Discovery** — an Agent Card served at `/.well-known/agent-card.json`.
- **Tasks** — a JSON-RPC endpoint at `/a2a/v1` that runs goals and reports
  progress.

Both mount on the dashboard server (`maverick dashboard`, default
`http://127.0.0.1:8765`).

## Enabling

A2A is **off by default** — it's an outward-facing surface. Turn it on in
the installer wizard (the **A2A** step) or directly:

```toml
# ~/.maverick/config.toml
[a2a]
enabled = true
```

or `MAVERICK_A2A_ENABLED=1`. When off, neither the card nor the task
endpoint is registered.

## Auth

The task endpoint spends real provider budget, so it **requires a bearer
token by default**:

```bash
export MAVERICK_A2A_TOKEN=$(openssl rand -hex 32)
```

Callers then send `Authorization: Bearer <token>`. For a trusted
localhost you can run it open with `MAVERICK_A2A_ALLOW_UNAUTHENTICATED=1`
(no token) — don't do that on a public bind.

The Agent Card itself (discovery) is public, like any A2A card.

## Budget caps

Client-supplied budget is always clamped to operator ceilings, so a remote
caller can't run up your provider bill:

| Env var | Default | Caps |
| --- | --- | --- |
| `MAVERICK_A2A_MAX_DOLLARS` | `5.0` | spend per task |
| `MAVERICK_A2A_MAX_WALL_SECONDS` | `3600` | wall-clock per task |
| `MAVERICK_A2A_MAX_DEPTH` | `3` | sub-agent recursion depth |

Every prompt is also screened by the [safety shield](safety.md) when it's
installed (fail-open if not).

## Base URL

The card advertises `…/a2a/v1` as the task URL. Behind a reverse proxy,
set the public address so clients reach the right place:

```bash
export MAVERICK_A2A_BASE_URL=https://agent.example.com
```

## Methods

All requests are JSON-RPC 2.0 `POST`ed to `/a2a/v1`.

### `message/send`

Run a goal to completion and return the final **Task**.

```json
{
  "jsonrpc": "2.0", "id": 1, "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "summarize the latest CPython release notes"}],
      "messageId": "9229e770-767c-417b-a0b0-f0741243c589"
    }
  }
}
```

Result (abridged):

```json
{
  "jsonrpc": "2.0", "id": 1,
  "result": {
    "id": "363422be-…", "contextId": "c295ea44-…", "kind": "task",
    "status": {"state": "completed", "timestamp": "2026-05-31T…"},
    "artifacts": [{"artifactId": "…", "name": "result",
                   "parts": [{"kind": "text", "text": "…"}]}],
    "history": [{"role": "user", "parts": [{"kind": "text", "text": "…"}]}],
    "metadata": {"statusHistory": [
      {"state": "submitted", "timestamp": "…"},
      {"state": "working",   "timestamp": "…"},
      {"state": "completed", "timestamp": "…"}
    ]}
  }
}
```

`status.state` is one of `submitted`, `working`, `completed`, `failed`,
`canceled`, `rejected`. The full transition timeline is under
`metadata.statusHistory`.

### `message/stream`

Same inputs, but the response is an **SSE** stream (`Content-Type:
text/event-stream`). Each event's `data:` is a JSON-RPC response wrapping
one of: the initial **Task**, a **`status-update`**, or an
**`artifact-update`**. The terminal status-update carries `"final":
true`.

```
data: {"jsonrpc":"2.0","id":1,"result":{"kind":"task","status":{"state":"submitted"},…}}

data: {"jsonrpc":"2.0","id":1,"result":{"kind":"status-update","status":{"state":"working"},"final":false,…}}

data: {"jsonrpc":"2.0","id":1,"result":{"kind":"artifact-update","artifact":{…},"lastChunk":true,…}}

data: {"jsonrpc":"2.0","id":1,"result":{"kind":"status-update","status":{"state":"completed"},"final":true,…}}
```

### `tasks/get` · `tasks/cancel`

```json
{"jsonrpc": "2.0", "id": 1, "method": "tasks/get",    "params": {"id": "<task-id>"}}
{"jsonrpc": "2.0", "id": 1, "method": "tasks/cancel", "params": {"id": "<task-id>"}}
```

`tasks/get` returns the Task (including `metadata.statusHistory`).
`tasks/cancel` is best-effort: a task that hasn't finished is marked
`canceled` and its result discarded, but an already in-flight goal isn't
force-killed mid-step.

### Push notifications

Register a webhook and Lightwork `POST`s the Task to it when the task
reaches a terminal state:

```json
{
  "jsonrpc": "2.0", "id": 1, "method": "tasks/pushNotificationConfig/set",
  "params": {
    "taskId": "<task-id>",
    "pushNotificationConfig": {
      "url": "https://client.example/webhook",
      "token": "secure-client-token"
    }
  }
}
```

The delivery includes `Authorization: Bearer <token>` when a `token` is
configured. Read it back with `tasks/pushNotificationConfig/get`.

## Capabilities

The Agent Card advertises what's backed:

```json
"capabilities": {
  "streaming": true,
  "pushNotifications": true,
  "stateTransitionHistory": true
}
```
