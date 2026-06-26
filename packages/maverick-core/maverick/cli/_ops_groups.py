"""Ops-maintenance CLI groups: cache, retention, encryption, local-runtime.

Split out of cli/__init__.py. Registered by importing this module at the end of
the package __init__ so the @main.group decorators fire on package import.
"""
from __future__ import annotations

import click

from . import main


@main.group("cache")
def cache_group() -> None:
    """Inspect and clear in-process caches (file reads, repo map, embeddings)."""


@cache_group.command("stats")
def cache_stats_cmd() -> None:
    """Show cache sizes."""
    import json as _json

    from ..cache import stats
    click.echo(_json.dumps(stats(), default=str, indent=2))


@cache_group.command("purge")
@click.option(
    "--scope", "scopes", multiple=True,
    type=click.Choice(["files", "repo_map", "skill_embeddings", "all"]),
    help="Scope to purge (repeatable). Default: all.",
)
def cache_purge_cmd(scopes: tuple[str, ...]) -> None:
    """Purge cache(s)."""
    import json as _json

    from ..cache import purge
    report = purge(scopes or ("all",))
    click.echo(_json.dumps(report, default=str, indent=2))


# ----- Retention enforcement ------------------------------------------

@main.group("retention")
def retention_group() -> None:
    """Enforce ~/.maverick/config.toml [retention] rules."""


@retention_group.command("enforce")
@click.option("--dry-run", is_flag=True, help="Report what would be removed.")
@click.option("--audit-days", type=int, default=None,
              help="Override [retention].audit_days.")
@click.option("--episodes-days", type=int, default=None,
              help="Override [retention].episodes_days.")
@click.option("--events-days", type=int, default=None,
              help="Override [retention].events_days.")
@click.option("--usage-days", type=int, default=None,
              help="Override [retention].usage_days (cost-ledger buckets).")
def retention_enforce_cmd(
    dry_run: bool,
    audit_days: int | None,
    episodes_days: int | None,
    events_days: int | None,
    usage_days: int | None,
) -> None:
    """Apply retention rules to the audit log and world model."""
    import json as _json

    from ..audit.retention import enforce
    # CLI overrides take precedence if any are set; otherwise read config.
    cfg: dict | None = None
    if any(v is not None for v in (audit_days, episodes_days, events_days, usage_days)):
        cfg = {}
        if audit_days is not None:
            cfg["audit_days"] = audit_days
        if episodes_days is not None:
            cfg["episodes_days"] = episodes_days
        if events_days is not None:
            cfg["events_days"] = events_days
        if usage_days is not None:
            cfg["usage_days"] = usage_days
    report = enforce(config=cfg, dry_run=dry_run)
    click.echo(_json.dumps(report, default=str, indent=2))


@main.group("encryption")
def encryption_group() -> None:
    """At-rest encryption maintenance (see docs/encryption.md)."""


@encryption_group.command("migrate")
@click.option("--dry-run", is_flag=True,
              help="Report what would be sealed without writing.")
@click.option("--backup/--no-backup", default=False,
              help="Opt in to a pre-migration plaintext backup next to the DB.")
@click.pass_context
def encryption_migrate_cmd(ctx, dry_run: bool, backup: bool) -> None:
    """Seal existing plaintext in the world DB (turns, facts, messages, questions).

    Enabling encryption only seals NEW writes; this seals data written before it
    was on. Idempotent and safe to re-run. Requires at-rest encryption enabled.

    The reseal is in place. By default no plaintext backup is written; pass
    --backup to write a timestamped plaintext snapshot alongside the DB first
    (mode 0600), and delete that backup once you have verified the migration.
    """
    from pathlib import Path

    from ..crypto_at_rest import EncryptionUnavailable
    from ..encryption_migrate import backup_world_db, migrate_world_db
    db = Path(ctx.obj["db"])
    try:
        if not dry_run and backup and db.exists():
            # Only snapshot when there is plaintext left to seal, so idempotent
            # re-runs don't litter identical backups. The CLI owns the backup
            # (so it can echo the path); the real run below skips its own.
            if sum(migrate_world_db(db, dry_run=True).values()):
                bpath = backup_world_db(db)
                click.echo(f"backed up plaintext world DB to {bpath} "
                           "(mode 0600; delete once the migration is verified)")
        report = migrate_world_db(db, dry_run=dry_run, backup=False)
    except EncryptionUnavailable as e:
        raise click.ClickException(str(e)) from e
    verb = "would seal" if dry_run else "sealed"
    for key in sorted(report):
        click.echo(f"  {key}: {verb} {report[key]}")
    total = sum(report.values())
    click.echo(
        f"{verb} {total} value(s) total" + (" (dry run)" if dry_run else "")
    )
    # Once legacy rows are sealed, strict mode (treat an unsealed value in a
    # sealed column as tampering, instead of trusting it as plaintext) becomes
    # safe to turn on -- nudge the operator there, since nothing else does.
    if not dry_run:
        try:
            from ..crypto_at_rest import strict_at_rest
            if not strict_at_rest():
                click.echo(
                    "tip: now that legacy rows are sealed, set [encryption] "
                    "strict = true (or MAVERICK_ENCRYPT_STRICT=1) so an unsealed "
                    "value in a sealed column is treated as tampering."
                )
        except Exception:  # pragma: no cover - never fail the command on a tip
            pass


@encryption_group.command("backup-key")
@click.option("--to", "dest", required=True,
              type=click.Path(file_okay=False, dir_okay=True),
              help="Directory to copy the key material into (created 0700).")
def encryption_backup_key_cmd(dest: str) -> None:
    """Copy the at-rest key material to a directory for secure escrow.

    The key file is the ONLY way to read sealed data -- if it is lost, that data
    is unrecoverable. This copies the primary key and any rotation-keyring keys
    (each 0600) so you can store them in a secrets manager / offline vault. Keep
    the copies at least as protected as the originals; do not leave them next to
    the data they unlock.
    """
    from pathlib import Path

    from ..crypto_at_rest import EncryptionUnavailable, backup_key_material
    try:
        written = backup_key_material(Path(dest))
    except EncryptionUnavailable as e:
        raise click.ClickException(str(e)) from e
    for p in written:
        click.echo(f"  backed up {p}")
    click.echo(f"copied {len(written)} key file(s) to {dest} -- store them "
               "securely and delete any working copy you don't need.")


@encryption_group.command("rotate")
def encryption_rotate_cmd() -> None:
    """Rotate the process-wide at-rest encryption key (additive, no re-encrypt).

    Mints a new active key in the rotation keyring. New writes are sealed under
    it immediately; all prior keys are retained so existing data stays readable
    -- no flag-day re-encrypt, no data loss. Keep the previous key(s) available
    until you have re-sealed old data (e.g. `maverick encryption migrate`).
    Per-tenant envelope keys rotate via their own KMS, not this command.
    """
    from ..crypto_at_rest import EncryptionUnavailable, rotate_at_rest_key
    try:
        key_id = rotate_at_rest_key()
    except EncryptionUnavailable as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"rotated at-rest key; new active key-id = {key_id}")
    click.echo("new writes seal under it; prior keys retained for reads. Keep "
               "the old key material until old data is re-sealed.")


@main.group("local-runtime")
def local_runtime_group() -> None:
    """Plan the local model-server runtime (vLLM / TGI / llama.cpp)."""


@local_runtime_group.command("plan")
def local_runtime_plan() -> None:
    """Print the server command Maverick WOULD run -- nothing is started.

    Composes the argv (and any env toggles) from [local_runtime] in
    ~/.maverick/config.toml plus MAVERICK_LOCAL_RUNTIME_* overrides.
    """
    import shlex

    from ..local_runtime import Launcher, LocalRuntimeError
    try:
        launcher = Launcher()
        argv, env = launcher.plan()
    except LocalRuntimeError as e:
        raise click.ClickException(str(e)) from e
    if not launcher.cfg["enabled"]:
        click.echo("# local runtime is DISABLED ([local_runtime] enabled = false); dry plan only")
    for key in sorted(env):
        click.echo(f"{key}={env[key]} \\")
    click.echo(shlex.join(argv))
