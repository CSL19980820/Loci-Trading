# Vibe-Trading 数据层一手证据

> 核验日期：2026-08-04
>
> 对象：[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading)，固定提交
> [`3a752d5`](https://github.com/HKUDS/Vibe-Trading/commit/3a752d5a8ed088633040893de1cc9e6dc712596f)。
> 证据仅来自该仓 README、依赖/配置入口和该提交的 GitHub 源码；未下载行情、未运行其回测。

## 结论

1. **没有观察到单一、明确命名为“研究稿”或“数据层设计”的规范文档。**README 是产品说明和版本变更记录；真正的契约分散在 loader 注册表、通用 loader、回测 runner 与 Agent 数据工具。README 只承诺“缺失标的沿回退链补齐且 fail-closed”，不是可重现实验的数据版本规范。[README#L68-L73](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/README.md#L68-L73)
2. **它是多来源获取层，不是版本化数据仓。**标准回测实际使用 `fetch_data_map()` 的 `DataFetchResult(data_map, source, effective_sources)`；auto 模式逐代码补齐缺失数据、仍缺即抛错，随后统一清洗 OHLC，再把同一 `data_map` 交给引擎。[runner.py#L57-L66](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L57-L66) [runner.py#L1076-L1155](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155) [runner.py#L1158-L1287](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1158-L1287)
3. **可借鉴的是数据不足时拒绝运行、集中 OHLC 校验和显式实际来源；不能把本地缓存或来源名当数据版本。**源码未见逐请求/逐代码 attempts、失败原因、抓取时刻、原始内容 digest 与供应商版本构成的完整 run receipt。

## 实际数据链

| 环节 | 可证实的实现 | 证据与边界 |
|---|---|---|
| 来源与获取 | 注册表维护按市场的有序 `FALLBACK_CHAINS`，并解析可用 loader；代码路径覆盖 A 股的 Tushare/AKShare/Tencent 类来源，以及 Yahoo/yfinance、OKX、Binance、CCXT、pykrx 等多市场 loader。显式 local/QVeris 不允许静默网络回退。 | [registry.py#L117-L242](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/registry.py#L117-L242)。具体可用性仍取决于运行期凭据、可选依赖和网络，不能把注册表当“本次已用来源”。 |
| 缺失补齐 | 回测 auto 路径对 `missing` 标的逐个 fallback source 补齐，最终仍缺会 `raise NoAvailableSourceError`，避免静默缩小股票池。 | [runner.py#L1076-L1155](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155)。这是回测入口语义；Agent `fetch_market_data()` 是按来源分组的便利包装，成功返回后仅保留最小 provenance。[market_data.py#L95-L214](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L95-L214) |
| 清洗 | `validate_ohlc()` 统一检查 high/low 包含 open/close 与价格正性；runner 在所有来源汇合后调用 `_sanitize_data_map()`。 | [base.py#L50-L119](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L50-L119) [runner.py#L1260-L1287](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1260-L1287)。缺列/空帧并非同一个严格拒绝契约，Agent 读取路径也不是此统一清洗点。 |
| 本地存储与缓存 | 通用 loader 用 source、symbol、时间窗、interval、fields 和内部版本构造 cache key；已完成区间存为 Parquet 及 sidecar metadata，并用 `os.replace` 替换。 | [base.py#L243-L340](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L243-L340)。Parquet 与 metadata 的替换不是一个跨文件事务；缓存没有绑定供应商版本或内容 digest。 |
| 回测输入与追溯 | `fetch_data_map()` 返回数据与 `effective_sources`；runner 将实际来源写入 run-card 配置，并用已抓取/清洗的同一 `data_map` 驱动引擎。 | [runner.py#L940-L970](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L940-L970) [runner.py#L1158-L1299](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1158-L1299)。`effective_sources` 是来源集合，不足以复现精确数据版本；Agent 的 `include_provenance` 也只输出成功 symbol 的 source/requested/detected/fallback 字段。[market_data.py#L189-L214](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L189-L214) |
| PIT 扩展 | SEC fundamentals 以 `filed` 日，而非报告期末，做日级可见性；`pit=True` 使用同一报告期最早 filing 并前向填充。 | [fundamentals_loader.py#L47-L193](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L47-L193)。这不是完整修订事实链：较晚 restatement 的可见时间线不能由“最早 filing”表达。 |

## 对 stock-analyzer 的取舍

- **可借鉴：**保留“逐代码补齐后仍缺即拒绝”的 fail-closed 语义；将 OHLC 校验置于所有来源汇合后的单一边界；研究运行记录实际来源而非用户配置的来源名。
- **应强化：**以 `MarketStore.data_snapshot()`、`market_revision`、quote/spot receipt、查询范围和股票池快照组成 run card。失败、skip、fallback、字段覆盖与坏 OHLC 必须是持久化证据，而不是运行日志。
- **不能照搬：**不以 Parquet cache、HMAC 或 `effective_sources` 代替数据版本；不引入为“总有结果”而设的静态股票池回填；财务 PIT 不能只保留最早 filing，必须保留披露、修订和各自 `available_at`。

## 限制

固定提交的 GitHub raw 源码已逐项读取；GitHub tree API 对该提交返回 404，因此“未观察到独立设计稿”是基于 README 与已核验源码入口的保守结论，不能证明仓库历史上绝无其它设计材料。
