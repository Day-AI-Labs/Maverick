"""Regression tests for shield bug-hunt fixes (wave 6)."""
from __future__ import annotations


class TestThresholdNormalization:
    def test_mixed_case_threshold_matches(self):
        from maverick_shield.builtin_rules import (
            SEVERITY_ORDER,
            _threshold_to_min_severity,
        )
        assert _threshold_to_min_severity("Medium") == SEVERITY_ORDER["medium"]
        assert _threshold_to_min_severity(" HIGH ") == SEVERITY_ORDER["high"]


class TestScanToolCallNestedArgs:
    def test_rm_rf_in_nested_list_is_blocked(self):
        from maverick_shield.guard import Shield
        s = Shield(backend="builtin")
        # The dangerous command is split across a list -- repr(args) used to
        # bury it behind quotes/commas so the rm_rf_root rule never matched.
        v = s.scan_tool_call("shell", {"argv": ["rm", "-rf", "/"]})
        assert not v.allowed

    def test_arg_strings_collects_nested_leaves(self):
        # main's guard uses _collect_arg_strings (same nested-leaf collection;
        # this PR's _arg_strings was reconciled into it on merge).
        from maverick_shield.guard import _collect_arg_strings
        leaves = _collect_arg_strings({"a": ["x", {"b": "y"}], "c": 3})
        assert "x" in leaves and "y" in leaves


class TestScanOutputSignature:
    def test_base_and_cascade_accept_known_prompt(self):
        from maverick_shield.cascade import CascadedShield
        from maverick_shield.guard import Shield
        base = Shield(backend="builtin")
        # Must not raise TypeError on known_prompt (the cascade override
        # previously dropped the parameter).
        base.scan_output("hello", known_prompt="sys")
        casc = CascadedShield(base)
        casc.scan_output("hello", known_prompt="sys")
