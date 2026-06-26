# Self-learning

> **Scope note:** this page covers *capability acquisition* (installing
> skills/tools on demand). The broader learning system — experience
> consolidation (`maverick dream`), department memory, hindsight
> regression detection, learning snapshots/rollback, and the fleet memory
> plane — is catalogued in [`FEATURES.md`](./FEATURES.md) under
> *Dreaming*, *Hindsight engine*, and *Fleet memory*.

When you ask Lightwork to do something it doesn't yet have the capability
for, it can **acquire the capability itself** — install a skill, drive a
REST API, or generate a brand-new tool — instead of giving up. It can also
*propose* a curated MCP server, but only one from the hash-pinned catalog and
only after you explicitly approve it (see "MCP-server acquisition" below).

It's **off by default**. The kernel runs unchanged unless you turn it on,
because "create a tool" means generating and executing fresh code in your
process — an explicit trust decision.

## Enabling it

In the installer wizard, answer **yes** to "Enable self-learning?", or
edit `~/.maverick/config.toml`:

```toml
[self_learning]
enable           = true  # master switch (default false)
preflight        = true  # pre-acquire likely skills before each run
create_tools     = true  # let the agent generate + run new tools
allow_mcp_acquisition = false  # let the agent propose catalog MCP servers (off)
max_acquisitions = 5     # cap on auto-acquisitions per run
```

> `allow_mcp_acquisition` is a **separate, higher-trust** opt-in that ships off
> even when the rest of self-learning is on. It re-enables (safely) the
> capability removed in #392: see "MCP-server acquisition" below. Set it via
> config or `MAVERICK_ALLOW_MCP_ACQUISITION=1`. An older config that still sets
> the retired `add_mcp_servers` key is tolerated and ignored.

Or for a one-off run: `MAVERICK_SELF_LEARNING=1 maverick start "..."`.
The env var also force-*disables* (`MAVERICK_SELF_LEARNING=0`) over config.

## How it works

There are two triggers, and they share one acquisition engine.

**1. Pre-flight (before the run).** When `preflight` is on, the
orchestrator makes one cheap LLM call to identify specialised
capabilities the goal may need, searches the federated
[catalog](plugins.md) for matching **skills**, and installs the best
hash-verified match. Those steps are already in context on the agent's
first turn.

**2. In-loop `learn_capability` tool (during the run).** When the agent
realises mid-task that it's missing something, it calls this tool:

| op | what it does |
| --- | --- |
| `search` | find catalog skills / MCP servers / plugins matching a need, plus already-loaded tools |
| `acquire_skill` | install a catalog skill by name (hash-verified) and inject its steps immediately |
| `add_mcp_server` | add a catalog MCP server **by name** — command + SHA come from the curated, hash-pinned catalog entry (no free-text command), gated behind `allow_mcp_acquisition` **and** operator approval (see below). Off by default. |
| `create_tool` | generate a Python tool from a description, validate it, and register it live |
| `find_api` | discover an API's OpenAPI spec (probe a `base_url` or web-search), list its operations, and drive it via the built-in `openapi_runner` (no new code) |

Anything acquired is registered into the **live** tool registry, so the
agent can use it on its very next turn — no restart.

**3. At pack birth (the agent factory).** The same acquisition engine also
runs *ahead* of any run, when a new specialist pack is created. Instead of an
agent discovering a capability hole mid-task, the
**agent factory** closes it at creation time:
`provision.analyze_profile` diffs a draft pack's workflow and declared
`allow_tools` against the installed skills and the live tool registry
(`tools.base_tool_names()`), surfaces the gaps at the approval gate, and on
approval `provision.apply_plan` reuses the **same governed paths** —
`self_learning.acquire_skill` for catalog skills (hash-pinned) and
`self_learning.write_generated_tool` for the missing declared tools
(stdlib-only, import-validated out-of-host, consent-gated). Wired into
`maverick onboard` and the `maverick learn-demo` (programming-by-demonstration)
flow. Provisioning **never widens** the pack's already-clamped envelope: it
only satisfies tools already inside `allow_tools` and installs skills (which
carry no tool grant of their own). It's gated by the same `[self_learning]
enable` switch plus a `provision_packs` sub-knob (default on once self-learning
is accepted) and the same human approval `save_profile` requires.

## What persists

- **Skills** install to `~/.maverick/skills/*.md` (the normal skill store).
- **MCP servers** are only written when `allow_mcp_acquisition` is on **and**
  you approve the specific server. The approved server is persisted as a normal
  `[mcp_servers.<name>]` block (with its `pin_sha256`) so it also loads on the
  next run. Operators can still add trusted blocks by hand.
- **Generated tools** are written to `~/.maverick/generated_tools/*.py`.
  When self-learning is enabled, the kernel loads them as first-class
  tools at the start of every run.
- A ledger of everything learned is appended to
  `~/.maverick/learned.ndjson`. List it with:

  ```bash
  maverick learned
  ```

## Safety

Self-learning honors the same chokepoints as the rest of the kernel:

- **Off by default** — no extra persisted state until you opt in.
- **Budget** — the generation LLM call is metered against the run's
  [budget](configuration.md); `max_acquisitions` bounds churn per run.
- **Static audit (enforced, not just requested)** — generated tool source is
  parsed and checked against a stdlib-only allowlist *before* it is imported:
  disallowed imports (`os`, `subprocess`, `socket`, …), banned builtins
  (`eval`/`exec`/`open`/`__import__`), and the dunder sandbox-escape chain are
  rejected. The `TOOL_AUTHOR_SYSTEM` prompt *asks* for stdlib-only; this layer
  *enforces* it. The source is re-audited every time a persisted tool is
  loaded, so on-disk tampering is caught too. This is a guardrail, not a true
  sandbox (a determined adversary with `getattr` tricks could still evade an
  AST allowlist).
- **Out-of-host import validation** — the check that a generated module
  imports cleanly and exposes a valid `make_tool()` runs in a **short-lived
  child process** (a `sandbox.exec()` child when the call site has a backend,
  otherwise a timed plain subprocess), never the kernel interpreter. So an
  import-time side-effect — or anything the static audit missed — can't touch
  the live process at validation time.
- **Consent gate at first registration** — before a newly generated tool is
  persisted or registered, it goes through the same consent queue as other
  risky actions (`require_consent`, action `register-generated-tool`). Denied,
  auto-deny, or a non-interactive context under a gating consent mode →
  **not persisted, not registered**. Reloads of an already-approved tool do
  **not** re-prompt.
- **Shield** — generated tool source is also scanned through the
  [Shield](safety.md) (when installed) before it is ever imported;
  blocked source is rejected.
- **Catalog trust** — `acquire_skill` only installs curated,
  SHA-256-pinned catalog entries, so a fetched skill must match the
  index byte-for-byte.
- **MCP subprocess safety** — see "MCP-server acquisition" below: the agent
  can never launch a model-supplied command. Only catalog-pinned, SHA-verified
  servers, and only after explicit operator approval.

### Trust model for generated tools

A generated tool is, in order: **AST-constrained** to stdlib-only,
**import-validated out-of-host** in a child process, and **consent-gated at
first registration**. After it is approved and persisted, its `fn` runs
**in-process at runtime** under the explicit `create_tools` opt-in — the AST
gate and out-of-host check bound *validation*, but execution of an approved
tool still happens in the kernel process. That residual in-process trust is
deliberate and documented; an **out-of-process tool runtime** (running each
generated tool's `fn` in its own sandbox on every call) is the planned future
hardening and is intentionally out of scope here.

Because of that, enabling `create_tools` is a genuine trust decision. Leave it
off (or set `create_tools = false`) if you only want the safer acquisition
paths (skills / APIs). For untrusted goals, also run with a real `[sandbox]`
backend (docker/podman): the out-of-host import check is then a true sandbox,
not just process isolation.

## Self-improving factory

Pack-birth provisioning produces a signal nothing else captures: which
capabilities the factory's drafts keep *missing* — a tool a finance pack kept
declaring but the factory kept omitting, a skill a workflow kept needing, an
envelope a human kept having to widen at approval. `factory_learning.py` closes
that loop back onto *generation quality* instead of letting it die in a log.

Provisioning/approval gaps are attributed to the pack's suite and signal, mined
into proposer **corrections**, and each is promoted through the **existing
`SelfImprovementController`** — on the `prompt` rung, since the correction is
guidance text that widens no capability (so it needs only the evidence and
calibration gates, not the escalation proof / human sign-off a capability
change would). A promoted correction is folded into future pack generation via
`augment_system_prompt`, scope-matched per suite, so the next pack the factory
writes already knows the pattern the last several taught it.

It's **off by default and byte-identical to before while off** — recording
writes nothing, mining reads nothing, and `augment_system_prompt` returns the
base prompt unchanged. Turn it on with `[self_improvement] enable` plus the
`factory_learning` sub-knob (default on once self-improvement is accepted), or
force it for one run with `MAVERICK_FACTORY_LEARNING=1`. The ledger is bounded
(oldest rows roll off), outcome text is secret-redacted before it's persisted,
and — like provisioning — a correction is never a tool grant, so it widens no
pack's envelope. Mine and preview the corrections without applying them:

```bash
maverick factory-learn --dry-run
```

## MCP-server acquisition

PR #378 once let the agent add and hot-start an MCP server from a
model-supplied `command`/`args`. PR #392 disabled that: a model that can pick
the command line is a remote-code-execution / supply-chain hole. #422 restores
the *capability* without re-opening the hole, by closing two gaps at once —
**no free-text command, and an operator in the loop**:

1. **Catalog-pinned only.** `op=add_mcp_server` takes a catalog **name**, not a
   command. The command, args, and `pin_sha256` come from the curated `mcp`
   catalog entry (resolved read-only via the federated index). A request that
   carries a free-text `command`/`args` is rejected outright, and a name with
   no catalog entry is rejected too.
2. **Explicit operator consent.** Before anything is persisted or started, the
   proposal goes through the same consent queue as other risky actions
   (`require_consent`), but silent `auto-approve` mode is not accepted for this
   high-trust path. Use a prior ledger grant, `MAVERICK_CONSENT_MODE=dashboard`
   (parks in the approvals queue for `maverick approve`), or `ask` mode on a
   TTY. Denied, auto-deny, default auto-approve without a ledger grant, or a
   non-interactive context → **not persisted, not started**.
3. **Existing spec defenses.** The pinned command still goes through
   `MCPServerSpec` validation (shell-metacharacter / NUL / newline rejection)
   and `pin_sha256` is verified against the on-disk binary at launch
   (CVE-2026-30615). None of those defenses are weakened.

The launch path is unchanged: catalog-pinned entry → operator-approved →
the same validated `MCPServerSpec` → the same `MCPClient.start()` the static
config loader uses. There is no new subprocess spawn.

The whole path is **off by default** and gated behind `allow_mcp_acquisition`
(or `MAVERICK_ALLOW_MCP_ACQUISITION=1`) — independent of the self-learning
master switch. With it off, `op=add_mcp_server` returns the same informative
"disabled" error as before.

> Note: catalog `mcp` entries encode their launch command in the entry's
> `source` field (e.g. `source = "npx -y @scope/server"`); Lightwork splits it
> into `command` + `args`. The entry's `sha256` becomes the server's
> `pin_sha256`.
