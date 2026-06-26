"""Adversarial platform stress: budget integrity, capability fuzz, dashboard load.

Drives the safety-critical in-process subsystems past their production defaults
and asserts their load-bearing invariants. Companion to mp_jobqueue_stress.py
(dispatch substrate) and the control_data_plane_soak CI gate.

  python3 scripts/stress/adversarial_stress.py
"""
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "maverick-core"))
sys.path.insert(0, str(_REPO / "packages" / "maverick-dashboard"))
os.environ.setdefault("MAVERICK_ENCRYPT_AT_REST", "0")

fails = []


def section(name):
    print(f"\n== {name} ==")


def stress_budget_integrity():
    """32 threads × 5k record_tokens, barrier-synced: no lost updates."""
    section("Budget accounting integrity under contention")
    from maverick.budget import Budget
    b = Budget(max_input_tokens=10**12, max_output_tokens=10**12,
               max_dollars=10**9, max_wall_seconds=10**9, max_tool_calls=10**12)
    n_threads, per = 32, 5000
    barrier = threading.Barrier(n_threads)

    def worker(_):
        barrier.wait()
        for _ in range(per):
            b.record_tokens(1, 1, model="claude-sonnet-4-6")

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        list(ex.map(worker, range(n_threads)))
    expected = n_threads * per
    ok = b.input_tokens == expected and b.output_tokens == expected
    print(f"  expected={expected} input={b.input_tokens} output={b.output_tokens} "
          f"{'OK' if ok else 'LOST UPDATES'}")
    if not ok:
        fails.append("budget lost updates under contention")


def stress_budget_cap():
    """16 threads racing a small cap: the cap must fire (no silent overshoot)."""
    section("Budget cap fires under concurrency")
    from maverick.budget import Budget, BudgetExceeded
    cap = 10000
    b = Budget(max_output_tokens=cap, max_input_tokens=10**12,
               max_dollars=10**9, max_wall_seconds=10**9, max_tool_calls=10**12)
    raised = [0]
    lock = threading.Lock()

    def worker(_):
        for _ in range(2000):
            try:
                b.record_tokens(0, 10, model="claude-sonnet-4-6")
            except BudgetExceeded:
                with lock:
                    raised[0] += 1
                return

    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(worker, range(16)))
    fired = raised[0] > 0
    print(f"  cap={cap} final_output={b.output_tokens} saw_exceed={raised[0]} "
          f"{'OK (enforced)' if fired else 'CAP NEVER FIRED'}")
    if not fired:
        fails.append("budget cap never fired under concurrency")


def stress_capability_fuzz(seeds=200, rounds=2000):
    """Hunt for any authorization leak across many seeds at high round counts."""
    section(f"Capability authorization fuzz ({seeds} seeds × {rounds} rounds)")
    from maverick.capability import Capability
    from maverick.capability_fuzzer import fuzz
    granted = {"fs.read", "fs.write", "shell.exec", "web_search", "http_fetch"}
    cap = Capability(principal="fuzzer", allow_tools=frozenset(granted),
                     deny_tools=frozenset({"shell.exec.sudo"}))
    total_probes = total_leaks = 0
    for seed in range(seeds):
        r = fuzz(cap, granted, seed=seed, rounds=rounds)
        total_probes += r.probes
        total_leaks += len(r.leaks)
        for probe, why in r.leaks[:3]:
            print(f"  LEAK seed={seed}: permits({probe!r}) -> {why}")
    print(f"  {total_probes} probes, {total_leaks} leaks "
          f"{'OK' if total_leaks == 0 else 'LEAK'}")
    if total_leaks:
        fails.append(f"capability boundary leaked ({total_leaks} probes)")


def stress_dashboard(n=3000):
    """Concurrent probe storm against the auth-exempt health endpoints."""
    section(f"Dashboard concurrent load ({n} probes)")
    try:
        from fastapi.testclient import TestClient
        from maverick_dashboard.app import app
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP dashboard ({e!r})")
        return
    client = TestClient(app, headers={"Origin": "http://testserver"})
    paths = ["/healthz", "/livez", "/readyz"]
    codes = {}
    errors = [0]
    lock = threading.Lock()

    def hit(i):
        p = paths[i % len(paths)]
        try:
            r = client.get(p)
            with lock:
                codes[(p, r.status_code)] = codes.get((p, r.status_code), 0) + 1
        except Exception:  # noqa: BLE001
            with lock:
                errors[0] += 1

    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(hit, range(n)))
    print(f"  codes={codes} exceptions={errors[0]}")
    if errors[0]:
        fails.append(f"dashboard raised {errors[0]} exceptions under load")


if __name__ == "__main__":
    stress_budget_integrity()
    stress_budget_cap()
    stress_capability_fuzz()
    stress_dashboard()
    print("\n=== SUMMARY ===")
    if fails:
        for f in fails:
            print(f"  FAIL: {f}")
        raise SystemExit(1)
    print("  all adversarial invariants held")
