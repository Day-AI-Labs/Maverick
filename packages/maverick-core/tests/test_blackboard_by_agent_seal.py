"""by_agent() must withhold a sealed agent's posts atomically.

User-testing finding: by_agent() checked _is_sealed() OUTSIDE the lock and read
the entries INSIDE it, so a concurrent seal() (e.g. from a FastAPI threadpool)
could slip between the check and the read and leak a just-sealed agent's posts.
The check now happens under the same lock as the read.
"""
from __future__ import annotations

import threading

from maverick.blackboard import Blackboard
from maverick.quarantine import QuarantineRegistry


def test_by_agent_withholds_sealed_agent():
    bb = Blackboard()
    reg = QuarantineRegistry()
    bb.attach_quarantine(reg)
    bb.post("rogue", "observation", "secret finding")
    bb.post("good", "observation", "ok finding")
    assert bb.by_agent("rogue")  # visible before sealing
    reg.seal("rogue", "exfil attempt")
    assert bb.by_agent("rogue") == []          # sealed -> withheld wholesale
    assert len(bb.by_agent("good")) == 1       # other agents unaffected


def test_by_agent_safe_under_concurrent_seal_and_post():
    # Hammer by_agent while another thread posts + seals/unseals; a sealed agent
    # must NEVER leak, and no "list changed size during iteration" may occur.
    bb = Blackboard()
    reg = QuarantineRegistry()
    bb.attach_quarantine(reg)
    stop = threading.Event()
    errors: list[Exception] = []

    def churn():
        i = 0
        while not stop.is_set():
            try:
                bb.post("rogue", "observation", f"f{i}")
                if i % 2 == 0:
                    reg.seal("rogue", "r")
                i += 1
            except Exception as e:  # pragma: no cover
                errors.append(e)

    writer = threading.Thread(target=churn, daemon=True)
    writer.start()
    try:
        for _ in range(3000):
            rows = bb.by_agent("rogue")
            # Whenever the agent is currently sealed, the read must be empty.
            if reg.is_sealed("rogue"):
                assert rows == [], "sealed agent's posts leaked"
    finally:
        stop.set()
        writer.join(timeout=5)
    assert not errors, errors
