"""End-to-end integration test: real `run_maverick` flow against a mocked
LLM that returns a recorded SWE-bench-style response.

This is the test class that would have caught the bugs the May 2026
smoke run actually surfaced:

  - WorldModel use-after-close (`world.list_episodes` / `get_goal` /
    `goal_events` called AFTER finally closed the SQLite connection)
  - `resp.text.startswith("FINAL:")` missed FINAL markers preceded by
    reasoning prose
  - `predicted_patch` polluted with trailing `[distilled skill]` +
    `[tokens ...]` metadata
  - `outcome="success"` reported when `predicted_patch` is empty

Run with: `pytest packages/maverick-core/tests/test_integration_swe_smoke.py`

The LLM is mocked; no network calls. The recorded response mirrors what
Sonnet 4.6 / Opus 4.7 actually emitted for psf__requests-1142 in our
May 26 smoke: a "Target: ..." reasoning line followed by `FINAL:` and a
SEARCH/REPLACE block.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Realistic recorded LLM response — model emits reasoning then FINAL.
# Whitespace + indentation matters: SEARCH/REPLACE is byte-exact.
RECORDED_FINAL_RESPONSE = """Target: `foo/bar.py:do_thing` — the unconditional default \
is the bug. Fix: drop the default-init line.

FINAL:

foo/bar.py
<<<<<<< SEARCH
    def do_thing(self, body):
        self.headers['X-Custom'] = 'default'
        if body is not None:
            self.headers['X-Custom'] = str(len(body))
=======
    def do_thing(self, body):
        if body is not None:
            self.headers['X-Custom'] = str(len(body))
>>>>>>> REPLACE
"""


@pytest.fixture
def repo_workdir(tmp_path):
    """Build a tiny git repo with a single bug to fix."""
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "foo").mkdir()
    bar_py = workdir / "foo" / "bar.py"
    bar_py.write_text(
        "class Thing:\n"
        "    def do_thing(self, body):\n"
        "        self.headers['X-Custom'] = 'default'\n"
        "        if body is not None:\n"
        "            self.headers['X-Custom'] = str(len(body))\n",
        encoding="utf-8",
    )
    for cmd in [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
        ["git", "config", "commit.gpgsign", "false"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "init"],
    ]:
        subprocess.run(cmd, cwd=str(workdir), check=True, capture_output=True)
    return workdir


def _load_swe_bench():
    p = Path(__file__).resolve().parents[3] / "benchmarks" / "swe_bench.py"
    spec = importlib.util.spec_from_file_location("sb_integration", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sb_integration"] = mod
    spec.loader.exec_module(mod)
    return mod


class _MockLLMResponse:
    """Mimics the maverick.llm.LLMResponse contract."""

    def __init__(self, text: str, in_tok: int = 1000, out_tok: int = 200):
        self.text = text
        self.thinking = None
        self.tool_calls = []
        self.stop_reason = "end_turn"
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0
        self.raw = None
        self._in_tok = in_tok
        self._out_tok = out_tok


class _MockLLM:
    """Drop-in for maverick.llm.LLM. The agent's first response is the
    recorded FINAL; subsequent calls (verifier, skill distill) return
    a generic FINAL too so the loop terminates cleanly."""

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, *a, **kw):
        self.model = "claude-sonnet-4-6"
        self._call_count = 0
        self._clients = {}
        import threading
        self._clients_lock = threading.Lock()

    def _resp_for(self) -> _MockLLMResponse:
        self._call_count += 1
        if self._call_count == 1:
            return _MockLLMResponse(RECORDED_FINAL_RESPONSE, 13000, 2200)
        # Verifier / skill-distill: accept and stop.
        return _MockLLMResponse(
            'FINAL: {"confidence": 0.95, "accepts": true, '
            '"critique": "ok", "issues": []}',
            500, 50,
        )

    def complete(self, *a, budget=None, model=None, **kw):
        r = self._resp_for()
        if budget is not None:
            budget.record_tokens(r._in_tok, r._out_tok, model=model)
        return r

    async def complete_async(self, *a, **kw):
        return self.complete(*a, **kw)


class TestEndToEndSmoke:
    """The actual integration: run_maverick → agent loop → SR apply →
    render_diff → CSV row. Mocks the LLM; uses a real git repo and the
    real WorldModel."""

    def test_full_pipeline_produces_valid_patch(
        self, repo_workdir, tmp_path, monkeypatch,
    ):
        # Point Maverick at the temp git repo via MAVERICK_CONFIG so
        # test isolation doesn't depend on the runtime HOME (which
        # Python's Path.home() caches in various places).
        config = tmp_path / "config.toml"
        config.write_text(
            f'[sandbox]\nbackend = "local"\nworkdir = "{repo_workdir}"\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("MAVERICK_CONFIG", str(config))
        # Coding mode + opaque so we exercise the real defensive validate
        # + FAIL_TO_PASS flow (without running pytest — empty test list).
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
        monkeypatch.setenv("MAVERICK_USE_SKILLS", "0")
        monkeypatch.setenv("MAVERICK_MAX_STEPS", "5")
        # Don't let the real Anthropic key (if set) sneak in.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        sb = _load_swe_bench()

        # Swap in the mock LLM so no network calls happen.
        with patch.object(sb, "_get_shared_llm", return_value=_MockLLM()):
            row = sb.run_maverick(
                instance_id="test__fixture-1",
                brief="The default X-Custom header should not be set "
                      "unconditionally; only set it when a body is present.",
                fail_to_pass=[],
                pass_to_pass=[],
                gold_patch="",
                language="python",
                base_commit="",  # workdir already at the right state
            )

        # The exact bugs from the May 26 smoke that we now guard against:
        # (a) WorldModel use-after-close — would raise ProgrammingError
        #     and the harness would catch it as "error:" outcome.
        assert "error:" not in row.outcome, (
            f"WorldModel close-then-use bug regressed: outcome={row.outcome}"
        )
        # (b) FINAL-detection on prose-prefixed responses — would leave
        #     predicted_patch empty.
        assert row.predicted_patch, (
            "predicted_patch is empty — FINAL detection regressed "
            "or SR block not applied"
        )
        # (c) The patch is a real unified diff, not raw SR-block text.
        assert "diff --git" in row.predicted_patch or (
            "--- a/" in row.predicted_patch
            and "+++ b/" in row.predicted_patch
        ), f"predicted_patch isn't a unified diff:\n{row.predicted_patch[:300]}"
        # (d) No trailing pollution from skill distill / budget summary.
        assert "[distilled skill" not in row.predicted_patch, (
            "predicted_patch leaked [distilled skill: ...] metadata"
        )
        assert "[tokens in=" not in row.predicted_patch, (
            "predicted_patch leaked [tokens in=...] budget summary"
        )
        # (e) When predicted_patch is non-empty, outcome should be success.
        assert row.outcome == "success", (
            f"non-empty patch should be success; got {row.outcome}"
        )

    def test_empty_patch_reports_no_diff_not_success(
        self, repo_workdir, tmp_path, monkeypatch,
    ):
        """If the agent fails to produce a usable patch, outcome must
        be 'no-diff' so operators can debug — NOT 'success'."""
        config = tmp_path / "config.toml"
        config.write_text(
            f'[sandbox]\nworkdir = "{repo_workdir}"\n', encoding="utf-8",
        )
        monkeypatch.setenv("MAVERICK_CONFIG", str(config))
        monkeypatch.setenv("MAVERICK_CODING_MODE", "1")
        monkeypatch.setenv("MAVERICK_BENCHMARK_OPAQUE", "1")
        monkeypatch.setenv("MAVERICK_MAX_STEPS", "3")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        sb = _load_swe_bench()

        class _NoFinalLLM(_MockLLM):
            def _resp_for(self):
                self._call_count += 1
                # Always returns text without FINAL: marker.
                return _MockLLMResponse(
                    "I'm thinking about this problem.", 100, 20,
                )

        with patch.object(sb, "_get_shared_llm", return_value=_NoFinalLLM()):
            row = sb.run_maverick(
                instance_id="test__no-diff-1",
                brief="No fix needed; agent should not produce a patch.",
                fail_to_pass=[],
                pass_to_pass=[],
                gold_patch="",
                language="python",
                base_commit="",
            )

        assert not row.predicted_patch, (
            f"expected empty patch; got {row.predicted_patch[:200]}"
        )
        assert row.outcome == "no-diff", (
            f"empty patch must be reported as no-diff; got {row.outcome!r}. "
            "Earlier hotfix forced no-diff when extracted diff is empty."
        )


class TestCsvRoundTrip:
    """The CSV produced by run_maverick must be readable by
    csv.DictReader (no NUL, no embedded raw \\r) and the predicted_patch
    column round-trips intact."""

    def test_csv_round_trips_patch_with_special_chars(self, tmp_path):
        sb = _load_swe_bench()
        # Patch with the things that historically broke CSV: BOM, CR, C1.
        evil_patch = (
            "﻿"          # BOM (must be stripped)
            "diff --git a/x b/x\n"
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1 +1 @@\n"
            "-old\r"         # bare CR
            "+new\r\n"       # CRLF
        )
        row = sb.Row(
            instance_id="csv-test", pipeline="maverick", model_id="x",
            predicted_patch=sb._sanitize_patch_for_csv(evil_patch),
            outcome="success",
        )
        out_csv = tmp_path / "test.csv"
        sb.write_csv([row], out_csv)

        with out_csv.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        recovered = rows[0]["predicted_patch"]
        # CR/BOM are stripped (Wave 12 hardening); the diff body survives.
        assert "\r" not in recovered
        assert "﻿" not in recovered
        assert "diff --git" in recovered
        assert "+new" in recovered

    def test_fetch_to_manifest_to_row_pipeline(self, tmp_path):
        """The full chain: simulated HF row → manifest line → harness
        consumes it without losing fields."""
        from importlib.util import module_from_spec, spec_from_file_location
        p = (Path(__file__).resolve().parents[3]
             / "benchmarks" / "fetch_swe_bench_verified.py")
        spec = spec_from_file_location("fetch_v", p)
        fetch = module_from_spec(spec)
        sys.modules["fetch_v"] = fetch
        spec.loader.exec_module(fetch)

        hf_row = {
            "instance_id": "test__x-1",
            "repo": "test/x",
            "base_commit": "a" * 40,
            "patch": "diff --git a/x b/x\n@@\n-a\n+b\n",
            "test_patch": "should not appear in manifest",
            "problem_statement": "fix the bug",
            "hints_text": "",
            "version": "1.0",
            "environment_setup_commit": "b" * 40,
            "FAIL_TO_PASS": '["test_x"]',
            "PASS_TO_PASS": '["test_y", "test_z"]',
            "difficulty": "<15 min fix",
        }
        manifest_path = tmp_path / "m.jsonl"
        fetch._write_manifest([hf_row], manifest_path)
        line = manifest_path.read_text(encoding="utf-8").strip()
        decoded = json.loads(line)

        assert decoded["instance_id"] == "test__x-1"
        assert decoded["fail_to_pass"] == ["test_x"]
        assert decoded["pass_to_pass"] == ["test_y", "test_z"]
        assert decoded["gold_patch"].startswith("diff --git")
        assert "test_patch" not in decoded
