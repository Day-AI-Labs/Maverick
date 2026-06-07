"""Workspaces (tenants): one isolated home per business.

A :class:`Workspace` walls off everything the factory produces for a business --
its domain packs, its uploaded-document knowledge store, its world DB -- under
its own directory (``~/.maverick/tenants/<tenant>/``). One business literally
cannot read another's files.

Selecting a tenant is explicit: construct ``Workspace(tenant)`` or set
``MAVERICK_TENANT``. With no tenant, paths fall back to the legacy single-tenant
``~/.maverick/`` layout, so existing single-business installs are unchanged.

The tenant id is sanitized to a safe directory name, so a hostile id (e.g.
``"../../etc"``) can never escape the tenants root -- isolation is the whole
point, and a path-traversal would defeat it.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_SAFE = re.compile(r"[^a-z0-9_-]+")


def _sanitize_tenant(tenant: str) -> str:
    """A safe directory name for a tenant id: lowercased, every run of
    non-``[a-z0-9_-]`` folded to ``_``, leading/trailing ``._-`` stripped -- so
    no ``..`` traversal, separator, or absolute path can escape the tenants
    root. Empty/degenerate ids become ``"default"``."""
    return _SAFE.sub("_", (tenant or "").strip().lower()).strip("._-") or "default"


def _home() -> Path:
    return Path(os.environ.get("MAVERICK_HOME", "~/.maverick")).expanduser()


@dataclass(frozen=True)
class Workspace:
    """An isolated home for one business. ``tenant=None`` is the legacy
    single-tenant layout (``~/.maverick/``)."""
    tenant: str | None = None

    @classmethod
    def current(cls) -> Workspace:
        """The active workspace, from ``MAVERICK_TENANT`` (unset -> single-tenant)."""
        return cls(os.environ.get("MAVERICK_TENANT") or None)

    @property
    def root(self) -> Path:
        if not self.tenant:
            return _home()
        return _home() / "tenants" / _sanitize_tenant(self.tenant)

    @property
    def domains_dir(self) -> Path:
        """Where this business's domain packs (its sealed agents) live."""
        return self.root / "domains"

    @property
    def knowledge_path(self) -> Path:
        """This business's document knowledge store (vector DB)."""
        return self.root / "knowledge.db"

    @property
    def db_path(self) -> Path:
        """This business's world DB (run history, facts)."""
        return self.root / "world.db"

    @property
    def slug(self) -> str | None:
        """The sanitized tenant id, or None for the single-tenant default."""
        return _sanitize_tenant(self.tenant) if self.tenant else None
