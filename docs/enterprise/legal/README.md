# Enterprise legal & compliance pack

Fill-in templates a deployer hands to procurement/legal. **These are starting
points, not legal advice — have counsel review before signing.** The technical
controls they reference are real and verifiable (`maverick enterprise verify`,
`maverick compliance --strict`, the signed audit chain); the *attestations*
(SOC 2 Type II, penetration test) require external auditors and are out of scope
for this repo.

| File | Purpose | Who completes it |
|---|---|---|
| `dpa-template.md` | Data Processing Agreement (GDPR Art. 28) | Counsel + DPO |
| `subprocessors.md` | Sub-processor disclosure (the LLM providers etc.) | You, per deployment |
| `sla-template.md` | Service Level Agreement (uptime / support / incident) | You + the customer |

For the data-residency story (self-hosted / egress-locked deployments), see
`../../regulated-deployment.md`; for the control mapping, `../diligence.md` and
`../../compliance/soc2-controls.md`.
