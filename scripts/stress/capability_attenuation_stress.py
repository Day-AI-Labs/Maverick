"""Capability attenuation property test: children can NEVER escalate.

The core authz invariant (Capability.attenuate docstring): every tool/path/host
the attenuated child permits is ALSO permitted by the parent. This generates
thousands of random parents, random attenuations, multi-level chains, and
intersections, and asserts the invariant against a wide tool/path/host universe.
A single violation is a privilege-escalation bug.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "maverick-core"))

from maverick.capability import Capability  # noqa: E402

TOOLS = [
    "read_file", "write_file", "shell", "web_search", "http_fetch", "sql_query",
    "send_message", "spawn_subagent", "spawn_swarm", "ask_user", "delegate_to_agent",
    "browser", "code_exec", "knowledge_search", "apply_patch", "str_edit",
    "send_to_agent", "recv_from_agent", "list_specialists", "spawn_specialist",
    "shell.exec.sudo", "unknown_tool_xyz", "another_unknown",
]
PATHS = ["/etc/passwd", "/home/u/a.txt", "/srv/data/x", "/tmp/y", "/var/log/z", "C:/win"]
HOSTS = ["example.com", "169.254.169.254", "localhost", "api.internal", "evil.test"]
RISKS = [None, "low", "medium", "high"]
TOOLSET = frozenset(TOOLS)


def _lcg(seed):
    x = (seed * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
    while True:
        x = (x * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        yield (x >> 17)


def _subset(rng, items, p_empty=0.25):
    if next(rng) % 100 < p_empty * 100:
        return frozenset()  # empty == "all"
    return frozenset(t for t in items if next(rng) % 2)


def _random_cap(rng, principal):
    return Capability(
        principal=principal,
        allow_tools=_subset(rng, TOOLS),
        deny_tools=_subset(rng, TOOLS, p_empty=0.5),
        max_risk=RISKS[next(rng) % len(RISKS)],
        allow_paths=_subset(rng, PATHS),
        allow_hosts=_subset(rng, HOSTS),
    )


def _violations(parent, child):
    """Anything the child permits that the parent does not = escalation."""
    bad = []
    for t in TOOLS:
        if child.permits(t) and not parent.permits(t):
            bad.append(("tool", t))
    for p in PATHS:
        if child.permits_path(p) and not parent.permits_path(p):
            bad.append(("path", p))
    for h in HOSTS:
        if child.permits_host(h) and not parent.permits_host(h):
            bad.append(("host", h))
    return bad


def run(n=40000):
    fails = []
    for it in range(n):
        rng = _lcg(it + 1)
        parent = _random_cap(rng, "agent:parent-0")

        # 1) single attenuation
        child = parent.attenuate(
            principal="agent:child-1",
            allow=_subset(rng, TOOLS) or None,
            deny=_subset(rng, TOOLS, p_empty=0.6) or None,
            max_risk=RISKS[next(rng) % len(RISKS)],
            allow_paths=_subset(rng, PATHS) or None,
            allow_hosts=_subset(rng, HOSTS) or None,
        )
        v = _violations(parent, child)
        if v:
            fails.append((it, "attenuate", v[:4]))
            break

        # 2) chain: grandchild must not exceed the ORIGINAL parent
        grand = child.attenuate(
            principal="agent:grand-2",
            allow=_subset(rng, TOOLS) or None,
            deny=_subset(rng, TOOLS, p_empty=0.7) or None,
            max_risk=RISKS[next(rng) % len(RISKS)],
        )
        v = _violations(parent, grand) + _violations(child, grand)
        if v:
            fails.append((it, "chain", v[:4]))
            break

        # 3) intersection must not exceed EITHER operand
        other = _random_cap(rng, "agent:peer-0")
        inter = parent.intersect(other, principal="agent:inter-1")
        v = _violations(parent, inter) + _violations(other, inter)
        if v:
            fails.append((it, "intersect", v[:4]))
            break

    print(f"  {n} random parents x (attenuate + chain + intersect), "
          f"{len(TOOLS)} tools + {len(PATHS)} paths + {len(HOSTS)} hosts each")
    if fails:
        for it, kind, v in fails:
            print(f"  ESCALATION at iter {it} ({kind}): {v}")
        return False
    print("  OK — no child ever escalated past its parent")
    return True


if __name__ == "__main__":
    print("== Capability attenuation: children cannot escalate ==")
    ok = run()
    print("\n=== SUMMARY ===")
    print("  attenuation invariant held" if ok else "  ESCALATION FOUND")
    raise SystemExit(0 if ok else 1)
