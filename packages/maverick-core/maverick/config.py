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


# Well-known credential env vars, one per hosted provider.
PROVIDER_KEY_ENV_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DEEPSEEK_API_KEY",
    "XAI_API_KEY",
)

# Self-hosted endpoints configured by env var (the mechanism each provider's
# docstring documents). Ollama has no env var: its only custom-URL surface is
# ``[providers.ollama] base_url`` in config, covered below.
PROVIDER_BASE_URL_ENV_VARS = (
    "VLLM_BASE_URL", "TGI_BASE_URL", "OPENAI_COMPATIBLE_BASE_URL",
)


def any_provider_configured() -> bool:
    """The ONE predicate for "can this install reach some LLM provider?".

    Three legitimate configuration surfaces, all honored:
      1. a well-known credential env var (hosted providers);
      2. a self-hosted base-URL env var (vLLM / TGI / OpenAI-compatible);
      3. a ``[providers.<name>]`` config table carrying a non-empty
         ``api_key`` or ``base_url`` (``${VAR}`` interpolates to "" when
         unset, so an empty interpolation does not count).

    Found by running the platform as a user: the CLI preflight, the LLM
    clients, and the dashboard each implemented a different subset, so a
    keyless self-hosted setup was accepted by one component and rejected by
    the next. Use this helper instead of growing a fourth variant.
    """
    if any(os.environ.get(v) for v in PROVIDER_KEY_ENV_VARS):
        return True
    if any(os.environ.get(v) for v in PROVIDER_BASE_URL_ENV_VARS):
        return True
    providers = load_config().get("providers") or {}
    for pcfg in providers.values():
        if not isinstance(pcfg, dict):
            continue
        if str(pcfg.get("api_key", "")).strip() or str(pcfg.get("base_url", "")).strip():
            return True
    return False


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
        # Programmatic tool calling: a sandboxed Python script that orchestrates
        # declared tool calls (also enableable via MAVERICK_CODE_EXEC).
        "code_exec": bool(cfg.get("code_exec", False)),
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
        # Operator-defined policy rules consumed by Shield.from_config().
        "constitution": cfg.get("constitution", []),
        # Agent compartments: a swarm-shared threat ledger so one agent's
        # blocked threat immunizes the rest for the run. Off by default.
        "compartments": cfg.get("compartments", False),
        # Who may clear a latched Rung-2 sector seal: "human" | "orchestrator"
        # | "both". Default human-only (safest for a security boundary).
        "compartment_unseal": cfg.get("compartment_unseal", "human"),
    }


def get_skills() -> dict:
    """Return the ``[skills]`` section with signing defaults filled in.

    ``trusted_pubkeys`` is a list of hex-encoded Ed25519 publisher keys; a
    signed skill is only accepted if its ``pubkey`` is in this list (when
    the list is non-empty). ``require_signed`` rejects unsigned skills.
    ``require_signed_catalog`` forces a verified Ed25519 signature from a
    trusted publisher for ANY catalog install, even when ``trusted_pubkeys``
    is empty (in which case the install fails for lack of a trust anchor) --
    it hardens the catalog path without flipping the global ``require_signed``
    default. The ``MAVERICK_REQUIRE_SIGNED_CATALOG`` env var overrides it.
    All default off so the kernel keeps current behavior out of the box.
    """
    cfg = load_config().get("skills", {})
    pubkeys = cfg.get("trusted_pubkeys", [])
    env_catalog = os.environ.get("MAVERICK_REQUIRE_SIGNED_CATALOG")
    require_catalog = (
        env_catalog.strip().lower() in ("1", "true", "yes", "on")
        if env_catalog is not None
        else bool(cfg.get("require_signed_catalog", False))
    )
    return {
        "trusted_pubkeys": [str(k) for k in pubkeys] if isinstance(pubkeys, list) else [],
        "require_signed": bool(cfg.get("require_signed", False)),
        "require_signed_catalog": require_catalog,
    }


def get_sandbox() -> dict:
    cfg = load_config().get("sandbox", {})
    return {
        "backend": cfg.get("backend", "local"),
        "workdir": cfg.get("workdir", "~/maverick-workspace"),
        "timeout": cfg.get("timeout", 60),
    }


def get_knowledge() -> dict:
    """Return the ``[knowledge]`` section (per-domain vector RAG).

    Off by default; the agent kernel never requires the maverick-knowledge
    package. ``embedder`` selects hosted/local/deterministic; ``store`` selects
    sqlite/pgvector. Provider details (model/base_url/dim/path) are read by
    maverick_knowledge.build_embedder / build_store.
    """
    cfg = load_config().get("knowledge", {}) or {}
    return {
        "enable": bool(cfg.get("enable", False)),
        "embedder": cfg.get("embedder", "hosted"),
        "store": cfg.get("store", "sqlite"),
        "model": cfg.get("model", "voyage-3"),
        "base_url": cfg.get("base_url", "https://api.voyageai.com/v1"),
        "dim": int(cfg.get("dim", 1024)),
        "path": cfg.get("path", ""),
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
        # Agent-proposed MCP-server acquisition is the highest-trust knob:
        # even gated behind catalog-pinning + operator consent it can start
        # a third-party subprocess, so it ships OFF independently of the
        # self-learning master switch (#422). Env override:
        # MAVERICK_ALLOW_MCP_ACQUISITION.
        "allow_mcp_acquisition": bool(cfg.get("allow_mcp_acquisition", False)),
        "max_acquisitions": max(1, max_acq),
    }


def get_autonomy() -> dict:
    """Return the ``[autonomy]`` section with defaults filled in.

    The autonomy gate (``maverick.autonomy``) is OFF by default so the kernel
    runs unchanged out of the box. When enabled, the sub-toggles default ON:
    ``escalate_verification`` runs the cross-family ensemble verifier on FINAL
    answers when the swarm disagreed (Loop 1); ``tighten_on_low_trust`` drops
    the effective risk ceiling for high-risk tools when run trust is low (Loop
    2). ``disagreement_high`` is the swarm-entropy threshold above which both
    fire; ``min_confidence`` is the verifier-confidence floor below which the
    ceiling tightens. Both are clamped to [0, 1].
    """
    cfg = load_config().get("autonomy", {})

    def _clamp01(key: str, default: float) -> float:
        try:
            v = float(cfg.get(key, default))
        except (TypeError, ValueError):
            v = default
        return max(0.0, min(1.0, v))

    return {
        "enable": bool(cfg.get("enable", False)),
        "min_confidence": _clamp01("min_confidence", 0.5),
        "disagreement_high": _clamp01("disagreement_high", 0.5),
        "escalate_verification": bool(cfg.get("escalate_verification", True)),
        "tighten_on_low_trust": bool(cfg.get("tighten_on_low_trust", True)),
    }


def get_calibration() -> dict:
    """Return the ``[calibration]`` section with defaults filled in.

    The verifier-calibration interlock (``maverick.calibration``) is OFF by
    default: ``enforce`` must be true for a failed assessment to freeze
    self-improvement (trajectory donation). ``min_samples`` is the minimum
    labeled samples before an assessment is trusted; ``min_discrimination`` is
    the floor on mean(confidence|correct) - mean(confidence|incorrect) below
    which the verifier is judged to have drifted.
    """
    cfg = load_config().get("calibration", {})

    def _int(key: str, default: int) -> int:
        try:
            return max(1, int(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    try:
        min_disc = float(cfg.get("min_discrimination", 0.15))
    except (TypeError, ValueError):
        min_disc = 0.15
    return {
        "enforce": bool(cfg.get("enforce", False)),
        "min_samples": _int("min_samples", 20),
        "min_discrimination": max(0.0, min(1.0, min_disc)),
        "collect_from_coding": bool(cfg.get("collect_from_coding", False)),
    }


def get_credit() -> dict:
    """Return the ``[credit]`` section (counterfactual swarm credit assignment).

    OFF by default: CSCA costs N+1 verifier passes per swarm. ``max_children``
    caps the swarm size it will attribute (skip larger ones); ``min_budget_
    headroom`` is the fraction of budget that must remain before it runs.
    """
    cfg = load_config().get("credit", {})
    try:
        maxc = max(2, int(cfg.get("max_children", 6)))
    except (TypeError, ValueError):
        maxc = 6
    try:
        head = float(cfg.get("min_budget_headroom", 0.4))
    except (TypeError, ValueError):
        head = 0.4
    return {
        "enable": bool(cfg.get("enable", False)),
        "max_children": maxc,
        "min_budget_headroom": max(0.0, min(1.0, head)),
    }


def get_adaptive_compute() -> dict:
    """Return the ``[adaptive_compute]`` section (SOTA: spend compute on
    uncertainty). OFF by default. ``low_uncertainty`` is the threshold below
    which fan-out width is scaled down; ``min_width`` is the floor."""
    cfg = load_config().get("adaptive_compute", {})
    try:
        low = float(cfg.get("low_uncertainty", 0.2))
    except (TypeError, ValueError):
        low = 0.2
    try:
        minw = max(1, int(cfg.get("min_width", 1)))
    except (TypeError, ValueError):
        minw = 1
    return {
        "enable": bool(cfg.get("enable", False)),
        "low_uncertainty": max(0.0, min(1.0, low)),
        "min_width": minw,
    }


def get_search() -> dict:
    """Return the ``[search]`` section (verifier-guided best-of-N generation).
    OFF by default. ``n`` is the number of candidate answers to sample."""
    cfg = load_config().get("search", {})
    try:
        n = max(1, int(cfg.get("n", 3)))
    except (TypeError, ValueError):
        n = 3
    return {"enable": bool(cfg.get("enable", False)), "n": n}


def get_skill_synthesis() -> dict:
    """Return the ``[skill_synthesis]`` section (test-time task-specific skills).
    OFF by default."""
    cfg = load_config().get("skill_synthesis", {})
    return {"enable": bool(cfg.get("enable", False))}


def get_experience() -> dict:
    """Return the ``[experience]`` section (outcome-guided orchestration).
    OFF by default."""
    cfg = load_config().get("experience", {})
    return {"enable": bool(cfg.get("enable", False))}


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
