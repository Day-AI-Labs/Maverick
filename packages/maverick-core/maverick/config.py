"""Configuration loader for Maverick.

Reads ``~/.maverick/config.toml`` (or the path set by ``$MAVERICK_CONFIG``).
Supports environment variable interpolation in string values: ``${VAR_NAME}``
is replaced with the env value, or the empty string if unset.

This is the surface the installer wizard writes to. Users can also edit
the TOML by hand. The kernel falls back to sensible defaults if no
config file exists, so research / dev use doesn't require running the
wizard first.

Schema overview::

    [providers.<name>]
    api_key = "${ANTHROPIC_API_KEY}"
    base_url = "..."  # optional

    [models]
    orchestrator = "anthropic:claude-opus-4-7"
    researcher   = "anthropic:claude-sonnet-4-6"
    # ...

    [budget]
    max_dollars = 5.0

    [safety]
    profile = "balanced"
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


# Note: do NOT cache `Path.home()` at module import time. It evaluates
# eagerly against the import-time HOME env var, and stays stale if HOME
# is later patched (e.g. by pytest's monkeypatch.setenv("HOME", ...)
# for test isolation). Resolve dynamically inside config_path() instead.
DEFAULT_CONFIG_BASENAME = (".maverick", "config.toml")


def _default_config_path() -> Path:
    return Path.home() / DEFAULT_CONFIG_BASENAME[0] / DEFAULT_CONFIG_BASENAME[1]


# Back-compat: many call sites still reference the constant.
DEFAULT_CONFIG_PATH = _default_config_path()

# Accept lower/mixed-case names too: a hand-edited config referencing a
# lowercase env var (`${my_token}`) previously left the literal `${my_token}`
# in the value, silently un-substituted. The docstring promises "${VAR_NAME}
# is replaced" with no case restriction.
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _interp(value: Any) -> Any:
    """Recursively replace ``${VAR}`` with environment values."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _interp(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interp(v) for v in value]
    return value


def config_path() -> Path:
    override = os.environ.get("MAVERICK_CONFIG")
    if override:
        return Path(override).expanduser()
    # Resolve dynamically so monkeypatch.setenv("HOME", ...) takes effect
    # mid-process — the prior `return DEFAULT_CONFIG_PATH` was evaluated
    # at import time and stayed stale.
    return _default_config_path()


def load_config(path: Path | None = None) -> dict:
    p = path or config_path()
    if not p.exists():
        return {}
    try:
        with open(p, "rb") as f:
            return _interp(tomllib.load(f))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
        # The kernel must tolerate a missing config (returns {} above); a
        # corrupt/unreadable one is the adjacent case. Fail soft to defaults
        # with a warning instead of crashing the agent loop / every
        # get_role_model / get_safety caller on a hand-edited TOML typo.
        logging.getLogger(__name__).warning(
            "ignoring unreadable %s (%s: %s); using defaults",
            p, type(e).__name__, e,
        )
        return {}


def get_role_model(role: str) -> str | None:
    """Return the model spec ("provider:model-id") for a role, or None."""
    cfg = load_config()
    spec = cfg.get("models", {}).get(role)
    return spec if isinstance(spec, str) and spec else None


def get_provider_config(provider: str) -> dict:
    cfg = load_config()
    return cfg.get("providers", {}).get(provider, {})


def get_budget_overrides() -> dict:
    return load_config().get("budget", {})


def get_capabilities() -> dict:
    """Return the [capabilities] section (computer_use / browser / web_search /
    mobile_tools). These gate the optional high-impact tools in
    ``tools.base_registry``; all default off."""
    cfg = load_config().get("capabilities", {}) or {}
    return {
        "computer_use": bool(cfg.get("computer_use", False)),
        "browser": bool(cfg.get("browser", False)),
        "web_search": bool(cfg.get("web_search", False)),
        "mobile_tools": bool(cfg.get("mobile_tools", False)),
    }


def get_features() -> dict:
    """Return the [features] section. These toggle agent-facing behaviors that
    are otherwise always on:

    - ``skills``      inject distilled/installed skills into agent prompts.
                      The MAVERICK_USE_SKILLS env var, when set, overrides this.
    - ``world_model`` inject persisted world-model facts (cross-run memory)
                      into the orchestrator brief. Off = run without prior
                      stored facts; the per-run goal/event/checkpoint store
                      (world.db) still functions regardless.
    - ``streaming``   stream live progress to the terminal during `maverick
                      start`. The MAVERICK_NO_PROGRESS env var / non-TTY output
                      still suppress it.

    All default on.
    """
    cfg = load_config().get("features", {}) or {}
    return {
        "skills": bool(cfg.get("skills", True)),
        "world_model": bool(cfg.get("world_model", True)),
        "streaming": bool(cfg.get("streaming", True)),
    }


def get_safety() -> dict:
    """Return safety section with sensible defaults filled in."""
    cfg = load_config().get("safety", {})
    return {
        "profile": cfg.get("profile", "balanced"),
        "block_threshold": cfg.get("block_threshold", "high"),
        "scan_input": cfg.get("scan_input", True),
        "scan_tool_calls": cfg.get("scan_tool_calls", True),
        "scan_output": cfg.get("scan_output", True),
    }


def get_skills() -> dict:
    """Return the ``[skills]`` section with signing defaults filled in.

    ``trusted_pubkeys`` is a list of hex-encoded Ed25519 publisher keys; a
    signed skill is only accepted if its ``pubkey`` is in this list (when
    the list is non-empty). ``require_signed`` rejects unsigned skills.
    Both default off so the kernel keeps current behavior out of the box.
    """
    cfg = load_config().get("skills", {})
    pubkeys = cfg.get("trusted_pubkeys", [])
    return {
        "trusted_pubkeys": [str(k) for k in pubkeys] if isinstance(pubkeys, list) else [],
        "require_signed": bool(cfg.get("require_signed", False)),
    }


def get_sandbox() -> dict:
    cfg = load_config().get("sandbox", {})
    return {
        "backend": cfg.get("backend", "local"),
        "workdir": cfg.get("workdir", "~/maverick-workspace"),
        "timeout": cfg.get("timeout", 60),
    }


def get_self_learning() -> dict:
    """Return the ``[self_learning]`` section with defaults filled in.

    The whole feature is off by default (``enable = false``) so the kernel
    keeps current behavior out of the box. When enabled, the sub-toggles
    default ON (the operator has already accepted the trust decision):
    ``preflight`` pre-acquires catalog skills before a run; ``create_tools``
    lets the agent generate + run new tools. ``max_acquisitions`` caps how
    many capabilities a single run may auto-acquire.

    Back-compat: a config that still carries the retired ``add_mcp_servers``
    key is tolerated (it is simply ignored) — agent-driven MCP acquisition
    was removed in #392, so the knob no longer does anything.
    """
    cfg = load_config().get("self_learning", {})
    try:
        max_acq = int(cfg.get("max_acquisitions", 5))
    except (TypeError, ValueError):
        max_acq = 5
    return {
        "enable": bool(cfg.get("enable", False)),
        "preflight": bool(cfg.get("preflight", True)),
        "create_tools": bool(cfg.get("create_tools", True)),
        "max_acquisitions": max(1, max_acq),
    }


def get_durable() -> dict:
    """Return the ``[durable]`` section with defaults filled in.

    Durable execution (checkpoint/resume) is OFF by default so the kernel
    keeps current warm-restart behavior out of the box. ``keep_last`` caps how
    many checkpoints are retained per agent for rewind/history.
    """
    cfg = load_config().get("durable", {})
    try:
        keep = int(cfg.get("keep_last", 5))
    except (TypeError, ValueError):
        keep = 5
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "keep_last": max(1, keep),
    }
