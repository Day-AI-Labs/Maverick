# Operations runbook

When something is wrong, start here. Each section is one symptom with a
checked playbook.

## Endpoints

| Endpoint | Auth | What it tells you |
|---|---|---|
| `GET /livez` | none | Process is alive (TCP accepts). |
| `GET /healthz` | none | Deep checks: DB writable, LLM key present, runner alive. Returns 503 if degraded. |
| `GET /readyz` | none | Alias for `/healthz` today. |
| `GET /metrics` | bearer (when set) | Prometheus text format: goals by status, $ spent, tokens, concurrent goals. |
| `GET /api/v1/spend` | bearer | Total spend + recent episode list. |

`MAVERICK_DASHBOARD_TOKEN` gates `/api/v1/*` and `/metrics`. The four
probe endpoints (`livez`, `healthz`, `readyz`, `openapi.json`, `docs`)
are always public so monitoring works on a locked-down VPS.

## "The service is hung"

```sh
# Is it accepting connections?
curl -sS http://127.0.0.1:8765/livez
# {"status":"ok"} → process alive. Continue.
# (no response / timeout) → process dead or wedged. Jump to "process died".

# Are the deep checks green?
curl -sS http://127.0.0.1:8765/healthz | jq
# {"status":"degraded","checks":{"db":"fail: ...","llm_key":"ok",...}}
# → look at the failing check and act on its message.

# How many goals are in flight right now?
curl -sS http://127.0.0.1:8765/metrics | grep maverick_concurrent_goals
# maverick_concurrent_goals 2   ← 2/3 slots used; not maxed.
```

If `/healthz` says `db: fail: ... database is locked`, a long-running
write transaction is blocking. Restart `maverick serve` to release.

## Process died

```sh
# What does systemd say?
systemctl status maverick

# Last 200 lines:
journalctl -u maverick -n 200 --no-pager

# If crash-looping (Restart= triggered too many times), unit enters
# 'failed'. To clear:
systemctl reset-failed maverick
systemctl start maverick
```

The systemd unit (`deploy/vps/maverick.service`) sets
`StartLimitBurst=5` over `StartLimitIntervalSec=300`. After 5 crashes
in 5 minutes the unit enters `failed` rather than respawning forever
and burning API credits.

## Goals stuck in `active` after a crash

This is now handled automatically: on every `maverick serve` and
`maverick dashboard` startup, `reclaim_orphan_goals()` flips rows
from `active`/`pending` to `blocked` with result
`[process restarted mid-run]`.

If you see active goals that *should* be running, check `/metrics`:
`maverick_concurrent_goals` should be > 0. If it's 0 but rows show
`active`, the reclaim hook didn't fire — open an issue.

## API credits burning unexpectedly

```sh
# Total spend over all time:
curl -sS -H "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:8765/api/v1/spend | jq

# Per-goal breakdown (most recent first):
curl -sS -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:8765/api/v1/spend?limit=20" | jq
```

Hard cap: `~/.maverick/config.toml` → `[budget] max_dollars`.

For multi-user channels (Telegram, SMS, WhatsApp) the per-user budget
work is on the roadmap. Today the cap is per-goal; any user can drain
it. **Don't expose channel webhooks to the open internet unless you
trust everyone who can DM the bot.**

## Restoring `world.db`

`~/.maverick/world.db` is SQLite in WAL mode. A naive `cp` while the
writer is running produces a torn copy. To back up safely:

```sh
umask 077
sqlite3 "$HOME/.maverick/world.db" ".backup $HOME/maverick-backup-$(date +%Y%m%d).db"
chmod 600 "$HOME/maverick-backup-$(date +%Y%m%d).db"
```

The `sqlite3 ... ".backup ..."` dot-command uses
`sqlite3.Connection.backup()` under the hood — online +
concurrent-write-safe. If `sqlite3` isn't installed, stop the writers
and copy:

```sh
# Stop the writers first.
systemctl stop maverick
cp ~/.maverick/world.db ~/maverick-backup.db
systemctl start maverick
```

To restore: stop the writers, replace `world.db`, restart.

## Learning-state operations

The learning loops persist state under `~/.maverick/` (reflexions, dreams/,
learned-skills/, *_stats.json). Operational handles:

- **Schedule**: `maverick dream` from cron/systemd (nightly is typical). Each
  CLI run snapshots every learned store first.
- **Inspect before it acts**: `maverick dream --dry-run` reports exact
  would-be changes without writing.
- **Roll back**: `maverick dream --list-snapshots` then
  `maverick dream --rollback latest|<name>` restores all learned stores
  wholesale (including removing skills learned after the snapshot).
- **Detect regressions**: `maverick hindsight --strict` exits non-zero if the
  forgetting loops cost coverage on past goals — suitable as a CI/cron gate.
- **Audit**: every dream cycle writes a `learning_update` row to the signed
  audit log; `maverick audit verify` covers learned state like tool calls.
- **Tenant note**: with an active tenant, all learned stores live under that
  tenant's data dir — back up per tenant.

## Retention / garbage collection

Conversations + goal_events accumulate forever by default. Manual:

```sh
maverick gc --days 90 --events-days 30
```

Scheduled (systemd timer, recommended on VPS):

```ini
# /etc/systemd/system/maverick-gc.timer
[Unit]
Description=Maverick weekly garbage collection

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/maverick-gc.service
[Unit]
Description=Maverick GC
After=maverick.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/maverick gc --yes
User=maverick
```

`systemctl enable --now maverick-gc.timer`.

## Rotating API keys without downtime

```sh
# Edit the new key in:
sudo -u maverick vim ~maverick/.maverick/.env
# (chmod 600 is enforced by the installer.)

# Hot reload:
systemctl reload maverick
# If the systemd unit doesn't support reload, restart:
systemctl restart maverick
```

## Logs

Plain text by default. Set `MAVERICK_LOG_FORMAT=json` for structured
output suitable for Loki / CloudWatch / Datadog:

```sh
MAVERICK_LOG_FORMAT=json MAVERICK_LOG_LEVEL=DEBUG maverick serve
```

Every log line emitted during a goal run carries `goal_id` and
`conversation_id` (and `channel` when set), so you can grep:

```sh
journalctl -u maverick --since "1 hour ago" -o json \
  | jq 'select(.MESSAGE | fromjson? | .goal_id == 42)'
```

## Setting up `/metrics` scrape

Prometheus config:

```yaml
scrape_configs:
  - job_name: maverick
    metrics_path: /metrics
    bearer_token: <MAVERICK_DASHBOARD_TOKEN>
    static_configs:
      - targets: ["maverick.example.com:8765"]
```

Useful queries:

- `rate(maverick_goals_total{status="done"}[5m])` — completion rate
- `maverick_concurrent_goals / maverick_max_concurrent_goals` —
  saturation
- `increase(maverick_cost_dollars_total[1h])` — spend rate
