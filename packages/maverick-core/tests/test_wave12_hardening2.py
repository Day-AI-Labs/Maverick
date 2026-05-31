"""Wave 12 hardening pass 2: correctness fixes from the 20-round
bug-hunt. Covers TTL normalization, Budget pickling, gotest false-
positive, token-overlap noise bypass, and Anthropic SDK robustness.
"""
from __future__ import annotations

import pickle


class TestCacheTtlNormalization:
    def test_trailing_space_normalized(self):
        from maverick.budget import _cache_write_mult_from_ttl
        assert _cache_write_mult_from_ttl("1h ") == 2.0
        assert _cache_write_mult_from_ttl(" 1h") == 2.0

    def test_uppercase_normalized(self):
        from maverick.budget import _cache_write_mult_from_ttl
        assert _cache_write_mult_from_ttl("1H") == 2.0

    def test_duration_parsing_handles_unknown_strings(self):
        from maverick.budget import _cache_write_mult_from_ttl
        # 30 minutes > 5m → 1h rate
        assert _cache_write_mult_from_ttl("30m") == 2.0
        # 2h > 1h → 1h rate (the upper tier)
        assert _cache_write_mult_from_ttl("2h") == 2.0
        # 7200s = 2h → 1h rate
        assert _cache_write_mult_from_ttl("7200s") == 2.0
        # 5m or below → 5m rate
        assert _cache_write_mult_from_ttl("5m") == 1.25
        assert _cache_write_mult_from_ttl("1m") == 1.25

    def test_unknown_garbage_defaults_to_5m(self):
        from maverick.budget import _cache_write_mult_from_ttl
        assert _cache_write_mult_from_ttl("forever") == 1.25
        assert _cache_write_mult_from_ttl("") == 1.25
        assert _cache_write_mult_from_ttl(None) == 1.25


class TestBudgetPickling:
    def test_round_trip_preserves_counters(self):
        from maverick.budget import Budget
        from maverick.llm import MODEL_SONNET

        b = Budget(max_dollars=100.0)
        b.record_tokens(10_000, 1000, model=MODEL_SONNET)
        original_dollars = b.dollars

        # multiprocessing.Pool ships via pickle.
        data = pickle.dumps(b)
        b2 = pickle.loads(data)
        assert b2.input_tokens == 10_000
        assert b2.output_tokens == 1000
        assert abs(b2.dollars - original_dollars) < 0.001
        # The new Budget has its own monotonic clock + lock.
        assert b2.elapsed() >= 0
        b2.record_tokens(1000, 100, model=MODEL_SONNET)
        # Both lock and counter survived.
        assert b2.input_tokens == 11_000


    def test_round_trip_preserves_elapsed_for_wall_cap(self):
        from maverick.budget import Budget, BudgetExceeded

        b = Budget(max_wall_seconds=0.01)
        # Exhaust wall-time budget before serialization.
        while b.elapsed() <= 0.02:
            pass
        try:
            b.check()
        except BudgetExceeded:
            pass
        else:
            raise AssertionError("pre-pickle budget should already be exceeded")

        b2 = pickle.loads(pickle.dumps(b))
        # Must remain exceeded after unpickle (no timer reset bypass).
        try:
            b2.check()
        except BudgetExceeded:
            pass
        else:
            raise AssertionError("post-unpickle wall cap bypassed")


class TestGotestPassInPackageName:
    def test_pass_in_package_name_does_not_mask_build_failure(self):
        """Package paths like github.com/PASSport/foo contain `PASS`;
        the old `'PASS' not in out` check incorrectly silenced build
        failures from such repos."""
        from maverick.coding_mode import _parse_gotest
        out = (
            "# github.com/PASSport/foo\n"
            "./foo.go:10:5: undefined: bar\n"
            "FAIL\tgithub.com/PASSport/foo [build failed]\n"
        )
        p, f, ok = _parse_gotest(out)
        assert ok
        assert f >= 1, (
            "build failure should be detected even when package "
            "contains 'PASS' in the path"
        )


class TestTokenOverlapNoisePrefixBypass:
    def test_prepended_noise_does_not_zero_ratio(self):
        """Bypass attempt: prepend ~1000 noise tokens before a verbatim
        gold copy. Before Wave 12 hardening, the `[:5000]` slice did
        not cut here but the symmetric ratio metric was diluted; the
        new "longest contiguous block / gold length" metric is
        immune to noise dilution as long as the gold body is preserved
        as a contiguous run."""
        from maverick.coding_mode import defensive_validate
        # ~150 lines of noise prose (< 10K tokens so sampling doesn't kick
        # in and the verbatim gold block stays contiguous in the matcher).
        noise = "\n".join(
            f"+# noise_{i}_token alpha beta gamma"
            for i in range(150)
        )
        gold_body = (
            "+def fixed_implementation():\n"
            "+    intermediate_result = compute_thing(input_value)\n"
            "+    final_answer = transform(intermediate_result)\n"
            "+    return final_answer\n"
        ) * 5
        ours = (
            "diff --git a/x.py b/x.py\n@@ -1 +1 @@\n"
            + noise + "\n" + gold_body
        )
        gold = (
            "diff --git a/x.py b/x.py\n@@ -1 +1 @@\n" + gold_body
        )
        result = defensive_validate(ours, gold_patch=gold)
        # The verbatim gold block must be detected as a contiguous run.
        assert not result.ok, (
            "noise-prefix bypass should be caught — longest contiguous "
            "match should equal the gold block. "
            f"warnings={result.warnings}"
        )

    def test_exact_50_percent_caught_on_substantive_gold(self):
        """Boundary `>= 0.50` (not `> 0.50`).

        May 26 smoke fix: the detector now skips gold patches with
        fewer than 30 tokens to avoid false-positives on obvious
        one-line fixes. The boundary test uses a 30+-token gold so
        the detector engages, and constructs ours with ~50% longest
        contiguous match to verify the boundary behavior."""
        from maverick.coding_mode import defensive_validate
        # 60+ tokens in gold so the detector engages.
        gold_body = " ".join([f"identifier_{i}" for i in range(60)])
        gold = f"diff --git a/x.py b/x.py\n@@ -1 +1 @@\n+{gold_body}\n"
        # ours: first 30 tokens of gold + 30 unrelated tokens =
        # longest contiguous match is 30/60 = 50% of gold tokens.
        first_half = " ".join([f"identifier_{i}" for i in range(30)])
        unrelated = " ".join([f"other_{i}" for i in range(30)])
        ours = f"diff --git a/x.py b/x.py\n@@ -1 +1 @@\n+{first_half} {unrelated}\n"
        result = defensive_validate(ours, gold_patch=gold)
        # >= 0.50 → blocked
        assert not result.ok


class TestAnthropicProviderRobust:
    def test_resp_usage_none_does_not_crash(self):
        from maverick.budget import Budget
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)

        class _Resp:
            content = []
            usage = None
            stop_reason = "end_turn"

        budget = Budget(max_dollars=10.0)
        # Must not raise even when usage is None entirely.
        resp = client._parse_response(_Resp(), budget, model="claude-sonnet-4-6")
        assert resp.text == ""
        assert budget.dollars == 0.0

    def test_string_usage_values_dont_crash(self):
        from maverick.budget import Budget
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)

        class _Usage:
            input_tokens = "100"
            output_tokens = "20"
            cache_creation_input_tokens = None
            cache_read_input_tokens = None

        class _Resp:
            content = []
            usage = _Usage()
            stop_reason = "end_turn"

        budget = Budget(max_dollars=10.0)
        client._parse_response(_Resp(), budget, model="claude-sonnet-4-6")
        # Should have coerced "100"→100; ~$0.001 spent.
        assert budget.input_tokens == 100

    def test_string_usage_garbage_does_not_crash(self):
        from maverick.budget import Budget
        from maverick.providers.anthropic_provider import AnthropicClient

        client = AnthropicClient.__new__(AnthropicClient)

        class _Usage:
            input_tokens = "not_a_number"
            output_tokens = 50

        class _Resp:
            content = []
            usage = _Usage()
            stop_reason = "end_turn"

        budget = Budget(max_dollars=10.0)
        # Must not raise — defensive _safe_int returns 0.
        client._parse_response(_Resp(), budget, model="claude-sonnet-4-6")
        assert budget.input_tokens == 0
        assert budget.output_tokens == 50

    def test_duplicate_tool_names_no_crash(self):
        from maverick.providers.anthropic_provider import _cached_tools
        tools = [
            {"name": "shell", "input_schema": {}},
            {"name": "shell", "input_schema": {}},  # duplicate
            {"name": None, "input_schema": {}},     # malformed
        ]
        # Must not raise on None name.
        out = _cached_tools(tools)
        assert len(out) == 3
        assert "cache_control" in out[-1]


class TestSanitizerCrlfBomC1:
    def test_strips_crlf_to_lf(self):
        from benchmarks.swe_bench import _sanitize_patch_for_csv
        out = _sanitize_patch_for_csv("line1\r\nline2\r\n")
        assert "\r" not in out
        assert "\n" in out

    def test_strips_bare_cr(self):
        from benchmarks.swe_bench import _sanitize_patch_for_csv
        out = _sanitize_patch_for_csv("a\rb\n")
        assert "\r" not in out

    def test_strips_bom(self):
        from benchmarks.swe_bench import _sanitize_patch_for_csv
        out = _sanitize_patch_for_csv("﻿text\n")
        assert "﻿" not in out

    def test_strips_c1_controls(self):
        from benchmarks.swe_bench import _sanitize_patch_for_csv
        # U+0085 (NEL) is a C1 control.
        out = _sanitize_patch_for_csv("a\x85b\n")
        assert "\x85" not in out

    def test_strips_bidi_marks(self):
        from benchmarks.swe_bench import _sanitize_patch_for_csv
        # U+202E is the right-to-left override — a classic Trojan Source
        # vector. Must be stripped from patches.
        out = _sanitize_patch_for_csv("normal‮malicious\n")
        assert "‮" not in out


class TestSwebenchSigtermReset:
    def test_main_resets_terminate_flag(self):
        """Wave 12 hardening: main() must reset _TERMINATE_REQUESTED so
        a previously-flagged process can re-enter without immediate exit."""
        from pathlib import Path
        # parents[3] = repo root (tests → maverick-core → packages → root).
        p = Path(__file__).resolve().parents[3] / "benchmarks" / "swe_bench.py"
        assert p.exists(), f"could not locate swe_bench.py at {p}"
        src = p.read_text(encoding="utf-8")
        assert "_TERMINATE_REQUESTED = False" in src, (
            "main() must reset _TERMINATE_REQUESTED before installing "
            "the SIGTERM handler"
        )
