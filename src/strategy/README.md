# 策略（strategy）

## 职责
战法协议、内置/自定义选股、审计与 AI 转换；即时选股结果可写入账本候选池。

## 边界
依赖 market 面板与 formula。选股计算本身不写 market.db。
通过 `persist_screen_candidates` **写入** `palace.db` 的 `candidate_reviews`（API / Job / 异步选股共用）；同日同池**先清空再写入**。正式 `picks` 按原裁决写入；弱市 `watch_picks` 强制以 `decision=观察`、`tier=watch` 留档，不计入精选胜率。两类都为空时删除当日该池全部结果，不留旧票。

写入源分流：
- 真选：`job:screen` / `api:screen_run`（仅仓内最新交易日）/ `api:screen_today` / `api:screen`
- 回填：`api:screen_backfill`（区间或历史日）；**只替换同池回填行，不覆盖真选**
- `GET /api/screen/history` **默认** `live_only=true`：排除回填，且要求 `created_at` 与选股日同一天；`live_only=false` 供审计含回填
- 历史污染行（隔日写入却标成 `api:screen*`）在连 `palace.db` 时幂等改标为 `api:screen_backfill`

## 关键入口
`StrategyEngine`（domain/base）；`screen`（可带 `on_progress`）；
HTTP：`/api/strategies/*`、`POST /api/strategies/screen`（默认 `record_candidates=true`；多日请用异步接口）、
`GET|POST /api/screen/run`（异步进度 + 默认入库；支持 `start`/`end` 区间 ≤31 自然日，按交易日循环通用 `screen` + 同日同池入库）、`GET /api/screen/today?date=`、`GET /api/screen/history?live_only=`（默认真选）、`GET /api/screen/history/batch`（多战法一次返回，供盘面）。
选股/回测热路径挂 `guard_strategy`（`entry_timing=open` 裸用盘中字段为 block；动态截断：列数 ≤100 全量，否则按 `LOCI_AUDIT_PANEL_SAMPLE_SIZE`（默认 200、上限 500）**分片**跑截断一致性，全覆盖任一片 block 即 fail-closed）；正式 `signals` 与观察 `watch_signals` 都接受截断一致性审计；AI 转换/Python Skill 草稿同口径 fail-closed。

静态审计（`application/audit.py::audit_source`）按入场时点分档，与 Screen Formula 编译器 `_audit_entry_timing` 的白名单保持同一口径：
- `open`（9:25 竞价）：裸用当日 `close/high/low/volume/turnover/amount` → **block**
- `close`（尾盘 14:50 前后）：收盘价已定型可用，裸用当日 `high` / `low` → **block**（全天最高最低要等收盘才知道）
- `next_open` / `next_dip`：当日 OHLC 全部合法，只保留负向 `shift` 的 warn
- 任意时点下，当日字段被 `MA/EMA/HHV/SUM…` 等**含当根**滚动函数读取 → `intraday_field_rolling` **warn**：`MA(CLOSE,5)` 的窗口右端就是信号日本身。同样写法在公式编译器里是 `E_ENTRY_TIMING_LOOKAHEAD` 硬错误，Python 侧目前只报 warn（历史豁免，见 `LAGGING_CALLS`）
- 动态截断探针会剔掉「截断到面板末日」那一格——那等于没截断，恒等通过。选股链路面板正好停在目标交易日，因此 `probe_dates=3` 实际是 2 个真探针
- 面板里可能混着**非 DataFrame 的元数据**（`__instrument_names__` 是 dict，由 `requires_instrument_names` 触发注入）。`audit_truncation` 只截 DataFrame、元数据原样透传，与 `audit_sampling` 的分片同一约定；漏了这层会让任何声明该 flag 的战法一进选股链路就 `AttributeError`（回归测试 `test_truncation_tolerates_non_dataframe_panel_entries`）

## 如何扩展
新战法：实现 Protocol，放 application/，在包 `__init__` 侧效 import 注册；声明 `entry_timing`。
Screen Skill 公式战法统一走 `src.formula.compile_screen_formula()` / `evaluate_screen_formula()`；不要在 `strategy` 再复制一套 parser/evaluator。Python Screen Skill 走 `application/screen_python.py`（引擎/契约）+ `screen_python_load.py`（模块加载），与公式引擎共同适配为 `StrategyEngine`，不得另写选股、回测或 Job 链路。包内 helper 变更会刷新 `strategy_revision`；加载前清除包内 `__pycache__` 与相关 `sys.modules`，避免同名 helper 被旧字节码/旧模块污染。

## 给 Agent 的用法
- 注册战法：实现 `StrategyEngine`，放 `application/`，在包 init 侧效 import
- 产品目录当前 3 个战法：`qianlong-close-v3`（潜龙出海 V3.2）、`sanyuan-tail-v1`（三源尾盘共振，15:30 收盘后托管）、`yangshi-tail-v1`（杨氏尾盘选股 V1，同样 15:30 托管）。已下线不注册：`rsi30-dip`、`qianlong-tail-v1`、`lugw-haidi`（海底捞月，半年窗重测组合约 -24%）及三源 V1 / 潜龙 V2 / 三外有三等，源码仅留 `application/backup/`。潜伏两档（`qianfu-close` / `qianfu-1450`）与尾盘 14:50 两档（`sanyuan-tail-1450` / `yangshi-tail-1450`）已连同定时任务一起从仓库删除，不要恢复。
- 潜龙 V3.2 在 V2 核心突破上：换手约 `3.5%≤turnover<8%`、上涨家数 breadth&lt;45% 时正式信号空仓、按**白线贴近度**（辰星线/CLOSE，刚站上白线优先）取 Top2、`next_open`、持有约 3 日、止损约 -7%；弱市中仅把已通过核心+换手条件的 Top2 放入 `watch_signals` 低吸观察，不改变原回测。V3.1 按 ROC5 降序取最热两只，全样本 2022/2023/2025 均净为负；V3.2 只换排序、闸门不动。活动目录通过策略元数据声明当前版本和回测口径。涨停价只使用前一交易日收盘、板块规则和当前收盘，不读取 T+1。默认股票池为主板+创业板。T+1 开盘分情景买入规则由 `entry_instructions` 元数据提供，不能把次日开盘缺口倒灌回 T 日选股信号。
- 潜龙声明 `screen_rank_factor=白线贴近度`（`辰星线/CLOSE`）：选股 `picks` 按贴近度**降序**输出（延伸最小排最前），入库候选 `score` 映射为贴近度×100（夹到 0–100）。`ROC5` 仍留在因子里只作成因，不再决定 Top2。
- 三源尾盘共振当前版本：三条公开公式取 OR；候选先过后置闸门，再要求**未复权现价≥6 元**，再按横截面评分取前两只。breadth&lt;40% 时正式信号空仓，但闸门前合格 Top2 进入 `watch_signals` 低吸观察；观察不进入 `next_open` 回测或自动次日预案。T+1 开盘买入、短持退出（成交回测 `hold_days=1`），默认股票池为主板+创业板。**托管时点**：`sanyuan-tail-v1` 工作日 **15:30** 用已完成 T 日 OHLCV；14:50 现价代理档 `sanyuan-tail-1450` 已整档删除（定时与代码均不再存在）。日线实现不把原始盘中公式的 `FROMOPEN>=210` 当作成交时点。现价门槛读 `__raw_close`（声明 `requires_raw_limit_price`），前复权价会让历史日整体偏移。
- 杨氏尾盘选股 V1：素材原文四条闸门（流通股本<2亿股、未复权现价<12元、涨幅 1%~5%、换手>2%）+ 成交额≥3000万/价格≥3元/非封板非一字的可交易底线；上涨家数<40% 整日空仓（合格 Top1 降级 `watch_signals`），否则按**当日涨幅降序**取 Top1；**托管时点**：`yangshi-tail-v1` 工作日 **15:30** 用已定型收盘价；14:50 现价代理档 `yangshi-tail-1450` 已整档删除（定时与代码均不再存在）。买入仍是 `next_open`、`screen_hold_days=2`（T+1 开盘买、T+3 收盘卖）、不设止损。闸门阈值**照抄素材原文未调参**，只搜索了执行维度（11 排序因子 × 4 Top-N × 2 宽度闸门 × 2 持有期 = 176 组，7 组通过「逐年零负年 + 两段皆正」且全部来自当日涨幅降序）。网格里 Top1 组合收益最高（+328%、回撤 −32.6%），Top2 是分散后的对照（+136%、回撤 −23.7%）。原文第 6 条「净资产收益率>0.001%」因本仓无财务数据**未实现**，已写进 `backtest_config.unimplemented_source_rule`。名字里的「尾盘」是**选股时点不是买入时点**——尾盘买实测每笔多付约 0.11pp 且弱市年转负，依据见 [`docs/research/2026-08-yule-materials-tail-close-feasibility.md`](../../docs/research/2026-08-yule-materials-tail-close-feasibility.md)。「现价<12元」必须读 `__raw_close`（声明 `requires_raw_limit_price`），前复权价会让老票整体偏移。
- `next_dip` 表示 T 日收盘后生成次日预挂价；T+1 开盘低于目标价按开盘成交，否则最低价触及目标价才按目标价成交，未触价样本跳过（公式/技能仍可用；内置 RSI 战法已下线）。
- 递推指标可声明 `warmup_bars`；选股与回测都通过 `signal_history_bars` 使用同一预热长度，避免信号随面板加载起点漂移。
- 选股：`from src.strategy import screen, get`；入库：`application/persist.py`
- 必须声明 `entry_timing`；补前视审计测试；大宇宙动态探测见 `application/audit_sampling.py`（`iter_guard_panel_shards` + `LOCI_AUDIT_PANEL_SAMPLE_SIZE`，默认分片 200 列）
- 自定义策略目录：`infrastructure/custom/`
- Screen Skill 适配：`application/screen_formula.py` / `screen_python.py` 把包契约映射成同一个 `StrategyEngine`
- Python Screen Skill 的 import/compute 失败会回显诊断码、entrypoint、包内相对文件和有界 trace；不要退化为无上下文异常文本
- Screen Skill 可声明默认 `data.universe` 与 `data.adjust`；运行请求未覆盖时由 screen/backtest 使用，并在 `data_snapshot` 回显
- 异步进度状态：`application/screen_run.py`（内存快照，仿 bootstrap；进度日志用战法中文名，不暴露 `lugw-*` slug / `pool_id`）；交易日窗口：`application/screen_dates.py`
- 即时选股窗口含**今天**时，默认先 `apply_today_spot`（可用 `refresh_spot=false` 跳过），与 `job:screen` 对齐；避免盘中覆盖率个位数被体检阻断

## README 维护
新增/下线战法、改 Protocol、选股入口或入库默认行为时必须更新本文。

## 相关测试
`tests/strategy/`（含 `test_persist.py`、`test_audit_sampling.py`、`test_audit_forward_peek.py`）
