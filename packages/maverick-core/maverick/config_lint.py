"""Config validator for ``~/.maverick/config.toml`` (Maverick 2.0 RFC item).

Walks an already-loaded config dict (see :func:`maverick.config.load_config`)
and reports likely mistakes: a mistyped section name, an unknown key inside a
section whose key set is fixed, and a small, safe set of obvious type errors
(``budget.max_dollars`` must be a number; ``*.enabled`` must be a bool).

Design constraints:
- Pure stdlib (``difflib`` for "did you mean" suggestions), deterministic.
- Conservative: only flag things we're confident about. Dynamic sections —
  ``[providers.<name>]``, ``[channels.<name>]``, ``[models]``,
  ``[mcp_servers.<name>]``, ``[roles.<role>]`` and similar — accept any
  subkeys, so we never flag their keys.
- Never raises on a weird dict. A non-dict section value, a non-string key,
  ``None`` — all tolerated; we simply skip what we can't reason about.

This is advisory only. The kernel itself fails soft on a bad config (see
``maverick.config.load_config``); this lets the wizard / a ``maverick config
lint`` command surface problems up front.
"""
from __future__ import annotations

import difflib
import math
from dataclasses import dataclass
from typing import Any

# Known top-level sections -> allowed keys, or ``None`` to allow ANY key.
#
# ``None`` is used for two kinds of section:
#   * genuinely dynamic tables whose subkeys are user-chosen names
#     (``models`` role->spec, ``providers.<name>``, ``channels.<name>``,
#     ``mcp_servers.<name>``, ``roles.<role>``), and
#   * sections whose key set is still evolving / spread across modules, where
#     enumerating keys would produce false-positive warnings on valid configs.
#
# Only sections with a small, stable, documented key set get an explicit set;
# those are the ones where an unknown key is a useful signal.
KNOWN_SCHEMA: dict[str, set[str] | None] = {
    # --- fixed-key sections (unknown keys are flagged) ---
    "deployment": {"type"},
    "budget": {
        "max_dollars",
        "max_wall_seconds",
        "max_tool_calls",
        "max_input_tokens",
        "max_output_tokens",
    },
    "safety": {
        "profile",
        "block_threshold",
        "scan_input",
        "scan_tool_calls",
        "scan_output",
        "constitution",
        "compartments",
        "compartment_unseal",
    },
    "sandbox": {"backend", "workdir", "timeout"},
    "features": {"skills", "world_model", "streaming"},
    "capabilities": {
        "computer_use",
        "browser",
        "web_search",
        "mobile_tools",
        "code_exec",
        # Governance knobs the runtime reads (capability.py / agent.py) that
        # were missing here -- so a client configuring the flagship
        # capability-enforcement feature, or the deferred-tools knob, got a
        # false "unknown key" warning (client-journey finding).
        "enforce",
        "per_call_tokens",
        "deferred_tools",
    },
    # Tamper-evident audit log. The runtime reads [audit] sign (audit/writer.py)
    # and migrate.py already lists it; config-lint flagged the whole section as
    # unknown ("did you mean auth?"), telling a regulated client their flagship
    # signed-audit config looked like a typo (client-journey finding).
    "audit": {"sign"},
    "durable": {"enabled", "keep_last"},
    "persona": {"name", "style", "addendum"},
    # The dashboard reads more than the auth token: theme/density/allow_extension
    # (app.py) and a [dashboard.themes] subtable (themes.py). Listing only
    # "token" made config-lint warn "unknown key" on documented operator
    # settings like `[dashboard] theme = "dark"` (user-testing finding).
    "dashboard": {"token", "theme", "density", "allow_extension", "themes"},
    "analytics": {"mcp_client_language"},
    # --- dynamic / open-ended sections (any subkey accepted) ---
    "providers": None,
    "models": None,
    "channels": None,
    "mcp_servers": None,
    "roles": None,
    "routing": None,
    "planning": None,
    "context": None,
    "reflexion": None,
    "effort": None,
    "cache": None,
    "quotas": None,
    "tenancy": None,
    "retention": None,
    "world_model": None,
    "memory": None,
    "voice": None,
    "webhooks": None,
    "a2a": None,
    "auth": None,
    "knowledge": None,
    "skills": None,
    "self_learning": None,
    "autonomy": None,
    "calibration": None,
    "credit": None,
    "adaptive_compute": None,
    "search": None,
    "skill_synthesis": None,
    "experience": None,
    "compliance": None,
    "security": None,
    "plugins": None,
    "tools": None,
}

# Keep this registry in lockstep with migrate.py's KNOWN_SECTIONS (curated
# from the real load_config() call sites) so config-lint never false-flags a
# section the runtime actually reads as a typo. The two had drifted by ~59
# sections -- a client configuring documented features like [provider_failover],
# [enterprise], [egress], [governance], [encryption] got told they were
# typos (client-journey finding). Sections with an explicit key schema above
# keep it (setdefault won't overwrite); the rest accept any subkey (None),
# exactly as migrate treats them.
from .migrate import KNOWN_SECTIONS as _RUNTIME_SECTIONS  # noqa: E402

for _section in _RUNTIME_SECTIONS:
    KNOWN_SCHEMA.setdefault(_section, None)


@dataclass
class Finding:
    section: str
    key: str | None
    severity: str  # "error" | "warning"
    message: str


# Keys that, when present, must be a number (int/float, but not bool — in
# Python ``bool`` is an ``int`` subclass, so we exclude it explicitly).
# Section -> key.
_NUMERIC_KEYS: dict[str, set[str]] = {
    "budget": {
        "max_dollars",
        "max_wall_seconds",
        "max_tool_calls",
        "max_input_tokens",
        "max_output_tokens",
    },
    "sandbox": {"timeout"},
    "durable": {"keep_last"},
}

# Keys that, when present, must be a bool. Section -> key. Plus the universal
# ``enabled``/``enable`` toggle, handled separately for every known section.
_BOOL_KEYS: dict[str, set[str]] = {
    "safety": {"scan_input", "scan_tool_calls", "scan_output", "compartments"},
    "features": {"skills", "world_model", "streaming"},
    "capabilities": {
        "computer_use",
        "browser",
        "web_search",
        "mobile_tools",
        "code_exec",
        "enforce",
        "per_call_tokens",
        "deferred_tools",
    },
    "audit": {"sign"},
    "analytics": {"mcp_client_language"},
}

_UNIVERSAL_BOOL_KEYS = ("enabled", "enable")


# Key names that carry secrets. A literal (non-``${ENV}``) string under one of
# these is a plaintext secret in config.toml -- flagged so operators route it
# through an env var / secrets manager instead. Conservative to avoid noise.
# Bare ``token`` is deliberately NOT here: it is a documented operator setting
# (e.g. ``[dashboard] token``) and too broad to flag without false positives.
# Secret-bearing ``*_token`` keys are still caught by the suffix list below.
_SECRET_KEY_NAMES = frozenset({
    "api_key", "apikey", "secret", "client_secret", "password", "passwd",
    "private_key",
})
_SECRET_KEY_SUFFIXES = ("_api_key", "_secret", "_password", "_token")


def _is_secret_key(key: str) -> bool:
    k = key.lower()
    return k in _SECRET_KEY_NAMES or k.endswith(_SECRET_KEY_SUFFIXES)


def _looks_like_env_ref(v: str) -> bool:
    """True for an env-var reference or an empty placeholder -- i.e. NOT an inline
    secret. ``${VAR}`` / ``$VAR`` interpolate from the environment; ``""`` is an
    unset placeholder. Anything else under a secret-bearing key is literal."""
    s = v.strip()
    return s == "" or s.startswith("$")


def _lint_inline_secrets(cfg: dict, _path: tuple[str, ...] = ()) -> list[Finding]:
    """Walk the whole config (nested tables included) and warn on a literal
    string under a secret-bearing key -- a plaintext secret in config.toml."""
    out: list[Finding] = []
    for key, val in cfg.items():
        if not isinstance(key, str):
            continue
        if isinstance(val, dict):
            out.extend(_lint_inline_secrets(val, _path + (key,)))
        elif (
            _is_secret_key(key)
            and isinstance(val, str)
            and not _looks_like_env_ref(val)
        ):
            dotted = ".".join(_path + (key,))
            out.append(Finding(
                section=".".join(_path) or "(root)",
                key=key,
                severity="warning",
                message=(
                    f"{dotted} looks like an inline secret; reference an env var "
                    f'instead (e.g. {key} = "${{MY_SECRET}}") so the secret is not '
                    "stored in plaintext config."
                ),
            ))
    return out


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_valid_numeric_cap(v: int | float) -> bool:
    """Return whether a numeric cap is finite and non-negative.

    ``math.isfinite`` coerces arbitrary-size Python ints to float, which can
    raise ``OverflowError`` for huge TOML integers. Integers are always finite,
    so handle them before checking floats.
    """
    if isinstance(v, int):
        return v >= 0
    return math.isfinite(v) and v >= 0


def _suggest(name: str, candidates: list[str]) -> str:
    """Return ' (did you mean "X"?)' for the closest candidate, else ''."""
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=0.6)
    if matches:
        return f' (did you mean "{matches[0]}"?)'
    return ""


def lint_config(cfg: dict) -> list[Finding]:
    """Validate a loaded config dict and return findings (possibly empty).

    Never raises: anything we can't interpret is skipped rather than flagged.
    """
    findings: list[Finding] = []
    if not isinstance(cfg, dict):
        return findings

    known_sections = sorted(KNOWN_SCHEMA)

    for section, value in cfg.items():
        if not isinstance(section, str):
            continue

        if section not in KNOWN_SCHEMA:
            findings.append(
                Finding(
                    section=section,
                    key=None,
                    severity="warning",
                    message=(
                        f'unknown config section "{section}"'
                        + _suggest(section, known_sections)
                    ),
                )
            )
            continue

        if not isinstance(value, dict):
            # A section is expected to be a table; a scalar/list here is almost
            # certainly a mistake, but we only own the cases we're sure about.
            continue

        allowed = KNOWN_SCHEMA[section]
        numeric_keys = _NUMERIC_KEYS.get(section, set())
        bool_keys = _BOOL_KEYS.get(section, set())

        for key, kval in value.items():
            if not isinstance(key, str):
                continue

            # Unknown key in a fixed-key section.
            if allowed is not None and key not in allowed:
                findings.append(
                    Finding(
                        section=section,
                        key=key,
                        severity="warning",
                        message=(
                            f'unknown key "{key}" in [{section}]'
                            + _suggest(key, sorted(allowed))
                        ),
                    )
                )
                # Don't also type-check a key we don't recognize.
                continue

            # Type checks (conservative; only knowable cases).
            if key in numeric_keys and not _is_number(kval):
                findings.append(
                    Finding(
                        section=section,
                        key=key,
                        severity="error",
                        message=(
                            f"{section}.{key} must be a number, got "
                            f"{type(kval).__name__}"
                        ),
                    )
                )
            elif key in numeric_keys and not _is_valid_numeric_cap(kval):
                # A negative cap bricks every run (immediate BudgetExceeded); a
                # non-finite cap (TOML nan/inf) silently DISABLES enforcement.
                # Both pass an isinstance check but are never valid caps
                # (user-testing finding).
                findings.append(
                    Finding(
                        section=section,
                        key=key,
                        severity="error",
                        message=(
                            f"{section}.{key} must be a finite, non-negative "
                            f"number, got {kval!r}"
                        ),
                    )
                )
            elif (
                key in bool_keys or key in _UNIVERSAL_BOOL_KEYS
            ) and not isinstance(kval, bool):
                findings.append(
                    Finding(
                        section=section,
                        key=key,
                        severity="error",
                        message=(
                            f"{section}.{key} must be true or false, got "
                            f"{type(kval).__name__}"
                        ),
                    )
                )

    findings.extend(_lint_inline_secrets(cfg))
    return findings


def format_findings(findings: list[Finding]) -> str:
    """Render findings as a human-readable summary.

    Returns ``"config OK"`` when there are none. Otherwise one line per
    finding, errors before warnings, with a count header.
    """
    if not findings:
        return "config OK"

    ordered = sorted(
        findings,
        key=lambda f: (0 if f.severity == "error" else 1, f.section, f.key or ""),
    )
    n_err = sum(1 for f in findings if f.severity == "error")
    n_warn = len(findings) - n_err

    lines = [f"config: {n_err} error(s), {n_warn} warning(s)"]
    for f in ordered:
        loc = f.section if f.key is None else f"{f.section}.{f.key}"
        lines.append(f"  [{f.severity}] {loc}: {f.message}")
    return "\n".join(lines)


def warn_config_at_startup(*, strict: bool | None = None) -> list[Finding]:
    """Lint the active config and emit findings to the log at server startup.

    Surfaces typo'd sections/keys -- which silently fall back to defaults, so a
    ``[budget] max_dollarss`` runs UNCAPPED -- at the moment a long-running
    server starts, rather than only when an operator happens to run
    ``maverick config-lint``. Warn-only by default (operators may legitimately
    use keys newer than this build). With ``strict`` (or
    ``MAVERICK_CONFIG_STRICT=1``) an error-level finding raises ``SystemExit`` so
    a regulated deployment fails fast instead of running with a mis-typed
    control. Never raises on its own bugs -- config linting must not block a
    start except via the explicit strict gate."""
    import logging
    import os

    _log = logging.getLogger("maverick.config")
    try:
        from .config import config_path, load_config
        if not config_path().exists():
            return []
        cfg = load_config() or {}
        findings = lint_config(cfg)
    except Exception:  # pragma: no cover -- linting never blocks startup
        return []
    for f in findings:
        loc = f.section if f.key is None else f"{f.section}.{f.key}"
        _log.warning("config: [%s] %s: %s", f.severity, loc, f.message)
    if strict is None:
        strict = os.environ.get("MAVERICK_CONFIG_STRICT", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
    # Strict mode fails on ANY finding, not just error-level ones: an unknown
    # key (a typo that silently uses a default -- the dangerous case M5 is
    # about) is reported as a *warning*, so an error-only gate would miss it. A
    # regulated/strict deployment wants a clean config or no start.
    if strict and findings:
        raise SystemExit(
            "config has problems (logged above) and MAVERICK_CONFIG_STRICT is "
            "set; refusing to start. Run `maverick config-lint` and fix them."
        )
    return findings
