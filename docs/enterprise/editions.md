# Editions

Lightwork is **proprietary, commercially licensed** software ([`../../LICENSE`](../../LICENSE)).
Production use requires a license — [contact us](https://github.com/Day-AI-Labs/Maverick).

> Editions are the **distribution** split (open-core). The commercial **pricing
> tiers** within Enterprise — Basic / Gold / Platinum — and the canonical SKU list
> live in [`../product-portfolio.md`](../product-portfolio.md).

| | **Community ("lite")** *(planned)* | **Enterprise** |
|---|---|---|
| Status | Future stripped-down edition (community on-ramp) | Available now (commercial license) |
| Agent kernel + swarm | ✓ | ✓ |
| Tools / channels / sandboxes | Subset | Full |
| **Enterprise mode** (egress lock, fail-closed consent, capability enforcement, at-rest encryption) | — | ✓ |
| SSO (OIDC) + reverse-proxy identity | — | ✓ |
| RBAC + attenuating capability tokens | — | ✓ |
| Per-user tenancy | — | ✓ |
| Tamper-evident signed audit + SIEM export | — | ✓ |
| DSAR + retention enforcement | — | ✓ |
| Regulated-deployment profile + `maverick enterprise verify` | — | ✓ |
| Compliance mapping (`compliance --strict`, SOC 2 readiness, EU AI Act helper) | — | ✓ |
| Support / SLA | Community | Commercial |

The Community edition is a deliberate, stripped-down on-ramp planned for after the
platform is built out; the governance / compliance control plane stays in the
commercial Enterprise edition and is never published under a permissive license.

See [`security-overview.md`](./security-overview.md) for how the Enterprise
controls are enforced.
