# 策略（strategy）

## 职责
战法协议、内置/自定义选股、审计与 AI 转换；即时选股结果可写入账本候选池。

股票范围统一由选股入口的股票池配置决定。活动内置战法的方法体不额外按板块、ST/退市名称、代码前缀、绝对股价或股本过滤；默认股票池仍可配置，显式范围应被遵守。形态所需的历史长度、有效行情、成交活跃度和真实涨跌停规则继续生效。

选股进度显示实际执行的热库同步、面板加载与信号计算；需要动态前视检查的实现另显示检查进度。区间选股保留逐日股票池、数据口径与入库规则。

策略代码验证与行情计算分开：`audit_policy` 只把中央清单中具体类型、计算方法、投影方法、能力声明与入场时点均匹配的受控内置实现识别为 `release-tested`。这些实现通过版本测试检查截断因果性，日常选股和回测不再重复执行验证用计算。内置子类、方法被替换的对象、自定义 Python 和公式仍走动态检查；调用方不能用自报 `pure/causal` 或同名 slug 获得豁免。显式 `guard_strategy` / `audit_strategy` 保留完整检查，新增或修改受控实现必须运行因果性、全部因子及输出等价测试。

受控内置的普通单日选股只计算目标日，不生成仅供验证使用的两日前缀，也不为一次性结果计算缓存指纹或做未来区间预计算。需要共享结果和动态检查的执行路径继续使用原有内容敏感缓存。结果快照的 `strategy_validation` 明示采用的验证方式；行情体检、数据版本复核、复权、真实交易价格与策略过滤条件不由此省略。

多日后台任务在 `screen_run_prepare.range_read_scope` 中按首日参数化预热起点至末日启用有界读取复用；所有日期仍调用同一个 `screen`，不把整段区间一次计算的结果直接当成逐日结果。单日、额外实时日、超预算和发生行情修改的场景仍按原语义读取。当日行情准备抽到 `ensure_screen_quotes`，失败继续阻断任务。

需要任务级计算复用时按实际输入内容校验。多个因果日期的指纹共用同一次调用内的递增前缀扫描，每个数值只扫描一次；下一次调用仍重新读取实际内容，价格原地修改、日期/代码轴、dtype、元数据及参数变化均会失效。乱序或重复日期轴回退逐日指纹。静态源码检查只在当前计算上下文内复用，键包含实际源码、入场时点与策略标识，返回独立报告；需要动态检查时保留真实截断与全列覆盖。

通用选股及普通成交/Horizon 回测报告入口从 `MarketStore` 直接取得 `compact` 来源证据，与原来完整装载后执行 `compact_job_result` 的传输摘要等价，保留事实、失败汇总和总数；`prepare_backtest_context` 默认保留 `full` 来源证据，供研究冻结上下文检查完整成功回执的严格 PIT 字段与拒绝 OHLC 事实。此边界减少报告读取和中间对象，研究门禁仍消费完整凭证。

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

### 倍量阴低开优选（未注册）

`double-volume-yin-low-open-v1` 保留实现但未注册到当前活动目录，以下为既有实现说明，未参与本轮股票范围调整。其设计使用两阶段流程。盘后准备任务与其它战法同档：
主租户 15:30、子租户沿用原有盘后错峰。该阶段复用正常行情补齐、健康检查、
股票范围与来源证据，只提取完整历史形态样本，不评分取前二、不写正式精选候选，
也不推送。样本按租户原子保存至 `screen_prepared/<slug>/<次交易日>.json`；
准备失败不会覆盖上一份有效产物，合法空样本与准备失败分别记录。

次交易日 09:25 固定运行、不错峰。仅对该日准备样本现场请求新浪开盘报价，
要求上游日期是当日、上游时间在 09:25–09:30、名称/真实开盘/前收参考与成交量有效。
晨间不打开 `MarketStore`，不读取行情仓或旧报价来补实时开盘；所有样本报价不完整
时不冒充完整排名。实时名称重新检查 ST/退市，实时前收与样本昨日收盘不一致
（例如除权）时拒绝该样本。目标日期、形态参数、历史窗口、版本、股票范围和
快照校验均通过后，才执行低开与大于 6 元的门槛。

仅支持沪深主板，创业板、科创板及北交所不进入形态候选或评分；
形态为主板大涨阳线（≥8%）后次日倍量阴（默认 ≥2 倍量），
截至大涨日近 10 交易日累计涨幅默认 ≤30%。不额外要求阴线高开或守实体中点。
晨间低位 60 分取截至昨日 60 日高低区间位置，均线接近 40 分取截至昨日
MA5/10/20 最近相对距离（3% 处归零）。总分四位，同分代码升序；真实东财行业
一级相同或消费分散组相同不得同时入选，缺行业组不补名额。默认最多精选 2 只。
任务、API 单日和异步入口使用同一实时链路，评分分项及准备/现场报价证据落库。
该流程不以事后日 K 或历史重放冒充现场遴选，也不自动买入；评分不表示胜率。

### 一线定乾坤·首板次日（已退役）

`yixian-auction` 已从活动策略目录、托管选股任务和天才交易员研究入口移除；生产中的
候选历史、任务回执、技能包版本历史与纸面舱也已按 slug 清理。模板源码保留在
`templates/skills/yixian-auction/`，仅供历史研究，系统禁止重新安装或启用。

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
选股/回测热路径使用 `guard_runtime_strategy` 按上述实现边界选择验证方式。动态路径调用 `guard_strategy`（`entry_timing=open` 裸用盘中字段为 block；动态截断：列数 ≤100 全量，否则按 `LOCI_AUDIT_PANEL_SAMPLE_SIZE`（默认 200、上限 500）**分片**跑截断一致性，全覆盖任一片 block 即 fail-closed）；正式 `signals` 与观察 `watch_signals` 都接受截断一致性审计；AI 转换/Python Skill 草稿同口径 fail-closed。

`GET /api/screen/run?view=progress` 仅返回进度、日志及槽元数据，以 `result_omitted=true` 标识省略结果；默认 `view=full` 的接口兼容原契约。前端共用在途进度读取和 1200 ms 采样周期，按当前查看策略或刚完成任务补读一次完整结果，历史已完成槽不会在普通页面冷启动时全部补读。相同进度保留对象引用，避免重复消费候选、日志与计时；重跑和取消通过世代与运行版本拒绝旧响应。

静态审计（`application/audit.py::audit_source`）按入场时点分档，与 Screen Formula 编译器 `_audit_entry_timing` 的白名单保持同一口径：
- `open`（9:25 竞价）：裸用当日 `close/high/low/volume/turnover/amount` → **block**
- `close`（尾盘 14:50 前后）：收盘价已定型可用，裸用当日 `high` / `low` → **block**（全天最高最低要等收盘才知道）
- `next_open` / `next_dip`：当日 OHLC 全部合法，只保留负向 `shift` 的 warn
- 任意时点下，当日字段被 `MA/EMA/HHV/SUM…` 等**含当根**滚动函数读取 → `intraday_field_rolling` **warn**：`MA(CLOSE,5)` 的窗口右端就是信号日本身。同样写法在公式编译器里是 `E_ENTRY_TIMING_LOOKAHEAD` 硬错误，Python 侧目前只报 warn（历史豁免，见 `LAGGING_CALLS`）
- 动态路径的截断探针会剔掉「截断到面板末日」那一格——那等于没截断，恒等通过。选股链路面板正好停在目标交易日，因此 `probe_dates=3` 实际是 2 个真探针
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
- 产品目录当前 5 个内置战法/指标：`qianlong-close-v3`（潜龙出海 V3.3）、`sanyuan-tail-v1`（三源尾盘共振 V2.7，15:30 收盘后托管）、`yangshi-tail-v1`（杨氏尾盘选股 V1.1，同样 15:30 托管）、`impulse-inside-breakout-v1`（大阳三日缩量突破 V1.4，手动运行）、`contraction-rebreakout-v1`（缩量回调后二次突破 V1.2，手动运行）。尾盘微右侧已按用户要求彻底退役，专属实现、目录、映射和调度入口删除，退役屏障阻止恢复。已下线不注册：`rsi30-dip`、`qianlong-tail-v1`、`lugw-haidi`（海底捞月，半年窗重测组合约 -24%）及三源 V1 / 潜龙 V2 / 三外有三等，源码仅留 `application/backup/`。潜伏两档（`qianfu-close` / `qianfu-1450`）与尾盘 14:50 两档（`sanyuan-tail-1450` / `yangshi-tail-1450`）已连同定时任务一起从仓库删除，不要恢复。
- 缩量回调后二次突破：`contraction-rebreakout-v1` 沿用固定通达信形态：T-12 至 T-3 有涨幅至少 5% 的阳线；T-2、T-1 两日收盘连续下降且各自量低于 MA(V,5)；T 日收阳上涨至少 3%、量至少为前日 1.5 倍、收盘突破此前 5 日高点。股票范围按统一配置，至少 31 根有效日 K；方法体不另加板块、名称、上市自然日或绝对股价门槛。未复权收盘涨停过滤按证券实际板块和 ST 规则计算（半入到分，低一分保留、盘中触板回落保留），声明 `requires_raw_limit_price`。评分为 10 日动量 40 分、回调缩量 15、回调深度 15、再突破放量 10、收盘位置 20；10 日涨幅达到 20% 时动量满分。完整股票池同日总分四位降序、同分代码升序，每日最多 2 只、不足不补。权重根据 2026-09-29 广康生化、芒果超媒案例校准，案例命中和同区间回测属于样本内、尚无独立样本外证据。`column_mode=coupled`，只用信号日及此前数据，最早次日开盘入场；不自动建立任务或推送。
- 大阳三日缩量突破：用户公式的五根 K 线形态；股票范围按统一配置，至少 180 根有效日 K；方法体不额外限制板块、ST/退市名称和绝对股价，6 元以下股票可参与。T-4 大阳实体高于此前 20 日均值、收盘高于 MA20；T-3 至 T-1 严格内包、实体收缩、三日均量低于大阳量；T 日收阳、放量并突破大阳高点。形态默认前复权，涨跌停高低价边界和距涨停至少 0.02 元使用完整未复权 OHLC（`requires_raw_limit_ohlc`）；今日触板后回落可入选，距涨停仅 0.01 元仍排除。保留形态条件与原形态分 `S0` 的四项构成：整理收敛 30、三日缩量 25、突破放量 25、收盘位置 20。最终评分改为 `0.7*S0 + 20*R*B(P) + 5*R + 5*U`（原形态 70、位置与修复 20、趋势 10）：`P` 为截至 T-5 的 120 日价格位置，`B(P)=clip(min(P/0.2,1,(1-P)/0.5),0,1)`，20%–50% 满舒适度、向两端递减；`R` 表示信号日收盘高于 MA20 且 MA20 高于 10 日前，`U` 表示 R 成立且 MA20≥MA60、MA60≥10 日前。上下文缺失时回退原分 S0，不额外剔除候选。在原条件合格股内按 0–100 最终评分每日最多取前 2 只，分数保留四位，同分按代码升序，不足两只不补足。该评分表示规则匹配程度，不是收益或胜率预测；本轮采纳基于已观察历史研究，未新增未来样本外验证。评分与上限在全量/投影计算中共用，选股、候选入库和回测同口径；横截面能力为 `coupled`。不设托管任务或交易参数；`entry_timing=next_open` 供通用回测使用，盘中结果需收盘确认。涨跌停比例所用名称/ST 状态沿用系统当前证券元数据，不声称历史状态逐日还原。
- 上述两条突破策略的历史目录摘要与成交回测模板来自 [2026 年 1 至 9 月复盘](../../docs/research/2026-10-03-chinext-breakout-review/report.md)：次日开盘、入场第 4 日收盘或 -6% 止损、往返费用假设 0.21%，另有固定 5/10/20 日比较。盈亏比为平均盈利/平均亏损绝对值，PF 为盈利总和/亏损总和绝对值，分开展示。真实行情来自线上只读隔离快照；当前名称/ST/成员目录、缺失历史来源收据以及沪深 300 参考基准的限制在报告列明，不作为严格历史时点或样本外业绩。
- 潜龙 V3.3 沿用 V3.2 的形态与排序：换手约 `3.5%≤turnover<8%`、上涨家数 breadth&lt;45% 时正式信号空仓、按**白线贴近度**（辰星线/CLOSE，刚站上白线优先）取 Top2、`next_open`、持有约 3 日、止损约 -7%；弱市中仅把已通过核心+换手条件的 Top2 放入 `watch_signals` 低吸观察，不改变原回测。V3.1 按 ROC5 降序取最热两只，全样本 2022/2023/2025 均净为负；V3.2 当时只换排序，V3.3 将股票范围收归统一配置并移除绝对股价门槛。旧版回测指标与配置已归档，当前版本不展示未经重跑的业绩。涨停价只使用前一交易日收盘、板块规则和当前收盘，不读取 T+1。股票范围遵守统一股票池配置。T+1 开盘分情景买入规则由 `entry_instructions` 元数据提供，不能把次日开盘缺口倒灌回 T 日选股信号。
- 潜龙声明 `screen_rank_factor=白线贴近度`（`辰星线/CLOSE`）：选股 `picks` 按贴近度**降序**输出（延伸最小排最前），入库候选 `score` 映射为贴近度×100（夹到 0–100）。`ROC5` 仍留在因子里只作成因，不再决定 Top2。
- 候选池 `score` 统一是 0–100 口径。战法可输出 `评分百分位` 因子（`application/score_percentile.py`），`persist.score_from_factors` 优先采用。三源的横截面评分 `4*r1+2*r5+1.5*r20+0.35*CLV+0.12*量比` 量纲约 1–3，旧版直接夹到 0–100 入库，最好的一只也只显示 1.x 分；现在入库分是该评分在**近 60 个交易日（含当日）三源候选**评分分布中的中位秩百分位：只读当日及以前数据，同日单调、不改变选股/信号/回测，跨日可比（弱市日排第一但绝对强度一般时如实偏低）。杨氏原先没有任何评分因子（入库 `score` 为空），现按排序因子“当日涨幅”在**近 40 个交易日条件候选**中的百分位入库（选股只加载 60 根日 K，40 日窗口在实盘与回测同口径）。原始 `横截面评分` 不再被当作 0–100 分。三源理由列先展示评分百分位、原始评分与 1/5/20 日涨幅、CLV，0/1 闸门标记排在后面。已入库的历史候选用 `python -m cli.market rescore [--since 日期] [--palace-db 路径]`（默认三源+杨氏，`--strategy` 可逗号指定）按新口径重算（逐日调用 `screen(..., data_snapshot={})`：不装载行情取证快照——那份快照为审计装载窗口内每只票的来源回执与 attempt，生产量级合成库实测单日峰值 3.9 GB，跳过后约 0.5 GB、多日不累积；默认预览，`--apply` 前自动备份账本；只改评分/理由/证据，不动真选来源与创建时间；多租户逐个传各自 palace.db）。
- 三源尾盘共振当前版本：三条公开公式取 OR；候选先过后置闸门，按横截面评分取前两只，不另设绝对股价门槛。breadth&lt;40% 时正式信号空仓，但闸门前合格 Top2 进入 `watch_signals` 低吸观察；观察不进入 `next_open` 回测或自动次日预案。T+1 开盘买入、短持退出（成交回测 `hold_days=1`），股票范围遵守统一股票池配置。**托管时点**：`sanyuan-tail-v1` 工作日 **15:30** 用已完成 T 日 OHLCV；14:50 现价代理档 `sanyuan-tail-1450` 已整档删除（定时与代码均不再存在）。日线实现不把原始盘中公式的 `FROMOPEN>=210` 当作成交时点。涨跌停计算仍使用未复权价格，避免前复权价格改变真实交易边界。
- 杨氏尾盘选股：保留涨幅 1%~5%、换手>2%、成交额≥3000万、非封板非一字的量价条件；股票范围统一配置，方法体不再附加绝对股价或流通股本门槛。上涨家数<40% 时正式信号空仓（合格 Top1 降级 `watch_signals`），否则按**当日涨幅降序**取 Top1；工作日 **15:30** 使用已定型收盘价。买入仍是 `next_open`、`screen_hold_days=2`（T+1 开盘买、T+3 收盘卖）、不设止损。原文第 6 条「净资产收益率>0.001%」因本仓无财务数据**未实现**，已记录在历史版本的 `backtest_config.unimplemented_source_rule`。原文条件与原执行维度研究见 [`docs/research/2026-08-yule-materials-tail-close-feasibility.md`](../../docs/research/2026-08-yule-materials-tail-close-feasibility.md)；历史收益仅代表当时条件及股票范围，不是放开范围后的新回测。涨跌停继续使用未复权价格及实际证券规则。
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
