from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from app.services.shareholder_scoring import score_shareholders

AS_OF = date(2026, 9, 11)


def source():
    return {'url': 'https://example.com/report.pdf', 'published_on': '2026-08-30', 'title': '报告'}


def comparison(previous, current):
    return {'previous': {'value': previous, 'report_date': '2026-03-31', 'evidence': [source()]},
            'current': {'value': current, 'report_date': '2026-06-30', 'evidence': [source()]},
            'comparable': True, 'basis': '同一流通股本及机构分类口径'}


def complete():
    names = comparison(0, 0)
    names['previous'].pop('value')
    names['current'].pop('value')
    names['previous']['names'] = ['机构甲']
    names['current']['names'] = ['机构甲', '机构乙', '机构丙']
    names['types_confirmed'] = True
    return {'metrics': {'holder_count': comparison(10000, 8900),
                        'top10_float_ratio': comparison(0.5, 0.51),
                        'institution_float_ratio': comparison(0.1, 0.11),
                        'new_institutions': names},
            'coverage': [{'kind': kind, 'as_of': str(AS_OF), 'covered_through': '2026-10-11',
                          'complete': True, 'evidence': [source()]}
                         for kind in ('reduction', 'unlock', 'investigation')]}


def score(data, chip=30, trend=25):
    return score_shareholders(data, as_of=AS_OF, chip_score=chip, trend_score=trend)


def test_complete_and_risk_missing_are_distinct():
    data = complete()
    result = score(data)
    assert result['shareholder_score'] == 25
    assert result['raw_score'] == 80
    assert result['final_score'] == 94.12
    assert result['grade'] == 'A'
    data['coverage'] = []
    result = score(data)
    assert result['status'] == 'incomplete'
    assert result['raw_score'] == 80
    assert result['final_score'] is None
    assert result['grade'] is None


@pytest.mark.parametrize(('current', 'expected'), [(8999, 10), (9000, 7), (9500, 7), (9501, 4), (10000, 0)])
def test_count_boundaries(current, expected):
    data = complete()
    data['metrics']['holder_count'] = comparison(10000, current)
    assert score(data)['factors']['holder_count']['score'] == expected


@pytest.mark.parametrize(('current', 'top', 'institution'), [(0.11, 8, 5), (0.105, 4, 3), (0.1, 0, 0)])
def test_ratio_percentage_point_boundaries(current, top, institution):
    data = complete()
    for key in ('top10_float_ratio', 'institution_float_ratio'):
        data['metrics'][key] = comparison(0.1, current)
    result = score(data)
    assert result['factors']['top10_float_ratio']['score'] == top
    assert result['factors']['institution_float_ratio']['score'] == institution


@pytest.mark.parametrize('problem', ['future', 'stale', 'basis', 'reversed', 'url', 'zero', 'percent_units'])
def test_invalid_evidence_never_becomes_zero_score(problem):
    data = complete()
    item = data['metrics']['holder_count']
    if problem == 'future':
        item['current']['evidence'][0]['published_on'] = '2026-09-12'
    elif problem == 'stale':
        item['current']['report_date'] = '2025-12-31'
        item['previous']['report_date'] = '2025-06-30'
    elif problem == 'basis':
        item['comparable'] = False
    elif problem == 'reversed':
        item['previous']['report_date'] = '2026-07-01'
    elif problem == 'url':
        item['current']['evidence'][0]['url'] = 'javascript:alert(1)'
    elif problem == 'zero':
        item['previous']['value'] = 0
    else:
        data['metrics']['top10_float_ratio']['current']['value'] = 51
    result = score(data)
    assert result['status'] == 'incomplete'
    assert result['shareholder_score'] is None
    assert result['raw_score'] is None
    assert result['final_score'] is None
    assert result['score_range'][0] < result['score_range'][1]


def test_unknown_institution_type_blocks_both_count_assumptions():
    data = complete()
    data['metrics']['new_institutions']['types_confirmed'] = False
    assert score(data)['factors']['new_institutions']['score'] is None


def test_veto_and_future_closure():
    data = complete()
    data['risks'] = [{'kind': 'reduction', 'announced_on': '2026-08-30',
                      'end_date': '2026-09-01', 'end_announced_on': '2026-09-12',
                      'evidence': [source()]}]
    assert score(data)['status'] == 'excluded'
    data['risks'][0]['end_announced_on'] = '2026-09-10'
    assert score(data)['status'] == 'excluded'
    data['risks'][0]['evidence'][0]['published_on'] = '2026-09-10'
    assert score(data)['status'] == 'complete'


def test_unlock_and_coverage_horizon():
    data = complete()
    data['risks'] = [{'kind': 'unlock', 'announced_on': '2026-08-30',
                      'effective_date': '2026-10-11', 'ratio': 0.05, 'evidence': [source()]}]
    assert score(data)['status'] == 'excluded'
    data['risks'][0]['effective_date'] = '2026-10-12'
    data['coverage'][0]['covered_through'] = '2026-10-10'
    assert score(data)['status'] == 'incomplete'


def test_no_inputs_unknown_and_no_mutation():
    result = score({})
    assert result['known_shareholder_score'] == 0
    assert result['shareholder_score'] is None
    assert result['known_raw_score'] == 55
    data = complete()
    before = deepcopy(data)
    score(data)
    assert data == before


@pytest.mark.parametrize('chip', [True, -1, 36, float('nan'), float('inf')])
def test_invalid_technical_score(chip):
    with pytest.raises(ValueError):
        score({}, chip=chip)


def test_model_score_fields_rejected():
    data = complete()
    data['final_score'] = 99
    with pytest.raises(ValidationError):
        score(data)


def test_review_store_filters_date_strategy_and_hash(tmp_path, monkeypatch):
    from app.config import settings
    from app.services.shareholder_assessments import list_assessments, save_assessment
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    technical = {'chip_score': 30, 'trend_score': 25, 'strategy_sha256': 'a' * 64,
                 'params': {}, 'history_start': '2025-01-01', 'history_end': str(AS_OF)}
    first = save_assessment('000001.SZ', '样本', AS_OF, 'strategy1', technical, {}, '核对原文, 存在缺项')
    second = save_assessment('000001.SZ', '样本', AS_OF, 'strategy1', technical, complete(), '补充两期原文')
    result = list_assessments(AS_OF, 'strategy1', strategy_sha256='a' * 64)
    assert len(result) == 1 and result[0]['id'] == second['id']
    assert first['id'] != second['id']
    assert result[0]['scoring']['final_score'] == 94.12
    assert list_assessments(AS_OF, 'strategy1', strategy_sha256='b' * 64) == []
    assert list_assessments(date(2026, 9, 10), 'strategy1', strategy_sha256='a' * 64) == []
    assert list_assessments(AS_OF, 'strategy2', strategy_sha256='a' * 64) == []
    with pytest.raises(ValueError):
        save_assessment('000001.SZ', '样本', AS_OF, 'strategy1', technical, {}, '')
    technical['history_end'] = '2026-09-10'
    with pytest.raises(ValueError):
        save_assessment('000001.SZ', '样本', AS_OF, 'strategy1', technical, {}, '已核对')
