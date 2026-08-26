# Vibe-Trading 数据层源码复核（2026-08-05）

> 外部对象：[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading)，固定提交 [`3a752d5a8ed088633040893de1cc9e6dc712596f`](https://github.com/HKUDS/Vibe-Trading/commit/3a752d5a8ed088633040893de1cc9e6dc712596f)。
>
> 方法：只读该提交的 README、`.env.example`、`requirements.txt` 和数据/回测源码；未安装其依赖、未配置任何凭据、未请求第三方行情、未运行其回测。因此本文只陈述静态源码可证明的行为，不把 README 的能力描述当作运行成功或数据质量证明。

## 结论

1. **它是运行时多源抓取加可选本机缓存，不是以不可变行情快照为中心的数据仓。**标准回测会记录实际成功的来源集合并在代码缺失时失败；但缓存键不含供应商版本、抓取时刻或原始 payload 摘要，不能单独作为研究输入版本。
2. **PIT 只有局部实现，不可泛化为全链路保证。**SEC 财务 loader 明确以 filing 日可得；CSI 300 Alpha bench 虽尝试拉历史 `index_weight`，但会在失败时退化为手工名单，并对 membership 同时 `ffill()` 和 `bfill()`。上游 Research Lab 自己也明确承认其公开 GTJA 191 实验使用当前 CSI 300 成分回填全历史，存在生存者偏差。
3. **“面向 Agent 的行情读取”和“标准回测输入”语义不同。**前者最多尝试三个来源，可返回部分结果和 `_unresolved`；后者对剩余缺失标的抛错。前者不应被当作本仓严格研究/回测的输入契约。
4. **最值得借鉴的是来源与失败显式化，不是多源数量或默认回退。**stock-analyzer 应继续以单市场持久化行情、范围化来源回执、`market_revision`、冻结输入和严格 PIT 门禁为主；不应引入以“尽量补齐”为目标的跨源混合默认值。

## 1. 数据来源与抓取路径

### 1.1 来源目录和路由

README 将 `get_market_data` 描述为按代码/市场选择来源、再沿回退链尝试；A 股链为 `tencent -> mootdx -> eastmoney -> baostock -> akshare -> tushare -> local`，并列出哪些来源需要 token、SDK 或本地服务。[README 数据源表与链](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/README.md#L332-L394)

源码注册表是这一能力的实际入口：`VALID_SOURCES` 和 `_loader_modules` 列出可注册 loader；缺少可选依赖时导入异常被吞掉；`FALLBACK_CHAINS` 定义各市场顺序。`resolve_loader()` 逐个构造并调用 `is_available()`，所有候选不可用才抛 `NoAvailableSourceError`。[registry.py#L23-L188](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/registry.py#L23-L188)

README 写“23 个免费源”，而当前 `VALID_SOURCES` 有 24 个具体来源名（另加 `auto`）；README 的数量宣称与注册表不完全同口径，应以固定提交的可用 loader/凭据/依赖实际探测为准，不能以宣传数字作为一次研究的来源清单。[README 数据源表与链](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/README.md#L332-L362) [registry.py#L33-L59](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/registry.py#L33-L59)

`local` 和 `qveris` 在**注册表的显式来源解析**中被列为不得静默退到网络的来源；不可用时应抛带配置说明的错误。[registry.py#L117-L124](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/registry.py#L117-L124) [registry.py#L191-L242](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/registry.py#L191-L242)

### 1.2 Agent 行情接口：允许不完整结果

`fetch_market_data()` 按代码模式分组，默认 `source="auto"`；每组构造来源链并限制为最多三次尝试。loader 构造或抓取异常只写日志，最终没有取得的代码放进 `_unresolved`；仅在 `include_provenance=True` 时，为成功返回的代码附简单来源字段。它还会按 `max_rows` 对返回行抽样。[market_data.py#L14-L54](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L14-L54) [market_data.py#L95-L214](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L95-L214)

这与注册表的显式 `local`/`qveris` 保护存在需要上游回归测试确认的差异：该函数会自行根据 `FALLBACK_CHAINS` 展开尝试列表，并在 `NoAvailableSourceError` 后继续下一候选；代码中没有为这两个来源保留 `_NO_NETWORK_FALLBACK_SOURCES` 的专门分支。静态路径表明它**可能**绕开注册表的 fail-closed 意图，是否最终命中网络还取决于所传代码及各 loader 的运行时行为，本文不把它表述为已实测泄漏。[market_data.py#L136-L181](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L136-L181)

### 1.3 标准回测：缺失标的 fail-closed，但仅记录来源集合

标准回测的 `auto` 路径先按市场获取数据，再只对**返回结果中缺失**的代码沿链补齐；仍有缺失时抛 `NoAvailableSourceError`。首个 `loader.fetch()` 调用本身没有包在该函数的回退 `try` 块中，因此它直接抛异常时可中断运行，而不是保证自动切到下一来源。成功来源被合并进 `_actual_sources`，随后 `fetch_data_map()` 作为 `effective_sources` 返回，并在主流程中写入 run-card 使用的配置字段。[runner.py#L1076-L1155](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155) [runner.py#L1158-L1267](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1158-L1267) [runner.py#L940-L951](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L940-L951)

在抓取结果汇合后，runner 对每个 frame 执行 `validate_ohlc()`。默认策略是删除 high/low/open/close 违反不变量或非正价格的行；空帧和缺少 OHLC 列的 frame 原样返回。这是统一质量检查点，但不是“缺列必拒绝”的严格 schema gate。[base.py#L50-L119](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L50-L119) [runner.py#L1270-L1287](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1270-L1287)

## 2. 存储、缓存与回放边界

### 2.1 持久化位置

环境示例说明 sessions、run artifacts、uploads、索引等默认在 `~/.vibe-trading`；本机行情 cache 默认关闭，开启后位于 `~/.vibe-trading/cache/loaders/`，并明确要求市场数据不要落在 checkout 内。[.env.example#L186-L209](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/.env.example#L186-L209)

loader cache 的默认根目录和 opt-in 开关由 `DataConfig` 读取；缓存根可以通过环境变量改写。[env_schema.py#L150-L180](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/config/env_schema.py#L150-L180) [base.py#L243-L281](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L243-L281)

依赖清单直接列出 `pandas`、`numpy`、`scipy`、`bottleneck`、`duckdb`，以及 `tushare`、`yfinance`、`akshare`、`ccxt` 等 provider SDK；这证明运行时依赖面很宽，但不证明任一 provider 在某次研究中实际可用或实际命中。[requirements.txt#L16-L22](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/requirements.txt#L16-L22) [requirements.txt#L38-L45](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/requirements.txt#L38-L45)

本地 Data Bridge 还可从 `~/.vibe-trading/data-bridge/config.yaml` 读取 CSV、Parquet 或只读 DuckDB。它是用户自带数据的桥接层，而不是项目维护的版本化行情仓。[local_loader.py#L1-L29](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/local_loader.py#L1-L29) [local_loader.py#L202-L216](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/local_loader.py#L202-L216)

在已核验的 loader、标准回测和 Alpha bench 路径中，数据由运行时 provider、Data Bridge 或上述本机 cache 进入 DataFrame；本次审查范围内**未见**一个由这些路径消费的、全市场不可变行情快照仓。这个是“已查路径中的未发现”，不是对整个项目所有目录的否定性证明。

### 2.2 cache 的确定行为与不足

cache key 只由内部版本、`source`、`symbol`、`timeframe`、日期窗和 `fields` 构成；只有结束日严格早于本机当天的区间可缓存，以免固定仍在形成的 bar。读 miss、损坏文件和写失败都是非致命，继续请求 live provider；Parquet 与 metadata 通过临时文件后 `os.replace()` 写入。[base.py#L284-L340](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L284-L340) [base.py#L343-L459](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L343-L459) [base.py#L536-L569](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L536-L569)

因此可借鉴“未结算日期不缓存、缓存失败不拖垮抓取、原子替换”的工程思想；但 cache key 没有供应商数据 revision、抓取时刻或原始响应摘要，**不能把 cache 命中或本机路径当成可复现实验的输入证据**。

Alpha bench 另有带 HMAC 完整性校验的 pickle 面板缓存。该实现仍不是供应商版本、请求回执或冻结行情 manifest。[alpha_bench_tool.py#L96-L157](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L96-L157)

### 2.3 run card 不等于冻结行情输入

`write_run_card()` 会保留配置 hash、可选策略文件 hash、调用方提供的 `data_sources`、标量指标、告警和 artifact 的 SHA-256。其回测摘要只含代码、时间范围、周期、引擎、初始资金和 `source` 等配置字段；该函数本身没有将实际 DataFrame、逐标的来源、请求尝试、payload digest 或行情 snapshot hash 写入 card。[run_card.py#L13-L95](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/run_card.py#L13-L95) [run_card.py#L147-L167](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/run_card.py#L147-L167)

结论：它可帮助定位一次运行的策略/配置/artifact，但仅凭该 card 不足以保证重放同一份修订后的外部行情。

## 3. 时间一致性与 PIT

### 3.1 有明确 PIT 规则的局部：SEC 与 A 股财务

SEC fundamentals loader 的核心规则是以 `filed` 而非 `period_end` 作为可见时点；`pit=True` 时同一报告期保留最早 filing，稀疏值按 filing 日向后填充。源码同时承认 SEC companyfacts 可能混合真季度、年初至今和年度口径，仍需要逐发行人规范化。[fundamentals_loader.py#L1-L10](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L1-L10) [fundamentals_loader.py#L47-L131](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L47-L131) [fundamentals_loader.py#L169-L185](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L169-L185)

这只能证明 SEC 这一支的日级可得性设计，不能证明 A 股财务、公告、停复牌、复权因子和指数成分都 PIT-safe。

A 股 Tushare fundamentals 路径也以公告/实际公告日期裁剪数据，并使用 `merge_asof` 对齐交易日；这是另一条局部 PIT 机制。它同样不等于所有 Tushare 行情字段、指数成分和外部来源都有可验证的 `available_at`，更不能替代一次运行冻结的实际 observation 集合。[tushare_fundamentals.py#L145-L230](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/tushare_fundamentals.py#L145-L230) [tushare_fundamentals.py#L264-L377](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/tushare_fundamentals.py#L264-L377)

### 3.2 CSI 300 bench：尝试历史成分，但仍有退化与前视边界

当前 Alpha bench 在窗口起点前回看 60 天以获取 Tushare `index_weight`，以历史快照构建 membership；请求失败则改用 30 只手工蓝筹，并写入 `degraded`/`survivorship_bias`/`pit_membership` 元数据。[alpha_bench_tool.py#L304-L368](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L304-L368) [alpha_bench_tool.py#L450-L463](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L450-L463)

membership mask 在重建时执行 `.ffill()` 后又执行 `.bfill()`。在请求起点以前没有可用快照时，`bfill()` 有使用后续名单补早期日期的风险；因此即使 `pit_membership=True`，严格研究仍须检查首个快照、每段覆盖和实际 meta，而不能把布尔标记直接视作 PIT 证明。[alpha_bench_tool.py#L432-L456](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L432-L456)

### 3.3 公开研究稿的直接披露

上游 Research Lab 的 GTJA 191 文本明确说它是截面 IC study，非交易成本、仓位约束齐全的 PnL 回测；其输入为 Tushare 日频 OHLCV/turnover，VWAP 从 amount 推导，缺少逐笔和 order-book 数据。[研究方法](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L296-L355) [数据范围](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L533-L538)

同一页面明确披露：该实验把当前 CSI 300 成分用于整个 2018--2025 窗口，存在生存者偏差，并把真正的 point-in-time 成分列为计划升级。该研究稿不能被引用为“已完成 PIT 股票池”的证据。[研究稿 caveat](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L547-L557)

### 3.4 执行时点不等于通用前视门禁

BaseEngine 将信号后移一根 bar 后以后一根开盘执行，这是一条值得借鉴的执行时点语义。[base.py#L135-L215](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/engines/base.py#L135-L215)

但 `SignalEngine.generate(data_map)` 接收完整历史面板；已核验的输入协议/调用点没有为用户策略建立通用的 `as_of` 列级访问限制。由此不能推定每个策略都有前视偏差，却也不能把执行层的一根 bar shift 当作所有用户信号天然 PIT-safe 的证明。[loader protocol](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L618-L643) [BaseEngine signal 调用](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/engines/base.py#L640-L685)

## 4. 回测/研究输入、凭据与失败处理

### 4.1 输入契约

标准回测配置要求至少有 `codes`、`start_date`、`end_date`，并可带 `interval`、`source` 和 `extra_fields`；runner 会将实际使用的来源以 `effective_sources` 传递到运行流程。[runner.py#L60-L89](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L60-L89) [runner.py#L1158-L1267](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1158-L1267)

研究稿给出的复现配方是安装、设置 `TUSHARE_TOKEN` 和运行 CLI，产物为 `~/.vibe-trading/reports/` 下的 HTML。它没有同时发布输入行快照、供应商版本、下载时间、原始响应摘要或逐次来源回执；“可以再次运行命令”不等价于“可以重放同一输入”。[研究稿复现段](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L567-L584)

### 4.2 凭据

`DataConfig` 集中定义 Tushare、Futu、Finnhub、Alpha Vantage、Tiingo、FMP、FRED、IwenCai、SEC User-Agent、QVeris、Longbridge 等数据源变量，默认都是空值或受控默认值。[env_schema.py#L150-L180](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/config/env_schema.py#L150-L180)

`.env.example` 将 Tushare 标为 A 股 token，并把若干 API-key 来源标为“未设置就静默跳过”；Tushare loader 本身也只有 token 非空且非 placeholder 时才 `is_available()`。它对复权因子请求失败会丢弃该代码，而不是在原始未复权价格上回测。[.env.example#L142-L173](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/.env.example#L142-L173) [tushare.py#L51-L72](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/tushare.py#L51-L72) [tushare.py#L108-L200](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/tushare.py#L108-L200)

### 4.3 失败语义总结

| 场景 | 源码行为 | 对严格研究的含义 |
| --- | --- | --- |
| 可选 loader 缺依赖/缺凭据 | 注册时或构造时跳过，回退链继续尝试。 | “最终有数据”不代表预期来源可用。 |
| Agent `fetch_market_data()` 失败 | 记录日志、继续候选、最后返回 `_unresolved`，成功项目的 provenance 是可选且简化的。 | 必须将 `_unresolved`、尝试链和抽样状态升级成硬门禁/回执，不能把部分字典直接交给回测。 |
| 标准回测首个 loader 直接抛异常 | `_fetch_auto()` 的首个 `fetch()` 未由该函数捕获。 | 不应假设所有异常都会自动回退；失败报告须区分“无行返回”与“请求中断”。 |
| 标准回测仍缺代码 | 抛 `NoAvailableSourceError`。 | 可借鉴 fail-closed；还应保存逐代码的请求、失败、fallback 和字段覆盖，而不只保存来源集合。 |
| 坏 OHLC | 默认丢行。 | 可借鉴统一校验位置，但本仓严格路径应拒绝并留下质量证据，不能静默删行改变样本。 |
| cache 读写失败 | 非致命，转 live provider。 | cache 是性能层，不能掩盖本次输入来源变化。 |

## 5. 对 stock-analyzer 的采纳边界

### 可借鉴

1. **区分 requested source 与 actual source。**在本仓既有行情同步回执上保留逐代码、逐字段的请求源、每次尝试、最终命中、fallback、未解析代码和失败原因；回测/研究 run 冻结后只引用该次回执和 `market_revision`。
2. **坚持缺失 fail-closed。**严格回测要求全股票池、执行 OHLC、复权、时间范围和来源证据完整；允许降级的研究也必须显式标为 `degraded`，不能进入策略默认参数或假设通过结论。
3. **将可得性建模为数据字段。**财务/公告用 `published_at`/`available_at`，指数成分用历史快照日期和来源版本；严格 PIT 禁止任何未来名单回填早期日期。
4. **把缓存限定为性能层。**可借鉴结束日已结算才缓存与原子写入；仍要以本仓已持久化快照、内容摘要和 artifact hash 作为研究重放依据。
5. **复用统一 OHLC 质量门。**在数据进入回测前一次性校验结构、覆盖率、停牌/缺失处理和复权状态，并把拒绝原因写入 run card，而非只在 logger 中出现。

### 不应照搬

1. **不把多源自动回退作为 A 股研究默认。**供应商在复权、停复牌、交易日、代码映射和历史修订上可能不一致；只有用户明确授权并且每代码回执、字段一致性和覆盖率都合格时，才可作为可审计的备源。
2. **不把 Agent 工具的部分/抽样返回作为回测面板。**`_unresolved`、`max_rows` 抽样和简化 provenance 对交互答复有用，对净值、因子和 OOS 统计不是充分输入。
3. **不复制 `bfill()` 或手工蓝筹名单来“保住”历史实验。**缺少请求日以前的历史成分时，严格 PIT 应拒绝；非严格路径也只能报告偏差，不能补出看似完整的历史宇宙。
4. **不把 run card、HTML 或 cache path 当成数据版本。**本仓应冻结实际消费的行、来源 receipt、`market_revision`、PIT observation/membership 版本、参数及 hash；相同命令/来源名不构成相同输入。
5. **不扩大为 20+ 外部 provider、多个密钥和本地 SDK 的运行边界。**本仓当前的 A 股单市场、数据归档和最小权限边界更适合先保证证据完整性；任何新源须先做只读历史验证，不改活动策略默认值。

## 6. 核验边界与已运行的只读检查

- 已运行 `git ls-remote https://github.com/HKUDS/Vibe-Trading.git HEAD`，得到上文固定提交。
- 已通过 GitHub REST commit API 和固定提交的 `raw.githubusercontent.com` 内容读取 README、`.env.example`、`requirements.txt`、registry、loader base/Tushare、Agent market-data helper、runner、run card、SEC fundamentals、Alpha bench 与 Research Lab 页面。
- 已使用本仓现有 CodeGraph 只读核对 `src/market`/`src/research` 当前公开契约，用于上述采纳边界；未修改这些模块，也未运行外部项目或外部行情调用。
- 结论锁定在该提交；上游未来提交、供应商返回的数据版本、实际 token 权限和网络失败表现均需另行实测。
