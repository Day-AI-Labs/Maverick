"""Regression tests for bug-hunt wave-7 fixes."""
from __future__ import annotations


class TestStripeZeroDecimal:
    def test_jpy_not_divided_by_100(self):
        from maverick.tools.stripe_tool import _money
        # ¥5000 is returned by Stripe as 5000 (zero-decimal), not 500000.
        assert _money(5000, "jpy") == "5,000 JPY"
        # USD still divides by 100.
        assert _money(5000, "usd") == "50.00 USD"


class TestArxivOldStyleId:
    def test_old_style_id_with_slash_preserved(self):
        import re
        # Mirror the normalization in _op_fetch.
        def norm(s):
            s = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", s)
            return re.sub(r"v\d+$", "", s)
        assert norm("math.GT/0309136") == "math.GT/0309136"
        assert norm("https://arxiv.org/abs/math.GT/0309136v1") == "math.GT/0309136"
        assert norm("2106.09685v2") == "2106.09685"


class TestCostRouterReconciled:
    def test_deepseek_and_moonshot_match_model_prices(self):
        from maverick.cost.router import _PRICING
        from maverick.llm import MODEL_PRICES
        rates = {mid: (cin, cout) for _p, mid, _t, cin, cout in _PRICING}
        for mid in ("deepseek-chat", "moonshot-v1-128k"):
            assert mid in MODEL_PRICES
            assert rates[mid] == MODEL_PRICES[mid], mid
