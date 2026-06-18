# Maverick on Postgres — scaling past single-writer SQLite

By default Maverick keeps run state in SQLite under `~/.maverick/world.db`:
simple, zero-dependency, and a **single writer**. That caps a deployment at one
replica per state volume. To run multiple replicas (HA, horizontal scale, or
many tenants on shared infra), move the world model to Postgres.

## When to switch

Switch to Postgres when **any** of these is true:

- you need more than one dashboard/serve replica;
- you want managed backups / PITR (RDS, Cloud SQL, Azure Database);
- you run many tenants and want DB-enforced isolation (row-level security).

Until then, SQLite is the right default — don't add a database you don't need.

## Configure

Point the world model at Postgres via config **or** env:

```toml
# ~/.maverick/config.toml
[world_model]
backend = "postgres"
dsn = "postgres://maverick:***@db.internal:5432/maverick"
```

```bash
# or environment (takes precedence; good for K8s secrets / Terraform)
export MAVERICK_WORLD_BACKEND=postgres
export MAVERICK_PG_DSN='postgres://maverick:***@db.internal:5432/maverick'
```

Install the extra that pulls the driver:

```bash
pip install 'maverick-agent[postgres]'   # psycopg[binary]
```

## Tenant isolation (row-level security)

For multi-tenant deployments, enable Postgres RLS so the tenant boundary is
enforced by the database, not just the app layer:

```bash
export MAVERICK_PG_RLS=1                    # force RLS on tenant-scoped tables
export MAVERICK_STRICT_TENANT_ISOLATION=1   # exclude legacy NULL-tenant rows
```

With RLS on, every connection sets the `maverick.tenant` session GUC and the
DB refuses cross-tenant reads/writes even if application code has a bug.

## Provision (managed Postgres)

Any Postgres 14+ works. Recommended baseline for a managed instance:

- **Storage**: start at 20–50 GiB with autogrow; world state is text-heavy but
  compact.
- **HA**: multi-AZ / zone-redundant for production.
- **Backups**: automated daily + point-in-time recovery (retain ≥ 7 days).
- **Connection pooling**: front with PgBouncer (transaction pooling) when you
  run many replicas — each Maverick process opens a small pool.
- **TLS**: require `sslmode=verify-full` in the DSN for networked databases.

Create the role and database:

```sql
CREATE ROLE maverick LOGIN PASSWORD '***';
CREATE DATABASE maverick OWNER maverick;
```

Maverick creates and migrates its own schema on first connect (the same
forward-only migration machinery as SQLite). No manual DDL is required.

## Backups & restore

- **Managed**: rely on the provider's automated backups + PITR (simplest).
- **Self-managed**: `pg_dump`/`pg_restore` on a schedule; test restores.
- Per-tenant export/erase (`maverick client export`, `maverick tenant delete
  --purge`) operate at the application layer and apply to either backend.

## Health

`/healthz` runs a deep check (DB writable, provider key present, runner alive)
and returns 503 when degraded — wire it to your load balancer and alerting.
