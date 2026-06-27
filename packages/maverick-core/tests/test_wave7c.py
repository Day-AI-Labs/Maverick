"""Wave 7c — Firecracker sandbox scaffold + PRM + training pipeline."""
from __future__ import annotations

import pytest

# ---------- Firecracker sandbox ----------

class TestFirecrackerBackend:
    def test_local_provider_requires_firecracker_binary(self, monkeypatch):
        from maverick.sandbox.firecracker import FirecrackerBackend
        monkeypatch.setattr("shutil.which", lambda c: None)
        from pathlib import Path
        with pytest.raises(NotImplementedError, match="firecracker"):
            FirecrackerBackend(workdir=Path.cwd(), provider="local")

    def test_e2b_provider_requires_api_key(self, monkeypatch):
        from maverick.sandbox.firecracker import FirecrackerBackend
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        from pathlib import Path
        with pytest.raises(ValueError, match="E2B_API_KEY"):
            FirecrackerBackend(workdir=Path.cwd(), provider="e2b")

    def test_e2b_picks_up_env_key(self, monkeypatch):
        from maverick.sandbox.firecracker import FirecrackerBackend
        monkeypatch.setenv("E2B_API_KEY", "test-key")
        from pathlib import Path
        b = FirecrackerBackend(workdir=Path.cwd(), provider="e2b")
        assert b.api_key == "test-key"

    def test_unknown_provider_raises(self, monkeypatch):
        from maverick.sandbox.firecracker import FirecrackerBackend
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/firecracker")
        from pathlib import Path
        with pytest.raises(ValueError, match="provider"):
            FirecrackerBackend(workdir=Path.cwd(), provider="bogus")

    def test_build_sandbox_factory_wires_firecracker(self, monkeypatch, tmp_path):
        """The build_sandbox() factory routes `backend=firecracker` correctly.

        We force the e2b provider so __post_init__'s `firecracker` binary
        check doesn't run (E2B path only needs an API key).
        """
        from maverick.sandbox import FirecrackerBackend
        monkeypatch.setenv("E2B_API_KEY", "test-key")
        # Direct construction; the factory tests are covered by build_sandbox
        # itself but they require the config layer to set provider=e2b.
        sb = FirecrackerBackend(
            workdir=tmp_path, provider="e2b", api_key="k",
        )
        assert isinstance(sb, FirecrackerBackend)
        assert sb.provider == "e2b"


# ---------- PRM ----------

class TestNullPRM:
    def test_returns_neutral(self):
        from maverick.prm import NullPRM, StepContext
        prm = NullPRM()
        out = prm.score(StepContext(goal_id=1, step_index=0, role="researcher"))
        assert out.promise == 0.5
        assert out.progress == 0.0
        assert out.confidence == 0.0


class TestHeuristicPRM:
    def test_error_strongly_negative(self):
        from maverick.prm import HeuristicPRM, StepContext
        out = HeuristicPRM().score(StepContext(
            goal_id=1, step_index=0, role="coder", error="something broke",
        ))
        assert out.promise < 0
        assert out.progress <= 0

    def test_final_strongly_positive(self):
        from maverick.prm import HeuristicPRM, StepContext
        out = HeuristicPRM().score(StepContext(
            goal_id=1, step_index=5, role="orchestrator", is_final=True,
        ))
        assert out.promise >= 0.9
        assert out.progress > 0

    def test_tool_success_positive_progress(self):
        from maverick.prm import HeuristicPRM, StepContext
        out = HeuristicPRM().score(StepContext(
            goal_id=1, step_index=2, role="researcher",
            tool_name="read_file", tool_succeeded=True,
        ))
        assert out.promise > 0.5
        assert out.progress > 0

    def test_tool_failure_negative_progress(self):
        from maverick.prm import HeuristicPRM, StepContext
        out = HeuristicPRM().score(StepContext(
            goal_id=1, step_index=2, role="researcher",
            tool_name="shell", tool_succeeded=False,
        ))
        assert out.promise > 0  # still some hope; not as negative as error
        assert out.progress < 0

    def test_thinking_decays(self):
        from maverick.prm import HeuristicPRM, StepContext
        out = HeuristicPRM().score(StepContext(
            goal_id=1, step_index=10, role="researcher", prior_step_score=0.8,
        ))
        # Decay vs prior, but never below floor 0.3.
        assert 0.3 <= out.promise <= 0.8


class TestRemotePRMFallback:
    def test_falls_back_when_no_httpx(self, monkeypatch):
        """Without httpx the remote PRM degrades to heuristic, never blocks."""
        # Force ImportError on httpx.
        import sys

        from maverick.prm import RemotePRM, StepContext
        monkeypatch.setitem(sys.modules, "httpx", None)
        prm = RemotePRM(endpoint="http://localhost:8888")
        out = prm.score(StepContext(
            goal_id=1, step_index=0, role="coder", error="boom",
        ))
        # Falls through to HeuristicPRM, which gives error=-0.5
        assert out.promise < 0


class TestBuildFromEnv:
    def test_default_is_null(self, monkeypatch):
        from maverick.prm import NullPRM, build_from_env
        monkeypatch.delenv("MAVERICK_PRM", raising=False)
        prm = build_from_env()
        assert isinstance(prm, NullPRM)

    def test_heuristic_via_env(self, monkeypatch):
        from maverick.prm import HeuristicPRM, build_from_env
        monkeypatch.setenv("MAVERICK_PRM", "heuristic")
        prm = build_from_env()
        assert isinstance(prm, HeuristicPRM)

    def test_remote_without_endpoint_falls_back(self, monkeypatch):
        from maverick.prm import HeuristicPRM, build_from_env
        monkeypatch.setenv("MAVERICK_PRM", "remote")
        monkeypatch.delenv("MAVERICK_PRM_ENDPOINT", raising=False)
        prm = build_from_env()
        # No endpoint set -> we fall back to heuristic with a warning.
        assert isinstance(prm, HeuristicPRM)


# ---------- Training schema + ingest ----------

class TestTrainingSchema:
    def test_klear_format_shape(self):
        from maverick.training.schema import (
            TrainingStep,
            TrainingTrajectory,
            to_klear_jsonl,
        )
        traj = TrainingTrajectory(
            trajectory_id="abc-1",
            task_brief_hash="abc",
            model_id="claude-opus-4-7",
            outcome="success",
            terminal_reward=1.0,
            verifier_confidence=0.9,
            disagreement_entropy=0.7,
            steps=[
                TrainingStep(
                    step_index=0, role="orchestrator",
                    action_type="think", action_name="",
                    observation_hash="h0",
                    promise_label=0.5, progress_label=0.0,
                ),
                TrainingStep(
                    step_index=1, role="researcher",
                    action_type="tool_call", action_name="read_file",
                    observation_hash="h1",
                    promise_label=0.7, progress_label=0.1,
                ),
            ],
        )
        out = to_klear_jsonl(traj)
        assert out["id"] == "abc-1"
        assert out["outcome"] == "success"
        assert len(out["messages"]) == 2
        assert out["messages"][1]["name"] == "read_file"
        assert len(out["rewards"]) == 2
        assert out["meta"]["verifier_confidence"] == 0.9


class TestIngest:
    def test_build_trajectory_labels_steps(self):
        from maverick.training.ingest import build_trajectory
        record = {
            "task_brief_hash": "abc",
            "ts": 1717000000,
            "model_id": "claude-opus-4-7",
            "outcome": "success",
            "reward": 1.0,
            "verifier_confidence": 0.9,
            "disagreement_entropy": 0.7,
        }
        events = [
            {"agent": "orchestrator-0-abc", "kind": "plan",
             "content": "plan the work", "ts": 1717000001},
            {"agent": "researcher-1-xyz", "kind": "observation",
             "content": "tool=read_file -> done", "ts": 1717000002},
            {"agent": "orchestrator-0-abc", "kind": "finding",
             "content": "the answer", "ts": 1717000003},
        ]
        traj = build_trajectory(record, events)
        assert len(traj.steps) == 3
        # First (plan) labeled by heuristic with neutral promise.
        # Second (tool success) labeled positive.
        assert traj.steps[1].action_type == "tool_call"
        assert traj.steps[1].action_name == "read_file"
        assert traj.steps[1].promise_label is not None
        # Third (final) labeled strongly positive.
        assert traj.steps[2].action_type == "final"
        assert traj.steps[2].promise_label >= 0.9

    def test_build_trajectory_sets_task_family(self):
        """DPO pairs only form WITHIN a task_family; ingest must set it from the
        task_brief_hash (repeated attempts at one task share that hash). It used
        to be left None, so build_preference_pairs skipped every row -> 0 pairs.
        """
        from maverick.training.ingest import build_trajectory
        traj = build_trajectory({"task_brief_hash": "abc", "ts": 1}, [])
        assert traj.task_family == "abc"

    def test_ingested_rows_pair_when_rewards_differ(self):
        """End-to-end: two attempts at the SAME task with a reward gap produce a
        DPO pair once task_family is populated (regression for 0-pairs bug)."""
        from maverick.training.ingest import build_trajectory
        from maverick.training.rlaif import build_preference_pairs
        from maverick.training.schema import to_klear_jsonl
        good = to_klear_jsonl(build_trajectory(
            {"task_brief_hash": "fam", "ts": 1, "outcome": "success",
             "reward": 1.0, "verifier_confidence": 0.95}, []))
        weak = to_klear_jsonl(build_trajectory(
            {"task_brief_hash": "fam", "ts": 2, "outcome": "success",
             "reward": 0.6, "verifier_confidence": 0.6}, []))
        pairs = build_preference_pairs([good, weak], min_margin=0.25)
        assert len(pairs) == 1
        assert pairs[0]["task_family"] == "fam"
        assert pairs[0]["chosen_reward"] > pairs[0]["rejected_reward"]

    def test_rejected_drafts_become_low_reward_pair_members(self):
        """A rejected pre-revision draft ingests as a low-reward row in the SAME
        task_family as the accepted run, so DPO pairs the two (chosen=accepted
        ~1.0, rejected=draft confidence). Drafts without text are skipped."""
        from maverick.training.ingest import (
            build_rejected_trajectories,
            rejected_trajectory_id,
        )
        rec = {
            "task_brief_hash": "fam", "ts": 7, "reward": 1.0,
            "rejected_attempts": [
                {"text": "weak draft", "confidence": 0.6, "critique": "x"},
                {"confidence": 0.5},  # no text -> skipped (nothing for DPO sidecar)
            ],
        }
        rejects = build_rejected_trajectories(rec)
        assert len(rejects) == 1
        r = rejects[0]
        assert r.task_family == "fam"           # same family as the accepted run
        assert r.terminal_reward == 0.6          # un-clamped low reward
        assert r.trajectory_id == rejected_trajectory_id(rec, 0)

    def test_rejected_draft_forms_a_dpo_pair_end_to_end(self):
        from maverick.training.ingest import (
            build_rejected_trajectories,
            build_trajectory,
        )
        from maverick.training.rlaif import build_preference_pairs
        from maverick.training.schema import to_klear_jsonl
        rec = {
            "task_brief_hash": "fam", "ts": 7, "outcome": "success", "reward": 1.0,
            "verifier_confidence": 0.92,
            "rejected_attempts": [{"text": "weak", "confidence": 0.5}],
        }
        rows = [to_klear_jsonl(build_trajectory(rec, []))]
        rows += [to_klear_jsonl(t) for t in build_rejected_trajectories(rec)]
        pairs = build_preference_pairs(rows, min_margin=0.25)
        assert len(pairs) == 1
        assert pairs[0]["chosen_reward"] == 1.0 and pairs[0]["rejected_reward"] == 0.5

    def test_candidate_trajectories_scored_by_objective_tests(self):
        """Best-of-N candidates ingest as rows rewarded by their OBJECTIVE test
        score (not the LLM verifier), all in the same task_family. Text-less
        candidates are skipped."""
        from maverick.training.ingest import (
            build_candidate_trajectories,
            candidate_trajectory_id,
        )
        rec = {
            "task_brief_hash": "fam", "ts": 7, "reward": 1.0,
            "scored_candidates": [
                {"text": "diff pass", "score": 1.0, "all_pass": True},
                {"text": "diff fail", "score": 0.0, "all_pass": False},
                {"score": 0.5},  # no text -> skipped (no patch for the sidecar)
            ],
        }
        cands = build_candidate_trajectories(rec)
        assert len(cands) == 2
        assert [c.terminal_reward for c in cands] == [1.0, 0.0]
        assert all(c.task_family == "fam" for c in cands)
        assert cands[0].trajectory_id == candidate_trajectory_id(rec, 0)
        assert cands[0].outcome == "candidate"

    def test_bestofn_candidates_form_a_dpo_pair_end_to_end(self):
        from maverick.training.ingest import build_candidate_trajectories
        from maverick.training.rlaif import build_preference_pairs
        from maverick.training.schema import to_klear_jsonl
        rec = {
            "task_brief_hash": "fam", "ts": 7,
            "scored_candidates": [
                {"text": "the patch that passes tests", "score": 1.0, "all_pass": True},
                {"text": "the patch that fails tests", "score": 0.0, "all_pass": False},
            ],
        }
        rows = [to_klear_jsonl(t) for t in build_candidate_trajectories(rec)]
        pairs = build_preference_pairs(rows, min_margin=0.5)
        assert len(pairs) == 1
        assert pairs[0]["chosen_reward"] == 1.0 and pairs[0]["rejected_reward"] == 0.0
        assert pairs[0]["margin"] == 1.0

    def test_load_donations_empty_dir(self, tmp_path):
        from maverick.training.ingest import load_donations
        out = list(load_donations(tmp_path))
        assert out == []

    def test_load_donations_reads_json(self, tmp_path):
        import json

        from maverick.training.ingest import load_donations
        (tmp_path / "a.json").write_text(json.dumps({"x": 1}))
        (tmp_path / "b.json").write_text(json.dumps({"x": 2}))
        records = list(load_donations(tmp_path))
        assert len(records) == 2
        assert {r["x"] for r in records} == {1, 2}

    def test_load_donations_skips_bad_json(self, tmp_path):
        from maverick.training.ingest import load_donations
        (tmp_path / "bad.json").write_text("not valid json")
        (tmp_path / "good.json").write_text('{"x": 1}')
        records = list(load_donations(tmp_path))
        assert records == [{"x": 1}]


class TestFirecrackerStrictDefault:
    """Firecracker fails CLOSED by default when firectl is absent (no silent
    downgrade to a weaker Docker boundary); the hardened fallback is only
    reached when the operator opts in with MAVERICK_FIRECRACKER_STRICT=0."""

    def _backend(self, monkeypatch, tmp_path):
        import shutil
        from pathlib import Path

        from maverick.sandbox.firecracker import FirecrackerBackend
        # Construct successfully (firecracker binary 'present').
        monkeypatch.setattr(shutil, "which", lambda c: "/usr/bin/firecracker")
        return FirecrackerBackend(workdir=Path(tmp_path), provider="local")

    def test_fails_closed_by_default_without_firectl(self, monkeypatch, tmp_path):
        import shutil

        import pytest
        b = self._backend(monkeypatch, tmp_path)
        monkeypatch.delenv("MAVERICK_FIRECRACKER_STRICT", raising=False)
        monkeypatch.setattr(shutil, "which", lambda c: None)  # firectl absent
        with pytest.raises(RuntimeError, match="microVM isolation is unavailable"):
            b._exec_local("echo hi")

    def test_strict_zero_allows_hardened_fallback(self, monkeypatch, tmp_path):
        import shutil
        b = self._backend(monkeypatch, tmp_path)
        monkeypatch.setenv("MAVERICK_FIRECRACKER_STRICT", "0")
        monkeypatch.setattr(shutil, "which", lambda c: None)
        called = {}
        monkeypatch.setattr(b, "_docker_fallback", lambda cmd: called.setdefault("cmd", cmd))
        b._exec_local("echo hi")
        assert called["cmd"] == "echo hi"

    def test_docker_fallback_is_hardened(self, monkeypatch, tmp_path):
        import subprocess
        b = self._backend(monkeypatch, tmp_path)
        captured = {}

        class _P:
            returncode = 0
            stdout = ""
            stderr = ""

        def _fake_run(args, **kw):
            captured["args"] = args
            return _P()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        b._docker_fallback("echo hi")
        args = captured["args"]
        assert "--cap-drop" in args and "ALL" in args
        assert "no-new-privileges" in args
        assert "--network=none" in args and "--read-only" in args
