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

# Built-in local providers can be redirected off-box via [providers.<name>]
# base_url or these env vars. A configured non-local endpoint must NOT satisfy the
# egress lock just because the provider *name* is "local" (ollama has no env
# override -- it reads [providers.ollama] base_url).
_LOCAL_PROVIDER_ENDPOINT_ENV = {
    "vllm": "VLLM_BASE_URL",
    "tgi": "TGI_BASE_URL",
}


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


def _configured_base_url(provider: str) -> str | None:
    """The operator-configured endpoint for ``provider`` (``[providers.<name>]
    base_url`` or its env override), or ``None`` if it uses its built-in default."""
    try:
        from .config import get_provider_config
        cfg = get_provider_config(provider)
    except Exception:
        cfg = {}
    env_var = _LOCAL_PROVIDER_ENDPOINT_ENV.get(provider)
    url = cfg.get("base_url") or (os.environ.get(env_var) if env_var else None)
    return str(url).strip() if url else None


def _builtin_local_provider_is_local(provider: str) -> bool:
    """A built-in local provider (ollama/vllm/tgi) is local unless it has been
    pointed at a non-local endpoint. No configured endpoint -> the built-in
    localhost default -> local. A public base_url -> NOT local: this is the
    egress-lock bypass (a "local" provider name aimed off-box) that we close."""
    url = _configured_base_url(provider)
    if url is None:
        return True
    return _is_local_endpoint(url)


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
                # Operator-vouched custom provider: admit it (a bare name is a
                # deliberate vouch), but never when it carries an explicitly
                # non-local base_url -- a public endpoint can't be "local".
                url = _configured_base_url(canon)
                if url is None or _is_local_endpoint(url):
                    providers.add(canon)
        return frozenset(providers)
    except Exception:
        return frozenset()


def is_local_provider(provider: str) -> bool:
    """True if ``provider`` is self-hosted AND its endpoint is provably local.

    The name is canonicalized first (so the ``ollama`` alias ``local`` and any
    capitalization resolve). A built-in local provider (ollama/vllm/tgi) only
    counts as local when its resolved endpoint is local/private -- a ``base_url``
    or ``VLLM_BASE_URL``/``TGI_BASE_URL`` pointing off-box does NOT satisfy the
    egress lock just because the provider name is "local".
    """
    try:
        from .providers import _canonical
        canon = _canonical(provider)
    except Exception:
        canon = (provider or "").strip().lower()
    if canon in LOCAL_PROVIDERS:
        return _builtin_local_provider_is_local(canon)
    return canon in _extra_local_providers()


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
