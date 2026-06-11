# Maverick 2.0 migration playbook

**Roadmap refs:** 2028-H1 "2.0 stable release" + "migration playbook".
This playbook is the operator-facing half; the changes themselves are
specified in [RFC 0001](./rfcs/0001-maverick-2.0.md) (config schema v2,
async-only channel SDK, connector re-homing, tool contract). **Cutting the
2.0 release — version bump, tag, publish — is a maintainer act** gated on
the [release checklist](./release-checklist-2.0.md); this document is what
an operator runs when that release exists.

> Honest status: the current line is 0.1.x. Every tool referenced below
> ships **today** and is dry-run-first, so the playbook is rehearsable now
> against a 0.1.x install — that rehearsal is itself one of the release
> checklist's gates.

## TL;DR for a single-box install

```bash
# 0) snapshot first (config + world DB + audit)
cp -r ~/.maverick ~/.maverick.bak-pre2.0

# 1) what will the upgrade do? (all read-only)
maverick migrate            # config findings: renames, removals, advisories
maverick config-lint        # unknown/typo'd keys with closest-match hints
maverick schema-plan        # pending world-model migrations: hot vs window

# 2) apply
pip install -U 'maverick-agent==2.*'
maverick migrate --apply    # rewrites config.toml per the v2 schema
maverick doctor             # post-upgrade health pass

# 3) verify
maverick status
maverick audit verify       # the chain must still verify after upgrade
```

## What each step covers

1. **`maverick migrate`** reads `~/.maverick/config.toml` and reports
   findings (renames, removed keys, advisories) without writing; `--apply`
   performs the rewrites. Anything it can't migrate mechanically it names
   explicitly rather than guessing.
2. **`maverick schema-plan`** classifies pending world-model schema
   statements *online* (safe while running) vs *offline* (table rewrite /
   backfill → maintenance window) and lints the migration table itself, so
   you know **before** upgrading whether to schedule downtime.
3. **`maverick config-lint`** catches the long tail the migrator doesn't
   own: typo'd sections, type mistakes, with suggestions.

## Channel adapters (SDK v2 is async-only)

Per RFC 0001 C2: sync handler shims are removed in 2.0. Third-party
adapters must implement the async seams; the deprecation warnings shipped
in 0.1.x (`deprecations.py`: `channels.str_handler`, remove_in 0.3.0)
name exactly what to change. The certification contract suite
([programs/certification.md](./programs/certification.md)) is the
compatibility test: an adapter that passes it on 0.1.x with no deprecation
warnings is 2.0-ready.

## Plugins

Manifests must declare `api_version = "2"` (v1 manifests warn today and
are removed per the sunset policy — `docs/specs/sunset-policy.md`). The
plugin compatibility matrix CI is the early-warning system; nothing else
changes for TS/gRPC plugin authors.

## Connector re-homing (C3)

The ~47-connector tail moves from always-registered to the plugin/registry
tier. After upgrade, a connector you use that didn't load is re-enabled by
listing it in config (the migrator's report names each one it detected in
your old config and the exact line to add).

## Multi-tenant / fleet installs

Same sequence, with two additions: run `maverick schema-plan` against a
**copy** of the largest tenant DB first (the offline-class migrations are
where size bites), and upgrade one canary tenant before the fleet — the
release canary tooling (`maverick canary`) records the before/after
cost-perf snapshot so the canary is judged on data.

## Rollback

`pip install 'maverick-agent==0.1.*'` + restore `~/.maverick` from the
step-0 snapshot. The world DB is forward-migrated in place — that's what
the snapshot is for; do not run a 2.0-migrated DB under 0.1.x.
