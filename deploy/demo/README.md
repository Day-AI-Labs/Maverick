# Maverick browser demo

Run Maverick as a **website** — the dashboard (web UI + REST API) in a browser
— instead of the terminal, for live and sales demos. All three options below
serve the **same** hardened image (`deploy/docker/Dockerfile`, unprivileged
uid 1000) running `maverick dashboard`; they differ only in *where* it runs and
*how* it's reached. Pick whichever fits the moment — having all three means a
fallback if one platform is down.

> The dashboard refuses to serve its admin surface off `localhost` without a
> bearer token, so every option here is **token-gated**. The demo link looks
> like `https://host/?token=<TOKEN>`; treat that link like a password.

---

## Model 1 — Local one-command (laptop demos)

Zero hosting cost, no public attack surface. Best for a live demo on your own
machine or a screen-share.

```bash
cd deploy/demo
cp demo.env.example demo.env        # put your ANTHROPIC_API_KEY in it
./run-demo.sh                       # builds, starts, prints + opens the URL
```

`run-demo.sh` generates a token (stored in `.demo-token`, git-ignored), boots
the container, waits for `/livez`, prints `http://localhost:8765/?token=…`, and
opens your browser. Stop with `docker compose -f docker-compose.yml down`
(add `-v` to wipe demo state for a clean slate).

## Model 2 — Hosted public URL (send a link)

A reachable HTTPS URL you can share with prospects. Run the same container on a
VPS and put **Caddy** in front for automatic TLS.

```bash
# on the VPS, from the repo root:
MAVERICK_DASHBOARD_TOKEN=$(openssl rand -hex 24) \
  docker compose -f deploy/demo/docker-compose.yml --env-file deploy/demo/demo.env up -d --build
# edit deploy/demo/Caddyfile (set your domain), then:
caddy run --config deploy/demo/Caddyfile
```

Share `https://demo.example.com/?token=<TOKEN>`. The dashboard still enforces
the token behind the proxy (proxied traffic is treated as non-loopback,
fail-closed).

## Model 3 — One-click cloud blueprint (managed)

Infrastructure-as-code so you (or a prospect) can spin up an isolated instance
on a managed platform. Two ready-to-use blueprints:

- **Render** — `deploy/demo/render.yaml`. In Render: *New → Blueprint*, point at
  this repo. `MAVERICK_DASHBOARD_TOKEN` is generated; set `ANTHROPIC_API_KEY`
  in the service's Environment tab. Demo link:
  `https://<service>.onrender.com/?token=<token from Environment tab>`.
- **Fly.io** — `deploy/demo/fly.toml`. From the repo root:
  ```bash
  flyctl launch --copy-config --config deploy/demo/fly.toml --no-deploy
  flyctl secrets set --config deploy/demo/fly.toml \
      ANTHROPIC_API_KEY=your-key-here MAVERICK_DASHBOARD_TOKEN=$(openssl rand -hex 24)
  flyctl deploy --config deploy/demo/fly.toml
  ```
  Demo link: `https://<app>.fly.dev/?token=<the token you set>`.

> These blueprints are templates written to each platform's documented schema;
> validate the first deploy against your account (plan names, regions, and
> port-detection can vary by platform tier).

---

## Cost & safety (read before exposing publicly)

Goals run **real** LLM calls billed to your `ANTHROPIC_API_KEY`. Every option
ships conservative guardrails you can tune via env:

| Knob | Default | Effect |
|------|---------|--------|
| `MAVERICK_BUDGET_DOLLARS` | `0.50` | Per-goal USD spend cap |
| `MAVERICK_DASHBOARD_MAX_GOALS_PER_MIN` | `3` | Per-caller goal submissions/min (then HTTP 429) |
| `MAVERICK_DASHBOARD_MAX_GOALS_GLOBAL_PER_MIN` | `10` | Global goal submissions/min |

**Sandbox note:** in this demo configuration agent-generated code runs in the
container's *local* sandbox — the container (unprivileged user, ephemeral
state) is the isolation boundary. That's fine for a controlled demo. For a
hardened, internet-exposed, or multi-tenant deployment, enable a container
sandbox backend and enterprise mode (egress lock, fail-closed consent) — see
`docs/enterprise/deployment-playbook.md` and `docs/enterprise/single-client-deployment.md`.

## Not for demos?

For production/self-host paths (CLI image, VPS+systemd, Helm, GitHub Action),
see the siblings of this directory under `deploy/` and the enterprise docs.
