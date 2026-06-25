# Flagship Demo — "Govern a risky autonomous action, then prove it"

> 5–7 minutes. The demo that ends with **verifiable evidence**, not a chat
> transcript. Every step below maps to functionality merged in `main`; the
> bracketed paths/flags are real. Rehearse once end-to-end before showing it.

## The story (one breath)

An AI agent runs a **vendor-payment workflow** in a browser. It does the safe
parts autonomously, then reaches a **"Pay $48,200" button**. Maverick **pauses**
that single action, routes it to a **human approver**, seals **before/after
screenshots**, and writes a **tamper-evident, signed record**. Then we **replay**
the whole run, **export a one-click evidence packet**, and let the audience
**verify the cryptographic chain themselves** with a standalone binary — no trust
in us required.

This is the thing a CISO, auditor, or regulator cannot get from an agent
framework or a chatbot.

---

## Pre-flight (do before the call)

Hardened, evidence-on configuration (all real flags):

```toml
# ~/.maverick/config.toml
[enterprise]
mode = true                 # fail-closed egress + capabilities + at-rest sealing
[audit]
sign = true                 # Ed25519 tamper-evident chain
```
```bash
export MAVERICK_CONSENT_MODE=dashboard      # high-risk actions park in the approvals queue
export MAVERICK_SCREENSHOT_KEY=<key>        # seal before/after screenshots as evidence
maverick enterprise verify --require        # prove the boundary actually holds (exits non-zero if not)
```
Open the dashboard; have these tabs ready: **/discovery**, **/simulate**,
**/approvals**, **/replay**, **/trust**. Pre-create the vendor-payment goal so you
don't burn time typing.

---

## Act 1 — "You can't govern what you can't see" (60s)

1. Open **/discovery**. Talk while it renders: *"Before we run anything — here's
   everything this deployment can do and govern: every tool by risk tier, every
   MCP server with its supply-chain pin, the model providers, channels, and
   external agents."*
2. Open **/trust**: *"And here's the permission graph for agents we didn't even
   build — each one's allowed tools, risk ceiling, budget, and direction."*

> Point made: **inventory + least privilege across heterogeneous agents**, before a single action.

## Act 2 — "Show me the decision before it happens" (45s)

1. Open **/simulate**. Enter surface `browser`, action `click`, target
   `text=Pay $48,200`. Submit.
2. Result: **risk = HIGH**, **decision = REQUIRES APPROVAL**, with the plain-English
   *why*. *"We can dry-run any action and see the policy decision before anything
   runs — no side effects."*

## Act 3 — the run, and the pause (2–3 min) ← the moment

1. Kick off the vendor-payment goal. Let the agent **navigate, read the invoice,
   fill fields** autonomously — narrate that these low-risk steps just run.
2. It reaches **"Pay $48,200."** The run **stops**. Switch to **/approvals**: the
   action is parked — **`browser.click` · risk HIGH · "Pay $48,200"** — with who/what/why.
   *"Maverick gated exactly one action — the consequential one — and routed it to
   a human. The agent is blocked, waiting."*
3. **Approve** it in the console. The action executes. Note for the room:
   **before and after screenshots were just sealed** into a tamper-evident ledger,
   and the approval is attributed to you.

> Point made: **containment + human-in-the-loop on the action that matters**, not a blanket block.

## Act 4 — "Now prove it" (2 min) ← the close

1. Open **/replay?goal=<id>**. Walk the timeline: run start → tool calls →
   **Approval requested (HIGH)** → **Approval decision: approve [dashboard]** →
   **Evidence captured (before/after, sha256…)** → run end. Top of the page: a
   **"Chain verified ✓"** badge.
2. Click **"Export evidence packet (JSON)"** (`/api/v1/replay/<id>/evidence`).
   *"One click. This is what your CISO, auditor, or regulator keeps — the goal, the
   chain verdict, the summary, and the full attributed timeline."*
3. **The mic-drop** — verify it without trusting us:
   ```bash
   maverick-verify-audit ~/.maverick/audit/<today>.ndjson --keys-dir ~/.maverick/audit/keys
   # OK: N rows verified   (exit 0)
   ```
   *"That's a standalone binary — no Python, no Maverick, no trust in us. Your
   auditor runs it themselves. If anyone had altered one byte of that record, it
   exits non-zero and names the row."* (Optional: flip a byte live, re-run, show
   the failure + the same verdict from `maverick audit verify`.)

> Point made: **independently verifiable evidence.** This is the control point.

---

## Landing line

> *"Every enterprise is deploying agents. Nobody can answer: who owns them, what
> can they reach, what did they do, why, and can you prove it. You just watched
> Maverick discover the surface, simulate the risk, gate the one action that
> mattered, get a human approval, and produce evidence an auditor can verify
> without trusting us — all self-hosted in your environment."*

## If asked / failure-proofing

- **"Does this slow the agent down?"** Only gated (high-risk) actions pause; the
  rest run free. Default mode is auto-approve — gating is something *you* turn on.
- **"What if the dashboard is down?"** The gate fails open by design (kernel rule 1);
  consent falls back rather than wedging the agent. Show it's a deliberate posture.
- **Live-demo risk:** record a backup screen capture of Acts 3–4. If the browser
  automation flakes, the sealed-evidence + verify story still lands from the recording.
- Keep a terminal showing `maverick enterprise verify --require` passing — proof
  the boundary is real, not a slide.

## What NOT to lead with
The 1,734 specialist packs, the channels, the IDE/mobile surfaces. They're proof
of platform maturity, not the demo. The demo is **govern → approve → prove**.
