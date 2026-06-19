# Design Spec: MCP Elicitation → Shield/Consent

**Status:** Phases 1–3 shipped — client inbound handler + server outbound form mode + **URL mode** (`server._elicit_url` / `elicit_url_action`: https-only, shield-screened prompt, action-only response so secrets never transit the model) · **Roadmap ref:** [`ROADMAP.md`](../ROADMAP.md) → "Current state & gap analysis" (B1) ([#396](https://github.com/Day-AI-Labs/Lightwork/issues/396)) · **Date:** May 2026

> Proposal for discussion. Stops at interface + integration points; module
> names/handlers should be confirmed against current code at implementation time.

## 1. Problem

MCP **elicitation** lets an MCP **server** request structured input from the
user *mid-request*, routed through the client. Lightwork's MCP server
(`packages/maverick-mcp/maverick_mcp/server.py`) deliberately **does not advertise
the elicitation capability** today — the `handle_initialize` capabilities block
omits it on purpose, with a comment that advertising it without a handler would
make 2025-11-25 clients hang waiting on a request that never comes. Instead, the
server relies on the `ask_user` tool for human-in-the-loop.

Two gaps result:
1. **As a server**, Lightwork can't use the protocol-native input channel; clients
   (Claude Desktop, Cursor) that support elicitation render a poorer experience
   (a tool round-trip instead of a typed form).
2. **As a client** consuming *external* MCP servers (`mcp_client.py`), Lightwork
   does **not** handle incoming `elicitation/create` requests at all — a server
   that elicits gets no response, stalling the call.

The high-value framing: elicitation is the protocol-native **human-in-the-loop /
consent** channel, and Lightwork already has a consent substrate
(`safety/consent.py`, the `approvals` table + dashboard `/approvals`, the
`ask_user` → `questions` flow). Wiring elicitation through that substrate — with
the **shield** screening elicited content — is the right design.

## 2. Goals / non-goals

**Goals**
- G1. **Server side**: advertise + implement elicitation so `ask_user`-style
  prompts surface as protocol forms when the client supports it (fall back to the
  `ask_user` tool when it doesn't — capability-gated).
- G2. **Client side**: handle inbound `elicitation/create` from external MCP
  servers by routing to the same consent/approval UI a tool call would use.
- G3. **Shield-screened**: elicited prompts (server→user) and elicited responses
  (user→server) pass through the shield; the URL-mode rules are enforced.
- G4. **Secrets never transit the model**: support elicitation **URL mode** for
  sensitive flows (OAuth/API keys/payments) so credentials go user↔service
  directly, never through the LLM context.

**Non-goals**
- N1. Replacing `ask_user`/`questions` — elicitation is an *additional*,
  capability-gated surface over the same backing store, not a rewrite.
- N2. Full remote-server OAuth (that's §B2 — but URL-mode elicitation is a
  prerequisite-friendly building block for it).

## 3. The two directions

### 3a. Lightwork as MCP **server** (outbound elicitation)
When a tool/flow needs user input and the connected client advertised
`elicitation` at initialize:
1. Emit `elicitation/create` with a JSON-Schema-typed `requestedSchema` (form
   mode) or a `url` (URL mode).
2. **Shield-screen the prompt** before sending (it's model-influenced text going
   to the user).
3. Persist the pending request in the existing `questions`/`approvals` store so
   the dashboard and other channels stay consistent and it survives a restart.
4. On the client's response, **shield-screen the returned content**, then resume
   the tool. Honor the three elicitation outcomes: `accept` / `decline` /
   `cancel` (decline ≠ cancel — cancel aborts, decline continues without the
   value).
5. **Capability gate**: only advertise + use elicitation when the client declared
   it; otherwise fall back to the `ask_user` tool exactly as today. (This closes
   the "clients hang" hazard the current code comment calls out.)

### 3b. Lightwork as MCP **client** (inbound elicitation)
`mcp_client.py` must handle `elicitation/create` from external servers:
1. Validate the request; enforce **URL-mode rules** — MUST show the full URL,
   MUST NOT pre-fetch it, MUST NOT auto-open it.
2. Route the prompt through the **consent/approval** path (`safety/consent.py` +
   the `approvals` queue), not straight to the LLM — an external server asking
   for input is a trust-boundary event, and the user (or policy) decides.
3. Shield-screen both the server's prompt and the user's response.
4. Return `accept`/`decline`/`cancel` per the user/policy decision; never
   pass-through credentials into model context.

## 4. Integration points (confirm names at impl time)
- `server.py::handle_initialize` — advertise `elicitation` *only* once a handler
  exists; add the send/await path.
- `mcp_client.py` — add an `elicitation/create` request handler (it currently has
  none).
- `safety/consent.py` + `approvals` table + dashboard `/approvals` — the shared
  consent surface both directions route through.
- `tools/ask_user.py` + `questions` — backing store; elicitation is a richer
  transport over the same records.
- Shield (`scan_input`/`scan_output`) — screen elicited prompts + responses.

## 5. Hard parts
- **Capability negotiation**: never send elicitation to a client that didn't
  advertise it (the existing hazard). Gate on the initialize result.
- **URL-mode safety**: the "show full URL, no pre-fetch, no auto-open" rules are a
  shield/consent concern; encode them as hard checks, not guidance.
- **Statelessness/resume**: an elicitation can outlive a transport reconnect;
  persist pending requests (ties into the durable-execution work — a run blocked
  on elicitation is `awaiting_user`).
- **Decline vs cancel semantics**: map cleanly onto the consent outcomes so a
  decline doesn't abort a long run.

## 6. Phasing
- **Phase 1 — client inbound handler. ✅ shipped.** `mcp_client.py` now answers
  every inbound request instead of dropping it: `elicitation/create` is resolved
  by policy (`MAVERICK_MCP_ELICITATION` — default `decline`, or `cancel` /
  `prompt`) after a `scan_remote_content` floor-scan of the prompt, with `prompt`
  mode collecting typed input off the event loop through `require_consent`; any
  other inbound method (`roots/list`, `sampling/createMessage`, …) gets a clean
  `-32601` instead of stalling the server. The client advertises the
  `elicitation` capability now that a handler exists. Elicited content is
  resolved entirely in the transport and never passes through the model context,
  and no URL in the request is ever fetched/auto-opened. Code:
  `mcp_client.py::_handle_inbound_request` / `_handle_elicitation`; tests:
  `tests/test_mcp_elicitation.py`.
- **Phase 2 — server outbound (form mode). ✅ shipped.** When a swarm run parks
  an `ask_user` question and the connected **stdio** client advertised the
  `elicitation` capability (captured at `handle_initialize`), the server surfaces
  the question as an `elicitation/create` form mid-call, records the answer
  through the same `world.answer` path as `maverick_answer`, and resumes the goal
  — collapsing the `start → answer → resume` dance into one round trip. Both legs
  are shield-screened (`scan_output` on the prompt, `scan_input` on the answer),
  it's capability- **and** transport-gated (HTTP and non-capable clients fall back
  to the async flow, byte-for-byte unchanged), the synchronous round trip reads
  the response on a nested `readline` (with a `select` timeout on real stdio), and
  outbound request ids are namespaced (`elicit-N`) so they can't collide with the
  client's. Code: `server.py::_maybe_elicit_open_questions` / `_elicit` /
  `_await_elicit_response`; tests: `tests/test_server_elicitation.py`. Not yet
  done: eliciting *arbitrary* tool flows (only the parked-question path), and the
  `approvals`-table/dashboard surface (answers flow through `questions`).
- **Phase 3 — URL mode** both directions (the secrets-never-transit-model path);
  dovetails with §B2 remote-server OAuth.

## 7. Test plan
- Client: an external server emits `elicitation/create`; assert it surfaces in the
  approvals queue, the shield screens it, and accept/decline/cancel are returned
  correctly; URL-mode request is shown-but-not-fetched/opened.
- Server: with an elicitation-capable client, `ask_user` surfaces as a form and
  resumes on response; with a non-capable client, it falls back to the `ask_user`
  tool (no hang).
- Shield: a malicious elicited prompt/response is screened on both legs.

## 8. Open questions
1. Should inbound elicitation default to **auto-decline** under the strict safety
   profile (server can't prompt the user without explicit opt-in)?
2. Do non-interactive deployments (channel/headless) answer elicitation from
   policy/config, or always decline?
3. One unified consent record type for tool-consent + elicitation, or separate?
