# Reference architectures

Self-hostable deployment blueprints for the governed Lightwork runtime. Every
one runs the dashboard + control plane from the published container image and
keeps state on a persistent volume; secrets come from the platform's secret
store, never the image. Pick the one that matches where you already run things.

> All four target the same container (`deploy/docker/Dockerfile` /
> `ghcr.io/day-ai-labs/maverick`), expose the dashboard on port **8765**, and
> use the auth-exempt **`/healthz`** probe. The dashboard/control plane is a
> single SQLite writer — run **one** instance until you switch
> `[world_model] backend = "postgres"` and add a `maverick worker` pool, after
> which the web tier scales horizontally.

| Platform | Manifest | State | Secrets |
|---|---|---|---|
| Kubernetes | [`kubernetes/maverick.yaml`](../deploy/reference-architectures/kubernetes/maverick.yaml) | PVC (`ReadWriteOnce`) | `Secret` → `envFrom` |
| AWS ECS (Fargate) | [`ecs/task-definition.json`](../deploy/reference-architectures/ecs/task-definition.json) | EFS volume | Secrets Manager → `secrets` |
| Fly.io | [`flyio/fly.toml`](../deploy/reference-architectures/flyio/fly.toml) | Fly volume at `/state` | `fly secrets set` |
| Railway | [`railway/railway.json`](../deploy/reference-architectures/railway/railway.json) | Railway volume at `/state` | service variables |

## Kubernetes

```bash
kubectl apply -f deploy/reference-architectures/kubernetes/maverick.yaml
kubectl -n maverick port-forward svc/maverick 8765:80
```

Namespaced, runs as non-root, readiness-gated on `/healthz`, state on a 10Gi
PVC. Put real values into the `maverick-secrets` Secret from your secret
manager (External Secrets Operator / Sealed Secrets) — the checked-in manifest
ships placeholders. Add an Ingress/Gateway for TLS termination.

## AWS ECS (Fargate)

```bash
aws ecs register-task-definition \
  --cli-input-json file://deploy/reference-architectures/ecs/task-definition.json
```

Fill in `ACCOUNT_ID`, `REGION`, the EFS `fileSystemId`, and the Secrets Manager
ARNs, then create a service behind an ALB whose target group points at
container port 8765 with health-check path `/healthz`.

## Fly.io

```bash
fly launch --copy-config --no-deploy
fly volumes create maverick_state --size 10
fly secrets set ANTHROPIC_API_KEY=... MAVERICK_DASHBOARD_TOKEN=...
fly deploy
```

`force_https` is on; `min_machines_running = 1` keeps the single writer alive.

## Railway

Create a project from the repo, add a Volume mounted at `/state`, set
`ANTHROPIC_API_KEY` and `MAVERICK_DASHBOARD_TOKEN` in the service variables, and
deploy. Railway injects `$PORT`; the start command binds the dashboard to it and
health-checks `/healthz`.

## Scaling to multi-tenant / multi-worker

These blueprints are single-node by default. To scale out, see the hosted
control-plane pieces in [`FEATURES.md`](./FEATURES.md): the Postgres world-model
backend (tenant isolation + migrations), the `QueueDispatcher` (arq) worker
pool, per-tenant KMS/egress, and the operator console. Once Postgres + queue are
configured, run the web tier (`maverick dashboard`) and a separate worker tier
(`maverick worker`) as independent, horizontally-scaled Deployments/services.
