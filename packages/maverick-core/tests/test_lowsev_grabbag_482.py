"""Issue #482 low-severity grab-bag fixes:
  - cron Feb-29 search horizon clears the Gregorian skipped-century gap
  - retry_classifier 5xx text match no longer over-matches bare '500' tokens
  - deploy bootstrap scripts validate MAVERICK_REPO against an owner/repo slug
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from maverick.retry_classifier import ErrorClass, classify
from maverick.scheduler import CronError, next_run

# ---------- cron Feb-29 across the skipped century ----------

def test_cron_feb29_resolves_across_skipped_century():
    # 2100 is NOT a leap year (Gregorian century rule), so the next Feb 29 after
    # 2097 is 2104 — ~7 years out, past the old 4-year (1464-day) horizon.
    base = dt.datetime(2097, 3, 1, 0, 0).timestamp()
    ts = next_run("0 0 29 2 *", after=base)
    got = dt.datetime.fromtimestamp(ts)
    assert (got.month, got.day) == (2, 29)
    assert got.year == 2104


def test_cron_impossible_day_still_raises():
    # Feb 30 never exists — must still terminate with CronError, not hang.
    base = dt.datetime(2026, 1, 1).timestamp()
    try:
        next_run("0 0 30 2 *", after=base)
        raise AssertionError("expected CronError for Feb 30")
    except CronError:
        pass


# ---------- retry classifier 5xx anchoring ----------

class _Err(Exception):
    pass


def test_retry_5xx_no_overmatch_on_bare_number():
    # A standalone 5xx-range token in prose must NOT be classified retryable.
    assert classify(_Err("used 500 tokens")) is not ErrorClass.SERVER_5XX
    assert classify(_Err("queued 503 jobs")) is not ErrorClass.SERVER_5XX


def test_retry_5xx_still_matches_http_context():
    assert classify(_Err("HTTP 503 from upstream")) is ErrorClass.SERVER_5XX
    assert classify(_Err("500 Internal Server Error")) is ErrorClass.SERVER_5XX
    assert classify(_Err("service unavailable")) is ErrorClass.SERVER_5XX


def test_retry_5xx_structured_status_code_unaffected():
    class _H(Exception):
        status_code = 502
    assert classify(_H("boom")) is ErrorClass.SERVER_5XX


# ---------- deploy bootstrap MAVERICK_REPO validation ----------

_DEPLOY = Path(__file__).resolve().parents[3] / "deploy" / "desktop"


def test_install_sh_validates_repo_slug():
    body = (_DEPLOY / "install.sh").read_text()
    # The bash validator + the regex it enforces.
    assert "validate_repo" in body
    assert "[A-Za-z0-9._-]+/[A-Za-z0-9._-]+" in body


def test_install_ps1_validates_repo_slug():
    body = (_DEPLOY / "install.ps1").read_text()
    assert "Ensure-RepoSlug" in body
    assert "[A-Za-z0-9._-]+/[A-Za-z0-9._-]+" in body
