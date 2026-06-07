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

import ipaddress
import os
from urllib.parse import urlparse

# Built-in self-hosted providers: data stays on infrastructure the operator runs.
# ``ollama`` (localhost:11434), ``vllm`` and ``tgi`` (self-hosted inference servers).
# An operator can declare additional local endpoints via ``[enterprise]
# local_providers`` (e.g. a custom in-process provider). Known cloud providers are
# never accepted as local, even if listed in config.
LOCAL_PROVIDERS = frozenset({"ollama", "vllm", "tgi"})

# Providers whose canonical implementations route to third-party/cloud APIs. They
# must not become enterprise-local through the operator-provided provider-name list.
CLOUD_PROVIDERS = frozenset({
    "anthropic",
    "azure",
    "bedrock",
    "deepseek",
    "gemini",
    "moonshot",
    "openai",
    "openrouter",
    "xai",
})

# The generic OpenAI-compatible provider can point at either a local/self-hosted
# endpoint or an arbitrary public gateway. In enterprise mode it is only treated as
# local when its configured endpoint is provably local/private.
_ENDPOINT_VALIDATED_PROVIDERS = frozenset({"openai_compatible"})


class EgressBlocked(RuntimeError):
    """Raised when enterprise mode refuses to send data to a non-local provider."""

    def __init__(self, provider: str):
        super().__init__(
            f"enterprise mode: refusing to send data to non-local provider "
            f"{provider!r}. Sensitive data must stay in your boundary — route this "
            f"role to a self-hosted model (ollama / vllm / tgi) or another "
            f"validated local provider."
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


def _configured_openai_compatible_base_url() -> str | None:
    """Return the configured OpenAI-compatible endpoint, matching provider setup."""
    try:
        from .config import get_provider_config

        cfg = get_provider_config("openai_compatible")
    except Exception:
        cfg = {}
    url = cfg.get("base_url") or os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
    return str(url).strip() if url else None


def _is_local_endpoint(url: str | None) -> bool:
    """True only for endpoints that are syntactically local/private.

    Enterprise egress is fail-closed: public hostnames such as Groq/Together and
    ambiguous DNS names are not considered local here because this check runs before
    prompt dispatch and must not rely on network lookups.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.strip().lower().rstrip(".")
    if host in {"localhost", "ip6-localhost", "ip6-loopback"} or host.endswith(
        ".localhost"
    ):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _endpoint_validated_provider_is_local(provider: str) -> bool:
    if provider != "openai_compatible":
        return False
    return _is_local_endpoint(_configured_openai_compatible_base_url())


def _extra_local_providers() -> frozenset[str]:
    """Operator-declared additional self-hosted providers (``[enterprise]
    local_providers``), canonicalized and fail-closed. Known cloud providers are
    ignored even if listed, and base-url-driven providers must have a configured
    local/private endpoint before they count as local. Empty / unreadable config ->
    no extras."""
    try:
        from .config import load_config
        from .providers import _canonical

        raw = ((load_config() or {}).get("enterprise") or {}).get("local_providers") or []
        providers: set[str] = set()
        for item in raw:
            canon = _canonical(str(item))
            if not canon:
                continue
            if canon in LOCAL_PROVIDERS:
                providers.add(canon)
            elif canon in CLOUD_PROVIDERS:
                continue
            elif canon in _ENDPOINT_VALIDATED_PROVIDERS:
                if _endpoint_validated_provider_is_local(canon):
                    providers.add(canon)
            else:
                providers.add(canon)
        return frozenset(providers)
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
    "CLOUD_PROVIDERS",
    "LOCAL_PROVIDERS",
    "EgressBlocked",
    "enterprise_enabled",
    "is_local_provider",
    "assert_provider_allowed",
]
