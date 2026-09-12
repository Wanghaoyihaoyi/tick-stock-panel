"""确定性股东评分。只消费有来源的可比指标, 不消费模型建议分。"""
from __future__ import annotations

from datetime import date, timedelta
from math import isclose
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Source(Model):
    url: str
    published_on: date
    title: str = Field(min_length=1)


class Observation(Model):
    value: float = Field(ge=0, strict=True)
    report_date: date
    evidence: list[Source] = Field(default_factory=list)


class Comparison(Model):
    previous: Observation
    current: Observation
    comparable: bool = False
    basis: str = ''


class InstitutionObservation(Model):
    names: list[str] = Field(max_length=10)
    report_date: date
    evidence: list[Source] = Field(default_factory=list)


class InstitutionComparison(Model):
    previous: InstitutionObservation
    current: InstitutionObservation
    comparable: bool = False
    basis: str = ''
    types_confirmed: bool = False


class Metrics(Model):
    holder_count: Comparison | None = None
    top10_float_ratio: Comparison | None = None
    institution_float_ratio: Comparison | None = None
    new_institutions: InstitutionComparison | None = None


RiskKind = Literal['reduction', 'unlock', 'investigation']


class RiskEvent(Model):
    kind: RiskKind
    announced_on: date
    end_date: date | None = None
    end_announced_on: date | None = None
    effective_date: date | None = None
    ratio: float | None = Field(default=None, ge=0)
    evidence: list[Source] = Field(default_factory=list)


class RiskCoverage(Model):
    kind: RiskKind
    as_of: date
    covered_through: date
    complete: bool = False
    evidence: list[Source] = Field(default_factory=list)


class ShareholderAssessment(Model):
    metrics: Metrics = Field(default_factory=Metrics)
    risks: list[RiskEvent] = Field(default_factory=list)
    coverage: list[RiskCoverage] = Field(default_factory=list)


def _safe_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and parsed.port in (None, 80, 443))
    except ValueError:
        return False


def _sources_valid(sources: list[Source], as_of: date, report_date: date | None = None) -> bool:
    return bool(sources) and all(
        _safe_url(s.url) and s.published_on <= as_of
        and (report_date is None or report_date <= s.published_on) for s in sources
    )


def _comparison_valid(item: Comparison | InstitutionComparison, as_of: date) -> bool:
    return (
        item.comparable and bool(item.basis.strip())
        and item.previous.report_date < item.current.report_date <= as_of
        and (as_of - item.current.report_date).days <= 240
        and all(_sources_valid(o.evidence, as_of, o.report_date)
                for o in (item.previous, item.current))
    )


def score_shareholders(
    payload: dict | ShareholderAssessment, *, as_of: date, chip_score: float, trend_score: float,
) -> dict:
    """返回可审计分项和可能分数区间; 未知不是0分, 风险未覆盖不产生最终分。"""
    data = ShareholderAssessment.model_validate(payload)
    if isinstance(chip_score, bool) or not 0 <= chip_score <= 35:
        raise ValueError('筹码分必须为0至35之间的有限数字')
    if isinstance(trend_score, bool) or not 0 <= trend_score <= 25:
        raise ValueError('趋势分必须为0至25之间的有限数字')
    factors, missing, vetoes = {}, [], []
    maxima = {'holder_count': 10, 'top10_float_ratio': 8,
              'institution_float_ratio': 5, 'new_institutions': 2}
    for key, maximum in maxima.items():
        item = getattr(data.metrics, key)
        score, value = None, None
        valid = item is not None and _comparison_valid(item, as_of)
        if valid and key == 'holder_count':
            valid = (item.previous.value > 0 and item.current.value > 0
                     and item.previous.value.is_integer() and item.current.value.is_integer())
            if valid:
                value = item.current.value / item.previous.value - 1
                score = (10 if value < -0.1 and not isclose(value, -0.1, abs_tol=1e-12)
                         else 7 if value < -0.05 or isclose(value, -0.05, abs_tol=1e-12)
                         else 4 if value < 0 else 0)
        elif valid and key in ('top10_float_ratio', 'institution_float_ratio'):
            valid = item.previous.value <= 1 and item.current.value <= 1
            if valid:
                value = item.current.value - item.previous.value
                score = (maximum if value > 0.01 or isclose(value, 0.01, abs_tol=1e-12)
                         else (4 if key == 'top10_float_ratio' else 3) if value > 0 else 0)
        elif valid:
            valid = item.types_confirmed and all(
                all(n.strip() for n in o.names)
                and len({n.strip() for n in o.names}) == len(o.names)
                for o in (item.previous, item.current)
            )
            if valid:
                names = sorted({n.strip() for n in item.current.names}
                               - {n.strip() for n in item.previous.names})
                value = {'count': len(names), 'names': names}
                score = min(len(names), 2)
        if not valid:
            missing.append(f'{key}: 缺少有效、未过期且口径可比的两期披露证据')
        factors[key] = {'score': score, 'max_score': maximum, 'value': value}

    horizon = as_of + timedelta(days=30)
    for event in data.risks:
        if event.announced_on > as_of:
            continue
        if not _sources_valid(event.evidence, as_of, event.announced_on):
            missing.append(f'{event.kind}: 风险事件来源无效')
            continue
        ended = (event.end_date is not None and event.end_date < as_of
                 and event.end_announced_on is not None and event.end_announced_on <= as_of
                 and any(s.published_on >= event.end_announced_on for s in event.evidence))
        if event.kind in ('reduction', 'investigation') and not ended:
            vetoes.append('存在尚未结束的明确减持计划' if event.kind == 'reduction' else '存在尚未结束的调查事项')
        elif event.kind == 'unlock':
            if event.effective_date is None or event.ratio is None:
                missing.append('unlock: 缺少解禁日期或相对流通股本比例')
            elif as_of < event.effective_date <= horizon and event.ratio >= 0.05:
                vetoes.append('未来30个自然日内有不低于流通股5%的解禁')
    covered = {c.kind for c in data.coverage if c.complete and c.as_of == as_of
               and c.covered_through >= horizon and _sources_valid(c.evidence, as_of)}
    missing.extend(f'{kind}: 风险核验未完整覆盖未来30日'
                   for kind in ('reduction', 'unlock', 'investigation') if kind not in covered)
    known = sum(f['score'] for f in factors.values() if f['score'] is not None)
    unknown = sum(f['max_score'] for f in factors.values() if f['score'] is None)
    lower = (chip_score + trend_score + known) / 85 * 100
    upper = (chip_score + trend_score + known + unknown) / 85 * 100
    status = 'excluded' if vetoes else 'incomplete' if missing else 'complete'
    final = lower if status == 'complete' else None
    grade = None
    if final is not None:
        grade = ('A' if final >= 80 and chip_score >= 25 and known >= 15 and trend_score >= 15
                 else 'B' if final >= 65 else 'C')
    return {'status': status, 'grade': grade, 'chip_score': chip_score, 'trend_score': trend_score,
            'known_raw_score': chip_score + trend_score + known,
            'raw_score': chip_score + trend_score + known if unknown == 0 else None,
            'known_shareholder_score': known, 'shareholder_score': known if unknown == 0 else None,
            'final_score': round(final, 2) if final is not None else None,
            'score_range': [round(lower, 2), round(upper, 2)], 'max_raw_score': 85,
            'factors': factors, 'missing': missing, 'vetoes': vetoes}
