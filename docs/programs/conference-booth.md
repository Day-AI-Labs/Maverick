# Conference booth — run-kit

**Roadmap ref:** 2027-H2 Distribution — "conference physical booth".
**Status:** kit complete; booking a conference and staffing it is the
remaining operational work. **Which conference, booth budget, and travel
spend are founder decisions.**

One booth, two or three staff, demos that run on hardware we control. The
audience for a governed-agent-runtime booth is platform/infra engineers,
security teams, and engineering leaders at regulated companies — pick
conferences where they are (infra/SRE, security, or the serious end of the
AI-engineering circuit) over generic AI expo floors.

## Demo stations (mapped to shipped features)

Every demo is a real run against a tagged release — no mockups, no videos
posing as live. Each station is one laptop + one screen, runs offline-capable
where possible, and has a 90-second version and a 5-minute version.

| Station | What it shows | Exactly what runs |
|---|---|---|
| **1. The swarm, live** | Long-horizon decomposition + true multi-agent parallelism | `maverick start "<prepared multi-step goal>"` with `maverick monitor` (plan-tree TUI) on the big screen; `maverick status --cost` shows the live spend meter |
| **2. Pull the plug** | Governance: hard caps + killswitch + audit | A goal with a deliberately tight `--max-dollars` cap dies at the cap on cue; `maverick halt` kills a second run mid-flight; `maverick audit verify` then proves the tamper-evident chain on the booth's own log |
| **3. The shield says no** | Safety chokepoints | A scripted prompt-injection / secret-exfil attempt blocked at input/tool/output; show the reason codes; for the security crowd, `python -m maverick_shield.redteam` running the labeled corpus gate live |
| **4. Air-gapped laptop** | Self-host claim made physical | A laptop with **Wi-Fi off**: Ollama as the provider, a local sandbox, `maverick airgap check` passing on stage — the "your data never leaves" claim demonstrated, not asserted |
| **5. Drive it from anything** (optional, staff permitting) | The interop surface | Lightwork driven from an MCP client (`maverick mcp`) and a message round-trip on a chat channel via `maverick serve` |

Station prep checklist (per laptop, before the show):

- [ ] Clean profile: scratch `~/.maverick/`, low-limit API keys, budget caps
      set in `config.toml`, `maverick doctor` green.
- [ ] Demo goals rehearsed ≥5 times; timings known; a recorded fallback for
      each (conference Wi-Fi fails — assume it will; stations 2 and 4 run
      fully offline by design).
- [ ] No real data, no production keys, terminal font ≥18pt.
- [ ] Power: each station on its own outlet + a power strip we bring.

## Booth materials

- Backdrop: name + the one-liner from the [press kit](./press-and-case-studies.md)
  boilerplate — no feature-soup wall of text.
- One A5 handout: the comparison-at-a-glance table from
  [`docs/comparison.md`](../comparison.md), install one-liner, QR to the
  repo, evaluation-license contact. Claims grounded in `FEATURES.md`, the
  proprietary license stated plainly.
- Swag per [`swag.md`](./swag.md).
- A "what's real" sign: alpha status and the today-vs-planned framing from
  the README — honesty at the booth converts better with this audience than
  bravado.

## Staffing

- **2 minimum, 3 recommended** (two on demos, one floating/queueing). All
  staff can run every station and answer the hard questions: licensing
  (proprietary, per-engagement), "why not open source" (the honest README
  answer + the lite-edition status: a stated possibility, not a
  commitment), security posture ([`SECURITY.md`](../../SECURITY.md),
  signed audit, red-team CI), and "how is this different from Devin /
  Hermes / OpenClaw" (the comparison page — describe competitors coarsely
  and direct people to vendors' own docs, exactly as `comparison.md` does).
- Shift in pairs; nobody works the floor solo longer than 2 hours.
- Code of conduct: ours ([`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md))
  and the conference's both apply to staff conduct.

## Lead capture

- **Consent-first**: a short form (name, company, email, "what would you
  evaluate it for", "ok to contact: y/n") on paper or a tablet — no badge
  scanning unless the person explicitly asks to be contacted. We sell a
  governance product; the booth behaves like it.
- Tag leads at capture: *evaluator* (wants a license conversation),
  *practitioner* (wants docs/community), *partner* (vendor — route to
  [`integration-partnerships.md`](./integration-partnerships.md)).
- Follow-up within 5 business days: evaluators get the licensor contact;
  practitioners get getting-started + office-hours links. One email each.
  Then the list is retired — no drip campaign.

## Budget + measurement

Line items (amounts founder-set): booth fee, travel/lodging, backdrop +
print, swag, shipping. After the show, one memo: leads by tag,
demos-per-day estimate, questions we couldn't answer (docs gaps → issues),
evaluation inquiries within 30 days, and a keep/change list. Two shows with
zero evaluator leads = wrong conference circuit; change venues before
changing the booth.
