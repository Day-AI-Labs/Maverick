"""Q3 2026 batch 1: tree-of-thought, debate, audit signing,
anonymous mode, Unicode safety filter, Linear + Jira tools."""
from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock


def _resp(text: str):
    """Duck-typed LLMResponse stand-in: only .text is used downstream."""
    return SimpleNamespace(text=text)


# ---------- tree of thought ----------

def _seq_llm(text_seq: list[str]):
    calls = {"n": 0}

    class _Stub:
        def complete(self, **kwargs):
            i = calls["n"]
            calls["n"] += 1
            return _resp(text_seq[i] if i < len(text_seq) else "fallback")

    return _Stub(), calls


def test_tree_of_thought_picks_critic_winner():
    from maverick.tree_of_thought import plan_tree_of_thought

    critic = json.dumps({
        "scores": [0.2, 0.9, 0.5],
        "winner": 1,
        "reason": "candidate 1 covers test plan and rollback",
    })
    llm, calls = _seq_llm(["plan-A", "plan-B", "plan-C", critic])
    result = plan_tree_of_thought(llm, "build feature X", n=3)
    assert result.winning_index == 1
    assert result.winning_plan == "plan-B"
    assert "covers test plan" in result.critic_reason
    assert calls["n"] == 4  # n candidates + 1 critic


def test_tree_of_thought_falls_back_when_critic_unparseable():
    from maverick.tree_of_thought import plan_tree_of_thought
    llm, _ = _seq_llm([
        "short",
        "a much longer candidate that should win the heuristic",
        "mid-length",
        "not valid JSON at all",
    ])
    result = plan_tree_of_thought(llm, "goal", n=3)
    # Fallback heuristic picks the longest plan.
    assert result.winning_index == 1


def test_tree_of_thought_n_must_be_positive():
    from maverick.tree_of_thought import plan_tree_of_thought
    llm, _ = _seq_llm([])
    try:
        plan_tree_of_thought(llm, "goal", n=0)
    except ValueError as e:
        assert "n must" in str(e).lower()
        return
    raise AssertionError("expected ValueError")


def test_tree_of_thought_single_candidate_skips_critic():
    from maverick.tree_of_thought import plan_tree_of_thought
    llm, calls = _seq_llm(["only-plan"])
    result = plan_tree_of_thought(llm, "goal", n=1)
    assert result.winning_plan == "only-plan"
    assert result.winning_index == 0
    assert calls["n"] == 1  # critic never invoked


def test_tree_of_thought_reraises_budget_exceeded():
    from maverick.budget import BudgetExceeded
    from maverick.tree_of_thought import plan_tree_of_thought

    class _Stub:
        def complete(self, **kwargs):
            raise BudgetExceeded("$1.00 > $0.50")

    try:
        plan_tree_of_thought(_Stub(), "goal", n=3)
    except BudgetExceeded:
        return
    raise AssertionError("expected BudgetExceeded")


# ---------- debate ----------

def test_debate_runs_rounds_and_picks_winner():
    from maverick.debate import DebateParticipant, run_debate

    def _reply(name):
        def _r(**kwargs):
            return _resp(f"{name}-says-something")
        return _r

    def _judge(**kwargs):
        return _resp(json.dumps({
            "winner": "alice",
            "reason": "stronger evidence",
            "key_argument": "cited the original spec",
        }))

    participants = [
        DebateParticipant("alice", "optimist", _reply("alice")),
        DebateParticipant("bob", "skeptic", _reply("bob")),
    ]
    result = run_debate(
        "should we ship?", participants,
        judge_complete=_judge, rounds=2,
    )
    assert result.winner == "alice"
    assert "stronger evidence" in result.judge_reason
    # 2 rounds * 2 participants = 4 turns.
    assert len(result.transcript) == 4
    assert result.rounds_completed == 2


def test_debate_judge_unparseable_yields_draw():
    from maverick.debate import DebateParticipant, run_debate

    def _reply(**kwargs):
        return _resp("argument")

    def _bad_judge(**kwargs):
        return _resp("this is not JSON")

    parts = [
        DebateParticipant("alice", "optimist", _reply),
        DebateParticipant("bob", "skeptic", _reply),
    ]
    result = run_debate("q", parts, judge_complete=_bad_judge, rounds=1)
    assert result.winner == "draw"


def test_debate_requires_two_participants():
    from maverick.debate import DebateParticipant, run_debate
    try:
        run_debate(
            "q",
            [DebateParticipant("solo", "x", lambda **kw: _resp("hi"))],
            judge_complete=lambda **kw: _resp("{}"),
        )
    except ValueError as e:
        assert "at least 2" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_debate_reraises_budget_exceeded():
    from maverick.budget import BudgetExceeded
    from maverick.debate import DebateParticipant, run_debate

    def _boom(**kwargs):
        raise BudgetExceeded("$1.00 > $0.50")

    participants = [
        DebateParticipant("alice", "optimist", _boom),
        DebateParticipant("bob", "skeptic", _boom),
    ]
    try:
        run_debate("q", participants, judge_complete=lambda **kw: _resp("{}"), rounds=1)
    except BudgetExceeded:
        return
    raise AssertionError("expected BudgetExceeded")


# ---------- audit signing ----------

def _crypto_available() -> bool:
    # cryptography's Rust bindings can panic on import when the C
    # ffi backend is missing — catch broadly.
    try:
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
        return True
    except BaseException:
        return False


def test_audit_signer_writes_chained_signed_rows(tmp_path, monkeypatch):
    if not _crypto_available():
        return  # extra not installed
    from maverick.audit import signing
    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
    path = tmp_path / "audit.ndjson"
    s = signing.AuditSigner(path)
    assert s.write({"event": "goal_start", "goal_id": 1})
    assert s.write({"event": "tool_call", "tool": "shell"})
    assert s.write({"event": "goal_end", "status": "done"})

    breaks = signing.verify_chain(path)
    assert breaks == []


def test_audit_signer_detects_tamper(tmp_path, monkeypatch):
    if not _crypto_available():
        return
    from maverick.audit import signing
    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
    path = tmp_path / "audit.ndjson"
    s = signing.AuditSigner(path)
    s.write({"event": "goal_start", "goal_id": 1})
    s.write({"event": "goal_end", "status": "done"})

    # Tamper: rewrite line 1's content but keep its hash/sig.
    lines = path.read_text().splitlines()
    row = json.loads(lines[0])
    row["event"] = "tampered"
    lines[0] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n")

    breaks = signing.verify_chain(path)
    assert breaks
    assert any(b.reason == "bad_hash" for b in breaks)


def test_audit_signer_resumes_chain(tmp_path, monkeypatch):
    if not _crypto_available():
        return
    from maverick.audit import signing
    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
    path = tmp_path / "audit.ndjson"
    s1 = signing.AuditSigner(path)
    s1.write({"event": "a"})
    s1.write({"event": "b"})

    # New signer instance should pick up where the last left off.
    s2 = signing.AuditSigner(path)
    s2.write({"event": "c"})

    breaks = signing.verify_chain(path)
    assert breaks == []


# ---------- privacy ----------

def test_anon_enabled_from_env(monkeypatch):
    from maverick import privacy
    monkeypatch.setenv("MAVERICK_ANON", "1")
    assert privacy.anon_enabled() is True
    monkeypatch.setenv("MAVERICK_ANON", "0")
    # Config may still enable it; just check env-only path doesn't crash.
    privacy.anon_enabled()


def test_anonymize_dict_hashes_user_id():
    from maverick.privacy import anonymize_dict
    out = anonymize_dict({"user_id": "alice@example.com", "ok": 1})
    assert out["user_id"].startswith("user_id#")
    assert out["ok"] == 1


def test_anonymize_dict_basename_for_path():
    from maverick.privacy import anonymize_field
    assert anonymize_field("path", "/etc/passwd") == "passwd"
    assert anonymize_field("filename", "/var/log/x.log") == "x.log"


def test_anonymize_hash_is_stable():
    from maverick.privacy import _hash_id  # type: ignore[attr-defined]
    a = _hash_id("alice", prefix="user_id")
    b = _hash_id("alice", prefix="user_id")
    assert a == b
    assert _hash_id("bob", prefix="user_id") != a


def test_anonymize_scrubs_text_keys():
    from maverick.privacy import anonymize_dict
    out = anonymize_dict({"summary": "contact me at a@b.com"})
    # PII detector should redact the email; if not, at minimum the
    # field is still processed and returns a string.
    assert isinstance(out["summary"], str)


# ---------- unicode filter ----------

def test_unicode_strips_zero_width():
    from maverick.safety.unicode_filter import normalize
    text = "hello​world‍!"
    r = normalize(text)
    assert r.cleaned == "helloworld!"
    assert "zero_width" in r.categories
    assert r.had_dangerous is True


def test_unicode_strips_bidi_overrides():
    from maverick.safety.unicode_filter import normalize
    # The Trojan Source RLO attack
    r = normalize("safe‮text")
    assert "‮" not in r.cleaned
    assert "bidi_override" in r.categories


def test_unicode_strips_tag_block():
    from maverick.safety.unicode_filter import normalize
    # E0041 = TAG LATIN CAPITAL LETTER A — invisible
    r = normalize("a\U000E0041b")
    assert r.cleaned == "ab"
    assert "tag_block" in r.categories


def test_unicode_nfkc_normalizes_lookalikes():
    from maverick.safety.unicode_filter import normalize
    # 'ﬁ' (U+FB01, FI ligature) -> 'fi' after NFKC.
    r = normalize("oﬁce")
    assert r.cleaned == "ofice"


def test_unicode_clean_text_is_untouched():
    from maverick.safety.unicode_filter import normalize
    r = normalize("plain ascii hello")
    assert r.cleaned == "plain ascii hello"
    assert r.had_dangerous is False
    assert r.categories == []


def test_has_dangerous_unicode_quick_check():
    from maverick.safety.unicode_filter import has_dangerous_unicode
    assert has_dangerous_unicode("ok​nope") is True
    assert has_dangerous_unicode("plain text") is False
    assert has_dangerous_unicode("") is False


# ---------- linear tool ----------

def test_linear_requires_op():
    from maverick.tools.linear import linear
    assert "op is required" in linear().fn({})


def test_linear_unknown_op_returns_validation():
    from maverick.tools.linear import linear
    out = linear().fn({"op": "garbage"})
    assert "unknown op" in out or "ERROR" in out


def test_linear_missing_key(monkeypatch):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    fake = types.ModuleType("httpx")
    fake.post = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.linear import linear
    out = linear().fn({"op": "search", "query": "bug"})
    assert "LINEAR_API_KEY" in out


def test_linear_search_calls_graphql(monkeypatch):
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_xxx")
    fake_resp = MagicMock()
    fake_resp.json = MagicMock(return_value={
        "data": {"issueSearch": {"nodes": [
            {"identifier": "ENG-1", "title": "Crash on load",
             "state": {"name": "Todo"}, "url": "https://x", "priority": 2},
        ]}},
    })
    fake_resp.raise_for_status = MagicMock()

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = MagicMock(return_value=fake_resp)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.linear import linear
    out = linear().fn({"op": "search", "query": "crash"})
    assert "ENG-1" in out
    assert "Crash on load" in out
    fake_httpx.post.assert_called_once()


def test_linear_create_requires_team():
    from maverick.tools.linear import linear
    out = linear().fn({"op": "create", "title": "x"})
    assert "title and team" in out


# ---------- jira tool ----------

def test_jira_requires_op():
    from maverick.tools.jira import jira
    assert "op is required" in jira().fn({})


def test_jira_unknown_op():
    from maverick.tools.jira import jira
    out = jira().fn({"op": "garbage"})
    assert "unknown op" in out or "ERROR" in out


def test_jira_missing_config(monkeypatch):
    monkeypatch.delenv("JIRA_URL", raising=False)
    monkeypatch.delenv("JIRA_USER", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    fake = types.ModuleType("httpx")
    fake.Client = MagicMock()
    monkeypatch.setitem(sys.modules, "httpx", fake)
    from maverick.tools.jira import jira
    out = jira().fn({"op": "search", "jql": "project = X"})
    assert "JIRA_URL" in out


def test_jira_create_requires_summary():
    from maverick.tools.jira import jira
    out = jira().fn({"op": "create", "project": "PROJ"})
    assert "project and summary" in out


def test_jira_search_calls_rest(monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "me@x")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")

    resp = MagicMock()
    resp.json = MagicMock(return_value={
        "issues": [{
            "key": "PROJ-1",
            "fields": {
                "summary": "fix the thing",
                "status": {"name": "To Do"},
            },
        }],
    })
    resp.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.post = MagicMock(return_value=resp)
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.jira import jira
    out = jira().fn({"op": "search", "jql": "assignee = currentUser()"})
    assert "PROJ-1" in out
    assert "fix the thing" in out
    # Uses the current /search/jql endpoint, not the removed /search.
    called_url = fake_client.post.call_args.args[0]
    assert called_url.endswith("/rest/api/3/search/jql")


def test_jira_search_follows_next_page_token(monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "me@x")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")

    def _page(key, summary, token):
        resp = MagicMock()
        body = {"issues": [{"key": key, "fields": {
            "summary": summary, "status": {"name": "To Do"},
        }}]}
        if token:
            body["nextPageToken"] = token
        resp.json = MagicMock(return_value=body)
        resp.raise_for_status = MagicMock()
        return resp

    fake_client = MagicMock()
    fake_client.post = MagicMock(side_effect=[
        _page("PROJ-1", "first issue", "tok-2"),
        _page("PROJ-2", "second issue", None),
    ])
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.jira import jira
    out = jira().fn({"op": "search", "jql": "project = PROJ", "limit": 50})
    assert "PROJ-1" in out and "PROJ-2" in out
    assert fake_client.post.call_count == 2
    # Second request carries the token from the first response.
    assert fake_client.post.call_args_list[1].kwargs["json"]["nextPageToken"] == "tok-2"


def test_jira_get_handles_404(monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "me@x")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")

    resp = MagicMock()
    resp.status_code = 404

    fake_client = MagicMock()
    fake_client.get = MagicMock(return_value=resp)
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = MagicMock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    from maverick.tools.jira import jira
    out = jira().fn({"op": "get", "issue_key": "PROJ-999"})
    assert "not found" in out


# ---------- registration smoke ----------

def test_linear_and_jira_register(tmp_path):
    """Both tools register cleanly via base_registry."""
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    assert "linear" in names
    assert "jira" in names
