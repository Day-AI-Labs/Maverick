# Lightwork — Security & Compliance Overview

Lightwork is a **governed, self-hostable AI agent runtime** built to run on
private and regulated data (PHI / PCI / PII / EU / classified) without that data
leaving your boundary. This page summarizes the security architecture for
technical and security reviewers. It describes the product as built; capabilities
are cited to the modules that enforce them.

## The data-boundary guarantee (Enterprise mode)

The kernel ships fail-open and cloud-capable by design — the right default for a
personal agent, the wrong one for sensitive data. **Enterprise mode is one opt-in
switch** (`MAVERICK_ENTERPRISE=1`, `[enterprise] mode = true`, or the installer) —
or, simplest, the named **deployment profile** `MAVERICK_PROFILE=enterprise`
(`maverick/profile.py`), which composes enterprise mode *and* the
deployment-specific secure defaults below in one knob — that flips the defaults
fail-closed (`maverick/enterprise.py`):

- **Egress lock.** Every LLM call is pinned to a local / self-hosted provider
  (Ollama / vLLM / TGI, or an allow-listed endpoint). A call routed to a cloud
  provider raises `EgressBlocked` **before any prompt is sent**, and the denial is
  audited. Sensitive data physically cannot reach a third-party API.
- **Consent fail-closed.** Destructive-action consent defaults to *ask* (and
  therefore *deny* in non-interactive contexts) instead of auto-approve.
- **Capabilities enforced.** Per-agent capability scoping with attenuating
  propagation — a sub-agent can never exceed its parent's grant.
- **Encryption at rest.** The world model and cross-session memory are sealed with
  AES-256-GCM (`crypto_at_rest.py`); `maverick encryption migrate` seals
  pre-existing plaintext.
- **Container-default sandbox.** A `local`/unset sandbox backend is upgraded to an
  available container runtime (docker → podman) instead of running `shell=True` on
  the host; if no container runtime is installed it fails closed rather than
  running agent-generated commands unsandboxed (`sandbox/__init__.py`).
- **Plugin supply-chain checks.** Plugin tool calls can be proxied through the
  configured isolation backend, and plugin distributions can be checked against
  a **content-hash lockfile** when lock enforcement is enabled. Plugin discovery,
  imports, tool factories, channel plugins, skill plugins, and persona plugins
  still run in the Maverick process; install only trusted plugins, and generate a
  lockfile before relying on drift enforcement (`plugins.py`,
  `plugin_isolation.py`, `plugin_lock.py`).

**Prove it, don't trust the flag.** `maverick enterprise verify`
(`deployment.py`) *actively exercises* the load-bearing guarantees — it confirms
the egress lock refuses a cloud provider and that at-rest sealing round-trips on
the host — so a pass means the boundary holds, not merely that a config flag reads
`on`.

## Identity & access

- **SSO via OIDC.** Inbound requests are authenticated by verifying an OIDC ID
  token (`oidc.py`, PyJWT); when enabled, the channel-provided identity is never
  trusted and verification is fail-closed.
- **Reverse-proxy identity.** A trusted forwarded-identity header is supported for
  gateway deployments (`proxy_auth.py`) — an unverifiable source can't assert
  identity (fail-closed).
- **RBAC + capability tokens.** Role-based access control over capabilities, plus
  unforgeable, attenuating capability grants (`capability.py`).
- **Per-tool ACLs & consent.** Tool-level allow-lists and a consent primitive gate
  risky actions (`safety/tool_acl.py`, `safety/consent.py`).
- **Per-user tenancy.** Each principal's goals, cross-session memory, and audit
  land in an isolated, co-located per-tenant store (`tenant_scope` in
  `server.py`); single-tenant is the default and is unchanged.

## Audit & evidence

- **Tamper-evident audit log.** Append-only, Ed25519 hash-chained, with
  anti-deletion anchors; `maverick audit verify` validates the chain
  (`audit/signing.py`).
- **SIEM export.** `maverick audit export` emits date-windowed events for SIEM
  ingestion.
- **Data subject rights.** DSAR export (`dsar.py`) and data-retention enforcement
  (`audit/retention.py`, GDPR Art. 5(1)(e) storage limitation).
- **Supply chain.** A CycloneDX SBOM is produced in CI; dependencies are scanned
  (`pip-audit`). Plugin tool calls can be isolation-proxied and plugin distributions can be
  lockfile-checked under the enterprise profile, but plugin import/discovery code
  still runs in-process; treat plugins as trusted code (see the data-boundary
  guarantees above).

## Compliance posture

- **Regulated-deployment profile.** One reference profile
  (`REGULATED_PROFILE` in `deployment.py`) composes Enterprise mode + audit
  signing + retention; `maverick compliance --strict` gates on it.
- **Framework mapping.** `maverick compliance` maps configured controls to
  regulation articles; an EU AI Act risk-classification helper ships (`ai_act.py`).
- **SOC 2 readiness.** A readiness probe (`soc2.py`) checks the load-bearing
  controls (encryption-at-rest, capability enforcement, audit signing). *This is
  self-assessment tooling, not a certification* — SOC 2 Type II is in progress.

## Reference architecture (self-host / air-gap)

```
        ┌─────────────────────── your boundary ───────────────────────┐
  user →│  channel / OIDC ──→ maverick serve ──→ orchestrator + swarm  │
        │                          │                  │                │
        │                    tenant_scope        sandbox (local/       │
        │                    per-tenant world.db  docker/k8s/firecracker)│
        │                          │                  │                │
        │   self-hosted LLM ←──────┘   signed audit ──┴─→ SIEM export  │
        │   (Ollama/vLLM/TGI)          (encrypted at rest)             │
        └──────────────────────────────────────────────────────────────┘
   Egress lock: no prompt or data leaves the boundary. No telemetry.
```

Deployable on a laptop, a VPC, Kubernetes, or a disconnected/air-gapped network.
No hyperscaler dependency; Lightwork emits no telemetry of its own.

## Roadmap (not yet built)

A **managed multi-tenant SaaS** offering (the self-host per-tenant substrate —
Postgres tenancy with fail-closed RLS, per-tenant KMS/DEK, the out-of-process
control/data-plane split — ships today), external **SOC 2 Type II /
penetration-test** attestations, and a **live-IdP certification** of the built-in
SAML SSO.

OIDC SSO, **SAML SSO** (via pysaml2, off by default), and **SCIM 2.0**
provisioning + deprovisioning all ship today; SCIM deprovision force-revokes live
sessions, including pairwise-`sub` IdPs (Entra) via a login-time subject directory.

> Licensing: Lightwork is proprietary, commercially licensed software
> ([`../../LICENSE`](../../LICENSE)). Contact us for evaluation or enterprise access.
