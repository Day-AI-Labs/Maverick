"""Adopt an evolution archive's best config into a domain pack.

Closes the loop from offline search to live behavior: ``evolve_continuous``
finds winning configs, but until now they never flowed back into the packs
the agent factory actually spawns from. ``adopt_best`` takes the archive's
best candidate, overlays the chosen keys onto a pack, and writes the result
as an OPERATOR pack (user domains dir overrides built-ins) — never editing
the source pack in place, always leaving a ``.bak`` of any pack it replaces.

Deliberately gated: this is an explicit operator action (CLI ``--adopt``
prints the diff and requires ``--yes``), not an automatic step of any loop —
a config that won offline still deserves a human glance before it changes a
department's live persona.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .archive import Archive

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover -- Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

# Keys adoption may overlay onto a pack. Capability scopes (allow_*, max_risk)
# are deliberately excluded: evolution must never widen a security envelope.
ADOPTABLE_KEYS = frozenset({"persona", "description", "models"})


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        if "\n" in escaped:
            return '"' + escaped.replace("\n", "\\n") + '"'
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


def render_pack(data: dict) -> str:
    """Serialize a domain-pack dict back to TOML.

    Covers the shapes a :class:`DomainProfile` uses (strings, lists of
    strings, numbers, and one level of string-valued tables like
    ``models``); raises on anything else rather than writing a corrupt pack.
    """
    lines: list[str] = []
    tables: list[tuple[str, dict]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    for key, table in tables:
        lines.append("")
        lines.append(f"[{key}]")
        for k, v in table.items():
            lines.append(f"{k} = {_toml_value(v)}")
    return "\n".join(lines) + "\n"


def plan_adoption(
    archive_path: str | Path, pack_path: str | Path, *,
    keys: list[str] | None = None,
) -> tuple[dict, dict[str, tuple[object, object]]]:
    """Compute the adopted pack dict + a ``{key: (old, new)}`` change map.

    Pure (no writes), so the CLI can show the diff before asking for
    confirmation and tests can assert the overlay without touching disk.
    Only :data:`ADOPTABLE_KEYS` are considered; a key absent from the best
    config is left untouched.
    """
    archive = Archive.load(archive_path)
    best = archive.best()
    if best is None:
        raise ValueError(f"archive {archive_path} has no candidates")
    with open(pack_path, "rb") as f:
        pack = tomllib.load(f)
    wanted = set(keys) if keys else set(ADOPTABLE_KEYS)
    illegal = wanted - ADOPTABLE_KEYS
    if illegal:
        raise ValueError(
            f"refusing to adopt non-adoptable key(s): {sorted(illegal)} "
            f"(capability scopes never widen via evolution)"
        )
    changes: dict[str, tuple[object, object]] = {}
    for key in sorted(wanted):
        if key not in best.config:
            continue
        new = best.config[key]
        old = pack.get(key)
        if new != old:
            changes[key] = (old, new)
            pack[key] = new
    return pack, changes


def adopt_best(
    archive_path: str | Path, pack_path: str | Path, *,
    keys: list[str] | None = None, out_dir: str | Path | None = None,
) -> Path | None:
    """Write the adopted pack into ``out_dir`` (default: alongside the pack).

    Returns the written path, or ``None`` when the best config changes
    nothing. An existing pack at the destination is backed up to ``.bak``
    first, so adoption is reversible with a rename.
    """
    pack_path = Path(pack_path)
    dest_dir = Path(out_dir) if out_dir is not None else pack_path.parent
    dest = dest_dir / pack_path.name
    # Idempotent: once an adopted pack exists at the destination, plan against
    # THAT, so re-running with an unchanged archive best is a no-op instead of
    # rewriting (and re-backing-up) the same content forever.
    base = dest if dest.exists() else pack_path
    adopted, changes = plan_adoption(archive_path, base, keys=keys)
    if not changes:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.copy2(dest, dest.with_suffix(dest.suffix + ".bak"))
    dest.write_text(render_pack(adopted), encoding="utf-8")
    return dest


__all__ = ["ADOPTABLE_KEYS", "render_pack", "plan_adoption", "adopt_best"]
