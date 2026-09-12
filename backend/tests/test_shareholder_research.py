import json
from datetime import date

import pytest

from app.services import ai_provider


@pytest.mark.parametrize('event,expected', [
    ({'type': 'item.completed', 'item': {'type': 'web_search',
      'action': {'type': 'search', 'query': '博云新材'}}}, True),
    ({'type': 'item.started', 'item': {'type': 'web_search'}}, False),
    ({'type': 'item.completed', 'item': {'type': 'web_search', 'status': 'failed'}}, False),
    ({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '已搜索'}}, False),
])
def test_codex_search_event_versions(event, expected):
    assert ai_provider._codex_searched(json.dumps(event)) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize('searched', [True, False])
async def test_web_research_requires_real_search_event(monkeypatch, searched):
    captured = {}

    def run(args, prompt, env, timeout):
        captured['args'] = args
        captured['prompt'] = prompt
        event = {'type': 'item.completed', 'item': {'type': 'web_search', 'status': 'completed'}}
        return 0, (json.dumps(event) if searched else '{}').encode(), b''

    monkeypatch.setattr(ai_provider, '_codex_base_command', lambda: ['codex'])
    monkeypatch.setattr(ai_provider, '_prepare_codex_home', lambda p: None)
    monkeypatch.setattr(ai_provider, '_codex_process_env', lambda p: {})
    monkeypatch.setattr(ai_provider, '_run_codex_process', run)
    monkeypatch.setattr(ai_provider, '_read_output_file', lambda p: '{"sections": []}')
    monkeypatch.setattr(ai_provider, 'current_ai_model', lambda: '')
    if searched:
        result = await ai_provider._run_codex_cli([], max_tokens=4000, timeout=1, web_search=True)
        assert result == '{"sections": []}'
        assert 'web_search="live"' in captured['args']
        assert 'features.shell_tool=false' in captured['args']
        assert '--json' in captured['args']
        assert 'Use only the user-provided prompt content' not in captured['prompt']
    else:
        with pytest.raises(RuntimeError, match='未实际执行联网搜索'):
            await ai_provider._run_codex_cli([], max_tokens=4000, timeout=1, web_search=True)


def test_normalize_research_filters_unusable_evidence():
    from app.services.shareholder_research import normalize_report

    def evidence(url, published):
        return {'url': url, 'published_on': published, 'title': '公告',
                'period': '2026-06-30', 'excerpt': '股东总数为10000户。'}

    payload = {'sections': [{'topic': 'shareholders', 'summary': '两期户数下降',
        'evidence': [evidence('https://www.cninfo.com.cn/new/disclosure/123', '2026-08-20'),
                     evidence('https://www.cninfo.com.cn/future', '2026-09-12'),
                     evidence('https://cninfo.com.cn.evil.test/a', '2026-08-20')]}]}
    report = normalize_report(json.dumps(payload), date(2026, 9, 11))
    assert report['status'] == 'needs_review'
    assert len(report['sections']) == 6
    assert len(report['sections'][0]['evidence']) == 1
    assert report['sections'][0]['status'] == 'needs_review'
    assert report['sections'][1]['status'] == 'missing'
    assert '两期户数下降' not in report['sections'][0]['summary']


@pytest.mark.parametrize('raw', ['not json', '{}', '{"sections": "bad"}'])
def test_invalid_report_is_not_saved(raw):
    from app.services.shareholder_research import normalize_report
    with pytest.raises(ValueError):
        normalize_report(raw, date(2026, 9, 11))


@pytest.mark.asyncio
async def test_research_persistence_cache_and_failure(tmp_path, monkeypatch):
    from app.config import settings
    from app.services import shareholder_research as service

    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    calls = []

    async def generate(messages):
        calls.append(messages)
        return json.dumps({'sections': []})

    monkeypatch.setattr(service, 'generate_web_research', generate)
    monkeypatch.setattr(service, 'cn_today', lambda: date(2026, 9, 12))
    monkeypatch.setattr(service, 'current_ai_provider', lambda: 'codex_cli')
    first = await service.research('002297.SZ', '博云新材', date(2026, 9, 11))
    # 用实际检索日期复用, 保证测试不依赖机器日期。
    from datetime import datetime
    monkeypatch.setattr(service, 'cn_today', lambda: datetime.fromisoformat(first['searched_at']).date())
    second = await service.research('002297.SZ', '博云新材', date(2026, 9, 11))
    assert first['id'] == second['id']
    assert len(calls) == 1
    assert service.list_reports('002297.SZ')[0]['status'] == 'needs_review'
    assert service.list_reports('002389.SZ') == []

    async def fail(messages):
        raise RuntimeError('搜索失败')

    monkeypatch.setattr(service, 'generate_web_research', fail)
    with pytest.raises(RuntimeError, match='搜索失败'):
        await service.research('002297.SZ', '博云新材', date(2026, 9, 11), refresh=True)
    assert len(service.list_reports('002297.SZ')) == 1
    assert not service._running


@pytest.mark.asyncio
async def test_concurrent_same_stock_does_not_repeat_search(tmp_path, monkeypatch):
    import asyncio

    from app.config import settings
    from app.services import shareholder_research as service

    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    async def generate(messages):
        started.set()
        await release.wait()
        return '{"sections": []}'

    monkeypatch.setattr(service, 'generate_web_research', generate)
    job = asyncio.create_task(service.research('002297.SZ', '博云新材', date(2025, 1, 1)))
    await started.wait()
    try:
        with pytest.raises(ValueError, match='正在搜索'):
            await service.research('002297.SZ', '博云新材', date(2025, 1, 1))
    finally:
        release.set()
        await job


def test_research_api_contract(monkeypatch):
    from types import SimpleNamespace

    import polars as pl
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.custom import shareholder_research as route

    app = FastAPI()
    app.include_router(route.router)
    app.state.repo = SimpleNamespace(get_instruments_asset=lambda _: pl.DataFrame(
        {'symbol': ['002297.SZ'], 'name': ['博云新材']}))
    monkeypatch.setattr(route, 'current_ai_provider', lambda: 'codex_cli')
    captured = {}

    async def run(symbol, name, as_of, **kwargs):
        captured.update(symbol=symbol, name=name, as_of=str(as_of))
        return {'id': 'test', **captured}

    monkeypatch.setattr(route.shareholder_research, 'research', run)
    monkeypatch.setattr(route.shareholder_research, 'list_reports', lambda symbol: [])
    with TestClient(app) as client:
        assert client.get('/api/disclosure-research/reports?symbol=002297.SZ').json() == {
            'reports': [], 'supported': True}
        result = client.post('/api/disclosure-research/research', json={
            'symbol': '002297.SZ', 'as_of': '2026-09-11'})
        assert result.status_code == 200
        assert result.json()['report']['name'] == '博云新材'
        assert client.post('/api/disclosure-research/research', json={'symbol': '../x'}).status_code == 422
        assert client.post('/api/disclosure-research/research', json={'symbol': '111111.SH'}).status_code == 404
        monkeypatch.setattr(route, 'current_ai_provider', lambda: 'openai_compat')
        assert client.post('/api/disclosure-research/research', json={'symbol': '002297.SZ'}).status_code == 409
        assert len(captured) == 3


def test_assessment_route_checks_date_code_and_params(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.custom import shareholder_research as route
    from app.services import shareholder_assessments as service
    from app.strategy import config

    path = tmp_path / 'strategy.py'
    path.write_text('# current strategy')
    strategy = SimpleNamespace(meta={'disclosure_scoring': 'chip_holder_v1'}, file_path=path)
    engine = SimpleNamespace(has=lambda _: True, get=lambda _: strategy)
    app = FastAPI()
    app.state.strategy_engine = engine
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    app.include_router(route.router)
    source = {'url': 'https://www.cninfo.com.cn/report.pdf', 'title': '报告', 'published_on': '2026-08-25'}
    record = {'symbol': '002297.SZ', 'technical': {'params': {}},
              'inputs': {'metrics': {'holder_count': {'previous': {'evidence': [source]},
                                                    'current': {'evidence': [source]}}}}}
    calls = []

    def read(day, strategy_id, *, strategy_sha256):
        calls.append((day, strategy_id, strategy_sha256))
        return [record]

    monkeypatch.setattr(service, 'list_assessments', read)
    monkeypatch.setattr(config, 'load_override', lambda *args: {})
    url = '/api/disclosure-research/assessments?strategy_id=custom_test&as_of=2026-09-11'
    with TestClient(app) as client:
        body = client.get(url).json()
        assert body['assessments']['002297.SZ']['review_sources'] == [source]
        assert calls == [(date(2026, 9, 11), 'custom_test', hashlib.sha256(path.read_bytes()).hexdigest())]
        monkeypatch.setattr(config, 'load_override', lambda *args: {'params': {'threshold': 2}})
        assert client.get(url).json()['assessments'] == {}
        strategy.meta = {}
        assert client.get(url).json() == {'enabled': False, 'assessments': {}}
