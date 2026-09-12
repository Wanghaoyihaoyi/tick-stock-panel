"""Behavior checks for additive research generation, without touching live data."""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest
from app.backtest.matrix import build_market_data_matrix
from strategy_handbook_research import PREFIX, PROJECT, RULES, derive


def module(parent, *, original=False):
    code = (PROJECT / "backend/app/strategy/builtin" / (parent + ".py")).read_text()
    result = {}
    exec(code if original else derive(code, parent), result)
    return result


def panel(n=120):
    rows = []
    for i in range(n):
        close = 10 + i * 0.02 + np.sin(i / 4) * 0.6
        rows.append(
            dict(
                symbol="000001.SZ",
                date=date(2025, 1, 1) + timedelta(days=i),
                open=close - 0.1,
                high=close + 0.2,
                low=close - 0.3,
                close=close,
                raw_close=close,
                volume=1e7 + i % 5 * 2e6,
                amount=1e8,
                turnover_rate=5.0,
                consecutive_limit_ups=0.0,
                price_limit_pct=0.1,
            )
        )
    return pl.DataFrame(rows)


def market(df):
    return build_market_data_matrix(
        df,
        field_columns={
            "raw_close",
            "turnover_rate",
            "consecutive_limit_ups",
            "amount",
            "price_limit_pct",
        },
    )


@pytest.mark.parametrize("parent", RULES)
def test_research_copies_preserve_exit_and_no_future_information(parent):
    original = module(parent, original=True)
    research = module(parent)
    assert research["META"]["id"] == PREFIX + parent
    assert research["META"]["scoring"] == original["META"]["scoring"]
    for field in ["STOP_LOSS", "MAX_HOLD_DAYS", "EXIT_SIGNALS"]:
        assert research[field] == original[field]
    full, prefix = market(panel()), market(panel().head(100))
    actual = research["MATRIX_STRATEGY"].compute_signals(full, {})
    earlier = research["MATRIX_STRATEGY"].compute_signals(prefix, {})
    old = original["MATRIX_STRATEGY"].compute_signals(full, {})
    np.testing.assert_array_equal(actual.exit, old.exit)
    np.testing.assert_array_equal(actual.entry[:100], earlier.entry)
    if parent != "n_day_low_reversal":
        assert np.all(actual.entry <= old.entry), parent


def flat_rows(n=70):
    return panel(n).with_columns(
        pl.lit(10.0).alias("close"),
        pl.lit(10.0).alias("raw_close"),
        pl.lit(9.9).alias("open"),
        pl.lit(10.1).alias("high"),
        pl.lit(9.8).alias("low"),
    )


@pytest.mark.parametrize("close,expected", [(10.2, 1), (9.8, 0)])
def test_new_low_requires_reclaim_not_new_closing_low(close, expected):
    rows = flat_rows().to_dicts()
    rows[-1].update(close=close, raw_close=close, open=9.6, low=9.5, high=10.3)
    m = market(pl.DataFrame(rows))
    params = {"use_volume_filter": False}
    assert (
        module("n_day_low_reversal")["MATRIX_STRATEGY"].compute_signals(m, params).entry[-1, 0]
        == expected
    )
    assert (
        module("n_day_low_reversal", original=True)["MATRIX_STRATEGY"]
        .compute_signals(m, params)
        .entry[-1, 0]
        == 1 - expected
    )


def test_platform_does_not_use_breakout_price_to_shrink_historical_range():
    rows = flat_rows().to_dicts()
    for row in rows[-11:-1]:
        row.update(high=10.9, low=10.0)
    rows[-1].update(close=11.2, raw_close=11.2, high=11.3, open=10.8)
    m = market(pl.DataFrame(rows))
    params = {"range_pct_max": 8.5, "vol_ratio_min": 0.0}
    assert (
        module("platform_consolidation_breakout", original=True)["MATRIX_STRATEGY"]
        .compute_signals(m, params)
        .entry[-1, 0]
        == 1
    )
    assert (
        module("platform_consolidation_breakout")["MATRIX_STRATEGY"]
        .compute_signals(m, params)
        .entry[-1, 0]
        == 0
    )


@pytest.mark.parametrize("gap", [1, 2])
def test_broken_board_requires_actual_sequence_and_current_limit(gap):
    m = market(flat_rows())
    boards = np.zeros(m.shape, dtype=np.float32)
    locked = np.zeros(m.shape, dtype=np.uint8)
    boards[-gap - 2, 0] = 2
    locked[-1, 0] = 1
    m = replace(m, fields={**m.fields, "consecutive_limit_ups": boards}, limit_up_locked=locked)
    helper = module("broken_board_recovery")["_broken_sequence"]
    assert helper(m)[-1, 0]
    assert not helper(replace(m, fields={**m.fields, "consecutive_limit_ups": np.zeros(m.shape)}))[
        -1, 0
    ]
    assert not helper(replace(m, limit_up_locked=np.zeros(m.shape, dtype=np.uint8)))[-1, 0]


def test_all_ordinary_builtins_are_covered_without_mutating_sources():
    ordinary = {
        p.stem
        for p in (PROJECT / "backend/app/strategy/builtin").glob("*.py")
        if p.stem not in {"__init__", "factor_rank_research"}
    }
    assert ordinary == set(RULES)
    for parent in RULES:
        source = PROJECT / "backend/app/strategy/builtin" / (parent + ".py")
        before = source.read_bytes()
        derive(before.decode(), parent)
        assert source.read_bytes() == before
