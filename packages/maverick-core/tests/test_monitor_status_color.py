"""monitor status->color map: single source for the status line + plan tree.

Regression: the live `'active'` status (set via `set_goal_status('active')`)
had no entry and rendered uncolored (white); `'blocked'` was missing from the
plan-tree map specifically. Both call sites now share `_status_color`.
"""
from __future__ import annotations

import pytest
from maverick.monitor import _status_color


@pytest.mark.parametrize("status,color", [
    ("active", "cyan"),        # the bug: normal running state was uncolored
    ("blocked", "red"),        # was missing from the plan-tree map
    ("pending", "yellow"),
    ("in_progress", "cyan"),
    ("running", "cyan"),
    ("succeeded", "green"),
    ("done", "green"),
    ("failed", "red"),
])
def test_known_statuses_have_colors(status, color):
    assert _status_color(status) == color


def test_case_insensitive():
    assert _status_color("ACTIVE") == "cyan"
    assert _status_color("Blocked") == "red"


def test_unknown_status_defaults_white():
    assert _status_color("frobnicating") == "white"


def test_none_or_empty_is_white_not_crash():
    assert _status_color(None) == "white"  # type: ignore[arg-type]
    assert _status_color("") == "white"
