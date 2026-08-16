"""Pin the analytics cost model.

CLAUDE.md invariant #2: the " (subscription)" model suffix is load-bearing —
`_cost()` prices anything carrying it at $0.00. `claude_vision.py` emits the
suffix (f"{model} (subscription)") and `test_vision_fallback.py` pins that
side; this file pins the pricing side so neither module can drift alone.
"""
from backend.routers.analytics import MODEL_PRICES, _DEFAULT_PRICE, _cost


def test_subscription_suffix_prices_at_zero():
    # Exactly the string claude_vision.py:326 produces for any model.
    assert _cost("claude-opus-4-7 (subscription)", 1_000_000, 1_000_000) == 0.0
    assert _cost("claude-sonnet-4-6 (subscription)", 500_000, 50_000) == 0.0


def test_known_model_priced_from_table():
    in_price, out_price = MODEL_PRICES["claude-opus-4-7"]
    assert _cost("claude-opus-4-7", 1_000_000, 1_000_000) == in_price + out_price


def test_unknown_model_overcounts_at_opus_rates():
    # Deliberate: estimates for overridden/unknown models never undercount.
    in_price, out_price = _DEFAULT_PRICE
    assert _cost("claude-mystery-9", 1_000_000, 1_000_000) == in_price + out_price
