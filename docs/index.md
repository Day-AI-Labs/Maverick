# Lightwork

> Enterprise recursive multi-agent swarm. One kernel, every model.

Lightwork is an **agentic enterprise platform**: a governed AI workforce of
1,118 prebuilt specialists across 26 business suites that provably improves
with use — deployed in your own environment. It drives any
LLM (Claude, GPT, Kimi, Grok, Gemini, DeepSeek, Ollama, OpenRouter), and
ships a governed, auditable safety surface built for regulated teams.
Lightwork is proprietary, commercially licensed software (see
[`LICENSE`](LICENSE)).

## What you can do with it

- **Long-horizon software work**: recursive agent-spawns-agent
  orchestration with shared world model, budgets, and audit log.
- **Use your existing chat subscriptions**: ChatGPT Plus, Claude Pro,
  Kimi, X Premium, Gemini Advanced — drive them from the agent via
  captured browser sessions, no extra API spend. Note: session providers
  have no native function-calling, so Lightwork gives them tools through a
  **simulated** markdown tool-call protocol — it works for tool-using
  roles, but reliability is model-dependent and weaker than an API-key
  provider's native tool use.
- **Computer use & web browser**: Anthropic-spec computer-use tool +
  Playwright-driven browser tool, with kill switches and an audit
  trail for every action.
- **Multi-channel deployment**: Telegram, Discord, Slack, Signal,
  Email, Matrix, WhatsApp, SMS, iMessage — one config, all channels.

## Quick start

```bash
pipx install 'maverick-agent[installer]'
maverick init                # interactive wizard (3 minutes)
maverick start "review my latest commit"
```

Or skip the prompts:

```bash
maverick init --fast         # defaults: Anthropic + local sandbox + $5 cap
```

## Watch it work

```bash
maverick monitor             # live plan-tree TUI in another terminal
maverick logs                # audit log
maverick cost                # spend summary
```

## Licensing & access

Lightwork is **proprietary, commercially licensed** software (see
[`LICENSE`](LICENSE)). It is self-hostable — the runtime executes entirely
in your own environment — and use requires a license. Pricing is handled
per engagement; [contact us](https://github.com/Day-AI-Labs/Lightwork) for
evaluation or enterprise access.

A deliberately stripped-down **open-source "lite" edition** may be released
later as a community on-ramp; the full runtime and the governance/compliance
platform remain proprietary.

## Where to go next

- [Getting started](getting-started.md) — install + first goal
- [Architecture](architecture.md) — the governed agent runtime (OS-style primitives)
- [Configuration](configuration.md) — providers, channels, budgets
- [Deployment](deployment.md) — desktop / docker / VPS / phone modes
- [Safety](safety.md) — shield, audit log, kill switches, consent
- [Security hardening](security-hardening.md) — enterprise opt-in controls (capabilities, tenancy, quotas, OIDC, encryption-at-rest, audit signing) + compliance commands
- [Security & compliance overview](enterprise/security-overview.md) — the data-boundary guarantee, identity, audit/evidence, reference architecture
- [Editions](enterprise/editions.md) — Community vs Enterprise
- [Plugins](plugins.md) — extending the tool / channel / skill surface
- [Self-learning](self-learning.md) — acquire skills, tools, MCP servers, and APIs on demand
- [Features → Dreaming / Hindsight / Fleet memory](FEATURES.md) — the full learning lifecycle: consolidation, regression detection, value proof, and the cross-vendor memory plane
- [Features](FEATURES.md) — everything Lightwork does today (shipped capabilities + tools)
- [Roadmap](ROADMAP.md) — the forward backlog (what isn't built yet)
- [Contributing](CONTRIBUTING.md) — how to send PRs
