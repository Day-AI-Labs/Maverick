# Press kit

Boilerplate, key facts, and naming rules for writing about Maverick. Counts
and capability claims on this page are grounded in
[`FEATURES.md`](./FEATURES.md), the catalogue of shipped features.

## Boilerplate

Maverick is a proprietary, commercially licensed agent runtime for enterprises
and regulated teams that need AI agents they can govern, audit, and run
entirely in their own environment. Hand it a goal and its orchestrator
decomposes the work and spawns specialist sub-agents — researcher, coder,
writer, verifier — that work in parallel under hard dollar, wall-clock, and
tool-call caps, with every input, tool call, and output screened by the Agent
Shield safety layer and every action recorded in a signed, append-only audit
log. The runtime is self-hosted — laptop, Docker, VPS, Kubernetes, or
air-gapped — and model-agnostic: 12 LLM providers, routable per role, so
customers pick the models. It ships 100+ built-in tools, 14
messaging/voice/wearable channels, and 7 sandbox backends, and can be driven
from other languages over MCP and gRPC. Maverick is developed by Day AI Labs.

### 50-word version

Maverick is a proprietary, commercially licensed, self-hosted AI agent runtime
for enterprises. A recursive orchestrator decomposes goals and spawns
specialist sub-agents that work in parallel under hard budget caps, behind a
safety shield, with a signed audit log. It ships 1,118 prebuilt specialist
agents across 26 business suites (every pack lint-audited for least-privilege
envelopes), a closed learning lifecycle — agents consolidate experience,
provably improve, and every learned change is audited and reversible — plus
100+ tools, 14 channels, 7 sandbox backends, and 12 LLM providers.

### 25-word version

Maverick is a proprietary, self-hosted multi-agent runtime for enterprises: a
recursive swarm under hard budget caps, a safety shield, and a signed,
append-only audit log.

## Key facts

- **License model**: proprietary, commercially licensed. Use, redistribution,
  and derivative works require a license (see [`LICENSE`](../LICENSE)). A
  stripped-down open-source "lite" edition is a stated possibility on the
  [roadmap](./ROADMAP.md), not a commitment.
- **Deployment**: self-hosted — laptop, Docker, VPS, Kubernetes, or a
  disconnected/air-gapped network with no required data egress.
- **Implementation**: Python (3.10–3.12), 2000+ tests in CI; other languages
  drive the runtime over MCP and gRPC rather than re-implementing it.
- **Architecture**: recursive multi-agent swarm — an orchestrator spawns
  parallel specialist sub-agents, with a default-on verifier, reflexion
  retries, and a graded critic.
- **Safety**: the Agent Shield layer screens at three chokepoints (input,
  tool call, output); hard budget caps and a killswitch bound every run.
- **Surface area** (counts from `FEATURES.md`): 100+ built-in tools, including
  ~47 SaaS connectors; 14 wired channels; 7 sandbox backends; 12 LLM
  providers, routable per role.
- **Auditability**: signed, append-only audit log (`maverick audit verify`),
  SIEM export, encryption-at-rest, DSAR, data-retention enforcement.
- **Distribution**: 8 packages on PyPI, a GHCR Docker image, PyInstaller
  binaries, and native double-click installers for Windows/macOS/Linux.
- **Status**: alpha, installable today.
- **Maker**: Day AI Labs (Christopher Day).

## Naming and trademark usage

"Maverick", the Maverick name, and the Maverick logo are trademarks of
Christopher Day / Day AI Labs and are **not** licensed under the software
[`LICENSE`](../LICENSE). The full policy is
[`TRADEMARK.md`](../TRADEMARK.md); the short version for writers:

- **Product name**: "Maverick", capital M. The CLI command is lowercase
  `maverick`; the PyPI distribution is `maverick-agent`.
- **Permitted without asking**: nominative, factual references — naming
  Maverick in an article, review, or comparison, or saying something is
  "compatible with Maverick" — where no endorsement or affiliation is implied.
- **Not permitted without written permission**: using the marks (or
  confusingly similar names/logos) for your own product, service, fork, or
  distribution; in domain names, package names, company names, or advertising;
  or describing any build as the "official" Maverick.

For permission requests, contact the licensor via
[github.com/Day-AI-Labs/Maverick](https://github.com/Day-AI-Labs/Maverick).

## Logos and assets

> **Assets to be added by maintainers.** Logo files (light/dark, SVG/PNG),
> wordmark, and screenshot set are not yet published in this repository. Until
> they land here, do not source logos from third parties — request assets via
> the contact below.

| Asset | Status |
|---|---|
| Logo (SVG, light/dark) | _placeholder — to be added by maintainers_ |
| Wordmark | _placeholder — to be added by maintainers_ |
| Dashboard / TUI screenshots | _placeholder — to be added by maintainers_ |

## Press contact

> **Placeholder — maintainers: add a press email/contact here.** Until a
> dedicated press contact is published, reach the project via
> [github.com/Day-AI-Labs/Maverick](https://github.com/Day-AI-Labs/Maverick).
