"""Enterprise mode — hardened defaults for working with private / sensitive data.

The kernel ships **fail-open and cloud-capable** by design (CLAUDE.md rule 1): the
shield fails open, consent auto-approves, capabilities are opt-in, and any configured
LLM provider — including a third-party cloud API — sees the prompt. That is the right
default for a personal agent. It is the *wrong* default the moment the agent is pointed
at PHI / PII / financial / regulated data, where the data leaving the boundary or an
unsupervised destructive action is exactly the exposure an enterprise cannot accept.

**Enterprise mode is one opt-in switch that makes those defaults fail-closed** and
guarantees the property an enterprise needs before it lets an agent touch sensitive
data: *the data never leaves your boundary.*

Turn it on with ``MAVERICK_ENTERPRISE=1``, ``[enterprise] mode = true`` in
``~/.maverick/config.toml``, or the installer wizard. **Off by default** — behaviour is
exactly as before.

When on, it enforces:

- **Egress lock.** Every LLM call is pinned to a local / self-hosted provider
  (``ollama`` / ``vllm`` / ``tgi``, or an endpoint you allow-list under
  ``[enterprise] local_providers``). A call routed to a cloud provider
  (``anthropic`` / ``openai`` / ...) raises :class:`EgressBlocked` **before any prompt
  is sent**, and the denial is audited. Sensitive data physically cannot reach a
  third-party API. (Enforced in :func:`maverick.llm.LLM.complete`.)
- **Consent fail-closed.** Destructive-action consent defaults to ``ask`` (and therefore
  *deny* in non-interactive contexts) instead of ``auto-approve``.
  (Enforced in :mod:`maverick.safety.consent`.)
- **Capabilities enforced.** Per-agent capability scoping + attenuating propagation is
  turned on, so a sub-agent can never exceed its grant.
  (Enforced in :func:`maverick.capability.capability_enforced`.)

An explicit env/config setting still wins for each individual control (so an operator
can, e.g., allow-list one extra self-hosted endpoint), but the *defaults* are safe and
the egress lock can never be satisfied by a cloud provider.
"""
from __future__ import annotations

import os

# Built-in self-hosted providers: data stays on infrastructure the operator runs.
# ``ollama`` (localhost:11434), ``vllm`` and ``tgi`` (self-hosted inference servers).
# An operator can declare additional local endpoints via ``[enterprise]
# local_providers`` (e.g. a generic OpenAI-compatible provider pointed at an internal
# vLLM) — see :func:`_extra_local_providers`.
LOCAL_PROVIDERS = frozenset({"ollama", "vllm", "tgi"})


class EgressBlocked(RuntimeError):
    """Raised when enterprise mode refuses to send data to a non-local provider."""

    def __init__(self, provider: str):
        super().__init__(
            f"enterprise mode: refusing to send data to non-local provider "
            f"{provider!r}. Sensitive data must stay in your boundary — route this "
            f"role to a self-hosted model (ollama / vllm / tgi) or add the endpoint "
            f"to [enterprise] local_providers in ~/.maverick/config.toml."
        )
        self.provider = provider


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def enterprise_enabled() -> bool:
    """True if enterprise mode is on. ``MAVERICK_ENTERPRISE`` env (set to a falsey
    value to force-disable) wins over ``[enterprise] mode`` in config. Off by default."""
    env = os.environ.get("MAVERICK_ENTERPRISE")
    if env is not None and env.strip() != "":
        return _truthy(env)
    try:
        from .config import load_config
        val = ((load_config() or {}).get("enterprise") or {}).get("mode")
    except Exception:
        return False
    if isinstance(val, str):
        return _truthy(val)
    return bool(val)


def _extra_local_providers() -> frozenset[str]:
    """Operator-declared additional self-hosted providers (``[enterprise]
    local_providers``), canonicalized. Lets an internal endpoint behind a generic
    provider count as local. Empty / unreadable config -> no extras."""
    try:
        from .config import load_config
        from .providers import _canonical
        raw = ((load_config() or {}).get("enterprise") or {}).get("local_providers") or []
        return frozenset(_canonical(str(x)) for x in raw)
    except Exception:
        return frozenset()


def is_local_provider(provider: str) -> bool:
    """True if ``provider`` is self-hosted (built-in local set or operator allow-list).

    The name is canonicalized first, so the ``ollama`` alias ``local`` and any
    capitalization resolve correctly.
    """
    try:
        from .providers import _canonical
        canon = _canonical(provider)
    except Exception:
        canon = (provider or "").strip().lower()
    return canon in LOCAL_PROVIDERS or canon in _extra_local_providers()


def assert_provider_allowed(provider: str) -> None:
    """Egress guard. No-op unless enterprise mode is on.

    When on, raises :class:`EgressBlocked` for a non-local provider so sensitive data
    never leaves the boundary, and records an ``egress_blocked`` audit event. Called at
    the single LLM dispatch chokepoint (:func:`maverick.llm.LLM.complete`) so it covers
    every agent, role, and tool-driven model call.
    """
    if not enterprise_enabled():
        return
    if is_local_provider(provider):
        return
    try:
        from .providers import _canonical
        canon = _canonical(provider)
    except Exception:
        canon = (provider or "").strip().lower()
    try:  # fail-safe: a blocked-egress denial must never crash on the audit path
        from .audit import EventKind, record
        record(EventKind.EGRESS_BLOCKED, provider=canon)
    except Exception:
        pass
    raise EgressBlocked(canon)


__all__ = [
    "LOCAL_PROVIDERS",
    "EgressBlocked",
    "enterprise_enabled",
    "is_local_provider",
    "assert_provider_allowed",
]
