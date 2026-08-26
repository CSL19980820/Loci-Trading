# 低特质波动率原始来源核验

> 核验日：2026-08-05
> 范围：只核验低特质波动率（idiosyncratic volatility, IVOL）/低总波动率作为 A 股横截面选股假设的原始学术与期刊来源。本文件不运行本地回测，不读取或修改策略默认值、代码、行情数据或既有文档。
>
> **定位：研究候选，非生产规则。** 本文不能证明任何 A 股历史或未来收益，更不能授权替换或调节活动的 PTH252、RSI 低吸或趋势策略。

## 结论

“低特质波动率”可以作为一个**值得证伪的研究候选**，但目前不应表述为“已验证的 A 股选股因子”。最早且影响力很高的直接来源 Ang、Hodrick、Xing、Zhang（2004 工作论文；2006 期刊发表）在美国样本中报告：按 Fama--French 三因子残差波动率排序时，高 IVOL 股票的后续收益异常低，故其结果隐含“低 IVOL 优于高 IVOL”的方向。[NBER 作者工作论文全文](https://www.nber.org/system/files/working_papers/w10852/w10852.pdf)；[NBER 发表记录](https://www.nber.org/papers/w10852)。

但这个方向并非稳健共识。Bali 与 Cakici（2008）的期刊原文摘要逐项改变频率、权重、分位断点、规模/价格/流动性筛选与股票池后，结论是不存在稳健显著的 IVOL--预期收益关系。[期刊 DOI](https://doi.org/10.1017/S002210900000274X)；[出版方存档内容入口](https://www.cambridge.org/core/services/aop-cambridge-core/content/view/S002210900000274X)；[期刊登记的可访问摘要](https://api.crossref.org/works/10.1017/S002210900000274X)。

| 问题 | 可否由一手来源支持 | 判定 |
| --- | --- | --- |
| “高 IVOL 后续收益更低，低 IVOL 可作为横截面排序方向” | 有条件支持 | Ang 等的美国、月度、价值加权组合结果支持此**研究假设** |
| “低 IVOL 在不同构造、断点、权重下稳定有效” | 不支持 | Bali--Cakici 的发表研究给出直接反证 |
| “低总波动率”与“低特质波动率”是同一个因子 | 不支持 | 前者不剔除市场/风格共同波动，后者定义为因子回归残差的波动率 |
| “该方向已适用于全 A 股、`T+1 open` 和 20 日持有” | 不支持 | 本次没有逐页核验到能覆盖该交易规则的 A 股原始实证；两份核心来源均为美国月度研究 |
| “它已独立于 PTH252、RSI 低吸和趋势” | 仅概念上不同 | 因子输入不同不等于收益相关性低；必须由同一严格 PIT 样本的相关性、双变量排序和回归验证 |

因此，允许的结论是：**在可信的历史 A 股股票池和可追溯因子输入下，可预注册“低 FF-3（或明确替代模型）残差波动率优于高残差波动率”的多空研究假设，并先检验长端是否有可投资信息。** 不允许的结论是“低波必然防跌”或“文献已经证明本仓库可以在 A 股按低 IVOL 直接买入”。证据不足时维持现金，不以弱票补足名额。

## 术语与可复现定义

### 1. 特质波动率（本研究的主候选）

Ang 等在其式（8）中以日频超额收益回归 Fama--French 三因子：

```text
r_i,d - r_f,d = alpha_i + beta_MKT,i * MKT_d + beta_SMB,i * SMB_d
                + beta_HML,i * HML_d + epsilon_i,d
IVOL_i = sqrt(var(epsilon_i,d))
```

其中 `IVOL_i` 是残差 `epsilon_i,d` 的标准差；若仅作横截面排序，是否乘 `sqrt(252)` 不改变名次。原文明确把它定义为“relative to the FF-3 model”，不是股票自身涨跌幅的标准差。[Ang 等 NBER PDF，PDF 第 24 页、印刷页 22，式（8）](https://www.nber.org/system/files/working_papers/w10852/w10852.pdf)

本候选的**可复现近似**应首先保持原义，而不是把它偷换成 ATR、振幅或收盘价收益率波动率：

1. 每个形成日只使用该日及以前可获得的复权日收盘价、无风险收益和市场/风格因子，计算日超额收益。
2. 在预先声明的尾随窗口内，对每只股票做同一因子模型的 OLS，取残差样本标准差；样本不足、停牌导致有效观测不足、因子缺失或回归奇异时，标记为不可排名，不填补为低风险股票。
3. 同一形成日只在当日合格股票横截面内升序排序；低 IVOL 是低分位，不应将“历史波动低”误写成预测到的未来波动低。

最贴近原文的首个复现版本是月末使用过去一个月日收益、五分位、价值加权、持有一个月、每月调仓（`1/0/1`）。这是研究的**预注册起点**，不是本项目的生产参数。若 A 股没有可审计的日频三因子输入，允许另做“市场模型残差波动率”敏感性版本：

```text
r_i,d - r_f,d = alpha_i + beta_MKT,i * MKT_d + epsilon_i,d
```

但它必须明确标为近似口径，不能与 FF-3 IVOL 混报或选择性挑选结果。把“总波动率”作为另一条并列敏感性：

```text
TVOL_i = std(r_i,d - r_f,d)
```

`TVOL` 不需要因子数据，却包含市场和风格的共同风险；它不是 IVOL 的无损替代，也不得拿其中较好的一个回测结果反向声称为原论文复现。

### 2. 与既有研究方向的关系

本候选按收益残差离散度排序，概念上不同于：

| 研究方向 | 主输入 | 与 IVOL 的关系 |
| --- | --- | --- |
| PTH252 | 当前价格相对约一年高点的位置 | 价格位置/锚定候选，不直接使用回归残差 |
| RSI 低吸 | 近期涨跌与均值回归状态 | 短期振荡状态，不直接度量残差离散度 |
| 趋势 | 价格或均线的方向/延续 | 方向性暴露，不等于残差风险 |
| 低 IVOL | 个股日收益对共同因子拟合后的残差标准差 | 风险/分歧或未解释波动候选 |

这仅说明输入层不同，**不证明统计独立性或增量收益**。实际研究必须在相同的严格 PIT 日历与股票池中报告：Spearman 相关、分组交叉表、IVOL 在 PTH/RSI/趋势控制后的 Fama--MacBeth 系数，以及是否在各既有因子分位内仍有单调性。没有这些结果，不得以“独立”名义组合或加权。

## 原始来源一：Ang、Hodrick、Xing、Zhang

Andrew Ang、Robert J. Hodrick、Yuhang Xing、Xiaoyan Zhang，*The Cross-Section of Volatility and Expected Returns*，NBER Working Paper 10852（2004），后发表于 *The Journal of Finance* 61(1), 259--299（2006）。[NBER 论文页](https://www.nber.org/papers/w10852)列出作者、工作论文日期和发表版本；[原始 PDF](https://www.nber.org/system/files/working_papers/w10852/w10852.pdf)可直接逐页核验。

- 因子定义：式（8）将 IVOL 定义为 FF-3 回归残差的 `sqrt(var(epsilon))`。[PDF 第 24 页/印刷页 22](https://www.nber.org/system/files/working_papers/w10852/w10852.pdf)
- 形成、调仓、持有：作者把 `L/M/N` 定义为形成期/月数跳过期/持有期；主分析采用 `1/0/1`，即过去一个月日收益估计、当月五分位、价值加权、持有一个月、每月调仓。`12/1/12` 是有重叠子组合的稳健性构造，而不是短周期成交模板。[PDF 第 24 页/印刷页 22](https://www.nber.org/system/files/working_papers/w10852/w10852.pdf)
- 预期方向和量级：总波动率排序的第五分位相对第一分位 FF-3 alpha 为 `-1.19%/month`（t=`-5.92`）；IVOL 排序则为 `-1.31%/month`（t=`-7.00`）。这表示作者样本中高波动端很弱，因而“做多低 IVOL、做空高 IVOL”是论文隐含的相对方向；不是只做多低 IVOL 的净收益或扣成本可成交结论。[PDF 第 25 页/印刷页 23，Table VI 描述](https://www.nber.org/system/files/working_papers/w10852/w10852.pdf)
- 样本边界：表格注释给出完整 IVOL 样本为 1963-07 至 2000-12；使用的交易所样本是 NYSE/AMEX/NASDAQ，且组合价值加权。[PDF 第 52 页/印刷页 50](https://www.nber.org/system/files/working_papers/w10852/w10852.pdf)
- 作者自己的保留：论文把 low-IVOL 结果与资产定价模型遗漏的市场波动风险相联系，也讨论样本极端事件和模型解释的不确定性；它不是“波动越低就越有正 alpha”的普适因果证明。[PDF 第 23--24 页/印刷页 21--22](https://www.nber.org/system/files/working_papers/w10852/w10852.pdf)

## 原始来源二：Bali 与 Cakici 的可重复性反证

Turan G. Bali、Nusret Cakici，*Idiosyncratic Volatility and the Cross Section of Expected Returns*，*Journal of Financial and Quantitative Analysis* 43(1), 29--58（2008）。[期刊 DOI](https://doi.org/10.1017/S002210900000274X)；[出版方文章内容入口](https://www.cambridge.org/core/services/aop-cambridge-core/content/view/S002210900000274X)。该刊发表记录的[可访问摘要](https://api.crossref.org/works/10.1017/S002210900000274X)可核验作者、年份、页码及以下原文结论。

摘要的关键表述为：数据频率、组合平均收益的权重、五分位断点，以及规模/价格/流动性筛选“play critical roles”；在日/月频 IVOL、三种权重、三种断点以及 NYSE/AMEX/NASDAQ 与仅 NYSE 股票池的组合检查后，作者结论是“**no robustly significant relation exists between idiosyncratic volatility and expected returns**”。

这份反证直接限制了可落地程度：任何 A 股研究若只报告一个窗口、一个权重、一个分位阈值或一次筛选后的最好结果，都不足以称为 IVOL 有效。至少应在预先写定的日历上同时呈现：

- 日频残差窗口的 `1/0/1` 复现，和较长窗口/跳月版本；
- 等权、流通市值权重，以及容量/流动性约束后的结果；
- 全可投资历史股票池与可交易的大市值子池；
- 五分位全谱、低--高多空，以及低分位只做多相对基准，不能只截取一个 top-N；
- 样本内与冻结的样本外时间段，及交易成本、涨跌停/停牌无法成交和闲置现金后的组合级结果。

## A 股外推与可执行性边界

两份核心资料都是美国样本，且文献组合收益不是“信号收盘后次日按开盘价一定成交”的中国股票仿真。因此，下列项目必须在任何 A 股结论前单独通过：

1. **因子输入的 PIT 性。** 若用 A 股 FF-3 近似，`MKT/SMB/HML` 本身必须在形成日可得；不能用今天全体股票市值、账面值或行业分类倒灌过去。风险自由利率、复权规则、IPO 首日和退市收益同样需留来源回执。
2. **股票池和可交易性。** 历史成分、退市、ST、长期停牌、涨跌停和上市初期观测不足要在信号日前过滤或建模；当前幸存者股票池不能回填。高 IVOL 端更可能受这些规则影响，删掉不能成交的坏结果会偏向低 IVOL。
3. **中国市场结构差异。** 论文中的价值加权多空月度组合不能自动变成 A 股长端、有限持仓、`T+1 open` 的净收益。没有融券可得性、开盘成交、价格限制和容量证据时，只能报告研究情景，不可把多空价差当作真实账户回报。
4. **定义风险。** A 股没有可审计三因子序列时，市场模型残差、行业中性残差、日收益总波动率会给出不同排序；它们是不同假设，必须并列披露，不能将其中最优者改名为“低 IVOL”。
5. **与既有信号的增量。** PTH252、RSI 和趋势都可能与风险偏好、近期价格路径或小盘流动性共同暴露。只有条件排序/回归在样本外仍显示增量，才能讨论组合；相关性低本身也不等于 alpha。

## 建议的研究门禁（非生产参数）

在开始任何本地回测前，应把下列事项写入 run card 并冻结，不在结果后调参：

| 项目 | 最低要求 |
| --- | --- |
| 主定义 | FF-3 日频残差波动率，月末形成，`1/0/1`，全五分位报告 |
| 近似定义 | 市场模型残差、TVOL 只能作为敏感性，明确独立标签 |
| 方向 | 预注册为“低 IVOL 相对高 IVOL 更强”；允许结果否定该假设 |
| 股票池 | 历史成员快照、上市/退市与停复牌可追溯；缺失即严格失败 |
| 执行 | 信号先于成交，记录开盘成交失败、涨跌停、成本、容量与闲置现金 |
| 增量检验 | 对 PTH252、RSI、趋势做相关、双排序、控制回归和样本外验证 |
| 通过条件 | 扣成本后的组合级指标在预先指定的样本外阶段、不同权重和合理子池中不依赖单一设定；否则不入候选池 |

在取得这些 A 股运行级证据前，本研究的结论是“**文献上有争议且需要本地严格 PIT 证伪的低 IVOL 候选**”，而不是可上架的选股规则。

## 来源清单

1. Andrew Ang, Robert J. Hodrick, Yuhang Xing, and Xiaoyan Zhang (2004), “The Cross-Section of Volatility and Expected Returns,” *NBER Working Paper* 10852；published version: *The Journal of Finance* 61(1), 259--299 (2006). [NBER paper page](https://www.nber.org/papers/w10852); [original full PDF](https://www.nber.org/system/files/working_papers/w10852/w10852.pdf); [DOI](https://doi.org/10.3386/w10852). 本文采用 PDF 第 24--25、52 页（印刷页 22--23、50）的公式、策略和结果。
2. Turan G. Bali and Nusret Cakici (2008), “Idiosyncratic Volatility and the Cross Section of Expected Returns,” *Journal of Financial and Quantitative Analysis* 43(1), 29--58. [Journal DOI](https://doi.org/10.1017/S002210900000274X); [Cambridge publisher content endpoint](https://www.cambridge.org/core/services/aop-cambridge-core/content/view/S002210900000274X); [publisher-deposited journal metadata and abstract](https://api.crossref.org/works/10.1017/S002210900000274X). 本文采用摘要中关于频率、权重、断点和筛选敏感性，以及“no robustly significant relation”的明确结论。
