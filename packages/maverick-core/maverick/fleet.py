"""Agent fleets -- Layer C of the enterprise control plane.

(See ``docs/enterprise/architecture.md``.) A **Fleet** is the per-employee unit
of the product: an *owner* (a human principal) plus a roster of named,
role-scoped **agents** that do ongoing work. Each agent's role drives its
capability (via ``[roles.<role>]`` RBAC) and the whole fleet runs under the
oversight control plane (``maverick.governance``).

This module is the persistent model + lifecycle (create / list / show / remove).
Binding a fleet's agents to live runs (spawn, schedule, supervise) is built on
top of this registry.

Fleets are stored as JSON at ``~/.maverick/fleets/<name>.json``, tenant-aware via
:func:`maverick.paths.data_dir`, so one tenant's fleet roster never leaks to
another.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

# Fleet + agent names become file + principal components, so constrain them to a
# safe, predictable charset (blocks path traversal and audit-id ambiguity).
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def valid_name(name: str) -> bool:
    return bool(isinstance(name, str) and _NAME_RE.match(name))


@dataclass(frozen=True)
class FleetAgent:
    """One agent in a fleet: a name + the RBAC role that scopes its capability."""

    name: str
    role: str
    description: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "role": self.role, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> FleetAgent:
        return cls(
            name=str(d.get("name", "")),
            role=str(d.get("role", "")),
            description=str(d.get("description", "") or ""),
        )


@dataclass(frozen=True)
class Fleet:
    """An owner's roster of role-scoped agents."""

    name: str
    owner: str
    agents: tuple[FleetAgent, ...] = ()
    created_at: float = field(default_factory=lambda: time.time())

    def principal_for(self, agent_name: str) -> str:
        """The audit/capability principal for one of this fleet's agents."""
        return f"agent:{self.name}.{agent_name}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "owner": self.owner,
            "agents": [a.to_dict() for a in self.agents],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Fleet:
        return cls(
            name=str(d.get("name", "")),
            owner=str(d.get("owner", "")),
            agents=tuple(FleetAgent.from_dict(a) for a in d.get("agents", []) or []),
            created_at=float(d.get("created_at", 0.0) or 0.0),
        )


def fleets_dir(*, tenant: str | None = "__active__") -> Path:
    from .paths import data_dir
    return data_dir("fleets", tenant=tenant)


def save_fleet(fleet: Fleet, *, tenant: str | None = "__active__") -> Path:
    """Persist a fleet (0600). Raises ValueError on an invalid name."""
    if not valid_name(fleet.name):
        raise ValueError(f"invalid fleet name: {fleet.name!r}")
    d = fleets_dir(tenant=tenant)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{fleet.name}.json"
    # 0600 from creation: a roster names principals + roles.
    import os as _os
    fd = _os.open(path, _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
    with _os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(fleet.to_dict(), f, indent=2, sort_keys=True)
    return path


def load_fleet(name: str, *, tenant: str | None = "__active__") -> Fleet | None:
    if not valid_name(name):
        return None
    path = fleets_dir(tenant=tenant) / f"{name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return Fleet.from_dict(data)


def list_fleets(*, tenant: str | None = "__active__") -> list[Fleet]:
    d = fleets_dir(tenant=tenant)
    if not d.exists():
        return []
    out: list[Fleet] = []
    for path in sorted(d.glob("*.json")):
        f = load_fleet(path.stem, tenant=tenant)
        if f is not None:
            out.append(f)
    return out


def remove_fleet(name: str, *, tenant: str | None = "__active__") -> bool:
    if not valid_name(name):
        return False
    path = fleets_dir(tenant=tenant) / f"{name}.json"
    try:
        path.unlink()
        return True
    except OSError:
        return False


def runs_path(name: str, *, tenant: str | None = "__active__") -> Path:
    """The per-fleet run index (``<name>.runs.json``), tenant-aware."""
    return fleets_dir(tenant=tenant) / f"{name}.runs.json"


def load_runs(name: str, *, tenant: str | None = "__active__") -> list[dict]:
    """Recent runs for a fleet (oldest first), or ``[]`` if none/unreadable."""
    if not valid_name(name):
        return []
    try:
        data = json.loads(runs_path(name, tenant=tenant).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def record_run(
    name: str, agent: str, goal_id: int, *, tenant: str | None = "__active__"
) -> None:
    """Append a ``{agent, goal_id, ts}`` entry to the fleet's run index (0600)."""
    if not valid_name(name):
        raise ValueError(f"invalid fleet name: {name!r}")
    runs = load_runs(name, tenant=tenant)
    runs.append({"agent": agent, "goal_id": goal_id, "ts": time.time()})
    d = fleets_dir(tenant=tenant)
    d.mkdir(parents=True, exist_ok=True)
    import os as _os
    path = runs_path(name, tenant=tenant)
    # 0600 from creation: the index names principals + their work.
    fd = _os.open(path, _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
    with _os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=2)


__all__ = [
    "FleetAgent",
    "Fleet",
    "valid_name",
    "fleets_dir",
    "save_fleet",
    "load_fleet",
    "list_fleets",
    "remove_fleet",
    "runs_path",
    "load_runs",
    "record_run",
]
