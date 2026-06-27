# Lightwork — Product User Stories

> **1,000 user stories** across **20 epics** and **14 personas**, spanning the full Lightwork platform — from running goals and authoring agents to governance, self-learning, multi-tenancy, and integrations.

**Story format:** `US-XXXX (Persona — Priority) — As a <persona>, I want <capability>, so that <benefit>.`

**Priority key:** `P0` must-have · `P1` should-have · `P2` could-have · `P3` nice-to-have

**Personas:** Operator · Team Lead · Agent Author · Platform Admin · Compliance Officer · Security Engineer · FinOps Owner · Tenant Admin · Developer/Integrator · Executive · Knowledge Steward · Requester (non-technical) · SRE · External Auditor

## Contents

1. [Epic 01 — Goals & Orchestration](#epic-01--goals--orchestration) — US-0001–US-0050
2. [Epic 02 — Chat & Requests](#epic-02--chat--requests) — US-0051–US-0100
3. [Epic 03 — The Workforce: Agents & Roles](#epic-03--the-workforce-agents--roles) — US-0101–US-0150
4. [Epic 04 — Agent Authoring & Packs](#epic-04--agent-authoring--packs) — US-0151–US-0200
5. [Epic 05 — Workflows & Automations](#epic-05--workflows--automations) — US-0201–US-0250
6. [Epic 06 — Graph & Plan Visualization](#epic-06--graph--plan-visualization) — US-0251–US-0300
7. [Epic 07 — Fleets, Projects & Deliverables](#epic-07--fleets-projects--deliverables) — US-0301–US-0350
8. [Epic 08 — Observability & Oversight](#epic-08--observability--oversight) — US-0351–US-0400
9. [Epic 09 — Spend & FinOps](#epic-09--spend--finops) — US-0401–US-0450
10. [Epic 10 — Providers & Models](#epic-10--providers--models) — US-0451–US-0500
11. [Epic 11 — Benchmarks & Evaluation](#epic-11--benchmarks--evaluation) — US-0501–US-0550
12. [Epic 12 — Self-Learning (Dream / Hindsight / Proof)](#epic-12--self-learning-dream--hindsight--proof) — US-0551–US-0600
13. [Epic 13 — Skills & Distillation](#epic-13--skills--distillation) — US-0601–US-0650
14. [Epic 14 — Approvals & Permissions](#epic-14--approvals--permissions) — US-0651–US-0700
15. [Epic 15 — Safety & Shield](#epic-15--safety--shield) — US-0701–US-0750
16. [Epic 16 — Compliance, Audit & Replay](#epic-16--compliance-audit--replay) — US-0751–US-0800
17. [Epic 17 — Compartments & Multi-Tenancy](#epic-17--compartments--multi-tenancy) — US-0801–US-0850
18. [Epic 18 — Agent Trust & Fleet Memory](#epic-18--agent-trust--fleet-memory) — US-0851–US-0900
19. [Epic 19 — Integrations: Channels, MCP, Tools, Plugins & SDK](#epic-19--integrations-channels-mcp-tools-plugins--sdk) — US-0901–US-0950
20. [Epic 20 — Admin: Setup, Settings, Users & Knowledge](#epic-20--admin-setup-settings-users--knowledge) — US-0951–US-1000


---

## Epic 01 — Goals & Orchestration

- **US-0001** *(Operator — P0)* — As an Operator, I want to start a goal with `maverick start "migrate the billing service to Postgres"`, so that the platform accepts my intent and returns a goal id I can track.
- **US-0002** *(Operator — P0)* — As an Operator, I want `maverick start` to automatically decompose my goal into a plan tree of researcher, coder, and verifier sub-agents, so that I don't have to hand-author the task breakdown.
- **US-0003** *(Team Lead — P0)* — As a Team Lead, I want sibling sub-agents in the plan tree to run in parallel where there are no dependencies, so that goals complete faster than a serial pipeline would allow.
- **US-0004** *(Operator — P0)* — As an Operator, I want `maverick monitor` to stream live updates of every running sub-agent's state and current step, so that I can watch a goal progress without re-polling.
- **US-0005** *(Operator — P0)* — As an Operator, I want `maverick status <goal-id>` to print the goal's current lifecycle state (active/blocked/done/cancelled/pending), so that I can check where it stands at a glance.
- **US-0006** *(Operator — P0)* — As an Operator, I want `maverick status` with no id to list all my goals and their states, so that I can survey my whole workload in one command.
- **US-0007** *(Requester (non-technical) — P1)* — As a non-technical Requester, I want to describe a goal in plain language and have it decomposed for me, so that I can request work without writing a plan.
- **US-0008** *(Operator — P0)* — As an Operator, I want a goal to enter the `blocked` state when a sub-agent raises an open question, so that I know human input is required before it proceeds.
- **US-0009** *(Operator — P0)* — As an Operator, I want open questions queued back to me and answerable with `maverick answer <question-id> "..."`, so that the blocked goal resumes from where it paused.
- **US-0010** *(Operator — P1)* — As an Operator, I want `maverick answer` to validate that the question id is still open before accepting my reply, so that I don't post answers to questions a goal already resolved.
- **US-0011** *(Team Lead — P1)* — As a Team Lead, I want to pause a running goal with a single command, so that I can hold execution while I gather more context without losing progress.
- **US-0012** *(Team Lead — P1)* — As a Team Lead, I want to resume a paused goal, so that the plan tree continues from its saved point rather than restarting.
- **US-0013** *(SRE — P0)* — As an SRE, I want active goals to survive a daemon restart by persisting their plan tree and state, so that an unplanned process bounce doesn't lose in-flight work.
- **US-0014** *(SRE — P1)* — As an SRE, I want goals that were `active` at shutdown to be re-enqueued or resumed on startup, so that the fleet self-heals without manual re-kicking.
- **US-0015** *(FinOps Owner — P0)* — As a FinOps Owner, I want each goal to record per-episode and cumulative cost, so that I can attribute spend to the goal that incurred it.
- **US-0016** *(FinOps Owner — P1)* — As a FinOps Owner, I want `maverick status <goal-id>` to show the goal's accumulated dollar and token cost, so that I can spot a runaway goal before its budget cap trips.
- **US-0017** *(Operator — P1)* — As an Operator, I want to view the per-episode breakdown of a goal, so that I can see which sub-agent step consumed the most tokens.
- **US-0018** *(Team Lead — P1)* — As a Team Lead, I want to retitle a goal after it starts, so that its label reflects the refined scope without creating a new goal.
- **US-0019** *(Team Lead — P1)* — As a Team Lead, I want to reparent a child goal under a different parent, so that I can reorganize the plan tree when priorities shift.
- **US-0020** *(Operator — P1)* — As an Operator, I want to add a new child goal under an existing goal, so that I can extend the plan tree with work discovered mid-flight.
- **US-0021** *(Operator — P0)* — As an Operator, I want to cancel a goal so it transitions to `cancelled` and its running sub-agents stop, so that I can abandon work that's no longer needed.
- **US-0022** *(SRE — P0)* — As an SRE, I want to halt a goal immediately (hard stop) distinct from a graceful cancel, so that I can stop a misbehaving goal that won't wind down on its own.
- **US-0023** *(Team Lead — P1)* — As a Team Lead, I want to set a priority on a goal, so that higher-priority goals are scheduled ahead of lower-priority ones in the queue.
- **US-0024** *(Platform Admin — P1)* — As a Platform Admin, I want goals to queue when concurrency limits are reached and dispatch in priority order, so that the fleet stays within capacity without dropping work.
- **US-0025** *(Operator — P1)* — As an Operator, I want to run multiple concurrent goals and see them all in `maverick monitor`, so that I can manage a portfolio of work simultaneously.
- **US-0026** *(Team Lead — P2)* — As a Team Lead, I want the plan tree to show each sub-agent's role (researcher/coder/verifier) and dependency edges, so that I understand why steps run in their given order.
- **US-0027** *(Operator — P2)* — As an Operator, I want a goal to move to `done` only after its verifier sub-agent confirms the result, so that completion means verified, not merely attempted.
- **US-0028** *(Compliance Officer — P1)* — As a Compliance Officer, I want every goal lifecycle transition (active→blocked→done/cancelled) recorded in the audit log, so that I can reconstruct what happened and when.
- **US-0029** *(Compliance Officer — P2)* — As a Compliance Officer, I want each human answer via `maverick answer` captured with author and timestamp, so that human-in-the-loop decisions are attributable.
- **US-0030** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want to start a goal via the MCP server tool equivalent of `maverick start`, so that an external agent can launch goals programmatically.
- **US-0031** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want to poll a goal's status and answer open questions through the TS SDK, so that I can drive the goal lifecycle from my own application.
- **US-0032** *(Operator — P2)* — As an Operator, I want `maverick monitor` to highlight goals in the `blocked` state, so that I immediately see which ones are waiting on my answer.
- **US-0033** *(Tenant Admin — P0)* — As a Tenant Admin, I want goals scoped to my tenant compartment so I only see and control my tenant's goals, so that one tenant's orchestration is isolated from another's.
- **US-0034** *(Tenant Admin — P1)* — As a Tenant Admin, I want concurrency and priority queue limits configurable per tenant, so that one tenant cannot starve another's goals of capacity.
- **US-0035** *(FinOps Owner — P0)* — As a FinOps Owner, I want a goal to halt automatically when it exhausts its budget cap, transitioning out of `active`, so that no goal can overspend silently.
- **US-0036** *(Security Engineer — P1)* — As a Security Engineer, I want each sub-agent in a plan tree to run under its own capability and permission clamp, so that a coder sub-agent can't exceed the goal's granted scope.
- **US-0037** *(Security Engineer — P2)* — As a Security Engineer, I want a goal that requests a sensitive capability to enter `blocked` pending approval, so that privileged actions never auto-execute without sign-off.
- **US-0038** *(Executive — P2)* — As an Executive, I want the dashboard Goals view to show counts by lifecycle state across the fleet, so that I can see throughput and backlog without using the CLI.
- **US-0039** *(Executive — P3)* — As an Executive, I want a fleet-wide rollup of total goal cost over a period, so that I can report spend trends to leadership.
- **US-0040** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want a completed goal's episodes retained as a record the learning lifecycle can ingest, so that dream/hindsight/proof has source material to learn from.
- **US-0041** *(Operator — P2)* — As an Operator, I want to inspect a single sub-agent's episode transcript within a goal, so that I can diagnose why one branch of the plan tree failed.
- **US-0042** *(Team Lead — P2)* — As a Team Lead, I want a blocked goal to surface its specific open question text in `maverick status`, so that I know exactly what to answer before resuming.
- **US-0043** *(SRE — P1)* — As an SRE, I want `maverick monitor` to keep streaming correctly across a worker reconnect, so that monitoring survives transient infrastructure hiccups.
- **US-0044** *(Platform Admin — P2)* — As a Platform Admin, I want a global cap on concurrent active goals across all workers, so that the fleet never exceeds the cluster's provisioned capacity.
- **US-0045** *(Operator — P2)* — As an Operator, I want to bump a queued goal's priority so it jumps ahead in the dispatch order, so that I can expedite urgent work without cancelling other goals.
- **US-0046** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want a goal's plan tree exposed as structured data (states, roles, costs) via the API, so that I can render it in my own UI.
- **US-0047** *(Compliance Officer — P2)* — As a Compliance Officer, I want a cancelled or halted goal to record who initiated the stop and why, so that abandonment decisions are auditable.
- **US-0048** *(External Auditor — P2)* — As an External Auditor, I want a read-only, immutable view of a goal's full lifecycle history and human answers, so that I can verify governance independently of operators.
- **US-0049** *(Operator — P3)* — As an Operator, I want a `pending` goal (queued but not yet dispatched) to be distinguishable from an `active` one in `maverick status`, so that I can tell what's waiting versus running.
- **US-0050** *(Team Lead — P3)* — As a Team Lead, I want to cancel an entire goal subtree in one action so child goals also stop, so that abandoning a parent doesn't leave orphaned sub-agents running.

---

## Epic 02 — Chat & Requests

- **US-0051** *(Requester — P0)* — As a Requester, I want to open the `/chat` dashboard and type a plain-English request like "summarize last quarter's support tickets" without knowing goal syntax, so that I can ask for work without learning the platform's internals.
- **US-0052** *(Operator — P0)* — As an Operator, I want a "Run as goal" button on any chat message that turns it into a running goal, so that I can move from conversation to execution in one click.
- **US-0053** *(Operator — P1)* — As an Operator, I want the chat to show a preview of the parsed goal (objective, suite, estimated budget) before I confirm, so that I can correct a misinterpretation before any tokens are spent.
- **US-0054** *(Requester — P0)* — As a Requester, I want the assistant to ask clarifying questions when my request is ambiguous (e.g. "which quarter?"), so that the resulting goal matches what I actually meant.
- **US-0055** *(Operator — P1)* — As an Operator, I want to answer a clarifying question inline in the same thread and have the goal draft update automatically, so that I don't have to retype the whole request.
- **US-0056** *(Requester — P1)* — As a Requester, I want to attach files (a CSV, a PDF spec) to my chat request, so that the agents have the source context they need to do the work.
- **US-0057** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want attached files to be stored as goal context with their content type and size recorded, so that downstream packs can reference them deterministically.
- **US-0058** *(Operator — P0)* — As an Operator, I want the goal-create form pre-populated from my chat message (objective, suite, budget caps), so that I can fine-tune fields without starting from a blank form.
- **US-0059** *(Team Lead — P1)* — As a Team Lead, I want the goal-create form to require a budget cap before submission, so that no chat-originated goal can run uncapped.
- **US-0060** *(FinOps Owner — P0)* — As a FinOps Owner, I want chat to display an inline budget-exceeded error when a request would breach the tenant's remaining budget, so that users get immediate feedback instead of a silently failed goal.
- **US-0061** *(Operator — P1)* — As an Operator, I want an inline rate-limit error in chat with the retry-after time when I send requests too quickly, so that I know exactly when I can try again.
- **US-0062** *(SRE — P1)* — As an SRE, I want chat-surfaced errors (rate-limit, budget, provider 5xx) to carry a correlation id, so that I can trace the failing request in the logs.
- **US-0063** *(Requester — P1)* — As a Requester, I want my chat history persisted per thread so I can scroll back and reread what I asked and what the assistant answered, so that I don't lose context between sessions.
- **US-0064** *(Operator — P0)* — As an Operator, I want to resume an existing chat thread and continue from where I left off, so that a multi-day request keeps its full conversational context.
- **US-0065** *(Operator — P1)* — As an Operator, I want each chat thread to link to the goals it spawned, so that I can jump from the conversation to the running or completed work.
- **US-0066** *(Agent Author — P0)* — As an Agent Author, I want `maverick onboard` to walk me through building a pack conversationally (role, tools, prompts), so that I can author a specialist without hand-editing config files.
- **US-0067** *(Agent Author — P1)* — As an Agent Author, I want `maverick onboard` to ask which capabilities and tool permissions the new pack needs and clamp them by default, so that I don't accidentally over-grant access.
- **US-0068** *(Agent Author — P1)* — As an Agent Author, I want `maverick onboard` to generate a runnable pack scaffold plus a smoke test, so that I can validate the pack immediately after the conversation ends.
- **US-0069** *(Agent Author — P2)* — As an Agent Author, I want `maverick onboard` to let me refine the draft pack over multiple turns ("make it read-only", "add the search tool"), so that I converge on the right definition iteratively.
- **US-0070** *(Requester — P0)* — As a non-technical Requester, I want a guided request mode that asks me what I need in business terms and never shows raw goal/JSON syntax, so that I can request work without engineering help.
- **US-0071** *(Requester — P2)* — As a Requester, I want suggested request templates ("draft an email", "analyze a spreadsheet") in the chat starter, so that I can begin from a known-good example.
- **US-0072** *(Operator — P1)* — As an Operator, I want to refine a goal across multiple chat turns before it runs ("also include EMEA", "cap it at $5"), so that the final goal is exactly scoped without re-opening the form.
- **US-0073** *(Team Lead — P0)* — As a Team Lead, I want to escalate a chat request to a human reviewer with one action, so that high-stakes work gets sign-off before it executes.
- **US-0074** *(Team Lead — P1)* — As a Team Lead, I want the escalation to capture the full thread, the parsed goal, and the requester, so that the reviewer has everything needed to approve or reject.
- **US-0075** *(Requester — P1)* — As a Requester, I want to see in chat that my request is "waiting for approval" and by whom, so that I understand why it hasn't started yet.
- **US-0076** *(Operator — P0)* — As an Operator, I want a Slack message addressed to the bot to become a goal in the platform, so that I can request work without leaving Slack.
- **US-0077** *(Operator — P0)* — As an Operator, I want an inbound email to a designated address to be turned into a chat thread and a goal, so that email-only stakeholders can trigger work.
- **US-0078** *(Tenant Admin — P1)* — As a Tenant Admin, I want channel-originated chats (Slack/email) tagged with the originating channel and tenant, so that work is attributed to the correct compartment.
- **US-0079** *(Security Engineer — P0)* — As a Security Engineer, I want channel-originated requests to map the external sender to a known identity before creating a goal, so that anonymous or spoofed senders can't spawn work.
- **US-0080** *(Operator — P1)* — As an Operator, I want goal status updates (started, needs-clarification, done) posted back to the originating Slack thread or email, so that the requester is informed where they asked.
- **US-0081** *(Requester — P2)* — As a Requester replying by email, I want my reply to a clarifying question to feed back into the same goal, so that I can complete a multi-turn exchange entirely over email.
- **US-0082** *(Compliance Officer — P0)* — As a Compliance Officer, I want every chat message, attachment, and the goal it produced recorded in the Operating Record, so that requests are auditable end to end.
- **US-0083** *(Compliance Officer — P1)* — As a Compliance Officer, I want chat attachments containing PII to be flagged or redacted per tenant policy before they reach an agent, so that sensitive data isn't processed without controls.
- **US-0084** *(External Auditor — P1)* — As an External Auditor, I want to retrieve the immutable chat-to-goal trail for a given request id, so that I can independently verify what was asked and what ran.
- **US-0085** *(Platform Admin — P1)* — As a Platform Admin, I want to configure which suites and packs are reachable from `/chat` per tenant, so that users can only request work the tenant is licensed for.
- **US-0086** *(Tenant Admin — P1)* — As a Tenant Admin, I want to set a default budget cap applied to all chat-originated goals in my tenant, so that ad-hoc requests can't blow the monthly budget.
- **US-0087** *(Security Engineer — P1)* — As a Security Engineer, I want chat input scanned for prompt-injection patterns before it becomes a goal objective, so that a crafted message can't hijack downstream agents.
- **US-0088** *(Operator — P2)* — As an Operator, I want to cancel a goal directly from the chat thread that started it, so that I can stop runaway work without hunting for it in the goals list.
- **US-0089** *(Requester — P1)* — As a Requester, I want the assistant to tell me when my request needs a capability my role lacks and offer to escalate, so that I'm not stuck at a silent permission wall.
- **US-0090** *(Team Lead — P2)* — As a Team Lead, I want to reassign a chat-originated goal to a different operator from the thread, so that requests land with the right owner.
- **US-0091** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want resolved chat threads with high-quality clarifications saved as reusable request examples, so that the assistant learns better defaults over time.
- **US-0092** *(SRE — P1)* — As an SRE, I want chat to degrade gracefully with a clear banner when the LLM provider is unavailable, so that users see "try again later" instead of a hung spinner.
- **US-0093** *(FinOps Owner — P2)* — As a FinOps Owner, I want each chat thread to show its running token and dollar cost (including clarification turns), so that I can see what conversation overhead costs before goals even start.
- **US-0094** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want a documented API to submit a natural-language request and receive the created goal id, so that I can wire external systems into the chat-to-goal flow.
- **US-0095** *(Operator — P2)* — As an Operator, I want to fork a chat thread to explore a variant request without losing the original, so that I can compare two framings before committing.
- **US-0096** *(Requester — P2)* — As a Requester, I want to remove or replace an attached file before submitting, so that I can fix an accidentally attached wrong document.
- **US-0097** *(Compliance Officer — P2)* — As a Compliance Officer, I want chat threads to honor the tenant's data-retention window and purge on schedule, so that requests aren't retained past policy.
- **US-0098** *(Executive — P2)* — As an Executive, I want a read-only weekly digest of the top chat-originated requests and their outcomes, so that I can see what the workforce is being asked to do without using the chat myself.
- **US-0099** *(Tenant Admin — P1)* — As a Tenant Admin, I want chat threads scoped to my tenant's compartment so users never see another tenant's history, so that multi-tenant isolation holds in the chat surface.
- **US-0100** *(Operator — P1)* — As an Operator, I want a clarifying question to time out and gently re-prompt if I don't answer, so that a half-specified request doesn't sit forever in a stuck state.

---

## Epic 03 — The Workforce: Agents & Roles

- **US-0101** *(Operator — P1)* — As an Operator, I want to browse the full ~2,020-pack specialist catalog grouped by its 53 suites, so that I can find the right agent for a goal without knowing its exact name.
- **US-0102** *(Operator — P1)* — As an Operator, I want to search the roster by free-text keyword across agent names, personas, and descriptions, so that I can locate a specialist by what it does rather than how it's labeled.
- **US-0103** *(Team Lead — P2)* — As a Team Lead, I want to filter the catalog by suite, so that my team only sees the specialist packs relevant to our domain.
- **US-0104** *(Operator — P2)* — As an Operator, I want to filter agents by risk level (low/medium/high), so that I can pick a safe specialist when working in a sensitive environment.
- **US-0105** *(Agent Author — P1)* — As an Agent Author, I want to open a specialist pack in the `/agents` editor, so that I can inspect and tune its persona, description, and capability envelope.
- **US-0106** *(Agent Author — P1)* — As an Agent Author, I want to edit an agent's persona and description in the `/agents` editor, so that the specialist's behavior and self-summary match our use case.
- **US-0107** *(Agent Author — P2)* — As an Agent Author, I want to create a new specialist pack from a blank template in the `/agents` editor, so that I can extend a suite with a capability the catalog lacks.
- **US-0108** *(Agent Author — P2)* — As an Agent Author, I want to clone an existing pack as the starting point for a new one, so that I inherit a known-good capability envelope and tweak only what differs.
- **US-0109** *(Platform Admin — P0)* — As a Platform Admin, I want to define roles on the `/roles` screen and bind each to a set of specialist packs, so that the workforce is organized by responsibility rather than by raw agent list.
- **US-0110** *(Platform Admin — P0)* — As a Platform Admin, I want to set per-role model mapping in the `[models]` config using `provider:model-id` form, so that each role runs on the model tier appropriate to its cost and capability needs.
- **US-0111** *(FinOps Owner — P1)* — As a FinOps Owner, I want to remap a role to a cheaper `provider:model-id` without editing any agent pack, so that I can cut spend on low-stakes roles centrally.
- **US-0112** *(Platform Admin — P2)* — As a Platform Admin, I want the `/roles` screen to validate that every `[models]` mapping references a configured provider, so that a typo in a model id is caught before a goal fails at runtime.
- **US-0113** *(Tenant Admin — P1)* — As a Tenant Admin, I want to enable or disable a whole suite for my tenant in one action, so that I can switch on the 53 suites my organization actually uses.
- **US-0114** *(Tenant Admin — P2)* — As a Tenant Admin, I want disabling a suite to immediately hide all its packs from the roster and block their spawning, so that retired domains can't be invoked accidentally.
- **US-0115** *(Operator — P0)* — As an Operator, I want to view the merged/resolved view of an agent showing the effective persona, model, and capability envelope after role and tenant overrides, so that I know exactly what will run, not just the pack defaults.
- **US-0116** *(Agent Author — P1)* — As an Agent Author, I want the resolved view to indicate which layer (pack, role, tenant) set each effective value, so that I can trace where an unexpected setting came from.
- **US-0117** *(Operator — P0)* — As an Operator, I want to spawn a specialist directly against a single task from the roster, so that I can run one-off work without defining a full goal.
- **US-0118** *(Requester — P2)* — As a non-technical Requester, I want to describe my task in plain language and have the workforce suggest the best-fit specialist, so that I don't have to understand the 52-suite taxonomy.
- **US-0119** *(Team Lead — P1)* — As a Team Lead, I want the `/workforce` screen to show which roles and agents are currently active across my team's running goals, so that I can see who is doing what at a glance.
- **US-0120** *(Operator — P2)* — As an Operator, I want each agent's capability envelope to be visible on its card, listing allow_tools, deny_tools, allow_paths, allow_hosts, and max_risk, so that I understand its reach before I spawn it.
- **US-0121** *(Security Engineer — P0)* — As a Security Engineer, I want to set an agent's deny_tools list so that named tools are refused even if they appear in allow_tools, so that a hard block always wins over a grant.
- **US-0122** *(Security Engineer — P0)* — As a Security Engineer, I want to constrain an agent's allow_paths to a path allowlist, so that a specialist cannot read or write files outside its sanctioned working area.
- **US-0123** *(Security Engineer — P0)* — As a Security Engineer, I want to constrain an agent's allow_hosts to a network allowlist, so that a specialist can only reach approved endpoints and nothing else.
- **US-0124** *(Security Engineer — P1)* — As a Security Engineer, I want to set a max_risk ceiling on an agent so that it refuses any action above that risk level, so that high-risk operations require a deliberately elevated specialist.
- **US-0125** *(Compliance Officer — P1)* — As a Compliance Officer, I want a single screen that shows, per agent, exactly what it can reach, what it denies, and what it refuses, so that I can attest to least-privilege without reading config files.
- **US-0126** *(Agent Author — P2)* — As an Agent Author, I want the `/agents` editor to warn when allow_tools grants a tool whose risk exceeds the agent's max_risk, so that I don't ship an envelope that contradicts itself.
- **US-0127** *(Platform Admin — P1)* — As a Platform Admin, I want to assign a default model mapping at the role level that individual packs inherit unless overridden, so that I set policy once instead of per agent.
- **US-0128** *(FinOps Owner — P2)* — As a FinOps Owner, I want the `/roles` screen to show the configured model and provider for every role side by side, so that I can spot expensive tiers assigned to low-value roles.
- **US-0129** *(Operator — P2)* — As an Operator, I want to filter the roster to only agents enabled for my current tenant and role, so that I'm not shown specialists I can't actually run.
- **US-0130** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to tag and annotate specialist packs with curation notes, so that operators learn which agent to prefer when several overlap.
- **US-0131** *(Operator — P1)* — As an Operator, I want to compare two specialists side by side on persona, model, risk level, and capability envelope, so that I can choose between similar packs in the same suite.
- **US-0132** *(Team Lead — P2)* — As a Team Lead, I want to mark a curated shortlist of favorite agents and roles, so that my team starts from a vetted set instead of the full 2,020-pack catalog.
- **US-0133** *(Agent Author — P1)* — As an Agent Author, I want to set an agent's risk level explicitly in the editor, so that the roster, filters, and max_risk checks reflect the true blast radius of the specialist.
- **US-0134** *(Compliance Officer — P0)* — As a Compliance Officer, I want every change to an agent's capability envelope to be recorded with who, what, and when, so that envelope drift is auditable after the fact.
- **US-0135** *(External Auditor — P1)* — As an External Auditor, I want to export the resolved view of all enabled agents, with effective envelopes and model mappings, so that I can review the workforce posture offline.
- **US-0136** *(Platform Admin — P1)* — As a Platform Admin, I want to disable a single agent within an otherwise-enabled suite, so that I can retire one risky specialist without losing the rest of the suite.
- **US-0137** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want to spawn a specialist programmatically via the TS SDK by role name, so that my application can delegate tasks to the workforce without hard-coding pack ids.
- **US-0138** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want the MCP server to expose the agent roster and each agent's capability envelope as resources, so that an external agent can discover which specialist to invoke.
- **US-0139** *(SRE — P2)* — As an SRE, I want to see how many instances of each role are concurrently spawned on the `/workforce` screen, so that I can detect a runaway suite consuming capacity.
- **US-0140** *(Operator — P2)* — As an Operator, I want a clear refusal message when I spawn a specialist for a task that exceeds its max_risk or hits a deny rule, so that I understand why it stopped instead of seeing a silent failure.
- **US-0141** *(Tenant Admin — P1)* — As a Tenant Admin, I want suite enablement and per-role model mappings to be scoped to my tenant, so that my configuration never leaks into or from another tenant.
- **US-0142** *(Agent Author — P2)* — As an Agent Author, I want to preview an agent's persona rendered as it will appear at spawn time, so that I can confirm the description reads correctly before publishing the pack.
- **US-0143** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to browse the 53 suites with a one-line summary of each suite's domain, so that I can map an organizational need to the right family of packs.
- **US-0144** *(Security Engineer — P1)* — As a Security Engineer, I want to define an envelope template (allow_tools/deny_tools/allow_paths/allow_hosts/max_risk) and apply it to many packs at once, so that a security baseline is enforced uniformly across a suite.
- **US-0145** *(Compliance Officer — P2)* — As a Compliance Officer, I want to flag agents whose effective envelope grants allow_hosts to external networks, so that I can review every specialist that can egress data.
- **US-0146** *(Executive — P3)* — As an Executive, I want a summary count of enabled suites, active roles, and specialist packs in use, so that I can report the scale of our deployed AI workforce.
- **US-0147** *(FinOps Owner — P1)* — As a FinOps Owner, I want to see which `provider:model-id` each spawned specialist resolved to in a run, so that I can attribute spend to roles and model tiers.
- **US-0148** *(Operator — P2)* — As an Operator, I want to sort roster search results by relevance, suite, or risk level, so that I can surface the safest or most relevant specialist first.
- **US-0149** *(Platform Admin — P0)* — As a Platform Admin, I want changes to role-to-model mappings and suite enablement to take effect for newly spawned agents without a restart, so that I can adjust the workforce live.
- **US-0150** *(External Auditor — P2)* — As an External Auditor, I want to verify that every enabled agent's deny_tools and max_risk are actually enforced at spawn via a refusal test, so that I can confirm the envelope is not merely advisory.

---

## Epic 04 — Agent Authoring & Packs

- **US-0151** *(Agent Author — P0)* — As an Agent Author, I want to open `/goal-builder` and describe an outcome in plain language, so that the builder drafts a candidate specialist pack scaffold I can refine.
- **US-0152** *(Agent Author — P1)* — As an Agent Author, I want the goal builder to suggest a role, tools, and playbook based on my goal description, so that I start from a sensible default instead of an empty file.
- **US-0153** *(Agent Author — P1)* — As an Agent Author, I want the goal builder to show me which existing built-in base pack my draft should extend, so that I reuse governed behavior instead of duplicating it.
- **US-0154** *(Operator — P1)* — As an Operator, I want to preview the goal builder's generated pack as a diff against its base before saving, so that I can see exactly what fields it changes.
- **US-0155** *(Agent Author — P0)* — As an Agent Author, I want to run `maverick learn-demo demo.txt` to build a specialist by showing it a watched task, so that I capture expertise without writing pack YAML by hand.
- **US-0156** *(Agent Author — P0)* — As an Agent Author, I want `learn-demo` to accept JSONL demonstration files, so that I can feed structured step-by-step traces from tooling.
- **US-0157** *(Agent Author — P1)* — As an Agent Author, I want `learn-demo` to accept prefixed-text demonstrations, so that I can author quick demos in a simple human-readable format.
- **US-0158** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want `learn-demo --no-llm` to synthesize a pack deterministically from the demonstration alone, so that I can build packs in air-gapped or no-API-key environments.
- **US-0159** *(Agent Author — P2)* — As an Agent Author, I want `learn-demo --name "Invoice Triage"` to set the new pack's name, so that the generated pack lands with a meaningful identity instead of an auto-generated slug.
- **US-0160** *(Agent Author — P2)* — As an Agent Author, I want `learn-demo --yes` to skip interactive confirmation prompts, so that I can script pack creation in CI or batch jobs.
- **US-0161** *(Agent Author — P1)* — As an Agent Author, I want `learn-demo` to report which steps it could not generalize from the demonstration, so that I know where the synthesized pack is weak before relying on it.
- **US-0162** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want a demonstration file to map each captured step to a catalog skill or declared tool, so that learned packs reuse governed capabilities rather than inventing untracked ones.
- **US-0163** *(Agent Author — P0)* — As an Agent Author, I want to define a pack override that inherits a built-in base and patches only the changed fields, so that I customize behavior without forking the whole base pack.
- **US-0164** *(Agent Author — P1)* — As an Agent Author, I want my override file to use `extends:` to name its base pack, so that the inheritance relationship is explicit and validated.
- **US-0165** *(Operator — P1)* — As an Operator, I want a field-level override to keep tracking upstream changes to unpatched fields of its base, so that base improvements flow through without re-authoring.
- **US-0166** *(Agent Author — P2)* — As an Agent Author, I want validation to reject an override that patches a field which no longer exists on its base, so that drifted overrides surface instead of silently no-op-ing.
- **US-0167** *(Platform Admin — P1)* — As a Platform Admin, I want to resolve an override into its fully merged effective pack on demand, so that I can audit what a customized specialist will actually do.
- **US-0168** *(Agent Author — P2)* — As an Agent Author, I want an override chain (`extends` across multiple levels) to merge predictably with documented precedence, so that I can layer org, team, and personal customizations.
- **US-0169** *(Security Engineer — P0)* — As a Security Engineer, I want every new pack to undergo a persona scan before it can run, so that nothing with an unreviewed identity activates in the fleet.
- **US-0170** *(Security Engineer — P0)* — As a Security Engineer, I want capability clamps applied to new packs so that no pack activates with broader tools or scopes than approved, so that authoring cannot escalate privilege.
- **US-0171** *(Platform Admin — P0)* — As a Platform Admin, I want a newly authored pack to remain inactive until explicitly approved, so that creating a pack is never the same as deploying it.
- **US-0172** *(Compliance Officer — P1)* — As a Compliance Officer, I want the persona scan to flag packs whose declared persona conflicts with policy (e.g. impersonating a regulated role), so that risky identities are caught at authoring time.
- **US-0173** *(Security Engineer — P1)* — As a Security Engineer, I want the capability clamp to show the requested-vs-granted capability delta on the approval screen, so that I approve the minimum needed and nothing more.
- **US-0174** *(Security Engineer — P0)* — As a Security Engineer, I want secrets in demonstrations and pack definitions redacted at the door before storage, so that captured credentials never persist in pack artifacts or logs.
- **US-0175** *(Compliance Officer — P1)* — As a Compliance Officer, I want secret-redaction events during authoring recorded in the audit trail, so that I can prove sensitive data was scrubbed at intake.
- **US-0176** *(Agent Author — P2)* — As an Agent Author, I want to see a masked indicator where a secret was redacted from my demonstration, so that I understand why a captured value is absent from the pack.
- **US-0177** *(Platform Admin — P0)* — As a Platform Admin, I want approving a pack to provision it by installing its declared catalog skills, so that the pack's capabilities are wired up automatically on activation.
- **US-0178** *(Platform Admin — P0)* — As a Platform Admin, I want provisioning to synthesize the pack's declared tools that don't already exist, so that an approved pack is runnable end to end without manual tool setup.
- **US-0179** *(SRE — P1)* — As an SRE, I want provisioning to be idempotent so re-approving or re-provisioning a pack does not duplicate skills or tools, so that recovery and retries are safe.
- **US-0180** *(SRE — P1)* — As an SRE, I want provisioning failures to roll back partial installs and leave the pack inactive, so that a half-provisioned pack never runs.
- **US-0181** *(Agent Author — P1)* — As an Agent Author, I want to attach a workflow playbook to a pack, so that the specialist follows a defined sequence of steps rather than improvising every run.
- **US-0182** *(Operator — P2)* — As an Operator, I want a pack's attached playbook to be visible and inspectable from the dashboard, so that I can see the workflow a specialist will execute before I run it.
- **US-0183** *(Team Lead — P2)* — As a Team Lead, I want to attach multiple playbooks to one pack and select which runs per goal, so that one specialist can handle related but distinct workflows.
- **US-0184** *(Agent Author — P1)* — As an Agent Author, I want playbook steps to reference only the pack's declared tools and skills, so that validation catches a playbook calling a capability the pack lacks.
- **US-0185** *(Agent Author — P0)* — As an Agent Author, I want to lint and validate a pack before submitting it, so that malformed packs are rejected with actionable errors instead of failing at runtime.
- **US-0186** *(Security Engineer — P0)* — As a Security Engineer, I want pack validation to run a risk-envelope check that fails packs exceeding their suite's allowed risk tier, so that high-risk capabilities can't slip in under an unreviewed pack.
- **US-0187** *(Agent Author — P1)* — As an Agent Author, I want pack lint to flag an `extends` target that doesn't exist or isn't a built-in base, so that broken inheritance is caught before approval.
- **US-0188** *(Compliance Officer — P2)* — As a Compliance Officer, I want validation to require a declared owner and data-handling classification on every pack, so that ungoverned packs can't be authored.
- **US-0189** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want pack lint exposed as a CLI command with a non-zero exit on failure, so that I can gate pack changes in CI.
- **US-0190** *(Agent Author — P2)* — As an Agent Author, I want lint warnings (vs errors) distinguished, so that I can ship a pack with non-blocking advisories while still fixing hard failures.
- **US-0191** *(Requester — P1)* — As a Requester, I want to run `maverick onboard` for conversational authoring, so that I can build a specialist through a guided Q&A without learning pack schema.
- **US-0192** *(Operator — P2)* — As an Operator, I want `maverick onboard` to confirm each captured requirement back to me before generating the pack, so that I catch misunderstandings early.
- **US-0193** *(Requester — P2)* — As a Requester, I want `onboard` to hand off the drafted pack into the same persona-scan and approval flow as other authoring paths, so that conversational packs get identical governance.
- **US-0194** *(Agent Author — P0)* — As an Agent Author, I want each saved pack to carry a version, so that I can iterate while keeping a stable history of what was deployed.
- **US-0195** *(Platform Admin — P1)* — As a Platform Admin, I want editing an approved pack to create a new version requiring re-approval rather than mutating the running one, so that live packs stay governed.
- **US-0196** *(Agent Author — P1)* — As an Agent Author, I want to export a pack to a portable file, so that I can share it across tenants or back it up outside the platform.
- **US-0197** *(Tenant Admin — P1)* — As a Tenant Admin, I want to import an exported pack into my tenant where it re-enters persona scan and approval, so that imported packs are never trusted blindly.
- **US-0198** *(External Auditor — P2)* — As an External Auditor, I want an exported pack to include its version, base lineage, and approval metadata, so that I can verify provenance of a deployed specialist offline.
- **US-0199** *(FinOps Owner — P2)* — As a FinOps Owner, I want each pack version to declare its budget caps, so that authoring can't deploy a specialist that bypasses cost controls.
- **US-0200** *(Executive — P3)* — As an Executive, I want a summary of how many specialist packs were authored, approved, and exported this period across suites, so that I can track the growth of our governed AI workforce.

---

## Epic 05 — Workflows & Automations

- **US-0201** *(Operator — P0)* — As an Operator, I want to open the workflow builder at `/workflow-builder` and assemble a multi-step workflow from a visual canvas, so that I can compose automations without writing code.
- **US-0202** *(Operator — P0)* — As an Operator, I want to run a saved workflow on demand with a single click from `/workflows`, so that I can trigger a known-good automation exactly when I need it.
- **US-0203** *(Team Lead — P0)* — As a Team Lead, I want the `/workflows` index to list every saved workflow with its name, owner, last-run time, and status, so that I can see at a glance what my team has automated.
- **US-0204** *(Agent Author — P1)* — As an Agent Author, I want to distinguish workflow templates I authored from packaged agent playbooks in the builder library, so that I don't accidentally edit a vendor-shipped playbook I'm only meant to reuse.
- **US-0205** *(Agent Author — P0)* — As an Agent Author, I want to define named parameters on a workflow template with types and default values, so that a single template can be reused across different inputs.
- **US-0206** *(Operator — P1)* — As an Operator, I want to be prompted for each declared parameter when I run a parameterized workflow, so that I supply the right inputs before execution begins.
- **US-0207** *(Operator — P1)* — As an Operator, I want the templates catalog at `/templates` to be searchable by name, tag, and suite, so that I can find a relevant template instead of building one from scratch.
- **US-0208** *(Team Lead — P1)* — As a Team Lead, I want to instantiate a workflow from a catalog template with one action, so that my team starts from a vetted baseline.
- **US-0209** *(Operator — P0)* — As an Operator, I want to create a recurring automation on `/automations` with a cron-like schedule, so that a workflow runs automatically at fixed times without me being present.
- **US-0210** *(Operator — P1)* — As an Operator, I want to pick a schedule using friendly presets (hourly, daily, weekly) as well as a raw cron expression, so that I can set timing whether or not I know cron syntax.
- **US-0211** *(Platform Admin — P1)* — As a Platform Admin, I want the schedule editor to validate cron expressions and reject invalid ones before saving, so that no automation is created with an unparseable trigger.
- **US-0212** *(Agent Author — P1)* — As an Agent Author, I want to define an event trigger so a workflow fires when a specific platform event occurs, so that automations react to activity instead of only the clock.
- **US-0213** *(Agent Author — P1)* — As an Agent Author, I want to attach a condition to a trigger so the workflow only runs when a predicate is true, so that I avoid firing on irrelevant events.
- **US-0214** *(Operator — P1)* — As an Operator, I want to edit an existing saved workflow from `/workflows` and have my changes persist, so that I can refine an automation as requirements change.
- **US-0215** *(Operator — P1)* — As an Operator, I want to clone an existing workflow into a new draft, so that I can adapt a proven automation for a new use case without altering the original.
- **US-0216** *(Operator — P2)* — As an Operator, I want to delete a workflow I no longer need with a confirmation step, so that I can keep the index tidy without accidental removals.
- **US-0217** *(Operator — P2)* — As an Operator, I want a quick-edit action on each workflow row that opens the builder directly to that workflow, so that I can make a small change without navigating through menus.
- **US-0218** *(Operator — P2)* — As an Operator, I want a quick-automate action that turns an existing workflow into a scheduled automation in one step, so that I can promote a manual workflow to recurring without rebuilding it.
- **US-0219** *(Compliance Officer — P0)* — As a Compliance Officer, I want to gate a workflow behind a required human approval before it executes, so that high-impact automations cannot run unreviewed.
- **US-0220** *(Team Lead — P1)* — As a Team Lead, I want to be notified when a workflow I own is waiting on my approval, so that gated runs aren't blocked because I didn't know.
- **US-0221** *(Operator — P1)* — As an Operator, I want a run that hits an approval gate to pause and resume from the gated step once approved, so that no work is repeated after the approver acts.
- **US-0222** *(Agent Author — P0)* — As an Agent Author, I want each save of a workflow to create a new immutable version, so that I have a full history of how the automation evolved.
- **US-0223** *(Agent Author — P1)* — As an Agent Author, I want to view a diff between two workflow versions, so that I can see exactly what changed between revisions.
- **US-0224** *(Operator — P1)* — As an Operator, I want to roll a workflow back to a previous version, so that I can recover quickly when a recent edit breaks the automation.
- **US-0225** *(Platform Admin — P1)* — As a Platform Admin, I want to pin a specific workflow version as the one used by its automations, so that scheduled runs don't silently pick up an unreviewed edit.
- **US-0226** *(Operator — P1)* — As an Operator, I want to pause and resume a scheduled automation without deleting it, so that I can temporarily halt recurring runs during a freeze.
- **US-0227** *(Operator — P2)* — As an Operator, I want to see the next scheduled run time for each automation on `/automations`, so that I can confirm a trigger is set up the way I intended.
- **US-0228** *(Team Lead — P1)* — As a Team Lead, I want to view the run history of a workflow with status, duration, and triggering cause, so that I can audit whether automations are behaving.
- **US-0229** *(Operator — P0)* — As an Operator, I want a failed workflow run to surface the failing step and its error, so that I can diagnose and fix the automation quickly.
- **US-0230** *(Operator — P2)* — As an Operator, I want to retry a failed run from the failed step rather than the beginning, so that I don't redo successful work.
- **US-0231** *(Agent Author — P1)* — As an Agent Author, I want to publish a workflow I built as a reusable template into the `/templates` catalog, so that others can instantiate my automation.
- **US-0232** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want to tag and categorize catalog templates by suite and domain, so that the catalog stays browsable as it grows.
- **US-0233** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to deprecate an outdated template so it's hidden from new instantiations but preserved for existing automations, so that I can retire stale content safely.
- **US-0234** *(FinOps Owner — P1)* — As a FinOps Owner, I want each workflow run to record its token and dollar cost against the run history, so that I can attribute spend to specific automations.
- **US-0235** *(FinOps Owner — P0)* — As a FinOps Owner, I want to set a per-run budget cap on a workflow that stops execution if exceeded, so that a misbehaving automation can't run up unbounded cost.
- **US-0236** *(Tenant Admin — P1)* — As a Tenant Admin, I want workflows and automations scoped to my tenant so they're invisible to other tenants, so that customers' automations stay isolated.
- **US-0237** *(Tenant Admin — P2)* — As a Tenant Admin, I want to set a tenant-wide limit on the number of active scheduled automations, so that one team can't exhaust shared scheduler capacity.
- **US-0238** *(Security Engineer — P0)* — As a Security Engineer, I want every workflow step that calls a shell or tool to route through the sandbox, so that automations can't execute arbitrary commands outside the governed boundary.
- **US-0239** *(Security Engineer — P1)* — As a Security Engineer, I want approval gates on workflows to require a different user than the one who authored the workflow, so that no single person can both define and approve a privileged automation.
- **US-0240** *(Compliance Officer — P1)* — As a Compliance Officer, I want every approval decision on a gated workflow recorded with approver, timestamp, and outcome in the audit log, so that I can prove who authorized each run.
- **US-0241** *(External Auditor — P1)* — As an External Auditor, I want to export the immutable version and run history of a workflow as a signed record, so that I can independently verify automation provenance.
- **US-0242** *(Developer/Integrator — P0)* — As a Developer/Integrator, I want to create, run, and schedule workflows through the API and TS SDK, so that I can drive automations from external systems without the dashboard.
- **US-0243** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want to trigger a workflow from the MCP server as an exposed tool, so that an external agent can invoke our automations.
- **US-0244** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want to import and export a workflow definition as a portable file, so that I can version-control automations in my own repository.
- **US-0245** *(SRE — P1)* — As an SRE, I want concurrent runs of the same scheduled workflow to be de-duplicated so a slow run doesn't overlap its next trigger, so that I avoid double-execution under load.
- **US-0246** *(SRE — P0)* — As an SRE, I want scheduled automations to survive a worker restart and run exactly once when their time arrives, so that no scheduled job is lost or duplicated on deploy.
- **US-0247** *(SRE — P2)* — As an SRE, I want to configure a retry-with-backoff policy on a workflow step, so that transient failures self-heal without manual intervention.
- **US-0248** *(Requester — P1)* — As a Requester, I want to submit a request that kicks off a predefined workflow and then track its progress, so that I can get work done without knowing how the automation is built.
- **US-0249** *(Executive — P2)* — As an Executive, I want a dashboard summary of how many workflows ran, succeeded, and were gated this period, so that I can gauge automation adoption and reliability at a glance.
- **US-0250** *(Platform Admin — P1)* — As a Platform Admin, I want to restrict who can create, edit, or approve workflows via role-based permissions, so that only authorized people can change what the workforce automates.

---

## Epic 06 — Graph & Plan Visualization

- **US-0251** *(Operator — P0)* — As an Operator, I want to open `/graph-editor` and see all my goals rendered as a force-directed graph, so that I can grasp the shape of my workload at a glance.
- **US-0252** *(Operator — P0)* — As an Operator, I want each goal node drawn as a circle sized by its connection count, so that I can immediately spot the most-connected hub goals.
- **US-0253** *(Operator — P0)* — As an Operator, I want node fill colors to encode goal status, so that I can tell pending, active, blocked, and done goals apart without reading labels.
- **US-0254** *(Team Lead — P1)* — As a Team Lead, I want a legend mapping each status color to its meaning, so that newcomers can read the graph without guessing.
- **US-0255** *(Operator — P1)* — As an Operator, I want links between goals drawn as thin lines, so that the dependency structure stays legible even on a dense graph.
- **US-0256** *(Operator — P1)* — As an Operator, I want directed links to indicate parent-to-child orientation, so that I can read the planning hierarchy from the edges.
- **US-0257** *(Operator — P0)* — As an Operator, I want hovering a node to spotlight that node and its immediate neighborhood while dimming the rest, so that I can isolate one goal's context in a crowded graph.
- **US-0258** *(Operator — P1)* — As an Operator, I want the spotlight to clear when I move the cursor off the node, so that the full graph returns without an extra click.
- **US-0259** *(Operator — P0)* — As an Operator, I want to drag any node to a new position, so that I can manually arrange the layout to match my mental model.
- **US-0260** *(Operator — P1)* — As an Operator, I want a dragged node to stay pinned where I drop it while the rest of the simulation settles, so that my arrangement is not undone by the physics.
- **US-0261** *(Operator — P0)* — As an Operator, I want to pan the canvas by dragging empty space, so that I can navigate a graph larger than the viewport.
- **US-0262** *(Operator — P0)* — As an Operator, I want to zoom the graph with the scroll wheel or trackpad pinch, so that I can move between overview and detail.
- **US-0263** *(Operator — P1)* — As an Operator, I want an auto-fit control that frames the entire graph in the viewport, so that I can recenter after panning far off.
- **US-0264** *(Operator — P1)* — As an Operator, I want the graph to auto-fit on first load, so that I see the whole workspace without having to zoom out manually.
- **US-0265** *(Operator — P1)* — As an Operator, I want node labels to fade out as I zoom away and reappear as I zoom in, so that the overview stays uncluttered while detail remains available.
- **US-0266** *(Operator — P2)* — As an Operator, I want labels to truncate with an ellipsis when goal titles are long, so that text does not overlap neighboring nodes.
- **US-0267** *(Operator — P0)* — As an Operator, I want to retitle a goal directly from the graph by editing its node, so that I can correct or refine goals without leaving the visualization.
- **US-0268** *(Operator — P1)* — As an Operator, I want a retitle to validate against empty or whitespace-only titles, so that I cannot accidentally blank out a goal name.
- **US-0269** *(Operator — P0)* — As an Operator, I want to reparent a goal by dragging its node onto a new parent, so that I can restructure the plan visually.
- **US-0270** *(Operator — P0)* — As an Operator, I want the reparent to only accept a target that is not a descendant of the goal, so that I cannot create an impossible parent-child loop.
- **US-0271** *(Operator — P0)* — As an Operator, I want the cycle guard to reject a reparent-into-a-descendant with a clear inline message, so that I understand why the move was refused.
- **US-0272** *(Team Lead — P1)* — As a Team Lead, I want reparenting onto the same current parent to be a no-op rather than an error, so that accidental re-drops do not generate noise.
- **US-0273** *(Operator — P0)* — As an Operator, I want to add a new pending child goal directly from a parent node in the graph, so that I can expand a plan in place.
- **US-0274** *(Operator — P1)* — As an Operator, I want a newly added child to appear immediately as a connected node with pending status color, so that I get visual confirmation it was created.
- **US-0275** *(Operator — P2)* — As an Operator, I want to undo my last graph edit (retitle, reparent, or add-child), so that I can recover quickly from a mistaken change.
- **US-0276** *(Operator — P1)* — As an Operator, I want graph edits to persist to the world model so that reloading the page shows the same structure, so that my changes are durable.
- **US-0277** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want the graph editor to reflect goal changes made via the CLI or API after a refresh, so that the visualization stays a faithful view of the underlying data.
- **US-0278** *(Operator — P0)* — As an Operator, I want to open `/plan-tree-3d` and see my plan rendered as a 3D WebGL forest, so that I can explore deep hierarchies spatially.
- **US-0279** *(Operator — P1)* — As an Operator, I want to orbit, pan, and zoom the 3D plan tree with mouse and touch, so that I can inspect branches from any angle.
- **US-0280** *(Operator — P1)* — As an Operator, I want each root goal to render as a separate tree in the 3D forest, so that independent plans are visually distinct.
- **US-0281** *(Operator — P2)* — As an Operator, I want 3D nodes colored by the same status palette as the 2D graph, so that I do not have to relearn the color meaning across views.
- **US-0282** *(SRE — P2)* — As an SRE, I want the 3D plan tree to gracefully fall back to the nested-tree view when WebGL is unavailable, so that the page is never blank on unsupported hardware.
- **US-0283** *(Compliance Officer — P0)* — As a Compliance Officer, I want a read-only nested-tree accessibility fallback for the plan, so that the visualization is usable by assistive technology and meets a11y requirements.
- **US-0284** *(Operator — P0)* — As an Operator, I want to select graph nodes using the keyboard, so that I can navigate the plan without a pointing device.
- **US-0285** *(Operator — P1)* — As an Operator, I want arrow-key traversal between a node and its parent, children, and siblings, so that keyboard navigation follows the plan structure.
- **US-0286** *(Compliance Officer — P1)* — As a Compliance Officer, I want the nested-tree fallback to expose ARIA roles, names, and the current selection to screen readers, so that an audit of accessibility passes.
- **US-0287** *(Operator — P2)* — As an Operator, I want a visible focus ring on the keyboard-selected node, so that I always know where I am in the graph.
- **US-0288** *(Operator — P1)* — As an Operator, I want to trigger a node's edit and add-child actions from the keyboard, so that I can manage goals without a mouse.
- **US-0289** *(Team Lead — P0)* — As a Team Lead, I want to filter the graph by status, so that I can focus on, for example, only blocked goals.
- **US-0290** *(Team Lead — P0)* — As a Team Lead, I want to filter the graph by owner, so that I can see just the goals assigned to one person.
- **US-0291** *(Team Lead — P1)* — As a Team Lead, I want status and owner filters to combine, so that I can narrow to one owner's blocked goals at once.
- **US-0292** *(Operator — P2)* — As an Operator, I want filtered-out nodes to dim or hide while their connecting links update, so that the filtered graph stays readable.
- **US-0293** *(Operator — P1)* — As an Operator, I want a one-click control to clear all active filters, so that I can return to the full graph quickly.
- **US-0294** *(Team Lead — P1)* — As a Team Lead, I want active filters reflected in the URL query string, so that I can bookmark or share a specific filtered view.
- **US-0295** *(Team Lead — P0)* — As a Team Lead, I want to export the current graph view as an image, so that I can drop a plan snapshot into a status update.
- **US-0296** *(Executive — P1)* — As an Executive, I want to share a read-only link to a graph view, so that stakeholders can see the plan without editing it.
- **US-0297** *(Tenant Admin — P1)* — As a Tenant Admin, I want shared graph links to respect the tenant's access controls, so that recipients only see goals they are permitted to view.
- **US-0298** *(Operator — P2)* — As an Operator, I want a shared or exported view to preserve my current zoom, pan, and filter state, so that recipients see exactly what I framed.
- **US-0299** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want to export the graph as structured JSON of nodes and edges, so that I can feed the plan into downstream tooling.
- **US-0300** *(SRE — P2)* — As an SRE, I want the graph editor to render a large goal set without freezing the browser, so that the visualization stays responsive at scale.

---

## Epic 07 — Fleets, Projects & Deliverables

- **US-0301** *(Team Lead — P0)* — As a Team Lead, I want to create a fleet at `/fleets` that groups multiple agents and goals under one named unit, so that I can manage a coordinated workforce instead of isolated agents.
- **US-0302** *(Team Lead — P1)* — As a Team Lead, I want to add and remove individual agents from a fleet, so that I can adjust the workforce composition as priorities change.
- **US-0303** *(Operator — P0)* — As an Operator, I want to create a project at `/projects` that bundles related goals toward a shared outcome, so that work spanning many goals stays organized under one objective.
- **US-0304** *(Operator — P1)* — As an Operator, I want to assign a goal to a specific project from the goal detail view, so that the goal rolls up into the right project's progress.
- **US-0305** *(Team Lead — P1)* — As a Team Lead, I want to assign a goal to a specific fleet, so that the fleet's agents pick it up and the goal counts toward fleet utilization.
- **US-0306** *(Operator — P0)* — As an Operator, I want each project to track its deliverables at `/deliverables` as concrete named outputs, so that I can see exactly what tangible artifacts the work has produced.
- **US-0307** *(Operator — P1)* — As an Operator, I want each deliverable to carry an explicit status (draft, in-review, accepted, rejected, archived), so that I always know where each output stands in its lifecycle.
- **US-0308** *(Requester — P1)* — As a Requester, I want to view the deliverables produced for a project I sponsored, so that I can confirm the workforce produced what I asked for.
- **US-0309** *(Requester — P0)* — As a Requester, I want to formally accept or reject a deliverable with a sign-off action, so that produced outputs are not considered final until a human approves them.
- **US-0310** *(Requester — P1)* — As a Requester, I want to attach a rejection reason and required changes when I reject a deliverable, so that the fleet knows precisely what to fix before resubmitting.
- **US-0311** *(Operator — P1)* — As an Operator, I want to export a deliverable to a downloadable file (PDF, Markdown, or original format), so that I can share the output with stakeholders outside the platform.
- **US-0312** *(Operator — P2)* — As an Operator, I want to export all accepted deliverables of a project as a single bundled archive, so that I can hand off a complete project package in one download.
- **US-0313** *(Team Lead — P0)* — As a Team Lead, I want a fleet to maintain shared fleet memory accessible to every agent in the fleet, so that agents reuse each other's context instead of relearning it independently.
- **US-0314** *(Agent Author — P1)* — As an Agent Author, I want to read and write to a fleet's shared memory from within an agent pack, so that an agent I author can contribute and consume fleet-wide knowledge.
- **US-0315** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want to review and curate entries in a fleet's shared memory, so that stale or incorrect shared context does not propagate across the fleet.
- **US-0316** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to pin or expire specific fleet memory entries, so that durable facts persist while transient ones age out automatically.
- **US-0317** *(Team Lead — P0)* — As a Team Lead, I want a project dashboard that rolls up goal status, progress, and blockers across all goals in the project, so that I can assess project health at a glance.
- **US-0318** *(Executive — P1)* — As an Executive, I want a fleet-level roll-up showing total goals completed, in-flight, and failed across the fleet, so that I can judge overall workforce throughput without inspecting individual goals.
- **US-0319** *(Executive — P2)* — As an Executive, I want a portfolio view rolling up multiple projects' status into one summary, so that I can compare progress across initiatives in a single screen.
- **US-0320** *(FinOps Owner — P0)* — As a FinOps Owner, I want to set a fleet-level budget cap that bounds total spend across all the fleet's agents and goals, so that a runaway fleet cannot exceed its allocation.
- **US-0321** *(FinOps Owner — P1)* — As a FinOps Owner, I want to set a per-project budget separate from the fleet budget, so that one project overspending does not starve the rest of the fleet.
- **US-0322** *(FinOps Owner — P1)* — As a FinOps Owner, I want fleet and project spend reported against their budgets in real time, so that I can intervene before a cap is breached rather than after.
- **US-0323** *(FinOps Owner — P2)* — As a FinOps Owner, I want an alert when a fleet or project crosses a configurable percentage of its budget, so that I get early warning instead of a hard stop.
- **US-0324** *(Team Lead — P1)* — As a Team Lead, I want fleet-level oversight controls that pause every goal in the fleet with one action, so that I can halt the whole workforce immediately during an incident.
- **US-0325** *(Team Lead — P2)* — As a Team Lead, I want to resume a paused fleet and have only the previously running goals restart, so that pausing for oversight does not lose in-flight work.
- **US-0326** *(Operator — P1)* — As an Operator, I want to reassign a goal from one project or fleet to another, so that I can correct misfiled work without recreating the goal.
- **US-0327** *(Team Lead — P0)* — As a Team Lead, I want to graduate a fleet's workforce from supervised to autonomous operation once it meets defined criteria, so that proven fleets earn reduced manual oversight.
- **US-0328** *(Compliance Officer — P1)* — As a Compliance Officer, I want graduation to require documented evidence (success rate, sign-off history, incident-free window) before a fleet becomes autonomous, so that autonomy is granted on proof, not assertion.
- **US-0329** *(Team Lead — P1)* — As a Team Lead, I want to revert a graduated fleet back to supervised mode, so that I can re-tighten oversight if a fleet's quality regresses.
- **US-0330** *(Operator — P0)* — As an Operator, I want to archive a completed project so it leaves the active list but stays retrievable, so that finished work stops cluttering my workspace without being lost.
- **US-0331** *(Operator — P1)* — As an Operator, I want archiving a project to be blocked while it has un-accepted deliverables, so that I cannot accidentally close out work that was never signed off.
- **US-0332** *(Tenant Admin — P2)* — As a Tenant Admin, I want to restore an archived project to active status, so that reopened initiatives resume exactly where they left off.
- **US-0333** *(Compliance Officer — P0)* — As a Compliance Officer, I want every deliverable acceptance and rejection recorded in the audit trail with actor, timestamp, and reason, so that sign-off decisions are provable after the fact.
- **US-0334** *(External Auditor — P1)* — As an External Auditor, I want a read-only export of a project's deliverables, sign-offs, and budget consumption, so that I can verify governance independently without platform write access.
- **US-0335** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want a `/fleets`, `/projects`, and `/deliverables` REST API surface, so that I can manage fleets and read deliverable status from external systems.
- **US-0336** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want a webhook fired when a deliverable changes status, so that downstream systems react to acceptance or rejection without polling.
- **US-0337** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want the TS SDK to expose fleet, project, and deliverable models, so that I can build integrations type-safely against these surfaces.
- **US-0338** *(Operator — P1)* — As an Operator, I want to link a deliverable to the specific goal and agent run that produced it, so that I can trace any output back to its provenance.
- **US-0339** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want accepted deliverables to optionally promote their content into fleet memory, so that approved outputs enrich the shared knowledge the fleet relies on.
- **US-0340** *(Team Lead — P1)* — As a Team Lead, I want a project to define expected deliverables up front as a checklist, so that I can see which required outputs are still outstanding.
- **US-0341** *(Operator — P2)* — As an Operator, I want a deliverable to support versioning so a resubmission after rejection creates a new version rather than overwriting, so that the full revision history of an output is preserved.
- **US-0342** *(Requester — P2)* — As a Requester, I want to leave inline review comments on a deliverable before signing off, so that feedback is captured against the exact output under review.
- **US-0343** *(Platform Admin — P1)* — As a Platform Admin, I want role-based permissions controlling who can accept deliverables, set fleet budgets, and graduate fleets, so that sign-off and governance authority is restricted to the right people.
- **US-0344** *(Tenant Admin — P0)* — As a Tenant Admin, I want fleets, projects, and deliverables scoped strictly to my tenant, so that no other tenant can view or affect my workforce or outputs.
- **US-0345** *(SRE — P1)* — As an SRE, I want fleet-level health metrics (active agents, queue depth, error rate) surfaced on the fleet dashboard, so that I can detect a degraded fleet before it impacts deliverables.
- **US-0346** *(SRE — P2)* — As an SRE, I want a fleet's oversight pause to drain in-flight goals gracefully rather than killing them, so that pausing for maintenance does not corrupt partial work.
- **US-0347** *(Security Engineer — P1)* — As a Security Engineer, I want deliverable exports to redact secrets and PII according to tenant policy before download, so that exporting an output cannot leak sensitive data.
- **US-0348** *(Compliance Officer — P2)* — As a Compliance Officer, I want a retention policy on archived projects that controls how long deliverables and their audit records are kept, so that retention obligations are enforced automatically.
- **US-0349** *(Executive — P1)* — As an Executive, I want a fleet roll-up of total budget consumed versus value delivered (accepted deliverables), so that I can judge return on the autonomous workforce.
- **US-0350** *(Platform Admin — P2)* — As a Platform Admin, I want to clone an existing fleet's configuration (agents, budget, memory scope) into a new fleet, so that I can stand up a proven workforce template without rebuilding it from scratch.

---

## Epic 08 — Observability & Oversight

- **US-0351** *(Operator — P0)* — As an Operator, I want the `/overview` dashboard to show a single live count of running, queued, blocked, and failed goals, so that I can assess fleet health at a glance without opening each goal.
- **US-0352** *(Operator — P1)* — As an Operator, I want the overview cards to auto-refresh without a manual page reload, so that the numbers I act on are never stale.
- **US-0353** *(Team Lead — P1)* — As a Team Lead, I want the overview filtered to only my team's agents and goals, so that I see my unit's workload instead of the whole tenant.
- **US-0354** *(Executive — P2)* — As an Executive, I want an overview summary tile showing today's completed goals versus the 7-day average, so that I can spot throughput trends without reading individual runs.
- **US-0355** *(Operator — P0)* — As an Operator, I want the `/oversight` view to list every currently running agent with its goal, role, and elapsed time, so that I know exactly what the workforce is doing right now.
- **US-0356** *(Operator — P0)* — As an Operator, I want to pause a running agent from the oversight view, so that I can halt work that looks wrong before it consumes more budget.
- **US-0357** *(Operator — P1)* — As an Operator, I want to resume a previously paused agent from oversight, so that I can let approved work continue without recreating the goal.
- **US-0358** *(Team Lead — P0)* — As a Team Lead, I want to cancel a runaway goal from the oversight view with a confirmation prompt, so that I can stop wasted spend without accidental clicks.
- **US-0359** *(Operator — P1)* — As an Operator, I want oversight to flag any agent that has been on the same step longer than a threshold, so that I can intervene on stuck work early.
- **US-0360** *(Security Engineer — P1)* — As a Security Engineer, I want oversight to surface which tools each running agent currently holds permission to call, so that I can detect over-privileged executions in flight.
- **US-0361** *(Operator — P0)* — As an Operator, I want a real-time activity feed of agent actions across the fleet, so that I can watch the workforce act as events happen.
- **US-0362** *(Operator — P1)* — As an Operator, I want to filter the live activity feed by agent, role, goal, or tenant, so that I can focus on a single thread of work.
- **US-0363** *(Operator — P2)* — As an Operator, I want to pause and resume the live activity feed scroll, so that I can read a fast-moving event without losing my place.
- **US-0364** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want each activity feed entry to carry a stable episode and event ID, so that I can correlate UI events with backend logs.
- **US-0365** *(Operator — P0)* — As an Operator, I want an episode timeline for a goal showing each step, tool call, and decision in order, so that I can understand how the agent reached its current state.
- **US-0366** *(Team Lead — P1)* — As a Team Lead, I want the episode timeline to show wall-clock duration per step, so that I can identify which steps are slow.
- **US-0367** *(Compliance Officer — P1)* — As a Compliance Officer, I want each episode timeline entry to link to the governing policy or budget check that approved it, so that I can verify oversight controls fired.
- **US-0368** *(Agent Author — P0)* — As an Agent Author, I want to open `/replay` for a finished run and step through every prompt, tool call, and result, so that I can debug why my agent behaved as it did.
- **US-0369** *(Agent Author — P1)* — As an Agent Author, I want replay to let me jump to a specific step by index or event ID, so that I can reach the failure point without scrubbing the whole run.
- **US-0370** *(Agent Author — P2)* — As an Agent Author, I want replay to diff the world-model state before and after each step, so that I can see exactly what the agent changed.
- **US-0371** *(External Auditor — P1)* — As an External Auditor, I want replay to be read-only and to record that I viewed a run, so that observation cannot alter evidence and my access is itself auditable.
- **US-0372** *(Compliance Officer — P2)* — As a Compliance Officer, I want to export a replay transcript as a signed, timestamped artifact, so that I can attach it to a compliance case.
- **US-0373** *(Operator — P1)* — As an Operator, I want the `/discovery` view to list all registered agents, roles, and packs available in my tenant, so that I can find the right capability to assign work.
- **US-0374** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want discovery to show each pack's suite, version, and last-validated date, so that I can spot stale or unverified capabilities.
- **US-0375** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want to search discovery by capability tag or tool name, so that I can locate an agent that already does what I need.
- **US-0376** *(Tenant Admin — P2)* — As a Tenant Admin, I want discovery to indicate which packs are enabled versus available for my tenant, so that I can manage the active catalog.
- **US-0377** *(SRE — P0)* — As an SRE, I want `/healthz` to return overall service health with a 200 or 503 status, so that my load balancer can route traffic away from a degraded instance.
- **US-0378** *(SRE — P0)* — As an SRE, I want `/livez` to report whether the process is alive independent of dependencies, so that my orchestrator restarts only truly dead pods.
- **US-0379** *(SRE — P0)* — As an SRE, I want `/readyz` to fail until migrations and the world DB are reachable, so that traffic is held back until the instance can actually serve.
- **US-0380** *(Security Engineer — P1)* — As a Security Engineer, I want the health endpoints to remain auth-exempt but redact internal detail when a dashboard token is configured, so that probes work without leaking topology.
- **US-0381** *(SRE — P1)* — As an SRE, I want `/healthz` to report degraded (503) when no LLM provider key is configured, so that I am alerted to a misconfigured deployment before users hit failures.
- **US-0382** *(SRE — P0)* — As an SRE, I want a Prometheus-style `/metrics` endpoint exposing goal, latency, error, and budget counters, so that I can scrape fleet telemetry into my existing monitoring stack.
- **US-0383** *(FinOps Owner — P1)* — As a FinOps Owner, I want `/metrics` to emit per-tenant token and dollar spend counters, so that I can build chargeback dashboards from standard scraping.
- **US-0384** *(SRE — P2)* — As an SRE, I want `/metrics` to label series by role and tool so that I can break down latency and error rates by capability in Grafana.
- **US-0385** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want to subscribe to a single goal's event stream over a stable streaming endpoint, so that I can mirror its progress into my own application.
- **US-0386** *(Operator — P1)* — As an Operator, I want to watch one goal's live event stream in the dashboard and have it reconnect automatically after a network blip, so that I never miss events during a long-running goal.
- **US-0387** *(Requester — P2)* — As a Requester, I want to follow the live status of the goal I submitted without operator access, so that I know when my request is progressing or needs input.
- **US-0388** *(Operator — P0)* — As an Operator, I want an alert when any goal becomes stuck on a step past a configurable timeout, so that I can intervene before it stalls the queue.
- **US-0389** *(Team Lead — P0)* — As a Team Lead, I want an alert when a goal enters a blocked state awaiting approval, so that I can unblock my team's work quickly.
- **US-0390** *(SRE — P1)* — As an SRE, I want an alert when a goal's failure rate over a rolling window exceeds a threshold, so that I catch systemic regressions rather than one-off errors.
- **US-0391** *(Platform Admin — P1)* — As a Platform Admin, I want to configure alert thresholds and routing (email, webhook, channel) per condition, so that the right team is notified for each kind of problem.
- **US-0392** *(Platform Admin — P2)* — As a Platform Admin, I want to snooze or acknowledge an active alert so that it stops re-paging while a known incident is being worked.
- **US-0393** *(Operator — P0)* — As an Operator, I want to drill down from any metric on the overview straight to the agent and episode responsible for it, so that I can investigate a spike without manual log hunting.
- **US-0394** *(FinOps Owner — P1)* — As a FinOps Owner, I want to click a cost spike in the perf view and land on the specific run that caused it, so that I can attribute and act on overspend.
- **US-0395** *(Team Lead — P2)* — As a Team Lead, I want to drill from an error-rate chart to the list of failing episodes behind it, so that I can triage the actual failures.
- **US-0396** *(SRE — P1)* — As an SRE, I want the `/perf` view to show p50/p95/p99 step and tool-call latency over a selectable time range, so that I can quantify performance and spot regressions.
- **US-0397** *(Executive — P2)* — As an Executive, I want the perf view to compare this week's throughput and success rate against last week, so that I can report on workforce performance trends.
- **US-0398** *(Operator — P0)* — As an Operator, I want real-time visibility of each tool call an agent makes, including arguments and result status, as it happens, so that I can catch dangerous or wrong tool use immediately.
- **US-0399** *(Security Engineer — P1)* — As a Security Engineer, I want sensitive arguments in the live tool-call view to be redacted according to policy, so that observers cannot read secrets passed to tools.
- **US-0400** *(Compliance Officer — P1)* — As a Compliance Officer, I want every observability action I take (replay open, export, alert ack) recorded in the signed audit log, so that oversight activity is itself provably governed.

---

## Epic 09 — Spend & FinOps

- **US-0401** *(Platform Admin — P0)* — As a Platform Admin, I want budget caps to be enforced inside `record_tokens` at the moment usage is recorded, so that a goal cannot overshoot its limit between explicit `check()` calls.
- **US-0402** *(Operator — P0)* — As an Operator, I want a goal to hard-stop the instant its `max_dollars` cap is crossed, so that runaway spend is contained without manual intervention.
- **US-0403** *(Operator — P0)* — As an Operator, I want a goal to hard-stop when its `max_output_tokens` cap is reached, so that a looping agent cannot burn unbounded tokens.
- **US-0404** *(Operator — P1)* — As an Operator, I want a goal to hard-stop when its `max_wall_clock` cap elapses, so that a stuck agent cannot run indefinitely and accrue idle cost.
- **US-0405** *(Operator — P1)* — As an Operator, I want a goal to hard-stop when its `max_tool_calls` cap is exceeded, so that a tool-thrashing agent is bounded regardless of token spend.
- **US-0406** *(Security Engineer — P0)* — As a Security Engineer, I want the budget enforcement path to have no bypass flag or override that skips `budget.check()`, so that the cap guarantee cannot be silently disabled in production.
- **US-0407** *(Agent Author — P1)* — As an Agent Author, I want a clear typed BudgetExceeded error raised when any cap trips, so that my agent code can distinguish a budget stop from a real failure.
- **US-0408** *(Agent Author — P1)* — As an Agent Author, I want to set all four caps (tokens, dollars, wall-clock, tool calls) when I create a goal, so that I control every dimension of spend up front.
- **US-0409** *(Operator — P2)* — As an Operator, I want the budget to record partial usage even when the cap trips mid-step, so that the spend ledger reflects what was actually consumed.
- **US-0410** *(FinOps Owner — P0)* — As a FinOps Owner, I want a `/spend` dashboard showing total spend over a selectable time window, so that I can see current burn at a glance.
- **US-0411** *(FinOps Owner — P1)* — As a FinOps Owner, I want the `/spend` dashboard to break cost down per goal, so that I can identify which goals are most expensive.
- **US-0412** *(Team Lead — P1)* — As a Team Lead, I want the `/spend` dashboard to break cost down per agent, so that I can see which specialist packs drive my team's spend.
- **US-0413** *(FinOps Owner — P1)* — As a FinOps Owner, I want the `/spend` dashboard to break cost down per tag, so that I can attribute spend to projects, cost centers, or campaigns.
- **US-0414** *(FinOps Owner — P2)* — As a FinOps Owner, I want to filter the `/spend` dashboard by date range, tenant, and tag simultaneously, so that I can isolate spend for a specific slice of activity.
- **US-0415** *(FinOps Owner — P0)* — As a FinOps Owner, I want to export a cost CSV from the `/spend` dashboard, so that I can load actuals into our finance system for chargeback.
- **US-0416** *(FinOps Owner — P2)* — As a FinOps Owner, I want the cost CSV to include per-row goal id, agent, tag, model, tokens, and dollars, so that downstream allocation is unambiguous.
- **US-0417** *(External Auditor — P2)* — As an External Auditor, I want the cost CSV export to be reproducible for a closed period, so that re-exporting yesterday's data yields identical figures.
- **US-0418** *(FinOps Owner — P1)* — As a FinOps Owner, I want cost anomaly detection that flags goals whose spend deviates sharply from their historical baseline, so that I catch cost regressions before the invoice.
- **US-0419** *(SRE — P1)* — As an SRE, I want a spend-spike alert fired when hourly spend exceeds a configured threshold, so that I am paged before a runaway fleet drains the budget overnight.
- **US-0420** *(FinOps Owner — P2)* — As a FinOps Owner, I want anomaly detection to suppress flags during known-busy windows I define, so that expected end-of-month batch runs do not generate false alarms.
- **US-0421** *(Operator — P1)* — As an Operator, I want a cost-preview for a goal before I run it, so that I can see the estimated spend and decide whether to proceed.
- **US-0422** *(Operator — P2)* — As an Operator, I want the cost-preview to show a low/expected/high range, so that I understand the uncertainty in the estimate.
- **US-0423** *(Team Lead — P1)* — As a Team Lead, I want a cost-breakdown for a goal after it runs, itemized by step and tool, so that I can see exactly where the money went.
- **US-0424** *(Agent Author — P2)* — As an Agent Author, I want the cost-breakdown to attribute model spend per role, so that I can tune which role uses which model.
- **US-0425** *(FinOps Owner — P1)* — As a FinOps Owner, I want budget-tune recommendations that suggest revised caps based on observed usage, so that caps are tight without falsely stopping legitimate goals.
- **US-0426** *(Operator — P2)* — As an Operator, I want budget-tune recommendations to explain why each suggested cap was chosen, so that I can trust and apply the change confidently.
- **US-0427** *(Team Lead — P2)* — As a Team Lead, I want to apply a budget-tune recommendation to a goal template with one action, so that future runs inherit the tightened caps.
- **US-0428** *(Tenant Admin — P0)* — As a Tenant Admin, I want a per-tenant budget cap that aggregates spend across all goals in my tenant, so that a single tenant cannot exceed its allocation.
- **US-0429** *(Platform Admin — P1)* — As a Platform Admin, I want a per-fleet budget cap that bounds spend across an external agent fleet, so that fleet usage stays within its contracted limit.
- **US-0430** *(Tenant Admin — P1)* — As a Tenant Admin, I want new goals to be rejected once my tenant budget is exhausted, so that overspend is structurally impossible.
- **US-0431** *(Platform Admin — P2)* — As a Platform Admin, I want per-tenant and per-fleet budgets to roll over (or reset) on a configurable cycle, so that allocations align with our billing period.
- **US-0432** *(FinOps Owner — P1)* — As a FinOps Owner, I want a `/billing` view that summarizes accrued charges per tenant for the current period, so that I can reconcile against contracts.
- **US-0433** *(Executive — P2)* — As an Executive, I want the `/billing` view to show period-over-period spend trend, so that I can see whether costs are growing or shrinking.
- **US-0434** *(Tenant Admin — P2)* — As a Tenant Admin, I want to download an itemized invoice from `/billing` for my tenant, so that I can submit it to my finance department.
- **US-0435** *(Compliance Officer — P2)* — As a Compliance Officer, I want every cap change and budget override request to be written to the signed audit log, so that spend governance decisions are provable after the fact.
- **US-0436** *(FinOps Owner — P1)* — As a FinOps Owner, I want a spend forecast that projects end-of-period cost from current burn rate, so that I can flag overruns while there is still time to act.
- **US-0437** *(Executive — P2)* — As an Executive, I want the spend forecast to show projected cost against budgeted cost with a confidence band, so that I can decide whether to intervene.
- **US-0438** *(FinOps Owner — P3)* — As a FinOps Owner, I want forecasts broken down per tenant, so that I know which tenant is on track to breach its allocation.
- **US-0439** *(Executive — P1)* — As an Executive, I want an ROI / cost-avoided report that estimates labor cost displaced by completed goals, so that I can justify continued investment in the platform.
- **US-0440** *(Team Lead — P2)* — As a Team Lead, I want cost-avoided figures attributable to my team's goals, so that I can demonstrate my team's value in reviews.
- **US-0441** *(FinOps Owner — P2)* — As a FinOps Owner, I want to compare actual spend against cost-avoided to compute net value, so that I can rank suites by return.
- **US-0442** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want a CLI command `maverick spend` that prints cost per goal/agent/tag, so that I can pull FinOps data into scripts without the dashboard.
- **US-0443** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want an MCP resource exposing current budget and spend for a goal, so that an external agent can self-throttle before it is hard-stopped.
- **US-0444** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want the TS SDK to surface a BudgetExceeded result and remaining-budget fields, so that my channel integration can react gracefully to a cap stop.
- **US-0445** *(SRE — P1)* — As an SRE, I want the spend-spike alert to route to my channels integration (Slack/email), so that the right on-call sees it immediately.
- **US-0446** *(Security Engineer — P2)* — As a Security Engineer, I want budget and billing data redacted for unauthorized roles on the dashboard, so that cost figures are exposed only to those with FinOps permissions.
- **US-0447** *(Compliance Officer — P3)* — As a Compliance Officer, I want a quarterly spend report bundling actuals, anomalies, and forecast accuracy, so that I can present FinOps governance to the board.
- **US-0448** *(Tenant Admin — P2)* — As a Tenant Admin, I want a configurable soft-warning threshold (for example 80 percent of budget) that notifies me before the hard stop, so that I can request an increase proactively.
- **US-0449** *(Platform Admin — P3)* — As a Platform Admin, I want a config knob and an installer-wizard step for default budget caps, so that fresh deployments ship with safe spend limits out of the box.
- **US-0450** *(Requester — P3)* — As a Requester, I want to see the estimated cost of a goal I submit through a channel before it is queued, so that I understand the spend my request will incur.

---

## Epic 10 — Providers & Models

- **US-0451** *(Platform Admin — P0)* — As a Platform Admin, I want to open the `/providers` screen and see every configured AI provider with its status, so that I can audit which providers are active at a glance.
- **US-0452** *(Platform Admin — P0)* — As a Platform Admin, I want to add a new AI provider from `/providers` by entering its name and base URL, so that I can onboard a provider without editing files by hand.
- **US-0453** *(Security Engineer — P0)* — As a Security Engineer, I want API keys I enter on `/providers` to be written only to `~/.maverick/.env` and never to `config.toml`, so that secrets stay out of version-controlled config.
- **US-0454** *(Security Engineer — P0)* — As a Security Engineer, I want `config.toml` to reference keys by env-var name rather than literal value, so that the config file can be shared or committed without leaking credentials.
- **US-0455** *(Platform Admin — P1)* — As a Platform Admin, I want the `/providers` screen to mask stored API keys showing only the last four characters, so that I can confirm a key is set without exposing it on screen.
- **US-0456** *(Platform Admin — P0)* — As a Platform Admin, I want to validate a provider key by pinging the provider from `/providers`, so that I get immediate confirmation the credential works before relying on it.
- **US-0457** *(Operator — P1)* — As an Operator, I want the key-validation ping to report a clear reason on failure (auth, network, rate-limit), so that I can fix the right problem instead of guessing.
- **US-0458** *(Platform Admin — P0)* — As a Platform Admin, I want to map each role to a `provider:model-id` pair in the `[models]` table of `config.toml`, so that every role runs on a deliberately chosen model.
- **US-0459** *(Agent Author — P1)* — As an Agent Author, I want to set a per-role model override for a role I own without touching other roles' mappings, so that I can tune my role independently.
- **US-0460** *(Platform Admin — P1)* — As a Platform Admin, I want a single default model that applies to any role lacking an explicit `[models]` entry, so that new roles work out of the box.
- **US-0461** *(Operator — P1)* — As an Operator, I want the install wizard to prompt me to choose a model for each role from the providers I configured, so that I never finish setup with an unrouted role.
- **US-0462** *(Operator — P2)* — As an Operator, I want the wizard to suggest a sensible default model per role that I can accept with one keystroke, so that I can complete setup quickly.
- **US-0463** *(Operator — P1)* — As an Operator, I want the wizard to skip providers I have no key for and warn me, so that I don't accidentally map a role to an unusable provider.
- **US-0464** *(SRE — P0)* — As an SRE, I want the router to automatically fall back to a secondary model when the primary provider returns an error, so that a single provider outage does not halt work.
- **US-0465** *(SRE — P0)* — As an SRE, I want the router to fall back when a provider rate-limits (HTTP 429), so that bursts of load degrade gracefully instead of failing.
- **US-0466** *(Platform Admin — P1)* — As a Platform Admin, I want to define an ordered fallback chain per role, so that I control exactly which models are tried and in what sequence.
- **US-0467** *(SRE — P1)* — As an SRE, I want fallback events recorded with the failing provider, error class, and the model that served the request, so that I can diagnose provider reliability after the fact.
- **US-0468** *(SRE — P2)* — As an SRE, I want the router to retry the primary provider after a configurable cooldown following a fallback, so that we return to the preferred model once it recovers.
- **US-0469** *(FinOps Owner — P1)* — As a FinOps Owner, I want to mix providers across roles (a cheap model for routine roles, a premium model for critical roles), so that I optimize spend without sacrificing quality where it matters.
- **US-0470** *(Team Lead — P2)* — As a Team Lead, I want to compare two candidate models for the same role side by side on cost and latency, so that I can pick the better fit for my team's workload.
- **US-0471** *(Agent Author — P1)* — As an Agent Author, I want to set adaptive thinking/effort level per role, so that reasoning-heavy roles think harder while simple roles stay fast and cheap.
- **US-0472** *(Agent Author — P1)* — As an Agent Author, I want to set the temperature per role, so that deterministic roles stay precise and creative roles can vary.
- **US-0473** *(Operator — P2)* — As an Operator, I want safe default thinking and temperature values applied when I leave them unset, so that roles behave reasonably without manual tuning.
- **US-0474** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want requests shaped to be cache-aware (stable prefixes, reused system blocks), so that repeated calls hit the provider's prompt cache and cost less.
- **US-0475** *(FinOps Owner — P2)* — As a FinOps Owner, I want cache-hit savings surfaced per role, so that I can see the financial benefit of cache-aware shaping.
- **US-0476** *(Platform Admin — P0)* — As a Platform Admin, I want to switch a role's provider without re-stating its installed packs, so that migrating models is a config change, not a reinstall.
- **US-0477** *(Tenant Admin — P1)* — As a Tenant Admin, I want to swap the provider for my whole tenant in one action, so that I can move off a deprecated provider quickly.
- **US-0478** *(SRE — P1)* — As an SRE, I want a provider health indicator on `/providers` reflecting recent ping and error rates, so that I can spot a degrading provider before it impacts roles.
- **US-0479** *(SRE — P2)* — As an SRE, I want the router to mark a provider unhealthy after consecutive failures and route around it, so that a flapping provider stops dragging down latency.
- **US-0480** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want to register a local-runtime model (e.g. a localhost OpenAI-compatible endpoint) as a provider, so that I can run roles fully offline.
- **US-0481** *(Security Engineer — P2)* — As a Security Engineer, I want local-runtime providers to require no API key and be clearly labeled as local, so that air-gapped deployments are obviously distinguished from cloud ones.
- **US-0482** *(Operator — P1)* — As an Operator, I want to list the available models for a configured provider on `/providers`, so that I can pick a valid model-id without memorizing it.
- **US-0483** *(Operator — P2)* — As an Operator, I want the UI to reject an unknown or malformed `provider:model-id` string before saving, so that I never persist a mapping the router can't resolve.
- **US-0484** *(Compliance Officer — P1)* — As a Compliance Officer, I want every provider, model, and key change recorded in an audit trail with actor and timestamp, so that I can prove who changed routing and when.
- **US-0485** *(External Auditor — P2)* — As an External Auditor, I want an exportable report of current role-to-model mappings and their provider regions, so that I can verify data-residency commitments.
- **US-0486** *(Compliance Officer — P1)* — As a Compliance Officer, I want to restrict which providers a tenant may use to an approved allowlist, so that roles cannot be pointed at unvetted providers.
- **US-0487** *(Tenant Admin — P2)* — As a Tenant Admin, I want my tenant's provider keys isolated from other tenants, so that one tenant's credentials are never usable by another.
- **US-0488** *(FinOps Owner — P1)* — As a FinOps Owner, I want to set a per-provider spend cap that triggers fallback to a cheaper model when exceeded, so that runaway cost on one provider is bounded.
- **US-0489** *(Executive — P2)* — As an Executive, I want a one-line summary of which providers power the workforce and their combined monthly cost, so that I understand our model footprint without reading config.
- **US-0490** *(Platform Admin — P2)* — As a Platform Admin, I want to rotate a provider API key in place and have the validation ping re-run automatically, so that key rotation is verified in one step.
- **US-0491** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want the TS SDK to read the same `[models]` mapping the CLI uses, so that an SDK-driven agent routes identically to a CLI-driven one.
- **US-0492** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want the MCP server to expose the resolved provider and model for a role on request, so that external tools can confirm routing programmatically.
- **US-0493** *(Operator — P2)* — As an Operator, I want `maverick doctor` to flag roles whose mapped provider has no usable key, so that misconfiguration surfaces in a routine health check.
- **US-0494** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to pin a long-context model for knowledge-retrieval roles specifically, so that large-document tasks use a model sized for them.
- **US-0495** *(Requester — P3)* — As a Requester, I want to optionally request a higher-effort model for a single sensitive task, so that I get extra reasoning quality when it matters without changing global config.
- **US-0496** *(Team Lead — P2)* — As a Team Lead, I want to preview the effective model, effort, and temperature for each of my team's roles after resolving defaults and overrides, so that I can confirm the final routing.
- **US-0497** *(Security Engineer — P1)* — As a Security Engineer, I want provider keys redacted from all logs and error messages, so that a captured log or stack trace never exposes a credential.
- **US-0498** *(Platform Admin — P2)* — As a Platform Admin, I want changes on `/providers` to be validated and applied atomically to `config.toml` and `.env`, so that a failed save never leaves routing half-updated.
- **US-0499** *(SRE — P2)* — As an SRE, I want to trigger a bulk validation ping across all configured providers from `/providers`, so that I can verify the whole provider fleet before a release.
- **US-0500** *(FinOps Owner — P3)* — As a FinOps Owner, I want a recommendation that flags roles over-provisioned on an expensive model relative to their token usage, so that I can downshift them to a cheaper provider:model pair.

---

## Epic 11 — Benchmarks & Evaluation

- **US-0501** *(Operator — P0)* — As an Operator, I want to open the `/benchmarks` screen and see the latest run's overall score, pass rate, and timestamp at a glance, so that I can tell whether the current fleet is performing within expectations.
- **US-0502** *(Operator — P1)* — As an Operator, I want each benchmark row on `/benchmarks` to link to its per-case breakdown of pass/fail/score, so that I can drill into exactly which cases dragged the aggregate down.
- **US-0503** *(SRE — P0)* — As an SRE, I want continuous benchmarking to run automatically on a schedule and after every release deploy, so that scoring drift is detected without anyone manually kicking off a run.
- **US-0504** *(SRE — P1)* — As an SRE, I want a continuous-benchmark run to be retried or quarantined when the LLM provider returns transient errors, so that flaky infrastructure is not misreported as a quality regression.
- **US-0505** *(Agent Author — P0)* — As an Agent Author, I want to run `domains-eval --check` locally against the behavioral golden cases, so that I can confirm my pack changes still produce the expected behaviors before I open a PR.
- **US-0506** *(Agent Author — P1)* — As an Agent Author, I want `domains-eval --check` to print a clear diff of expected vs actual behavior for each failing golden case, so that I can see precisely which assertion broke and why.
- **US-0507** *(Platform Admin — P0)* — As a Platform Admin, I want CI to fail the build when `domains-eval --check` reports any golden-case regression, so that no pack that breaks established behavior can merge to the catalog.
- **US-0508** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want to add a new behavioral golden case with an input, expected behavior, and rationale, so that newly discovered correct behaviors are locked in against future regressions.
- **US-0509** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to mark a golden case as deprecated with a reason and removal date, so that obsolete expectations are retired in a governed way rather than silently deleted.
- **US-0510** *(Agent Author — P0)* — As an Agent Author, I want to run `domains-lint` over the specialist catalog, so that structural and metadata errors in my pack definition are caught before audit.
- **US-0511** *(Platform Admin — P0)* — As a Platform Admin, I want `domains-lint` to enforce that every one of the 2,020 specialist packs has a unique id, suite assignment, and required fields, so that the catalog stays internally consistent across all 53 suites.
- **US-0512** *(Compliance Officer — P1)* — As a Compliance Officer, I want `domains-audit` to flag packs that lack a documented owner or governance tag, so that every specialist in the catalog is attributable and accountable.
- **US-0513** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want `domains-audit` to report packs with overlapping or contradictory scopes across suites, so that I can resolve catalog ambiguity before it confuses routing.
- **US-0514** *(Agent Author — P2)* — As an Agent Author, I want `domains-lint` to warn when my pack references a tool or capability that is not registered, so that I catch dangling dependencies at lint time.
- **US-0515** *(Team Lead — P0)* — As a Team Lead, I want regression detection to compare the current release's benchmark scores against the previous release and surface any case that dropped beyond a threshold, so that I know whether to block the rollout.
- **US-0516** *(Team Lead — P1)* — As a Team Lead, I want regression detection to distinguish a true score drop from statistical noise using a configurable significance margin, so that I am not paged for sub-threshold jitter.
- **US-0517** *(Platform Admin — P1)* — As a Platform Admin, I want the regression report to name the specific release pair, commit, and dataset version it compared, so that every regression finding is traceable to exact inputs.
- **US-0518** *(Executive — P2)* — As an Executive, I want a single red/green regression verdict per release summarized at the top of `/benchmarks`, so that I can approve or hold a release without reading the case-level detail.
- **US-0519** *(Operator — P0)* — As an Operator, I want to launch an A/B evaluation that runs a treatment arm against a frozen-learning control arm using `MAVERICK_LEARNING_FROZEN`, so that I can isolate the effect of a change from ongoing self-improvement.
- **US-0520** *(Agent Author — P1)* — As an Agent Author, I want the frozen-learning control arm to be guaranteed not to update its memory or weights during the A/B run, so that the control is a stable baseline I can trust.
- **US-0521** *(Team Lead — P1)* — As a Team Lead, I want the A/B evaluation to report per-arm win rate, mean score, and confidence interval, so that I can decide whether the treatment is a real improvement.
- **US-0522** *(Compliance Officer — P2)* — As a Compliance Officer, I want every A/B run to record that `MAVERICK_LEARNING_FROZEN` was set on the control arm in the signed learning audit, so that the experiment's integrity is provable after the fact.
- **US-0523** *(SRE — P0)* — As an SRE, I want each benchmark run to record its full reproducibility manifest — dataset version, model ids, seed, config hash, and pack catalog snapshot — so that any run can be rerun deterministically.
- **US-0524** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want to rerun a past benchmark by its run id and get a byte-identical scoring manifest where execution is deterministic, so that I can reproduce a reported result without guessing the setup.
- **US-0525** *(External Auditor — P1)* — As an External Auditor, I want to verify that a published benchmark score corresponds to its recorded manifest hash, so that I can independently confirm the result was not tampered with.
- **US-0526** *(Requester — P1)* — As a Requester, I want a deliverable I submitted to be scored objectively against an explicit rubric with per-criterion scores, so that I understand why it passed or failed rather than getting a single opaque number.
- **US-0527** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to define and version the scoring rubric used to evaluate deliverables, so that scoring criteria evolve under change control rather than ad hoc.
- **US-0528** *(Team Lead — P2)* — As a Team Lead, I want objective deliverable scoring to flag low inter-rater agreement when an LLM judge and a reference scorer disagree, so that ambiguous rubrics get reviewed instead of silently passing.
- **US-0529** *(Operator — P0)* — As an Operator, I want to select two benchmark runs and see a side-by-side comparison of aggregate and per-case scores, so that I can understand exactly what changed between them.
- **US-0530** *(Operator — P1)* — As an Operator, I want the run-comparison view to highlight cases that flipped from pass to fail and fail to pass, so that I can focus on the cases that actually moved.
- **US-0531** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want to export a two-run comparison as JSON via the API, so that I can feed benchmark deltas into my own release pipeline.
- **US-0532** *(Team Lead — P0)* — As a Team Lead, I want to evaluate a new specialist pack against the benchmark suite in a staging context before rollout, so that I can gate its promotion on measured quality.
- **US-0533** *(Platform Admin — P1)* — As a Platform Admin, I want a new pack's pre-rollout evaluation to be blocked from promotion unless it meets or exceeds the incumbent pack's score on overlapping cases, so that rollouts never regress coverage.
- **US-0534** *(Security Engineer — P1)* — As a Security Engineer, I want a new pack's pre-rollout evaluation to include adversarial and safety cases, so that a pack cannot be promoted if it introduces a security regression.
- **US-0535** *(Executive — P1)* — As an Executive, I want a leaderboard ranking packs and suites by current benchmark score, so that I can see which parts of the workforce are strongest and where to invest.
- **US-0536** *(Team Lead — P1)* — As a Team Lead, I want a trend chart of benchmark score over time per suite, so that I can tell whether quality is improving, flat, or degrading across releases.
- **US-0537** *(Operator — P2)* — As an Operator, I want to annotate a point on the trend chart with the release or change that caused a jump or drop, so that future viewers understand what drove the inflection.
- **US-0538** *(FinOps Owner — P1)* — As a FinOps Owner, I want each benchmark run to report token and dollar cost alongside its score, so that I can evaluate quality per dollar rather than quality alone.
- **US-0539** *(FinOps Owner — P2)* — As a FinOps Owner, I want a benchmark run to respect a configurable budget cap and abort cleanly if it would exceed it, so that an evaluation never runs up an unbounded bill.
- **US-0540** *(Knowledge Steward — P0)* — As a Knowledge Steward, I want to register and version eval datasets with a checksum and provenance record, so that everyone evaluates against a known, immutable dataset version.
- **US-0541** *(Compliance Officer — P1)* — As a Compliance Officer, I want eval datasets containing sensitive data to be tagged and access-controlled, so that evaluation never exposes regulated content to unauthorized roles.
- **US-0542** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to detect overlap between an eval dataset and training/learning data, so that I can prevent contamination that would inflate scores.
- **US-0543** *(Tenant Admin — P1)* — As a Tenant Admin, I want benchmark runs and `/benchmarks` results scoped to my tenant, so that one tenant's evaluation data is never visible to or comingled with another's.
- **US-0544** *(Tenant Admin — P2)* — As a Tenant Admin, I want to run the standard benchmark suite against my tenant's own packs and datasets, so that I can measure my configuration rather than only the global baseline.
- **US-0545** *(Security Engineer — P2)* — As a Security Engineer, I want a dedicated red-team benchmark suite of prompt-injection and exfiltration cases, so that I can track the fleet's resistance to attacks over time.
- **US-0546** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want a stable API and CLI to trigger a benchmark run and poll its status and result, so that I can wire evaluation into external CI without scraping the dashboard.
- **US-0547** *(SRE — P1)* — As an SRE, I want a benchmark run to emit a webhook or notification on completion with its verdict, so that downstream gates react automatically instead of polling.
- **US-0548** *(External Auditor — P2)* — As an External Auditor, I want read-only access to historical benchmark runs, their manifests, and verdicts, so that I can audit the evaluation program without write access to the platform.
- **US-0549** *(Platform Admin — P1)* — As a Platform Admin, I want to define pass/fail gate thresholds per suite that block a release when continuous benchmarking falls below them, so that quality gates are policy, not tribal knowledge.
- **US-0550** *(Compliance Officer — P0)* — As a Compliance Officer, I want every benchmark and evaluation run to be appended to the Operating Record with its manifest, verdict, and approver, so that the platform's evaluation history is complete and provable for audit.

---

## Epic 12 — Self-Learning (Dream / Hindsight / Proof)

- **US-0551** *(Operator — P1)* — As an Operator, I want to run `maverick dream` on demand to consolidate recent task experience into reusable insights, so that future runs benefit from what the fleet already learned.
- **US-0552** *(Operator — P0)* — As an Operator, I want dream consolidation to be opt-in for any LLM-in-the-loop step via an explicit flag, so that no experience is sent to a model without my consent.
- **US-0553** *(Platform Admin — P1)* — As a Platform Admin, I want to schedule `maverick dream` to run nightly during low-traffic windows, so that consolidation happens automatically without competing with production workloads.
- **US-0554** *(Agent Author — P1)* — As an Agent Author, I want consolidated insights written to `~/.maverick/dreams/` in a documented format, so that I can inspect, edit, and version the learned guidance my agents receive.
- **US-0555** *(Operator — P2)* — As an Operator, I want `maverick dream --dry-run` to preview which trajectories would be consolidated and the resulting insights, so that I can review impact before mutating the learning state.
- **US-0556** *(Team Lead — P1)* — As a Team Lead, I want dream to group experiences by role and task type before consolidation, so that insights are scoped to the agents that will actually use them.
- **US-0557** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want to tag, rename, and retire individual consolidated insights in `~/.maverick/dreams/`, so that stale or low-quality guidance does not pollute future runs.
- **US-0558** *(Operator — P1)* — As an Operator, I want a rehearsal queue that replays candidate insights against held-out tasks before they go live, so that only insights that demonstrably help are promoted.
- **US-0559** *(Team Lead — P2)* — As a Team Lead, I want to inspect and reorder the rehearsal queue, so that I can prioritize validating the insights most relevant to upcoming work.
- **US-0560** *(SRE — P2)* — As an SRE, I want dream consolidation to run within a bounded budget (tokens, dollars, wall-clock), so that a runaway consolidation job cannot exhaust resources.
- **US-0561** *(Operator — P0)* — As an Operator, I want to run `maverick hindsight` to measure whether a recent learning change helped or regressed task outcomes, so that I keep only changes that actually improve performance.
- **US-0562** *(Team Lead — P1)* — As a Team Lead, I want hindsight to report per-task and aggregate deltas in success rate, cost, and latency since the last learning update, so that I can quantify the value of learning.
- **US-0563** *(FinOps Owner — P1)* — As a FinOps Owner, I want hindsight to attribute cost changes to specific learning updates, so that I can tell whether learning is making the fleet cheaper or more expensive.
- **US-0564** *(Operator — P1)* — As an Operator, I want hindsight to flag regressions above a configurable threshold and recommend a rollback, so that a harmful learning change is caught before it spreads.
- **US-0565** *(Compliance Officer — P2)* — As a Compliance Officer, I want hindsight reports persisted with the learning version they evaluate, so that I can audit the evidence behind every promotion or rollback decision.
- **US-0566** *(Executive — P1)* — As an Executive, I want `maverick proof` to produce a report of deliverables shipped, cost avoided, and ROI attributable to self-learning, so that I can justify continued investment.
- **US-0567** *(Executive — P2)* — As an Executive, I want the proof report exportable as a signed PDF and JSON, so that I can share defensible learning ROI numbers with the board.
- **US-0568** *(FinOps Owner — P1)* — As a FinOps Owner, I want proof to compute cost-avoided as the delta between learned-path and baseline-path token spend on matched tasks, so that savings claims are grounded in comparable work.
- **US-0569** *(Team Lead — P2)* — As a Team Lead, I want proof to break down ROI by suite and specialist pack, so that I can see which learned packs drive the most value.
- **US-0570** *(Executive — P2)* — As an Executive, I want proof to show a confidence interval on ROI rather than a single point estimate, so that I do not overclaim savings to stakeholders.
- **US-0571** *(Operator — P0)* — As an Operator, I want every learning update captured as an immutable, named snapshot, so that I can restore the fleet to any prior learning state.
- **US-0572** *(Operator — P0)* — As an Operator, I want `maverick` to roll back to a previous learning snapshot with a single command, so that I can recover instantly when a learning change degrades quality.
- **US-0573** *(Platform Admin — P1)* — As a Platform Admin, I want to list, diff, and annotate learning snapshots, so that I can understand what changed between any two learning states before rolling back.
- **US-0574** *(SRE — P1)* — As an SRE, I want rollback to a learning snapshot to be atomic and verified against a checksum, so that a partial restore can never leave the fleet in an inconsistent learning state.
- **US-0575** *(Platform Admin — P2)* — As a Platform Admin, I want a retention policy for learning snapshots with configurable count and age limits, so that snapshot storage does not grow unbounded.
- **US-0576** *(Compliance Officer — P0)* — As a Compliance Officer, I want every learning event recorded in a signed, append-only learning audit trail, so that I can prove the integrity and provenance of all learning changes.
- **US-0577** *(External Auditor — P0)* — As an External Auditor, I want to independently verify the signatures on the learning audit trail with a published public key, so that I can confirm no entries were forged or altered.
- **US-0578** *(Security Engineer — P1)* — As a Security Engineer, I want the learning audit trail to be tamper-evident via a hash chain, so that any deletion or reordering of entries is detectable.
- **US-0579** *(Compliance Officer — P1)* — As a Compliance Officer, I want each audit entry to link the snapshot, hindsight result, and approver identity for a promotion, so that I can trace every learned change end to end.
- **US-0580** *(External Auditor — P2)* — As an External Auditor, I want to export the learning audit trail for a date range in a portable signed format, so that I can review it offline in my own tooling.
- **US-0581** *(Agent Author — P1)* — As an Agent Author, I want to donate successful trajectories to the learning corpus, so that high-quality runs become training material for the fleet.
- **US-0582** *(Platform Admin — P1)* — As a Platform Admin, I want configurable thresholds (reward, success, cost) that gate which trajectories are eligible for donation, so that only genuinely good runs enter the corpus.
- **US-0583** *(Agent Author — P2)* — As an Agent Author, I want a `--repeat` option that re-runs a task N times and donates only the best outcomes, so that I can harvest strong examples from naturally variable runs.
- **US-0584** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want donated trajectories de-duplicated and PII-scrubbed before entering the corpus, so that the learning corpus stays clean and compliant.
- **US-0585** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want an API to donate trajectories programmatically from external agents, so that fleet memory can grow from systems outside the CLI.
- **US-0586** *(Agent Author — P1)* — As an Agent Author, I want the system to build DPO/preference pairs from best-of-N candidate generations, so that the model learns to prefer the stronger of two real outputs.
- **US-0587** *(Agent Author — P2)* — As an Agent Author, I want to inspect generated preference pairs with their chosen/rejected labels and scores, so that I can validate that pairing logic reflects true quality differences.
- **US-0588** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want preference pairs exported in a standard DPO dataset format, so that I can fine-tune models in my own training pipeline.
- **US-0589** *(Agent Author — P1)* — As an Agent Author, I want a reward model to score candidate trajectories, so that best-of-N selection and preference pairing rest on a consistent quality signal.
- **US-0590** *(Team Lead — P2)* — As a Team Lead, I want to calibrate and version the reward model against human-rated examples, so that its scores stay aligned with what we actually consider good work.
- **US-0591** *(Operator — P0)* — As an Operator, I want a frozen-learning A/B control arm that disables learning for a holdout, so that I can prove improvements come from learning and not from drift or external factors.
- **US-0592** *(Team Lead — P1)* — As a Team Lead, I want the A/B harness to report statistical significance between the learning and frozen-control arms, so that I can claim learning works with evidence, not anecdote.
- **US-0593** *(Operator — P1)* — As an Operator, I want the prove-learning harness to be runnable as a single command that sets up arms, runs tasks, and emits a verdict, so that proving learning is repeatable and low-effort.
- **US-0594** *(SRE — P2)* — As an SRE, I want the prove-learning harness to stub the LLM boundary so it runs deterministically in CI, so that learning plumbing is validated without live model cost.
- **US-0595** *(Compliance Officer — P0)* — As a Compliance Officer, I want learning governance to require explicit approval before any insight is promoted to production, so that no learned change goes live unreviewed.
- **US-0596** *(Platform Admin — P1)* — As a Platform Admin, I want to configure multi-approver rules for promotion based on the blast radius of a learning change, so that high-impact promotions require stronger sign-off.
- **US-0597** *(Compliance Officer — P1)* — As a Compliance Officer, I want promotion approvals and rejections recorded with rationale in the signed audit trail, so that the governance decision and its reasoning are permanently provable.
- **US-0598** *(Operator — P2)* — As an Operator, I want `factory-learn` to run the full dream→hindsight→proof cycle in one pipeline with gated promotion, so that I can operate the closed learning lifecycle without orchestrating each stage by hand.
- **US-0599** *(Tenant Admin — P1)* — As a Tenant Admin, I want learning corpus, snapshots, and dreams isolated per tenant, so that one tenant's experience never leaks into another tenant's learned behavior.
- **US-0600** *(Security Engineer — P2)* — As a Security Engineer, I want a kill-switch that freezes all learning and promotion fleet-wide, so that I can halt the self-learning loop immediately during a suspected poisoning or compromise.

---

## Epic 13 — Skills & Distillation

- **US-0601** *(Operator — P0)* — As an Operator, I want the `/skills` screen to list every installed SKILL.md with its name, version, source, and last-used date, so that I can see at a glance which skills my workforce can apply.
- **US-0602** *(Operator — P1)* — As an Operator, I want to filter and search the `/skills` screen by name, tag, and suite, so that I can find a specific skill without scrolling the whole catalog.
- **US-0603** *(Agent Author — P0)* — As an Agent Author, I want successful runs to auto-distill a SKILL.md into `~/.maverick/skills/`, so that reusable know-how is captured without me writing it by hand.
- **US-0604** *(Agent Author — P1)* — As an Agent Author, I want each distilled SKILL.md to include the trigger conditions, ordered steps, and example inputs/outputs, so that the skill is immediately usable by another agent.
- **US-0605** *(Knowledge Steward — P0)* — As a Knowledge Steward, I want a distillation quality gate that only saves skills scoring above a configurable threshold, so that low-value or noisy runs never pollute the skill library.
- **US-0606** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want the quality gate to record its score and the reasons a skill passed or failed, so that I can audit why a run did or did not become a skill.
- **US-0607** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want skills that fail the quality gate to land in a rejected queue rather than disappear, so that I can manually promote a borderline candidate when warranted.
- **US-0608** *(Agent Author — P0)* — As an Agent Author, I want learned skills produced by the learning loops to be saved in `~/.maverick/learned-skills/` separately from run-distilled skills, so that I can tell loop-derived knowledge apart from single-run distillations.
- **US-0609** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want the `/skills` screen to badge each skill with its origin (distilled, learned, or installed), so that I can reason about provenance from the list view.
- **US-0610** *(Operator — P0)* — As an Operator, I want `maverick skills` to print all installed skills and their paths from the terminal, so that I can inspect the skill set in a headless environment.
- **US-0611** *(Operator — P1)* — As an Operator, I want `maverick skills show <name>` to render a single skill's full SKILL.md and metadata, so that I can review its content from the CLI.
- **US-0612** *(Operator — P1)* — As an Operator, I want `maverick skills install <id>` to fetch and place a skill from the catalog into my skills directory, so that I can add capabilities without manual file copying.
- **US-0613** *(Operator — P2)* — As an Operator, I want `maverick skills remove <name>` to uninstall a skill and confirm it is gone, so that I can prune skills I no longer need.
- **US-0614** *(Team Lead — P1)* — As a Team Lead, I want a browsable skill catalog in the dashboard with descriptions, ratings, and install counts, so that my team can discover skills worth adopting.
- **US-0615** *(Team Lead — P2)* — As a Team Lead, I want to preview a catalog skill's SKILL.md before installing it, so that I can vet its steps without committing it to my environment.
- **US-0616** *(Security Engineer — P0)* — As a Security Engineer, I want every published skill to be cryptographically signed, so that I can verify a skill's authenticity before it runs in my environment.
- **US-0617** *(Security Engineer — P0)* — As a Security Engineer, I want signature verification to use canonical-byte serialization of the SKILL.md, so that whitespace or ordering changes cannot invalidate or forge a valid signature.
- **US-0618** *(Security Engineer — P0)* — As a Security Engineer, I want skill install to reject any skill whose signature fails the canonical-bytes integrity check, so that tampered skills cannot be installed.
- **US-0619** *(Security Engineer — P1)* — As a Security Engineer, I want `maverick skills verify <name>` to recompute canonical bytes and confirm the on-disk signature, so that I can detect post-install tampering.
- **US-0620** *(Platform Admin — P1)* — As a Platform Admin, I want to configure the set of trusted signing keys for skills, so that only skills from approved publishers can be installed.
- **US-0621** *(Knowledge Steward — P0)* — As a Knowledge Steward, I want a review queue of distilled skills awaiting approval, so that nothing enters the active library until a human signs off.
- **US-0622** *(Knowledge Steward — P0)* — As a Knowledge Steward, I want to approve a distilled skill from the `/skills` review view, so that I can promote a good candidate into the installed set.
- **US-0623** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want to edit a distilled skill's text before approving it, so that I can fix wording or tighten steps without rejecting the whole skill.
- **US-0624** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want to reject a distilled skill with a reason, so that the rejection rationale is preserved for future distillation tuning.
- **US-0625** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want edits to a distilled skill to require re-signing before activation, so that my changes cannot bypass the integrity chain.
- **US-0626** *(Agent Author — P0)* — As an Agent Author, I want to attach a skill to a specific agent, so that the agent applies that skill when its trigger conditions match.
- **US-0627** *(Agent Author — P1)* — As an Agent Author, I want to detach a skill from an agent, so that I can remove a capability that is no longer relevant to that agent's role.
- **US-0628** *(Agent Author — P1)* — As an Agent Author, I want to see which agents a given skill is attached to, so that I can assess the blast radius before changing or removing it.
- **US-0629** *(Operator — P2)* — As an Operator, I want a run's trace to show which skills were applied and at which step, so that I can attribute outcomes to specific skills.
- **US-0630** *(Knowledge Steward — P0)* — As a Knowledge Steward, I want the system to detect near-duplicate skills by similarity, so that the library does not accumulate redundant variants of the same know-how.
- **US-0631** *(Knowledge Steward — P0)* — As a Knowledge Steward, I want to merge two similar skills into one canonical skill, so that consumers reference a single authoritative version.
- **US-0632** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want a merge to preserve the provenance of both source skills, so that the merged skill records where its content originated.
- **US-0633** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want dedupe suggestions surfaced proactively on the `/skills` screen, so that I can resolve duplicates before they spread across agents.
- **US-0634** *(Team Lead — P1)* — As a Team Lead, I want to share an approved skill to the store, so that other teams and tenants can install it.
- **US-0635** *(Compliance Officer — P0)* — As a Compliance Officer, I want sharing a skill to the store to require an explicit redaction and approval step, so that no sensitive data leaks via a published SKILL.md.
- **US-0636** *(Tenant Admin — P1)* — As a Tenant Admin, I want store-shared skills scoped to my tenant by default with an opt-in to publish publicly, so that internal skills don't leak across tenant boundaries.
- **US-0637** *(Agent Author — P0)* — As an Agent Author, I want each skill to carry a semantic version that increments when its content changes, so that I can pin agents to a known-good version.
- **US-0638** *(Agent Author — P1)* — As an Agent Author, I want to view the version history and diff between two versions of a skill, so that I can see exactly what changed and why.
- **US-0639** *(Agent Author — P1)* — As an Agent Author, I want to roll back a skill to a prior version, so that I can recover from a bad edit or regression.
- **US-0640** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want each skill version to record provenance — the source run, learning loop, or merge that produced it, so that I can trace any skill back to its origin.
- **US-0641** *(External Auditor — P0)* — As an External Auditor, I want an immutable audit log of every skill approval, edit, merge, and share with actor and timestamp, so that I can verify the skill lifecycle was governed.
- **US-0642** *(External Auditor — P1)* — As an External Auditor, I want to export a skill's full provenance and signature chain as a signed report, so that I can attest to its integrity independently.
- **US-0643** *(Compliance Officer — P1)* — As a Compliance Officer, I want a policy that blocks distillation from runs touching regulated data classes, so that confidential context is never captured into a skill.
- **US-0644** *(FinOps Owner — P2)* — As a FinOps Owner, I want a report of token and dollar savings attributable to skill reuse, so that I can quantify the ROI of the distillation pipeline.
- **US-0645** *(Platform Admin — P1)* — As a Platform Admin, I want to configure the distillation quality-gate threshold and the skills directories per environment, so that I can tune how aggressively skills are captured.
- **US-0646** *(Platform Admin — P2)* — As a Platform Admin, I want the installer wizard to include a step that enables distillation and sets the skills storage location, so that the capability is configured at setup time.
- **US-0647** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want the MCP server to expose installed skills as resources, so that external agents can read and apply skills programmatically.
- **US-0648** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want the TS SDK to list, install, and verify skills via typed methods, so that I can manage skills from my own application code.
- **US-0649** *(SRE — P2)* — As an SRE, I want metrics on distillation rate, gate pass/fail counts, and skill-application latency, so that I can monitor the health of the skills pipeline.
- **US-0650** *(Executive — P3)* — As an Executive, I want a dashboard summary of skills learned, approved, and shared over time, so that I can see the platform compounding its own expertise.

---

## Epic 14 — Approvals & Permissions

- **US-0651** *(Operator — P0)* — As an Operator, I want a single `/approvals` queue showing every pending high-risk action with its agent, goal, tool, and risk score, so that I can triage what needs my decision without hunting across goals.
- **US-0652** *(Operator — P0)* — As an Operator, I want to approve a pending tool call from the queue and have the blocked goal resume at its next tool-call boundary, so that work continues immediately after I authorize it.
- **US-0653** *(Operator — P0)* — As an Operator, I want to deny a pending tool call with a required reason, so that the agent receives the denial and a recorded justification is attached to the action.
- **US-0654** *(Team Lead — P1)* — As a Team Lead, I want to see the exact arguments (paths, hosts, command, payload) of a pending tool call before deciding, so that I approve the precise action and not a vague description of it.
- **US-0655** *(Operator — P1)* — As an Operator, I want to approve a pack activation request from the approvals queue, so that a new specialist pack only goes live after a human authorizes it.
- **US-0656** *(Operator — P1)* — As an Operator, I want to deny a pack activation and have the requesting goal told the pack is unavailable, so that unvetted packs never run.
- **US-0657** *(Security Engineer — P0)* — As a Security Engineer, I want an `/permissions` screen listing every role, the tools, paths, and hosts it may use, and the risk threshold that forces approval, so that I can review the full permission posture in one place.
- **US-0658** *(Platform Admin — P0)* — As a Platform Admin, I want to set a per-role policy on `/permissions` that allows specific tools and denies all others, so that each role runs with least privilege by default.
- **US-0659** *(Platform Admin — P1)* — As a Platform Admin, I want a per-action policy that requires approval for any action whose risk score exceeds a configurable threshold, so that low-risk work flows freely while dangerous actions are gated.
- **US-0660** *(Security Engineer — P0)* — As a Security Engineer, I want capability grants to attenuate down a delegation chain so a child agent can never hold a capability broader than its parent, so that delegation cannot escalate privilege.
- **US-0661** *(Security Engineer — P0)* — As a Security Engineer, I want the system to reject any grant where a child requests a tool, path, or host outside its parent's grant, so that attenuation is enforced at grant time, not just at use time.
- **US-0662** *(Agent Author — P1)* — As an Agent Author, I want to declare the minimal capability set my agent needs in its manifest, so that operators grant exactly those permissions and nothing wider.
- **US-0663** *(Agent Author — P2)* — As an Agent Author, I want a dry-run that reports which of my agent's planned tool calls would require approval under the current policy, so that I can design around gates before shipping.
- **US-0664** *(Operator — P0)* — As an Operator, I want to arm the halt killswitch from the dashboard, so that every running goal stops at its next tool-call boundary when a situation is going wrong.
- **US-0665** *(Operator — P0)* — As an Operator, I want to clear the halt killswitch after I arm it, so that goals can resume once I've confirmed it is safe to continue.
- **US-0666** *(SRE — P0)* — As an SRE, I want the halt killswitch armable from the `maverick` CLI, so that I can stop the fleet during an incident even when the dashboard is unreachable.
- **US-0667** *(SRE — P1)* — As an SRE, I want a halted goal to stop cleanly at the next tool-call boundary rather than mid-tool, so that no partially executed side effect is left dangling.
- **US-0668** *(Operator — P1)* — As an Operator, I want the dashboard to show a clear banner and count of goals frozen while the killswitch is armed, so that I always know the halt is active and its blast radius.
- **US-0669** *(Compliance Officer — P0)* — As a Compliance Officer, I want every approval and denial recorded with approver identity, timestamp, action, and reason in the audit log, so that I can prove who authorized each high-risk action.
- **US-0670** *(Compliance Officer — P1)* — As a Compliance Officer, I want killswitch arm and clear events logged with the actor and the goals affected, so that emergency stops are fully accountable.
- **US-0671** *(Operator — P1)* — As an Operator, I want just-in-time elevation that grants me a higher capability for a single action with an expiry, so that I can handle an exception without holding standing elevated rights.
- **US-0672** *(Compliance Officer — P0)* — As a Compliance Officer, I want every just-in-time elevation recorded with the requester, the capability, the justification, and the expiry, so that temporary privilege is always auditable.
- **US-0673** *(Security Engineer — P1)* — As a Security Engineer, I want just-in-time elevations to auto-expire and revoke at their TTL, so that elevated access never silently persists past its window.
- **US-0674** *(Platform Admin — P1)* — As a Platform Admin, I want to maintain an explicit allow-list and deny-list of tools per role, so that I can both whitelist trusted tools and hard-block dangerous ones.
- **US-0675** *(Security Engineer — P1)* — As a Security Engineer, I want path-scoped permissions that allow or deny specific filesystem paths and globs per role, so that an agent can read its workspace but never touch secrets directories.
- **US-0676** *(Security Engineer — P1)* — As a Security Engineer, I want host-scoped network permissions that allow or deny specific hostnames and domains, so that agents can only reach approved endpoints.
- **US-0677** *(Security Engineer — P2)* — As a Security Engineer, I want a deny rule to take precedence over an allow rule when both match an action, so that an explicit block can never be overridden by a broad allow.
- **US-0678** *(Team Lead — P1)* — As a Team Lead, I want to designate delegated approvers for my team's approval queue, so that decisions are not blocked when I am unavailable.
- **US-0679** *(Team Lead — P2)* — As a Team Lead, I want to set a fallback approver chain so that if the primary approver does not act, the request escalates to the next person, so that approvals never stall on one absent person.
- **US-0680** *(Platform Admin — P1)* — As a Platform Admin, I want to configure an approval SLA per risk tier (e.g. critical actions due in 15 minutes), so that high-risk requests get a guaranteed response time.
- **US-0681** *(Operator — P2)* — As an Operator, I want reminder notifications when a pending approval is approaching its SLA deadline, so that I act before the request breaches.
- **US-0682** *(Team Lead — P2)* — As a Team Lead, I want a request that breaches its approval SLA to auto-escalate to the delegated approver, so that overdue decisions don't silently block goals.
- **US-0683** *(Operator — P1)* — As an Operator, I want to filter and sort the approvals queue by risk score, age, requesting agent, and SLA status, so that I work the most urgent items first.
- **US-0684** *(Operator — P2)* — As an Operator, I want to batch-approve several low-risk pending actions that share a category in one confirmed step, so that I clear routine items quickly without rubber-stamping individually.
- **US-0685** *(Compliance Officer — P2)* — As a Compliance Officer, I want batch approvals to still record an individual audit entry per action, so that bulk convenience never collapses the per-action accountability trail.
- **US-0686** *(Requester — P1)* — As a Requester, I want to see the live status of an approval I triggered (pending, approved, denied, expired) with the approver and reason, so that I know why my agent's action is waiting or was blocked.
- **US-0687** *(Requester — P2)* — As a Requester, I want to add context or a justification to my pending request, so that the approver has what they need to decide quickly.
- **US-0688** *(Tenant Admin — P0)* — As a Tenant Admin, I want approval policies and permission grants scoped strictly to my tenant, so that another tenant's operators can never see or approve my actions.
- **US-0689** *(Tenant Admin — P1)* — As a Tenant Admin, I want to arm a halt killswitch limited to my tenant's goals, so that I can stop my workforce without affecting other tenants on the platform.
- **US-0690** *(FinOps Owner — P1)* — As a FinOps Owner, I want any action whose projected spend exceeds a budget threshold routed to the approvals queue, so that costly operations get a human sign-off before money is committed.
- **US-0691** *(FinOps Owner — P2)* — As a FinOps Owner, I want the pending-approval card to show the estimated cost of the action, so that I weigh spend against value when I decide.
- **US-0692** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want an API and webhook to receive approval requests and post decisions, so that I can drive approvals from our existing ITSM or chat tooling.
- **US-0693** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want the MCP server to expose pending approvals as a resource and accept approve/deny calls, so that an external agent or bot can participate in the approval flow.
- **US-0694** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want activation of a pack that reads or writes the knowledge base to require my approval, so that no pack touches curated knowledge without steward review.
- **US-0695** *(External Auditor — P0)* — As an External Auditor, I want a read-only, immutable export of all approval, denial, elevation, and killswitch events for a date range, so that I can independently verify governance controls were enforced.
- **US-0696** *(External Auditor — P1)* — As an External Auditor, I want each audit entry to show the policy version in effect when the decision was made, so that I can confirm decisions matched the rules active at that time.
- **US-0697** *(Security Engineer — P2)* — As a Security Engineer, I want to prevent an approver from approving their own request (separation of duties), so that no single actor can both trigger and authorize a high-risk action.
- **US-0698** *(Platform Admin — P2)* — As a Platform Admin, I want to preview the impact of a permission policy change by replaying recent actions against the new rules, so that I see what would have been blocked or gated before I save it.
- **US-0699** *(Executive — P3)* — As an Executive, I want a summary view of approval volume, denial rate, average decision time, and SLA breaches over time, so that I can gauge how much friction and risk the governance layer is managing.
- **US-0700** *(Compliance Officer — P3)* — As a Compliance Officer, I want an automatic periodic access review that flags standing grants unused for N days, so that we revoke stale permissions and keep least privilege true over time.

---

## Epic 15 — Safety & Shield

- **US-0701** *(Security Engineer — P0)* — As a Security Engineer, I want a `/safety` screen that shows whether the agent-shield is currently active or absent, so that I can confirm at a glance whether tool-call screening is in effect.
- **US-0702** *(Platform Admin — P0)* — As a Platform Admin, I want the kernel to run successfully when `agent-shield` is not installed and only emit a warning, so that the core platform never hard-fails on a missing optional shield.
- **US-0703** *(Security Engineer — P0)* — As a Security Engineer, I want every tool call to be screened by the agent-shield before it executes when the shield is present, so that disallowed actions are blocked at the boundary rather than after the fact.
- **US-0704** *(Security Engineer — P1)* — As a Security Engineer, I want the shield to evaluate built-in safety rules in a defined cascade order, so that a blocking rule short-circuits later rules and the first matching verdict wins predictably.
- **US-0705** *(Agent Author — P1)* — As an Agent Author, I want the shield to return a structured allow/deny verdict with the rule id and reason that fired, so that I can see exactly why a tool call was blocked.
- **US-0706** *(Security Engineer — P0)* — As a Security Engineer, I want the fail-open warning to be logged with a distinct event code whenever the shield is absent at startup, so that an unscreened deployment is detectable in our logs and alerts.
- **US-0707** *(Compliance Officer — P1)* — As a Compliance Officer, I want each shield deny decision written to the signed audit log with the rule, tool, and arguments hash, so that blocked actions are provable after the fact.
- **US-0708** *(Platform Admin — P1)* — As a Platform Admin, I want to enable a fail-closed mode that refuses to start the kernel if the shield is required but missing, so that regulated deployments cannot accidentally run unscreened.
- **US-0709** *(Security Engineer — P0)* — As a Security Engineer, I want prompt-injection defense that rejects boundary-split injection payloads during knowledge ingest, so that an attacker cannot smuggle instructions across chunk boundaries into the knowledge base.
- **US-0710** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want ingested documents flagged when they contain instruction-like content aimed at the agent, so that I can quarantine poisoned sources before they reach retrieval.
- **US-0711** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want the `/safety` screen to list recent prompt-injection detections with the source document and matched pattern, so that I can triage and remove the offending content.
- **US-0712** *(Security Engineer — P1)* — As a Security Engineer, I want a persona scan that detects when an agent's persona or system prompt has been manipulated to bypass safety, so that prompt-tampering attempts are caught.
- **US-0713** *(Agent Author — P2)* — As an Agent Author, I want persona-scan results surfaced when I author or edit a pack, so that I learn my persona text trips a safety rule before I publish it.
- **US-0714** *(Security Engineer — P0)* — As a Security Engineer, I want all shell execution routed through `sandbox.exec()` with no direct subprocess paths, so that no command escapes sandbox policy.
- **US-0715** *(Platform Admin — P1)* — As a Platform Admin, I want to select the sandbox backend between local subprocess and docker/podman container isolation, so that I can match isolation strength to the deployment's risk tolerance.
- **US-0716** *(Security Engineer — P1)* — As a Security Engineer, I want the docker/podman sandbox backend to run each command in an isolated container with no host filesystem mount by default, so that a compromised tool cannot read or write the host.
- **US-0717** *(SRE — P2)* — As an SRE, I want `sandbox.exec()` to enforce per-command CPU, memory, and wall-clock limits, so that a runaway shell command cannot exhaust the host.
- **US-0718** *(Operator — P2)* — As an Operator, I want the local-subprocess sandbox to surface an isolation-warning banner on the `/safety` screen, so that I know shell commands are not container-isolated in this deployment.
- **US-0719** *(Platform Admin — P2)* — As a Platform Admin, I want to suppress the sandbox-isolation warning via an explicit config acknowledgment, so that a deliberately ungated dev environment does not nag operators.
- **US-0720** *(Compliance Officer — P1)* — As a Compliance Officer, I want suppressing the isolation warning to be recorded in the audit log with who acknowledged it, so that the decision to run without container isolation is accountable.
- **US-0721** *(Security Engineer — P0)* — As a Security Engineer, I want an egress lock that blocks all outbound network from sandboxed tools unless a host is on the allowlist, so that exfiltration and SSRF are prevented by default.
- **US-0722** *(Security Engineer — P0)* — As a Security Engineer, I want SSRF protection that rejects requests to private, link-local, and metadata IP ranges (e.g. 169.254.169.254), so that a tool cannot reach internal services or cloud credentials.
- **US-0723** *(Platform Admin — P1)* — As a Platform Admin, I want to configure a per-deployment host allowlist for outbound requests, so that only sanctioned external endpoints are reachable.
- **US-0724** *(Tenant Admin — P2)* — As a Tenant Admin, I want to define a tenant-scoped egress allowlist that narrows the platform default, so that my tenant's agents reach only my approved destinations.
- **US-0725** *(Security Engineer — P1)* — As a Security Engineer, I want egress allowlist matching to resolve and re-check the destination IP after DNS resolution, so that DNS-rebinding cannot defeat the host allowlist.
- **US-0726** *(Security Engineer — P2)* — As a Security Engineer, I want redirects from an allowlisted host to a non-allowlisted host to be blocked, so that an open redirect cannot be chained into SSRF.
- **US-0727** *(Security Engineer — P0)* — As a Security Engineer, I want secret redaction applied to tool inputs, outputs, and logs so that detected credentials and tokens are masked, so that secrets never leak into traces, logs, or the audit record.
- **US-0728** *(Compliance Officer — P1)* — As a Compliance Officer, I want secret-redaction patterns aligned with the detect-secrets baseline, so that what CI flags in source is also redacted at runtime.
- **US-0729** *(Operator — P2)* — As an Operator, I want a redacted preview of a tool call's arguments on the `/safety` screen, so that I can inspect what was attempted without exposing the underlying secret.
- **US-0730** *(Security Engineer — P2)* — As a Security Engineer, I want redaction to cover structured secrets in JSON and env-style payloads, not just inline strings, so that credentials embedded in nested fields are still masked.
- **US-0731** *(Compliance Officer — P1)* — As a Compliance Officer, I want a watermark safety check that detects content-provenance watermarks in generated images, so that I can confirm AI-generated media is labeled per policy.
- **US-0732** *(Compliance Officer — P1)* — As a Compliance Officer, I want a voice safety check that screens synthesized or cloned voice output against an impersonation policy, so that the platform cannot be used to mimic a real person without consent.
- **US-0733** *(Compliance Officer — P1)* — As a Compliance Officer, I want an image safety check that screens generated images for disallowed categories before they leave the platform, so that unsafe media is blocked at the boundary.
- **US-0734** *(Security Engineer — P2)* — As a Security Engineer, I want watermark, voice, and image safety checks to run inside the shield cascade, so that a failing media check denies the tool call like any other safety rule.
- **US-0735** *(Platform Admin — P0)* — As a Platform Admin, I want a hardened/regulated safety profile I can select that turns on the shield, fail-closed start, container isolation, egress lock, and media checks together, so that I can configure a compliant baseline in one step.
- **US-0736** *(Platform Admin — P1)* — As a Platform Admin, I want the regulated safety profile exposed as both a config knob and an installer-wizard step, so that fresh deployments can opt into hardened safety during setup.
- **US-0737** *(Security Engineer — P1)* — As a Security Engineer, I want the `/safety` screen to display the active safety profile and every setting it implies, so that I can verify the deployment matches our required posture.
- **US-0738** *(Compliance Officer — P2)* — As a Compliance Officer, I want a downloadable safety-posture report summarizing shield status, sandbox backend, egress policy, and media checks, so that I can attach it to a compliance attestation.
- **US-0739** *(Agent Author — P2)* — As an Agent Author, I want to add a custom shield rule scoped to my pack, so that I can block tool calls specific to my domain without editing the built-in rules.
- **US-0740** *(Security Engineer — P1)* — As a Security Engineer, I want custom shield rules to be evaluated after built-in deny rules in the cascade, so that a pack rule can tighten but never loosen a platform safety guarantee.
- **US-0741** *(Agent Author — P2)* — As an Agent Author, I want a dry-run mode that reports what the shield would have denied without blocking execution, so that I can tune rules against real traffic before enforcing them.
- **US-0742** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want a `maverick safety` CLI command that prints shield status, sandbox backend, and egress policy, so that I can assert safety posture in CI without the dashboard.
- **US-0743** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want an MCP resource exposing the current shield verdict for a proposed tool call, so that an external agent can pre-check an action before requesting it.
- **US-0744** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want the TS SDK to surface a ShieldDenied result with the rule id and reason, so that my channel integration can handle a blocked action gracefully.
- **US-0745** *(Requester — P3)* — As a Requester, I want a clear, non-technical message when my channel request is blocked by a safety rule, so that I understand why it was refused and what to change.
- **US-0746** *(SRE — P1)* — As an SRE, I want an alert fired when the kernel starts in fail-open mode in a production tenant, so that an accidentally unscreened deployment pages on-call.
- **US-0747** *(Team Lead — P2)* — As a Team Lead, I want a per-team summary of shield denials and injection detections on the `/safety` screen, so that I can see whether my team's agents are tripping safety rules.
- **US-0748** *(External Auditor — P2)* — As an External Auditor, I want to replay a sample of historical tool calls against the recorded shield verdicts, so that I can independently verify the shield enforced policy at the time.
- **US-0749** *(Executive — P3)* — As an Executive, I want a high-level safety scorecard showing shield coverage, blocked-action counts, and isolation status across tenants, so that I can attest to the board that the workforce runs under guardrails.
- **US-0750** *(Tenant Admin — P2)* — As a Tenant Admin, I want to escalate my tenant to the regulated safety profile independently of the platform default, so that my regulated workloads get container isolation and egress locks even when other tenants do not.

---

## Epic 16 — Compliance, Audit & Replay

- **US-0751** *(Compliance Officer — P0)* — As a Compliance Officer, I want to generate a SOC2 evidence report from `/compliance` for a named control period, so that I can hand auditors a dated package without screen-scraping the dashboard.
- **US-0752** *(External Auditor — P0)* — As an External Auditor, I want to download a self-contained evidence bundle (controls, logs, signatures, manifest) from `/compliance`, so that I can verify it offline without access to the live platform.
- **US-0753** *(Compliance Officer — P1)* — As a Compliance Officer, I want each SOC2 evidence item to cite the originating audit-log entry id and run id, so that every control assertion is traceable back to source.
- **US-0754** *(Compliance Officer — P1)* — As a Compliance Officer, I want to filter compliance reports by control family (CC1–CC9), so that I can produce targeted evidence for a single Trust Services Criterion.
- **US-0755** *(Compliance Officer — P2)* — As a Compliance Officer, I want compliance reports rendered to both PDF and machine-readable JSON, so that humans and GRC tooling can both consume the same evidence.
- **US-0756** *(Security Engineer — P0)* — As a Security Engineer, I want the audit log to be tamper-evident via a hash chain linking each entry to its predecessor, so that any insertion, deletion, or edit breaks verification.
- **US-0757** *(Security Engineer — P0)* — As a Security Engineer, I want `/audit` to expose a verify endpoint that recomputes the hash chain and reports the first broken link, so that I can detect tampering and pinpoint where it occurred.
- **US-0758** *(Security Engineer — P0)* — As a Security Engineer, I want audit entries cryptographically signed so that authenticity is provable, so that a forged entry cannot pass signature verification.
- **US-0759** *(Security Engineer — P1)* — As a Security Engineer, I want the audit signing key to live off-host in a KMS/HSM rather than on the dashboard node, so that a host compromise cannot mint valid audit signatures.
- **US-0760** *(Platform Admin — P1)* — As a Platform Admin, I want to rotate the off-host audit signing key with overlapping validity windows, so that I can rotate without invalidating previously signed entries.
- **US-0761** *(Security Engineer — P2)* — As a Security Engineer, I want each signed audit segment to record the key id and algorithm used, so that verification picks the right public key after a rotation.
- **US-0762** *(External Auditor — P1)* — As an External Auditor, I want to independently verify audit signatures using only the published public key, so that I do not have to trust the platform to confirm integrity.
- **US-0763** *(SRE — P1)* — As an SRE, I want a daily automated job that verifies the prior day's audit chain and alerts on any break, so that tampering is surfaced within 24 hours rather than at audit time.
- **US-0764** *(Compliance Officer — P0)* — As a Compliance Officer, I want the audit log to be append-only with no UI or API path to delete an entry, so that the record cannot be quietly revised.
- **US-0765** *(Operator — P0)* — As an Operator, I want to replay any past run from `/replay` step by step, so that I can reconstruct exactly what an agent did during an incident.
- **US-0766** *(SRE — P0)* — As an SRE, I want replay to reproduce a run deterministically from recorded inputs, decisions, and tool results, so that forensic conclusions are reproducible rather than approximate.
- **US-0767** *(Security Engineer — P1)* — As a Security Engineer, I want replay to clearly mark when live side effects (tool calls, writes) are stubbed versus replayed, so that a forensic replay cannot accidentally re-execute against production.
- **US-0768** *(Operator — P1)* — As an Operator, I want to jump replay to a specific timestamp or step index, so that I can land directly on the moment of failure without stepping through the whole run.
- **US-0769** *(External Auditor — P2)* — As an External Auditor, I want to export a replay session as an immutable, signed transcript, so that I can attach forensic evidence to a finding.
- **US-0770** *(Compliance Officer — P1)* — As a Compliance Officer, I want every replay invocation itself recorded in the audit log, so that who-replayed-what-when is also accountable.
- **US-0771** *(Executive — P1)* — As an Executive, I want the Operating Record to summarize what the workforce did, decided, and spent over a period, so that I can attest to oversight to the board.
- **US-0772** *(Compliance Officer — P0)* — As a Compliance Officer, I want the Operating Record to be derived solely from the signed audit log, so that the human-readable narrative cannot diverge from the verified record.
- **US-0773** *(Team Lead — P2)* — As a Team Lead, I want to scope an Operating Record export to a single team or queue, so that I can produce accountability evidence for just my function.
- **US-0774** *(Requester — P1)* — As a Requester, I want to submit a GDPR Data Subject Access Request (DSAR) for a named subject, so that I can fulfill a regulatory request through a governed workflow.
- **US-0775** *(Compliance Officer — P0)* — As a Compliance Officer, I want a DSAR to compile all data held about a subject across the world model and audit log into one export, so that the response is complete and defensible.
- **US-0776** *(Tenant Admin — P0)* — As a Tenant Admin, I want an `export-user` operation that produces a portable archive of one user's data in my tenant, so that I can satisfy data-portability rights.
- **US-0777** *(Compliance Officer — P0)* — As a Compliance Officer, I want an `erase` operation that removes a subject's personal data on request, so that I can honor the right to erasure.
- **US-0778** *(Security Engineer — P0)* — As a Security Engineer, I want an `erase-verify` step that proves no residual personal data remains after erasure, so that erasure is provable rather than asserted.
- **US-0779** *(Compliance Officer — P1)* — As a Compliance Officer, I want erasure to preserve tamper-evidence by tombstoning rather than deleting audit entries, so that erasing personal data does not break the hash chain.
- **US-0780** *(Tenant Admin — P1)* — As a Tenant Admin, I want erase and export operations confined to my own tenant's data, so that a privacy operation cannot reach across tenant boundaries.
- **US-0781** *(Compliance Officer — P1)* — As a Compliance Officer, I want each DSAR, export, and erasure logged with requester, subject, scope, and outcome, so that I can prove the request was handled within SLA.
- **US-0782** *(Platform Admin — P0)* — As a Platform Admin, I want to define data retention policies per data class with a max age, so that records are purged automatically when their retention window expires.
- **US-0783** *(FinOps Owner — P2)* — As a FinOps Owner, I want a dry-run preview of what a retention policy would delete before it runs, so that I can confirm storage savings without risking premature loss.
- **US-0784** *(Compliance Officer — P1)* — As a Compliance Officer, I want retention enforcement actions recorded in the audit log, so that purges are themselves auditable and not silent.
- **US-0785** *(Compliance Officer — P0)* — As a Compliance Officer, I want to generate an EU AI Act conformity artifact for a deployed agent system, so that I can demonstrate obligations are met for high-risk use.
- **US-0786** *(Compliance Officer — P1)* — As a Compliance Officer, I want to author and export a DPIA (Data Protection Impact Assessment) tied to a specific deployment profile, so that I have the required risk assessment on file.
- **US-0787** *(Compliance Officer — P1)* — As a Compliance Officer, I want an auto-generated ROPA (Record of Processing Activities) listing data categories, purposes, and recipients, so that I keep an Article 30 register current without manual upkeep.
- **US-0788** *(Compliance Officer — P2)* — As a Compliance Officer, I want DPIA and ROPA artifacts versioned and timestamped, so that I can show what assessment was in force at any past date.
- **US-0789** *(Platform Admin — P0)* — As a Platform Admin, I want a regulated deployment profile (enterprise mode) that enforces at-rest encryption and data anonymization by default, so that compliant configuration is the default, not opt-in.
- **US-0790** *(Security Engineer — P0)* — As a Security Engineer, I want enterprise mode to refuse to start if at-rest encryption is disabled, so that a misconfiguration cannot silently downgrade the security posture.
- **US-0791** *(Tenant Admin — P1)* — As a Tenant Admin, I want anonymization in enterprise mode applied to PII before it is persisted to the world model, so that raw identifiers never land at rest.
- **US-0792** *(Compliance Officer — P2)* — As a Compliance Officer, I want a report attesting which regulated-profile controls are active in a deployment, so that I can confirm enterprise mode is genuinely engaged.
- **US-0793** *(Platform Admin — P0)* — As a Platform Admin, I want world-model migrations to be immutable once released, governed by a checksum lock, so that the schema history cannot be silently rewritten.
- **US-0794** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want CI to fail when a released migration is edited or removed without regenerating the governance lock, so that integrity violations are caught before merge.
- **US-0795** *(Compliance Officer — P2)* — As a Compliance Officer, I want a verifiable record proving the live schema matches the governed migration head, so that I can attest the database has not drifted from its sanctioned history.
- **US-0796** *(External Auditor — P0)* — As an External Auditor, I want to export a complete evidence package (compliance reports, signed audit segment, public key, replay transcripts, privacy logs) with a verification manifest, so that I can attest independently.
- **US-0797** *(External Auditor — P1)* — As an External Auditor, I want the evidence export accompanied by a one-command verification script, so that I can confirm signatures and hash chains without bespoke tooling.
- **US-0798** *(Security Engineer — P0)* — As a Security Engineer, I want PII automatically redacted in the live audit day-file as entries are written, so that raw personal data is never persisted in the active log.
- **US-0799** *(Compliance Officer — P1)* — As a Compliance Officer, I want live PII redaction to preserve the hash chain by hashing redacted spans deterministically, so that redaction does not break tamper-evidence.
- **US-0800** *(Security Engineer — P2)* — As a Security Engineer, I want a configurable PII redaction policy (patterns and field allow/deny lists) for the audit day-file, so that I can tune what is masked to match our data classification.

---

## Epic 17 — Compartments & Multi-Tenancy

- **US-0801** *(Tenant Admin — P0)* — As a Tenant Admin, I want to onboard a new tenant via `/tenants` with an isolated world DB and domains directory provisioned automatically, so that the tenant starts fully data-isolated with no manual setup.
- **US-0802** *(Tenant Admin — P0)* — As a Tenant Admin, I want offboarding a tenant to securely purge its world DB, domains dir, and KMS keys after a configurable retention window, so that decommissioned tenants leave no residual data.
- **US-0803** *(Platform Admin — P0)* — As a Platform Admin, I want `/tenants/overview` to show every tenant's status, region, key-rotation age, and compartment count, so that I can monitor the whole fleet from one screen.
- **US-0804** *(Security Engineer — P0)* — As a Security Engineer, I want a sector seal on `/compartments` that quarantines an entire domain (blocks all reads/writes/agent access) with one action, so that I can contain a suspected breach instantly.
- **US-0805** *(Security Engineer — P0)* — As a Security Engineer, I want cross-tenant containment tests in CI that assert no data bleed between two tenants' world DBs, so that an isolation regression fails the build before release.
- **US-0806** *(Compliance Officer — P0)* — As a Compliance Officer, I want compartment-scoped tax and client data marked no-web-egress so that any tool attempting outbound HTTP from that compartment is blocked, so that regulated data never leaves the boundary.
- **US-0807** *(Platform Admin — P0)* — As a Platform Admin, I want per-tenant KMS keys generated at onboarding so that each tenant's data-at-rest is encrypted under a distinct key, so that one tenant's key compromise cannot decrypt another's data.
- **US-0808** *(Security Engineer — P0)* — As a Security Engineer, I want fleet-wide key rotation that rotates every tenant's KMS key on a schedule while preserving decryptability of existing data, so that key material stays fresh without downtime.
- **US-0809** *(Tenant Admin — P0)* — As a Tenant Admin, I want the active-tenant context bound to my session so that all CLI, dashboard, and MCP operations resolve to my tenant's data only, so that I cannot accidentally read or write another tenant's records.
- **US-0810** *(Operator — P0)* — As an Operator, I want one tenant's agent to be hard-blocked from reaching another tenant's hosts and data even if it constructs the path, so that a malicious or buggy agent cannot pivot across tenants.
- **US-0811** *(Compliance Officer — P0)* — As a Compliance Officer, I want to set `MAVERICK_DATA_REGION` per tenant so that the tenant's data is provisioned and stored only in the chosen region, so that we meet data-residency obligations.
- **US-0812** *(Tenant Admin — P1)* — As a Tenant Admin, I want to bind a `[client]` id with `enforce=true` in tenant config so that operations are rejected when the active client does not match, so that work is always attributed to the correct client.
- **US-0813** *(Operator — P1)* — As an Operator, I want to switch the active tenant context with an explicit command that re-scopes every subsequent operation, so that I can service multiple tenants without leaking state between them.
- **US-0814** *(Platform Admin — P1)* — As a Platform Admin, I want creating a compartment under `/compartments` to define its domain scope and egress policy in one step, so that the boundary is enforced from the moment it exists.
- **US-0815** *(Security Engineer — P1)* — As a Security Engineer, I want lifting a sector seal to require a documented reason and approver so that quarantine release is auditable, so that no domain is silently un-quarantined.
- **US-0816** *(Compliance Officer — P1)* — As a Compliance Officer, I want every tenant onboarding and offboarding event written to a signed audit log so that the tenant lifecycle is provable to auditors, so that we can demonstrate controlled provisioning.
- **US-0817** *(Tenant Admin — P1)* — As a Tenant Admin, I want per-tenant config overrides for budgets, model roles, and feature flags so that my tenant's policy is independent of the platform defaults, so that one tenant's changes never affect another.
- **US-0818** *(Tenant Admin — P2)* — As a Tenant Admin, I want per-tenant dashboard themes (logo, color, name) so that my users see a branded surface, so that the workspace feels like our own environment.
- **US-0819** *(Platform Admin — P1)* — As a Platform Admin, I want a tenant to be suspended (read-only, agents paused) without deleting data so that I can halt activity during a billing or compliance hold, so that I can resume later without data loss.
- **US-0820** *(Security Engineer — P0)* — As a Security Engineer, I want the world DB and domains dir paths derived from the active tenant id so that no query can reference another tenant's storage location, so that path-level isolation is structural, not advisory.
- **US-0821** *(External Auditor — P1)* — As an External Auditor, I want a read-only attestation report per tenant showing its region, key id, rotation date, and sealed compartments, so that I can verify isolation controls without platform access.
- **US-0822** *(FinOps Owner — P1)* — As a FinOps Owner, I want per-tenant cost and token usage rolled up on `/tenants/overview` so that I can attribute spend to each tenant, so that I can bill and budget accurately.
- **US-0823** *(SRE — P1)* — As an SRE, I want a health check per tenant that verifies its world DB is reachable and its KMS key is usable, so that I detect a broken tenant before users do.
- **US-0824** *(Security Engineer — P1)* — As a Security Engineer, I want an alert when an agent in one compartment attempts to access another compartment's data so that I am notified of containment violations in real time, so that I can respond before damage spreads.
- **US-0825** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want domains in a sealed compartment to be excluded from cross-tenant knowledge sharing and fleet memory, so that sealed knowledge stays inside its boundary.
- **US-0826** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want the TS SDK and MCP server to require an explicit tenant id on connect so that no call defaults to a wrong or shared tenant, so that integrations are tenant-safe by construction.
- **US-0827** *(Tenant Admin — P1)* — As a Tenant Admin, I want bulk export of my tenant's data scoped strictly to my world DB and domains so that an export never includes another tenant's records, so that data portability respects isolation.
- **US-0828** *(Platform Admin — P0)* — As a Platform Admin, I want tenant ids validated and namespaced so that two tenants cannot collide on storage or config keys, so that provisioning is collision-free.
- **US-0829** *(Compliance Officer — P1)* — As a Compliance Officer, I want a no-web-egress compartment to also block DNS and file-share egress, not just HTTP, so that data cannot exfiltrate through side channels, so that the seal is comprehensive.
- **US-0830** *(Operator — P2)* — As an Operator, I want a banner showing the active tenant, client, and region in every surface so that I always know which boundary I am working in, so that I avoid acting in the wrong tenant.
- **US-0831** *(Security Engineer — P1)* — As a Security Engineer, I want per-tenant KMS keys stored so the platform operator cannot read tenant plaintext without the tenant key, so that isolation holds even against an insider with platform access.
- **US-0832** *(SRE — P2)* — As an SRE, I want fleet key rotation to be resumable and report per-tenant success/failure so that a partial rotation can be retried safely, so that no tenant is left on a stale key silently.
- **US-0833** *(Tenant Admin — P1)* — As a Tenant Admin, I want a dry-run of offboarding that lists exactly what will be purged so that I can confirm scope before deletion, so that I never destroy more than intended.
- **US-0834** *(Team Lead — P2)* — As a Team Lead, I want to scope my team's agents to specific compartments so that they only operate within authorized domains, so that team work cannot stray into restricted data.
- **US-0835** *(Compliance Officer — P0)* — As a Compliance Officer, I want region enforcement to reject any attempt to store a tenant's data outside its `MAVERICK_DATA_REGION`, so that residency cannot be bypassed by misconfiguration.
- **US-0836** *(Agent Author — P1)* — As an Agent Author, I want my agent pack to declare which compartments it needs so that it is denied at load time if a compartment is sealed or unauthorized, so that I fail fast instead of mid-run.
- **US-0837** *(External Auditor — P1)* — As an External Auditor, I want evidence that cross-tenant containment tests passed in the release that is deployed so that I can tie the control to the running version, so that the attestation is current, not historical.
- **US-0838** *(Platform Admin — P2)* — As a Platform Admin, I want to clone a tenant's config (not its data) as a template for new tenants so that onboarding is consistent, so that I avoid drift across tenant setups.
- **US-0839** *(Security Engineer — P1)* — As a Security Engineer, I want a sealed compartment to immediately terminate in-flight agent runs touching that domain so that quarantine is effective against active sessions, so that containment is not delayed until the next run.
- **US-0840** *(FinOps Owner — P2)* — As a FinOps Owner, I want per-tenant budget caps that pause the tenant's agents when exceeded so that one tenant cannot overrun shared cost, so that spend stays bounded per boundary.
- **US-0841** *(Requester — P2)* — As a Requester, I want my requests automatically tagged with my tenant and client so that results are stored in the right compartment, so that I never have to specify isolation manually.
- **US-0842** *(Tenant Admin — P1)* — As a Tenant Admin, I want rotating my tenant's KMS key on demand (outside the fleet schedule) so that I can respond to a suspected key exposure, so that I am not forced to wait for the next cycle.
- **US-0843** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want an API to list a tenant's compartments and their seal status so that my integration can avoid sending work to a quarantined domain, so that I handle seals gracefully.
- **US-0844** *(Security Engineer — P0)* — As a Security Engineer, I want a containment test that an agent given another tenant's id is still denied unless authorized for it, so that id spoofing cannot defeat isolation, so that authorization, not just scoping, gates access.
- **US-0845** *(Executive — P2)* — As an Executive, I want a single isolation-posture summary across all tenants (regions, sealed domains, rotation health) so that I can report tenancy controls to the board, so that governance is visible at the top.
- **US-0846** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want per-tenant domains directories kept separate so that knowledge ingested for one tenant never indexes into another's, so that retrieval respects tenant boundaries.
- **US-0847** *(SRE — P1)* — As an SRE, I want tenant provisioning to be idempotent so that a retried onboarding does not create duplicate world DBs or keys, so that recovery from a failed setup is safe.
- **US-0848** *(Compliance Officer — P1)* — As a Compliance Officer, I want proof that a sealed compartment's data was unreachable for the entire seal duration so that I can demonstrate quarantine effectiveness, so that incident response is provable.
- **US-0849** *(Platform Admin — P2)* — As a Platform Admin, I want migrating a tenant's data to a new region to enforce residency at the destination and verify the source is purged, so that a region change leaves no residency gap.
- **US-0850** *(Tenant Admin — P1)* — As a Tenant Admin, I want a self-service view of my tenant's isolation settings (region, key id, sealed compartments, client binding) so that I can confirm my boundary without contacting the platform team, so that I trust my isolation independently.

---

## Epic 18 — Agent Trust & Fleet Memory

- **US-0851** *(Operator — P0)* — As an Operator, I want to open the Agent Trust screen at `/trust` and see every external agent listed with its current engaged/disengaged state, so that I know at a glance which third-party agents Lightwork is actually governing.
- **US-0852** *(Platform Admin — P0)* — As a Platform Admin, I want external agents to be disengaged (ungoverned) by default until I explicitly engage them, so that no third-party agent can act under our governance without a deliberate decision.
- **US-0853** *(Operator — P0)* — As an Operator, I want to engage a specific external agent from `/trust` with one action, so that its subsequent actions are routed through our policy and budget controls.
- **US-0854** *(Operator — P1)* — As an Operator, I want to disengage an external agent and have it immediately fall back to ungoverned (and blocked from our resources), so that I can stop governing a misbehaving agent without deleting its record.
- **US-0855** *(Team Lead — P1)* — As a Team Lead, I want each external agent on `/trust` to display a numeric trust score with its contributing factors, so that I can compare agents and decide which ones to grant more access.
- **US-0856** *(Security Engineer — P0)* — As a Security Engineer, I want to attest an external agent's identity by verifying a signed identity claim (e.g. SPIFFE ID or signed JWT) before engagement, so that we only govern agents whose origin we have cryptographically confirmed.
- **US-0857** *(Security Engineer — P1)* — As a Security Engineer, I want a failed identity attestation to block engagement and surface the exact verification failure on `/trust`, so that I can diagnose why an agent could not be trusted.
- **US-0858** *(Platform Admin — P0)* — As a Platform Admin, I want to apply a capability clamp to an engaged external agent that restricts which tools and scopes it may invoke, so that a third-party agent can never exceed the permissions we intend.
- **US-0859** *(FinOps Owner — P0)* — As a FinOps Owner, I want to assign a token and dollar budget cap to each engaged external agent, so that an external agent cannot run up unbounded spend against our providers.
- **US-0860** *(FinOps Owner — P1)* — As a FinOps Owner, I want an external agent that hits its budget cap to be automatically throttled or disengaged with an alert, so that runaway spend is contained without manual intervention.
- **US-0861** *(Knowledge Steward — P0)* — As a Knowledge Steward, I want to grant an external agent read access to fleet memory under a named scope, so that a partner agent can benefit from our distilled knowledge within defined boundaries.
- **US-0862** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want to grant or deny an external agent write access to fleet memory independently of read access, so that I can let an agent contribute learnings without exposing everything for reading, or vice versa.
- **US-0863** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want fleet-memory write scopes to be namespaced per external agent, so that one partner agent's contributions cannot overwrite or pollute another's memory.
- **US-0864** *(Compliance Officer — P0)* — As a Compliance Officer, I want every action an external agent takes while engaged to be recorded in the audit log with the agent's attested identity, so that I can prove who did what during an investigation.
- **US-0865** *(Compliance Officer — P1)* — As a Compliance Officer, I want the audit trail to distinguish actions taken while an agent was engaged from any ungoverned activity, so that I can scope accountability precisely to the governed window.
- **US-0866** *(Knowledge Steward — P0)* — As a Knowledge Steward, I want to share distilled knowledge and skills with an external agent only through a policy that filters what may leave our boundary, so that proprietary or sensitive material is never exported.
- **US-0867** *(Compliance Officer — P1)* — As a Compliance Officer, I want each piece of knowledge shared with an external agent to carry a policy decision record (what was shared, under which rule, to whom), so that knowledge egress is fully auditable.
- **US-0868** *(Operator — P1)* — As an Operator, I want to revoke trust from an external agent in one click and have its fleet-memory grants, capability clamps, and active sessions all torn down atomically, so that revocation leaves no lingering access.
- **US-0869** *(Security Engineer — P0)* — As a Security Engineer, I want revoked external-agent credentials to be added to a denylist that survives restarts, so that a revoked agent cannot reconnect by replaying its old identity.
- **US-0870** *(Tenant Admin — P1)* — As a Tenant Admin, I want external-agent engagement, trust grants, and fleet-memory scopes to be isolated per tenant, so that one tenant's partner agents can never read another tenant's memory or audit data.
- **US-0871** *(Developer/Integrator — P0)* — As a Developer/Integrator, I want to onboard a partner's agent through a guided flow that walks me through identity attestation, clamp selection, budget, and scope grants, so that I can engage a new external agent safely without missing a control.
- **US-0872** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want the TS SDK to expose methods for an external agent to read and write fleet memory within its granted scopes, so that I can integrate a partner agent against fleet memory programmatically.
- **US-0873** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want fleet-memory writes from the SDK to be rejected with a clear scope-violation error when they exceed granted scopes, so that I learn at integration time exactly which scope I am missing.
- **US-0874** *(Agent Author — P1)* — As an Agent Author, I want to register my agent's declared capabilities and request specific tool scopes during onboarding, so that the governing operator can review and clamp precisely what I asked for.
- **US-0875** *(Agent Author — P2)* — As an Agent Author, I want to see which of my requested scopes were granted, denied, or clamped after review, so that I can adjust my agent's behavior to operate within the approved envelope.
- **US-0876** *(Team Lead — P1)* — As a Team Lead, I want trust score to decay when an external agent triggers policy violations or budget overruns, so that an agent's posture reflects its recent behavior rather than only its initial attestation.
- **US-0877** *(Team Lead — P2)* — As a Team Lead, I want trust score to recover gradually over a clean operating window, so that a previously flagged agent can earn back access without a manual reset.
- **US-0878** *(Operator — P1)* — As an Operator, I want to set a minimum trust-score threshold below which an external agent is automatically disengaged, so that posture degradation enforces itself without me watching the dashboard.
- **US-0879** *(SRE — P1)* — As an SRE, I want `/trust` and the trust-scoring engine to expose health and latency metrics, so that I can detect when trust evaluation is failing or slowing down agent actions.
- **US-0880** *(SRE — P2)* — As an SRE, I want fleet-memory read/write operations from external agents to be rate-limited per agent, so that a single partner agent cannot saturate the memory store and degrade others.
- **US-0881** *(Security Engineer — P1)* — As a Security Engineer, I want capability clamps on external agents to be deny-by-default, so that any tool not explicitly allowed is blocked even if the clamp definition is incomplete.
- **US-0882** *(Compliance Officer — P1)* — As a Compliance Officer, I want to export a per-agent report of all knowledge shared with and all actions taken by an external agent over a date range, so that I can satisfy a partner data-handling audit.
- **US-0883** *(External Auditor — P1)* — As an External Auditor, I want read-only access to the external-agent audit log with tamper-evident signing, so that I can independently verify the integrity of governed-agent activity records.
- **US-0884** *(External Auditor — P2)* — As an External Auditor, I want to confirm that each external agent's identity attestation event is linked to its subsequent actions, so that I can verify no action was attributed to an unattested identity.
- **US-0885** *(Platform Admin — P1)* — As a Platform Admin, I want to define reusable trust profiles (clamp + budget + scope bundles) and apply one to a new external agent, so that I can onboard partner agents consistently instead of configuring each from scratch.
- **US-0886** *(Tenant Admin — P2)* — As a Tenant Admin, I want to cap the number of external agents that may be engaged in my tenant at once, so that I can control blast radius and licensing for third-party fleet access.
- **US-0887** *(Requester — P2)* — As a Requester, I want to request that a specific partner agent be engaged for my project and route it for approval, so that I can get external help without holding governance permissions myself.
- **US-0888** *(Operator — P2)* — As an Operator, I want to review and approve or reject pending external-agent engagement requests from a queue on `/trust`, so that engagement stays a deliberate, reviewed action.
- **US-0889** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want to preview exactly which distilled skills an external agent would receive under a proposed sharing policy before I apply it, so that I can catch over-sharing prior to egress.
- **US-0890** *(FinOps Owner — P2)* — As a FinOps Owner, I want a consolidated view of spend attributed to each external agent versus internal agents, so that I can charge partner-driven costs back accurately.
- **US-0891** *(Executive — P2)* — As an Executive, I want a summary tile showing how many external agents are engaged, their aggregate trust posture, and any active revocations, so that I can gauge third-party fleet risk at a glance.
- **US-0892** *(Executive — P3)* — As an Executive, I want a trend of external-agent trust posture over the last quarter, so that I can report on whether our partner-agent ecosystem is getting safer or riskier.
- **US-0893** *(Security Engineer — P1)* — As a Security Engineer, I want external agents to re-attest their identity on a configurable interval and be auto-disengaged if re-attestation fails, so that long-lived sessions cannot outlive a compromised credential.
- **US-0894** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want fleet-memory reads to return provenance metadata (source, confidence, sharing policy applied), so that my external agent can decide how much to rely on a given memory.
- **US-0895** *(Compliance Officer — P1)* — As a Compliance Officer, I want a kill switch that disengages and revokes ALL external agents at once with a logged reason, so that I can respond instantly to a partner-side breach disclosure.
- **US-0896** *(Operator — P2)* — As an Operator, I want to simulate an external agent's proposed action against its clamp and budget without executing it, so that I can confirm governance will behave as expected before going live.
- **US-0897** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to revoke a previously granted fleet-memory write scope and quarantine the memories that agent already wrote, so that I can contain low-quality or poisoned contributions after the fact.
- **US-0898** *(Tenant Admin — P2)* — As a Tenant Admin, I want a clear visual indicator on `/trust` distinguishing engaged, disengaged, and revoked external agents, so that operators never confuse a paused agent with a permanently denied one.
- **US-0899** *(SRE — P2)* — As an SRE, I want trust revocations and engagements to emit events on the channels bus, so that downstream systems and on-call tooling react to governance changes in real time.
- **US-0900** *(Security Engineer — P3)* — As a Security Engineer, I want fleet-memory shared with external agents to be tagged and watermarked so leaked content can be traced back to the receiving agent, so that I can attribute a downstream knowledge leak to its source.

---

## Epic 19 — Integrations: Channels, MCP, Tools, Plugins & SDK

- **US-0901** *(Requester — P0)* — As a Requester, I want to start a work request by sending a message to a connected Telegram bot, so that I can delegate tasks without opening the dashboard.
- **US-0902** *(Requester — P0)* — As a Requester, I want to receive the finished result and status updates back in the same Slack thread I requested from, so that I keep the full conversation in one place.
- **US-0903** *(Operator — P1)* — As an Operator, I want to connect a Discord server and map specific channels to specific agent queues, so that requests land in the right workflow automatically.
- **US-0904** *(Operator — P1)* — As an Operator, I want to enable a Signal channel using a registered phone number, so that requesters on Signal can reach the workforce securely.
- **US-0905** *(Tenant Admin — P1)* — As a Tenant Admin, I want to onboard WhatsApp Business via its API credentials in the `/channels` screen, so that customers can request work over WhatsApp.
- **US-0906** *(Operator — P2)* — As an Operator, I want to enable inbound SMS through a provider number, so that requesters without smart apps can still submit text requests.
- **US-0907** *(Operator — P1)* — As an Operator, I want to connect an Email channel (IMAP/SMTP) so that emails to a shared inbox become work requests and replies are sent back by email.
- **US-0908** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want to bridge a Matrix room to a channel, so that federated/self-hosted chat users can request work.
- **US-0909** *(Operator — P3)* — As an Operator, I want to connect an iMessage channel on a Mac relay, so that Apple-ecosystem requesters can reach the workforce.
- **US-0910** *(Team Lead — P1)* — As a Team Lead, I want each incoming channel message to be attributed to a known requester identity, so that I can see who asked for what across channels.
- **US-0911** *(Security Engineer — P1)* — As a Security Engineer, I want per-channel allowlists of who may submit requests, so that only authorized identities can trigger agent work.
- **US-0912** *(Operator — P2)* — As an Operator, I want to set a per-channel auto-reply acknowledgement when a request is received, so that requesters know the work was accepted.
- **US-0913** *(Operator — P2)* — As an Operator, I want channel messages exceeding length limits to be chunked and reassembled correctly, so that long requests and long results are not truncated.
- **US-0914** *(Compliance Officer — P1)* — As a Compliance Officer, I want every channel inbound and outbound message recorded in the Operating Record, so that I have an auditable trail of requests and deliveries.
- **US-0915** *(Operator — P2)* — As an Operator, I want to test a channel connection from `/channels` with a synthetic ping before going live, so that I can confirm credentials and routing work.
- **US-0916** *(SRE — P2)* — As an SRE, I want channel connectors to reconnect with backoff after a provider outage, so that requests are not lost during transient failures.
- **US-0917** *(Operator — P3)* — As an Operator, I want to disable or pause a single channel without affecting others, so that I can take one integration offline for maintenance.
- **US-0918** *(Agent Author — P0)* — As an Agent Author, I want my external agent to connect to the Maverick MCP server via `maverick mcp`, so that it can call governed tools and read resources.
- **US-0919** *(Developer/Integrator — P0)* — As a Developer/Integrator, I want the MCP server to negotiate protocol `2025-11-25` and fall back to `2024-11-05`, so that both new and older MCP clients can connect.
- **US-0920** *(Agent Author — P1)* — As an Agent Author, I want to list available MCP tools with their JSON schemas, so that my agent can discover and call capabilities correctly.
- **US-0921** *(Agent Author — P1)* — As an Agent Author, I want to read MCP resources exposed by the platform (e.g. world-model facts), so that my agent has grounded context.
- **US-0922** *(Security Engineer — P0)* — As a Security Engineer, I want MCP tool calls to be authenticated and scoped to a token's permissions, so that external agents cannot invoke tools they are not granted.
- **US-0923** *(Platform Admin — P1)* — As a Platform Admin, I want each MCP tool invocation to be subject to budget and policy checks, so that external agents cannot bypass governance.
- **US-0924** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want the MCP server to support both stdio and streamable-HTTP transports, so that I can embed it locally or call it over the network.
- **US-0925** *(Agent Author — P2)* — As an Agent Author, I want MCP tool errors returned as structured tool-result errors rather than transport failures, so that my agent can handle them gracefully.
- **US-0926** *(Platform Admin — P2)* — As a Platform Admin, I want to publish my MCP server into the MCP registry with metadata and version, so that other teams can discover and connect to it.
- **US-0927** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want to browse the MCP registry to find available servers and their capabilities, so that I can wire up integrations without manual config exchange.
- **US-0928** *(Operator — P1)* — As an Operator, I want the `/tools` screen to list every declared tool with its description, parameters, and required permissions, so that I understand what the workforce can do.
- **US-0929** *(Agent Author — P0)* — As an Agent Author, I want to synthesize a new tool from a declarative spec on the `/tools` screen, so that I can add a capability without writing a full implementation by hand.
- **US-0930** *(Agent Author — P1)* — As an Agent Author, I want a synthesized tool to be validated against its schema before activation, so that malformed tools never reach the agent loop.
- **US-0931** *(Compliance Officer — P2)* — As a Compliance Officer, I want each tool tagged with a risk/permission level on `/tools`, so that high-impact tools require explicit approval to enable.
- **US-0932** *(Developer/Integrator — P0)* — As a Developer/Integrator, I want to build a custom tool with typed inputs/outputs and register it, so that the workforce can use my domain-specific capability.
- **US-0933** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want a tool I build to declare its required connectors and secrets, so that the platform provisions credentials safely at call time.
- **US-0934** *(Agent Author — P2)* — As an Agent Author, I want to dry-run a tool with sample inputs from `/tools`, so that I can verify behavior before exposing it to agents.
- **US-0935** *(Platform Admin — P1)* — As a Platform Admin, I want to install, enable, and disable plugins from the `/plugins` screen, so that I control which extensions are active in my tenant.
- **US-0936** *(Developer/Integrator — P0)* — As a Developer/Integrator, I want to scaffold a plugin using the TS plugin SDK in `sdks/plugin-ts`, so that I can build extensions in TypeScript with typed contracts.
- **US-0937** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want the TS SDK to expose typed hooks for registering tools, channels, and resources, so that my plugin integrates without guessing the interface.
- **US-0938** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want `npm test` (tsc + node --test) to validate my plugin against the SDK contract, so that I catch breakage before publishing.
- **US-0939** *(Security Engineer — P1)* — As a Security Engineer, I want plugins to run with a declared permission manifest enforced at load time, so that an extension cannot access capabilities it never requested.
- **US-0940** *(Platform Admin — P2)* — As a Platform Admin, I want plugin versions and signatures verified on install, so that only trusted, unmodified plugins run in production.
- **US-0941** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want to configure third-party connectors (e.g. SaaS APIs) once and reference them from tools and plugins, so that credentials are centralized and reusable.
- **US-0942** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want to embed the dashboard in my own app via `/embed-demo` with a scoped token, so that my users see governed work without leaving my product.
- **US-0943** *(Security Engineer — P2)* — As a Security Engineer, I want the embedded dashboard constrained by frame-ancestors and origin allowlists, so that it can only be embedded by approved hosts.
- **US-0944** *(Developer/Integrator — P0)* — As a Developer/Integrator, I want to call the public `/api/v1` with a bearer token, so that my services can create and query work programmatically.
- **US-0945** *(Security Engineer — P0)* — As a Security Engineer, I want mutating `/api/v1` requests to enforce CSRF same-origin checks in no-token mode, so that browser sessions cannot be abused cross-site.
- **US-0946** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want to register a webhook URL for work-lifecycle events, so that my system reacts when a goal completes or fails.
- **US-0947** *(Security Engineer — P1)* — As a Security Engineer, I want outbound webhooks signed with a shared secret and timestamp, so that receivers can verify authenticity and reject replays.
- **US-0948** *(FinOps Owner — P1)* — As a FinOps Owner, I want per-token and per-channel rate limits on the API and inbound channels, so that runaway integrations cannot exhaust budget or capacity.
- **US-0949** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want rate-limited API responses to return 429 with a Retry-After header, so that my client can back off correctly.
- **US-0950** *(External Auditor — P2)* — As an External Auditor, I want a read-only export of all integration configs (channels, MCP, tools, plugins, connectors, webhooks) with who enabled each and when, so that I can verify the tenant's integration surface independently.

---

## Epic 20 — Admin: Setup, Settings, Users & Knowledge

- **US-0951** *(Operator — P0)* — As an Operator, I want `maverick init` to complete a guided install in about two minutes, so that I can stand up a working instance without reading docs.
- **US-0952** *(Operator — P0)* — As an Operator, I want the install wizard to write a valid `config.toml` and `.env` to `~/.maverick/`, so that my configuration persists across restarts.
- **US-0953** *(Platform Admin — P0)* — As a Platform Admin, I want `maverick init` to refuse to overwrite an existing `config.toml` without an explicit `--force` flag, so that I never clobber a live configuration by accident.
- **US-0954** *(Operator — P1)* — As an Operator, I want the wizard to validate my provider API key before saving it, so that I find out it is wrong during setup rather than at first run.
- **US-0955** *(Developer/Integrator — P1)* — As a Developer/Integrator, I want a non-interactive `maverick init --yes` mode that reads answers from flags or env vars, so that I can provision instances from a CI pipeline.
- **US-0956** *(Operator — P0)* — As an Operator, I want `maverick doctor` to report the status of every dependency, key, and path in one command, so that I can diagnose a broken install at a glance.
- **US-0957** *(SRE — P1)* — As an SRE, I want `maverick doctor` to exit non-zero when any critical check fails, so that I can gate deploys on its result in automation.
- **US-0958** *(SRE — P1)* — As an SRE, I want `maverick doctor --json` to emit machine-readable check output, so that I can pipe health results into monitoring.
- **US-0959** *(Operator — P2)* — As an Operator, I want `maverick doctor` to print a suggested fix line under each failed check, so that I know the next action without searching the docs.
- **US-0960** *(Platform Admin — P0)* — As a Platform Admin, I want the wizard to let me choose a deployment profile of standard or enterprise/regulated, so that the instance starts with policy defaults appropriate to my environment.
- **US-0961** *(Compliance Officer — P0)* — As a Compliance Officer, I want the enterprise/regulated profile to enable encrypt-at-rest and audit logging by default, so that we meet controls without manual hardening.
- **US-0962** *(Platform Admin — P1)* — As a Platform Admin, I want to switch an existing instance from standard to regulated profile via a single setting, so that I can tighten governance without reinstalling.
- **US-0963** *(Operator — P0)* — As an Operator, I want a `/settings` screen that groups every config knob into labeled sections, so that I can find and change a setting without editing TOML by hand.
- **US-0964** *(Operator — P1)* — As an Operator, I want `/settings` changes to be validated and written back to `config.toml`, so that the UI and the file on disk never drift apart.
- **US-0965** *(Platform Admin — P1)* — As a Platform Admin, I want `/settings` to mark which knobs require a restart to take effect, so that I know when to bounce the service.
- **US-0966** *(Operator — P2)* — As an Operator, I want to choose a light, dark, or system theme in `/settings`, so that the dashboard matches my preference and ambient lighting.
- **US-0967** *(Operator — P2)* — As an Operator, I want to set UI density to compact, comfortable, or spacious, so that I can fit more or less information on screen.
- **US-0968** *(Operator — P3)* — As an Operator, I want to choose the dashboard font and base font size, so that text is comfortable for my eyesight and display.
- **US-0969** *(Operator — P0)* — As an Operator with low vision, I want a high-contrast theme that meets WCAG AA contrast, so that I can read the dashboard clearly.
- **US-0970** *(Operator — P1)* — As an Operator with dyslexia, I want a dyslexia-friendly font option, so that I can read long text panels with less strain.
- **US-0971** *(Tenant Admin — P1)* — As a Tenant Admin in an Arabic-speaking market, I want full right-to-left (RTL) layout support, so that the dashboard reads naturally for my users.
- **US-0972** *(Tenant Admin — P1)* — As a Tenant Admin, I want to select the dashboard language from supported locales, so that my operators work in their own language.
- **US-0973** *(Compliance Officer — P2)* — As a Compliance Officer, I want dates, numbers, and currency to follow the chosen locale, so that records are unambiguous for local reviewers.
- **US-0974** *(Operator — P3)* — As an Operator, I want to define and save a custom operator theme with my own accent colors, so that I can match our brand or distinguish environments.
- **US-0975** *(Platform Admin — P2)* — As a Platform Admin, I want to set an instance-wide default theme that new users inherit, so that the workspace looks consistent out of the box.
- **US-0976** *(Tenant Admin — P0)* — As a Tenant Admin, I want a `/users` screen to invite, list, and deactivate users, so that I control who can access the workforce.
- **US-0977** *(Tenant Admin — P0)* — As a Tenant Admin, I want to assign each user a role with scoped permissions, so that operators cannot change platform settings they should not touch.
- **US-0978** *(Security Engineer — P0)* — As a Security Engineer, I want to configure SSO via an OIDC identity provider, so that users authenticate with our corporate accounts instead of local passwords.
- **US-0979** *(Security Engineer — P1)* — As a Security Engineer, I want to map IdP groups to Lightwork roles, so that access is governed by our existing directory rather than manual assignment.
- **US-0980** *(Security Engineer — P1)* — As a Security Engineer, I want to enforce SSO-only login and disable local credentials per instance, so that there is one auditable authentication path.
- **US-0981** *(Compliance Officer — P2)* — As a Compliance Officer, I want every user invite, role change, and deactivation written to the audit log, so that I can prove who was granted what and when.
- **US-0982** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want a `/styles` screen to define reusable tone and writing-style presets, so that agent output stays on-brand across tasks.
- **US-0983** *(Team Lead — P2)* — As a Team Lead, I want to assign a style preset as the default for my team, so that my operators produce consistent deliverables without configuring it each time.
- **US-0984** *(Operator — P1)* — As an Operator, I want a `/cache` screen showing cache size, hit rate, and entry count, so that I can see whether caching is helping.
- **US-0985** *(FinOps Owner — P1)* — As a FinOps Owner, I want cache hit-rate to surface estimated token and dollar savings, so that I can quantify the cost benefit of the cache.
- **US-0986** *(Operator — P2)* — As an Operator, I want to clear the cache or selectively evict stale entries from `/cache`, so that I can force fresh results after upstream data changes.
- **US-0987** *(Operator — P1)* — As an Operator, I want `maverick facts` to list, add, and remove facts the platform knows about me, so that agents act on accurate personal context.
- **US-0988** *(Requester — P2)* — As a Requester, I want a `/facts` screen to review the facts the system holds about me, so that I can correct anything wrong before it influences my work.
- **US-0989** *(Compliance Officer — P1)* — As a Compliance Officer, I want each fact to record its source and timestamp, so that I can trace why the system believes something about a user.
- **US-0990** *(Knowledge Steward — P0)* — As a Knowledge Steward, I want to ingest knowledge sources such as documents, URLs, and folders into the world model, so that agents answer from our own material.
- **US-0991** *(Knowledge Steward — P1)* — As a Knowledge Steward, I want ingestion to show per-source progress and surface failures, so that I know which documents were actually indexed.
- **US-0992** *(Knowledge Steward — P2)* — As a Knowledge Steward, I want to re-sync or remove a previously ingested source, so that stale or retracted material stops influencing answers.
- **US-0993** *(Developer/Integrator — P2)* — As a Developer/Integrator, I want to inspect goals, facts, and episodes in the persistent world model at `~/.maverick/world.db`, so that I can debug what the platform has learned.
- **US-0994** *(SRE — P0)* — As an SRE, I want a backup command that snapshots `world.db` and config to a single archive, so that I can recover state after a failure.
- **US-0995** *(SRE — P0)* — As an SRE, I want a restore command that validates an archive before applying it, so that a corrupt backup cannot brick a running instance.
- **US-0996** *(Platform Admin — P0)* — As a Platform Admin, I want world-model migrations to run automatically on upgrade and refuse to downgrade the schema, so that the database stays consistent with the binary.
- **US-0997** *(Platform Admin — P1)* — As a Platform Admin, I want a dry-run that previews pending world-model migrations, so that I can review schema changes before applying them in production.
- **US-0998** *(Operator — P0)* — As an Operator, I want a killswitch that immediately halts all agent execution from the dashboard and CLI, so that I can stop runaway activity in an emergency.
- **US-0999** *(Security Engineer — P1)* — As a Security Engineer, I want killswitch activations and deactivations recorded with actor and reason, so that emergency stops are fully accountable.
- **US-1000** *(Operator — P2)* — As an Operator, I want guided `/walkthroughs` for setup, settings, users, and knowledge tasks, so that I can learn each admin surface in context instead of from external docs.

