# Maverick Helm chart

Production-oriented chart for the Maverick dashboard (web UI + API + webhooks).

```bash
# Minimal install (SQLite, single replica). Provide a provider key + token.
helm install maverick ./deploy/helm/maverick \
  --set image.tag=0.1.6 \
  --set-string secret.data.ANTHROPIC_API_KEY=sk-ant-... \
  --set-string secret.data.MAVERICK_DASHBOARD_TOKEN=$(openssl rand -hex 32)
```

The image runs as the unprivileged `maverick` user (uid/gid 1000); the chart
sets a restricted-PSS `securityContext` and an `fsGroup` so the state PVC is
writable.

## Scaling past one replica

The default world-model backend is **SQLite on a ReadWriteOnce volume** — a
single writer. The chart **refuses to render `replicaCount > 1`** unless you
move to Postgres:

```bash
helm install maverick ./deploy/helm/maverick \
  --set worldModel.backend=postgres \
  --set worldModel.postgres.rls=true \
  --set replicaCount=3 \
  --set-string secret.data.MAVERICK_PG_DSN=postgres://user:pass@host:5432/maverick \
  --set-string secret.data.ANTHROPIC_API_KEY=sk-ant-...
```

See [`deploy/postgres/README.md`](../postgres/README.md) for provisioning the
database, row-level-security, pooling, and backups.

## Values

See [`maverick/values.yaml`](maverick/values.yaml) for the full list. Common
overrides: `image.*`, `persistence.size`, `resources`, `ingress.*`,
`env` (plain), `secret.data` (sensitive), `worldModel.backend`.

## Validate before applying

```bash
helm lint ./deploy/helm/maverick
helm template maverick ./deploy/helm/maverick | kubectl apply --dry-run=client -f -
```
