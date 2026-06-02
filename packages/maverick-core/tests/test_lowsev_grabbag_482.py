"""Issue #482 low-severity grab-bag fixes:
  - cron Feb-29 search horizon clears the Gregorian skipped-century gap
  - provider_health p95 falls back to nearest-rank on small windows
  - retry_classifier 5xx text match no longer over-matches bare '500' tokens
  - file_cache byte accounting counts encoded bytes, not code points
  - deploy bootstrap scripts validate MAVERICK_REPO against an owner/repo slug
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from maverick import file_cache
from maverick.provider_health import ProviderStat
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


# ---------- provider_health p95 small-window ----------

def test_p95_small_window_never_overstates_max():
    # With only a few samples, quantiles(n=20) would interpolate a p95 ABOVE
    # every observed latency. Nearest-rank must stay <= the slowest observation.
    st = ProviderStat(provider="p", model="m")
    for v in (10.0, 20.0, 1000.0):
        st.latencies_ms.append(v)
    p95 = st.p95()
    assert p95 == 1000.0  # ceil(0.95*3)=3 -> the max, a real observation
    assert p95 <= max(st.latencies_ms)


def test_p95_single_sample():
    st = ProviderStat(provider="p", model="m")
    st.latencies_ms.append(42.0)
    assert st.p95() == 42.0


def test_p95_empty_is_none():
    assert ProviderStat(provider="p", model="m").p95() is None


def test_p95_full_window_uses_interpolation():
    # >=20 samples: the interpolated quantile path runs and lands in range.
    st = ProviderStat(provider="p", model="m")
    for v in range(1, 41):  # 1..40 ms
        st.latencies_ms.append(float(v))
    p95 = st.p95()
    assert 36.0 <= p95 <= 40.0


# ---------- file_cache byte accounting ----------

def test_read_cache_counts_encoded_bytes(tmp_path):
    file_cache.clear_read_cache()
    # A multi-byte char: 'é' is 1 code point but 2 UTF-8 bytes.
    f = tmp_path / "u.txt"
    f.write_text("é" * 100, encoding="utf-8")
    text = file_cache.read_file_cached(f)
    assert text == "é" * 100
    stats = file_cache.read_cache_stats()
    # 100 chars -> 200 UTF-8 bytes, not 100.
    assert stats["bytes"] == 200
    file_cache.clear_read_cache()


def test_read_cache_byte_accounting_balances_on_evict(tmp_path):
    file_cache.clear_read_cache()
    f = tmp_path / "a.txt"
    f.write_text("ünïcödé", encoding="utf-8")
    file_cache.read_file_cached(f)
    # Re-reading the same key must not double-count (replace, not append).
    f.write_text("ünïcödé!", encoding="utf-8")
    file_cache.read_file_cached(f)
    stats = file_cache.read_cache_stats()
    assert stats["entries"] == 1
    assert stats["bytes"] == len("ünïcödé!".encode())
    file_cache.clear_read_cache()


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
