"""review_diff must propagate BudgetExceeded, never soft-pass-approve.

Regression: the reviewer's LLM call was wrapped in a bare ``except
Exception`` that returned approves=True on ANY failure, including budget
exhaustion. A goal that ran out of budget mid-review would have its diff
auto-approved (CLAUDE.md rule 3). Non-budget failures still soft-pass.
"""
import asyncio

import pytest

from maverick.budget import Budget, BudgetExceeded
from maverick.reviewer import review_diff

_DIFF = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"


class _BudgetBoomLLM:
    async def complete_async(self, **kwargs):
        raise BudgetExceeded("$6.00 > $5.00")


class _TransientErrorLLM:
    async def complete_async(self, **kwargs):
        raise RuntimeError("transient network blip")


def test_review_diff_propagates_budget_exceeded():
    with pytest.raises(BudgetExceeded):
        asyncio.run(review_diff(
            brief="add x", diff=_DIFF, llm=_BudgetBoomLLM(), budget=Budget(),
        ))


def test_review_diff_soft_passes_non_budget_errors():
    # A non-budget failure still soft-passes (unchanged conservative behavior).
    verdict = asyncio.run(review_diff(
        brief="add x", diff=_DIFF, llm=_TransientErrorLLM(), budget=Budget(),
    ))
    assert verdict.approves is True
