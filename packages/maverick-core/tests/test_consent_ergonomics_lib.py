"""Consent ergonomics: batching, plain-language, session memory, dry-run, ask."""
from __future__ import annotations

from maverick.consent_ergonomics import (
    PendingConsent,
    SessionConsentMemory,
    ask,
    dry_run,
    group_pending,
    summarize_group,
    summarize_pending,
)


class _Clock:
    """A hand-cranked clock so memory expiry is deterministic."""

    def __init__(self, t=0.0):
        self.t = float(t)

    def __call__(self):
        return self.t


class _FakeDecision:
    def __init__(self, granted, source="prompt"):
        self.granted = granted
        self.source = source


def _consent_always(granted):
    """A stand-in for require_consent that records calls and returns a verdict."""
    calls = []

    def fn(action, *, risk="medium", scope=None, detail=None, **kw):
        calls.append((action, scope, risk))
        return _FakeDecision(granted)

    fn.calls = calls
    return fn


# ---- batching -------------------------------------------------------------

def test_group_by_action_and_risk():
    pending = [
        PendingConsent("rm", "/a", "medium"),
        PendingConsent("rm", "/b", "medium"),
        PendingConsent("force-push", "main", "high"),
    ]
    groups = group_pending(pending)
    assert len(groups) == 2
    rm = next(g for g in groups if g.action == "rm")
    assert rm.count == 2 and rm.scopes == ["/a", "/b"]


def test_different_risk_splits_group():
    pending = [
        PendingConsent("rm", "/a", "medium"),
        PendingConsent("rm", "/b", "high"),
    ]
    assert len(group_pending(pending)) == 2


# ---- plain language -------------------------------------------------------

def test_summarize_group_known_action_plain_language():
    g = group_pending([PendingConsent("rm-rf", "/tmp/x", "high"),
                       PendingConsent("rm-rf", "/tmp/y", "high")])[0]
    text = summarize_group(g)
    assert "delete files and folders" in text
    assert "2 item(s)" in text and "/tmp/x" in text
    assert "high" in text


def test_summarize_group_unknown_action_generic():
    g = group_pending([PendingConsent("frobnicate", "thing", "low")])[0]
    assert "frobnicate" in summarize_group(g)


def test_summarize_truncates_long_scope_list():
    pending = [PendingConsent("rm", f"/f{i}", "low") for i in range(12)]
    text = summarize_group(group_pending(pending)[0], max_scopes=3)
    assert "and 9 more" in text


def test_summarize_pending_overall():
    pending = [PendingConsent("rm", "/a", "low"), PendingConsent("mass-dm", "#all", "high")]
    text = summarize_pending(pending)
    assert "2 pending consent request(s)" in text
    assert "delete files" in text and "message many people" in text


def test_summarize_pending_empty():
    assert "No pending" in summarize_pending([])


# ---- session memory -------------------------------------------------------

def test_session_memory_remembers_then_expires():
    clk = _Clock(100.0)
    mem = SessionConsentMemory(ttl_s=50.0, clock=clk)
    key = ("rm", "/a", "medium", "", ())
    assert mem.has_grant(key) is False
    mem.remember_grant(key)
    assert mem.has_grant(key) is True       # within TTL
    clk.t = 149.0
    assert mem.has_grant(key) is True       # still inside window
    clk.t = 151.0
    assert mem.has_grant(key) is False      # expired


def test_expired_entry_is_dropped():
    clk = _Clock(0.0)
    mem = SessionConsentMemory(ttl_s=10.0, clock=clk, store={})
    mem.remember_grant(("a", "b", "medium", "", ()))
    clk.t = 20.0
    assert mem.has_grant(("a", "b", "medium", "", ())) is False
    # lazily evicted so the store doesn't grow unbounded
    assert ("a", "b", "medium", "", ()) not in mem._store


def test_clear_forgets_everything():
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    mem.remember_grant(("a", "b", "medium", "", ()))
    mem.clear()
    assert mem.has_grant(("a", "b", "medium", "", ())) is False


# ---- ask: composition with the consent primitive --------------------------

def test_ask_calls_consent_and_records_grant_in_session():
    fn = _consent_always(True)
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    pending = [PendingConsent("rm", "/a", "medium")]
    res = ask(pending, mem, consent_fn=fn)
    assert res["results"][0]["granted"] is True
    assert res["results"][0]["source"] == "prompt"
    assert len(fn.calls) == 1
    # the grant is now remembered for the session
    assert mem.has_grant(("rm", "/a", "medium", "", ())) is True


def test_ask_replays_session_grant_without_reprompting():
    fn = _consent_always(True)
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    p = PendingConsent("rm", "/a", "medium")
    ask([p], mem, consent_fn=fn)
    assert len(fn.calls) == 1
    # second ask for the SAME (action, scope) replays memory, no new consent call
    res = ask([p], mem, consent_fn=fn)
    assert len(fn.calls) == 1
    assert res["results"][0]["source"] == "session-memory"


def test_session_grant_does_not_replay_for_higher_risk():
    fn = _consent_always(True)
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    ask([PendingConsent("rm", "/a", "low")], mem, consent_fn=fn)
    ask([PendingConsent("rm", "/a", "critical")], mem, consent_fn=fn)
    assert len(fn.calls) == 2
    assert fn.calls[1] == ("rm", "/a", "critical")


def test_session_grant_does_not_replay_for_stricter_policy_kwargs():
    fn = _consent_always(True)
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    p = PendingConsent("rm", "/a", "low")
    ask([p], mem, consent_fn=fn)
    ask([p], mem, consent_fn=fn, allow_auto_approve=False, consult_ledger=False)
    assert len(fn.calls) == 2


def test_ask_denial_is_not_remembered_and_reasks():
    fn = _consent_always(False)
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    p = PendingConsent("rm", "/a", "medium")
    res1 = ask([p], mem, consent_fn=fn)
    assert res1["results"][0]["granted"] is False
    assert mem.has_grant(("rm", "/a", "medium", "", ())) is False       # denial never cached
    ask([p], mem, consent_fn=fn)
    assert len(fn.calls) == 2                          # asked again, not replayed


def test_ask_never_fabricates_a_grant():
    # if the consent primitive denies, the composed result is a denial — the
    # ergonomics layer can't turn a deny into an allow.
    fn = _consent_always(False)
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    res = ask([PendingConsent("force-push", "main", "high")], mem, consent_fn=fn)
    assert res["granted"] == []
    assert res["denied"] == [("force-push", "main", "high", "", ())]


def test_ask_passes_action_scope_risk_through_to_consent():
    fn = _consent_always(True)
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    ask([PendingConsent("rm", "/secret", "high", "wipe it")], mem, consent_fn=fn)
    assert fn.calls[0] == ("rm", "/secret", "high")


# ---- dry run --------------------------------------------------------------

def test_dry_run_does_not_call_consent():
    # dry_run takes no consent_fn at all; it must never prompt or decide.
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    pending = [PendingConsent("rm", "/a", "low"), PendingConsent("rm", "/b", "low")]
    preview = dry_run(pending, mem)
    assert preview["remembered_this_session"] == []
    assert preview["would_ask"][0]["count"] == 2
    assert "delete files" in preview["summary"]


def test_dry_run_splits_remembered_from_would_ask():
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    mem.remember_grant(("rm", "/a", "low", "", ()))
    pending = [PendingConsent("rm", "/a", "low"), PendingConsent("rm", "/b", "low")]
    preview = dry_run(pending, mem)
    assert preview["remembered_this_session"] == [{"action": "rm", "scope": "/a"}]
    assert preview["would_ask"][0]["scopes"] == ["/b"]


def test_default_consent_fn_is_the_real_primitive(monkeypatch):
    # When no consent_fn is injected, ask() must use safety.consent.require_consent
    # (composition, not a bypass). We patch the real symbol and confirm it's hit.
    import maverick.safety.consent as consent
    seen = {}

    def fake(action, *, risk="medium", scope=None, detail=None, **kw):
        seen["action"] = action
        return _FakeDecision(True, source="auto")

    monkeypatch.setattr(consent, "require_consent", fake)
    mem = SessionConsentMemory(ttl_s=1000.0, clock=_Clock(0.0))
    ask([PendingConsent("rm", "/a", "low")], mem)
    assert seen["action"] == "rm"
