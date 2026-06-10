# Observability and provider integrations

How to wire Maverick into OpenRouter, LangSmith, and Helicone using the
surfaces that already ship: the OpenRouter provider in the 12-provider router
(`llm.py`), the opt-in OpenTelemetry / Prometheus / Sentry observability layer
(`observability.py`), and the `base_url` mechanism on OpenAI-compatible
providers. Everything here is self-serve configuration — see the
[partnership status](#partnership-status) note at the end.

Substrate, per [`FEATURES.md`](../FEATURES.md):

- **OpenTelemetry traces, Prometheus `/metrics`, Sentry** — all opt-in,
  off by default (`observability.py`).
- **OpenRouter** is one of 12 routable providers, with cost-aware routing
  (`cost_router.py`) and provider failover (`provider_failover.py`,
  `failover_policy.py`) layered on top, all opt-in.
- **Generic OpenAI-compatible endpoints via `base_url`** — the mechanism
  behind the TGI / vLLM / `openai_compatible` providers.

## OpenRouter as a provider

OpenRouter is OpenAI-compatible at `https://openrouter.ai/api/v1` and
aggregates models from many vendors. Maverick ships a first-class provider for
it — configure a key, then route any role to it.

```toml
# ~/.maverick/config.toml

[providers.openrouter]
api_key = "${OPENROUTER_API_KEY}"   # env var interpolation; secret lives in ~/.maverick/.env

[models]
# Per-role model specs are "provider:model-id". OpenRouter model ids are
# "vendor/model", so the full spec is "openrouter:vendor/model".
researcher = "openrouter:meta-llama/llama-3.3-70b"
summarizer = "openrouter:meta-llama/llama-3.3-70b"
```

Roles are independent — mix OpenRouter workers with an Anthropic orchestrator
freely (see [Configuration](../configuration.md)). On top of the static picks,
two opt-in layers apply:

- **Cost-aware routing** (`cost_router.py`; enable via `[routing] cost_aware`
  or `MAVERICK_COST_ROUTING`) with per-role policies
  (`[routing.roles.<role>]`: provider allow/deny, cost ceiling, tier floor).
- **Provider failover** (`provider_failover.py`) with a policy engine
  (`failover_policy.py`): auth errors fail fast, 429/timeout/5xx fail over,
  per-model cooldowns.

### Verify

```bash
maverick start "Summarize the README in this directory" --max-dollars 0.25
maverick status --cost        # spend attributed to the run's models
maverick budget               # total + per-run cost history
```

The cost report attributes spend to the model spec you routed, so an
`openrouter:*` line confirms the calls went through OpenRouter. For a
pre-flight estimate without spending, use `maverick start ... --dry-cost`.

## Tracing into LangSmith

Maverick has **no bespoke LangSmith integration**. What it has is an opt-in
OpenTelemetry exporter that speaks standard OTLP/HTTP, emitting spans that
follow the OTel GenAI semantic conventions (span name `<operation> <model>`;
provider, model, token, and cost attributes) — one span per LLM call, per tool
invocation, and per provider dispatch. Any backend that ingests OTLP can
receive them; LangSmith qualifies via whatever OTLP endpoint and auth headers
its own documentation specifies.

```bash
pip install 'maverick-agent[observability]'   # exporter deps are optional

export MAVERICK_OTEL_EXPORTER=otlp
# Default endpoint is a local collector: http://localhost:4318/v1/traces.
# Point it at your backend's documented OTLP traces endpoint instead:
export MAVERICK_OTEL_ENDPOINT="https://<your-backend-otlp-endpoint>/v1/traces"
# Auth/routing headers, comma-separated k=v pairs (same format as the
# standard OTEL_EXPORTER_OTLP_HEADERS) — use the header names your backend
# documents (LangSmith, Honeycomb, Datadog, Grafana Cloud, ...):
export MAVERICK_OTEL_HEADERS="<header-name>=<value>"

maverick start "..." 
```

### Verify

On startup, the log confirms the exporter wired up:

```
observability: OTLP traces -> https://<endpoint> (1 header(s))
```

Then look in the backend for spans named like `<operation> <model>` with
token/cost attributes. To rule out backend-side auth issues first, run a local
`otel-collector` on `localhost:4318` with the default endpoint and confirm
spans arrive there. The Prometheus side works the same way:

```bash
MAVERICK_PROMETHEUS_PORT=9100 maverick start "..."
curl -s http://127.0.0.1:9100/metrics | grep maverick_llm
# maverick_llm_calls_total, maverick_llm_tokens_total,
# maverick_llm_cache_tokens_total, maverick_budget_dollars_spent, ...
```

## Helicone as a gateway

Maverick has **no bespoke Helicone integration** either. LLM gateways like
Helicone proxy the OpenAI chat-completions protocol, and Maverick already
supports arbitrary OpenAI-compatible endpoints through the `base_url`
mechanism — the same one behind the TGI, vLLM, and Ollama providers. The
generic form is the `openai_compatible` provider:

```toml
[providers.openai_compatible]
# The gateway's OpenAI-compatible endpoint, passed through verbatim —
# supply the exact URL (including any /v1 suffix) the gateway documents.
base_url = "https://<your-gateway-host>/v1"
api_key  = "${GATEWAY_API_KEY}"

[models]
summarizer = "openai_compatible:<model-id-the-gateway-expects>"
```

Two honest constraints:

- Maverick sends the key as a standard OpenAI-style bearer `Authorization`
  header. Gateways that authenticate that way (or encode routing into the key
  or URL) work; a gateway mode that requires **extra custom headers on every
  LLM request** has no config knob today.
- `base_url` is per-provider config, so a gateway fronting one provider is the
  supported shape; consult your gateway's docs for its URL format and key
  handling rather than this page.

### Verify

```bash
maverick start "Summarize the README in this directory" --max-dollars 0.25
```

Confirm the request shows up in the gateway's own request log/dashboard, then
cross-check the local view: `maverick status --cost` attributes the spend to
the `openai_compatible:*` model spec, and (with
`MAVERICK_PROMETHEUS_PORT` set) the `maverick_llm_calls_total` counter
increments.

## Partnership status

These are **self-serve integration paths** built on generic protocols — an
OpenRouter provider client, OTLP trace export, and OpenAI-compatible
`base_url` overrides. No formal partnership, co-marketing arrangement, or
endorsement with LangSmith, Helicone, OpenRouter, or any other vendor is
implied; establishing those is maintainer/business work tracked on the
[roadmap](../ROADMAP.md), not an engineering artifact in this repo.
