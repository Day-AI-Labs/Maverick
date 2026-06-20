"""Audit round 5: governance fail-open on unknown risk floor, DSAR fact
omission, and erasure-verify false-clean on an unresolved channel.

1. ``governance._risk_level`` returned ``None`` for any value outside
   ("low","medium","high"), and a floor only fires when it resolves to a level
   (``policy.deny_min_risk and ...``). So ``deny_min_risk = "critical"`` -- a
   natural, stricter-sounding choice -- silently disabled the deny floor
   entirely (fail-OPEN). Now "critical"/"severe"/"max" map to "high" and any
   other unrecognized value clamps to "high" rather than disabling the gate.

2. ``dsar._export_world`` omitted explicitly user-scoped global facts
   (``user:<channel>:<user_id>:*``) that the erase path *would* delete, breaking
   the erasure verifier's "exported == erasable" invariant and the subject's
   Art.15 right of access. Now exported, attribution-safe.

3. ``erasure_verify.verify_erasure`` returned ``clean=True`` when the channel
   couldn't be resolved: the export fails closed to all-zero counts, which read
   as a clean erasure though nothing was checked. Now ``indeterminate`` and
   ``clean=False``.
"""
from __future__ import annotations

from maverick import erasure_verify
from maverick.dsar import export_subject_data
from maverick.governance import Decision, Policy, evaluate
from maverick.world_model import WorldModel

# --- fix 1: governance risk floor never silently disabled ------------------

def test_critical_risk_floor_denies_high_risk_action():
    from maverick.governance import _risk_floor
    # "critical" used to resolve to None -> no deny floor at all. As a config
    # value it must now behave as the top tier and deny a high-risk tool. This
    # is exactly what Policy.from_config does with cfg["deny_min_risk"].
    pol = Policy(deny_min_risk=_risk_floor("critical"))
    assert pol.deny_min_risk == "high"
    assert evaluate("shell", policy=pol).decision is Decision.DENY  # shell=high
    # Sanity: a low-risk tool is still allowed under that floor.
    assert evaluate("read_file", policy=pol).decision is Decision.ALLOW


def test_unknown_risk_floor_clamps_high_not_disabled():
    from maverick.governance import _risk_floor
    assert _risk_floor("critical") == "high"
    assert _risk_floor("severe") == "high"
    assert _risk_floor("bogus-typo") == "high"   # fail-closed, not None
    assert _risk_floor("HIGH") == "high"          # case/space tolerant
    assert _risk_floor("  medium ") == "medium"


def test_explicit_disable_sentinel_clears_floor():
    from maverick.governance import _risk_floor
    # An operator can still intentionally clear a floor.
    assert _risk_floor("none") is None
    assert _risk_floor("off") is None
    assert _risk_floor(None) is None
    assert _risk_floor("") is None


def test_risk_override_still_falls_through_to_classifier():
    # The caller-supplied risk= override keeps its strict semantics: an
    # unrecognized value falls back to the tool classifier, NOT clamped to high.
    from maverick.governance import _risk_level
    assert _risk_level("bogus") is None
    assert _risk_level("critical") is None  # not a known level; override path


# --- fix 2: DSAR exports explicitly user-scoped facts ----------------------

def _world_db():
    from pathlib import Path
    return Path.home() / ".maverick" / "world.db"


def test_dsar_exports_user_scoped_facts_and_excludes_others():
    wm = WorldModel(_world_db())
    # A conversation anchors the channel resolution for the bare-id export.
    wm.get_or_create_conversation("telegram", "alice")
    wm.upsert_fact("user:telegram:alice:preference", "alice likes blue")
    wm.upsert_fact("user:telegram:bob:preference", "bob likes red")
    wm.upsert_fact("global:telegram:alice", "not deliberately scoped")
    wm.close()

    bundle = export_subject_data("alice", channel="telegram")
    facts = bundle["world"]["facts"]
    assert facts == {"user:telegram:alice:preference": "alice likes blue"}
    assert bundle["counts"]["facts"] == 1
    # No cross-subject / unscoped leakage.
    import json
    blob = json.dumps(bundle)
    assert "bob likes red" not in blob
    assert "not deliberately scoped" not in blob


def test_dsar_export_includes_fact_history_key():
    # Shape guarantee: the bundle always carries fact_history (empty when
    # temporal memory is off), so downstream consumers can rely on it.
    wm = WorldModel(_world_db())
    wm.get_or_create_conversation("telegram", "alice")
    wm.close()
    bundle = export_subject_data("alice", channel="telegram")
    assert "fact_history" in bundle["world"]
    assert isinstance(bundle["world"]["fact_history"], dict)


# --- fix 3: erasure verify never certifies clean on an unresolved channel ---

def test_verify_erasure_indeterminate_without_channel():
    # No channel passed and no rows to disambiguate -> the export can't scope to
    # a subject, so the verdict must be indeterminate, not a false "clean".
    rep = erasure_verify.verify_erasure("ghost")
    assert rep.get("indeterminate") is True
    assert rep["clean"] is False


def test_verify_erasure_clean_with_concrete_channel_and_no_data():
    # A concrete channel + genuinely no data is a real, definitive clean.
    rep = erasure_verify.verify_erasure("nobody", channel="telegram")
    assert not rep.get("indeterminate")
    assert rep["clean"] is True
