# Maverick — Launch Readiness Assessment

_What actually has to be true to ship a public v0.1.3 launch, the critical path,
and a go/no-go. Companion to `LAUNCH_AUDIT.md` (the issue log) and
`LAUNCH_CHECKLIST.md` (the step list)._

## Verdict

**Code: GO** (pending #204 merge). Every launch-blocker and every High from the
audit is fixed and test-verified. **Operational: NOT YET** — three human-gated
items below are the real gate, not code.

## The true critical path (in order)

1. **Merge the hardening fixes to `main`** (#204 / `launch-hardening`, in progress
   on desktop). Until then `main` still has the killswitch-no-op, the broken
   MCP HTTP transport, the VPS-installer bug, etc.
2. **PyPI Trusted Publishers for all 6 dist names.** 🔴 Hardest-to-reverse,
   easiest-to-forget. `publish.yml` is OIDC-only (no token). Each dist needs a
   publisher configured or it silently no-publishes. Highest risk:
   - `maverick-mcp-server` — **renamed** from `maverick-mcp`; brand-new project on
     PyPI, needs its own publisher + the old name is now orphaned.
   - `maverick-installer` — docs now tell users `pip install
     'maverick-agent[installer]'`, which only resolves once this publishes.
   - `maverick-agent`, `-shield`, `-channels`, `-dashboard`.
3. **GitHub Pages source → "GitHub Actions"** (repo Settings → Pages) + create the
   `github-pages` and `pypi` environments. Without it the docs site 404s and the
   publish job can't run.
4. **Cut `v0.1.3`** → fans out to publish.yml (PyPI), release.yml (Docker +
   PyInstaller binaries + GitHub Release), desktop.yml (unsigned bundles attached).
5. **Smoke the published artifacts** (see "Pre-launch smoke" below) before
   announcing.

## What I could NOT verify here (verify before/at launch)

- **The release pipeline on a real tag.** All workflow YAML parses and the logic
  was reviewed (race fixed, desktop-attach added, Docker now installs all 6), but
  GitHub Actions was never exercised — no tag was pushed (that's yours). **Do a
  dry run on a throwaway pre-release tag (e.g. `v0.1.3-rc1`) first.**
- **CI matrix 3.10/3.11/3.12 on Linux.** Local is Python 3.13 / Windows only. The
  ~20 local test failures are all Windows-only mechanisms (POSIX chmod, symlink
  privilege, `Path.home()`, cp1252) that pass on the Ubuntu CI matrix — reasoned,
  not run. **Confirm the CI `test` job is green on `main` after the merge.**
- **A real Tauri Rust bundle** (no `cargo` here) and **code-signing** (no certs —
  bundles ship unsigned; SmartScreen/Gatekeeper will warn; that's expected).

## Pre-launch smoke (10 minutes, catches the embarrassing stuff)

```bash
# In a CLEAN venv, after PyPI publish:
pip install 'maverick-agent[installer]'      # resolves only if installer published
maverick version                              # shows 0.1.3 for all installed pkgs
maverick --help                               # all subcommands present
maverick init --fast                          # wizard writes a readable config.toml
maverick start "say hello"                    # one real run end-to-end (needs a key)
maverick halt                                 # NOW actually stops a run (was a no-op)
# Then: the one-line installers on a fresh Win + a fresh mac/Linux box.
# Then: docs site loads at the Pages URL; the Download link resolves.
```

## Security posture to OWN publicly (a security-positioned launch will be probed)

These are **deliberate, defensible** design choices — but say them out loud in the
README/SECURITY.md so a reviewer/HN commenter can't frame them as oversights:

- **Default sandbox runs model-driven shell on the host** (no fs/net isolation;
  secret env vars are scrubbed, but it's not a container). Docker/podman are
  opt-in. → Recommend docker in the wizard; surface the active backend + a warning
  when `local` in the dashboard. (Banner added in this wave.)
- **`curl|bash` / `irm|iex` installers, no checksum, default ref `main`.** Standard
  for OSS, but post-first-release default the installer ref to the **signed
  release tag** and document SHA-256 verification. (Can't default to a tag that
  doesn't exist yet — this is a v0.1.4 follow-up.)
- **Dashboard CSP allows `'unsafe-inline'`** on a page that renders agent output
  (escaped + loopback-only by default). Nonce-based CSP is the planned hardening.
- **Shield default fallback is ~20 regex rules**, not the full SDK's F1 0.988
  (now correctly qualified in the web/docs).

## Remaining audit items vs. launch-criticality

| Item | Launch-critical? | Status |
|---|---|---|
| All blockers + Highs | yes | ✅ fixed (#204) |
| Coding-mode `sandbox.exec()` routing | no — default `local` works; affects SSH/k8s coding-mode (advanced, later-quarter) | wave-3 / documented |
| Audit signed-chain re-anchoring after erase | no — only with `[audit] sign` (off by default) | wave-3 |
| Windows POSIX-mode **test** cosmetics | no — pass on Linux CI | wave-3 (green the local suite) |
| Dashboard local-sandbox warning banner | launch-protective (security narrative) | wave-3 |
| Default-install tag pinning | no — post-first-release (tag must exist) | v0.1.4 follow-up |

## Bottom line

The repo is **code-ready** once #204 lands. The launch is gated by **PyPI trusted
publishers + the Pages/environments config + cutting the tag**, and should not be
announced until the **pre-launch smoke** passes on real published artifacts. Do a
`-rc1` tag dry-run of the release pipeline first — it's the one thing that's never
been executed end-to-end.
