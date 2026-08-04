# 策略（strategy）

## 职责
战法协议、内置/自定义选股、审计与 AI 转换；即时选股结果可写入账本候选池。

## 边界
依赖 market 面板与 formula。选股计算本身不写 market.db。
通过 `persist_screen_candidates` **写入** `palace.db` 的 `candidate_reviews`（API / Job / 异步选股共用）；同日同池**先清空再写入**。重选 0 只时删除当日该池全部结果，不留旧票。

写入源分流：
- 真选：`job:screen` / `api:screen_run`（仅仓内最新交易日）/ `api:screen_today` / `api:screen`
- 回填：`api:screen_backfill`（区间或历史日）；**只替换同池回填行，不覆盖真选**
- `GET /api/screen/history` **默认** `live_only=true`：排除回填，且要求 `created_at` 与选股日同一天；`live_only=false` 供审计含回填
- 历史污染行（隔日写入却标成 `api:screen*`）在连 `palace.db` 时幂等改标为 `api:screen_backfill`

## 关键入口
`StrategyEngine`（domain/base）；`screen`（可带 `on_progress`）；
HTTP：`/api/strategies/*`、`POST /api/strategies/screen`（默认 `record_candidates=true`；多日请用异步接口）、
`GET|POST /api/screen/run`（异步进度 + 默认入库；支持 `start`/`end` 区间 ≤31 自然日，按交易日循环通用 `screen` + 同日同池入库）、`GET /api/screen/today?date=`、`GET /api/screen/history?live_only=`（默认真选）。

## 如何扩展
新战法：实现 Protocol，放 application/，在包 `__init__` 侧效 import 注册；声明 `entry_timing`。
Screen Skill 公式战法统一走 `src.formula.compile_screen_formula()` / `evaluate_screen_formula()`；不要在 `strategy` 再复制一套 parser/evaluator。Python Screen Skill 走 `application/screen_python.py`，与公式引擎共同适配为 `StrategyEngine`，不得另写选股、回测或 Job 链路。

## 给 Agent 的用法
- 注册战法：实现 `StrategyEngine`，放 `application/`，在包 init 侧效 import
- 产品目录当前仍包含 4 个战法：`qianlong-close-v3`（潜龙出海 V3）、`qianlong-tail-v1`（潜龙尾盘 V1）、`sanyuan-tail-v1`（三源尾盘共振，当前运行版本 V2）、`rsi30-dip`（RSI 超卖次日低吸）。三源 V1 作为版本历史归档，不新增第二个运行入口；海底捞月、潜龙 V2、三外有三及其他旧版源码快照只留在 `application/backup/` 或历史记录中，不会自动注册。
- `rsi30-dip` 当前默认口径为 `RSI14<22`、收阳、收盘位于日内区间上方 20%、价格不低于 5 元，默认股票池为主板+创业板（剔 ST、退市、停牌与上市不足 60 日）；`next_dip` 的 2% 预挂价和 T+2 退出口径不变。
- 潜龙 V3 在历史 V2 核心条件上增加 T 日换手率过滤，不改变 `entry_timing`、成交回测、持有期或止损止盈；活动目录中的每个版本都通过策略元数据声明当前版本和回测口径。
- V3 保留 V2 的核心突破条件，新增 T 日换手率 `2%≤turnover<8%`，并排除 T 日收盘达到按板块计算的涨停价的标的；涨停价只使用前一交易日收盘、板块规则和当前收盘，不读取 T+1。默认股票池为主板+创业板。T+1 的开盘分情景买入规则由 `entry_instructions` 元数据提供，不能把次日开盘缺口倒灌回 T 日选股信号。
- 潜龙 V3 / 尾盘声明 `screen_rank_factor=ROC5`（`CLOSE/REF(CLOSE,5)`）：选股 `picks` 按 ROC5 **降序**输出，入库候选 `score` 映射为五日涨跌幅%（夹到 0–100），列表按分排序时最强排最前。不改变信号真假，只改展示/入库顺序。
- 潜龙尾盘 V1 在同一核心条件上使用最低价 `10`、按当日 `CLOSE/REF(CLOSE,5)` 只保留一只候选；T 日 14:50 后理想化按未复权收盘价成交，T+1 触及 `+3%` 止盈或 `-6%` 止损，否则收盘退出。技术指标仍用 `qfq`，执行 OHLC 用 `none`，避免除权日把复权价当作真实成交价。
- 三源尾盘共振当前版本 V2：三条公开公式取 OR，收盘后 15:30 计算并按横截面评分先取原始前两只；随后要求双阴反包、市场上涨家数≥60%、T 日换手率 8%-12%、收盘位置 `CLV<0.5` 四项至少一项成立，失败不递补第三名。T+1 开盘买入、T+2 收盘卖出（成交回测 `hold_days=1`），默认股票池为主板+创业板；日线实现使用已完成的 T 日 OHLCV 与换手率，不把原始盘中公式的 `FROMOPEN>=210` 当作调度或成交时点。
- `next_dip` 表示 T 日收盘后生成次日预挂价；T+1 开盘低于目标价按开盘成交，否则最低价触及目标价才按目标价成交，未触价样本跳过。
- 递推指标可声明 `warmup_bars`；选股与回测都通过 `signal_history_bars` 使用同一预热长度，避免信号随面板加载起点漂移。
- 选股：`from src.strategy import screen, get`；入库：`application/persist.py`
- 必须声明 `entry_timing`；补前视审计测试
- 自定义策略目录：`infrastructure/custom/`
- Screen Skill 适配：`application/screen_formula.py` / `screen_python.py` 把包契约映射成同一个 `StrategyEngine`
- Python Screen Skill 的 import/compute 失败会回显诊断码、entrypoint、包内相对文件和有界 trace；不要退化为无上下文异常文本
- Screen Skill 可声明默认 `data.universe` 与 `data.adjust`；运行请求未覆盖时由 screen/backtest 使用，并在 `data_snapshot` 回显
- 异步进度状态：`application/screen_run.py`（内存快照，仿 bootstrap；进度日志用战法中文名，不暴露 `lugw-*` slug / `pool_id`）；交易日窗口：`application/screen_dates.py`
- 即时选股窗口含**今天**时，默认先 `apply_today_spot`（可用 `refresh_spot=false` 跳过），与 `job:screen` 对齐；避免盘中覆盖率个位数被体检阻断

## README 维护
新增/下线战法、改 Protocol、选股入口或入库默认行为时必须更新本文。

## 相关测试
`tests/strategy/`（含 `test_persist.py`）
