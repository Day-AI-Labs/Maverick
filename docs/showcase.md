# Built with Lightwork

The showcase wall: a curated list of real projects, automations, and
deployments built on Lightwork. The bar is evidence, not enthusiasm — every
entry links to something a reader can inspect and, ideally, replay.

The table below is **empty by design** until real submissions land. The rows
marked *(example — replace with real submissions)* exist only to show the
expected shape.

## What qualifies

An entry qualifies when all of these hold:

- **It actually runs on Lightwork** — the kernel (`maverick start` /
  `maverick serve`), a channel adapter, the MCP server, or the gRPC API is
  load-bearing, not decorative.
- **It is inspectable**: a public repository, or a public write-up with enough
  config (`config.toml` fragments, goal templates, skills) to reproduce the
  setup.
- **It ships evidence of a real run** (see below).
- **It respects the [trademark policy](../TRADEMARK.md)** — "built with
  Lightwork" is fine (nominative use); naming your product "Lightwork-anything"
  or implying it is the official Lightwork is not.

### Evidence a submission needs

Two artifacts, both required:

1. **A repo or write-up link** showing how the project is wired together.
2. **A replayable trace or run export** from a representative run:
   - a trace directory captured via `MAVERICK_TRACE_DIR` (replayable with
     `maverick replay` / inspectable with `maverick diag`), or
   - a `maverick export` of the run.

   Redact secrets and private data before publishing — the trace is there to
   show the plan tree, tool calls, and cost, not your credentials.

## How to submit

1. Fork the repo and add **one row** to the entries table below (keep the
   table sorted alphabetically by project name).
2. Open a pull request titled `docs: add <project> to the showcase wall`.
   The usual PR rules in [`CONTRIBUTING.md`](../CONTRIBUTING.md) apply.
3. In the PR description, link the evidence artifacts and note anything
   reviewers should know (e.g., which sandbox backend and providers the trace
   was captured with).

Maintainers curate: entries can be declined or later removed if the evidence
link breaks, the project goes stale, or the criteria above stop holding.

## Entries

Column semantics:

| Column | Meaning |
|---|---|
| **Project** | Name, linked to the repo or write-up. |
| **What it does** | One sentence, concrete — what the agent(s) accomplish. |
| **Lightwork surface** | The parts that are load-bearing: kernel, channels, MCP, gRPC, specific tools/skills. |
| **Evidence** | Link to the replayable trace or run export. |
| **Submitted by** | GitHub handle of the submitter. |

| Project | What it does | Lightwork surface | Evidence | Submitted by |
|---|---|---|---|---|
| Example: nightly-dep-triage *(example — replace with real submissions)* | Scheduled goal that triages a repo's dependency alerts and opens draft PRs | Kernel + scheduler, `git_advanced`, GitHub connector | *(link a `MAVERICK_TRACE_DIR` capture)* | *(handle)* |
| Example: support-inbox-swarm *(example — replace with real submissions)* | Email channel deployment that drafts replies for a shared support inbox with human approval | `maverick serve` + Email channel, approval queue | *(link a `maverick export`)* | *(handle)* |
| Example: research-digest-bot *(example — replace with real submissions)* | Telegram bot that runs a weekly research goal and posts a cited digest | Telegram channel, `web_search` + `arxiv` tools, templates | *(link a replay trace)* | *(handle)* |
