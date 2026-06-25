"""Migration governance — the Alembic-grade ratchet over the world-model
migration ladders (roadmap: regulated-SaaS data-plane).

``schema_migrations.py`` lints a single ladder for online/offline safety. This
module governs the *integrity and evolution* of BOTH backend ladders together —
SQLite (``world_model.MIGRATIONS`` + ``SCHEMA_VERSION``) and Postgres
(``world_model_backends.postgres.MIGRATIONS`` + ``_PG_SCHEMA_VERSION``) — the way
Alembic governs a revision graph:

* **Immutability of released migrations.** Each version's statements are
  fingerprinted (sha256). A committed lock manifest (``migrations.lock.json``)
  pins those fingerprints. CI fails if an *already-released* version's checksum
  changes — editing a shipped migration silently diverges every DB that already
  applied the old text. Appending a NEW version is fine; it shows up as a
  reviewable lock diff (regenerate with ``--regen``).
* **Cross-backend head parity.** Both ladders must reach the same head and that
  head must equal each backend's declared ``SCHEMA_VERSION`` constant, so the
  two backends can never silently diverge in schema level.
* **Subset coherence.** The Postgres ladder folds the early SQLite versions into
  its consolidated base (v1), so every Postgres version must also exist in the
  SQLite ladder; a Postgres version with no SQLite counterpart is a drift bug.
* **Additive-only for new versions.** A version added since the lock may not
  carry a destructive statement (``DROP TABLE``/``DROP COLUMN``/``RENAME``):
  those break a rolling deploy where old replicas still read the old schema.
  Released versions are grandfathered (governed by the checksum, not re-judged).

Pure and offline (no DB). Surfaced as ``python -m maverick.migration_governance
--ci`` (CI gate) and ``--regen`` (rewrite the lock after an intentional add).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# Destructive shapes that must not appear in a NEW migration: they break a
# rolling deploy (old replicas still expect the column/table) and are
# non-additive. Grandfathered for already-released versions via the lock.
# The base-schema seed. SQLite applies its base CREATE at db creation and starts
# its MIGRATIONS dict at v2; Postgres carries the consolidated base as migration
# v1. So v1 legitimately exists in the PG ladder with no SQLite MIGRATIONS entry
# — exclude it from the cross-backend subset check (per-backend checksums still
# pin it independently).
_BASE_VERSION = 1

_DESTRUCTIVE = (
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+TABLE\s+\S+\s+RENAME\b", re.IGNORECASE),
    re.compile(r"\bRENAME\s+COLUMN\b", re.IGNORECASE),
)


def lock_path() -> Path:
    """The committed lock manifest, next to this module."""
    return Path(__file__).with_name("migrations.lock.json")


def _normalize(statement: str) -> str:
    """Whitespace-stable form of a statement so cosmetic reformatting (indent,
    trailing semicolon) does not move a checksum, but a real SQL change does."""
    return re.sub(r"\s+", " ", statement.strip().rstrip(";")).strip()


def version_checksum(statements: list[str]) -> str:
    """Stable sha256 (16 hex chars) over a version's normalized statements,
    order-significant."""
    joined = "\n".join(_normalize(s) for s in statements)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _sqlite_ladder() -> dict[int, list[str]]:
    from .world_model import MIGRATIONS
    return {int(v): list(stmts) for v, stmts in MIGRATIONS.items()}


def _postgres_ladder() -> dict[int, list[str]]:
    from .world_model_backends.postgres import MIGRATIONS
    return {int(v): list(stmts) for v, stmts in MIGRATIONS}


def _declared_heads() -> dict[str, int]:
    from .world_model import SCHEMA_VERSION
    from .world_model_backends.postgres import _PG_SCHEMA_VERSION
    return {"sqlite": int(SCHEMA_VERSION), "postgres": int(_PG_SCHEMA_VERSION)}


def ladders() -> dict[str, dict[int, list[str]]]:
    return {"sqlite": _sqlite_ladder(), "postgres": _postgres_ladder()}


def fingerprint(lads: dict[str, dict[int, list[str]]] | None = None) -> dict:
    """``{"heads": {...}, "checksums": {backend: {version: cksum}}}`` — the
    canonical, JSON-stable description of both ladders."""
    lads = lads if lads is not None else ladders()
    checksums = {
        backend: {str(v): version_checksum(stmts) for v, stmts in sorted(steps.items())}
        for backend, steps in lads.items()
    }
    heads = {backend: max(steps) if steps else 0 for backend, steps in lads.items()}
    return {"heads": heads, "checksums": checksums}


def structural_problems(lads: dict[str, dict[int, list[str]]] | None = None) -> list[str]:
    """Backend-coherence checks that don't need the lock: head parity vs the
    declared constants, cross-backend head equality, and PG ⊆ SQLite."""
    lads = lads if lads is not None else ladders()
    problems: list[str] = []
    declared = _declared_heads()
    sqlite_v = set(lads["sqlite"])
    pg_v = set(lads["postgres"])

    for backend, steps in lads.items():
        if not steps:
            problems.append(f"{backend}: migration ladder is empty")
            continue
        head = max(steps)
        if head != declared[backend]:
            problems.append(
                f"{backend}: head migration v{head} != declared SCHEMA_VERSION "
                f"{declared[backend]} (bump the constant with the migration)")

    if lads["sqlite"] and lads["postgres"] and max(sqlite_v) != max(pg_v):
        problems.append(
            f"backend head mismatch: sqlite v{max(sqlite_v)} != postgres "
            f"v{max(pg_v)} (the two backends have diverged in schema level)")

    orphan_pg = sorted(pg_v - sqlite_v - {_BASE_VERSION})
    if orphan_pg:
        problems.append(
            f"postgres versions with no sqlite counterpart: {orphan_pg} "
            "(every PG migration needs a matching SQLite ladder entry)")
    return problems


def _destructive_statements(statements: list[str]) -> list[str]:
    hits = []
    for stmt in statements:
        if any(p.search(stmt) for p in _DESTRUCTIVE):
            hits.append(_normalize(stmt)[:70])
    return hits


def lock_problems(
    lock: dict | None, lads: dict[str, dict[int, list[str]]] | None = None,
) -> list[str]:
    """Immutability + additive-only checks against the committed lock.

    A changed checksum on a version present in the lock = an edit to a released
    migration (hard fail). A version absent from the lock is *new*: allowed, but
    it must be additive (no destructive statement) and the operator must
    regenerate the lock so the add is reviewed.
    """
    lads = lads if lads is not None else ladders()
    fp = fingerprint(lads)
    if not lock:
        return ["no migrations.lock.json — run `--regen` to create the baseline"]
    locked = lock.get("checksums", {})
    problems: list[str] = []
    pending_regen = False

    for backend, current in fp["checksums"].items():
        prior = locked.get(backend, {})
        for version, cksum in current.items():
            if version in prior:
                if prior[version] != cksum:
                    problems.append(
                        f"{backend}: migration v{version} checksum changed "
                        f"({prior[version]} -> {cksum}) — a released migration was "
                        "edited; released migrations are immutable, add a new "
                        "version instead")
            else:
                pending_regen = True
                destructive = _destructive_statements(lads[backend][int(version)])
                if destructive:
                    problems.append(
                        f"{backend}: new migration v{version} has destructive "
                        f"statement(s) {destructive}; new migrations must be "
                        "additive (old replicas still read the old schema)")
        for version in prior:
            if version not in current:
                problems.append(
                    f"{backend}: migration v{version} is in the lock but gone "
                    "from the ladder — released migrations may not be removed")
    if pending_regen and not problems:
        problems.append(
            "new migration version(s) detected — run `--regen` and commit "
            "migrations.lock.json so the addition is reviewed")
    return problems


def validate() -> list[str]:
    lads = ladders()
    return structural_problems(lads) + lock_problems(load_lock(), lads)


def load_lock() -> dict | None:
    try:
        return json.loads(lock_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_lock() -> Path:
    path = lock_path()
    payload = fingerprint()
    payload["_comment"] = (
        "Committed fingerprint of the world-model migration ladders. Generated "
        "by `python -m maverick.migration_governance --regen`. Do not hand-edit; "
        "a changed checksum on a released version fails CI."
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render() -> str:
    fp = fingerprint()
    lines = [f"migration ladders: heads {fp['heads']}"]
    for backend, cks in fp["checksums"].items():
        lines.append(f"  {backend}: {len(cks)} versions, head checksum "
                     f"{cks[max(cks, key=int)] if cks else '-'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- CLI shell
    import argparse
    p = argparse.ArgumentParser(
        prog="maverick.migration_governance",
        description="Govern the world-model migration ladders (checksums, "
                    "head parity, additive-only).")
    p.add_argument("--ci", action="store_true",
                   help="exit 1 on any governance violation")
    p.add_argument("--regen", action="store_true",
                   help="rewrite migrations.lock.json from the current ladders")
    args = p.parse_args(argv)

    if args.regen:
        path = write_lock()
        print(f"wrote {path}")
        return 0

    problems = validate()
    if problems:
        print("migration governance: PROBLEMS")
        for prob in problems:
            print(f"  - {prob}")
    else:
        print("migration governance: OK")
        print(render())
    if args.ci and problems:
        return 1
    return 0


__all__ = [
    "lock_path", "version_checksum", "ladders", "fingerprint",
    "structural_problems", "lock_problems", "validate", "load_lock",
    "write_lock", "render", "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
