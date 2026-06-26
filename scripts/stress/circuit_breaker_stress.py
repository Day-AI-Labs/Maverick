"""Circuit-breaker state-machine stress.

Two invariants under heavy concurrency:
  1. CLOSED -> OPEN exactly when consecutive_failures crosses the threshold.
  2. HALF_OPEN admits EXACTLY ONE probe; all other concurrent callers fast-fail
     (the documented re-storm guard). This is the race-prone one.
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "maverick-core"))
os.environ.setdefault("MAVERICK_ENCRYPT_AT_REST", "0")

from maverick.circuit_breaker import CircuitBreaker, CircuitOpen, CircuitState  # noqa: E402

fails = []


def stress_open_threshold():
    print("\n== CLOSED -> OPEN at threshold under concurrent failures ==")
    for trial in range(200):
        cb = CircuitBreaker(f"t{trial}", failure_threshold=5, cooldown_seconds=60)

        def boom():
            raise RuntimeError("x")

        # Fire many concurrent failing calls; once >=5 consecutive land, OPEN.
        with ThreadPoolExecutor(max_workers=16) as ex:
            list(ex.map(lambda _, cb=cb: _safe(cb, boom), range(40)))
        if cb.state is not CircuitState.OPEN:
            fails.append(f"trial {trial}: not OPEN after 40 failures")
            break
    print(f"  200 trials -> {'OK (all opened)' if not fails else fails[-1]}")


def _half_open_trial(trial, workers=12):
    """One HALF_OPEN trial: trip OPEN, wait out cooldown, then storm with
    `workers` concurrent callers. Returns the number of probes admitted."""
    cb = CircuitBreaker(f"h{trial}", failure_threshold=1, cooldown_seconds=0.02)
    _safe(cb, lambda: (_ for _ in ()).throw(RuntimeError("x")))  # trip OPEN
    assert cb.state in (CircuitState.OPEN, CircuitState.HALF_OPEN)
    time.sleep(0.03)  # let cooldown elapse -> next call probes

    admitted = []
    admit_lock = threading.Lock()
    start = threading.Barrier(workers)

    def fn():
        with admit_lock:
            admitted.append(1)
        time.sleep(0.005)  # hold the probe so concurrents collide
        return "ok"

    def probe(_):
        start.wait()
        try:
            cb.call(fn)
        except (CircuitOpen, RuntimeError):
            pass

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(probe, range(workers)))
    return len(admitted)


def stress_half_open_single_probe():
    print("\n== HALF_OPEN admits exactly ONE probe under concurrency ==")
    violations = sum(1 for trial in range(300) if _half_open_trial(trial) != 1)
    msg = "OK (exactly one probe each)" if violations == 0 else f"{violations}/300 admitted !=1 probe"
    print(f"  300 trials -> {msg}")
    if violations:
        fails.append(f"HALF_OPEN admitted multiple probes in {violations} trials")


def stress_concurrent_record():
    print("\n== concurrent record_success/record_failure keeps state legal ==")
    cb = CircuitBreaker("mix", failure_threshold=5, cooldown_seconds=0.01)
    bad = [0]

    def churn(i):
        for _ in range(2000):
            if i % 2:
                cb.record_failure()
            else:
                cb.record_success()
            s = cb.state
            if s not in (CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN):
                bad[0] += 1

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(churn, range(12)))
    print(f"  24k mixed ops -> illegal states={bad[0]} {'OK' if bad[0] == 0 else 'BAD'}")
    if bad[0]:
        fails.append("illegal circuit state observed")


def _safe(cb, fn):
    try:
        cb.call(fn)
    except (CircuitOpen, RuntimeError):
        pass


if __name__ == "__main__":
    stress_open_threshold()
    stress_half_open_single_probe()
    stress_concurrent_record()
    print("\n=== SUMMARY ===")
    if fails:
        for f in fails:
            print(f"  FAIL: {f}")
        raise SystemExit(1)
    print("  circuit-breaker invariants held")
