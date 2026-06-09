"""The proof harness must stay green in CI: every product guarantee holds on the
REAL roster + enforcement code. In CI (cryptography present) this also exercises
the two Ed25519 guarantees -- verified peer handoffs and the tamper-evident audit
ledger -- so all seven run. See proof/run_proof.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_proof_of_guarantees_passes():
    repo = Path(__file__).resolve().parents[3]
    script = repo / "proof" / "run_proof.py"
    assert script.exists(), f"proof harness missing at {script}"
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, f"a guarantee failed:\n{r.stdout}\n{r.stderr}"
    # the five always-on guarantees must have run and passed
    assert r.stdout.count("[PASS]") >= 5, r.stdout
    assert "[FAIL]" not in r.stdout, r.stdout
