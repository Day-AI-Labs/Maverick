"""Per-client customization of the core agent ROLES.

The kernel's roles (orchestrator, researcher, coder, writer, analyst, revisor,
summarizer, verifier, ...) already route to per-role models ([models] +
:func:`maverick.config.get_role_model`) and reasoning effort ([effort]). This
module adds the missing knob: a per-tenant, editable **system-prompt addendum**
appended to a role's base template at spawn (:func:`role_addendum`, read by
``maverick.agent``), plus the editing surface the dashboard drives.

Overrides live in one TOML file in the tenant workspace -- ``roles.toml``, a
table per role::

    [orchestrator]
    system_addendum = "For ACME, always open with the risk summary first."

This mirrors the per-client pack overlay (:mod:`maverick.domain_edit`): the base
template is inherited; the addendum is the only thing a client adds. It is
additive and bounded, so a role with no override behaves exactly as before.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    import tomllib  # 3.11+
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from .llm import ROLE_MODELS

# The roles a client may customize -- the kernel's known roles. Anything else
# (e.g. a domain-pack specialist whose role is its pack name) simply has no
# override and is unaffected.
ROLES: tuple[str, ...] = tuple(ROLE_MODELS.keys())

# A role addendum rides on every spawn of that role, so keep it bounded.
_MAX_ADDENDUM = 4000


def roles_file() -> Path:
    """The active tenant's role-override file. ``MAVERICK_ROLES_FILE`` wins
    (tests / custom layouts); otherwise ``<workspace>/roles.toml``."""
    override = os.environ.get("MAVERICK_ROLES_FILE")
    if override:
        return Path(override).expanduser()
    from .workspace import Workspace
    return Workspace.current().root / "roles.toml"


def _load(path: str | Path | None = None) -> dict:
    p = Path(path) if path else roles_file()
    if not p.is_file():
        return {}
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except Exception:  # a malformed file must never break a spawn
        return {}


def role_addendum(role: str) -> str:
    """The client's system-prompt addendum for ``role`` (``""`` if none).

    Read by ``maverick.agent`` at spawn and appended to the role's base system
    template -- the hook that makes a saved override actually shape behavior."""
    table = _load().get(role) or {}
    return str(table.get("system_addendum") or "")


def validate_role(role: str, patch: dict) -> list[str]:
    """Errors that block a save: an unknown role, or an over-long addendum."""
    errors: list[str] = []
    if role not in ROLES:
        errors.append(f"unknown role {role!r} (expected one of {sorted(ROLES)})")
    addendum = str(patch.get("system_addendum") or "")
    if len(addendum) > _MAX_ADDENDUM:
        errors.append(f"system_addendum too long ({len(addendum)} > {_MAX_ADDENDUM} chars)")
    return errors


def _dump(tables: dict) -> str:
    """Serialize the whole roles file. Empty addenda are dropped so the file
    only ever records real customizations."""
    lines: list[str] = []
    for role in sorted(tables):
        addendum = str((tables[role] or {}).get("system_addendum") or "")
        if not addendum:
            continue
        lines.append(f"[{role}]")
        lines.append(f"system_addendum = {json.dumps(addendum)}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n" if lines else ""


def write_role_override(role: str, patch: dict, path: str | Path | None = None) -> str:
    """Validate then persist a role's addendum. Raises ``ValueError`` on a
    validation error. An empty addendum clears the override. Returns the path."""
    errors = validate_role(role, patch)
    if errors:
        raise ValueError("; ".join(errors))
    p = Path(path) if path else roles_file()
    tables = _load(p)
    addendum = str(patch.get("system_addendum") or "").strip()
    if addendum:
        tables[role] = {"system_addendum": addendum}
    else:
        tables.pop(role, None)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_dump(tables), encoding="utf-8")
    return str(p)


def remove_role_override(role: str, path: str | Path | None = None) -> bool:
    """Drop a role's override, reverting it to the built-in template. Returns
    whether anything was removed."""
    p = Path(path) if path else roles_file()
    tables = _load(p)
    if role not in tables:
        return False
    tables.pop(role, None)
    p.write_text(_dump(tables), encoding="utf-8")
    return True


def _model_and_effort(role: str) -> tuple[str | None, str | None]:
    """The role's resolved model + reasoning effort (informational, set via
    config/wizard). Defensive: never raises into the view."""
    model = None
    try:
        from .config import get_role_model
        model = get_role_model(role) or ROLE_MODELS.get(role)
    except Exception:
        model = ROLE_MODELS.get(role)
    effort = None
    try:
        from .effort import effort_for_role
        effort = effort_for_role(role, model or "")
    except Exception:
        effort = None
    return model, effort


def resolved_role(role: str, path: str | Path | None = None) -> dict | None:
    """The merged view the editor renders: the role's resolved model/effort
    (read-only here -- set globally via config), its addendum, and provenance.
    ``None`` for an unknown role."""
    if role not in ROLES:
        return None
    addendum = str((_load(path).get(role) or {}).get("system_addendum") or "")
    model, effort = _model_and_effort(role)
    return {
        "role": role,
        "model": model,
        "effort": effort,
        "system_addendum": addendum,
        "is_override": bool(addendum),
        "errors": validate_role(role, {"system_addendum": addendum}),
    }


def list_roles(path: str | Path | None = None) -> list[dict]:
    """Roster for the editor: every role, flagged by override status."""
    tables = _load(path)
    out: list[dict] = []
    for role in ROLES:
        model, _ = _model_and_effort(role)
        out.append({
            "role": role,
            "model": model,
            "is_override": bool((tables.get(role) or {}).get("system_addendum")),
        })
    return out


__all__ = [
    "ROLES", "roles_file", "role_addendum", "validate_role",
    "write_role_override", "remove_role_override", "resolved_role", "list_roles",
]
