# 策略（strategy）

## 职责
战法协议、内置/自定义选股、审计与 AI 转换；即时选股结果可写入账本候选池。

选股进度分别显示热库同步、面板加载、全股票范围前视检查和信号计算，耗时检查不再一直显示为“加载面板”。涨停大涨回落转强战法使用数组计算，保留原信号、因子、停牌压缩和浮点边界；区间选股继续逐日执行原有体检、前视检查与入库规则。

多日后台任务在 `screen_run_prepare.range_read_scope` 中按首日参数化预热起点至末日启用有界读取复用；所有日期仍调用同一个 `screen`，不把整段区间一次计算的结果直接当成逐日结果。单日、额外实时日、超预算和发生行情修改的场景仍按原语义读取。当日行情准备抽到 `ensure_screen_quotes`，失败继续阻断任务。

显式小股票池继续使用定向 SQL，避免为了少量标的预读全市场。潜龙的市场宽度面板改为一次数组广播，值与列序沿用原 Series 字典，扩展 dtype 仍走原构造；板块涨停比例面板也复用同一行比例，规则不变。

## 边界
依赖 market 面板与 formula。选股计算本身不写 market.db。
通过 `persist_screen_candidates` **写入** `palace.db` 的 `candidate_reviews`（API / Job / 异步选股共用）；同日同池**先清空再写入**。正式 `picks` 按原裁决写入；弱市 `watch_picks` 强制以 `decision=观察`、`tier=watch` 留档，不计入精选胜率。两类都为空时删除当日该池全部结果，不留旧票。

写入源分流：
- 真选：`job:screen` / `api:screen_run`（仅仓内最新交易日）/ `api:screen_today` / `api:screen`
- 回填：`api:screen_backfill`（区间或历史日）；**只替换同池回填行，不覆盖真选**
- `GET /api/screen/history` **默认** `live_only=true`：排除回填，且要求 `created_at` 与选股日同一天；`live_only=false` 供审计含回填
- 历史污染行（隔日写入却标成 `api:screen*`）在连 `palace.db` 时幂等改标为 `api:screen_backfill`

## 关键入口

### 一线定乾坤·首板次日（2026-09-12）

`yixian-auction` 是可编辑 Python Screen Skill，包在 `templates/skills/yixian-auction/`。
昨日首板 + 地量 + 放量 + KDJ/MACD 条件，今日仅按开盘涨幅选股。默认只选主板，
关闭 ST/退市/停牌过滤及额外上市自然日限制；无行业、市值、价格、宽度和 Top-N 限制。
18 个参数均在指标参数表编辑，定时任务不固定复制参数，下一次运行读取保存后的默认值。
详见 [指标说明与参数](../../templates/skills/yixian-auction/SKILL.md)。

Python 包的入口函数可带 `history_bars(params)`、`live_candidate_codes(panels,date,params)`
和 `strict_live_ohlcv=True` 属性。未声明者沿用原逻辑；声明者按有效参数计算预热长度，
并只向昨日条件合格股票请求严格实时报价。所有选股/回测入口传递实际参数给
`signal_history_bars`，热库不足时按原规则回退全量库。开盘入场指标不会因当天零量而丢弃
有效开盘价；缺失开盘字段仍不允许用现价回填。

`impulse-pullback-tail-v1`（涨停大涨回落转强·十日）已按用户要求从活动注册表下线，
删除其定时任务；源码仅供历史研究重放，不再自行注册。历史候选与研究记录保留。

`StrategyEngine`（domain/base）；`screen`（可带 `on_progress`；盘中选今天自动 `live_overlay`：实时日 K 叠内存，不写行情库）；
HTTP：`/api/strategies/*`、`POST /api/strategies/screen`（默认 `record_candidates=true`；多日请用异步接口）、
`GET|POST /api/screen/run`（异步进度 + 默认入库；支持 `start`/`end` 区间 ≤31 自然日，按交易日循环通用 `screen` + 同日同池入库；**进度按战法分槽**：`GET` 不带参返回聚合快照 `{...当前这一个, runs: {slug: 槽}, running_strategies}`，带 `?strategy=` 只看一个；`POST /api/screen/run/cancel?strategy=` 点名停一个，省略则停全部）、`GET /api/screen/today?date=`、`GET /api/screen/history?live_only=`（默认真选）、`GET /api/screen/history/batch`（多战法一次返回，供盘面）。
选股/回测热路径挂 `guard_strategy`（`entry_timing=open` 裸用盘中字段为 block；动态截断：列数 ≤100 全量，否则按 `LOCI_AUDIT_PANEL_SAMPLE_SIZE`（默认 200、上限 500）**分片**跑截断一致性，全覆盖任一片 block 即 fail-closed）；正式 `signals` 与观察 `watch_signals` 都接受截断一致性审计；AI 转换/Python Skill 草稿同口径 fail-closed。

静态审计（`application/audit.py::audit_source`）按入场时点分档，与 Screen Formula 编译器 `_audit_entry_timing` 的白名单保持同一口径：
- `open`（9:25 竞价）：裸用当日 `close/high/low/volume/turnover/amount` → **block**
- `close`（尾盘 14:50 前后）：收盘价已定型可用，裸用当日 `high` / `low` → **block**（全天最高最低要等收盘才知道）
- `next_open` / `next_dip`：当日 OHLC 全部合法，只保留负向 `shift` 的 warn
- 任意时点下，当日字段被 `MA/EMA/HHV/SUM…` 等**含当根**滚动函数读取 → `intraday_field_rolling` **warn**：`MA(CLOSE,5)` 的窗口右端就是信号日本身。同样写法在公式编译器里是 `E_ENTRY_TIMING_LOOKAHEAD` 硬错误，Python 侧目前只报 warn（历史豁免，见 `LAGGING_CALLS`）
- 动态截断探针会剔掉「截断到面板末日」那一格——那等于没截断，恒等通过。选股链路面板正好停在目标交易日，因此 `probe_dates=3` 实际是 2 个真探针
- 动态审计只保留探针日的正式/观察代码集合；下一次计算前释放上一份结果及因子矩阵，避免全量与截断结果同时驻留。探针日期、全列分片覆盖及阻断规则不变。
- 面板里可能混着**非 DataFrame 的元数据**（`__instrument_names__` 是 dict，由 `requires_instrument_names` 触发注入）。`audit_truncation` 只截 DataFrame、元数据原样透传，与 `audit_sampling` 的分片同一约定；漏了这层会让任何声明该 flag 的战法一进选股链路就 `AttributeError`（回归测试 `test_truncation_tolerates_non_dataframe_panel_entries`）

异步区间选股的数据范围由通用 `screen` 用例负责：逐日解析股票池与预热窗口后取来源证据，编排层不再预取无范围的全库 `data_snapshot`。这是逐日观察到的版本，不声称整段区间被冻结在同一个数据库快照中。 **但会在收尾时复核一次**：`screen` 返回前再读一次 `market_revision`（meta 单行查询，零成本），与取证时不一致就在 `data_snapshot` 里加 `revision_changed_during_run: true` 与 `market_revision_end`。一致时不加任何字段，旧契约不变。命中这条说明面板加载期间有人写过行情库——行情读写槽本该防住选股与同步撞车，所以它是要查的信号而不是正常现象。真做统一读事务的代价（热库重建单事务重写 700 日窗口期间 WAL 无法 checkpoint）远大于收益，强复现仍沿用 research 的冻结机制。

**所有**选股入口共用同一个热/全量选择判据 `src.market.hot_fallback_reason`：除近期完整性检查（窗口深度 + 末日是否跟上全量库）外，还校验从首个目标日的指标预热起点到区间末日的全部交易日；历史日/区间落在热库外、预热不足或中间缺日时回退全量库。预热长度由调用方 `signal_history_bars(engine)` 算好传进去（market 不得反向依赖 strategy），策略显式 `warmup_bars` 同样生效。

覆盖的五个入口：异步 `POST /api/screen/run`（`application/screen_run.py`）、同步 `POST /api/strategies/screen`（`api/router.py`）、`job:screen`（`src/ops/application/jobs/screen.py`）、Screen Skill 试跑（`application/screen_skills.py`）、助手战法工具（`src/ai/application/system_toolbus_strategy.py`，后两者经 `open_screen_store(..., trade_date=, warmup_bars=)`）。这条判据 2026-09 之前只有异步入口有，另外四个只过 `hot_unusable_reason`——那两条都是相对**今天**的判据，历史日一律放行，随后 `screener._resolve_start` 的 `max(0, len(days) - bars)` 无声钳位预热起点，选出的票少了也不报错，同步端点还默认 `record_candidates=true` 直接污染候选池胜率。改判据请只改 `hot_fallback_reason` 一处。

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
- 异步选股拆成两个文件：进度槽状态机在 `application/screen_run_state.py`（内存快照，仿 bootstrap；`_STATES[tenant][strategy_slug]` **双层分片** / 两级 LRU / 按战法 running 互斥 / 按战法协作式取消旗），交易日循环的执行体在 `application/screen_run.py`（进度日志用战法中文名，不暴露 `lugw-*` slug / `pool_id`）。`screen_run.py` 原样 re-export 状态机全部符号，历史导入 `from ...screen_run import _STATES` 继续成立且是同一个对象；交易日窗口：`application/screen_dates.py`
- **战法级多槽并发**（2026-08）：一个租户可以同时跑潜龙 / 三源 / 杨氏，各有独立进度条、日志、结果与取消旗。执行体入口 `execute_screen_run` 用 `screen_run_slot_scope(slug)` 把 ContextVar 绑到自己的槽，里面所有 `screen_run_update(...)` 无需传 strategy；`screen_run_try_begin` 只挡**同一战法**重复点击（`busy_reason='same_strategy'`），并发到顶返回 `busy_reason='tenant_limit'`。上限 `MAX_CONCURRENT_RUNS`（默认 3，`LOCI_SCREEN_MAX_CONCURRENT_RUNS` 可覆盖）——底层 `market_gate` 早就是「sync 独占写 / screen 共享读」，挡住用户的一直是这个上层单槽
- 即时选股窗口含**今天**时，默认先 `apply_today_spot`（可用 `refresh_spot=false` 跳过），与 `job:screen` 对齐；避免盘中覆盖率个位数被体检阻断

## 战法目录的租户分片

`application/catalog.py` 的 `_SHARDS` **按 `current_tenant()` 分片**，一个租户一份
`{slug: engine}` + `{slug: metadata}`。内置三个战法（`_REGISTRY`）仍然全进程共享——那是
代码事实；Screen Skill 不是，它是从**用户私有目录** `skill_root()` 编译出来的引擎。

**为什么不能用进程全局**：`POST /api/screen-skills` 任何登录用户都能调，它会
`save_screen_package()` 写自己的 `skill_root()`，再 `refresh_screen_strategy_catalog()`
把 `list_screen_packages()` 的结果 `replace_screen_engines()` 进目录。旧实现在这一行把租户
维度丢了，而 `replace_screen_engines` 是 `clear()+update()` **全量替换**，所以串味是双向的：
A 一保存战法，B 的战法当场从 `GET /api/strategies` 里消失，同时 B 看到 A 的私有战法。更重的是
`catalog.get(slug)` 被 `application/screener.py` 与 `src/backtest/application/runner.py` 直接
消费——**B 能跑 A 的代码**，而引擎的 `install_path` 指着 A 的租户目录。

**惰性加载回调怎么工作**：进程启动时 `src/app/main.py` 只刷了主租户，别的租户的分片一开始是
空的。`catalog` 不能 import `screen_skills`（那边已经 import 了 `catalog`，反向会成环），所以
用**回调注入**：`screen_skills` 在 import 期调用 `catalog.set_loader(refresh_screen_strategy_catalog)`，
`get()` / `all_strategies()` / `describe_all()` 读分片前先走 `_ensure_loaded(tenant)`——该租户
第一次被访问时回调 loader，用**他自己的** `skill_root()` 刷一次，之后 `loaded=True` 不再扫盘。
`replace_screen_engines()` 也会置 `loaded=True`（显式刷过就算加载过，否则下一次读会再惰性加载一遍
把结果盖掉）。加载失败按空目录处理并写日志，不让战法列表整个 500；下一次保存/更新会自愈。
`_LOAD_LOCK` 只串行化「加载」本身，读路径不被磁盘 IO 与包编译堵住；`_LOADING` 防 loader 重入。

**LRU 上限**：`MAX_TENANT_SHARDS = 64`。已编译的 Python Screen Skill 是活的模块对象加闭包，
50+ 租户各留一份能吃掉几百 MB，而服务器只有 1.1G（见 `application/screener.py` 顶部的内存约定）。
超出上限时按最近使用顺序淘汰最旧的分片，被淘汰的租户下次访问重新惰性加载，语义不变、只是慢一点。

同源问题的另外两处，改法一致：

- `application/screen_run_state.py` 的 `_STATES`（经 `application/screen_run.py` re-export）：选股进度（含完整
  `result.picks`）按 **`[租户][战法]` 两层**分片，外层 `MAX_TENANT_STATES = 64`、内层
  `MAX_RUNS_PER_TENANT = 6`，**再加一道全进程总闸 `MAX_TOTAL_RUN_SLOTS = 96`**（两个上限
  相乘不等于有界：64 × 6 = 384 份 `result.picks`，服务器只有 1.1 GB），三级 LRU 都**只淘汰
  已结束的槽**，且绝不淘汰调用方此刻正在写的那一个。running 互斥随之细化到战法：
  以前是进程级一把锁（A 在跑时 B 直接被判 busy = 跨租户 DoS），后来是每租户一把（同一个人
  跑潜龙时点不动三源），现在是每「租户 × 战法」一把。后台线程一律走 `spawn_tenant_thread`，
  裸 `threading.Thread` 会丢掉 ContextVar，把 B 的候选写进管理员的 `palace.db`。
- `src/market/application/realtime_signals.py` 的 `_fired`：key 是 `(租户, code, rule, 交易日)`。
  行情是全局共享事实，「谁已经被提醒过」是私人事实；带上限 `MAX_FIRED_KEYS` 与换日清理。

## README 维护
新增/下线战法、改 Protocol、选股入口或入库默认行为时必须更新本文。

## 相关测试
`tests/strategy/`（含 `test_persist.py`、`test_audit_sampling.py`、`test_audit_forward_peek.py`、`test_tenant_catalog.py`、`test_screen_run_tenant.py`、**`test_screen_run_multi.py`**（战法级多槽并发/隔离/并发上限）、`test_screen_run_cancel.py`）；实时信号去抖的双租户回归在 `tests/market/test_realtime_signals.py`
