"""`maverick soc2` -- print the SOC 2 evidence snapshot as JSON.

The collector (`maverick.soc2.collect_soc2_evidence`) is already fail-soft; this
covers the thin CLI wrapper: it emits valid JSON carrying the evidence keys and
exits 0, in both the default (pretty) and `--json` (compact) forms.
"""
from __future__ import annotations

import json

from click.testing import CliRunner
from maverick.cli import main


def test_soc2_prints_valid_json_and_exits_zero():
    result = CliRunner().invoke(main, ["soc2"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    # Top-level shape of collect_soc2_evidence() (see maverick/soc2.py).
    assert "controls" in payload
    assert "audit_log" in payload
    assert "version" in payload
    assert "collected_at" in payload
    assert "audit_signing_key" in payload
    # Each control probe carries a status.
    assert "capability_enforcement" in payload["controls"]
    assert "status" in payload["controls"]["capability_enforcement"]
    assert "status" in payload["audit_log"]


def test_soc2_default_is_pretty_printed():
    result = CliRunner().invoke(main, ["soc2"])
    assert result.exit_code == 0
    # indent=2 output spans multiple lines and indents nested keys.
    assert "\n  " in result.output


def test_soc2_json_flag_is_compact_single_line():
    result = CliRunner().invoke(main, ["soc2", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "controls" in payload
    assert "audit_log" in payload
    # Compact form: a single JSON line (click.echo adds one trailing newline).
    assert result.output.strip().count("\n") == 0
