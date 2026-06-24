# Information Asset Inventory

| Field | Value |
| --- | --- |
| Document ID | REG-05 |
| Owner | Security Lead / ISMS Manager |
| Approver | Management |
| Version | 0.1 |
| Status | Draft — pending management approval |
| Review cycle | Annual + on significant change |
| Frameworks | ISO 27001 A.5.9, A.5.12; ISO 42001 A.4.3; SOC 2 C1.1 |

The inventory of information assets within the ISMS/AIMS scope (ISO 27001 A.5.9),
each with an owner, a classification (A.5.12), and the controls that protect it.
This is the asset register the [risk methodology](../risk-management-methodology.md)
and [Statement of Applicability](../iso-27001/statement-of-applicability.md) refer
to. Classification scale: **Restricted** > **Confidential** > **Internal** > **Public**.

## Information assets

| Asset | Description | Classification | Owner | Store / location | Protecting controls |
| --- | --- | --- | --- | --- | --- |
| Audit log (Operating Record) | Append-only, signed, chained record of all goals/tool calls/decisions | Restricted | Security Lead | `~/.maverick/audit/*.ndjson` (`maverick/audit/`) | Ed25519 chain + anchors, WORM, sealing, tenant-scoped, RBAC auditor read-only |
| World-model DB | Facts, episodes, goals, conversations, learnings | Confidential | AI Lead | `world.db` (`maverick/world_model.py`) | At-rest AES-256-GCM, tenant/owner scoping, DSAR/erase, RLS (Postgres) |
| Secrets / API keys | Provider keys, signing keys, tokens | Restricted | Security Lead | env / `~/.maverick/keys/` (mode 0600) / KMS | Secret scrubber, detect-secrets gate, at-rest key perms, external KMS |
| Fleet memory | Cross-agent shared learning plane | Confidential | AI Lead | `maverick/fleet_memory.py` | Provenance tagging, Shield scan, scope gating, audited reads |
| Customer data processed by agents | Prompts, tool I/O, attachments, channel messages | Confidential / Restricted (PII) | Data Protection Officer | world DB / channels / vector store | PII/secret redaction, tenant isolation, DSAR/erase, retention TTL |
| Model-selection & deployment config | `config.toml` (controls, providers, governance) | Confidential | Platform Eng | `~/.maverick/config.toml` | Access control, change management (PROC-03), preflight validation |
| Learning state / snapshots | Distilled skills, insights, calibration state | Confidential | AI Lead | `maverick/dreaming.py` snapshots | Signed learning audit, snapshot+rollback, staged rollout |
| Source code | The Maverick platform itself | Internal (proprietary) | Engineering Lead | Git repo | Branch protection, CODEOWNERS, CI gates, signed commits |
| Capability / signing keys (audit, skills) | Ed25519 keys anchoring audit + skill signatures | Restricted | Security Lead | `~/.maverick/.../keys/` | Filesystem perms, rotation support, separate trust store |
| Dashboard user store | Dashboard identities + RBAC role assignments | Confidential | Security Lead | `dashboard-users.json` | OIDC/SAML, RBAC, MAVERICK_DASHBOARD_ADMINS bootstrap |
| Backups / evidence snapshots | `maverick soc2` snapshots, audit exports | Confidential | Security Lead | deployment-defined | Same handling as the source asset; access-controlled |

## Notes

- **Owners** are role placeholders — assign named individuals at management review.
- Physical/infrastructure assets (servers, storage media) are **inherited from the
  cloud provider** (ISO 27001 A.7) and evidenced via their certification, not
  inventoried here.
- Each Restricted/Confidential asset maps to one or more risks in the
  [risk register](../risk-register.md); review this inventory and the register
  together each cycle.
