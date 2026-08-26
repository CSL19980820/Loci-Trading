# PTH252 原始来源核验

> 核验日：2026-08-05
> 范围：只核验 `PTH252 = Close / rolling_max(High, 252)` 作为 A 股横截面研究候选的外部理论/实证依据，以及当前仓库的严格 PIT、`T+1 open`、20 个交易日持有设定能否由公开原始来源支撑。本文不运行本地回测，不改变策略、参数、数据或默认值。

## 结论

`PTH252` 可以保留为一个有原始金融文献依据的**研究候选**，但不能写成已被外部文献验证的“当前全 A 股可执行因子”。最强的一手证据是 George 与 Hwang（2004）：它在美国 CRSP 股票的横截面上，以“月末价格 / 截至该月末过去 12 个月最高价”排序，发现接近 52 周高点的组合对后续收益有预测信息，并提出锚定机制解释。[作者托管的原始 PDF](https://www.bauer.uh.edu/TGeorge/papers/gh4-paper.pdf)；[期刊 DOI](https://doi.org/10.1111/j.1540-6261.2004.00695.x)

该论文不是 A 股样本，也不是日频 `Close / rolling_max(High, 252)`、Top 10%、只做多、`T+1 open`、20 日持有的复现。公开可核验的直接 A 股材料中，Lan、Truong、Zhang 的 SSRN 摘要报告了上交所 A 股 1995--2018 的正收益和月均 0.28%，但它是未同行评审工作论文，且本次只能核验到原始 SSRN DOI 登记的摘要，未取得全文方法表。[SSRN DOI](https://doi.org/10.2139/ssrn.6403338)

| 问题 | 可否由原始来源支持 | 判定 |
| --- | --- | --- |
| “价格接近过去 52 周高点”可作为横截面收益预测候选 | 可以，限 George--Hwang 的美国样本、月度构造和其报告的组合 | **支持研究假设**，不支持当前 A 股收益结论 |
| `Close / rolling_max(High, 252)` 是原论文唯一公式 | 不可以 | 原文是月末价格除过去 12 个月最高价；未把分母限定为日内 `High` 或 252 个交易日 |
| A 股存在同方向证据 | 有限支持 | 仅有一篇未同行评审、只覆盖上交所 A 股 1995--2018 的直接材料；不能外推全 A 股或当前样本 |
| 严格 PIT | 支持为研究卫生要求，不是因子 alpha 证据 | 原始退市偏差研究支持防生存者偏差；外部论文不能证明本仓库某次运行真的 PIT 合格 |
| `T+1 open` | 不支持为论文复现 | 原始 52 周高点论文只说明月末形成和后续月收益，未给出次日开盘成交价或 A 股可成交性 |
| 20 个交易日持有/调仓 | 不支持为论文复现 | George--Hwang 的主设计为每月形成、持有 6 个月；SSRN 摘要只给月收益，未公开该参数 |

因此，在没有本地严格 PIT 运行产物和独立样本外结果前，允许的表述是“有外部理论和有限 A 股工作论文支持的待检验候选”；不允许的表述是“文献已验证本仓库 `PTH252` 的 20 日、`T+1 open` 净收益”。

## 一手原始来源

### 1. George 与 Hwang（2004）：最强的因子定义和理论来源

[George 与 Hwang 的原始 PDF](https://www.bauer.uh.edu/TGeorge/papers/gh4-paper.pdf) 是作者所在 University of Houston 网站托管的 *The Journal of Finance* 发表版本（Vol. 59, No. 5, pp. 2145--2176）。其可直接核验的内容如下。

- 样本为 1963--2001 的全 CRSP 股票，研究以月度组合收益报告，不是中国市场日线成交回测（p. 2148）。
- 对月 `t` 的 52 周高点度量为 `P_i,t-1 / high_i,t-1`：`P_i,t-1` 是 `t-1` 月末价格，`high_i,t-1` 是截至 `t-1` 月最后一个交易日、过去 12 个月中该股达到的最高价格（p. 2149）。
- 主表中的 52 周高点赢家/输家分别是比率最高/最低的 30%，等权多赢家、空输家；每月形成并持有 6 个月，形成期重叠（pp. 2148--2149）。全样本主表的赢家减输家平均月收益为 0.45%（t=2.00）；剔除一月的表中为 1.23%（t=7.06）（pp. 2148--2150）。这些是作者样本的毛组合发现，不能当作 A 股或扣成本收益。
- 作者认为接近 52 周高点相对于个股及行业历史收益有额外预测能力；其机制解释是投资者将 52 周高点作为锚点，对好/坏消息调整缓慢，造成后续延续（pp. 2146--2147、2174--2175）。这是与数据一致的行为机制，不是对 A 股投资者的因果证明。
- 文中为回归检验会跳过一个月以弱化 bid-ask bounce，但描述性表格不跳过（p. 2149）。这进一步说明它不能被简化为“信号日收盘、次日开盘必然成交”的日频可执行模板。

### 2. 中国市场的同行评审记录：题目和发表可核验，细节不足

[Zhou、Liu、Guo 的期刊 DOI](https://doi.org/10.1080/1540496X.2021.1904880) 对应 *The 52-week High Momentum Strategy and Economic Policy Uncertainty: Evidence from China*，发表于 *Emerging Markets Finance and Trade* 58(2), 428--440。第一作者的[高校个人发表记录](https://faculty.ctbu.edu.cn/ZXM12/en/lwcg/59300/content/12196.htm)也能核验题名、期刊、卷期和发表信息。

这足以证明“中国市场 + 经济政策不确定性 + 52 周高点动量”是已经发表的研究边界；但本次审计环境无法通过期刊原文页取得全文，作者主页也没有附稿。因而下列关键细节均**不作为一手验证结论**：股票池是否为沪深全部 A 股、排序分位、价格字段、是否使用日内高价、持有期、交易成本、`T+1 open` 和具体统计表。

一个二手索引中的摘要称低 EPU 时效应强、高 EPU 时几乎没有动量，并把锚定作为解释；该摘要与论文题名一致，但没有被本次审计的期刊原文或作者稿逐段核验，故只列入“二手材料”，不用于支持任何仓库参数。见[Semantic Scholar 的二手索引记录](https://api.semanticscholar.org/graph/v1/paper/DOI:10.1080/1540496X.2021.1904880?fields=title,abstract,openAccessPdf,externalIds,publicationDate,authors)。

### 3. 上交所 A 股工作论文：直接但证据等级较低

[Lan、Truong、Zhang 的 SSRN DOI](https://doi.org/10.2139/ssrn.6403338) 标题为 *The 52-Week High Momentum Strategy: Evidence in Chinese Stock Market*。该原始工作论文登记的摘要称：用上交所上市 A 股的扩展数据复现 George--Hwang，样本为 1995--2018，52 周高点动量在该样本中持续正收益，月均 0.28%，并在若干控制项下仍盈利。

这是本次能找到的最直接 A 股材料，但证据边界必须保留：

- SSRN 是工作论文平台，不等于同行评审发表；不能把摘要主张当作独立复现。
- 摘要没有公开本次需要的完整构造和表格，不能确认它是否等价于 `close / rolling_max(daily_high, 252)`、是否只做多、分位数多少、是否按 `T+1 open`，也不能确认 20 日持有。
- 其样本只说上交所 A 股、止于 2018；它不覆盖深市、创业板、科创板以及 2019 年后的样本外时期。

## 原论文与仓库公式的映射

| 层面 | 原始文献可核验的定义 | 当前仓库设定 | 是否可称为直接复现 |
| --- | --- | --- | --- |
| 信号 | 月末 `P_i,t-1 / high_i,t-1`；分母为截至该月末过去 12 个月最高价格 | `close / rolling_max(high, 252)`；计算函数只向后滚动，包含当日行 | **否**。经济含义相近，但“12 个月”不等于固定 252 交易日，且原文未指定日内 `High` 字段 |
| 分子 | 月末价格 | 当日收盘价 | 近似映射，不是字段级已证实等价 |
| 分母 | 过去 12 个月内最高价格 | 过去 252 个日线 `High` 最大值 | 未被原文唯一支持；必须与 `rolling_max(Close, 252)` 并列敏感性检验 |
| 横截面构造 | 前 30% 对后 30%，等权多空 | 前十分位内再按分数取最多 20 只；主信号只使用高分组 | **否**。分位、容量和多空结构不同 |
| 调仓/持有 | 每月形成，持有 6 个月且有重叠组合 | 每 20 个交易日形成，持有 20 个交易日 | **否**。20 日是本地预注册参数，未从该论文推导 |
| 成交时点 | 以月末信号和后续月收益描述 | 收盘后信号、`T+1 open` 执行 | **否**。原文不报告次日开盘成交或 A 股涨停/停牌成交 |

当前代码已把 `High` 与 `Close` 两种参考口径同时保留为敏感性产物：`src/research/application/factor_analysis.py` 计算尾随窗口，`src/research/application/factor_artifacts.py` 另外跑 `reference="close"`。这正是合理做法，但不能倒过来说两种口径已被论文证明等价。

## 当前严格 PIT、T+1 与持有期的核验

### 严格 PIT

当前 PTH252 HTTP 契约把 `strict_pit` 固定为 `true`，且强制提交 `historical_universe_id`：`src/research/api/factor_models.py:42-50`；路由实际调用也传入 `strict_pit=True`：`src/research/api/factor_router.py:67-80`。运行时若没有历史股票池快照会失败，而非降级通过：`src/research/application/factor_experiment.py:170-183`。`membership_mask()` 对每个信号日只选择 `as_of <= day` 的最新历史快照，并在没有历史股票池时显式标记 `survivorship_bias=True`：`src/research/application/backtest_support.py:23-112`。冻结输入、来源证据和 OHLC 覆盖也进入严格验证。

这与[Shumway（1997）](https://doi.org/10.1111/j.1540-6261.1997.tb03818.x)所揭示的研究风险方向一致：作者发现 CRSP 中负面退市的回报常缺失，遗漏退市回报规模很大。该来源支持“不能用今天的幸存股票池替代历史股票池”的方法论必要性；它不证明本仓库的 JSON 快照、来源链接、复权和退市处理已经正确，也不是 A 股 PTH252 的收益证据。

**判定：**严格 PIT 可以作为必要的研究质量门禁，但不能靠外部文献或配置键本身取得“已严格 PIT”的结论。只有某一次 run 同时拥有可追溯历史成员快照、实际 OHLC 来源证据、冻结输入，并以 `validation.status = passed` 结束，才能对那一次运行作该表述。本次没有运行回测，故没有这种运行级证据。

### `T+1 open`

当前引擎把 `entry_timing` 固定为 `next_open`，产物文字明确为“signal after close, T+1 open, 20 trading-day hold”：`src/research/application/factor_experiment.py:51-65`、`127-138`，以及 `src/research/application/factor_artifacts.py:104-123`、`289-301`。`hold_days=20` 也由 HTTP 契约限制为字面量 20，而不是用户可调字段。

George--Hwang 的一手方法段只给出“月初形成、使用上月末价格、看后续月收益”的时间顺序；它没有给出日频 `T` 收盘后在 `T+1` 开盘按记录开盘价成交的规则。该顺序可以支持“信号必须早于收益标签”的原则，却不能验证开盘集合竞价中的排队、涨跌停、停牌、滑点、成交量或全部候选的成交概率。

**判定：**`T+1 open` 是合理且较保守的本地防前视执行假设，但没有找到可把它称为 52 周高点原论文或 A 股原始实证论文复现的公开一手来源。日线 `Open` 回测应继续被表述为“记录开盘价情景，受引擎的涨停/停牌/成本规则约束”，而不是已证实可成交的实盘收益。

### 20 个交易日持有与调仓

原始 George--Hwang 论文的主组合是每月形成、持有 6 个月；其稳健性还讨论 `(6,12)`、`(12,6)`、`(12,12)` 等**月度**组合。它没有 20 个交易日持有、20 日调仓或短期只做多收益的表格。Lan 等 SSRN 的可访问摘要只报告“月均收益”，没有公开持有期构造，不能补足这一空白。

**判定：**20 个交易日是本仓库固定的研究窗口，不是可由已核验文献推导的参数，也不应被标为外部验证的默认值。它需要在严格 PIT 的本地样本中，与预先声明的其他期限并列报告；不得在同一回测样本中挑出表现最好的期限后再反向声称来自文献。

## 明确不可验证或仅属二手的说法

- “George--Hwang 使用的最高价就是日内 `High`，所以 `rolling_max(High, 252)` 是严格原始公式。”不可验证。原文只给出月末价格和过去 12 个月最高价格的关系。
- “原论文支持 Top 10%、容量 20、只做多、20 日调仓/持有。”不成立；原文主设计是前后各 30%、多空、每月形成、6 个月持有。
- “原论文或直接 A 股论文支持 `T+1 open` 的可成交净收益。”未找到支持。月度收益口径不能替代集合竞价成交和涨跌停队列证据。
- “Zhou、Liu、Guo 的中国期刊论文已经证明当前全 A 股、所有市场状态均有效。”不可验证。原始期刊全文和参数表本次未取得；低/高 EPU 的具体摘要措辞仅见二手索引。
- “Lan、Truong、Zhang 的 0.28% 月收益已被同行评审、可外推至深市/创业板/科创板或 2019 年后。”不成立。该来源是 SSRN 工作论文，且样本只写上交所 A 股 1995--2018。
- “仓库当前已完成严格 PIT。”不可验证。代码/测试证明会拒绝缺失快照的任务，不等于存在一个已通过、可复核的真实 PTH252 run。
- “PTH252 与常规 12-1 动量在 A 股中有稳定增量、低相关或可替代性。”本次没有找到直接原始 A 股证据；应由双变量排序、回归和样本外检验回答。

## 可采纳的研究边界

外部资料只支持下述可证伪命题：在明确的历史 A 股股票池中，股票价格越接近其过去约一年的高点，可能包含对后续横截面收益有用的信息。仓库当前的 `PTH252`、严格 PIT、`T+1 open` 和 20 日持有是为了把该命题变成可审计的本地实验，而不是外部论文已经认可的交易模板。

上线或改变活动策略前，仍需以通过严格 PIT 的 run card 证明：历史股票池和行情来源可追溯、`High` 与 `Close` 复权口径一致、开盘成交失败被真实处理、扣成本后结果在样本外和不同期限下不依赖单一时期。证据不足时维持研究候选，不以弱信号补位。

## 来源清单

1. Thomas J. George and Chuan-Yang Hwang (2004), “The 52-Week High and Momentum Investing,” *The Journal of Finance*, 59(5), 2145--2176. [作者托管原始 PDF](https://www.bauer.uh.edu/TGeorge/papers/gh4-paper.pdf)；[DOI](https://doi.org/10.1111/j.1540-6261.2004.00695.x)。
2. Xuemei Zhou, Qiang Liu and Shuxin Guo (2022), “The 52-week High Momentum Strategy and Economic Policy Uncertainty: Evidence from China,” *Emerging Markets Finance and Trade*, 58(2), 428--440. [DOI](https://doi.org/10.1080/1540496X.2021.1904880)；[第一作者高校发表记录](https://faculty.ctbu.edu.cn/ZXM12/en/lwcg/59300/content/12196.htm)。本次只把题名/发表信息作为一手可核验内容；结果细节未纳入一手结论。
3. Tiancheng Lan, Thanh Truong and Xiaorui Zhang (2026), “The 52-Week High Momentum Strategy: Evidence in Chinese Stock Market,” *SSRN Electronic Journal*. [DOI/原始工作论文入口](https://doi.org/10.2139/ssrn.6403338)。未同行评审，且本次仅核验到摘要。
4. Tyler Shumway (1997), “The Delisting Bias in CRSP Data,” *The Journal of Finance*, 52(1), 327--340. [DOI](https://doi.org/10.1111/j.1540-6261.1997.tb03818.x)。用于 PIT/生存者偏差的方法论风险，不用于支持 PTH252 alpha。
5. [Semantic Scholar 二手索引](https://api.semanticscholar.org/graph/v1/paper/DOI:10.1080/1540496X.2021.1904880?fields=title,abstract,openAccessPdf,externalIds,publicationDate,authors)：仅记录 Zhou 等论文的摘要说法；不是本文件采用的原始实证结论来源。
