"""股东与公告联网核验扩展入口。"""
from datetime import date

import polars as pl
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar
from app.market_time import cn_today
from app.services import shareholder_research
from app.services.ai_provider import CODEX_CLI_PROVIDER, current_ai_provider

EXTENSION_ID = 'disclosure.research'
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION
router = APIRouter(prefix='/api/disclosure-research', tags=['disclosure-research'])
SYMBOL_PATTERN = r'^\d{6}\.(SH|SZ|BJ)$'


class ResearchRequest(BaseModel):
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    as_of: date = Field(default_factory=cn_today)
    refresh: bool = False


@router.get('/reports')
def reports(symbol: str = Query(pattern=SYMBOL_PATTERN)):
    return {'reports': shareholder_research.list_reports(symbol),
            'supported': current_ai_provider() == CODEX_CLI_PROVIDER}


@router.post('/research')
async def research(request: Request, req: ResearchRequest):
    if current_ai_provider() != CODEX_CLI_PROVIDER:
        raise HTTPException(409, '联网核验目前需要在 AI 设置中选择已登录的 Codex CLI')
    repo = request.app.state.repo
    instruments = await run_in_threadpool(repo.get_instruments_asset, 'stock')
    if instruments.is_empty():
        raise HTTPException(400, '请先同步股票列表')
    matched = instruments.filter(pl.col('symbol') == req.symbol)
    if matched.is_empty():
        raise HTTPException(404, '股票代码不存在或不是 A 股')
    name = str(matched['name'][0] or '') if 'name' in matched.columns else req.symbol
    try:
        result = await shareholder_research.research(req.symbol, name, req.as_of, refresh=req.refresh)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {'report': result}


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(router)


@router.get('/assessments')
def assessments(request: Request, as_of: date,
                strategy_id: str = Query(pattern=r'^custom_[A-Za-z0-9_]+$')):
    import hashlib

    from app.services.shareholder_assessments import list_assessments
    engine = getattr(request.app.state, 'strategy_engine', None)
    if not engine or not engine.has(strategy_id):
        return {'enabled': False, 'assessments': {}}
    strategy = engine.get(strategy_id)
    if strategy.meta.get('disclosure_scoring') != 'chip_holder_v1' or not strategy.file_path:
        return {'enabled': False, 'assessments': {}}
    digest = hashlib.sha256(strategy.file_path.read_bytes()).hexdigest()
    records = list_assessments(as_of, strategy_id, strategy_sha256=digest)
    from app.strategy.config import load_override
    params = load_override(request.app.state.repo.store.data_dir, strategy_id).get('params', {})
    visible = {}
    for record in records:
        if record['technical']['params'] != params:
            continue
        sources = {}
        for metric in record['inputs']['metrics'].values():
            if not metric:
                continue
            for period in ('previous', 'current'):
                for source in metric[period]['evidence']:
                    sources[source['url']] = source
        visible[record['symbol']] = {**record, 'review_sources': list(sources.values())}
    return {'enabled': True, 'assessments': visible}
