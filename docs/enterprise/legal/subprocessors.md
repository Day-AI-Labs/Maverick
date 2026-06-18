# Sub-processor disclosure

> Template. List every third party that processes customer data for *this*
> deployment. A self-hosted, egress-locked deployment has a **short** list; a
> SaaS deployment that calls a hosted LLM must disclose that provider.

**Last updated:** `<YYYY-MM-DD>` · **Deployment:** `<customer / instance>`

| Sub-processor | Purpose | Data exposed | Region | Their DPA |
|---|---|---|---|---|
| `<LLM provider, e.g. Anthropic>` | LLM inference for agent turns | Prompts + tool I/O sent at inference time | `<US / EU / …>` | `<link>` |
| `<telemetry, e.g. Sentry>` (if enabled) | Error tracking | Scrubbed error events | `<…>` | `<link>` |
| `<email/SMS provider>` (if a channel is enabled) | Message delivery | Message content + recipient | `<…>` | `<link>` |
| `<vector store / object storage>` (if enabled) | RAG / attachments | Knowledge + attachment content | `<…>` | `<link>` |

## Notes
- **Self-hosted LLM** (vLLM/Ollama/TGI) or **enterprise mode** (egress lock):
  no LLM sub-processor — inference stays on the customer's infrastructure. State
  that explicitly here when it applies.
- Maverick **scrubs secrets** from logs/audit/exports before they leave the
  process (`maverick.secrets`); document this as a data-minimization control.
- Update this list and notify the customer **before** adding a sub-processor, per
  the DPA's change-notification clause.
