# 筹码峰策略移植说明（请教高手用）

> 背景：想把个人项目 `~/jinrong` 里的筹码峰选股策略，加到 `tick-stock-panel`（本仓库）里当一个自定义策略。
> 本文档整理现状、两边机制、已确认结论和待决策事项，方便高手直接给方案；
> 文末（第 8 节）明确了期望交付物：可直接粘贴导入的完整策略代码。
> 编写日期：2026-09-12；tick-stock-panel 上游基线 `54ef03a`（`origin/main` 与 `upstream/main` 一致）。

---

## 1. 两个项目是什么（一句话版）

- **tick-stock-panel（本仓库）**：股票工具台。FastAPI 后端（`:3018`）+ React 前端（`:3011`），`./dev.sh` 一键启动。数据靠调 TickFlow 行情接口 + 数据源插件；25 个内置技术形态策略（布林/MACD/均线/涨停等，**没有筹码类**），带回测、监控预警、自选股、AI 辅助。思路是**广撒网**：全市场扫描出信号。
- **~/jinrong（个人项目，筹码候选）**：只做一件事——筹码峰选股。Python + 本机 PostgreSQL（`chip_lab` schema），页面 `:8787`。就一个策略（strategy-v1，85 分制），数据手工采集入库（日线、股东户数、十大流通、减持解禁公告，留原文留时间），讲究 point-in-time（收盘初稿/晚间版分开记，缺资料就判 incomplete 不给分）。思路是**宁缺毋滥**。

---

## 2. jinrong 策略结构（strategy-v1，85 分制）

源码：`~/jinrong/chip_screener/strategy.py`（入口 `evaluate_stock`），筹码模型 `~/jinrong/chip_screener/model.py`（chip-v3）。

| 模块 | 分值 | 内容 |
|---|---|---|
| 筹码 | 35 | 20/40 日集中度趋势 10；单峰代理（主峰±3%权重）10；收盘与主峰距离 10；20 日主峰抬升 5 |
| 股东 | 25 | 户数下降 10；十大流通合计占比增加 8；机构占比增加 5；新进机构 2 |
| 趋势 | 25 | 收盘>MA20、MA20>MA60、突破前 20 日高点、量比、收盘位置，各 5 |
| 否决项 | — | 减持/调查未结束、大解禁临近、ST、停牌、北交所、上市不足 120 日、20 日均成交额 < 2000 万 |

关键参数（`strategy.py` 内 `DEFAULT_CONFIG`，共约 40 个，含校验规则）：

- 集中度：`concentration20_strong=-0.10` / `mild=-0.05`；`concentration40_strong=-0.15` / `mild=-0.08`
- 主峰邻域：`peak_neighborhood_ratio=0.03`，`strong=0.60` / `mild=0.40`
- 主峰距离：`near=0.03` / `mid=0.06` / `far=0.10`
- 主峰抬升：`strong=0.03` / `mild=0.01`
- 量比：`signal_volume_ratio_min=1.30` / `max=2.50`；收盘位置 `close_position_min=0.70`
- 评级：`grade_a_min=80` / `grade_b_min=65`，且要求筹码≥25、股东≥15、趋势≥15
- 筹码模型：`MIN_HISTORY=120`（至少 120 个有成交日才可信），`MAX_INITIAL_MASS=0.05`，口径 `adjusted_to_latest`，输入要求 **raw 未复权价格** + 公司行动重述

数据依赖（缺一不可，缺了就判 incomplete）：raw 日线（含换手率/成交额/流通股本）、公司行动、股东户数（两个可比报告期）、十大流通股东明细、风险事件（减持/解禁/调查）+ 风险覆盖声明、证券状态（ST/停牌）、交易日历。

---

## 3. 本仓库的策略机制（已核实代码位置）

- **添加入口**：选股页 → 「创建策略 · AI」→ 「自定义编写」→ 执行后端选「矩阵原生」（`frontend/src/components/screener/StrategyBuilderDialog.tsx`，模板 `MATRIX_TEMPLATE` 约第 133 行起）。
- **文件格式**：一个 `.py`，含 `META` 字典 + `MATRIX_STRATEGY` 类（`required_fields` / `required_warmup_bars` / `compute_signals`）。范例：`backend/app/strategy/builtin/boll_breakout.py`。
- **存放位置**：`data/strategies/custom/`（引擎启动扫描四目录之一，见 `backend/app/main.py:253-258`）。属 L1 级扩展，不碰核心代码，升级无冲突。
- **硬约束**（`backend/app/strategy/ai_generator.py`，AST 级校验，存不上会报错）：
  1. 策略 ID 必须 `custom_` 开头；内置策略不可覆盖；
  2. `import` 白名单仅：`numpy`、`polars`、`app.backtest.matrix`、`app.strategy.market_data`、`datetime`、`__future__`（第 344 行起）——**jinrong 的 `model.py` 不能 import，只能把算法用 numpy 重写**；
  3. `META.scoring` 权重总和必须等于 1.0；
  4. `compute_signals(market, params)` 里 `market.close`、`market.turnover_rate` 等是（股票×日期）矩阵，需向量化实现。
- **可直接复用的现成特征**（`backend/app/backtest/matrix.py:3756`，`_MATRIX_COMPUTED_FEATURES`）：`vol_ratio_5d`（量比）、`close_position`（收盘位置）、`turnover_mean_20d`、`ma20_bias`、`vol_ratio_10d` 等；MA20/60、20 日最高价需自己对矩阵做 rolling。`turnover_rate`、`float_shares` 列存在（`matrix.py:907-917, 1407-1437`），股票换手率可用。
- 项目必读：根目录 `CONTRIBUTING.md`（架构/数据契约/测试矩阵），`docs/secondary-development.md`（L1/L2/L3 分级，custom 策略属 L1）。

---

## 4. 能移植 vs 不能移植（已确认结论）

| 部分 | 结论 | 原因 |
|---|---|---|
| 筹码 35 分（集中度趋势、单峰代理、主峰距离、主峰抬升） | ✅ 能 | 换手率衰减核心所需数据（`close`、`turnover_rate`、`amount`）都有 |
| 趋势 25 分（MA/突破/量比/收盘位置） | ✅ 能 | 指标全有，部分现成特征可直接用 |
| 股东 25 分 + 全部否决项 | ❌ 不能 | 本仓库数据层没有股东户数、十大流通、机构持股、减持/解禁/调查事件、ST 状态等数据集（`data_providers` 只有行情类），无米之炊 |
| 「缺资料就不评分」逻辑 | ❌ 不能照搬 | matrix 策略必须输出信号，没有 incomplete 概念；分数体系要重标（建议只做筹码+趋势，另定分制） |

---

## 5. 已识别的风险（请高手重点看）

1. **计算量**：chip-v3 是逐股时序递推（120 天预热），要在 `compute_signals` 里对全市场矩阵向量化实现，不能逐股 Python 循环硬算，否则太慢。
2. **复权口径差异**：jinrong 要求 raw 未复权 + 公司行动重述；本仓库给的是复权后的 `close`，主峰位置会有系统性偏移，距离阈值（3%/6%/10%）可能要重调。
3. **预热**：`required_warmup_bars` 建议声明 160（120 预热 + 40 趋势窗口），上市不足的票自动无信号；另用 `basic_filter` 的 `exclude_st`、`exclude_new_days`、`amount_min` 对齐部分否决项。
4. **结论定位**：缺了股东和公告数据，移植版只能当参考信号，不能当 jinrong 那套「证据齐全才给分」的结论用。两边对同一只票判断不一致时，先信 jinrong。

---

## 6. 待决策事项（请高手拍板）

1. 参数是否沿用 `DEFAULT_CONFIG` 阈值（第 2 节所列），还是先简化？
2. 分数体系怎么定（只做筹码+趋势的话，满分/评级线怎么设）？
3. chip-v3 换手衰减的向量化实现方案（性能是否可行，要不要先做单峰代理简化版）？
4. 复权口径偏移要不要做修正，还是直接重调阈值？
5. 验证标准：建议用宁德时代等 jinrong 已有评估结果的票做两边对照，以 jinrong 为准。

---

## 8. 希望高手交付什么：可直接导入的完整策略代码

请直接给一个**完整、单个 `.py` 文件**，我能原样粘贴到「创建策略 · AI → 自定义编写 → 矩阵原生」的代码框里，点「校验代码」通过、「保存自定义策略」后直接可用。不需要我再补逻辑，只需要我按说明改参数。

### 交付物必须满足（否则本仓库存不上，见第 3 节约束）

1. 顶层 `META` 字典：`id` 以 `custom_` 开头（建议 `custom_chip_peak`）；`asset_types=["stock"]`，`timeframes=["1d"]`；`scoring` 权重和**必须等于 1.0**；建议带上 `basic_filter`（`exclude_st=True`、`exclude_new_days=120`、`amount_min=20000000`，对齐第 2 节否决项中能表达的部分）。
2. `MATRIX_STRATEGY` 类实现三个方法：`required_fields()`（返回所需字段，至少 `close`、`volume`、`turnover_rate`、`amount`）、`required_warmup_bars()`（建议 160，120 天预热 + 40 天趋势窗口）、`compute_signals(market, params)`（返回 `np.ndarray` 布尔/数值信号矩阵）。
3. `import` 只能用白名单：`numpy`、`polars`、`app.backtest.matrix`、`app.strategy.market_data`、`datetime`。**jinrong 的 `model.py` 不能 import，chip-v3 换手衰减算法请用 numpy 重写**（注意全市场矩阵要向量化实现，不要逐股 Python 循环，见第 5 节风险 1）。
4. 策略参数（阈值）做成 `params` 可配置项并给默认值：默认值沿用第 2 节 `DEFAULT_CONFIG`（集中度 −0.10/−0.05、主峰邻域 3%、距离 3%/6%/10%、量比 1.30–2.50、收盘位置 ≥0.70 等），并注明哪些阈值因复权口径差异（第 5 节风险 2）需要重调、建议往哪个方向调。
5. 分数体系请一并定好：只做筹码 + 趋势两部分（股东部分无数据，见第 4 节），给出满分、评级线（对应原来 80/65 分 A/B 级），以及 `ENTRY_SIGNALS` / `EXIT_SIGNALS` / `STOP_LOSS` / `MAX_HOLD_DAYS` 的建议值。
6. `basic_filter` 里表达不了的否决项（减持/解禁/调查、股东条件），请在代码注释里明确标出「本策略无法覆盖，需人工另行核对」，不要静默忽略。
7. 附一段验证说明：用哪只票、哪个日期区间验证（建议用 jinrong 已有评估结果的票，如宁德时代），预期看到什么结果算对（方向一致即算通过，分数不必完全相等）。

### 格式参考

- 照抄 `backend/app/strategy/builtin/boll_breakout.py` 的骨架（`META` + 类 + `compute_signals` 写法），这是本仓库里和目标格式完全一致的范例。
- 前端模板原文见 `frontend/src/components/screener/StrategyBuilderDialog.tsx`（`MATRIX_TEMPLATE`，约第 133 行起）。

## 7. 关键文件速查

- 本仓库策略范例：`backend/app/strategy/builtin/boll_breakout.py`
- 本仓库策略约束：`backend/app/strategy/ai_generator.py`（`_ALLOWED_IMPORT_MODULES`、`_MATRIX_SCORING_FIELDS` 约第 56 行、`_validate_meta_semantics`）
- 本仓库矩阵特征：`backend/app/backtest/matrix.py`（`_MATRIX_COMPUTED_FEATURES` 第 3756 行，`matrix_feature` 第 3780 行）
- 本仓库策略目录装配：`backend/app/main.py:253-260`
- jinrong 策略：`~/jinrong/chip_screener/strategy.py`（`DEFAULT_CONFIG`、`evaluate_stock`）
- jinrong 筹码模型：`~/jinrong/chip_screener/model.py`（`MIN_HISTORY=120`、`build_report`）
- jinrong 说明：`~/jinrong/README.md`
