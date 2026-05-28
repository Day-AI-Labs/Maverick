# maverick-dashboard

Local web dashboard for Maverick. Reads `~/.maverick/world.db` and
`~/.maverick/skills/` and surfaces:

- Goals: status, plan tree, trajectory replay, cancel, answer pending
  questions inline.
- Skills: installed list plus an install form (gated behind
  `MAVERICK_ALLOW_SKILL_INSTALL=1`).
- Facts: persistent key/value memory.
- Spend: per-episode breakdown with CSV export.
- Providers / tools / channels / plugins / MCP servers: read-only views
  of what the kernel currently has wired.
- Audit log: tail and grep over `~/.maverick/audit/`.
- Halt button: arms `~/.maverick/HALT` from the header on any page.

## Design

- FastAPI + Jinja2. No React, no build step.
- Server binds to `127.0.0.1` by default.
- To bind publicly (`--host 0.0.0.0`), set `MAVERICK_DASHBOARD_TOKEN`
  and send `Authorization: Bearer <token>`. Query-token auth was
  removed in the council security pass because it leaks via Referer
  and access logs.
- Baseline browser security headers (X-Frame-Options DENY,
  X-Content-Type-Options nosniff, Referrer-Policy no-referrer,
  Cross-Origin-Opener-Policy same-origin) are applied to every response.
- WorldModel is held as a singleton per DB path so each request
  doesn't reopen SQLite + reapply migrations.

## Run

```bash
pip install -e ./packages/maverick-dashboard
maverick-dashboard          # listens on http://127.0.0.1:8765
```

Or via the core CLI:

```bash
maverick dashboard
```
