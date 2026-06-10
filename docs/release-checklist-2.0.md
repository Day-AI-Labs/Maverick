# 2.0 stable release — checklist

**Roadmap ref:** 2028-H1 "2.0 stable release". The release itself —
version bump, tag, wheel build, publish — is a **maintainer act**; this
checklist is the gate it runs through. Every line is a real command or a
shipped artifact; nothing here is aspirational.

## Code gates (all must be green on the release commit)

- [ ] Full matrix CI green (3.10 / 3.11 / 3.12, lint, docker, postgres,
      redteam, audit, eval-smoke, language-binding jobs)
- [ ] `python -m maverick.grpc_api.contract --check` — wire compatibility
- [ ] `python -m maverick.deprecations --ci` — nothing past-due ships;
      everything slated "remove in 2.0/0.3.0" is actually removed
- [ ] Plugin compatibility matrix green (`plugin_matrix.py --ci`)
- [ ] `python -m maverick.a11y_audit --ci` — dashboard accessibility
- [ ] detect-secrets baseline audited at the release commit
- [ ] Perf SLA suite green (`perf_sla` — the published thresholds in
      [perf-sla.md](./perf-sla.md) hold on the release build)
- [ ] Release canary recorded (`maverick canary record 2.0.0 --metric …`)
      against the final RC, compared clean vs the last 0.1.x

## Migration gates (RFC 0001's story, proven not promised)

- [ ] `maverick migrate` on a real 0.1.x config produces a clean `--apply`
      (rehearsed per [migration-2.0.md](./migration-2.0.md))
- [ ] `maverick schema-plan` output reviewed; offline-class migrations
      documented in the release notes with expected duration on a large DB
- [ ] An 0.1.x → 2.0 upgrade + rollback rehearsal performed on a seeded
      workspace (snapshot → upgrade → `maverick audit verify` → rollback)
- [ ] Channel SDK v2: every in-tree adapter passes the contract suite with
      zero deprecation warnings

## Docs gates

- [ ] CHANGELOG: every breaking change paired with its migration line
- [ ] FEATURES.md and ROADMAP.md consistent ("nothing in both docs")
- [ ] Release notes name the connector re-homing list explicitly
- [ ] Localized docs: `python -m maverick.docs_i18n --check` run; stale
      translations either refreshed or marked per the i18n README contract

## Release mechanics (maintainer)

- [ ] Version bump (`0.1.x` → `2.0.0`) in every package's pyproject; the
      lockstep versions of maverick-shield/-channels/-dashboard/-installer
      bumped together
- [ ] Tag `v2.0.0`; wheel + sdist built from the tag; artifacts signed
      (sigstore keyless per `sigstore_signing.py`)
- [ ] LTS line: per [security-backports.md](./security-backports.md), the
      previous stable line's `lts/0.1` branch is cut at this moment —
      `python -m maverick.backport_tool plan` must be empty at cut time
- [ ] Announcement: release notes + the press-kit evidence rules (no claim
      FEATURES.md can't back)

## Post-release (first 30 days)

- [ ] Watch `maverick canary compare` deltas from early adopters' reports
- [ ] A 2.0.1 window held open for migration-tooling fixes specifically —
      migration bugs jump the normal queue (they block everyone behind you)
