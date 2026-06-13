"""Per-tool network egress policy (allow/deny hosts).

Declarative egress control so a tool can be restricted to a set of hosts:

    [sandbox.tool.http_fetch]
    allow_egress = ["api.github.com", "*.openai.com"]

    [sandbox.tool.shell]
    deny_egress = ["*"]

``host_allowed(tool, host, policy)`` is the pure decision (fnmatch globs; deny
wins over allow; empty/absent policy = allow-all, preserving current behavior).
This module is the *policy layer*; a backend (Docker/Firecracker) enforces it at
the packet level on Linux, and falls back to advisory when the backend can't.
The decision is unit-tested in isolation.
"""
from __future__ import annotations

from fnmatch import fnmatch


def load_policy() -> dict:
    """Read ``[sandbox.tool.<name>]`` egress tables from config (or empty)."""
    try:
        from ..config import load_config
        sb = (load_config() or {}).get("sandbox", {}) or {}
        return sb.get("tool", {}) or {}
    except Exception:  # pragma: no cover -- config never blocks the sandbox
        return {}


def _canonical_dns_name(name: str) -> str:
    """Return a DNS name in policy-comparison form.

    DNS names may be written with a final root-label dot (for example,
    ``example.com.``), but that is equivalent to ``example.com`` for lookup
    purposes.  Canonicalize both request hosts and policy patterns so deny
    rules cannot be bypassed with the fully-qualified spelling.
    """
    value = (name or "").strip().lower()
    value = value.removesuffix(".")
    labels = []
    for label in value.split("."):
        if any(ch in label for ch in "*?["):
            labels.append(label)
            continue
        try:
            labels.append(label.encode("idna").decode("ascii"))
        except UnicodeError:
            labels.append(label)
    return ".".join(labels)


def _matches(host: str, patterns) -> bool:
    h = _canonical_dns_name(host)
    return any(fnmatch(h, _canonical_dns_name(str(p))) for p in (patterns or []))


def host_allowed(tool: str, host: str, policy: dict | None = None) -> bool:
    """True iff ``tool`` may reach ``host`` under ``policy``.

    Rules (deny wins): an explicit ``deny_egress`` match blocks; otherwise, if
    ``allow_egress`` is set, the host must match it; with no policy for the tool,
    egress is allowed (unchanged default behavior).
    """
    pol = policy if policy is not None else load_policy()
    rule = (pol or {}).get(tool) or {}
    if not isinstance(rule, dict):
        return True
    if _matches(host, rule.get("deny_egress")):
        return False
    allow = rule.get("allow_egress")
    if allow:  # non-empty allow-list -> host must be on it
        return _matches(host, allow)
    return True


def describe(tool: str, policy: dict | None = None) -> str:
    """Human summary of a tool's egress rule."""
    pol = policy if policy is not None else load_policy()
    rule = (pol or {}).get(tool) or {}
    if not rule:
        return f"{tool}: egress unrestricted"
    parts = []
    if rule.get("allow_egress"):
        parts.append(f"allow={list(rule['allow_egress'])}")
    if rule.get("deny_egress"):
        parts.append(f"deny={list(rule['deny_egress'])}")
    return f"{tool}: " + (", ".join(parts) or "unrestricted")


__all__ = ["load_policy", "host_allowed", "describe"]
