"""Run-scoped agent quarantine -- the containment half of agent compartments.

The threat ledger (``maverick_shield.compartment``) is the *immunity* half: it
shares one agent's caught signature so the rest of the swarm bounces the same
attack (Rung 0). This module is the *containment* half (Rung 1): when an agent
shows signs of actual compromise -- a critical-severity shield block, or
repeated blocks -- it is "sealed off like a submarine door." A sealed agent:

  * runs no further tools (its calls are refused in ``Agent._run_tool``), and
  * has its blackboard posts withheld from siblings and the orchestrator (see
    ``Blackboard.render``), so a poisoned finding it already posted can't steer
    the rest of the swarm.

Run-scoped, in-memory, and OFF unless ``[safety] compartments`` is enabled. The
trigger is deliberately conservative: most shield blocks are deflected probes,
not compromise, so a single sub-critical block only immunizes (Rung 0) -- it
does NOT seal the agent. Promotion to a seal is a privileged step taken here
(driven from the agent's own chokepoint), never by an agent broadcasting about
its peers. Fail-open: a bug in here must never crash the agent loop.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Seal an agent once it has tripped the shield this many times in a run, even
# below critical severity: a repeat offender is stuck in attacker-controlled
# territory, not deflecting a one-off probe.
_STRIKE_SEAL_THRESHOLD = 2


@dataclass
class QuarantineRegistry:
    """Run-scoped, swarm-shared record of sealed agents (compartment Rung 1)."""

    _sealed: dict[str, str] = field(default_factory=dict)   # agent -> reason
    _strikes: dict[str, int] = field(default_factory=dict)  # agent -> block count
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def seal(self, agent: str, reason: str) -> None:
        with self._lock:
            self._sealed.setdefault(agent, reason)

    def is_sealed(self, agent: str) -> bool:
        with self._lock:
            return agent in self._sealed

    def reason(self, agent: str) -> str | None:
        with self._lock:
            return self._sealed.get(agent)

    def record_strike(self, agent: str) -> int:
        """Count a shield block against ``agent``; return its running total."""
        with self._lock:
            n = self._strikes.get(agent, 0) + 1
            self._strikes[agent] = n
            return n

    @property
    def sealed_agents(self) -> list[str]:
        with self._lock:
            return list(self._sealed)


def triage_block(
    registry: QuarantineRegistry, agent: str, severity: str, reason: str
) -> bool:
    """Decide whether a shield block should SEAL the agent (compartment Rung 1).

    Conservative: seal on a critical-severity block, or once the agent is a
    repeat offender (>= threshold blocks this run). Lower-severity one-off
    blocks only immunize (Rung 0). Returns True iff the agent was sealed.
    Fail-open -- never raises into the caller.
    """
    try:
        strikes = registry.record_strike(agent)
        if severity == "critical" or strikes >= _STRIKE_SEAL_THRESHOLD:
            registry.seal(agent, f"{reason} (severity={severity}, strikes={strikes})")
            log.warning("compartment: sealed agent %s after block: %s", agent, reason)
            return True
    except Exception:  # pragma: no cover -- containment must never break the loop
        pass
    return False
