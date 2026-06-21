"""Import clients' existing automations from other platforms into Lightwork.

External automation platforms model a **trigger + ordered actions**. This
package normalizes any of them into one IR (:mod:`.ir`) via a per-platform
translator (:mod:`.base` registry), then maps the IR onto Lightwork's existing
``Template`` + trigger/schedule primitives (:mod:`.materialize`).

Two import modes, by platform capability:

* **Definition import** -- platforms that expose their automation definitions
  over an API (n8n, Make, Workato, Power Automate, UiPath): fetch + translate
  the real workflow graph. ``Importer.can_fetch_definitions`` is True.
* **Connect-and-trigger** -- platforms that do NOT expose their automation
  definitions (Zapier, Notion automations): the source automation can't be
  read, so the client's tool calls into Lightwork (inbound webhook) and/or we
  read its data; ``can_fetch_definitions`` is False and ``fetch`` explains.

Gated by ``[automation_import] enable`` / ``MAVERICK_AUTOMATION_IMPORT``.
"""
from __future__ import annotations

# Importers self-register on import. Keep this list as the platforms grow.
from . import (
    make,  # noqa: E402,F401  -- registers "make"
    n8n,  # noqa: E402,F401  -- registers "n8n"
    notion,  # noqa: E402,F401  -- registers "notion" (connect-and-trigger)
    power_automate,  # noqa: E402,F401  -- registers "power_automate"
    uipath,  # noqa: E402,F401  -- registers "uipath"
    workato,  # noqa: E402,F401  -- registers "workato"
    zapier,  # noqa: E402,F401  -- registers "zapier" (connect-and-trigger)
)
from .base import (
    Importer,
    ImporterError,
    available_sources,
    get_importer,
    register,
    translate_all,
)
from .ir import ImportedAutomation, ImportedStep, ImportedTrigger
from .materialize import MaterializeResult, materialize


def enabled() -> bool:
    """True when automation import is switched on (off by default)."""
    from ..config import env_flag
    v = env_flag("MAVERICK_AUTOMATION_IMPORT")
    if v is not None:
        return v
    try:
        from ..config import get_automation_import
        return bool(get_automation_import().get("enable", False))
    except Exception:  # pragma: no cover -- never block on config
        return False


__all__ = [
    "Importer",
    "ImporterError",
    "ImportedAutomation",
    "ImportedStep",
    "ImportedTrigger",
    "MaterializeResult",
    "available_sources",
    "enabled",
    "get_importer",
    "materialize",
    "register",
    "translate_all",
]
