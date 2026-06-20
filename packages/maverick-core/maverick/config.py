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


def __getattr__(name: str):
    # Back-compat: `DEFAULT_CONFIG_PATH` used to be a module-level constant, but
    # caching it bound Path.home() at import time (stale under HOME changes /
    # monkeypatch — exactly what the comment above warns against). Resolve it
    # lazily on attribute access so every read reflects the current HOME.
    if name == "DEFAULT_CONFIG_PATH":
        return _default_config_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


CONFIG_OVERLAY_ENV = "MAVERICK_CONFIG_OVERLAY"

# Dashboard Settings overlay for config-read settings (provider keys,
# capability/feature toggles). Deep-merged over config.toml on every
# load_config() — always-on at a fixed path next to config.toml — so UI edits
# take effect on the next read without rewriting the user's config.toml. The
# dashboard owns this file (maverick_dashboard.settings_store). Distinct from
# runtime-overrides.toml (denied_tools / models / budget, read via own hooks).
DASHBOARD_OVERRIDES_BASENAME = "dashboard-config.toml"

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


# Parsed-TOML cache keyed by absolute path -> (mtime_ns, size, raw_dict). Only
# the expensive part (file read + TOML parse) is memoized; env-var interpolation
# and the overlay deep-merge still run on every load_config() call, so a changed
# ${VAR} or edited overlay is always reflected. Invalidated when the file's mtime
# OR size changes (a rewrite). load_config() is on many hot paths (a single
# inbound A2A delegate triggers ~6-10 full parses); this removes the redundant
# I/O + tokenize while preserving exact semantics.
_toml_cache: dict[str, tuple[int, int, dict]] = {}
# Bound the cache so a deployment with many per-tenant config paths
# (~/.maverick/tenants/<t>/config.toml) can't grow it without limit. Entries
# are cheap to rebuild (a stat + parse), so a simple oldest-first cap is enough.
_TOML_CACHE_MAX = 512


def reset_config_cache() -> None:
    """Drop the parsed-TOML cache (test hook; prod files rarely change)."""
    _toml_cache.clear()


def _read_toml_raw(path: Path) -> dict:
    """Parsed TOML for ``path`` (NO interpolation), memoized by mtime+size.
    Returns ``{}`` for a missing file, and ``{}`` + a warning for a corrupt one."""
    try:
        st = path.stat()
    except OSError:
        return {}  # missing/inaccessible -> defaults (no warning, like before)
    key = str(path)
    cached = _toml_cache.get(key)
    if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return cached[2]
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
        # The kernel must tolerate a missing config (returns {} above); a
        # corrupt/unreadable one is the adjacent case. Fail soft to defaults
        # with a warning instead of crashing the agent loop / every
        # get_role_model / get_safety caller on a hand-edited TOML typo.
        logging.getLogger(__name__).warning(
            "ignoring unreadable %s (%s: %s); using defaults",
            path, type(e).__name__, e,
        )
        raw = {}
    # Evict oldest entries first when over the cap (dicts preserve insertion
    # order). Re-fetching ``key`` below keeps the just-read path resident.
    while len(_toml_cache) >= _TOML_CACHE_MAX:
        _toml_cache.pop(next(iter(_toml_cache)), None)
    _toml_cache[key] = (st.st_mtime_ns, st.st_size, raw)
    return raw


def _load_config_file(path: Path) -> dict:
    # _interp returns a fresh dict tree on every call, so the cached raw dict is
    # never mutated by callers; env substitution stays live.
    return _interp(_read_toml_raw(path))


def _deep_merge_config(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def dashboard_overrides_path() -> Path:
    """Path to the dashboard-owned config overlay (next to config.toml)."""
    return config_path().parent / DASHBOARD_OVERRIDES_BASENAME


def tenant_config_path() -> Path | None:
    """Path to the active tenant's config overlay, or None in single-tenant mode.

    Resolves to ``~/.maverick/tenants/<tenant>/config.toml`` when a tenant is
    active via an explicit ``set_tenant`` scope or the ``MAVERICK_TENANT`` env
    var, and None otherwise. Deliberately config-free: it reads only the tenant
    ContextVar and env var, NOT ``current_tenant_id()`` (whose client-binding
    branch reads config and would recurse back into ``load_config`` on every
    call -- a hot-path blow-up). A client-bound single deployment already loads
    its own ``config.toml``, so it needs no separate per-tenant overlay.
    """
    try:
        from .paths import _TENANT, _tenant_segment, maverick_home
        tid = _TENANT.get() or os.environ.get("MAVERICK_TENANT", "").strip() or None
        if not tid:
            return None
        return maverick_home() / "tenants" / _tenant_segment(tid) / "config.toml"
    except Exception:  # pragma: no cover -- config resolution never blocks a run
        return None


_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def env_flag(name: str) -> bool | None:
    """Parse an env var as a tri-state boolean: ``True``/``False`` for a
    recognized truthy/falsy value, ``None`` when unset or unrecognized. Lets the
    module ``enabled()`` gates share one parser instead of re-spelling the
    ``{"1","true","yes","on"}`` literal set (and its inverse) each time.

    Positive-only callers use ``if env_flag(name): ...``; tri-state callers use
    ``v = env_flag(name); if v is not None: return v``."""
    raw = os.environ.get(name, "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return None


def load_config(path: Path | None = None) -> dict:
    if path is not None:
        return _load_config_file(path)

    cfg = _load_config_file(config_path())
    # Dashboard Settings overlay (always-on, fixed path): UI-edited provider
    # keys / capability+feature toggles merge over config.toml without touching it.
    dash = dashboard_overrides_path()
    if dash.exists():
        cfg = _deep_merge_config(cfg, _load_config_file(dash))
    overlay = os.environ.get(CONFIG_OVERLAY_ENV)
    if overlay:
        cfg = _deep_merge_config(cfg, _load_config_file(Path(overlay).expanduser()))
    # Per-tenant overlay (highest precedence): when a tenant is active, its own
    # config.toml wins, so each client supplies its own provider API keys, model
    # choices and budget without sharing one global credential set. Skipped in
    # single-tenant mode, so the legacy path is byte-for-byte unchanged.
    tcfg = tenant_config_path()
    if tcfg is not None and tcfg.exists():
        cfg = _deep_merge_config(cfg, _load_config_file(tcfg))
    return cfg


def get_role_model(role: str) -> str | None:
    """Return the model spec ("provider:model-id") for a role, or None.

    A per-tenant override (the dashboard roles editor, persisted to roles.toml)
    wins over the global [models] config; absent one, the config value is used."""
    try:
        from .role_edit import override_model
        ov = override_model(role)
        if ov:
            return ov
    except Exception:  # role layer is optional; never block model resolution
        pass
    cfg = load_config()
    spec = cfg.get("models", {}).get(role)
    return spec if isinstance(spec, str) and spec else None


def get_provider_config(provider: str) -> dict:
    cfg = load_config()
    return cfg.get("providers", {}).get(provider, {})


# Well-known credential env vars, one per hosted provider.
# Canonical provider -> credential env var(s) map. Single source of truth for
# both "which env var holds a provider's key" (llm._provider_api_key) and the
# flat "is any provider configured?" check below. Aliases (GROK/GOOGLE) included.
PROVIDER_KEY_ENV_MAP: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "moonshot": ("MOONSHOT_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "xai": ("XAI_API_KEY", "GROK_API_KEY"),
}

PROVIDER_KEY_ENV_VARS = tuple(
    dict.fromkeys(v for vs in PROVIDER_KEY_ENV_MAP.values() for v in vs)
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
    mobile_tools / ros). These gate the optional high-impact tools in
    ``tools.base_registry``; all default off."""
    cfg = load_config().get("capabilities", {}) or {}
    return {
        "computer_use": bool(cfg.get("computer_use", False)),
        "browser": bool(cfg.get("browser", False)),
        "web_search": bool(cfg.get("web_search", False)),
        "mobile_tools": bool(cfg.get("mobile_tools", False)),
        "ros": bool(cfg.get("ros", False)),
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
    - ``pack_editing`` allow editing/overriding domain packs (agents) from the
                      dashboard editor. Off = the editor is read-only and the
                      mutating REST endpoints return 403, so an operator can
                      lock the agent roster in a governed deployment. Writing
                      override TOML on the host is unaffected.
    - ``role_editing`` allow editing the core agent roles (orchestrator, coder,
                      ...) from the dashboard -- a per-tenant system-prompt
                      addendum plus model/effort overrides per role (which win
                      over the global [models]/[effort] config). Off = the roles
                      editor is read-only and its mutating endpoints 403.
    - ``scheduling`` allow arming recurring schedules (cron) from the dashboard
                      workflow builder -- each fire enqueues a ``start_goal`` job
                      run by ``maverick worker``. Off = the schedule endpoints
                      return 403 and the UI hides; the ``maverick schedule`` CLI
                      on the host is unaffected.
    - ``triggers`` allow binding a saved template to an inbound webhook (POST
                      /webhook/run) so an external event runs it as a goal. The
                      inbound route is HMAC-signed exactly like /webhook/start
                      and fails closed without a [webhooks] secret. Off = the
                      /api/v1/triggers editor and the /webhook/run route 404/403
                      and the builder panel hides.

    All default on.
    """
    cfg = load_config().get("features", {}) or {}
    return {
        "skills": bool(cfg.get("skills", True)),
        "world_model": bool(cfg.get("world_model", True)),
        "streaming": bool(cfg.get("streaming", True)),
        "pack_editing": bool(cfg.get("pack_editing", True)),
        "role_editing": bool(cfg.get("role_editing", True)),
        "scheduling": bool(cfg.get("scheduling", True)),
        "triggers": bool(cfg.get("triggers", True)),
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
        # Recall the shipped first-party skills library at runtime (opt-out).
        "builtin": bool(cfg.get("builtin", True)),
        # Relevance GATES on skill recall. Precision >> recall for agent memory:
        # weakly-relevant retrieved context regresses the agent (hard negatives
        # flip answers -- GSM-DC/GSM-IC; large/noisy memory degrades -- Lifelong-
        # AgentBench). The embedding path keeps a skill only above this cosine;
        # the lexical fallback keeps one only at/above this RAW score (a real
        # two-word or phrase match), so noise is never injected -> warm is never
        # worse than cold.
        "embed_threshold": float(cfg.get("embed_threshold", 0.35)),
        "lexical_min_relevance": float(cfg.get("lexical_min_relevance", 4.0)),
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


def get_automation_import() -> dict:
    """Return the ``[automation_import]`` section with defaults filled in.

    Importing clients' existing automations (n8n/Make/Workato/Power Automate/
    UiPath definitions, plus connect-and-trigger for Zapier/Notion) is OFF by
    default: it reaches out to third-party platforms and writes user templates,
    so the operator opts in. ``create_schedules`` lets a recovered cron trigger
    auto-create a Lightwork schedule; off by default so an import never starts
    spending on a recurring run without an explicit second step.
    Env override: ``MAVERICK_AUTOMATION_IMPORT``.
    """
    cfg = load_config().get("automation_import", {})
    return {
        "enable": bool(cfg.get("enable", False)),
        "create_schedules": bool(cfg.get("create_schedules", False)),
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
        # Independent axis (resolved without ``enable``): assume-and-proceed
        # instead of blocking on ``ask_user`` when no human can answer
        # (headless / batch / benchmark runs). Default off.
        "headless_assume": bool(cfg.get("headless_assume", False)),
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


def get_fleet_memory() -> dict:
    """Return the ``[fleet_memory]`` section (agent-agnostic learning plane).
    OFF by default: exposing governed memory to third-party agents is an
    explicit trust decision."""
    cfg = load_config().get("fleet_memory", {})
    return {"enable": bool(cfg.get("enable", False))}


def get_memory() -> dict:
    """Return the ``[memory]`` section. ``temporal`` keeps a bitemporal history
    of every fact value (validity windows) instead of overwriting, so the
    Operating Record can answer "what did we believe on date X, and why".
    OFF by default (one extra append per fact change); the live-value read path
    is unchanged when off. Also honored via ``MAVERICK_TEMPORAL_MEMORY=1``."""
    cfg = load_config().get("memory", {})
    return {"temporal": bool(cfg.get("temporal", False))}


def get_memory_guard() -> dict:
    """Return the ``[memory_guard]`` section (OWASP ASI06 controls). OFF by
    default. When on, every memory write is screened for injection/poisoning and
    stamped with provenance + a trust tier, and memory below ``min_recall_trust``
    is filtered out of the agent's standing brief (trust-aware retrieval).
    ``min_recall_trust`` is a :class:`maverick.memory_guard.TrustTier` value
    (default 1 = drop only EXTERNAL/untrusted memory). Also honored via
    ``MAVERICK_MEMORY_GUARD=1``."""
    cfg = load_config().get("memory_guard", {})
    return {
        "enable": bool(cfg.get("enable", False)),
        "min_recall_trust": int(cfg.get("min_recall_trust", 1)),
    }


def get_domains() -> dict:
    """Return the ``[domains]`` section with defaults filled in.

    ``discipline`` appends the per-suite operating-discipline block to every
    domain pack's persona at spawn (ON by default — it is pack content, not a
    new capability; see :mod:`maverick.domain_discipline`). ``memory`` injects
    the department's recalled lessons into a specialist's brief at spawn —
    only meaningful when reflexion/dreaming are themselves enabled.
    """
    cfg = load_config().get("domains", {})
    return {
        "discipline": bool(cfg.get("discipline", True)),
        "memory": bool(cfg.get("memory", True)),
    }


def get_experience() -> dict:
    """Return the ``[experience]`` section (outcome-guided orchestration).
    OFF by default."""
    cfg = load_config().get("experience", {})
    return {"enable": bool(cfg.get("enable", False))}


def get_tax() -> dict:
    """Return the ``[tax]`` section (signed tax-constants content channel).

    ``auto_update`` is ON by default but a no-op until the operator
    configures both ``update_url`` and ``trusted_constants_pubkeys`` —
    updates are fail-closed against those anchors (see
    :mod:`maverick.tax_constants`). ``check_hours`` throttles the network
    check."""
    cfg = load_config().get("tax", {})
    try:
        check_hours = max(1.0, float(cfg.get("check_hours", 20.0)))
    except (TypeError, ValueError):
        check_hours = 20.0
    keys = cfg.get("trusted_constants_pubkeys", [])
    if not isinstance(keys, list):
        keys = []
    return {
        "auto_update": bool(cfg.get("auto_update", True)),
        "update_url": str(cfg.get("update_url", "") or "").strip(),
        "check_hours": check_hours,
        "trusted_constants_pubkeys": [str(k).strip() for k in keys
                                      if str(k).strip()],
    }


def get_dreaming() -> dict:
    """Return the ``[dreaming]`` section (offline experience consolidation).

    OFF by default. ``min_cluster`` is the evidence floor before a recurring
    pattern is consolidated (a one-off is noise); ``max_insights`` caps the
    persisted insight store; ``prune`` lets a dream cycle compact the
    reflexion log down to ``keep_reflexions`` deduplicated entries.
    """
    cfg = load_config().get("dreaming", {})

    def _int(key: str, default: int) -> int:
        try:
            return max(1, int(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _ratio(key: str, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(cfg.get(key, default))))
        except (TypeError, ValueError):
            return default

    def _nonneg_int(key: str, default: int) -> int:
        try:
            return max(0, int(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {
        "enable": bool(cfg.get("enable", False)),
        "min_cluster": _int("min_cluster", 2),
        "max_insights": _int("max_insights", 100),
        "prune": bool(cfg.get("prune", True)),
        "keep_reflexions": _int("keep_reflexions", 500),
        # Shared promotion is disabled by default: department-scoped failures
        # must not be written into globally recallable insights.
        "promote_shared": bool(cfg.get("promote_shared", False)),
        # Mine verifier critiques out of donated trajectory records (empty
        # unless [telemetry] donate_trajectories has produced any).
        "mine_critiques": bool(cfg.get("mine_critiques", True)),
        # Insights unconfirmed for this many days retire; 0 = never expire.
        "insight_ttl_days": _nonneg_int("insight_ttl_days", 90),
        # Retire a failure insight once this many NEWER similar successes
        # contradict it ("we now reliably do X").
        "contradiction_successes": _int("contradiction_successes", 2),
        # Fact consolidation deletes operator data, so it is opt-in even
        # inside the already-opt-in dreaming feature.
        "prune_facts": bool(cfg.get("prune_facts", False)),
        "facts_max_age_days": _nonneg_int("facts_max_age_days", 180),
        "facts_cap": _nonneg_int("facts_cap", 2000),
        # Distill explicit user-preference statements into per-user notes.
        "user_notes": bool(cfg.get("user_notes", True)),
        # Quarantine this cycle's NEW skills while the continuously-tracked
        # benchmark suite is regressing (learning-side canary).
        "benchmark_gate": bool(cfg.get("benchmark_gate", True)),
        # Learning rollback: snapshot every learned store before a CLI dream
        # cycle mutates it, keeping the last N snapshots.
        "snapshots": bool(cfg.get("snapshots", True)),
        "snapshot_keep_last": _int("snapshot_keep_last", 5),
        # Dream-time rehearsal (maverick-evolve harness) is a separate trust
        # decision from consolidation: it spends real agent runs. Default off.
        "rehearse": bool(cfg.get("rehearse", False)),
        "max_rehearsals": _int("max_rehearsals", 3),
        # Forgetting loop: retire learned skills whose recall track record
        # decayed below the floor (after enough attempts to judge).
        "retire_skills": bool(cfg.get("retire_skills", True)),
        "retire_min_uses": _int("retire_min_uses", 5),
        "retire_below": _ratio("retire_below", 0.25),
    }


def get_self_improvement() -> dict:
    """Return the ``[self_improvement]`` section (governed learning promotion).

    OFF by default and a no-op while off: when ``enable`` is false the
    Self-Improvement Controller never promotes a self-change, so a default
    deployment is unaffected. ``min_improvement`` is the eval margin a candidate
    must beat its own baseline by before any rung is eligible; ``max_auto_rung``
    is the highest rung that may be promoted without a human (anything above it
    -- e.g. ``code``/``weights`` -- always requires explicit approval).
    """
    cfg = load_config().get("self_improvement", {})

    def _ratio(key: str, default: float) -> float:
        try:
            return max(0.0, float(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {
        "enable": bool(cfg.get("enable", False)),
        "min_improvement": _ratio("min_improvement", 0.0),
        "max_auto_rung": str(cfg.get("max_auto_rung", "policy")).strip().lower() or "policy",
        # Phase-0 capture (raw-trajectory store) and PRM-in-loop guidance, both
        # off by default; see maverick.trajectory_store / maverick.prm_guidance.
        "capture": bool(cfg.get("capture", False)),
        "prm_guidance": bool(cfg.get("prm_guidance", False)),
        # Counterfactual promotion: judge a self-change on its confounder-adjusted
        # CAUSAL effect (maverick.promotion_effect) rather than a correlational
        # baseline/candidate diff. Off by default; the controller only consults a
        # causal effect when this is set.
        "causal_promotion": bool(cfg.get("causal_promotion", False)),
    }


def get_rehearsal() -> dict:
    """Return the ``[rehearsal]`` section (pre-execution rehearsal gate).

    The governance half of the Operating Twin: before a risky plan executes, it
    is simulated against the learned world-model and gated on the prediction.
    OFF by default and fail-open -- when ``enable`` is false ``gate_action`` is a
    no-op that proceeds, so a default deployment is unaffected. ``outcome_floor``
    is the predicted-outcome below which a *confident* rehearsal blocks;
    ``min_support`` is the (state, action) observations the model needs before it
    will vouch for a move (below it the action is escalated, never waved through);
    ``max_uncertainty`` escalates an over-uncertain rollout.
    """
    cfg = load_config().get("rehearsal", {})

    def _num(key: str, default: float, cast=float):
        try:
            return cast(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    return {
        "enable": bool(cfg.get("enable", False)),
        "outcome_floor": _num("outcome_floor", 0.5),
        "min_support": _num("min_support", 5, int),
        "max_uncertainty": _num("max_uncertainty", 0.25),
        "horizon": _num("horizon", 8, int),
        "rollouts": _num("rollouts", 200, int),
    }


def get_speculative() -> dict:
    """Return the ``[speculative]`` section (speculative agent execution).

    Draft a turn with a cheap model when the Operating Twin's world-model is
    confident the turn is predictable, reserving the frontier model for novel /
    uncertain turns. OFF by default and fail-open -- when ``enable`` is false (or
    no ``draft_model`` is configured) the agent always uses its normal model.
    ``draft_model`` is an operator-chosen cheap model spec (never hard-coded);
    ``min_confidence``/``min_support`` set how dominant + well-observed an action
    must be before its turn is drafted.
    """
    cfg = load_config().get("speculative", {})

    def _num(key: str, default: float, cast=float):
        try:
            return cast(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    return {
        "enable": bool(cfg.get("enable", False)),
        "draft_model": (str(cfg.get("draft_model", "")).strip() or None),
        "min_confidence": _num("min_confidence", 0.85),
        "min_support": _num("min_support", 8, int),
    }


def get_data_engine() -> dict:
    """Return the ``[data_engine]`` section (the Cognitive Data Engine).

    The Tesla-style improvement flywheel for the agent workforce: production
    failures are causally triaged, a fix is mined + validated in the world-model,
    promoted through the safety ladder, and measured against real outcomes. OFF
    by default -- when ``enable`` is false the engine never runs, so a default
    deployment is unaffected. ``failure_threshold`` is the outcome below which an
    episode counts as a failure; ``min_support`` is the evidence a causal-impact
    estimate needs before a failure class is ranked.
    """
    cfg = load_config().get("data_engine", {})

    def _num(key: str, default: float, cast=float):
        try:
            return cast(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    return {
        "enable": bool(cfg.get("enable", False)),
        "failure_threshold": _num("failure_threshold", 0.5),
        "min_support": _num("min_support", 8, int),
        "top_k": _num("top_k", 10, int),
    }


def get_consequence() -> dict:
    """Return the ``[consequence]`` section (the Consequence Engine).

    Reality as the reward: real downstream outcomes (invoice paid, contract
    renewed, ticket stayed closed), reported by a system-of-record connector and
    joined back to the episode that acted, become the grounded learning signal.
    OFF by default -- when ``enable`` is false the data-engine join keeps using
    the verifier-confidence proxy, so a default deployment is unaffected;
    recording outcomes is always harmless (it just stores).
    """
    cfg = load_config().get("consequence", {})
    return {"enable": bool(cfg.get("enable", False))}


def get_operations_scientist() -> dict:
    """Return the ``[operations_scientist]`` section (the discovery engine).

    An agent that discovers a better process and proves it causally: it pairs a
    harmful action with the beneficial habit that should replace it, validates the
    swap in the world-model, then (downstream) runs a real experiment and ships
    the proven win. OFF by default -- when ``enable`` is false the engine never
    runs, so a default deployment is unaffected.
    """
    cfg = load_config().get("operations_scientist", {})
    return {"enable": bool(cfg.get("enable", False))}


def get_emergent_protocol() -> dict:
    """Return the ``[emergent_protocol]`` section (learned coordination shorthand).

    The swarm evolves short codes for the boilerplate it repeats, paying frontier
    tokens only for what's new -- but every code decodes exactly back to English
    (the auditable translation layer). OFF by default -- when ``enable`` is false
    the codec is the identity transform, so a default deployment is unaffected.
    """
    cfg = load_config().get("emergent_protocol", {})
    return {"enable": bool(cfg.get("enable", False))}


def get_emergent_codec() -> dict:
    """Return the ``[emergent_codec]`` section (live token-aware compression).

    The token-aware codec (``maverick.emergent_tokens``) is the implementation that
    actually saves *frontier tokens*, not just bytes -- byte-stuffed ~2-token codes
    instead of the ~5-token sentinels. When ``enable`` is true the blackboard
    measures, on the real coordination stream, what the codec would save (telemetry
    only -- the rendered text agents see is unchanged, so the audit/Shield path is
    untouched). OFF by default: a default deployment measures nothing and pays
    nothing. Flipping agents to actually *read* codes is a separate, stricter step.
    """
    cfg = load_config().get("emergent_codec", {})
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
