from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from app.backtest.matrix import build_market_data_matrix
from app.backtest.strategy import StrategyDependencyResolver, build_matrix_cache_profile
from app.strategy.engine import StrategyEngine


@pytest.mark.parametrize(
    ('symbol', 'last_close', 'expected'),
    [('600001.SH', 10.8, 1), ('300001.SZ', 10.8, 0), ('300001.SZ', 11.8, 1)],
)
def test_near_limit_dependency_plan_reaches_signal_computation(symbol, last_close, expected):
    engine = StrategyEngine(strategy_dirs=[Path(__file__).resolve().parents[2] / 'app/strategy/builtin'])
    strategy = next(s for s in engine.strategy_definitions() if s.meta['id'] == 'near_limit_up')
    params = engine.resolve_params(strategy)
    plan = StrategyDependencyResolver().resolve(
        strategy, params=params, basic_filter={}, entry_signals=[], exit_signals=[],
    )
    closes = [10.0] * 20 + [last_close]
    panel = pl.DataFrame({
        'symbol': [symbol] * 21,
        'name': ['普通股'] * 21,
        'date': [date(2026, 8, 1) + timedelta(days=i) for i in range(21)],
        'open': closes, 'high': closes, 'low': closes, 'close': closes,
        'volume': [1000.0] * 21,
    })
    market = build_market_data_matrix(panel, field_columns=plan.matrix_columns)
    signals = strategy.matrix_strategy.compute_signals(market, params)
    assert signals.entry[-1, 0] == expected
    np.testing.assert_allclose(
        market.field('price_limit_pct'), 0.2 if symbol.startswith('300') else 0.1,
    )
    # Derived rules are requested from the matrix builder, never from stored Parquet columns.
    assert 'price_limit_pct' not in plan.base_columns
    profile = build_matrix_cache_profile(
        SimpleNamespace(strategy_definitions=lambda: [strategy]), 'stock', requested_plan=plan,
    )
    assert 'price_limit_pct' in profile.field_columns
