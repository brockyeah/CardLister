"""Pin the analytics cost model.

CLAUDE.md invariant #2: the " (subscription)" model suffix is load-bearing —
`_cost()` prices anything carrying it at $0.00. `claude_vision.py` emits the
suffix (f"{model} (subscription)") and `test_vision_fallback.py` pins that
side; this file pins the pricing side so neither module can drift alone.
"""
from backend.routers.analytics import MODEL_PRICES, _DEFAULT_PRICE, _cost
from backend.services.claude_vision import PRESETS


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


def test_every_preset_model_is_priced_explicitly():
    """A model a preset can select must not fall through to _DEFAULT_PRICE.

    The fallback is the right default for a model nobody chose — an env
    override, a legacy row — because overcounting is the safe direction. It is
    the wrong answer for a preset: the Cost preset exists to be cheaper, and
    priced at Opus rates its whole reason for existing is invisible in the very
    report that would show it. Nothing else connects these two tables, so a
    preset refresh (tracked in docs/BACKLOG.md) that updated `PRESETS` alone
    would silently misprice every scan taken through it, with no error anywhere.
    """
    missing = sorted(
        preset["model"] for preset in PRESETS.values()
        if preset["model"] not in MODEL_PRICES
    )
    assert not missing, (
        f"PRESETS select models with no MODEL_PRICES entry: {missing}. "
        "Add them to analytics.MODEL_PRICES — the _DEFAULT_PRICE fallback "
        "would price them at Opus rates."
    )
