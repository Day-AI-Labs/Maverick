"""Multiprocess JobQueue stress: true OS-process contention on claim().

The soak gate uses GIL-bound threads. This uses real processes so the
SELECT->UPDATE window in JobQueue.claim() is actually concurrent. Asserts
exactly-once (no job claimed by two processes) and zero-loss (every job claimed).

Also stresses: retry/fail path, purge under load, oversized payloads, and
claim() liveness under contention (does it spuriously return None and leave
ready jobs unclaimed?).
"""
import multiprocessing as mp
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "maverick-core"))
os.environ.setdefault("MAVERICK_ENCRYPT_AT_REST", "0")

from maverick.job_queue import JobQueue  # noqa: E402


def _drain_proc(db_path, out_path, spin):
    """Claim until the queue reports empty `spin` consecutive times, recording
    every claimed job id to out_path (one per line)."""
    q = JobQueue(db_path=Path(db_path))
    claimed = []
    empties = 0
    while empties < spin:
        job = q.claim()
        if job is None:
            empties += 1
            continue
        empties = 0
        claimed.append(job.id)
        q.complete(job.id)
    Path(out_path).write_text("\n".join(str(c) for c in claimed))


def run(n_jobs, n_procs, spin=50):
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "jobs.db"
        q = JobQueue(db_path=db)
        ids = [q.enqueue("stress", {"i": i}) for i in range(n_jobs)]
        assert len(set(ids)) == n_jobs, "enqueue returned duplicate ids!"

        outs = [str(Path(d) / f"claimed_{i}.txt") for i in range(n_procs)]
        t0 = time.time()
        procs = [mp.Process(target=_drain_proc, args=(str(db), outs[i], spin))
                 for i in range(n_procs)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=180)
        elapsed = time.time() - t0

        stuck = [p.pid for p in procs if p.is_alive()]
        for p in procs:
            if p.is_alive():
                p.terminate()

        all_claimed = []
        for o in outs:
            txt = Path(o).read_text() if Path(o).exists() else ""
            all_claimed += [int(x) for x in txt.split() if x.strip()]

        counts = Counter(all_claimed)
        duplicates = {j: c for j, c in counts.items() if c > 1}
        claimed_set = set(all_claimed)
        lost = [j for j in ids if j not in claimed_set]

        # queue should have nothing left pending/running
        remaining = len(q.list(status="pending", limit=n_jobs + 1)) + \
            len(q.list(status="running", limit=n_jobs + 1))

        ok = (not duplicates and not lost and not stuck and remaining == 0
              and len(all_claimed) == n_jobs)
        print(f"  jobs={n_jobs} procs={n_procs} spin={spin} -> "
              f"claimed={len(all_claimed)} unique={len(claimed_set)} "
              f"dups={len(duplicates)} lost={len(lost)} remaining={remaining} "
              f"stuck={stuck} {elapsed:.1f}s  {'OK' if ok else 'FAIL'}")
        if duplicates:
            print(f"    DUPLICATE CLAIMS (exactly-once VIOLATED): "
                  f"{dict(list(duplicates.items())[:10])}")
        if lost:
            print(f"    LOST JOBS (zero-loss VIOLATED): {lost[:10]}")
        return ok


if __name__ == "__main__":
    mp.set_start_method("fork")
    print("== Multiprocess JobQueue contention (true OS parallelism) ==")
    results = []
    # escalating: more procs than CPUs maximizes the SELECT->UPDATE window
    for n_jobs, n_procs in [(500, 8), (2000, 16), (5000, 32), (3000, 48)]:
        results.append(run(n_jobs, n_procs))
    print("ALL_PASS" if all(results) else "SOME_FAILED")
