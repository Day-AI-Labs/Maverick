# Service Level Agreement (template)

> **Not legal advice.** Negotiable defaults; fill in the bracketed targets with
> the customer. For a customer-self-hosted deployment, availability is the
> customer's responsibility — this SLA then covers **support & updates** only.

**Provider:** `<your entity>`  **Customer:** `<…>`  **Effective:** `<…>`

## 1. Availability (hosted deployments)
- Target uptime: `<99.9%>` monthly, measured against the `/healthz` probe.
- Exclusions: scheduled maintenance (`<window>`), customer-caused incidents,
  upstream LLM-provider outages, force majeure.
- Service credits: `<e.g. 10% < 99.9%, 25% < 99.0%>`.

## 2. Support
| Severity | Definition | Response | Target resolution |
|---|---|---|---|
| Critical | Platform down / data at risk | `<1h>` | `<4h workaround / 24h fix>` |
| High | Major feature broken, no workaround | `<4h>` | `<2 business days>` |
| Medium | Degraded / workaround exists | `<1 business day>` | `<next release>` |
| Low | Question / cosmetic | `<2 business days>` | `<best effort>` |

Channels: `<email / portal>`. Hours: `<24×7 / business hours>`.

## 3. Security & incident response
Vulnerability disclosure and breach handling per `../../../SECURITY.md`
(coordinated disclosure, severity SLAs). Breach notification per the DPA §8.

## 4. Maintenance & upgrades
- Notice: `<N business days>` for planned maintenance.
- Upgrades take a pre-migration backup automatically; online-safe migrations are
  CI-gated for rolling deploys (see the deployment playbook §9).

## 5. Backups & recovery (hosted)
- Backup cadence: `<daily>`; retention: `<30 days>`; RPO `<…>` / RTO `<…>`.
- Per-tenant restore via `maverick backup restore` (fail-closed on mismatch).

## 6. Data handling
Retention, residency, deletion, and sub-processors per the DPA and
`subprocessors.md`.
