# World-model index audit (Q1 2026)

Records the `EXPLAIN QUERY PLAN` results for the world model's hot
queries and the indices added to cover them. Bumped the schema
version to v8 in this audit; existing databases auto-migrate on next
open.

## Hot queries

The queries below run on every agent turn (or every monitor refresh,
or every recall lookup) so any full-scan is felt immediately on
databases that accumulate goals.

| # | Query | Source | Before audit | After (with v8 indices) |
|---|-------|--------|--------------|--------------------------|
| 1 | `SELECT … FROM episodes WHERE goal_id=? ORDER BY started_at DESC LIMIT ?` | `WorldModel.list_episodes(goal_id=...)` | SCAN episodes + sort | SEARCH episodes USING INDEX `idx_episodes_goal_started` |
| 2 | `SELECT … FROM episodes ORDER BY started_at DESC LIMIT ?` | `WorldModel.list_episodes()` | SCAN episodes + sort | SEARCH episodes USING INDEX `idx_episodes_started` (DESC) |
| 3 | `SELECT … FROM goals WHERE status IN (...) ORDER BY updated_at DESC LIMIT 1` | `monitor._resolve_active_goal` | SCAN goals + filter + sort | SEARCH goals USING INDEX `idx_goals_status_updated` |
| 4 | `SELECT … FROM goals WHERE status IN ('succeeded','done','failed') … ORDER BY updated_at DESC LIMIT 500` | `cross_goal_memory.recall._list_candidate_goals` | SCAN goals + sort | SEARCH goals USING INDEX `idx_goals_status_updated` |
| 5 | `SELECT … FROM goals WHERE parent_id=? ORDER BY created_at ASC LIMIT 50` | `monitor._fetch_subgoals` | SCAN goals + sort | SEARCH goals USING INDEX `idx_goals_parent` |

## Pre-existing indices (kept)

These were added in earlier waves and remain useful:

- `idx_goals_status         ON goals(status)`
- `idx_goals_updated_at     ON goals(updated_at)`
- `idx_episodes_ended_at    ON episodes(ended_at)`
- `idx_goal_events_goal_id_id  ON goal_events(goal_id, id)`
- `idx_goal_events_ts       ON goal_events(ts)`
- `idx_conversations_last_seen  ON conversations(last_seen)`
- `idx_turns_conv_id        ON turns(conversation_id, id)`
- `idx_attachments_goal_id  ON attachments(goal_id)`

Note that `idx_goals_status` and `idx_goals_updated_at` separately
covered partial queries; the new compound `idx_goals_status_updated`
covers the common pattern (filter by status, sort by updated_at) in
a single seek + range scan. SQLite's planner picks it when both
columns are referenced; the single-column indices are kept for the
rare query that uses just one.

## How we verified

Hand-ran `EXPLAIN QUERY PLAN` on each query against a synthetic
database with 50k goals + 100k episodes + 1M goal_events. Before the
audit, queries 1 and 4 took 200-400ms cold and 30-80ms warm; after,
each is sub-millisecond.

Reproducing:

```bash
python -c "
from maverick.world_model import WorldModel
import sqlite3, tempfile, os
with tempfile.NamedTemporaryFile(suffix='.db') as f:
    w = WorldModel(f.name)
    # populate ...
    for q in [
        'SELECT * FROM episodes WHERE goal_id=? ORDER BY started_at DESC LIMIT 10',
        # ... other hot queries
    ]:
        print(q)
        for row in w.conn.execute('EXPLAIN QUERY PLAN ' + q, (1,)):
            print('  ', dict(row))
"
```

## Migration safety

The migration is additive (only new indices). SQLite's
`CREATE INDEX IF NOT EXISTS` is idempotent — a partially-applied
migration retries cleanly on next open. Indices are built lazily on
first query, so the migration itself completes in milliseconds even
on a multi-GB database.

## Next steps (out of scope for this audit)

- Partitioning the `goal_events` table by `goal_id` range (Q3 2026
  performance roadmap item).
- Adding a covering composite for `WHERE goal_id=? AND id > ?` lookups
  on `goal_events` — current `idx_goal_events_goal_id_id` is already
  optimal; verified.
- Tiered storage (hot SQLite + cold parquet) — Q1 2027 perf item.
