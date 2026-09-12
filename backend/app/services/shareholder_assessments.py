"""已复核股东输入的内部存储入口; 与模型研究草稿分开保存。"""
from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market_time import cn_now
from app.services.json_report_store import JsonReportStore
from app.services.shareholder_scoring import ShareholderAssessment, score_shareholders

_store = JsonReportStore('shareholder_assessments.json', 200, 'sha')


class TechnicalSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    chip_score: float = Field(ge=0, le=35, strict=True)
    trend_score: float = Field(ge=0, le=25, strict=True)
    strategy_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    params: dict[str, Any]
    history_start: date
    history_end: date

    @model_validator(mode='after')
    def valid_history(self):
        if self.history_start > self.history_end:
            raise ValueError('行情窗口开始日不能晚于结束日')
        return self


def save_assessment(
    symbol: str, name: str, as_of: date, strategy_id: str,
    technical: dict, inputs: dict, review_note: str, source_report_id: str | None = None,
) -> dict:
    """仅由已复核工作流调用; 不应向生成模型暴露此函数或HTTP写入口。"""
    if not review_note.strip():
        raise ValueError('必须记录原文复核过程、口径与缺项')
    snapshot = TechnicalSnapshot.model_validate(technical)
    if snapshot.history_end != as_of:
        raise ValueError('技术行情截止日必须与核验日一致')
    validated_inputs = ShareholderAssessment.model_validate(inputs)
    scoring = score_shareholders(validated_inputs, as_of=as_of,
                                 chip_score=snapshot.chip_score, trend_score=snapshot.trend_score)
    now = cn_now().isoformat(timespec='microseconds')
    report = {'id': f'sha_{uuid4().hex}', 'symbol': symbol, 'name': name, 'as_of': str(as_of),
              'strategy_id': strategy_id, 'technical': snapshot.model_dump(mode='json'),
              'inputs': validated_inputs.model_dump(mode='json'), 'review_note': review_note.strip(),
              'reviewed_at': now, 'created_at': now, 'source_report_id': source_report_id,
              'scoring': scoring}
    return _store.save_report(report)


def list_assessments(as_of: date, strategy_id: str, *, strategy_sha256: str) -> list[dict]:
    """同观察日、策略和当前代码哈希的最新每股一份; 不回退到旧算法分数。"""
    latest: dict[str, dict] = {}
    for report in _store.list_reports():
        if (report.get('as_of') != str(as_of) or report.get('strategy_id') != strategy_id
                or report.get('technical', {}).get('strategy_sha256') != strategy_sha256):
            continue
        symbol = report.get('symbol')
        if symbol and symbol not in latest:
            latest[symbol] = report
    return list(latest.values())
