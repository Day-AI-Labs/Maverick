"""Air-gapped preflight verification (roadmap: 2028 H2 safety — "air-gapped mode").

A regulated / classified deployment needs to *prove* there is no outbound path
before it trusts the box. Full OS-level air-gapping (firewall, no NIC) is the
operator's job; this is the **application-layer audit** that catches the ways
Maverick's own config would still reach the network: a remote model provider, a
non-deny-all egress policy, or a sandbox allowed network access. ``maverick
airgap check`` runs it and exits non-zero on any finding, so it can gate a
deployment.

Pure config inspection — a config dict in, a list of violations out — so it's
deterministic and tested without touching the network. The runtime *enforcement*
(the egress chokepoint, local-first routing) ships separately; this verifies the
deployment is actually configured for them.
"""
from __future__ import annotations


def audit(*, config=None) -> dict:
    """Audit a config for outbound paths. Returns ``{clean, violations}``."""
    if config is None:
        try:
            from .config import load_config
            config = load_config() or {}
        except Exception:  # pragma: no cover -- never block the check
            config = {}
    violations: list[str] = []
    violations += _audit_providers(config)
    violations += _audit_egress(config)
    violations += _audit_sandbox(config)
    return {"clean": not violations, "violations": violations}


def _audit_providers(config: dict) -> list[str]:
    from .llm import ROLE_MODELS
    from .provider_local_first import is_local
    models = dict(ROLE_MODELS)
    for role, spec in (config.get("llm") or {}).items():
        if isinstance(spec, str) and spec.strip():
            models[role] = spec
    remote = sorted({m for m in models.values() if not is_local(m)})
    if remote:
        return [f"remote model(s) in use: {', '.join(remote)} — route every role "
                "to a local provider (ollama / vllm / tgi)"]
    return []


def _audit_egress(config: dict) -> list[str]:
    egress = config.get("egress") or {}
    deny = egress.get("deny") or []
    if "*" not in deny:
        return ['egress is not deny-all — set [egress] deny = ["*"] to block '
                "all outbound hosts"]
    return []


def _audit_sandbox(config: dict) -> list[str]:
    sb = config.get("sandbox") or {}
    val = sb.get("allow_network")
    if val is True or (isinstance(val, str) and val.strip().lower() in
                       {"1", "true", "yes", "on"}):
        return ["[sandbox] allow_network is on — the sandbox can reach the network"]
    return []


__all__ = ["audit"]
