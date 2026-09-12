"""Additive, fixed-hypothesis research; never edits built-in strategy sources.

Run with backend/.venv/bin/python. See docs/strategy-handbook.md.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pprint
import shutil
import sys
import urllib.request
from dataclasses import asdict
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PREFIX = "custom_hb0912_"

# One explicitly stated hypothesis per parent, not a fitted parameter sweep.
RULES = {
    "active_limit_gene": (
        "收盘高于MA20且MA20较5个有效交易日前抬升",
        'entry &= (market.close > matrix_feature(market, "ma20")) & (matrix_feature(market, "ma20") > shift(matrix_feature(market, "ma20"), 5))',
    ),
    "boll_breakout": (
        "仅保留首次上穿布林上轨",
        'entry &= shift(market.close, 1) <= shift(matrix_feature(market, "boll_upper"), 1)',
    ),
    "breakout_new_high_60d": (
        "收盘突破前60个有效交易日盘中最高价",
        "entry &= market.close > shift(valid_rolling_max(market.high, np.isfinite(market.high), 60), 1)",
    ),
    "broken_board_recovery": (
        "补齐至少2连板后断板1至2个有效交易日、再涨停的序列",
        "entry &= _broken_sequence(market)",
    ),
    "bullish_alignment": (
        "限制收盘高于MA20的偏离不超过8%",
        'entry &= market.close <= matrix_feature(market, "ma20") * 1.08',
    ),
    "consecutive_limit_ups": (
        "限制最高3连板，超过3板不新增入场",
        'entry &= matrix_feature(market, "consecutive_limit_ups") <= 3',
    ),
    "high_turnover_surge": (
        "限制当日换手率不超过15%",
        'entry &= market.field("turnover_rate") <= 15.0',
    ),
    "limit_up_momentum": (
        "限制5个有效交易日累计涨幅不超过30%",
        'entry &= matrix_feature(market, "momentum_5d") <= 0.30',
    ),
    "long_lower_shadow_reversal": (
        "下影出现时要求收盘高于前一有效交易日收盘",
        "entry &= market.close > shift(market.close, 1)",
    ),
    "low_volatility_leader": (
        "收盘高于MA60且MA60较5个有效交易日前抬升；不代表企业龙头",
        'entry &= (market.close > matrix_feature(market, "ma60")) & (matrix_feature(market, "ma60") > shift(matrix_feature(market, "ma60"), 5))',
    ),
    "ma_convergence_breakout": (
        "确认收盘突破前5个有效交易日最高收盘",
        "entry &= market.close > shift(valid_rolling_max(market.close, np.isfinite(market.close), 5), 1)",
    ),
    "ma_golden_cross": (
        "增加MA60较5个有效交易日前抬升",
        'entry &= matrix_feature(market, "ma60") > shift(matrix_feature(market, "ma60"), 5)',
    ),
    "macd_below_zero_revival": (
        "要求DIF较上一有效交易日回升",
        'entry &= matrix_feature(market, "macd_dif") > shift(matrix_feature(market, "macd_dif"), 1)',
    ),
    "macd_golden": (
        "金叉发生时要求收盘高于MA60",
        'entry &= market.close > matrix_feature(market, "ma60")',
    ),
    "n_day_low_reversal": ("改为盘中触及前60日最低收盘、当日收盘重新站回该支撑", ""),
    "near_limit_up": ("明确排除当日已收盘涨停", "entry &= ~market.limit_up_locked.astype(bool)"),
    "oversold_bounce": (
        "要求RSI14较上一有效交易日回升",
        'entry &= matrix_feature(market, "rsi_14") > shift(matrix_feature(market, "rsi_14"), 1)',
    ),
    "oversold_reversal": (
        "增加5日量比至少1.2的量能确认",
        'entry &= matrix_feature(market, "vol_ratio_5d") >= 1.2',
    ),
    "platform_consolidation_breakout": ("历史平台振幅改用昨日收盘作分母，并要求完整平台窗口", ""),
    "pullback_ma20_bounce": (
        "要求收盘至少收复MA20",
        'entry &= market.close >= matrix_feature(market, "ma20")',
    ),
    "pullback_to_support": (
        "要求收盘高于前一有效交易日收盘",
        "entry &= market.close > shift(market.close, 1)",
    ),
    "rsi_midline_pullback": (
        "要求RSI14较上一有效交易日回升",
        'entry &= matrix_feature(market, "rsi_14") > shift(matrix_feature(market, "rsi_14"), 1)',
    ),
    "strong_open": (
        "收盘处于当日价格振幅上四分之一区域，零振幅不入选",
        "entry &= (market.high > market.low) & ((market.close - market.low) >= 0.75 * (market.high - market.low))",
    ),
    "trend_breakout": (
        "严格超过前60日最高收盘，排除追平",
        'entry &= market.close > shift(matrix_feature(market, "high_60d"), 1)',
    ),
    "volume_price_surge": (
        "收盘高于MA60且MA60较5个有效交易日前抬升",
        'entry &= (market.close > matrix_feature(market, "ma60")) & (matrix_feature(market, "ma60") > shift(matrix_feature(market, "ma60"), 5))',
    ),
}

SEQUENCE_HELPER = """
def _broken_sequence(market):
    valid = np.isfinite(market.close)
    locked = np.where(valid, market.limit_up_locked.astype(float), np.nan)
    boards = market.field("consecutive_limit_ups")
    p1 = shift(locked, 1, valid)
    p2 = shift(locked, 2, valid)
    one_gap = (shift(boards, 2, valid) >= 2) & (p1 == 0)
    two_gap = (shift(boards, 3, valid) >= 2) & (p2 == 0) & (p1 == 0)
    return valid & (locked == 1) & (one_gap | two_gap)
"""


def derive(code: str, parent: str) -> str:
    """Copy parent implementation, modifying only documented entry semantics."""
    tree = ast.parse(code)
    meta_node = next(
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "META" for t in n.targets)
    )
    meta = ast.literal_eval(meta_node.value)
    description, guard = RULES[parent]
    meta.update(
        id=PREFIX + parent,
        name="研究·" + meta["name"] + "·核验版",
        description=description
        + "。固定假设研究版，保留原退出和评分；盘后确认，最早下一交易日成交。非价值投资评级，未批准实盘。",
        asset_types=["stock"],
        tags=["手册研究", *meta.get("tags", [])],
    )
    lines = code.splitlines(keepends=True)
    lines[meta_node.lineno - 1 : meta_node.end_lineno] = [
        "META = " + pprint.pformat(meta, sort_dicts=False, width=100) + "\n"
    ]
    code = "".join(lines)
    # Keep independent files self-contained within the supported L1 import allowlist.
    node = ast.parse(code).body[0]
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        lines = code.splitlines(keepends=True)
        lines[node.lineno - 1 : node.end_lineno] = [repr(meta["description"]) + "\n"]
        code = "".join(lines)
    # All added features use only t and earlier valid bars. 65 bars covers MA60 slope.
    tree = ast.parse(code)
    edits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "required_fields":
            ret = next(n for n in node.body if isinstance(n, ast.Return))
            fields = ast.get_source_segment(code, ret.value)
            extra = '{"open", "high", "low", "close", "volume"}'
            if parent == "broken_board_recovery":
                extra = '{"open", "high", "low", "close", "volume", "consecutive_limit_ups"}'
            edits.append(
                (ret.lineno - 1, ret.end_lineno, f"        return {fields} | frozenset({extra})\n")
            )
        if isinstance(node, ast.FunctionDef) and node.name == "required_warmup_bars":
            ret = next(n for n in node.body if isinstance(n, ast.Return))
            value = ast.get_source_segment(code, ret.value)
            edits.append((ret.lineno - 1, ret.end_lineno, f"        return max(65, {value})\n"))
    lines = code.splitlines(keepends=True)
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = [replacement]
    code = "".join(lines)
    if parent == "n_day_low_reversal":
        old = 'entry &= market.close <= matrix_feature(market, "low_60d")'
        assert code.count(old) == 1
        code = code.replace(
            old,
            'prior_low = shift(matrix_feature(market, "low_60d"), 1)\n            entry &= (market.low <= prior_low) & (market.close > prior_low)',
        )
        code = code.replace("'label': '要求60日新低'", "'label': '要求触及并收复前60日最低收盘'")
    elif parent == "platform_consolidation_breakout":
        old = "(prior_high - prior_low) / market.close * 100.0"
        assert code.count(old) == 1
        code = code.replace(old, "(prior_high - prior_low) / shift(market.close, 1) * 100.0")
        guard = "entry &= np.isfinite(shift(market.close, days))"
    if guard:
        assert code.count("        return make_signal_matrix(") == 1
        code = code.replace(
            "        return make_signal_matrix(",
            "        # 独立研究假设: "
            + description
            + "\n        "
            + guard
            + "\n        return make_signal_matrix(",
        )
    imports = []
    if "valid_shift as shift" not in code:
        imports.append("from app.backtest.matrix import valid_shift as shift")
    if "valid_rolling_max(" in code:
        imports.append("from app.backtest.matrix import valid_rolling_max")
    if imports:
        code = code.replace("import numpy as np", "import numpy as np\n\n" + "\n".join(imports), 1)
    if parent == "broken_board_recovery":
        code += SEQUENCE_HELPER
    return code


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False))
    temp.replace(path)


def api(path, payload=None):
    req = urllib.request.Request(
        "http://127.0.0.1:3018" + path,
        data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=120) as r:
        return json.load(r)


def bootstrap(root):
    os.environ["DATA_DIR"] = str(root / "snapshot/data")
    os.environ.setdefault("POLARS_MAX_THREADS", "2")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    sys.path.insert(0, str(root / "snapshot"))


def prepare(root, data_snapshot):
    if root.is_relative_to(data_snapshot) or data_snapshot.is_relative_to(root):
        raise ValueError("Output and input snapshot must be separate, non-nested directories")
    if (root / "plan.json").exists():
        raise RuntimeError("A locked plan already exists; choose a new output directory")
    snapshot = root / "snapshot"
    shutil.copytree(
        PROJECT / "backend/app",
        snapshot / "app",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(
        data_snapshot,
        snapshot / "data",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*cache*", "*.duckdb*"),
    )
    bootstrap(root)
    from app.strategy.engine import StrategyEngine

    catalog = api("/api/strategies?include_research=true")
    save(root / "catalog-before.json", catalog)
    save(root / "candidates-before.json", api("/api/backtest/candidates"))
    records = []
    for parent in RULES:
        source = snapshot / "app/strategy/builtin" / (parent + ".py")
        sid = PREFIX + parent
        assert not any(s["id"] == sid for s in catalog["strategies"]), sid
        target = root / "generated" / (sid + ".py")
        target.parent.mkdir(exist_ok=True)
        target.write_text(derive(source.read_text(), parent))
        checked_engine = StrategyEngine([target.parent])
        assert not checked_engine.load_errors(), checked_engine.load_errors()
        records.append(
            {
                "parent": parent,
                "id": sid,
                "name": checked_engine.get(sid).meta["name"],
                "improvement": RULES[parent][0],
                "original_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    save(
        root / "plan.json",
        {
            "variants": records,
            "periods": {
                "train": ["2026-01-05", "2026-05-29"],
                "validation": ["2026-06-01", "2026-09-11"],
            },
            "method": "25 fixed hypotheses; no parameter search; every result reported; observed history, not blind out-of-sample; no live promotion",
            "data_snapshot": str(data_snapshot),
            "stress_slippage_bps": 10,
        },
    )


def install(root):
    if (root / "curation.json").exists():
        raise RuntimeError("This batch has been curated; do not reinstall removed research variants")
    plan = json.loads((root / "plan.json").read_text())
    receipts = []
    for item in plan["variants"]:
        code = (root / "generated" / (item["id"] + ".py")).read_text()
        # L1 file extension supports the same fields as built-ins. The AI editor's
        # narrower scoring allowlist excludes several legitimate built-in fields.
        target = PROJECT / "data/strategies/custom" / (item["id"] + ".py")
        with target.open("x") as stream:
            stream.write(code)
        result = {
            "id": item["id"],
            "path": str(target),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        assert result["sha256"] == item["sha256"]
        (root / "snapshot/data/strategies/custom" / (item["id"] + ".py")).write_text(code)
        receipts.append(result)
        save(root / "installation.json", receipts)
        print("ADDED", item["name"], flush=True)
    result = api("/api/strategies/reload", {})
    save(root / "reload.json", result)


def run(root):
    bootstrap(root)
    from app.backtest.engine import BacktestEngine
    from app.backtest.strategy import (
        BacktestResultPolicy,
        StrategyBacktestConfig,
        StrategyBacktestService,
    )
    from app.strategy.engine import StrategyEngine
    from app.tickflow.repository import DataStore, KlineRepository

    plan = json.loads((root / "plan.json").read_text())
    store = DataStore(root / "snapshot/data")
    store.db.execute("SET threads=2")
    engine = StrategyEngine(
        [root / "snapshot/app/strategy/builtin", root / "snapshot/data/strategies/custom"]
    )
    assert not engine.load_errors(), engine.load_errors()
    service = StrategyBacktestService(BacktestEngine(KlineRepository(store)), engine)
    for item in plan["variants"]:
        for sid in [item["parent"], item["id"]]:
            for period, bounds in plan["periods"].items():
                stresses = (
                    [False, True] if sid == item["id"] and period == "validation" else [False]
                )
                for stress in stresses:
                    out = (
                        root
                        / "results"
                        / (sid + "__" + period + ("__stress" if stress else "") + ".json")
                    )
                    if out.exists():
                        continue
                    cfg = {
                        "strategy_id": sid,
                        "symbols": None,
                        "start": bounds[0],
                        "end": bounds[1],
                        "params": {},
                        "overrides": {},
                        "mode": "position",
                        "entry_fill": "open_t+1",
                        "exit_fill": "open_t+1",
                        "commission_pct": 0.0002,
                        "stamp_tax_pct": 0.001,
                        "slippage_bps": 10 if stress else 5,
                        "max_positions": 10,
                        "max_exposure_pct": 1.0,
                        "initial_capital": 1000000,
                        "position_sizing": "equal",
                        "minute_fill": False,
                        "asset_type": "stock",
                        "regime_filter": None,
                    }
                    cfg["params"] = service._normalize_params({}, engine.get(sid))
                    print("RUN", out.stem, flush=True)
                    result = service.run(
                        StrategyBacktestConfig(
                            **{
                                **cfg,
                                "start": date.fromisoformat(bounds[0]),
                                "end": date.fromisoformat(bounds[1]),
                            }
                        ),
                        result_policy=BacktestResultPolicy(include_monte_carlo=False),
                    )
                    assert result.error is None, result.error
                    save(out, {"request": cfg, "result": asdict(result)})
                    print(
                        "DONE",
                        out.stem,
                        {k: result.stats[k] for k in ["total_return", "max_drawdown", "n_trades"]},
                        flush=True,
                    )


def candidates(root):
    if (root / "curation.json").exists():
        raise RuntimeError("This batch has been curated; do not recreate removed candidates")
    receipts = []
    for item in json.loads((root / "plan.json").read_text())["variants"]:
        payload = json.loads((root / "results" / (item["id"] + "__validation.json")).read_text())
        cfg = {**payload["request"], "symbols": []}
        assert not any(
            c["source_id"] == item["id"] for c in api("/api/backtest/candidates")["items"]
        )
        result = api(
            "/api/backtest/candidates",
            {
                "kind": "strategy",
                "name": item["name"],
                "source_id": item["id"],
                "config": cfg,
                "metrics": {
                    k: payload["result"]["stats"].get(k)
                    for k in [
                        "total_return",
                        "max_drawdown",
                        "sharpe",
                        "win_rate",
                        "n_trades",
                        "profit_factor",
                    ]
                },
                "data_as_of": cfg["end"],
                "status": "pending",
            },
        )
        receipts.append(result)
        save(root / "candidates-added.json", receipts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "install", "run", "candidates"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-snapshot", type=Path)
    args = parser.parse_args()
    if args.stage == "prepare":
        if args.data_snapshot is None:
            parser.error("prepare requires --data-snapshot")
        prepare(args.output.resolve(), args.data_snapshot.resolve())
    else:
        {"install": install, "run": run, "candidates": candidates}[args.stage](
            args.output.resolve()
        )
