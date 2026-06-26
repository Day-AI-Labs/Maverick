# Oversight experience — audit & plan

> The strategic UX bet: the **supervisor / oversight experience** is both
> Lightwork's biggest experience gap and its competitive moat (see
> [`strategy/competitive-landscape.md`](../strategy/competitive-landscape.md)).
> This note audits what exists and lays out the plan to make one experience
> excellent rather than thirty pages adequate.

## Four users, four experiences

"Good experience" isn't one thing — an enterprise agentic platform has four
distinct users, and each needs a different surface to feel good:

| Persona | Job | Surface today | State |
|---|---|---|---|
| **Operator / admin** | install, configure, set policy | installer wizard + dashboard | functional |
| **Supervisor / approver** | review agent actions, approve high-risk ops, halt | `/oversight`, `/approvals`, `/trajectory`, `/plan_tree` | **the wedge — the focus of this plan** |
| **Builder / developer** | define goals, fleets, skills; integrate | CLI (strong), VS Code, REST + gRPC | strong CLI, thin GUI |
| **End-user / requester** | ask an agent to do work | channels (Slack/Telegram/…) + `/chat` | decent (conversational) |

The recommendation is **not** to polish all four. It's to make the supervisor
experience the crown jewel and leave the rest as the competent console they are.

## Current state (audited)

The dashboard is a ~30-page server-rendered console (FastAPI + Jinja, inline
CSS/vanilla JS, four themes incl. high-contrast, SSE streaming, **no build
step** — ships in the wheel, works air-gapped). That no-build choice is correct
for self-hosted enterprise and should be kept.

`/oversight` is already a solid "mission control": live killswitch state, active
agents, pending-approval count, a live **Active now** panel (5 s poll), the
inline approval queue (approve/deny wired to the decision API), a by-guardrail
breakdown (governance / shield / capability / egress / consent / halt), and an
incident-review date-range filter. Owner-scoped, fail-soft.

**What it was missing — the gap this plan targets:** when a supervisor sees an
agent running or an approval pending, there was no way to answer **"why is this
agent doing this?"** without context-switching to the trajectory page. Governance
was *configured and logged* but not *visible in the moment of decision*.

## Shipped: the "why this action" drill-down (first slice)

`GET /api/v1/oversight/why/{goal_id}` (owner-scoped) returns a goal's status,
cost-so-far, a by-kind summary, and the recent reasoning → tool → decision chain.
The `/oversight` **Active now** panel now has a per-agent **"why?"** button that
opens this chain inline. This is the seed of the hero experience: the moment a
supervisor can *see why*, the governance value becomes tangible.

## The plan — make oversight the hero

In rough priority order (each a 1–2 week slice, all on existing data + the
no-build stack):

1. **"Why" everywhere it's needed.** Extend the drill-down to the **approval
   queue** ("why is this approval being requested" — the chain that led to the
   REQUIRE_HUMAN hold) and to past interventions in the trail. _(Done for Active
   now; approvals next.)_
2. **Live, not polled.** Move Active now + the trail from 5 s polling to the
   existing SSE stream so the console feels real-time during a demo.
3. **Cost & risk at a glance.** Per-agent running cost + a risk signal (recent
   guardrail hits, high-risk tools requested) on each Active-now row, so a
   supervisor triages without drilling in.
4. **One-click intervention in context.** Halt / cancel a *single* goal (not just
   the global killswitch) from its row, with confirmation — pairs with the gRPC
   `Cancel` already shipped.
5. **The plan-tree as the centrepiece.** Promote the live plan-tree (what the
   swarm is decomposing right now) into the oversight view, so "what is happening"
   and "why" sit together.
6. **Audit-ready in one click.** "Export this incident" from the trail → the
   signed audit slice an auditor would accept (the evidence we sell).

## Principles

- **Keep the no-build stack.** Self-hosted enterprise wants a single artifact, no
  npm, air-gap-friendly. Vanilla JS + SSE + Jinja is a feature, not debt.
- **Owner-scoped + fail-soft, always.** Every oversight surface already scopes to
  the caller's goals and degrades to an empty panel rather than a 500. Hold that
  line — leaking the audit trail is fatal for a governance product.
- **One excellent workflow beats ten adequate pages.** The supervisor watching the
  fleet work, seeing *why*, and intervening in one place is the demo that sells.
