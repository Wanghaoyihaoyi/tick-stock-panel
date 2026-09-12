"""把已复核的输入包同步为候选评分; 从 backend 环境运行, 不执行联网或模型审批。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.services.screener import ScreenerService
from app.services.shareholder_assessments import save_assessment
from app.strategy.config import load_override
from app.strategy.engine import StrategyEngine
from app.tickflow.repository import DataStore, KlineRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review_packet', type=Path)
    args = parser.parse_args()
    packet = json.loads(args.review_packet.read_text())
    strategy_id = packet['strategy_id']
    if not strategy_id.startswith('custom_') or not strategy_id.replace('_', '').isalnum():
        raise ValueError('只支持本地自定义策略')
    as_of = date.fromisoformat(packet['as_of'])
    store = DataStore()
    path = store.data_dir / 'strategies' / 'custom' / f'{strategy_id}.py'
    strategy = StrategyEngine._load_file(path)
    if strategy.meta.get('disclosure_scoring') != 'chip_holder_v1':
        raise ValueError('策略未启用股东后置核验')
    params = load_override(store.data_dir, strategy_id).get('params', {})
    model = strategy.matrix_strategy
    if model is None or not hasattr(model, 'compute_diagnostics'):
        raise ValueError('策略未提供可复核的技术分项')
    symbols = [r['symbol'] for r in packet['rows']]
    panel = ScreenerService(KlineRepository(store))._load_enriched_history(
        as_of, model.required_warmup_bars(params) + 1,
    ).filter(pl.col('symbol').is_in(symbols))
    market = build_market_data_matrix(panel, field_columns=set(model.required_fields()))
    diagnostics = model.compute_diagnostics(market, params)
    if str(panel['date'].max()) != str(as_of):
        raise ValueError('观察日行情缺失')
    for row in packet['rows']:
        i = list(market.symbols).index(row['symbol'])
        if int(diagnostics['status'][-1, i]) != 5:
            raise ValueError(f"{row['symbol']} 技术数据不完整")
        technical = {key: float(diagnostics[key][-1, i]) for key in ('chip_score', 'trend_score')}
        technical.update(strategy_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), params=params,
                         history_start=str(panel['date'].min()), history_end=str(as_of))
        report = save_assessment(row['symbol'], row['name'], as_of, strategy_id,
                                 technical, row['inputs'], row['review_note'])
        print(row['symbol'], json.dumps(report['scoring'], ensure_ascii=False))


if __name__ == '__main__':
    main()
