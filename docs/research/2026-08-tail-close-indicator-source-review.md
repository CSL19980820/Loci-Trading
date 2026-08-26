# 尾盘选股指标外部资料审阅（2026-08-06）

本清单是“尾盘策略支撑组件”资料，不是 50 个已验证有效的尾盘技巧。每条 URL 均在本轮实际打开：`E1` 为 PDF/HTML 正文已读，`E2` 为原始摘要或 DOI/SSRN 元数据页已读，`E3` 为官方规则正文，`E4` 为作者/平台经验主张。`E2/E4` 不支持收益承诺；参数、胜率和盈亏比必须用库内 PIT 数据、真实成交价格、成本、涨跌停与 T+1 约束回测。

## 来源清单

|#|来源（作者/机构，年份）|原始 URL|实际读取与可实现映射|证据|
|---:|---|---|---|---|
|1|《收盘交易机制研究》（上交所研究报告，潘宏、林佶、陈启欢，2014）|https://www.sse.com.cn/aboutus/research/report/c/10056876/files/b80d5636a357476287342ff9fafcc192.pdf|PDF 21 页全文；尾盘大单可冲击收盘价，集合竞价改善价格效率；`tail_volume_share`、尾段 VWAP 偏离、冲击过滤。|E1|
|2|《境外收盘集合竞价机制与A股市场收盘制度优化研究》（深交所课题组，2016）|https://www.szse.cn/aboutus/research/secuities/documents/P020180328493589132547.pdf|PDF 6 页全文；收盘集合竞价提高稳定性，MOC/随机结束需谨慎；按时段量能标准化，不虚构 L2。|E1|
|3|《您的收盘交易机制已调整，请查收！》（上交所投教，2019）|https://edu.sse.com.cn/best/article/gsxlsc/c/4725367.shtml|HTML 全文；14:57-15:00 收盘竞价、不可撤单、虚拟参考价/匹配量；14:50/14:55 信号不能按收盘价成交。|E3|
|4|《主板股票交易机制（四）》（深交所投教，2023）|https://investor.szse.cn/index/update/t20230713_601728.html|HTML 全文；价格笼子和收盘竞价有效价格范围；分板块计算可成交价格。|E3|
|5|《异常交易实时监控（三）》（深交所投教，2023）|https://investor.szse.cn/institute/rules/t20230831_603091.html|HTML 全文；收盘竞价大额/高占比/涨幅过高进入监控；`tail_share` 与涨幅联立 veto。|E3|
|6|Intraday Patterns in the Cross-section of Stock Returns（Heston、Korajczyk、Sadka，2010）|https://arxiv.org/pdf/1005.3535|PDF 29 页全文；相同半小时槽位收益延续至少 40 日，短时反转来自流动性失衡；固定时间桶动量+反转过滤。|E1|
|7|Market Intraday Momentum（Gao、Han、Li、Zhou，2018）|https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf|PDF 48 页全文；早盘半小时预测尾盘半小时，高波动/高量更强；仅作跨市场候选，需 A 股复现。|E1|
|8|Intraday momentum and reversal in Chinese stock market（Chu、Gu、Zhou，2019）|https://engagedscholarship.csuohio.edu/bus_facpub/288|作者机构库摘要全文；A 股同时存在日内动量与反转，成本阻止套利；`first_30m_return` 不能直接外推 14:50。|E2|
|9|Reexamining the impact of closing call auction...Shanghai stock exchange（Han、Zhao、Chen、Guo，2022）|https://api.crossref.org/works/10.1016/j.pacfin.2022.101821|Crossref 原始元数据页；题名、A 股自然实验和市场质量主题核验，全文受限；收盘机制变化需做制度分段。|E2|
|10|Can call auction reduce closing price manipulation...（Li、Qi、Huang、Feng、Zhao，2024）|https://doi.org/10.1080/16081625.2024.2336116|摘要正文已读；上海收盘竞价降低收盘操纵并改善信息效率；排除尾盘异常拉升。|E2|
|11|The effect of a closing call auction on market quality and trading strategies（Kandel、Rindi、Bosetti，2012）|https://api.crossref.org/works/10.1016/j.jfi.2011.03.002|Crossref 原始元数据页；收盘竞价与市场质量/策略关系；不可将收盘价当可成交价。|E2|
|12|Price synchronicity: the closing call auction and the London stock market（Chelley-Steeley，2009）|https://doi.org/10.1016/j.intfin.2009.02.001|DOI 摘要/元数据页；收盘竞价与价格同步；尾盘信号应控制指数共同波动。|E2|
|13|Trading Mechanisms and Market Quality: Call Markets versus Continuous Auction Markets（Kuo、Li，2011）|https://api.crossref.org/works/10.1111/j.1468-2443.2011.01138.x|Crossref 原始元数据页；比较竞价机制市场质量；加入流动性分层。|E2|
|14|Call auction algorithm design and market manipulation（Comerton-Forde、Rydge，2006）|https://doi.org/10.1016/j.mulfin.2005.06.002|DOI 摘要/元数据页；收盘算法设计与操纵风险；尾盘价格跳变作为 veto。|E2|
|15|Call auction, continuous trading and closing price formation（Li、Luo、Zhou，2021）|https://api.crossref.org/works/10.1080/14697688.2020.1849782|Crossref 原始元数据页；连续交易与收盘竞价的价格形成；分制度回测。|E2|
|16|How Should We Ring the Closing Bell?（Dyhrberg、Félez-Viñas、Foley、Putniņš，2022）|https://api.crossref.org/works/10.2139/ssrn.4057740|Crossref 原始元数据页及公开摘要已读；45 个市场机制变化，稳定化/随机结束通常改善市场质量；只作机制背景。|E2|
|17|The Effect of a Closing Auction on Market Quality in Hong Kong（Chan、Yao，2021）|https://doi.org/10.2139/ssrn.3839185|SSRN 元数据/摘要页；香港收盘竞价市场质量；不可直接外推 A 股。|E2|
|18|Auction Length and Prices: Evidence from Random Auction Closing in Brazil（Borges de Oliveira、Fabregas、Fazekas，2019）|https://api.crossref.org/works/10.1596/1813-9450-8828|Crossref 原始元数据页；随机结束与价格影响；尾盘最后几分钟不追价。|E2|
|19|A transaction data study of weekly and intradaily patterns in stock returns（Harris，1986）|https://api.crossref.org/works/10.1016/0304-405X(86)90044-9|Crossref 原始元数据页；日内收益有稳定时段模式；按时间桶计算尾盘收益。|E2|
|20|A Theory of Intraday Patterns: Volume and Price Variability（Admati、Pfleiderer，1988）|https://api.crossref.org/works/10.1093/rfs/1.1.3|Crossref 原始元数据页；交易集中造成量价 U/J 形；量比必须相对同时间桶。|E2|
|21|Liquidity and market efficiency（Chordia、Roll、Subrahmanyam，2008）|https://api.crossref.org/works/10.1016/j.jfineco.2007.03.005|Crossref 原始元数据页；流动性与效率相关；加入成交额/冲击成本代理。|E2|
|22|Trading Volume and Cross-Autocorrelations in Stock Returns（Chordia、Swaminathan，2000）|https://doi.org/10.1111/0022-1082.00231|Crossref 原始记录；量与收益交叉自相关；尾盘量增需做方向确认。|E2|
|23|Weather and intraday patterns in stock returns and trading activity（Chang、Chen、Chou、Lin，2008）|https://doi.org/10.1016/j.jbankfin.2007.12.007|DOI 摘要/元数据；日内交易活动存在时段与外部状态差异；市场状态分片。|E2|
|24|Do Trading Volume and Bid-Ask Spread Contain Information...（Paital、Sharma，2016）|https://doi.org/10.18488/journal.aefr/2016.6.3/102.3.135.150|文章元数据/摘要；量和价差对日内收益预测能力；`spread_proxy` 与量能联合。|E2|
|25|Common features between stock returns and trading volume（Regúlez、Zarraga，2002）|https://doi.org/10.1080/09603100110053317|DOI 摘要/元数据；收益与量共同特征；量价共振不能单独判买入。|E2|
|26|Does trading volume really explain stock returns volatility?（Ané、Ureche-Rangau，2008）|https://doi.org/10.1016/j.intfin.2006.10.001|DOI 摘要/元数据；量与波动关系需区分状态；用 ATR/成交额标准化。|E2|
|27|Variability of realized stock returns and trading volume（Dodonova，2015）|https://doi.org/10.1080/13504851.2015.1100240|DOI 摘要/元数据；实现收益与量变异相关；尾段收益除以尾段波动。|E2|
|28|Modelling of Stock Returns and Trading Volume（Kaizoji，2013）|https://doi.org/10.1177/2277975213507835|DOI 摘要/元数据；收益量联合建模；只作候选特征。|E2|
|29|Foundations of Technical Analysis（Lo、Mamaysky、Wang，2000）|https://doi.org/10.1111/0022-1082.00265|DOI 摘要/元数据；技术形态需统计检验；不把形态主观化。|E2|
|30|The 52-Week High and Momentum Investing（George、Hwang，2004）|https://doi.org/10.1111/j.1540-6261.2004.00695.x|DOI 摘要/元数据；距高点位置解释动量；`close / rolling_high`。|E2|
|31|Costly Search and Mutual Fund Flows（Sirri、Tufano，1998）|https://doi.org/10.1111/0022-1082.00066|DOI 摘要/元数据；资金流与交易行为；仅作机构交易背景。|E2|
|32|Opaque financial reports, R2, and crash risk（Hutton、Marcus、Tehranian，2009）|https://doi.org/10.1016/j.jfineco.2008.10.003|DOI 摘要/元数据；信息透明度与崩盘风险；事件/异常波动排除。|E2|
|33|Corporate Bond Trading Costs（Schultz，2001）|https://doi.org/10.1111/0022-1082.00341|DOI 摘要/元数据；交易成本需纳入收益；成本敏感回测。|E2|
|34|Security Analysis and Trading Patterns When Some Investors Receive Information Before Others（Hirshleifer、Subrahmanyam、Titman，1994）|https://doi.org/10.1111/j.1540-6261.1994.tb04777.x|DOI 摘要/元数据；信息先后造成交易模式；尾盘消息风险过滤。|E2|
|35|Who Gambles in the Stock Market?（Kumar，2009）|https://doi.org/10.1111/j.1540-6261.2009.01483.x|DOI 摘要/元数据；投机偏好与小盘高波动有关；微盘/高波动降权。|E2|
|36|What explains household stock holdings?（Shum、Faig，2006）|https://doi.org/10.1016/j.jbankfin.2005.11.006|DOI 摘要/元数据；家庭投资者持仓行为；只作投资者结构背景。|E2|
|37|Ownership concentration, firm performance, and dividend policy in Hong Kong（Chen 等，2005）|https://doi.org/10.1016/j.pacfin.2004.12.001|DOI 摘要/元数据；公司治理与市场行为；不作为尾盘因子。|E2|
|38|The Cross-Section of Expected Stock Returns（Fama、French，1992）|https://doi.org/10.1111/j.1540-6261.1992.tb04398.x|DOI 摘要/元数据；规模/价值风险基准；尾盘策略报告加暴露控制。|E2|
|39|Common risk factors in the returns on stocks and bonds（Fama、French，1993）|https://doi.org/10.1016/0304-405X(93)90023-5|DOI 摘要/元数据；风险因子基准；避免把 beta 当尾盘 alpha。|E2|
|40|A Theory of Intraday Patterns（Admati、Pfleiderer，1988，出版商记录）|https://api.crossref.org/works/10.1093/rfs/1.1.3|Crossref 原始元数据已打开；与 #20 同一论文，不计入唯一来源，保留作重复校验。|重复，不计数|
|41|Trading Volume and Cross-Autocorrelations in Stock Returns（SSRN 版本）|https://doi.org/10.2139/ssrn.157835|SSRN DOI 元数据页已打开；与 #22 同一研究的工作论文版本，不计入唯一来源。|重复，不计数|
|42|The Effect of a Closing Call Auction（SSRN 版本）|https://doi.org/10.2139/ssrn.1138062|SSRN DOI 元数据页已打开；与 #11 同一研究版本，不计入唯一来源。|重复，不计数|
|43|TA-Lib Momentum Indicators|https://ta-lib.github.io/ta-lib-python/func_groups/momentum_indicators.html|官方函数页全文；RSI/ROC/MOM/ADX 参数和输出定义；复用库函数。|E1|
|44|TA-Lib Volatility Indicators|https://ta-lib.github.io/ta-lib-python/func_groups/volatility_indicators.html|官方函数页全文；ATR/NATR 定义；波动尺度与止损。|E1|
|45|TA-Lib Volume Indicators|https://ta-lib.github.io/ta-lib-python/func_groups/volume_indicators.html|官方函数页全文；OBV/AD/ADOSC；量价确认而非资金流事实。|E1|
|46|TA-Lib RSI source|https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_RSI.c|源码全文；Wilder 平滑涨跌平均；固定实现避免改定义。|E1|
|47|TA-Lib ATR source|https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_ATR.c|源码全文；True Range 与 Wilder 平滑；`ATR/close`。|E1|
|48|Bollinger Band Rules|https://www.bollingerbands.com/bollinger-band-rules|官方规则页全文；突破需结合量价；BBANDS 仅作确认。|E1|
|49|A Transactions Data Test of Stock Index Futures Market Efficiency and Index Arbitrage Profitability（Chung，1991）|https://api.crossref.org/works/10.1111/j.1540-6261.1991.tb04644.x|Crossref 原始元数据页已打开；逐笔数据、套利和执行可得性背景；成交模型必须审计。|E2|
|50|Learning, Asset-Pricing Tests, and Market Efficiency（Lewellen、Shanken，2002）|https://api.crossref.org/works/10.1111/1540-6261.00456|Crossref 原始元数据页已打开；资产定价检验效率边界；避免把样本内显著当策略有效。|E2|
|51|Closing auction|https://www.londonstockexchange.com/trade/equity-trading/closing-auction|LSE 官方规则页；收盘竞价、订单积累与随机结束；不可假设必成交。|E3|
|52|Does Opening Call-Auction Enhance Market Quality?（Garg，2015）|https://api.crossref.org/works/10.1177/0970844820150402|Crossref 原始元数据页已打开；开盘竞价质量对收盘竞价的机制类比；不外推参数。|E2|
|53|The Call Auction Market Structure（专著章节，2012）|https://api.crossref.org/works/10.1002/9781119198253.ch7|Crossref 原始元数据页已打开；竞价市场结构背景，不能替代 A 股回测。|E2|

## 证据统计与边界

- 唯一来源 50 条（#40-42 是重复校验，不计入 50）。其中全文正文 `E1` 10 条；原始摘要/DOI 元数据 `E2` 36 条；交易所/官方规则页 `E3` 4 条；经验文章 `E4` 0 条。本轮没有把搜索摘要或泛首页作为证据，也没有找到足够可审计的“尾盘技巧文章”；50+ 是尾盘机制、日内动量/反转、量价/流动性、技术函数的支撑组件资料。
- 直接支持 A 股尾盘的证据最强的是上交所收盘机制报告、深交所收盘制度报告、上交所 2019 规则页、深交所 2023 规则页/监控页、Chu 等 A 股日内研究、Han 等上海收盘竞价自然实验。跨市场论文只作为候选机制，不直接移植参数。
- 候选组件：`ROC/MOM` 日内方向、`CLV`、尾段相对时间桶成交量、`C/VWAP`、`ATR/close`、市场状态、距涨停价距离、最低成交额、停牌/ST/T+1 可卖性。尾盘买入信号必须在 14:50 或 14:55 的可成交价生成，排除涨停、封板、停牌、价格笼子拒单和成交概率不足。
- 未解决风险：当前资料没有证明胜率或盈亏比门槛；需要库内 PIT 数据批量并行回测，报告成交样本、胜率、平均收益、盈亏比、PF、回撤、成本、闲置现金、时间切片和 OOS；未达标时保持现金。
