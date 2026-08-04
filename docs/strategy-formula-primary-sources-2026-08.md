# A 股日线短线公式：一手资料与可证伪候选

日期：2026-08-01  
范围：仅研究两类日线公式，不修改 `src/strategy`、回测代码或现有策略。本文不声称任何资料证明本仓胜率，也不把文献中的市场、频率和持有期结果外推为本仓结论。

## 结论先行

1. **T 日尾盘收盘买入、T+1 卖出**最适合先拆成两个可观测收益：隔夜收益
   `O[t+1] / C[t] - 1` 与 T+1 盘中收益 `C[t+1] / O[t+1] - 1`。中国市场的 T+1 规则使二者不能合并成一个“次日收益”指标；候选应优先测试收盘位置、短期反转/动量、相对强弱、异常换手和波动收缩后的延续。
2. **T 日收盘选股、T+1 低吸、T+2 卖出**的核心不是预测 `L[t+1]`，而是 T 日预先决定一个限价目标 `P_limit`，然后只在 T+1 的 `low` 触及该价时认定成交。日线回测不能用 `L[t+1]` 作为成交价，也不能把 T+1 收盘后的信息用于目标价。
3. 一手资料支持的是机制和指标定义：中期动量、短期反转、价格动量与成交量状态、波动率/波动收缩、52 周高点距离、交易时段拆分。它们**只产生待检验假设**，不能证明本仓任一公式达到 50% 胜率。
4. 首轮只测单因子和少量预先登记的参数；所有候选按“信号留存率、活跃交易日、净收益、盈亏比、回撤和滑点敏感性”共同判断，不以单一胜率挑选。

## 1. 信息边界与成交契约

### 1.1 日线符号

交易日用 `t` 表示，字段为 `O[t]、H[t]、L[t]、C[t]、V[t]、TO[t]`，其中 `TO` 是换手率。价格类字段必须统一复权口径；`V`、`TO` 不因复权缩放。缺失、停牌、上市未满预热期和零分母均保留为缺失，不用 0 填充。

本文所有 `rolling(N)` 基准均指 `t-1` 及更早的数据：

```text
past_max_N[t] = max(H[t-N], ..., H[t-1])
past_mean_N[t] = mean(V[t-N], ..., V[t-1])
```

公式在 T 收盘后计算时可以使用完整的 `O/H/L/C/V/TO` 到 T；盘中选股不能使用 T 的最终 `H/L/C/V`。横截面排名只在 T 日实际可交易股票集合中计算。

### 1.2 两类策略的最小可复现实验口径

| 策略 | 信号时点 | 首选基准成交口径 | 必须另做的敏感性口径 |
| --- | --- | --- | --- |
| A：T 收盘买、T+1 卖 | T 收盘后形成信号 | 理想化 `P_in=C[t]`；退出分别测 `P_out=O[t+1]`（纯隔夜）和 `P_out=C[t+1]`（持有至次日收盘） | 收盘竞价不可保证成交时，加入 `C[t]` 到可成交收盘价/次日开盘的滑点；两种退出不可混报 |
| B：T 收盘选、T+1 低吸、T+2 卖 | T 收盘后形成信号和限价目标 | `P_limit=C[t]*(1-d)`；若 `O[t+1] <= P_limit`，按 `O[t+1]` 成交；否则仅当 `L[t+1] <= P_limit` 时按 `P_limit` 成交；未触及则无交易 | `d` 用固定百分比和 ATR/NATR 两族分别测试；T+2 先测 `O[t+2]`，另测 `C[t+2]`，不得事后选择更优成交价 |

T 日尾盘买入是否能以 `C[t]` 成交，取决于交易所规则、收盘集合竞价和下单时点；上交所当前规则入口见 [SSE-1]，深交所规则入口见 [SZSE-1]。这两个官方入口用于核对交易时段与成交机制，不能替代本仓的成交、排队和滑点模型。

## 2. 一手资料支持的机制

| 机制 | 原始资料能支持的最窄结论 | 可转成的日线观察量 | 不应声称的结论 |
| --- | --- | --- | --- |
| 中期动量/相对强弱 | Jegadeesh-Titman 研究 3--12 个月赢家/输家组合的持续性；George-Hwang 研究距 52 周高点的动量信息 | `ROC_N`、相对指数超额收益、距过去高点的距离、横截面 percentile | 不能把美股月频结果变成本仓 A 股 T+1 胜率 |
| 短期反转 | Lehmann 的原始研究提供短期收益反转的检验动机 | `ROC_1`、`ROC_3`、`ROC_5` 的横截面低分位，配合成交量和波动状态 | 不能断言每个低跌幅股票都反弹，或反转不受流动性/成本影响 |
| 价格动量与成交量 | Lee-Swaminathan 将价格动量与成交量状态联系起来 | 异常量、异常换手、OBV、MFI、价量同向/背离 | 不能直接采用“放量倍数”作为论文结论 |
| 波动收缩/扩张 | Bollinger 官方规则给出中轨、标准差带和 BandWidth/Squeeze 解释；TA-Lib 给出 ATR/NATR 函数定义 | `BandWidth`、`NATR`、真实波幅、收缩后突破 | 收缩不是必然上涨；参数 20、2、14 只是规则或函数默认值 |
| 技术形态检验 | Lo-Mamaysky-Wang 的原始研究支持把技术形态转成可计算算法并做统计检验 | 收盘位置、突破、均线/带宽状态 | 不能把形态名称当作经济机制或已验证 alpha |
| 隔夜效应 | Cooper-Cliff-Gulen 区分交易时段与非交易时段收益；Qiao-Dam 专门研究中国股市隔夜收益与 T+1 规则 | `gap[t+1]=O[t+1]/C[t]-1`、T+1 盘中收益、T+1 低吸触发率 | 不能把平均隔夜效应视为个股稳定可交易收益；税费、涨跌停、不可卖出约束必须单独建模 |

## 3. 指标和公式定义

以下定义优先采用 TA-Lib 官方函数接口/源码或指标作者规则；`N` 是预先登记的参数，不是事后调到最优的结果。

### 3.1 动量、反转和相对强弱

| ID | 精确定义 | 首轮参数 | 适用策略与假设 |
| --- | --- | --- | --- |
| M1 `ROC_N` | `ROC_N[t] = 100 * (C[t] / C[t-N] - 1)`；等价的比例收益为 `C[t]/C[t-N]-1` | `N in {1, 3, 5, 20, 60}`；TA-Lib `ROC` 默认 `N=10` | A：正 `ROC_3/ROC_5` 配合高收盘位置可能延续至隔夜；负 `ROC_1/ROC_3` 的低分位可检验短期反转。B：T 日选股用 `ROC_20/ROC_60` 做横截面排序，不直接硬筛最高分 |
| M2 超额相对强弱 | `RS_N[t] = (C_stock[t]/C_stock[t-N]-1) - (C_index[t]/C_index[t-N]-1)`；按 T 日股票横截面做 percentile rank | `N in {5, 20, 60}`；指数、个股使用相同交易日和复权口径 | A/B：检验强于指数的股票是否分别表现为隔夜延续或低吸后的 T+2 延续；缺指数时不与有指数结果混报 |
| M3 高点距离 | `near_high_N[t] = C[t] / max(H[t-N],...,H[t-1])` | `N=20` 和 `N=120` | A：接近高点且不极端延伸的股票测试动量延续；B：接近高点但 T 日出现收缩/回撤时测试低吸后的恢复。`N=120` 只是 A 股六个月研究代理，不是 52 周原参数 |
| R1 短期反转 | `rev_N[t] = C[t]/C[t-N]-1`，在当日横截面取低分位；可增加 `abs(rev_1)` 上限避免把停牌复牌异常混入 | `N=1,3,5`；分位数先登记 20%/30% | A：测试 T 日短跌后 T+1 隔夜/次日收盘反弹；B：测试 T 日回撤后给出低吸目标。反转候选必须和异常换手、波动状态分层，否则可能只是流动性冲击 |

### 3.2 量价与换手

| ID | 精确定义 | 首轮参数 | 适用策略与假设 |
| --- | --- | --- | --- |
| Q1 相对成交量 | `rvol_N[t] = V[t] / mean(V[t-N:t-1])` | `N=20`；同时记录 `V[t] / median(V[t-N:t-1])` | A：高收盘位置 + 温和放量测试信息确认；极端放量单独分层，避免把流动性冲击当作强度。B：T 日选出“收缩后恢复”而非持续枯竭的标的 |
| Q2 相对换手 | `rto_N[t] = TO[t] / mean(TO[t-N:t-1])`；本仓 `TO` 为小数时保持小数口径 | `N=20`；按流动性分组后横截面排名 | A/B：测试相同价格信号中，换手是否比成交量绝对值提供额外信息；缺 `TO` 时该候选为缺失，不用 0 代替 |
| Q3 OBV 确认 | `OBV[t]=OBV[t-1]+V[t]` if `C[t]>C[t-1]`; `OBV[t]=OBV[t-1]-V[t]` if `C[t]<C[t-1]`; unchanged close adds 0 | 比较 `OBV[t]` 与 `max(OBV[t-20],...,OBV[t-1])`；不跨股票比较绝对 OBV | A：T 日收盘创新高且 OBV 同步创新高，测试隔夜延续；B：T 日价弱而 OBV 未破坏，测试 T+1 低吸后的恢复 |
| Q4 MFI | 使用典型价 `TP=(H+L+C)/3` 与成交量构造资金流，按正/负资金流比计算 MFI；实现直接调用 TA-Lib `MFI(H,L,C,V,N)`，不自行混用不同平滑 | `N=14`，注意 TA-Lib 标记的 unstable/warm-up period | A/B：作为量价确认的替代变量；只比较同一实现和同一预热规则，不把 MFI 70/30 当作官方交易阈值 |
| Q5 收盘位置 | `CLV[t]=(2*C[t]-H[t]-L[t])/(H[t]-L[t])`；若当日振幅为 0 则缺失 | `CLV>=0.5`、`>=0.8` 仅作为预注册分层点 | A：高 CLV 表示收盘靠近当日高位，测试强势收盘后的隔夜表现；B：低吸候选要求 T 日不是极端长上影，或单独比较长上影组。该量是本文的 OHLC 派生变量，不宣称为交易所标准指标 |

### 3.3 波动收缩与趋势状态

| ID | 精确定义 | 首轮参数 | 适用策略与假设 |
| --- | --- | --- | --- |
| V1 Bollinger BandWidth | `mid=SMA_N(C)`，`sd=sqrt(mean((C-mid)^2))`，`upper=mid+2*sd`，`lower=mid-2*sd`，`BBW=(upper-lower)/mid=4*sd/mid` | `N=20`、`2` 倍标准差；收缩定义为 `BBW[t-1]` 位于自身过去 60 日 20% 分位 | A：收缩后 T 日向上突破过去 20 日高点，测试隔夜延续；B：收缩后 T 日收盘选股，限价目标用固定百分比或 NATR，测试 T+1 回撤是否更容易成交并恢复 |
| V2 NATR | `TR[t]=max(H[t]-L[t], abs(H[t]-C[t-1]), abs(L[t]-C[t-1]))`；按 TA-Lib ATR 的 Wilder 平滑得到 `ATR_N`，`NATR_N=100*ATR_N/C[t]` | `N=14`；`NATR[t-1]` 低于此前 60 日 20% 分位 | A/B：作为 BBW 的稳健替代；只选 V1/V2 之一进入组合，避免同一波动信息重复计分 |
| V3 波动调整低吸目标 | `P_limit = C[t] * (1-d)`；固定目标 `d in {0.005,0.01,0.015}`，或 `d=max(0.005, k*NATR_14[t]/100)`，`k in {0.5,1.0}` | 目标价只能用 T 收盘前已知的 T 值；参数网格冻结后测 T+1 | B 专用：检验“波动收缩标的用浅回撤、扩张标的用深回撤”是否改变触发率和 T+2 净收益；触发率下降/成交选择性增强必须同时报告 |
| V4 趋势方向 | `MA20=SMA(C,20)`，测试 `C[t]>MA20[t]` 与 `MA20[t]>MA20[t-5]`；或使用 TA-Lib `ADX/PLUS_DI/MINUS_DI` 的官方接口 | 只选均线版本或 ADX 版本；ADX/DI 默认 14 并遵守预热期 | A：只做轻量确认，不能把反转策略变成长期趋势筛选；B：`C[t]>MA20` 作为低吸后恢复的先验，不得使用 T+1/T+2 价格 |

## 4. 面向两类策略的候选公式

### 4.1 A：T 日尾盘收盘买入，T+1 卖出

每个候选在 T 收盘后给出 `signal[t]`。建议先固定一个候选，不把所有条件相乘。

| ID | T 日条件 | 可证伪假设 | 主要风险 |
| --- | --- | --- | --- |
| A-1 强势收盘隔夜延续 | `CLV[t]>=0.8`，`rvol_20[t]` 位于 1.0--2.0，且 `RS_20[t]` 为当日横截面前 30% | 相比同股票池基线，`O[t+1]/C[t]-1` 的均值/中位数更高 | 收盘竞价成交不确定；极端行情、涨跌停和次日无法卖出 |
| A-2 短期反转隔夜 | `ROC_1[t]` 或 `ROC_3[t]` 位于横截面低 20%，但 `CLV[t]>=0` 且 `rto_20[t]` 不低于中位数 | T 日被动抛压后的隔夜反弹高于低换手下跌组 | 可能只是流动性差或坏消息未充分反映；交易成本会吞噬小反弹 |
| A-3 收缩后突破 | `BBW[t-1]` 处于过去 60 日低 20%，且 `C[t] > past_max_20[t]`，`CLV[t]>=0.5` | 低波动突破的 `O[t+1]/C[t]-1` 或 T+1 收盘收益高于无收缩突破 | 突破定义不能包含 `H[t]`；参数和“突破”高度相关，易重复计分 |
| A-4 量价一致 | `OBV[t] > past_max_20(OBV)[t]`，且 `RS_20[t]` 前 50%，不要求绝对成交量极大 | OBV 同步创新高的收盘信号隔夜收益更稳定 | OBV 绝对值不可跨股票比较；只能比较自身历史或横截面标准化值 |
| A-5 隔夜/盘中拆分 | 对 A-1 至 A-4 各自同时报告 `gap[t+1]` 与 `day[t+1]=C[t+1]/O[t+1]-1` | 优势若只在隔夜段，机制更接近非交易时段效应；若只在盘中，不应包装为隔夜公式 | 日线不能复原盘中路径；开盘价、涨跌停和不可成交必须单独标记 |

### 4.2 B：T 日收盘选股，T+1 低吸，T+2 卖出

T 日条件先选出候选和 `P_limit`；T+1 的 `L` 只用于判断预先挂出的限价单是否触发。成交后才进入 T+2 退出统计。

| ID | T 日条件与低吸目标 | 可证伪假设 | 主要风险 |
| --- | --- | --- | --- |
| B-1 动量回撤低吸 | `RS_20[t]` 前 30%，`ROC_5[t] > 0`，`CLV[t]` 在 0--0.8；`P_limit=C[t]*(1-1%)` | 强于指数但非极端收盘的标的，T+1 浅回撤成交后 T+2 收益优于无 RS 组 | 追高标的可能 T+1 直接低开；`1%` 只是研究点，不是规则结论 |
| B-2 收缩后的浅回撤 | `BBW[t]` 低于过去 60 日 20% 分位，且 `RS_20[t]` 不低于中位数；`d=max(0.5%,0.5*NATR_14[t]/100)` | 收缩标的 T+1 触及较浅目标的条件概率更高，且成交后的 T+2 方向更稳定 | 触发率和收益可能负相关；若只看已成交样本会产生选择偏差 |
| B-3 短期过度下跌反转 | `ROC_3[t]` 横截面最低 20%，`rto_20[t]` 高于中位数，`CLV[t]>=0`；`d=1%` | 高换手但收盘未失守的短跌，T+1 回撤后 T+2 反弹比低换手短跌更强 | 重大信息下高换手可能是继续下跌而非反转；需按消息不可得性和涨跌停分组 |
| B-4 量价未破坏 | `C[t]` 低于近 5 日高点但 `OBV[t] > past_max_20(OBV)[t]`；`d=0.5%` 或 `1%` 分层 | 价回撤而资金流未破坏的股票，T+1 低吸后 T+2 收益优于 OBV 同步走弱组 | OBV 对价格方向离散编码，不能替代真实订单流；成交量质量有数据源差异 |
| B-5 隔夜状态分层 | 先按 `gap[t]=O[t]/C[t-1]-1` 分为正、近零、负三组，再在每组测试 B-1 至 B-4 | T 日开盘缺口状态会改变 T+1 低吸触发率和 T+2 收益，故不能混成一条平均曲线 | 分组会减少样本；不能用 T+1 实际缺口回填 T 日分类 |

## 5. 时间一致性、A 股边界与验收

1. **收盘信号**：所有 T 日指标必须在 T 收盘后冻结。`past_max_N[t]`、均量、分位数和历史排名排除 T；若指标本身定义为 T 日收盘值，可以使用 T，但成交从 T+1 开始时不得把未来成交价带回信号。
2. **尾盘买入**：若模型使用 `C[t]`，必须把它标记为“理想化收盘成交”；真实验收至少与次日开盘成交、收盘滑点和涨跌停不可成交分开报告。
3. **T+1 低吸**：`L[t+1] <= P_limit` 只说明限价单触发，不说明能以日内最低价成交。使用 `O[t+1] <= P_limit` 时按开盘价成交，否则按预挂目标价成交；未触发的样本不能进入 T+2 收益分母而不披露。
4. **T+2 卖出**：默认用 `O[t+2]` 作为无未来信息的退出价；若使用 `C[t+2]`，必须显式命名为“持有到 T+2 收盘”，不能与开盘退出混在一起。
5. **涨跌停和停牌**：日线 `H/L` 不能保证可成交。应记录 T+1/T+2 是否触及涨跌停、是否停牌、是否存在不能卖出的状态；没有分钟级队列数据时，对相关交易做保守剔除或单独区间估计。
6. **复权和指数**：个股和基准指数使用一致复权逻辑；`gap`、`O/C` 的执行价格必须明确是否使用原始价格。复权切点不能造成虚假的隔夜跳空。
7. **预热**：TA-Lib 标记 `ATR/NATR`、`ADX/DI`、`MFI`、`RSI` 等存在 unstable/warm-up period；预热期保持缺失，不用部分窗口伪造信号。BBANDS 使用完整窗口。
8. **验证设计**：先冻结股票池、行情快照、复权、成本和退出口径；用前段训练、后段验证，再做滚动前进验证。每个候选必须报告信号数、活跃日、触发率、成交数、胜率、平均净收益、盈亏比、最大回撤和滑点敏感性。
9. **不以幸存者偏差取胜**：股票池应按当日可知的上市/停牌/ST/退市状态重建；不能用当前仍存续股票名单回填历史。

## 6. 来源目录

### 原始论文

- **[P1]** Jegadeesh, N.; Titman, S. (1993), *Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency*, The Journal of Finance. [DOI](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x)
- **[P2]** De Bondt, W. F. M.; Thaler, R. (1985), *Does the Stock Market Overreact?*, The Journal of Finance. [DOI](https://doi.org/10.1111/j.1540-6261.1985.tb05004.x)
- **[P3]** Lehmann, B. N. (1990), *Fads, Martingales, and Market Efficiency*, The Quarterly Journal of Economics. [DOI](https://doi.org/10.2307/2937816)
- **[P4]** Lee, C. M. C.; Swaminathan, B. (2000), *Price Momentum and Trading Volume*, The Journal of Finance. [DOI](https://doi.org/10.1111/0022-1082.00280)
- **[P5]** George, T. J.; Hwang, C.-Y. (2004), *The 52-Week High and Momentum Investing*, The Journal of Finance. [DOI](https://doi.org/10.1111/j.1540-6261.2004.00695.x)
- **[P6]** Lo, A. W.; Mamaysky, H.; Wang, J. (2000), *Foundations of Technical Analysis: Computational Algorithms, Statistical Inference, and Empirical Implementation*, The Journal of Finance. [DOI](https://doi.org/10.1111/0022-1082.00265)
- **[P7]** Qiao, K.; Dam, L. (2020), *The overnight return puzzle and the “T+1” trading rule in Chinese stock markets*, Journal of Financial Markets. [DOI](https://doi.org/10.1016/j.finmar.2020.100534)
- **[P8]** Cooper, M. J.; Cliff, M. T.; Gulen, H. (2008), *Return Differences between Trading and Non-Trading Hours: Like Night and Day*. [SSRN/DOI](https://doi.org/10.2139/ssrn.1004081)

### 官方指标规则与实现

- **[I1]** TA-Lib Python 官方函数索引：动量函数，包含 `ROC`、`RSI`、`MFI`、`ADX/DI` 等接口及默认参数/预热说明。 [链接](https://ta-lib.github.io/ta-lib-python/func_groups/momentum_indicators.html)
- **[I2]** TA-Lib Python 官方函数索引：波动率函数，包含 `ATR`、`NATR`、`TRANGE`。 [链接](https://ta-lib.github.io/ta-lib-python/func_groups/volatility_indicators.html)
- **[I3]** TA-Lib Python 官方函数索引：成交量函数，包含 `OBV`、`AD`、`ADOSC`。 [链接](https://ta-lib.github.io/ta-lib-python/func_groups/volume_indicators.html)
- **[I4]** TA-Lib 官方 C 源码：`BBANDS`、`ATR`、`NATR`、`RSI`、`OBV`、`MFI`、`ROC` 的实际实现。 [BBANDS](https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_BBANDS.c) · [ATR](https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_ATR.c) · [NATR](https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_NATR.c) · [RSI](https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_RSI.c) · [OBV](https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_OBV.c) · [MFI](https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_MFI.c) · [ROC](https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_ROC.c)
- **[I5]** John Bollinger 官方规则：20 期中轨、标准差带、BandWidth 和 Squeeze 的解释；默认参数不是对所有市场的有效性保证。 [链接](https://www.bollingerbands.com/bollinger-band-rules)

### 交易所官方规则入口

- **[SSE-1]** 上海证券交易所《规则总览》，用于核对当前交易规则、交易时段和收盘成交机制的具体条款。 [链接](https://www.sse.com.cn/lawandrules/sselawsrules2025/overview/)
- **[SZSE-1]** 深圳证券交易所规则入口，用于核对深市交易规则和成交机制。 [链接](https://www.szse.cn/lawrules/rule/)

## 7. 最小研究顺序

1. 先在 A 策略上把收益拆成隔夜和盘中两段，只比较 `A-1/A-2/A-3` 的单因子结果。
2. 再在 B 策略上固定 `P_limit` 的三档百分比，单独报告触发率与成交后收益，优先测试 `B-1/B-2`。
3. 在单因子通过样本外之前，不组合 `BBW + NATR`、`ROC + RS`、`OBV + MFI` 等高度相关变量。
4. 只有在样本外方向、成交率和交易成本敏感性都稳定时，才把候选交给本仓现有策略/回测流程；本研究本身不修改那些代码。
