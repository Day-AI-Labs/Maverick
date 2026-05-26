"""Wave 12 (council F11): operational hardening tests.

Covers:
  - F11a: SIGTERM handler installed + flag plumbing
  - F11b: error rows in CSV are NOT marked done; resume retries them
  - F11e: consecutive-failure circuit breaker
"""
from __future__ import annotations

import csv
import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_sb():
    p = Path(__file__).resolve().parent / "swe_bench.py"
    spec = importlib.util.spec_from_file_location("benchmarks_swe_bench", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmarks_swe_bench"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        if not rows:
            return
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        for r in rows:
            w.writerow(r)


class TestErrorRowsRetried:
    def test_error_row_not_marked_done(self, tmp_path):
        sb = _load_sb()
        csv_path = tmp_path / "results.csv"
        _write_csv(csv_path, [
            {"instance_id": "i1", "pipeline": "maverick",
             "outcome": "success", "predicted_patch": ""},
            {"instance_id": "i2", "pipeline": "maverick",
             "outcome": "error: ConnectionError: 429", "predicted_patch": ""},
            {"instance_id": "i3", "pipeline": "maverick",
             "outcome": "no-diff", "predicted_patch": ""},
        ])
        done = sb.already_done(csv_path)
        # Success and no-diff stay done; error row gets retried.
        assert ("i1", "maverick") in done
        assert ("i3", "maverick") in done
        assert ("i2", "maverick") not in done, (
            "error row should NOT be in the done set; resume must retry it"
        )

    def test_all_success_rows_marked_done(self, tmp_path):
        sb = _load_sb()
        csv_path = tmp_path / "results.csv"
        _write_csv(csv_path, [
            {"instance_id": "i1", "pipeline": "maverick",
             "outcome": "success", "predicted_patch": ""},
            {"instance_id": "i2", "pipeline": "sonnet_single",
             "outcome": "success", "predicted_patch": ""},
        ])
        done = sb.already_done(csv_path)
        assert len(done) == 2

    def test_outcome_with_leading_whitespace_recognized(self, tmp_path):
        sb = _load_sb()
        csv_path = tmp_path / "results.csv"
        _write_csv(csv_path, [
            {"instance_id": "i1", "pipeline": "maverick",
             "outcome": "  error: timeout  ", "predicted_patch": ""},
        ])
        done = sb.already_done(csv_path)
        assert ("i1", "maverick") not in done


class TestSigtermHandler:
    def test_handler_sets_flag(self):
        sb = _load_sb()
        # Reset state from any prior test.
        sb._TERMINATE_REQUESTED = False
        sb._on_sigterm(15, None)
        assert sb._TERMINATE_REQUESTED is True
        sb._TERMINATE_REQUESTED = False

    def test_main_installs_handler(self):
        """Smoke: running --help installs the signal handler without
        crashing."""
        sb_path = Path(__file__).resolve().parent / "swe_bench.py"
        result = subprocess.run(
            [sys.executable, str(sb_path), "--help"],
            capture_output=True, timeout=10,
        )
        assert result.returncode == 0
        assert b"--max-consecutive-failures" in result.stdout, (
            "Wave 12 added a circuit-breaker flag — must surface in --help"
        )


class TestCircuitBreakerFlag:
    def test_flag_in_argparse(self):
        sb_path = Path(__file__).resolve().parent / "swe_bench.py"
        result = subprocess.run(
            [sys.executable, str(sb_path), "--help"],
            capture_output=True, timeout=10,
        )
        out = result.stdout.decode("utf-8", errors="replace")
        assert "--max-consecutive-failures" in out
        # Tip about the why is in the help text.
        assert "consecutive" in out.lower()

    def test_flag_accepts_zero_to_disable(self, tmp_path):
        """--max-consecutive-failures 0 should parse cleanly (it disables
        the breaker for harnesses that intentionally tolerate flaky runs)."""
        manifest = tmp_path / "m.txt"
        manifest.write_text("instance_1\n")
        # Invoke argparse via subprocess to exercise the full CLI.
        sb_path = Path(__file__).resolve().parent / "swe_bench.py"
        env = {"PATH": sys.executable, "MAVERICK_BENCH_DRY_RUN": "1"}
        import os as _os
        env.update(_os.environ)
        env["MAVERICK_BENCH_DRY_RUN"] = "1"
        result = subprocess.run(
            [sys.executable, str(sb_path),
             "--instances", str(manifest),
             "--pipelines", "maverick",
             "--out", str(tmp_path / "out.csv"),
             "--max-consecutive-failures", "0"],
            capture_output=True, timeout=30, env=env,
        )
        # Exit 0 (or any non-2 — 2 is the argparse error code).
        assert result.returncode != 2, (
            f"--max-consecutive-failures 0 must parse cleanly; "
            f"stderr={result.stderr!r}"
        )
