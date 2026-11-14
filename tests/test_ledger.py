from types import SimpleNamespace

import pytest

from sentinel.llm import PRICING, UsageLedger


def _usage(inp=1000, out=500, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def test_single_model_cost():
    ledger = UsageLedger()
    ledger.record("claude-haiku-5-5", _usage(1_000_000, 1_000_000))
    (line,) = ledger.cost_lines()
    price = PRICING["claude-haiku-5-5"]
    assert line.cost_usd == pytest.approx(price.input + price.output)


def test_accumulates_across_calls():
    ledger = UsageLedger()
    ledger.record("claude-opus-5-5", _usage(100, 50))
    ledger.record("claude-opus-5-5", _usage(200, 100, cache_read=1000))
    (line,) = ledger.cost_lines()
    assert line.calls == 2
    assert line.input_tokens == 300
    assert line.cache_read_tokens == 1000


def test_tiered_total_is_sum():
    ledger = UsageLedger()
    ledger.record("claude-haiku-5-5", _usage(10_000, 2_000))
    ledger.record("claude-opus-5-5", _usage(5_000, 1_000))
    assert ledger.total_cost() == pytest.approx(
        sum(line.cost_usd for line in ledger.cost_lines())
    )
    assert len(ledger.cost_lines()) == 2


def test_unknown_model_prices_zero():
    assert UsageLedger.price_tokens("not-a-model", 1000, 1000) == 0.0
