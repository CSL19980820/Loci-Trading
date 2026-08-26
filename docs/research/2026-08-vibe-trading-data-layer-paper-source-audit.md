# Vibe-Trading 研究稿与数据层一手来源审计

> 核验日期：2026-08-05
>
> 外部对象：[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) 固定提交 [`3a752d5`](https://github.com/HKUDS/Vibe-Trading/commit/3a752d5a8ed088633040893de1cc9e6dc712596f)
> 方法：只读该提交的 README、Research Lab 页面、源码与 Git tree；未安装外部项目、未下载行情或运行其回测。

## 可引用极简结论

- **不是正式论文。**在固定提交可见发布物中，研究材料是 Research Lab 的 HTML 页面；未见论文、数据集或可版本化数据 schema 工件。该观察仅覆盖此提交，不能外推到仓库外的作者发表物。[研究页](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L567-L584) [固定 tree](https://api.github.com/repos/HKUDS/Vibe-Trading/git/trees/b2632d71eba2387857cb81eee5ef4d43bf9f6dc5?recursive=1)
- **数据层写得有限但明确。**页面声明 Tushare 日频 OHLCV、turnover 和由 amount 推导的 VWAP；没有逐笔或盘口，日频替代的因子被标作“未被正确测试”。股票池是 CSI 300，且页面明确承认当前成分回填 2018--2025 会产生幸存者偏差，不能当作 PIT 样本。[数据范围](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L533-L538) [PIT caveat](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L547-L557)
- **可运行不等于可重放。**网页只给 token 加 CLI，且研究方法展示 `2018-2025`、复现段却写 `2020-2025`；没有输入 snapshot、供应商版本、抓取时间或内容 hash。[方法命令](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L351-L355) [复现段](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L567-L584)

| 本仓可落地借鉴 | 不应照搬 | 现有研究链落点 |
| --- | --- | --- |
| 缺失、回退和字段异常必须结构化披露，并在严格研究中 fail-closed。 | 为跑出结果静默缩小股票池或退化为手工蓝筹名单。 | `data_snapshot.source_evidence` 与 receipt/attempt；见[实施 Brief](2026-08-vibe-trading-implementation-brief.md)。 |
| 将 PIT 成分、来源日期、降级状态做成输入契约。 | 将页面 caveat、内存 `_meta` 或当前成分名单当作 PIT 事实。 | `MembershipSnapshot`、`available_at` 与严格门禁；见[实施 Brief](2026-08-vibe-trading-implementation-brief.md)。 |
| 用冻结的市场 revision、覆盖范围、PIT 版本和 artifact hash 支持 replay。 | 把本机 cache、HMAC、来源名或一条 CLI 当成数据版本。 | run card / frozen replay；见[实施 Brief](2026-08-vibe-trading-implementation-brief.md)。 |

## 直接结论

**有写，但不是一份完整的数据层研究稿或可复现数据集说明。**固定提交中能找到的研究性材料是 [Research Lab 的 GTJA 191 样本外网页研究](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L226-L266)，不是论文式数据方法章节。它明确写了：研究使用 **Tushare 日频 OHLCV + turnover，VWAP 由 amount 推导**；不含逐笔/盘口，相关因子以日频替代且标注为“未被正确测试”。[原文](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L533-L538)

它也明确承认 CSI 300 股票池是当前成分回填整个 2018--2025 窗口，存在生存者偏差，真正的 point-in-time 成分仍是计划项。[原文](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L547-L557) 因此，这篇稿最有价值的是**如实暴露数据限制**，不是可直接作为严谨历史数据层的依据。

在该固定提交的完整 Git tree 中，未见 `paper/`、`CITATION.cff`、`*.pdf`、`*.tex`、`*.bib`、数据集或数据 schema 工件；README 也未链接 arXiv、DOI 或 OpenReview。这个结论是对仓库发布物的观察，**不能证明作者在仓库之外从未发表论文**。[可复查 tree API](https://api.github.com/repos/HKUDS/Vibe-Trading/git/trees/b2632d71eba2387857cb81eee5ef4d43bf9f6dc5?recursive=1)

## 研究稿实际写到的数据

| 主题 | 一手事实 | 判定 |
| --- | --- | --- |
| 研究目的与输出 | 是截面 IC 研究，不是带交易成本、仓位约束、行业中性的完整 PnL 回测；输出是每个因子的 IC、t-stat、正 IC 比例。[方法](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L296-L355) | **研究方法描述**，不是行情工程契约。 |
| 行情字段 | 数据源被写为 Tushare EOD OHLCV、turnover，VWAP 从 amount 推导；无逐笔和 order-book，部分因子做日频替代并标注未正确测试。[数据范围](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L533-L538) | **数据集/字段描述**；没有原始行、抓取时间、请求参数或内容 hash。 |
| 股票池 | 文章前段称以 CSI 300 为研究宇宙，[说明](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L304-L315)；但 caveat 明确说使用当前成分名单回填全窗口、存在生存者偏差，PIT 成分是计划升级。[更具体的 caveat](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L547-L557) | **研究数据限制**。两段措辞并不完全一致，应以具体 caveat 为准，不能宣称该稿使用了历史 PIT 成分。 |
| 可复现性 | 复现步骤只有安装、Tushare token 和 CLI 命令，产物是 HTML 报告；页面没有发布输入数据 snapshot、供应商版本、下载时间或 artifact manifest。[复现段](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/wiki/research-lab/posts/alpha-191-in-2026.html#L567-L584) | **可运行配方**，不是可复现数据版本。 |
| GTJA 2014 报告的角色 | 项目自己的许可说明只复现 191 个数学公式，明确不复现原报告的叙述、样例、样本内/样本外表格和图；它是因子公式来源，**不是本次行情数据集来源**。[LICENSE.md](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/factors/zoo/gtja191/LICENSE.md#L1-L37) | **外部研究引用**，不能反推 Vibe-Trading 持有或复现了 GTJA 的原始数据。 |

## 必须与研究稿分开的当前源码能力

README 所列的 23 个免费来源、按市场回退链和 `local:` 数据桥是产品能力说明，[README](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/README.md#L332-L394)；它们**不是** GTJA 191 研究稿所实际使用的数据集。固定源码能验证以下工程能力：

- 标准回测的 `auto` 路径会只对缺失标的继续回退；仍缺即抛错，并记录实际命中的来源集合，而不是静默缩小股票池。[runner.py](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1076-L1155)
- 所有回测抓取结果汇合后统一执行 OHLC 结构校验；默认是丢弃坏 bar，缺列/空帧会原样返回，故它不是完整的严格 schema gate。[base.py](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L50-L119) [runner.py](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/runner.py#L1260-L1287)
- 当前 CSI 300 loader 会尝试读取 Tushare `index_weight`、按日期 mask，并把 `pit_membership`、`survivorship_bias`、`degraded` 写进内存 `_meta`；取数失败时仍会退化为手工 30 只名单。[alpha_bench_tool.py](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L304-L464) 这比研究稿的静态名单说明更进一步，但不能倒推研究稿当时已经 PIT-safe，且公共 HTML 返回体没有带出该 `_meta`。[alpha_bench_tool.py](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L914-L937)
- loader cache 的 key 是来源、代码、周期、日期窗和字段；只缓存已经结束的交易日。它解决性能，不绑定供应商内容版本、抓取时刻或原始 payload digest，不能当研究数据版本。[base.py](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L243-L340)

## 与 stock-analyzer 的精简映射

| Vibe 能力 | 已确认事实 | 本仓等价能力 | 处置 | 理由与验证边界 |
| --- | --- | --- | --- | --- |
| 缺失标的回退后 fail-closed | 回测 auto 模式逐代码补齐，仍缺直接失败。 | `MarketStore.data_snapshot()` 已把范围化 `source_evidence` 和 `market_revision` 绑定到研究输入；当前工作树还持久化逐代码 receipt/attempt。 [本仓快照](../../src/market/infrastructure/store.py#L72) [本仓回执](../../src/market/infrastructure/store_provenance.py#L97) | **等价并补强** | 保留“数据不足即阻断”，将每次失败、skip、fallback 作为可查询证据；不要为得到结果引入手工蓝筹 fallback。实际来源质量仍需由同步测试和运行 receipt 验证。 |
| 集中 OHLC 校验 | Vibe 在 runner 统一校验，但默认会丢坏 bar，缺列可穿透。 | 本仓 `source_evidence()` 输出字段覆盖、坏 OHLC 计数及 attempts 未观测标记。 [本仓回执摘要](../../src/market/infrastructure/store_provenance.py#L97) | **补强** | 严格研究应拒绝缺列/坏值/未知 attempts，而非只在日志 warning；非严格模式可以降级，但不可将其作为假设通过证据。 |
| PIT 成分与生存者偏差披露 | 研究稿明确承认静态 CSI 300 回填和 PIT 缺口；当前源码有不透明的降级路径。 | `MembershipSnapshot` 保留来源、版本、PIT/生存者偏差与 degraded；严格模式会拒绝缺少历史快照或来源证据的输入。 [本仓时间契约](../../src/research/domain/temporal.py#L95) | **等价并更严格** | 继续要求 `as_of` 以前的历史快照；不能把今天成分、最早未来名单或 fallback 名单写成历史事实。真实供应商快照仍需后续导入。 |
| 数据版本与复现 | 研究稿仅给 token + CLI；cache 和 `effective_sources` 不能识别精确输入版本。 | 行情快照含 revision/digest，研究 README 要求冻结实际行、来源和 input hash。 [本仓快照](../../src/market/infrastructure/store.py#L79) [本仓研究边界](../../src/research/README.md#L13) | **补强** | run card 应引用市场 revision、PIT 事实/成分版本、receipt 和 artifact hash，不引用本机 cache path 或“auto”来源名。该能力在当前工作树中，须以测试与后续提交为准。 |
| 多市场长回退链与本地 loader 插件 | 是面向通用交易工作台的产品边界；显式 local 不回退网络。 [注册表](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/registry.py#L117-L242) | 本仓是 A 股单市场行情仓。 | **不照搬** | 借鉴“显式本地输入不可静默改源”的原则即可；不扩大到 23 源、多币种或平行缓存仓，否则会稀释 A 股研究的可复核性。 |

## 可采纳的四点

1. **复用 fail-closed 语义，不复用来源数量。**先保证单市场每个代码的数据完整性，再谈回退；缺失、降级和异常要进入 run card。
2. **把研究稿中的 caveat 变成系统门禁。**静态指数成分、缺乏逐笔字段、字段替代和调整因子缺失，不能只写在报告脚注，应直接决定严格研究是否可运行。
3. **以不可变输入快照取代“可运行命令”。**命令、token 和来源名只能帮助重跑；真正可审计的重放还需要市场 revision、原始消费范围、PIT 版本、receipt 和产物 hash。
4. **将缓存定位为性能层。**可借鉴只缓存已结算日期，但不能把 cache key、HMAC 或本机路径当作数据版本、来源证据或研究结论。

## 范围与限制

- 本稿只回答“研究稿是否写了数据层、写到了什么”，不评价其因子表现，也不改变本仓任何策略默认参数或真实数据。
- 外部结论锁定在 `3a752d5`；上游后续 README、Wiki 或源码变化不自动纳入。
- 本仓对照的是当前工作树，未提交能力不等同于发布基线；本稿不把它表述为生产默认。
