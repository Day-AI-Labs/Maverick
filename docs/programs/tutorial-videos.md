# Tutorial video seasons 2-4 — script kit

**Roadmap refs:** 2027-H1 "tutorial video season 2", 2027-H2 "video season
3", 2028-H2 "tutorial season 4". This kit is the repo-completable half:
per-episode scripts (cold open, beats, exact commands, close). **Recording,
editing, and publishing are maintainer acts** — every command below is real
and verified against the tree, so a recording session is read-through +
screen capture, not invention.

Format rules (all seasons): 4-8 minutes per episode; the terminal/dashboard
is the star, the narrator is glue; every typed command must appear in the
docs; no fabricated outputs — record against a real seeded workspace
(`deploy/reference-architectures/demo-cluster/seed_demo.py` makes one).

---

## Season 2 — the working loop (5 episodes)

**S2E1 — From zero to first goal.** Cold open: "One command, one goal."
Beats: `pip install 'maverick-agent[dev]'` → `maverick init` (wizard tour:
provider, safety profile, budget) → `maverick start "summarize this repo"`
→ `maverick monitor`. Close on the result + where it lives
(`maverick runs`).

**S2E2 — Reading the swarm.** Beats: `maverick monitor` panes, the
blackboard, `maverick status`, the dashboard at `127.0.0.1:8765` (goals
list → goal detail → live event stream), `maverick charts` for the inline
spend/throughput/latency view.

**S2E3 — Budgets that actually stop.** Beats: `[budget]` in config.toml,
a deliberately tiny `max_dollars`, watching the run pause at the synthesis
reserve, `maverick budget-tune` suggestions over recorded history.

**S2E4 — Channels: drive it from where you are.** Beats: wizard's channel
step (Slack or Discord), allowlists ("refuses all senders until you set
…"), a round trip from the channel, `maverick serve`.

**S2E5 — Skills and the validator.** Beats: `maverick skill validate` on a
scaffold from the `template_generator` tool, the SKILL.md contract, signed
skills + `[skills] require_signed`.

## Season 3 — running it for a team (5 episodes)

**S3E1 — Tenants and walls.** Beats: `maverick tenant` group, per-tenant
data dirs, the multi-tenant isolation suite as the proof
(`tests/test_multitenant_isolation.py`).

**S3E2 — The audit log you can verify.** Beats: `maverick audit verify`,
Ed25519 chaining, what tamper looks like (flip a byte in a day file on a
copy), retention via `maverick retention enforce`.

**S3E3 — Sandboxes from local to gVisor.** Beats: `[sandbox] backend =`
docker → gvisor → firecracker tour, `allow_network = false` proof
(curl fails inside), the scrub on cross-run pooling.

**S3E4 — Compliance evidence on demand.** Beats: dashboard compliance page
→ `report.md`/CSV download, `python -m maverick.ai_act_package`,
`maverick airgap check` on a deliberately leaky config.

**S3E5 — When it breaks.** Beats: `maverick failures`, `maverick doctor`,
self-healing remedies output, the killswitch (`maverick halt` /
`maverick unhalt`).

## Season 4 — the ecosystem (4 episodes)

**S4E1 — Write a tool in TypeScript.** Beats: `sdks/plugin-ts` defineTool →
`[plugins] ts =` → the tool shows up in the registry; crash-restart demo.

**S4E2 — Any language over gRPC.** Beats: `grpc_api/plugin_host.proto`,
Describe → Call with a deadline, the contract gate
(`python -m maverick.grpc_api.contract --check`).

**S4E3 — Federation, honestly.** Beats: two instances; marketplace listing
export → signed envelope → import (watch a bad signature get rejected);
channel federation with the pseudonymized ids.

**S4E4 — Benchmarks you can reproduce.** Beats: `bench_track op=record`,
the `/benchmarks` page, reproducibility manifests and a
`verify_reproduction` pass/fail.

---

## Production checklist (per episode)

- [ ] Dry-run every command against a fresh seeded workspace
- [ ] Terminal at 100×30, dashboard at 1280×800, dark theme
- [ ] Captions exported (the walkthroughs page shows the WebVTT pattern)
- [ ] Publish: YouTube + link from docs index; file names
      `maverick-s<season>e<episode>-<slug>`
