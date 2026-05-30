"""A2A (Agent2Agent) discovery: serve a standards-shaped Agent Card.

The A2A protocol (Linux Foundation, v1.0 — crossed 150+ orgs and went to
production in 2026) lets agents discover and describe each other. The
foundational primitive is the **Agent Card**, a JSON document served at
``/.well-known/agent-card.json`` describing who the agent is and what it
can do.

This module makes Maverick *discoverable* as an A2A agent: a pure
``build_agent_card()`` (fully unit-testable, no server) plus a ``mount()``
that registers the well-known route on the FastAPI app.

Off by default: the card is an outward-facing description of a local agent,
so an operator opts in via ``MAVERICK_A2A_ENABLED=1`` or ``[a2a] enabled =
true``. When off, no route is registered.

Scope: this is the discovery half of A2A. The task-lifecycle endpoint
(``message/send`` mapping to ``run_goal``, with streaming + auth) is a
deliberate follow-up -- discovery is the correct, low-risk first increment.
"""
from __future__ import annotations

import os
from typing import Any, Optional

A2A_PROTOCOL_VERSION = "1.0"

# Default public base URL; overridable so a card served behind a reverse
# proxy advertises the right address.
_DEFAULT_BASE_URL = "http://localhost:8000"


def a2a_enabled() -> bool:
    """Opt-in gate. Off by default (outward-facing surface)."""
    env = os.environ.get("MAVERICK_A2A_ENABLED")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("a2a") or {}
        val = cfg.get("enabled", False)
    except Exception:
        return False
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


def _base_url(override: Optional[str] = None) -> str:
    url = (
        override
        or os.environ.get("MAVERICK_A2A_BASE_URL")
        or _DEFAULT_BASE_URL
    )
    return url.rstrip("/")


def _version() -> str:
    try:
        from . import __version__
        return str(__version__)
    except Exception:
        return "0"


# Coarse A2A "skills" (capability descriptors, not internal agent roles).
_SKILLS: list[dict[str, Any]] = [
    {
        "id": "execute-goal",
        "name": "Execute a long-horizon goal",
        "description": (
            "Give Maverick a goal; a swarm of specialist sub-agents plans, "
            "runs in parallel, and verifies the result -- under a hard "
            "budget cap, with every step screened by a safety layer."
        ),
        "tags": ["autonomy", "multi-agent", "long-horizon", "safety"],
    },
    {
        "id": "research",
        "name": "Research and synthesize",
        "description": "Search across sources, verify, and synthesize a cited answer.",
        "tags": ["research", "web", "synthesis"],
    },
    {
        "id": "code",
        "name": "Write and test code",
        "description": "Implement, run, and verify code changes in a sandbox.",
        "tags": ["code", "sandbox"],
    },
]


def build_agent_card(base_url: Optional[str] = None) -> dict[str, Any]:
    """Return an A2A v1.0-shaped Agent Card for this Maverick instance.

    Pure function -- no I/O beyond reading the version/base-url config -- so
    it can be unit-tested and embedded wherever needed.
    """
    url = _base_url(base_url)
    return {
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "name": "Maverick",
        "description": (
            "An open-source recursive multi-agent swarm that runs long-horizon "
            "work locally -- your models, a hard budget cap, safety baked in."
        ),
        "url": f"{url}/a2a/v1",
        "version": _version(),
        "provider": {
            "organization": "Maverick",
            "url": "https://github.com/cdayAI/Maverick",
        },
        "capabilities": {
            # Discovery-only for now; flip these on when the task endpoint ships.
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": list(_SKILLS),
    }


def mount(app: Any) -> None:
    """Register the A2A well-known Agent Card route, if enabled.

    No-op when A2A is disabled (the default), so the surface only exists
    when an operator opts in.
    """
    if not a2a_enabled():
        return

    async def _agent_card() -> dict[str, Any]:
        return build_agent_card()

    # Canonical A2A v1.0 location, plus the pre-1.0 alias some clients still probe.
    app.add_api_route("/.well-known/agent-card.json", _agent_card, methods=["GET"])
    app.add_api_route("/.well-known/agent.json", _agent_card, methods=["GET"])
