"""Rehearsal queue -> eval cases bridge."""
from __future__ import annotations

import json

from maverick_evolve.rehearsal_bridge import cases_from_rehearsals


def _write_queue(path, rows):
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8",
    )


def test_cases_carry_evidence_as_weight(tmp_path):
    q = tmp_path / "rehearsals.ndjson"
    _write_queue(q, [
        {"prompt": "reconcile the ledger", "evidence": 2, "scope": "local"},
        {"prompt": "fix the flaky export", "evidence": 5, "scope": "local"},
    ])
    cases = cases_from_rehearsals(q)
    assert [c.prompt for c in cases] == [
        "fix the flaky export", "reconcile the ledger",  # biggest first
    ]
    assert cases[0].weight == 5.0
    # Grading matches the kernel's rehearsal signal.
    assert cases[0].check("DONE: handled") is True
    assert cases[0].check("Stopped: budget") is False
    assert cases[0].check("") is False


def test_missing_or_empty_queue_is_empty(tmp_path):
    assert cases_from_rehearsals(tmp_path / "nope.ndjson") == []
    q = tmp_path / "rehearsals.ndjson"
    q.write_text("not json\n{\"no_prompt\": 1}\n", encoding="utf-8")
    assert cases_from_rehearsals(q) == []


def test_max_cases_caps_the_queue(tmp_path):
    q = tmp_path / "rehearsals.ndjson"
    _write_queue(q, [{"prompt": f"case {i}", "evidence": i, "scope": "local"}
                     for i in range(1, 8)])
    assert len(cases_from_rehearsals(q, max_cases=3)) == 3
