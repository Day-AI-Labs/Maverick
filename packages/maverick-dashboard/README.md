# maverick-dashboard

Local web dashboard for Maverick. Reads `~/.maverick/world.db` and
`~/.maverick/skills/` and shows:

- **Goals** — every goal you've started, its status, and the last
  result message.
- **Skills** — every distilled or installed SKILL.md, with triggers.
- **Facts** — things Maverick has learned about you.
- **Budget** — a placeholder for run-by-run cost tracking (v0.2).

Design:

- FastAPI + Jinja2 templates + a sprinkle of htmx for the live
  refresh on the goals list. No React, no build step.
- The server binds to ``127.0.0.1`` by default so nothing is exposed
  off-host.
- To bind publicly (for example ``--host 0.0.0.0``), you **must** set
  ``MAVERICK_DASHBOARD_TOKEN`` and send ``Authorization: Bearer <token>``
  on requests.
- No write actions in v0.1 — the dashboard is read-only. Mutating
  actions (cancel a goal, remove a skill) come in v0.2 once we add
  CSRF.

## Run

```bash
pip install -e ./packages/maverick-dashboard
maverick-dashboard          # listens on http://127.0.0.1:8765
```

Or via the core CLI (after this package is installed):

```bash
maverick dashboard
```

## Theme

Dark, monospace, minimal. Inspired by Linear and GitHub's
``/{owner}/{repo}/actions`` pages. No JavaScript framework; htmx for
the one bit of interactivity (live-refreshing goals).
