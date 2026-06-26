# Decision: adopt A2A's Agent Card; cut the homegrown ACD

**Status:** Decided — adopt A2A, retire ACD · **Roadmap ref:** [`ROADMAP.md`](../ROADMAP.md) → "Current state & gap analysis" (B3) · **Date:** June 2026

## The question

Roadmap **B3** was an open decision: should Lightwork describe its agent
capabilities with the open **A2A (Agent2Agent) Agent Card**, or with a
**homegrown ACD** (Agent Capability Descriptor) — a Lightwork-specific spec that
the roadmap had penciled in as `docs/specs/acd.md` (Q4 2026), then `ACD spec
v1.0` (2027 H2) and `v1.1` (2028 H2)?

## Decision

**Adopt the A2A Agent Card. Cut the homegrown ACD entirely.** Do not author
`docs/specs/acd.md`; remove ACD as a roadmap workstream and fold its only real
goal — "let other agents discover what Lightwork can do" — into A2A, which already
ships.

## Why

1. **A2A is an open standard, ACD would be a private one.** A2A is a Linux
   Foundation protocol (v1.0; 150+ orgs; production in 2026). Its foundational
   primitive is the Agent Card, a JSON document at
   `/.well-known/agent-card.json`. A homegrown ACD competes with a standard the
   rest of the ecosystem is converging on — the classic "15th competing
   standard" trap. Interop is the entire point of a capability descriptor;
   inventing our own forfeits it.

2. **A2A is already implemented; ACD is vapor.** The discovery half shipped:
   `packages/maverick-core/maverick/a2a.py` (`build_agent_card()` returns the
   v1.0 shape — `protocolVersion`, `name`, `url`, `version`, `provider`,
   `capabilities`, `skills`; `mount()` serves it at `/.well-known/agent-card.json`
   and the `/.well-known/agent.json` alias, opt-in via `MAVERICK_A2A_ENABLED` /
   `[a2a] enabled`). The delegation half shipped too:
   `a2a_tasks.py` wires `POST /a2a/v1` with `message/send`, `message/stream`
   (SSE), `tasks/*`, bearer auth, budget caps, and status-history. Docs:
   [`docs/a2a.md`](../a2a.md). Tests: `tests/test_a2a_agent_card.py`,
   `tests/test_a2a_tasks.py`. ACD has no code and no spec — nothing to keep.

3. **It doesn't overlap MCP — it complements it.** Three layers, three jobs:
   - **MCP** (`maverick mcp`): "what *tools* can a connected client call?" —
     fine-grained, with input/output schemas. Already shipped.
   - **A2A** (`/.well-known/agent-card.json` + `/a2a/v1`): "what is this *agent*,
     and how do I delegate a goal to it?" — coarse skills + a task lifecycle.
     Already shipped.
   - **ACD**: would have answered the *same* question A2A's Agent Card answers,
     in a non-standard way. It is redundant with A2A, not additive.

4. **The skills in the card are deliberately coarse and curated.** A2A "skills"
   (`a2a._SKILLS`: `execute-goal`, `research`, `code`) are agent-level capability
   descriptors, intentionally *distinct* from the fine-grained MCP `TOOLS` list.
   Do **not** auto-derive the card's skills from the MCP tool list — the two
   surfaces describe different altitudes, and conflating them produces a noisy,
   wrong card. No "Agent Card emitter" is needed; `build_agent_card()` is already
   the single source.

## What this changes on the roadmap

- **B3 row:** `⬜ decision` → `✅ decision: adopt A2A's Agent Card; ACD cut`.
- **Q4 2026 Ecosystem — "ACD spec v0.1 (`docs/specs/acd.md`)":** cut; superseded
  by the shipped A2A Agent Card. Annotated in place pointing here.
- **2027 H2 / 2028 H2 Ecosystem — "ACD spec v1.0 / v1.1 / ACD interop tests":**
  superseded by this decision. Any future "capability descriptor" work tracks
  A2A's own versioning, not a parallel ACD line. (Left in the far-future lists as
  historical context; this doc is the record of record.)

## What remains open (small, non-blocking)

- **Wizard knob for A2A.** A2A is enable-able via `MAVERICK_A2A_ENABLED` / `[a2a]`
  today, but there's no installer-wizard step (CLAUDE.md #6). A small follow-up:
  a `pick_a2a()`-style toggle already exists in the wizard — wire its output into
  the emitted config so non-technical users can opt in. (Outward-facing surface,
  so it stays off by default.)
- **Cross-agent card federation** (discovering *other* agents' cards) tracks the
  2027 H1 ecosystem cluster, not ACD.
