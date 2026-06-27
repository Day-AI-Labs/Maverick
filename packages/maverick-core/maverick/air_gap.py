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
    for role, spec in (config.get("models") or {}).items():
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


def _truthy(val) -> bool:
    return val is True or (isinstance(val, str) and val.strip().lower() in
                           {"1", "true", "yes", "on"})


def _audit_sandbox(config: dict) -> list[str]:
    sb = config.get("sandbox") or {}
    backend = str(sb.get("backend") or "local").strip().lower()
    val = sb.get("allow_network")
    network_policy = str(sb.get("network_policy") or "").strip().lower()
    if backend == "kubernetes":
        # A transient `kubectl run` pod has full egress by default and the
        # backend refuses to run with allow_network=false (it cannot self-
        # enforce no-egress). The only k8s config that actually runs air-gapped
        # is allow_network=true behind an operator-applied cluster-level
        # deny-all NetworkPolicy — invisible to static config inspection. So
        # the audit can only clear k8s when the operator explicitly asserts
        # that policy; otherwise egress is unprovable.
        if _truthy(val) and network_policy in {"deny-all", "deny_all", "deny"}:
            return []
        return ["[sandbox] backend=kubernetes egress cannot be proven by config "
                "inspection — a cluster-level deny-all NetworkPolicy must be "
                "applied out-of-band; assert it with allow_network = true and "
                'network_policy = "deny-all"']
    if _truthy(val):
        return ["[sandbox] allow_network is on — the sandbox can reach the network"]
    if backend in {"docker", "podman", "gvisor"}:
        return []
    if backend == "devcontainer":
        if val is False or (isinstance(val, str) and val.strip().lower() in
                            {"0", "false", "no", "off"}):
            return []
        return ["[sandbox] backend=devcontainer defaults to network access — set "
                "allow_network = false or use a deny-by-default backend"]
    if backend == "firecracker":
        network = str(sb.get("network") or "egress-deny").strip().lower()
        if network == "egress-deny":
            return []
        return [f"[sandbox] firecracker network={network!r} can reach the network "
                "— set network = \"egress-deny\""]
    if backend == "ssh":
        return ["[sandbox] backend=ssh uses a remote host with its own network access"]
    if backend == "modal":
        return ["[sandbox] backend=modal runs in a cloud sandbox with network access"]
    if backend.startswith("ep:"):
        return ["[sandbox] entry-point backends cannot be proven air-gapped by "
                "static config inspection"]
    if backend == "local":
        return ["[sandbox] backend=local uses the host network — choose a sandbox "
                "backend with network disabled"]
    return [f"[sandbox] backend={backend!r} is not recognized; air-gap status "
            "cannot be proven"]


__all__ = ["audit"]
