# Sub-processor Register

| Field | Value |
| --- | --- |
| Document ID | REG-01 |
| Owner | Christopher Day |
| Approver | Christopher Day |
| Version | 1.0 |
| Status | Approved — effective 2026-06-24 (Christopher Day) |
| Review cycle | On any sub-processor change + quarterly |
| Frameworks | ISO 27001 A.5.19–A.5.23; ISO 42001 A.10.2/A.10.3; SOC 2 CC9.2; GDPR Art. 28/30 |

The live inventory of every third party that processes Organization/customer data
for a Maverick deployment. It backs the customer-facing
[sub-processor disclosure](../../enterprise/legal/subprocessors.md) and the
[Vendor Management Procedure](../procedures/vendor-management-procedure.md)
(PROC-07). **Maintain it per deployment** and notify customers **before** adding a
sub-processor, per the DPA change-notification clause.

> Maverick's footprint is **deployment-dependent**. A self-hosted, egress-locked
> (`[enterprise] mode = true`) deployment using a self-hosted model has a *near-
> empty* list — inference and data stay on the customer's infrastructure. A SaaS
> deployment calling a hosted LLM must disclose that provider. Fill the columns
> for **your** deployment; the rows below are the candidate set to assess.

## How to use

For each third party in scope: record the data exposed, region, the signed DPA
link, and a review date. Cross-reference the [vendor register](vendor-register.md)
(REG-04) for the risk tier and review cadence. Remove rows that don't apply to
your deployment; add any deployment-specific ones.

## Candidate sub-processors (assess + disclose those that apply)

| Sub-processor | Purpose | Data exposed | Region | DPA on file | Status |
| --- | --- | --- | --- | --- | --- |
| LLM provider — Anthropic (`claude-*`) | Inference for agent turns (default provider) | Prompts + tool I/O at inference time | `<US / region>` | `<link>` | `<in use? y/n>` |
| LLM provider — OpenAI (`gpt-*`, `o*`) | Inference (if configured) | Prompts + tool I/O | `<…>` | `<link>` | `<y/n>` |
| LLM provider — Google Gemini | Inference (if configured) | Prompts + tool I/O | `<…>` | `<link>` | `<y/n>` |
| LLM provider — xAI (`grok-*`) | Inference (if configured) | Prompts + tool I/O | `<…>` | `<link>` | `<y/n>` |
| LLM provider — DeepSeek | Inference (if configured) | Prompts + tool I/O | `<…>` | `<link>` | `<y/n>` |
| LLM provider — Moonshot / Kimi | Inference (if configured) | Prompts + tool I/O | `<…>` | `<link>` | `<y/n>` |
| OpenRouter | Inference broker (if configured) | Prompts + tool I/O routed to the chosen model | `<…>` | `<link>` | `<y/n>` |
| Self-hosted model (Ollama / vLLM / TGI) | On-prem inference | None leaves the boundary | On-prem | n/a | `<y/n>` |
| Cloud / hosting provider | Compute, storage, networking for a hosted deployment | All processed data at rest/in transit on their infra | `<…>` | `<link>` | `<y/n>` |
| Telemetry / error tracking (if enabled) | Error monitoring | Scrubbed error events (secrets redacted by `maverick.secrets`) | `<…>` | `<link>` | `<y/n>` |
| Email / SMS / chat channel provider (if a channel is enabled) | Message delivery | Message content + recipient | `<…>` | `<link>` | `<y/n>` |
| Vector store / object storage (if enabled) | RAG / attachments | Knowledge + attachment content | `<…>` | `<link>` | `<y/n>` |

## Data-minimization notes (controls that reduce exposure)

- **Enterprise / egress lock** (`[enterprise] mode = true`): refuses cloud LLM
  providers, keeping inference on-prem — verify with `maverick enterprise verify`.
- **Secret scrubbing** (`maverick.secrets`): API keys, tokens, and PEM/JWT material
  are redacted from logs, audit, MCP stderr, and exports before they leave the
  process — document this as a data-minimization control in customer disclosures.
- **At-rest encryption** (`[encryption] at_rest = true`) and **tenant isolation**
  (`[tenancy] by_user = true`) bound what any one sub-processor can be exposed to.

## Change control

Adding or changing a sub-processor is a change subject to
[PROC-07](../procedures/vendor-management-procedure.md): assess via the
[vendor security questionnaire](../templates/vendor-security-questionnaire.md),
sign a DPA, update this register **and** the customer-facing disclosure, then
notify affected customers before the change takes effect.
