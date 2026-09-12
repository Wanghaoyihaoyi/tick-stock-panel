"""缺少本地除权因子时必须补齐已有日K历史, 不只拉近期事件。"""
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.jobs.daily_pipeline import _adj_sync_start


@pytest.mark.parametrize(
    "has_factors,daily_start,earliest,expected",
    [
        (True, None, date(2025, 9, 12), datetime(2026, 8, 28, 16)),
        (False, None, date(2025, 9, 12), datetime(2025, 9, 12)),
        (False, date(2026, 9, 10), date(2025, 9, 12), datetime(2025, 9, 12)),
        (False, date(2025, 1, 1), date(2025, 9, 12), datetime(2025, 1, 1)),
        (True, date(2026, 9, 10), date(2025, 9, 12), datetime(2026, 9, 10)),
        (False, None, None, datetime(2026, 8, 28, 16)),
    ],
)
def test_adj_sync_start(tmp_path, has_factors, daily_start, earliest, expected):
    if has_factors:
        factor_dir = tmp_path / "adj_factor"
        factor_dir.mkdir()
        (factor_dir / "all.parquet").touch()
    repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        earliest_daily_date=Mock(return_value=earliest),
    )
    end = datetime(2026, 9, 12, 16)
    assert _adj_sync_start(repo, daily_start, end) == expected
    if has_factors:
        repo.earliest_daily_date.assert_not_called()
    else:
        repo.earliest_daily_date.assert_called_once_with()
