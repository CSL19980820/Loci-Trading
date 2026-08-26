# Vibe-Trading 数据层一手研究

> 核验日期：2026-08-05  
> 上游对象：[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) 固定提交 [`3a752d5a8ed088633040893de1cc9e6dc712596f`](https://github.com/HKUDS/Vibe-Trading/commit/3a752d5a8ed088633040893de1cc9e6dc712596f)  
> 方法：只读官方 GitHub 仓库及其随仓发布的 Research Lab 页面；未安装上游依赖、未请求第三方行情、未运行回测。  
> 标签：**研究稿明确** = Research Lab 正文直接陈述；**仓库实现** = 固定提交源码或 README 直接可见；**推断** = 从已列代码/正文能得出的有限工程结论，不把它写成作者声明。

## 结论

1. **尚未核验到 Vibe-Trading 的正式论文或独立数据规范。**本次能定位的一手研究性正文是仓库内的 Research Lab 文章 `alpha-191-in-2026.html`；它明确描述了 GTJA 191 实验的数据源、字段和局限，但不是端到端的数据摄取、版本与复现规范。[研究页的方法段](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L296-L355) [数据范围与复现段](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L533-L584)
2. **研究稿中的实际输入比产品数据能力窄得多。**该实验写的是 Tushare 日频 OHLCV、turnover 和由 amount 推导的 VWAP；README 所列 23 个免费数据源、跨市场回退链和 `local:` 桥接是仓库产品能力，不能倒推为研究稿实际使用的数据集。[研究稿数据范围](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L533-L538) [README 数据源说明](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/README.md#L332-L394)
3. **point-in-time 不能因“有历史日期”而默认成立。**研究稿直接承认 CSI 300 用当前成分回填 2018--2025，存在生存者偏差；当前源码虽开始读取 `index_weight` 历史快照并标注 `pit_membership`，但掩码同时使用 `.ffill()` 和 `.bfill()`，因此在缺少请求起点以前快照时仍须逐次验证，不能无条件宣称完全 PIT-safe。[研究稿披露](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L547-L557) [当前实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L331-L464)
4. 对 stock-analyzer 应吸收的是**不可变输入快照、逐标的来源回执、可得时点和严格失败语义**；不应复制“为尽量有结果而跨源混合”的默认路由或以本机缓存替代研究数据版本。

## 研究稿是否明确写了数据层

| 问题 | 一手证据 | 判定 |
| --- | --- | --- |
| 是否有可核验的正式论文/数据规范 | 官方 README 将官网、文档、功能和使用入口列为项目公开入口；本次固定版本所定位的研究性正文为仓库内 Research Lab 文章。该文章自称一次 IC study，并明确排除完整交易成本/仓位/行业中性回测。没有把这观察延伸为“作者从未发表论文”。[README 公开入口](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/README.md#L31-L42) [研究方法](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L296-L302) | **研究稿明确**：有公开研究帖，不是本文可确认的正式论文或独立数据契约。 |
| 研究稿是否写到数据 | 正文直接给出股票池、期间、下一日收益定义、Tushare EOD 字段、无逐笔/盘口、日频替代规则和生存者偏差 caveat。[方法与股票池](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L304-L355) [数据与偏差](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L533-L557) | **研究稿明确**：写了实验数据边界；未形成摄取、存储、更新和数据版本规范。 |

## 数据、摄取与更新证据

### 研究稿实际使用的数据

| 维度 | 事实 | 标签与边界 |
| --- | --- | --- |
| 行情字段 | 数据 feed 被明确写为 Tushare 日频 OHLCV 加 turnover，VWAP 由 amount 推导；不含逐笔或 order-book。原公式依赖盘口/逐笔的因子以日频 VWAP 替代，文章要求将其视为“未被正确测试”，而不是已失效。[原文](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L533-L538) | **研究稿明确**：仅适用于该 GTJA 191 IC 实验。 |
| 股票池与期间 | 文章称研究 CSI 300、2018-01-02 至 2025-12-31，以当日截面因子与下一日 close-to-close 对数收益计算 Spearman IC；这不是完整 PnL 回测。[原文](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L304-L355) | **研究稿明确**：不应把 IC 结果当作已含交易约束的策略收益证据。 |
| 复现产物 | 公开配方要求安装包、设置 `TUSHARE_TOKEN` 并运行 CLI，输出为 `~/.vibe-trading/reports/` 下的 HTML 报告。[原文](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L567-L584) | **研究稿明确**：给出了可运行步骤；**推断**：该段没有发布输入行快照、供应商版本、抓取时刻或内容摘要，因此不能单凭命令重建同一数据版本。 |

### 仓库实现的数据路径

| 维度 | 事实 | 标签与边界 |
| --- | --- | --- |
| 来源与路由 | README 宣称 `get_market_data` 可使用 23 个免费来源并按市场回退；源码将具体链条写为 `FALLBACK_CHAINS`，显式 `local` 和 `qveris` 不允许静默退回网络来源。[README](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/README.md#L332-L394) [注册实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/registry.py#L117-L242) | **仓库实现**：来源选择是运行时路由能力，不是单一权威数据仓。 |
| 标准回测的缺失处理 | `auto` 回测先用解析出的 loader 取数，只对缺失代码继续尝试链中来源；仍缺失则抛错，并把实际成功来源写入 `_actual_sources`。[实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155) | **仓库实现**：标准回测路径是逐代码补齐后 fail-closed。 |
| 面向 Agent 的读取接口 | `fetch_market_data()` 以来源组尝试，默认最多三次；成功返回的标的可附简化 provenance，未返回代码写入 `_unresolved`，与标准回测的缺失即抛错语义不同。[实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L95-L214) | **仓库实现**：不能把 Agent 工具的“部分结果”当作严谨回测输入。 |
| OHLC 输入校验 | 汇总后的回测数据会执行 `validate_ohlc()`；默认策略为丢弃违反 high/low/价格不变量的 bar，但空帧或缺少 OHLC 列会原样返回。[校验函数](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L50-L119) [汇合点](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1270-L1287) | **仓库实现**：有统一坏 bar 处理，但不是严格 schema gate。 |
| 存储/缓存 | 可选 cache 位于 `~/.vibe-trading/cache/loaders`，键含 source、symbol、timeframe、日期窗和 fields；仅缓存结束日早于当天的区间，缓存格式为 Parquet 加 metadata 文件。[实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L243-L340) [写入实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L536-L562) | **仓库实现**：缓存解决性能与未收盘 bar 固化问题；**推断**：key 不含供应商版本、抓取时刻或原始内容 digest，故 cache 命中不能单独证明研究输入版本。 |
| 更新方式 | 在已核验的标准回测和 Alpha bench 路径中，数据由运行时 loader/`pro.daily` 和 `index_weight` 请求取得，随后可写本机报告或 cache；研究稿没有声明刷新周期或发布的数据快照。[回测取数](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155) [Alpha bench 取数](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L331-L464) [研究稿复现段](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L567-L584) | **推断**：本次路径呈现按需摄取加本机缓存；未核验到独立的全量行情仓、更新作业或数据版本发布机制。 |

## point-in-time、可得性与复现实验边界

| 主题 | 证据与结论 | 标签 |
| --- | --- | --- |
| 股票池 PIT | 研究稿明确说当前 CSI 300 成分被应用到整个历史窗口，晚加入股票拥有完整历史、已删除/降级股票缺席，因而有生存者偏差，并把 PIT 成分列为计划升级。[原文](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L547-L557) | **研究稿明确**：该研究实验不能标为 PIT universe。 |
| 当前成分实现 | 当前 Alpha bench 尝试从 Tushare `index_weight` 拉取窗口内成分，并将 `pit_membership`、`survivorship_bias`、`degraded` 等写入内存 `_meta`；取数失败会使用手选列表并设为 degraded。随后 membership mask 同时 forward-fill 与 back-fill。[实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L331-L464) | **仓库实现**：比研究稿更接近 PIT；**推断**：`bfill()` 使最早可得快照后的未知日期可能使用未来名单，严格研究仍需验证首个快照覆盖与输出 `_meta`。 |
| 财务 PIT | SEC fundamentals loader 明确将值锚定在 `filed` 而非 `period_end`，默认 `pit=True` 时同一报告期保留最早 filing；文档也承认 companyfacts 的口径标准化仍可能需要逐发行人处理。[实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L1-L131) | **仓库实现**：对美国 SEC 财务给出日级可得性规则；不是对 A 股财务、公告时刻或重述历史的普遍证明。 |
| 报告复现边界 | Alpha bench 报告上下文写入生成时刻、股票池、期间、因子计数、结果和部分失败；调用返回的是报告路径和汇总结果。该处未见输入行情行、来源清单、cache key 或内容 hash 被放进报告上下文。[实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L878-L937) | **推断**：同命令可再次运行，不等价于可重放同一份数据输入。 |

## 研究稿与当前代码的差异

| 对比面 | 研究稿 | 当前仓库实现 | 影响 |
| --- | --- | --- | --- |
| 研究数据范围 | Tushare 日频 OHLCV/turnover/VWAP，明确不含逐笔和盘口。[研究稿](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L533-L538) | 多市场、多个来源和 `local:` 数据桥；标准回测可以对缺失标的回退。[README](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/README.md#L332-L394) [runner](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155) | 不能用产品“支持的来源”改写或抬高研究稿的数据质量。 |
| 指数成分 | 当前成分回填全窗口，文章明确承认非 PIT。[研究稿](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L547-L557) | 代码已尝试使用历史 `index_weight` 并传播降级标记，但仍有 `bfill()` 边界。[实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L331-L464) | 当前实现不能倒推研究稿已经无生存者偏差；新实现也应以实际快照覆盖率验收。 |
| 可复现性 | 提供 token 加 CLI，产出 HTML 报告。[研究稿](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L567-L584) | 提供本机 cache 与运行期 `effective_sources`，但已核验报告上下文没有数据 manifest。[cache](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L243-L340) [报告](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L914-L937) | “能运行”与“能逐字重放历史输入”应分开表述。 |

## 对 stock-analyzer 的采纳边界

### 可采纳的设计

1. **研究输入快照而非来源名。**每次回测/研究冻结 `market_revision`、证券池快照、查询范围、复权策略、逐标的/字段最终来源、失败与跳过原因、抓取时间和内容摘要；报告引用该快照 ID。这吸收了上游“实际成功来源”而补足其缺少的版本证据。[上游运行时来源记录](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155) [上游 cache key 边界](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L284-L340)
2. **严格 PIT 契约。**财务、公告、指数成分应保存 `available_at`/`published_at`、来源版本与历史快照；缺少请求日以前的快照时，严格研究拒绝，非严格研究明确 `degraded`。这比仅布尔化 `pit_membership` 更可审计。[上游 SEC filed-date 规则](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L1-L131) [上游成分降级标记](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L450-L463)
3. **数据质量与回测输入分层。**同步可保留原始响应和修复记录；权威回测只能消费 schema 完整、OHLC 校验通过且覆盖率达标的快照。上游统一校验是可借鉴的汇合点，但默认丢行不足以作为严格研究规则。[上游校验](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L50-L119)
4. **缓存只作性能层。**可参考“未收盘区间不缓存”的思想，但 cache path、来源字符串和本机命中不能充当实验输入版本；报告仍应绑定持久化快照和 hash。[上游缓存完成区间规则](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L328-L340)

### 不可直接照搬

- **多源自动回退作为默认 A 股研究语义。**不同供应商的复权、停复牌、证券代码、交易日和修订历史可能不同；跨源补齐必须逐标的记录，并在覆盖率或字段不一致时阻断，而不是把“有数据”视为同质输入。[上游回退实现](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1123-L1155)
- **用今天或未来快照填补历史股票池。**研究稿已明确这种做法带来生存者偏差，当前 `.bfill()` 也说明“历史快照存在”本身还不够。[研究稿 caveat](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L547-L557) [当前 mask](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L432-L456)
- **把“缓存或 HTML 已生成”作为复现实验的充分证据。**上游公开的复现配方与报告产物没有固定数据 manifest；stock-analyzer 不能据此把相同 CLI/报告路径解释为相同输入。[研究稿配方](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L567-L584) [报告上下文](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L914-L937)

## 未决项

- 若需要声称“作者已发表正式论文”，应由作者或项目方提供 DOI、arXiv/OpenReview 或官网论文 URL；本次一手材料不足以作肯定结论。
- 上游研究稿没有公开其 Tushare 下载时间、权限等级、复权/停复牌处理、原始数据版本或逐次请求回执；这些字段需要独立数据供应商合同与实际 payload 才能核验。
- 对 stock-analyzer 的任何数据层改动仍应先做只读历史验证；本研究不授权改变现有策略默认参数、接入密钥或写入外部数据源。
