# Maverick

> Open-source recursive multi-agent swarm. One kernel, every model.

Maverick is an **agent framework** for users who want the depth of
Devin, Hermes, and OpenClaw without paying for any of them. It runs
locally, drives any LLM (Claude, GPT, Kimi, Grok, Gemini, DeepSeek,
Ollama, OpenRouter), and ships with the same safety surface that
hosted platforms gate behind subscriptions.

## What you can do with it

- **Long-horizon software work**: recursive agent-spawns-agent
  orchestration with shared world model, budgets, and audit log.
- **Use your existing chat subscriptions**: ChatGPT Plus, Claude Pro,
  Kimi, X Premium, Gemini Advanced — drive them from the agent via
  captured browser sessions, no extra API spend. Note: session providers
  have no native function-calling, so Maverick gives them tools through a
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

## Pricing

There isn't any. Maverick is MIT-licensed, runs entirely on your
hardware, and we don't take a cut of your LLM spend. The project is
brand-building for the founder; if it helps you ship, that's the
whole reason it exists.

You can support the project via
[GitHub Sponsors](https://github.com/sponsors/cdayAI) or
[Open Collective](https://opencollective.com/maverick).

## Where to go next

- [Getting started](getting-started.md) — install + first goal
- [Configuration](configuration.md) — providers, channels, budgets
- [Deployment](deployment.md) — desktop / docker / VPS / phone modes
- [Safety](safety.md) — shield, audit log, kill switches, consent
- [Security hardening](security-hardening.md) — enterprise opt-in controls (capabilities, tenancy, quotas, OIDC, encryption-at-rest, audit signing) + compliance commands
- [Plugins](plugins.md) — extending the tool / channel / skill surface
- [Self-learning](self-learning.md) — acquire skills, tools, MCP servers, and APIs on demand
- [Roadmap](ROADMAP.md) — 36-month plan, all open
- [Contributing](CONTRIBUTING.md) — how to send PRs
