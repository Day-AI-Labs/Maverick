# Maverick v0.1.3 Launch Checklist

_Human-only steps left after the automated hardening pass. Order matters._

## 🔴 TRUE BLOCKERS — do these or the launch breaks

1. **Configure PyPI Trusted Publishers for ALL 6 dist names** before pushing the
   tag. `publish.yml` uses OIDC trusted publishing (no tokens). Any dist without
   a configured publisher fails only its own job (good — `fail-fast: false` +
   `skip-existing`), but it simply won't publish. Pay special attention to the
   **two that changed**:
   - `maverick-mcp-server` (renamed from `maverick-mcp` — needs a NEW publisher;
     the old `maverick-mcp` project on PyPI is now orphaned)
   - `maverick-installer` (the docs/`[installer]` extra now resolve from PyPI;
     it must actually publish or `pipx install 'maverick-agent[installer]'`
     breaks for users)
   - plus `maverick-agent`, `maverick-shield`, `maverick-channels`,
     `maverick-dashboard`.
   Set up at https://pypi.org/manage/account/publishing/ (workflow `publish.yml`,
   environment `pypi`).

2. **Merge the fix branches** (see "PRs to open" below). At minimum the 3
   launch-blocker branches + `fix/dep-metadata` must land before the tag, or the
   tag ships the known-broken code:
   - `fix/vps-installer-blocker`, `fix/killswitch-runtime`,
     `fix/mcp-http-transport`, `fix/dep-metadata`.

## 🟠 Decisions / config (not code)

3. **GitHub Pages source = "GitHub Actions"** (repo Settings → Pages). `docs.yml`
   deploys via `actions/deploy-pages`; it needs the Pages source set to Actions
   and the `github-pages` environment to exist. Until then the docs site 404s.

4. **Code-signing certs (deferred — unsigned is OK to launch).** The desktop
   Tauri bundles build **unsigned**; they run but trip SmartScreen (Windows) /
   Gatekeeper (macOS). Plugging in Apple Developer + Azure Trusted Signing certs
   is a later milestone — the secret placeholders are in `desktop.yml`. Not a
   launch blocker; just set expectations.

5. **Verify the Tauri Rust bundle on a machine/CI WITH cargo.** Could not be
   built here (no Rust toolchain). The frontend half is verified; run
   `pnpm tauri icon src-tauri/icons/icon.png && pnpm tauri build` (or trigger
   `desktop.yml` via `workflow_dispatch`) once before relying on the installers.

## 🟢 The tag (your step — I did NOT cut it)

6. After 1–2 land and trusted publishers are set:
   ```bash
   git tag v0.1.3 && git push origin v0.1.3
   ```
   This fans out to `publish.yml` (PyPI ×6), `release.yml` (Docker + PyInstaller
   binaries + GitHub Release with notes), and now `desktop.yml` (unsigned bundles
   attached to the same Release). Watch that `release.yml`'s `release` job is the
   sole Release creator and `publish.yml`'s `sign` job + `desktop.yml` only
   *upload assets* (the race fix). NOTE: `release.yml`'s `release` job requires
   **all** PyInstaller matrix legs to succeed (`needs.binaries.result=='success'`)
   — if one OS fails, no Release is created. Re-run or relax if needed.

## Opening the PRs (gh is NOT authenticated in this session)

I committed 14 verified fix branches + 1 docs branch locally but **could not push
or open PRs** (no `gh` auth, and I won't risk a hanging credential prompt). To
publish them:

```bash
gh auth login                      # once
for b in fix/vps-installer-blocker fix/killswitch-runtime fix/mcp-http-transport \
         fix/dep-metadata fix/compute-sympy fix/cli-command-collisions \
         fix/provider-pricing fix/gdpr-erase fix/dashboard-cost-utc \
         fix/desktop-typecheck fix/docs-accuracy fix/release-pipeline \
         fix/channel-authz fix/wizard-allowlist fix/config-home-isolation \
         chore/launch-audit-docs; do
  git push -u origin "$b"
  gh pr create --draft --base main --head "$b" --fill   # title/body from the commit
done
```

All commit titles are Conventional-Commits with a letter-leading subject
(passes `lint-pr-title`). Each commit body states exactly what was run and the
result. **Do not merge without your own review** — especially the release-pipeline
YAML (could not be exercised against real GitHub Actions here).

## Recommended follow-ups before/right-after launch (see LAUNCH_AUDIT.md §Remaining)

- [HIGH] Channel per-sender allowlists (slack/signal/matrix/voice) + wizard
  collecting `*_ALLOWED_USER_IDS`.
- [DECISION] Route coding-mode git through `sandbox.exec()` (breaks for remote
  sandboxes today).
- [MED] Wire or delete `preflight()`; fix `best_of_n` budget rollup; make
  `load_config` fail-soft on corrupt TOML; Windows test isolation + a
  `windows-latest` CI leg; install sympy in CI so the `[math]` path is tested.
- [MED] Default the install scripts to a signed tag (not `main`); document the
  host-exec posture of the default sandbox.

## Verified-good (no action needed)

Tests 2036 passing / 0 flakes / async runs for real; dashboard auth
(constant-time, fail-closed, no `?token=`); Shield fail-open chokepoint on tool
call + output; audit hash-chain tamper-evident; tomllib 3.10 fallback correct;
secrets in `0600` `.env`; all 6 packages build + `twine check` clean + import
clean (dependency under-declaration disproven); 6 distinct wheel names, no
publish-matrix collision.
