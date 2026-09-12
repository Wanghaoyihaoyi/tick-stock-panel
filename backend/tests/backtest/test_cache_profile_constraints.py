from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backtest.strategy import StrategyDependencyResolver, build_matrix_cache_profile
from app.strategy.engine import StrategyEngine


class CoupledThresholds:
    def required_fields(self):
        return {'close'}

    def required_warmup_bars(self, params):
        if params['strong'] >= params['mild']:
            raise ValueError('strong 必须小于 mild')
        return params['history']


def strategy():
    engine = StrategyEngine(strategy_dirs=[Path(__file__).resolve().parents[2] / 'app/strategy/builtin'])
    base = next(iter(engine.strategy_definitions()))
    return replace(base, meta={'id': 'coupled', 'params': [
        {'id': 'strong', 'type': 'float', 'default': -0.1, 'max': -0.001},
        {'id': 'mild', 'type': 'float', 'default': -0.05, 'max': -0.001},
        {'id': 'history', 'type': 'int', 'default': 160, 'max': 500},
    ]}, required_features=frozenset(), matrix_strategy=CoupledThresholds())


def resolve(s, params):
    return StrategyDependencyResolver().resolve(
        s, params=params, basic_filter={}, entry_signals=[], exit_signals=[],
        overrides={}, asset_type='stock',
    )


def test_optional_maximum_probe_does_not_break_valid_backtest():
    s = strategy()
    requested = resolve(s, {'strong': -0.2, 'mild': -0.1, 'history': 400})
    engine = SimpleNamespace(strategy_definitions=lambda: [s])
    profile = build_matrix_cache_profile(engine, 'stock', requested_plan=requested)
    assert profile.warmup_bars >= 400
    assert 'close' in profile.field_columns
    assert s.meta['params'][0]['default'] == -0.1


def test_actual_invalid_parameters_are_still_rejected():
    with pytest.raises(ValueError, match='strong 必须小于 mild'):
        resolve(strategy(), {'strong': -0.001, 'mild': -0.001, 'history': 400})


def test_valid_maximum_probe_still_expands_shared_cache():
    s = strategy()
    s.meta['params'][0]['max'] = -0.02
    profile = build_matrix_cache_profile(SimpleNamespace(strategy_definitions=lambda: [s]), 'stock')
    assert profile.warmup_bars == 500
