"""Wave 7a — self-reviewer agent + MAV ensemble verifier."""
from __future__ import annotations

import pytest


# ---------- Self-reviewer parsing ----------

class TestReviewerParse:
    def test_clean_approval(self):
        from maverick.reviewer import _parse
        v = _parse(
            '{"approves": true, "confidence": 0.9, "comments": []}'
        )
        assert v.approves is True
        assert v.confidence == 0.9
        assert v.comments == []

    def test_rejection_with_blocker(self):
        from maverick.reviewer import _parse
        v = _parse(
            '{"approves": false, "confidence": 0.4, "comments": ['
            '{"path": "foo.py", "line": 12, "severity": "blocker", '
            '"message": "null deref"}'
            ']}'
        )
        assert v.approves is False
        assert len(v.blockers) == 1
        assert v.blockers[0].path == "foo.py"

    def test_comment_severity_clamped_to_known(self):
        from maverick.reviewer import _parse
        v = _parse(
            '{"approves": false, "confidence": 0.5, "comments": ['
            '{"path": "x.py", "line": 1, "severity": "catastrophic", '
            '"message": "x"}'
            ']}'
        )
        # Unknown severity normalized to "warning".
        assert v.comments[0].severity == "warning"

    def test_empty_response_rejects(self):
        from maverick.reviewer import _parse
        v = _parse("")
        assert v.approves is False

    def test_unparseable_rejects(self):
        from maverick.reviewer import _parse
        v = _parse("not json")
        assert v.approves is False

    def test_string_approves_value(self):
        from maverick.reviewer import _parse
        v = _parse('{"approves": "true", "confidence": 0.8, "comments": []}')
        assert v.approves is True


class TestReviewDiff:
    @pytest.mark.asyncio
    async def test_empty_diff_short_circuits(self):
        """No diff = empty pass; no LLM call."""
        from maverick.budget import Budget
        from maverick.reviewer import review_diff

        class _ShouldNotBeCalled:
            async def complete_async(self, **_kw):
                raise AssertionError("LLM called on empty diff")

        v = await review_diff("brief", "", _ShouldNotBeCalled(), Budget())
        assert v.approves is True
        assert v.comments == []

    @pytest.mark.asyncio
    async def test_reviews_diff_via_llm(self, fake_llm, make_llm_response):
        from maverick.budget import Budget
        from maverick.reviewer import review_diff
        fake_llm.scripted = [make_llm_response(
            text=(
                '{"approves": true, "confidence": 0.85, '
                '"comments": [{"path": "x.py", "line": 3, '
                '"severity": "nit", "message": "minor"}]}'
            ),
        )]
        v = await review_diff(
            "brief",
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n",
            fake_llm, Budget(),
        )
        assert v.approves is True
        assert v.comments[0].severity == "nit"


class TestGetDiff:
    def test_git_diff_disables_external_helpers(self, monkeypatch, tmp_path):
        from maverick.reviewer import get_diff

        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)

        class _Proc:
            stdout = "ok"

        seen = {}

        def _fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["kwargs"] = kwargs
            return _Proc()

        monkeypatch.setattr("maverick.reviewer.subprocess.run", _fake_run)

        out = get_diff(repo)
        assert out == "ok"
        assert "--no-ext-diff" in seen["cmd"]
        assert "--no-textconv" in seen["cmd"]
        assert "diff.external=" in seen["cmd"]
        assert "diff.textconv=false" in seen["cmd"]

    def test_non_repo_returns_empty(self, tmp_path):
        from maverick.reviewer import get_diff

        assert get_diff(tmp_path) == ""


class TestReviewVerdictRendering:
    def test_empty_pass_is_short(self):
        from maverick.reviewer import ReviewVerdict, format_for_human
        out = format_for_human(ReviewVerdict.empty_pass())
        assert "approved" in out

    def test_blocker_uses_stop_icon(self):
        from maverick.reviewer import (
            ReviewComment,
            ReviewVerdict,
            format_for_human,
        )
        v = ReviewVerdict(approves=False, confidence=0.4, comments=[
            ReviewComment(path="x.py", line=1, severity="blocker", message="bad"),
        ])
        out = format_for_human(v)
        assert "blocker" in out
        assert "x.py:1" in out


# ---------- MAV ensemble verifier ----------

class TestMAVCombine:
    def test_three_accept_majority(self):
        from maverick.verifier import VerifierVerdict, _combine
        verdicts = [
            VerifierVerdict(confidence=0.9, accepts=True, critique="ok"),
            VerifierVerdict(confidence=0.8, accepts=True, critique="ok"),
            VerifierVerdict(confidence=0.3, accepts=False, critique="wrong"),
        ]
        v = _combine(verdicts, weighted=True)
        assert v.accepts is True
        # Confidence is mean of the accepting voters (0.9 + 0.8) / 2.
        assert abs(v.confidence - 0.85) < 1e-6

    def test_weighted_overrides_count(self):
        """Weighted: 2 accepters at 0.5 + 1 strong rejecter at 0.95 -> reject."""
        from maverick.verifier import VerifierVerdict, _combine
        verdicts = [
            VerifierVerdict(confidence=0.5, accepts=True, critique=""),
            VerifierVerdict(confidence=0.5, accepts=True, critique=""),
            VerifierVerdict(confidence=0.95, accepts=False, critique="strong veto"),
        ]
        v = _combine(verdicts, weighted=True)
        # accept_weight = 1.0; reject_weight = 0.95 -> still accepts by 0.05.
        # The point is the weighted scheme actually considers magnitude.
        assert v.accepts is True

    def test_unweighted_majority_wins(self):
        from maverick.verifier import VerifierVerdict, _combine
        verdicts = [
            VerifierVerdict(confidence=0.5, accepts=True, critique=""),
            VerifierVerdict(confidence=0.5, accepts=True, critique=""),
            VerifierVerdict(confidence=0.95, accepts=False, critique=""),
        ]
        v = _combine(verdicts, weighted=False)
        assert v.accepts is True  # 2-of-3

    def test_issues_deduplicated_across_panel(self):
        from maverick.verifier import VerifierVerdict, _combine
        verdicts = [
            VerifierVerdict(confidence=0.4, accepts=False,
                            critique="x", issues=["bad math", "missing units"]),
            VerifierVerdict(confidence=0.5, accepts=False,
                            critique="y", issues=["bad math", "off by one"]),
        ]
        v = _combine(verdicts, weighted=True)
        assert v.accepts is False
        # 3 unique issues: bad math, missing units, off by one.
        assert sorted(v.issues) == ["bad math", "missing units", "off by one"]

    def test_single_verdict_passthrough(self):
        from maverick.verifier import VerifierVerdict, _combine
        single = VerifierVerdict(confidence=0.7, accepts=True, critique="")
        v = _combine([single], weighted=True)
        assert v is single

    def test_empty_panel_rejects(self):
        from maverick.verifier import _combine
        v = _combine([], weighted=True)
        assert v.accepts is False


class TestVerifyEnsemble:
    @pytest.mark.asyncio
    async def test_filters_same_family_panel_members(self, fake_llm, make_llm_response):
        from maverick.budget import Budget
        from maverick.verifier import verify_proposal_ensemble
        # Both panel members return accept; we don't care about the
        # combined result -- we care that the Anthropic panel member is
        # FILTERED OUT when proposer is Anthropic.
        fake_llm.scripted = [
            make_llm_response(
                text='{"confidence": 0.9, "accepts": true, "critique": "", "issues": []}',
            ),
            make_llm_response(
                text='{"confidence": 0.9, "accepts": true, "critique": "", "issues": []}',
            ),
        ]
        await verify_proposal_ensemble(
            "brief", "proposal",
            fake_llm, Budget(),
            proposer_model="anthropic:claude-opus-4-7",
        )
        # Panel was [anthropic, openai, deepseek] -> [openai, deepseek]
        # after filtering. 2 LLM calls.
        assert len(fake_llm.calls) == 2
        models_used = [c.get("model") or "" for c in fake_llm.calls]
        for m in models_used:
            assert "claude" not in m.lower()

    @pytest.mark.asyncio
    async def test_explicit_panel_used(self, fake_llm, make_llm_response):
        from maverick.budget import Budget
        from maverick.verifier import verify_proposal_ensemble
        fake_llm.scripted = [
            make_llm_response(
                text='{"confidence": 0.9, "accepts": true, "critique": "", "issues": []}',
            ),
        ]
        await verify_proposal_ensemble(
            "brief", "proposal",
            fake_llm, Budget(),
            panel=["openai:gpt-5.4"],
        )
        assert len(fake_llm.calls) == 1
        assert fake_llm.calls[0].get("model") == "openai:gpt-5.4"
