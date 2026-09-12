"""历史策略应取得声明的交易日窗口, 不受自然日上限截断。"""
from datetime import date, timedelta
from unittest.mock import MagicMock

import polars as pl
import pytest

from app.services.screener import ScreenerService


@pytest.mark.parametrize("asset_type", ["stock", "etf"])
@pytest.mark.parametrize("available,lookback", [(260, 161), (260, 20), (30, 161)])
def test_history_window_uses_trading_dates(tmp_path, asset_type, available, lookback):
    days = []
    day = date(2025, 1, 1)
    while len(days) < available + 5:
        # 稀疏交易日历也不能通过自然日倍数猜测窗口。
        if day.weekday() < 5 and day.month != 2:
            days.append(day)
        day += timedelta(days=1)
    target = days[available - 1]
    dirname = "kline_daily_enriched" if asset_type == "stock" else "kline_etf_enriched"
    for day in days:
        part = tmp_path / dirname / f"date={day}"
        part.mkdir(parents=True)
        pl.DataFrame({
            "symbol": ["600000.SH"], "date": [day],
            "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
            "volume": [1000.0], "amount": [10500.0], "turnover_rate": [5.0],
            "raw_close": [10.5], "raw_high": [11.0], "raw_low": [9.0],
        }).write_parquet(part / "part.parquet")
    repo = MagicMock()
    repo.store.data_dir = tmp_path
    repo.get_enriched_history.return_value = None
    repo.get_instruments_asset.return_value = pl.DataFrame()
    service = ScreenerService(repo, asset_type=asset_type)
    service.clear_history_cache()
    try:
        result = service._load_enriched_history(target, lookback)
        expected = days[max(0, available - lookback - 1):available]
        assert result["date"].to_list() == expected
        assert result["turnover_rate"].to_list() == [5.0] * len(expected)
        if available > lookback + 60:
            assert result["ma60"][0] == pytest.approx(10.5)
        assert service._load_enriched_history(target, lookback).equals(result)
    finally:
        service.clear_history_cache()
