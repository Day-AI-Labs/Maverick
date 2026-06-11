"""Reproducible benchmark harness v2 (ROADMAP 2027 H1 Distribution).

Offline + deterministic: a scripted oracle/divergent solver, no LLM, no
network. Asserts the manifest is stable across runs, the signature round-trips,
and the verifier names exactly the task that diverged.
"""
from __future__ import annotations

import json

import pytest
from maverick.benchmarks.reproducible_v2 import (
    MANIFEST_VERSION,
    RunConditions,
    Task,
    build_manifest,
    builtin_suite,
    env_fingerprint,
    main,
    run_suite,
    verify_manifests,
    verify_signature,
)


def _oracle(task: Task, *, seed: int = 0) -> str:
    return task.answer


def _wrong(task: Task, *, seed: int = 0) -> str:
    return "definitely-not-the-answer"


# Flip the answer for exactly one task id -> a single controlled divergence.
def _flaky_on(target_id: str):
    def solve(task: Task, *, seed: int = 0) -> str:
        return "WRONG" if task.task_id == target_id else task.answer
    return solve


def _conditions(**kw) -> RunConditions:
    base = {"seed": 7, "model_id": "fixture/offline", "prompt_template": "do: {q}", "tool_set": ("shell", "write_file")}
    base.update(kw)
    return RunConditions(**base)


class TestRunSuite:
    def test_oracle_is_perfect(self):
        body = run_suite(builtin_suite(), _oracle, _conditions())
        assert body["aggregate"]["pass_at_1"] == 1.0
        assert body["aggregate"]["n"] == len(builtin_suite())
        assert body["version"] == MANIFEST_VERSION

    def test_wrong_is_zero(self):
        body = run_suite(builtin_suite(), _wrong, _conditions())
        assert body["aggregate"]["pass_at_1"] == 0.0
        assert body["aggregate"]["passed"] == 0

    def test_results_sorted_by_task_id(self):
        body = run_suite(builtin_suite(), _oracle, _conditions())
        ids = [r["task_id"] for r in body["results"]]
        assert ids == sorted(ids)

    def test_solver_exception_scored_zero_not_fatal(self):
        def boom(task, *, seed=0):
            if task.task_id == "arith-1":
                raise RuntimeError("kaboom")
            return task.answer
        body = run_suite(builtin_suite(), boom, _conditions())
        bad = next(r for r in body["results"] if r["task_id"] == "arith-1")
        assert bad["score"] == 0.0
        assert "kaboom" in bad["got"]
        # the other tasks still graded fine
        assert body["aggregate"]["passed"] == len(builtin_suite()) - 1

    def test_solver_without_seed_kwarg_tolerated(self):
        def no_seed(task):
            return task.answer
        body = run_suite(builtin_suite(), no_seed, _conditions())
        assert body["aggregate"]["pass_at_1"] == 1.0

    def test_custom_scorer_injected(self):
        # A scorer that always passes -> even a wrong solver scores 1.0.
        body = run_suite(builtin_suite(), _wrong, _conditions(), scorer=lambda t, o: 1.0)
        assert body["aggregate"]["pass_at_1"] == 1.0


class TestDeterminism:
    def test_two_oracle_runs_are_byte_identical_bodies(self):
        a = run_suite(builtin_suite(), _oracle, _conditions())
        b = run_suite(builtin_suite(), _oracle, _conditions())
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_seed_recorded_in_fingerprint(self):
        body = run_suite(builtin_suite(), _oracle, _conditions(seed=99))
        assert body["env_fingerprint"]["seed"] == 99
        assert body["seed"] == 99

    def test_prompt_and_tool_hashes_change_with_inputs(self):
        c1 = _conditions(prompt_template="A")
        c2 = _conditions(prompt_template="B")
        assert c1.prompt_hash() != c2.prompt_hash()
        # tool set hash is order-independent
        assert _conditions(tool_set=("a", "b")).tool_set_hash() == \
            _conditions(tool_set=("b", "a")).tool_set_hash()

    def test_env_fingerprint_has_python_and_hashes(self):
        fp = env_fingerprint(_conditions())
        assert set(fp) >= {"seed", "model_id", "prompt_hash", "tool_set_hash", "python", "implementation"}


class TestSigning:
    def test_signature_round_trips(self):
        m = build_manifest(builtin_suite(), _oracle, _conditions(), secret="topsecret")
        assert m["signature"].startswith("sha256=")
        assert verify_signature(m, "topsecret") is True

    def test_wrong_secret_fails_verification(self):
        m = build_manifest(builtin_suite(), _oracle, _conditions(), secret="topsecret")
        assert verify_signature(m, "other") is False

    def test_tampered_manifest_fails_verification(self):
        m = build_manifest(builtin_suite(), _oracle, _conditions(), secret="topsecret")
        m["results"][0]["got"] = "tampered"
        assert verify_signature(m, "topsecret") is False

    def test_unsigned_manifest_has_null_signature(self):
        m = build_manifest(builtin_suite(), _oracle, _conditions())
        assert m["signature"] is None
        assert verify_signature(m, "anything") is False

    def test_signature_is_stable(self):
        s1 = build_manifest(builtin_suite(), _oracle, _conditions(), secret="k")["signature"]
        s2 = build_manifest(builtin_suite(), _oracle, _conditions(), secret="k")["signature"]
        assert s1 == s2


class TestVerifyManifests:
    def test_identical_runs_reproducible(self):
        a = build_manifest(builtin_suite(), _oracle, _conditions())
        b = build_manifest(builtin_suite(), _oracle, _conditions())
        report = verify_manifests(a, b)
        assert report.reproducible is True
        assert report.diverged_tasks == []

    def test_single_divergence_is_named(self):
        base = build_manifest(builtin_suite(), _oracle, _conditions())
        cur = build_manifest(builtin_suite(), _flaky_on("capital-1"), _conditions())
        report = verify_manifests(base, cur)
        assert report.reproducible is False
        assert len(report.diverged_tasks) == 1
        assert report.diverged_tasks[0]["task_id"] == "capital-1"
        assert report.diverged_tasks[0]["baseline_got"] == "Paris"
        assert report.diverged_tasks[0]["current_got"] == "WRONG"
        assert any("capital-1" in r for r in report.reasons)

    def test_suite_mismatch_flagged_and_not_comparable(self):
        base = build_manifest(builtin_suite(), _oracle, _conditions())
        other = build_manifest([Task("x", "?", "y")], _oracle, _conditions())
        report = verify_manifests(base, other)
        assert report.suite_match is False
        assert report.reproducible is False
        assert any("suite mismatch" in r for r in report.reasons)

    def test_added_and_dropped_tasks_detected(self):
        base = build_manifest(builtin_suite(), _oracle, _conditions())
        cur = build_manifest(builtin_suite(), _oracle, _conditions())
        # Drop one task from current, add a stray one (same suite id is forced
        # by reusing the base body so we isolate the result-set diff).
        cur["results"] = [r for r in cur["results"] if r["task_id"] != "bool-1"]
        cur["results"].append({"task_id": "stray", "score": 1.0, "passed": True, "expected": "z", "got": "z"})
        report = verify_manifests(base, cur)
        assert "bool-1" in report.only_in_baseline
        assert "stray" in report.only_in_current
        assert report.reproducible is False

    def test_env_drift_is_advisory_not_fatal(self):
        base = build_manifest(builtin_suite(), _oracle, _conditions())
        cur = build_manifest(builtin_suite(), _oracle, _conditions())
        cur["env_fingerprint"]["python"] = "9.9.9"
        report = verify_manifests(base, cur)
        # python drift alone does NOT break reproducibility (no task diverged)
        assert report.reproducible is True
        assert "python" in report.env_drift


class TestCLI:
    def test_run_writes_manifest(self, tmp_path, capsys):
        out = tmp_path / "baseline.json"
        rc = main(["run", "--out", str(out), "--seed", "5"])
        assert rc == 0
        manifest = json.loads(out.read_text())
        assert manifest["seed"] == 5
        assert manifest["aggregate"]["pass_at_1"] == 1.0

    def test_run_then_verify_identical_is_zero(self, tmp_path):
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        assert main(["run", "--out", str(a)]) == 0
        assert main(["run", "--out", str(b)]) == 0
        assert main(["--verify", str(a), str(b)]) == 0

    def test_verify_diverged_runs_exit_one(self, tmp_path, monkeypatch):
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        main(["run", "--out", str(a)])
        # Hand-edit b so one task diverges.
        manifest = json.loads(a.read_text())
        manifest["results"][0]["got"] = "changed"
        manifest["results"][0]["score"] = 0.0
        b.write_text(json.dumps(manifest))
        assert main(["--verify", str(a), str(b)]) == 1

    def test_verify_bad_signature_exits_three(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_BENCH_SECRET", "k")
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        main(["run", "--out", str(a)])
        main(["run", "--out", str(b)])
        # Corrupt b's body without re-signing -> signature no longer matches.
        manifest = json.loads(b.read_text())
        manifest["results"][0]["got"] = "tampered"
        b.write_text(json.dumps(manifest))
        assert main(["--verify", str(a), str(b)]) == 3

    def test_secret_via_env_signs_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_BENCH_SECRET", "envkey")
        out = tmp_path / "m.json"
        main(["run", "--out", str(out)])
        manifest = json.loads(out.read_text())
        assert verify_signature(manifest, "envkey") is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
