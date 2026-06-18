# Single-Client Deployment — one Maverick per enterprise

**Delivery model (decided, non-negotiable): one Maverick instance per enterprise
client, always.** There is no shared, hosted, multi-tenant service. Cross-client
data mingling is therefore a *deployment* guarantee — separate instances,
separate hosts, separate storage — not something the application has to enforce
at request time.

On top of that physical isolation, every instance is **bound to exactly one
client** and stamps all state with that client id, so isolation is *provable*
and a misconfiguration can never silently write client data to a shared root.

This document is (1) the architecture + guarantee, (2) the remediation roadmap
to get fully enterprise-ready, and (3) the per-client deployment runbook.

---

## 1. The isolation guarantee

| Layer | How a single client is isolated |
|---|---|
| **Deployment** | One Maverick process/host/volume per client. Two clients never share a host. |
| **Client binding** | `[client] id` / `MAVERICK_CLIENT_ID` binds the instance. `[client] enforce = true` (auto-on under enterprise mode) makes serving **fail closed** if unbound. |
| **Tenant floor** (`maverick.client` + `maverick.paths`) | The client id is the tenant *floor*: every `data_dir()` path — world DB, audit chain + keys, cross-session memory, fleet memory — resolves under `~/.maverick/tenants/<client>/…`. There is no un-scoped global location for client data. |
| **At-rest encryption** | Per-tenant DEK wrapped by a KEK, with the client id bound into the AEAD context (`tenant_kms`), so a key cannot decrypt another scope's data. Enable with `[encryption] at_rest = true` + `per_tenant = true`. |
| **Audit** | Signed, hash-chained, per-client audit dir + signing key; `maverick doctor` shows the bound client + data root. |

**Status (this PR): the client-binding keystone is shipped** — binding, tenant
floor, dashboard routing through the client world DB, fail-closed `serve()`
guards, a `doctor` check, config + wizard. Everything below is the roadmap to
"fully deliverable."

---

## 2. Remediation roadmap

Sequenced by leverage. Each phase is independently shippable.

### Phase 0 — Client binding & no un-scoped state ✅ (this PR)
- `[client] id` + `enforce`; client id as tenant floor; dashboard world DB
  scoped to the client; fail-closed guards on the gRPC/federation servers;
  `doctor` binding check; wizard step.

### Phase 1 — Transport encryption (TLS/mTLS) ✅
- `maverick/grpc_tls.py` builds gRPC server + channel credentials from config;
  the gRPC goal API and federation servers bind TLS via `bind_port()` and the
  federation client dials `secure_channel`. `[grpc]`/`[federation]` `tls`,
  `tls_cert`, `tls_key`, `tls_client_ca` (mTLS), and client-side `tls_ca` /
  `tls_client_cert` / `tls_client_key`.
- **Fail-closed**: when the deployment is client-bound/enterprise (or
  `tls_required = true`), a server that can't build credentials refuses to
  start and the federation client refuses to dial in the clear — sensitive data
  never silently falls back to plaintext.
- Still document TLS termination for the dashboard + MCP HTTP surfaces (reverse
  proxy or native). The federation shared token never crosses plaintext now.

### Phase 2 — Trust-plane & key administration (`maverick trust` CLI) ✅
- `maverick trust status / list / show / add / rm / revoke / unrevoke / verify`
  and `maverick trust pubkey` (print this deployment's pinned key to hand to
  peers). Write-ops manage a per-client JSON overlay (`agent_trust.json`, under
  the client's data dir) that `load_registry` merges over the hand-edited
  `[agent_trust] agents` — so peers/keys are managed without editing TOML.
- `revoke` flips `revoked` (denied immediately via `is_active`); rotation is
  `add --pubkey <new>` (overlay overrides config), with `expires_at` /
  `not_before` available for zero-downtime overlap.
- Mirror in the dashboard (read-only at minimum) — remaining follow-up.

### Phase 3 — Backup / restore / failover (HA for single-node) ✅
- `maverick backup create` snapshots the **client-scoped data root** — world DB
  (via the SQLite **online backup API**, consistent under WAL), signed **audit
  chain + anchors + keys**, memory, fleet, and the managed trust registry — into
  a portable `.tgz` with an integrity manifest (client id, time, schema, per-file
  SHA-256). `maverick backup info` inspects it; `maverick backup restore`
  applies it.
- **Fail-closed restore**: refuses a backup whose client id differs from this
  deployment's (`--force` to override); extraction is path-traversal safe.
- **Warm standby**: cron `backup create`, ship the `.tgz` offsite + to a standby
  host, `backup restore` + start on failover (see runbook §3.6).

### Phase 4 — Security hardening
- **Mandatory shield**: `[safety] require_shield = true` (auto under enterprise)
  that treats a missing/erroring shield as a refusal on network-facing surfaces.
- **Disable loopback-trust** when client-bound/enterprise — always require a
  token or OIDC at the dashboard edge.
- **Secrets hygiene**: warn on world-readable `config.toml`; encourage/enforce
  `${ENV}` refs for all tokens; never literal secrets in the file.
- **BYOK**: at least one real KMS backend (AWS KMS / GCP KMS / Vault) behind the
  existing `tenant_kms.KMS` Protocol, for customer-managed keys.

### Phase 5 — Packaging & headless provisioning (VM + image)
- **Build-time gRPC stubs**: pre-generate `*_pb2.py` into the wheels so nothing
  runs `protoc` at runtime (immutable/read-only FS; SBOM/reproducibility).
- **Declarative install**: `maverick init --from-file client.toml` (and the
  installer accepting an answer file) so a VM/image bakes a fully-configured
  client non-interactively.
- Ship a hardened `systemd` unit + install script (below) and a baked image.

### Phase 6 — Compliance & data-subject operations
- **Per-client export + erasure**: one command that exports/erases the client's
  data across *every* store (world DB, audit per retention law, memory, fleet,
  vector store, caches) with `erasure_verify` coverage proof.
- Residual-plaintext: seal the live audit day-file (or require `[privacy]
  anonymous = true`) so no PII sits unsealed.
- Certification track: SOC 2 Type II, HIPAA BAA, third-party pen test (the
  control machinery exists; the attestations are organizational).

---

## 3. Per-client deployment runbook (VM / systemd)

> One VM (or image) per client. Nothing on it is shared with another client.

### 3.1 Provision

```bash
# 1. Dedicated host, dedicated user, locked-down home.
useradd -r -m -d /var/lib/maverick maverick
install -d -o maverick -g maverick -m 0700 /var/lib/maverick/.maverick

# 2. Install (per-package wheels; pre-built, no build-time network).
python3 -m pip install --no-index --find-links /opt/maverick/wheels \
  maverick-core maverick-shield maverick-channels maverick-dashboard \
  maverick-mcp maverick-knowledge agent-shield

# 3. Provision config non-interactively (Phase 5: --from-file).
maverick init --from-file /opt/maverick/<client>.toml   # roadmap
```

### 3.2 Bind the client (the critical step)

`/var/lib/maverick/.maverick/config.toml`:

```toml
[client]
id = "acme-corp"          # this deployment serves ONLY acme-corp
enforce = true            # refuse to start unbound — data can't hit the shared root

[enterprise]
mode = true               # egress lock + fail-closed consent + capabilities + (Phase 4) mandatory shield

[encryption]
at_rest = true
per_tenant = true         # DEK bound to the client id

[audit]
sign = true               # tamper-evident, per-client signed chain

# Transport encryption (Phase 1). Required automatically under client binding /
# enterprise mode — the gRPC + federation servers refuse to start in plaintext.
[grpc]
tls = true
tls_cert = "/etc/maverick/tls/server.crt"
tls_key  = "/etc/maverick/tls/server.key"
tls_client_ca = "/etc/maverick/tls/clients-ca.crt"   # optional: enables mTLS

[federation]
tls = true
tls_cert = "/etc/maverick/tls/server.crt"
tls_key  = "/etc/maverick/tls/server.key"
tls_client_ca = "/etc/maverick/tls/peers-ca.crt"     # mTLS: require peer certs
tls_ca = "/etc/maverick/tls/peers-ca.crt"            # verify peers we dial
tls_client_cert = "/etc/maverick/tls/client.crt"     # our cert when dialing
tls_client_key  = "/etc/maverick/tls/client.key"
```

### 3.3 systemd unit

`/etc/systemd/system/maverick-dashboard.service`:

```ini
[Unit]
Description=Maverick (client: acme-corp)
After=network-online.target

[Service]
User=maverick
Environment=MAVERICK_HOME=/var/lib/maverick/.maverick
Environment=MAVERICK_CLIENT_ID=acme-corp          # belt-and-suspenders: floor set in env
Environment=MAVERICK_CLIENT_ENFORCE=1
Environment=MAVERICK_DASHBOARD_TOKEN=%d/dashboard_token   # from a credential, not the file
LoadCredential=dashboard_token:/run/secrets/maverick_dashboard_token
ExecStart=/usr/local/bin/maverick dashboard --host 127.0.0.1 --port 8770
# TLS terminated by the front proxy (Phase 1 adds native TLS for gRPC/federation)
Restart=on-failure
# Hardening
ProtectSystem=strict
ReadWritePaths=/var/lib/maverick/.maverick
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 3.4 Verify the binding (gate before go-live)

```bash
sudo -u maverick MAVERICK_HOME=/var/lib/maverick/.maverick \
  MAVERICK_CLIENT_ID=acme-corp maverick doctor
```

`doctor` MUST show:

```
✓ client   (bound to 'acme-corp' — data root /var/lib/maverick/.maverick/tenants/acme-corp)
```

If it shows `✗ client  (client binding ENFORCED but no client id set …)`, the
deployment will refuse to serve — fix the binding before exposing it. The whole
data tree must live under `…/tenants/acme-corp/`; nothing for this client should
appear directly under `…/.maverick/`.

### 3.6 Backup & warm-standby failover

```bash
# Nightly consistent backup, shipped offsite + to the standby host.
sudo -u maverick MAVERICK_HOME=/var/lib/maverick/.maverick \
  MAVERICK_CLIENT_ID=acme-corp maverick backup create --out /backups/acme.tgz
aws s3 cp /backups/acme.tgz s3://acme-maverick-dr/   # or rsync to standby

# On the STANDBY (same MAVERICK_CLIENT_ID), restore + start on failover:
maverick backup info  /backups/acme.tgz              # confirm client_id = acme-corp
maverick backup restore /backups/acme.tgz            # fail-closed if client mismatches
systemctl start maverick-dashboard
```

The restore refuses a backup whose `client_id` differs from the standby's
binding — a client's data can never be restored onto another client's node.

### 3.5 Cloud marketplace image

Bake the above (Phase 5): pinned wheels, pre-generated stubs, the systemd unit,
and a first-boot hook that requires `MAVERICK_CLIENT_ID` (and rejects boot
without it). One image template → one instance per client at launch.

---

## 4. Pre-go-live checklist (per client)

- [ ] `[client] id` set and `enforce = true`; `doctor` shows the bound client.
- [ ] Data tree is entirely under `tenants/<client>/`; shared root empty of client data.
- [ ] TLS on every listener (Phase 1); no plaintext gRPC/federation.
- [ ] Tokens injected from secrets (not literal in `config.toml`); config is `0600`.
- [ ] `[encryption] at_rest + per_tenant`, `[audit] sign` on; `maverick audit verify` passes.
- [ ] Backup job runs and a restore has been tested (Phase 3).
- [ ] Trust registry populated; `doctor` not RED on an empty engaged registry.
- [ ] Shield present and (Phase 4) mandatory.
