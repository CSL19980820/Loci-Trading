# Vibe-Trading 数据层源码审计

> 审计日期：2026-08-04  
> 外部对象：[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) 固定 [commit `3a752d5a8ed088633040893de1cc9e6dc712596f`](https://github.com/HKUDS/Vibe-Trading/commit/3a752d5a8ed088633040893de1cc9e6dc712596f)  
> 方法：仅阅读固定提交源码和本仓当前工作树；未安装外部项目、未下载行情或真实财务数据。

## 结论

已有[对比研究稿](2026-08-vibe-trading-comparison.md)的 1.6 节概述了来源回退、OHLC、PIT 财务和历史成分。本稿补足源码级审计：Vibe-Trading 的数据层确有可借鉴实现，但不是可直接搬运的“可信数据仓”。

最该吸收的是三件事：**将数据来源/覆盖率/降级写入研究输入、仅用已披露日期的财务值、对历史股票池明确标识生存者偏差**。本仓当前 `MarketStore.data_snapshot()` 与 `source_evidence()` 已更适合做运行证据的基座；`temporal.py` 的可见时间和严格拒绝语义也比外部项目的静态回退更保守。

判定口径：`已实现` 指固定提交中有可执行代码路径；`仅声称` 指 README 描述不能由本次核验的调用层直接证实；`缺口` 指代码未留下所需证据或存在破坏严格语义的路径；`不应照搬` 指会削弱本仓 A 股研究可复核性。

## 映射矩阵

| 维度 | Vibe-Trading 固定提交的源码事实 | 判定 | 本仓映射与可借鉴点 |
|---|---|---|---|
| 数据源选择与回退 | `FALLBACK_CHAINS` 按市场给出有序来源；面向 Agent 的 `fetch_market_data()` 按检测来源分组，最多总计尝试 3 个来源，任一非空 `data_map` 即结束该组。标准回测入口 `fetch_data_map()` / `_fetch_auto()` 则会只对 `missing` 代码逐源补齐，仍缺失时 `raise`，并记录实际服务来源集合。显式 `local` / `qveris` 在注册层禁止悄悄回退到网络。证据：[registry.py#L117-L242](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/registry.py#L117-L242)、[market_data.py#L149-L214](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L149-L214)、[runner.py#L1076-L1155](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155)。 | 已实现；标准回测可逐代码补齐且 fail-closed，Agent 包装层仍是来源组级回退，二者都没有完整的逐代码 attempts/error receipt。 | [MarketStore.source_evidence()](../../src/market/infrastructure/store.py#L126) 已按查询范围汇总落盘来源、未解析代码和字段覆盖率。借鉴“逐代码补齐后仍不足即拒绝”与显式回退，而非复制多市场来源清单。 |
| OHLC/schema 边界 | `validate_ohlc()` 检查 high/low 包含 open/close、价格正性，可 `drop` / `warn` / `raise`；空帧或缺少任一 OHLC 列时原样返回。标准回测在所有数据抓取汇合后统一用默认 `drop` 清洗每个 frame；Agent 的 `fetch_market_data()` 并没有这个全局清洗点。证据：[base.py#L50-L119](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L50-L119)、[runner.py#L1260-L1287](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1260-L1287)。 | 回测执行路径已实现统一坏 bar 剔除，仍非严格 schema gate：缺列 frame 不会被拒绝，工具读取路径也可绕过统一校验。 | 本仓已在 [source_evidence()](../../src/market/infrastructure/store.py#L188) 给出 OHLC 非空覆盖率和 `invalid_ohlc_rows`。可补同步写入时的拒绝/回执，不应把缺列或坏 bar 送进权威回测。 |
| provenance / 失败回执 | `include_provenance=True` 时，每个成功返回的 symbol 只记录 `source`、请求/检测来源及 `fallback_used`；未返回的代码放入 `_unresolved`。它不输出完整 attempts、错误、提取时间、原始内容 hash 或供应商版本。证据：[market_data.py#L189-L214](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L189-L214)。 | 已实现最小 provenance；完整运行回执是缺口。 | 本仓 `source_evidence()` 的来源行、覆盖率、未解析代码和坏 OHLC 已可进入 [data_snapshot()](../../src/market/infrastructure/store.py#L93)。它诚实标记 `attempts_not_observed=true`，因此后续只应补同步层 receipt，不能伪造失败链。 |
| 缓存与版本 | 通用 loader cache 的 key 含 source/symbol/timeframe/时间窗/fields/内部版本，只缓存已结束日期；Parquet 与 metadata 各自通过 `os.replace` 替换，但两文件不是一个原子事务。Alpha bench 另有按 `universe_start_end` 命名的 pickle+HMAC 缓存，写入也不是原子替换。两者都不把供应商数据版本、抓取时刻或内容 digest 绑定到研究运行。证据：[base.py#L243-L263](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L243-L263)、[base.py#L284-L340](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L284-L340)、[base.py#L536-L562](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L536-L562)、[alpha_bench_tool.py#L122-L157](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L122-L157)、[alpha_bench_tool.py#L209-L268](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L209-L268)。 | 已实现性能和本地缓存完整性；可复现的数据版本仍是缺口。 | 本仓 [data_snapshot()](../../src/market/infrastructure/store.py#L101) 已固定 schema、quotes、复权因子、证券表摘要和 `market_revision`。可借鉴“只缓存已结算区间”；不应把 HMAC/pickle cache 当研究证据或另建平行行情仓。 |
| PIT 财务 | SEC loader 把值锚定在经 `normalize()` 的日级 `filed`，而非 `period_end`，并在 `pit=True` 时保留同一报告期最早 filing；稀疏值只从 filed 日向后填充。证据：[fundamentals_loader.py#L47-L131](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L47-L131)、[fundamentals_loader.py#L169-L193](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L169-L193)、[fundamentals_loader.py#L292-L300](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L292-L300)。 | 已实现日级 filed-date PIT；修订事实时间线和披露时刻仍是缺口：`pit=True` 丢弃同报告期较晚 restatement，无法表达“较晚日期已知的修订值”。 | [PointInTimeObservation](../../src/research/domain/temporal.py#L26) 已有 `available_at`、`published_at`、`revision`、`restated`、来源字段；[select_point_in_time()](../../src/research/domain/temporal.py#L70) 按可见日选择。应接真实披露源后再启用，不能以当前财务值回填历史。 |
| 历史股票池 | CSI300 从 Tushare `index_weight` 取历史成分并按日期 mask；`pit_membership`、`survivorship_bias`、`degraded` 与来源日期只写进内存 panel 的 `_meta`。Alpha bench 随后的 HTML context 和工具返回均未携带 `_meta`，也不因 `degraded` 拒绝运行；失败时仍用手工 30 只静态名单继续 bench。证据：[alpha_bench_tool.py#L304-L463](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L304-L463)、[alpha_bench_tool.py#L878-L937](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L878-L937)。 | 内部已实现掩码和降级 metadata，但公共结果缺少该状态且无严格 gate；mask 在首个可得快照之前使用 `.bfill()`，可能把未来成分回填。 | [MembershipSnapshot](../../src/research/domain/temporal.py#L95) 保留来源、revision 和偏差标记；[resolve_membership()](../../src/research/domain/temporal.py#L133) 只取 `as_of` 当日以前快照；[assert_strict_membership()](../../src/research/domain/temporal.py#L159) 会拒绝 degraded/生存者偏差输入。这个严格边界应保留。 |
| README 的“缺失代码自动补齐”表述 | README 称 partial market-data 会沿回退链补齐缺失 symbol；该表述由标准回测 `_fetch_auto()` 的 `missing` 循环及最终 `raise` 直接支持。`fetch_market_data()` 的确会在任一非空 `data_map` 后结束该来源组循环并返回 `_unresolved`，但它是 Agent 数据读取包装层，不能据此否定 README 对回测路径的表述。证据：[README.md#L73](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/README.md#L73)、[runner.py#L1076-L1155](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155)、[market_data.py#L149-L214](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L149-L214)。 | README 对标准回测路径属实；工具读取路径与其语义不同，且都不能替代逐代码运行回执。 | 本仓 run card 仍应只引用已写入的 `data_snapshot` / source receipt；可吸收“补齐后仍缺失即失败”，而非只记录一个来源名。 |

## 对本仓的可落地启发

1. 将 `data_snapshot` 作为每次研究运行不可变输入：保留 `market_revision`、复权因子摘要、`source_evidence`、查询范围和股票池快照，而不是只写一个来源名。
2. 同步层输出结构化 receipt：每个代码/字段记录请求来源、尝试序列、最终来源、失败原因、落盘行数和 OHLC 拒绝数；没有 telemetry 时继续保留 `attempts_not_observed`。
3. 财务/成分供应商接入仅允许追加式 PIT 事实和历史快照；`available_at` 或历史名单不足时，普通研究标 `degraded`，严格研究直接拒绝。
4. 缓存只解决性能：缓存 key 可参考“已结算日期 + 输入维度”，但 run card 必须引用行情仓 revision/content digest，不能引用机器本地 cache path。

## 不应照搬

- 不引入覆盖多个市场的长回退链或手工蓝筹 fallback 来“保证有结果”；A 股研究应宁空勿弱，严格模式数据不足即阻断。
- 不保留 `.bfill()` 的历史成分逻辑；它会在最早可得快照之前引入未来信息。
- 不将 `warn` 的坏 OHLC 或缺列帧视为可回测输入；权威回测应使用明确的拒绝或降级契约。
- 不把 cache HMAC、来源名或 README 文案当成数据版本；它们不能证明本次运行使用了哪一版供应商数据。
- 不将“最早 filing”简化为完整的财务 PIT；需要保留后续公告、重述及其各自可见时点。
