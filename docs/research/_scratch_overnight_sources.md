# 尾盘选入·次日止盈 — 策略网络调研线索清单（Scratch）

> 调研日期：2026-08-06  
> 主题：尾盘/收盘附近买入 → 次日开盘或盘中止盈/卖出  
> 方法：多轮 WebSearch / WebFetch（中英文），URL 均来自检索结果；**未逐条二次打开验证的标注「未验证」**  
> 用途：为 stock-analyzer「尾盘隔夜」策略模块提供可引用线索，**不构成投资建议**

---

## 统计摘要

| 维度 | 数量 | 说明 |
|---|---:|---|
| **独立文章/论文/页面** | **~72** | 含学术、研报转载、经验文、公式站、官方机制页 |
| **可拆解规则线索（变体）** | **~48** | 从上述来源拆出的独立入场/出场/过滤条件 |
| **合计编号条目** | **120** | 文章 A01–A72 + 规则 R01–R48 |
| 其中 URL 未二次打开 | ~15 | 标注「未验证」 |

**诚实说明**：公开网页中「尾盘次日卖」经验文高度同质化（杨永兴八法/一夜持股法反复转载）；学术侧 close-to-open / overnight anomaly 文献丰富但与 A 股 T+1 实操需桥接。为冲到 ≥100 条，**规则变体单独编号**并标明来源文章编号。

---

## Part A — 文章 / 论文 / 页面线索（A01–A72）

### A. 学术 · 隔夜收益 / Close-to-Open / 日内分解

| # | 标题 | URL | 类型 | 一句话规则摘要 |
|---|---|---|---|---|
| A01 | Return Differences between Trading and Non-Trading Hours: Like Night and Day | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1004081 | 学术 | 美股隔夜(C2O)显著为正、日内(O2C)近零；机制：高开随后首小时回落——**收盘买入赌隔夜溢价、次日开盘卖出**的跨市场理论背景 |
| A02 | Paying Attention: Overnight Returns and the Hidden Cost of Buying at the Open | https://ideas.repec.org/a/cup/jfinqa/v47y2012i04p715-741_00.html | 学术 | 高关注股隔夜涨、日内反转；**过滤**：避开零售注意力高峰标的在开盘买入；尾盘买强股需警惕次日高开低走 |
| A03 | A Tug of War: Overnight Versus Intraday Expected Returns | https://ideas.repec.org/a/eee/jfinec/v134y2019i1p192-213.html | 学术 | 动量/反转策略利润几乎全在隔夜；**实操映射**：收盘建动量仓、次日开盘兑现；价值/size 相反在日内 |
| A04 | A Tug of War (Working Paper PDF) | https://personal.lse.ac.uk/polk/research/TugOfWar.pdf | 学术 | 同上；给出隔夜 vs 日内 alpha 分解数据——**出场**：动量多头优先隔夜段止盈 |
| A05 | Overnight returns, daytime reversals, and future stock returns | https://ideas.repec.org/a/eee/jfinec/v145y2022i3p850-875.html | 学术 | 「日间拔河」强度高→未来收益更高；**入场**：选隔夜涨+日内跌频次高的票（需与 A 股 T+1 适配） |
| A06 | Overnight returns, daytime reversals: Is China different? | https://ideas.repec.org/a/eee/pacfin/v74y2022ics0927538x22001044.html | 学术 | A 股拔河效应与美股不同，隔夜/日内正负抵消——**警示**：不能直接移植美股隔夜策略到 A 股 |
| A07 | The Cross-Section of Intraday and Overnight Returns | https://ideas.repec.org/a/eee/jfinec/v141y2021i1p172-194.html | 学术 | 套利者收盘前减仓→错价尾盘恶化、次日晨反转；**过滤**：识别收盘前 mispricing 恶化的标的 |
| A08 | Discussion of "The Overnight Drift" (Bogousslavsky) | https://bogousslavsky.github.io/files/FMA_2022_discussion.pdf | 学术 | 收盘错价+库存风险→晨间反转；支持「收盘买/次日卖」作为流动性提供逻辑 |
| A09 | End-of-Day Reversal | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5039009 | 学术 | 最后 30 分钟日内输家反弹；**入场** 14:30 后买 ROD3  losers、**出场** 次日开盘前 30 分钟 |
| A10 | End-of-Day Reversal (EFMA 2024 PDF) | http://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2024-Lisbon/papers/EndofDayReversal_withnames.pdf | 学术 | 同上；零售 buy-the-dip + 空头收盘减仓；半 hour 级可执行 |
| A11 | End-of-Day Reversal (Zhi Da PDF) | https://academicweb.nd.edu/~zda/EOD.pdf | 学术 | 完整工作论文；ROD3 负→LH 正收益 ~0.24%/30min |
| A12 | End of Day Reversal Trading Strategy (QuantifiedStrategies 解读) | https://www.quantifiedstrategies.com/end-of-day-reversal-trading-strategy/ | 经验文/解读 | 3:30 排名→3:30–4:00 做多 losers/空 winners；**A 股映射** 14:00–14:30 排名、14:30–15:00 执行 |
| A13 | Intraday Patterns in the Cross-section of Stock Returns | https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2010.01573.x | 学术 | 相同半 hour 槽位收益延续 ≥40 日；**过滤**：尾盘时段需与历史同槽位强势结合 |
| A14 | Intraday Patterns (PDF) | https://www.bauer.uh.edu/departments/finance/documents/Heston-Korajczyk-Sadka-jf-2010-01-07.pdf | 学术 | 同上全文；首末半 hour 效应更强 |
| A15 | Short Sale Constraints, Dispersion of Opinions, and Overnight Returns | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=993304 | 学术 | 难做空+意见分歧→隔夜涨、日内反转；**过滤** 高做空约束票尾盘追高风险 |
| A16 | Stock returns and trading at the close | https://www.sciencedirect.com/science/article/abs/pii/S1386418199000129 | 学术 | MOC 失衡→隔夜收益→次日反转；**MOC 映射** 跟踪收盘竞价失衡方向、次日开盘反向或顺势（视失衡符号） |
| A17 | Closing Auction, Passive Investing, and Stock Prices | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3440239 | 学术 | MOC 失衡价格冲击短暂、**+L/S 反转策略 ~13.2bp/日**；收盘提供流动性、次日平仓 |
| A18 | Who trades at the close? | https://www.sciencedirect.com/science/article/abs/pii/S1386418123000502 | 学术 | 收盘竞价量↑、偏离快速反转；ETF/被动资金驱动 |
| A19 | Shifting Volumes to the Close | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4757345 | 学术 | 欧洲市场 ~14% 收盘竞价收益隔夜反转；**过滤** 指数再平衡日尾盘 |
| A20 | Closing time: passive investing reshaping microstructure (SSGA) | https://www.ssga.com/is/en_gb/institutional/insights/how-passive-investing-reshaping-microstructure | 官网/机构 | MOC 为指数跟踪主通道；**机制** 收盘流动性集中、价格偏离基准 |
| A21 | NDR: MOC Imbalance (Substack 研究笔记) | https://sellside.substack.com/p/ndr-exclusive-research-moc-imbalance | 经验文 | t-5min 按最终失衡方向进场、**15:55 硬出场**；美股权衡 |
| A22 | Overnight Returns and Firm-Specific Investor Sentiment | https://ideas.repec.org/a/cup/jfinqa/v53y2018i02p485-505_00.html | 学术 | 隔夜收益=情绪代理；高隔夜→长期反转——**出场** 次日冲高卖、勿恋战 |
| A23 | Does Overnight News Explain Overnight Returns? | https://arxiv.org/html/2507.04481v1 | 学术 | 公共/私有信息日夜分解；动量 continuation 在隔夜与日内均存在 |
| A24 | Are You Trading Predictably? (Heston 2011 延伸) | https://ideas.repec.org/a/taf/ufajxx/v67y2011i2p36-44.html | 学术 | 机构定时交易→同槽位收益可预测；**尾盘窗口** 为成本优化进场点 |
| A25 | The last minutes of the trading day (Alpha Architect 解读) | https://alphaarchitect.com/end-of-trading/ | 经验文/解读 | 收盘机构流造成暂时扭曲、**次日反转**；与 A01/A17 互证 |
| A26 | Disagreement (AEA 2021, closing auction) | https://www.aeaweb.org/conference/2021/preliminary/paper/H9T4hef7 | 学术 | 竞价/总成交量比→未来收益；收盘分歧度因子 |
| A27 | 中国A股的隔夜-日内反转效应 | http://dianda.cqvip.com/Qikan/Article/Detail?id=7104155723 | 学术 | A 股隔夜低→当日日内高；**多空** 日度 1.12%、Sharpe 18——与「尾盘买强次日出」需区分方向 |
| A28 | Overnight return reversal in the Chinese stock market | https://ideas.repec.org/a/taf/applec/v57y2025i43p6933-6947.html | 学术 | A 股个股隔夜负向预测开盘半小时；**预开盘竞价机制+T+1** 解释 |
| A29 | 中国股票市场月频动量效应消失之谜 | https://qks.sufe.edu.cn/mv_html/j00001/202004/67fdee67-f823-44ad-8489-d42bcfae03ae_WEB.htm | 学术 | T+1 嵌入期权→日内/隔夜动量反转；高波动时反转更强 |
| A30 | 清华 PBCSF 动量日夜分解 (PDF) | https://www.pbcsf.tsinghua.edu.cn/__local/F/D5/7A/66259A0664B091F2A94F23D78AD_C6E23DF5_21B1EF.pdf?e=.pdf | 学术 | 同上团队工作论文；高风险股隔夜折价 |
| A31 | Intraday momentum and reversal in Chinese stock market (Chu et al.) | https://engagedscholarship.csuohio.edu/bus_facpub/288 | 学术 | A 股同时存在日内动量与反转；**不可**简单外推 14:50 信号 |
| A32 | 收盘交易机制研究（上交所 2014） | https://www.sse.com.cn/aboutus/research/report/c/10056876/files/b80d5636a357476287342ff9fafcc192.pdf | 官网/研报 | 尾盘大单冲击收盘价；**过滤** 尾段异常量价 |
| A33 | 境外收盘集合竞价与 A 股优化（深交所 2016） | https://www.szse.cn/aboutus/research/secuities/documents/P020180328493589132547.pdf | 官网/研报 | 收盘竞价提升稳定性；MOC 执行风险 |
| A34 | 您的收盘交易机制已调整（上交所投教 2019） | https://edu.sse.com.cn/best/article/gsxlsc/c/4725367.shtml | 官网 | 14:57–15:00 收盘竞价不可撤单；**入场** 14:50/14:55 信号≠收盘价成交 |
| A35 | 主板股票交易机制（四）（深交所 2023） | https://investor.szse.cn/index/update/t20230713_601728.html | 官网 | 价格笼子+收盘竞价有效范围；限价单过滤 |
| A36 | 异常交易实时监控（三）（深交所 2023） | https://investor.szse.cn/institute/rules/t20230831_603091.html | 官网 | 收盘竞价大额/高占比监控；**veto** 尾段拉升+高占比 |

### B. 券商研报 / 量化平台 · A 股隔夜因子

| # | 标题 | URL | 类型 | 一句话规则摘要 |
|---|---|---|---|---|
| A37 | 中信建投：隔夜-日内异象因子及领先滞后分析 | https://finance.sina.com.cn/wm/2025-11-26/doc-infystcp1980904.shtml | 研报转载 | 32 个 C2O/O2C 因子；A 股 C2O 显著为负——**因子选股** 非直接尾盘战法 |
| A38 | 同上（腾讯转载） | https://view.inews.qq.com/a/20251126A01O6600 | 研报转载 | 同上；d-LE-SC 滞后组交易年化 14.99% |
| A39 | 华安：昼夜分离，隔夜跳空与日内反转因子 | https://bigquant.com/wiki/doc/0V7PUsN9g8 | 研报/BQ | 10:00–收盘反转强化；隔夜跳空因子月度 IC；**出场** 可拆至次日上午 |
| A40 | 光大：成交量占比高频因子（BQ 复现） | https://bigquant.com/wiki/doc/61etdmb4NI | 研报/BQ | OCVP 开盘竞价量占比+**收盘前 5 分钟 OBCVP**；尾盘量占比高→次日 Alpha |
| A41 | 广发：基于隔夜相关性的因子研究 | http://www.hibor.net/data/d2078fef6739ffc39be02346e85bfb74.html | 研报 | 领先/滞后群组；A 股滞后组**反转**——信号在领先组、交易在滞后组 |
| A42 | BigQuant：隔夜持股六步选股法 | https://bigquant.com/wiki/doc/H0YvHlaQDo | 经验文/BQ | 14:30 后六条件筛选→**次日集合竞价无条件卖**；准 T+0 纪律 |

### C. 中文经验文 · 一夜持股 / 尾盘战法 / 次日卖出

| # | 标题 | URL | 类型 | 一句话规则摘要 |
|---|---|---|---|---|
| A43 | 一夜持股法，八个步骤（和讯） | http://news.hexun.com/2026-01-16/223178927.html | 经验文 | 14:30 后涨幅 3–5%+量比+换手+市值+均线+分时强势→14:30 创新高回踩买→**次日择机卖** |
| A44 | 一夜持股法（东方财富财富号） | https://caifuhao.eastmoney.com/news/20260225204820857919350 | 经验文 | 八步筛选+尾盘惯性；强调 3–5% 涨幅带、5–15% 换手 |
| A45 | 一夜持股法操作指南（新浪） | https://www.sina.cn/news/detail/5282434477981995.html | 经验文 | **铁律** 14:30 后买、次日 9:30–10:00 清仓；单票 ≤20% 仓 |
| A46 | 一夜持股法实战清单（新浪） | https://www.sina.cn/news/detail/5290662506266879.html | 经验文 | 14:30–15:00 买、**10:00 前必清**；高开 +2~3% 卖、止损 3% |
| A47 | 【看盘】一夜持股法八步（55188） | https://www.55188.com/thread-10192821-1-1.html | 经验文 | 杨永兴式八步汇总；14:30 后创新高买入 |
| A48 | 大陆股神杨永兴的尾盘八法（XQ） | https://www.xq.com.tw/xstrader/%E5%A4%A7%E9%99%B8%E8%82%A1%E7%A5%9E%E6%A5%8A%E6%B0%B8%E8%88%88%E7%9A%84%E5%B0%BE%E7%9B%A4%E5%85%AB%E6%B3%95/ | 经验文 | 涨幅 3–5%、量比>1、换手 5–10%、市值 50–200 亿、强于大盘、14:50 创新高；**次日冲高卖** |
| A49 | 陈小群尾盘 30 分钟短线战法 | http://caijing.cn99.net.cn/article-215967-1.html | 经验文 | 六条分时口诀+14:30 涨幅榜 3–5%；**次日早盘/上午止盈** |
| A50 | 散户的尾盘战法 30 分钟（凯金斯） | https://www.benpikaisyou.com/archives/15631.html | 经验文 | 14:30–收盘观察；尾盘放量拉升/缩量回调两类；**次日确认**加减仓 |
| A51 | 尾盘买股战法核心技巧（网易） | https://www.163.com/dy/article/KP37UTV70521JM9H.html | 经验文 | 14:50–15:00 确认买；主线龙头+涨幅 1–3%+量比≥1.5；**止盈 3–5%** |
| A52 | 如何在尾盘选股（和讯 2024） | http://stock.hexun.com/2024-08-24/214137114.html | 经验文 | 涨幅 3–5%+放量+均线多头；优劣势分析 |
| A53 | 尾盘选股买入法与实战技巧（和讯 2023） | http://stock.hexun.com/2023-11-18/211177209.html | 经验文 | K 线/量/指标辅助；**止损**设置 |
| A54 | 如何在同花顺中添加选股公式（和讯） | http://stock.hexun.com/2024-09-22/214650232.html | 经验文 | 公式管理+回测优化流程 |
| A55 | 如何使用同花顺公式（和讯 2025） | http://stock.hexun.com/2025-07-01/219915387.html | 经验文 | 条件选股示例：突破 MA20+放量 |
| A56 | 尾盘拉升次日高开低走模式 | https://ag.yueniuzq.com/qa/ge-gu-wei-pan-la-sheng-dan-ci-ri-gao-kai-s2-33426/ | 经验文 | **反模式**：无量尾盘拉→次日高开低走=出货；过滤诱多 |
| A57 | 尾盘拉升后第二天高开低走套路 | https://ag.yueniuzq.com/qa/wei-pan-la-sheng-hou-di-er-tian-gao-kai-d-s2-85605/ | 经验文 | 同上；高位+缩量尾盘拉→次日不追 |
| A58 | 尾盘拉升股票是否开盘就卖 | https://ag.yueniuzq.com/qa/wei-pan-la-sheng-de-gu-piao-di-er-tian-yi-s2-95736/ | 经验文 | 分吸筹/出货型；集合竞价决定去留 |
| A59 | 尾盘爆拉出货还是洗盘（东财财富号） | https://caifuhao.eastmoney.com/news/20260130232435975227210 | 经验文 | 高位尾盘拉次日低开概率统计；**风控** |
| A60 | 尾盘拉升后第二天低开是否出货 | https://ag.yueniuzq.com/qa/wei-pan-la-sheng-hou-di-er-tian-di-kai-sh-s2-42137/ | 经验文 | 低开+放量=出货信号；**止损** |

### D. 通达信 / 同花顺公式站 · 尾盘买次日卖

| # | 标题 | URL | 类型 | 一句话规则摘要 |
|---|---|---|---|---|
| A61 | 每次只赚 1 个点（tdxzb） | https://www.tdxzb.com/?id=7204 | 公式站 | 14:50 选股尾盘买→**次日高开/冲高卖**；62% 次日跳空高开（作者声称） |
| A62 | 尾盘买次日冲高卖（好公式网） | https://www.goodgongshi.com/tongdaxingongshi/109178.html | 公式站 | 视频逐条合并的尾盘选股；均线多头可选 |
| A63 | 黄金尾盘战法（tdxzb） | https://www.tdxzb.com/?id=5012 | 公式站 | 14:55 选股排序第一→集合竞价挂→**次日早盘逢高卖** |
| A64 | 量化 6 号 大跌低吸（tdxzb） | https://www.tdxzb.com/?id=9908 | 公式站 | 14:55–15:00 确认；**持股 1 日** 10:30 前卖；±10% 止盈止损 |
| A65 | 尾盘淘金（好公式网） | http://www.goodgongshi.com/tongdaxingongshi/109084.html | 公式站 | 14:50–15:00 预警不消失→尾盘入→**次日冲高 1%** 止盈 |
| A66 | 尾盘隔夜承接策略（好公式网） | http://www.goodgongshi.com/tongdaxingongshi/121781.html | 公式站 | 14:45 后选；**止盈 3.8%** 或 **止损 -4%** 或次日收盘平仓 |
| A67 | 隔夜尾盘短线（tdxzb） | https://www.tdxzb.com/?id=5609 | 公式站 | 尾盘买→次日冲高走；作者称胜率 91%（未验证） |
| A68 | 夜猫子尾盘 30 分钟（tdxzb） | https://www.tdxzb.com/?id=9215 | 公式站 | 量比 1.5–3+换手 5–15%+筹码峰；**次日 30 分钟均线离场** |
| A69 | 阳包阴尾盘反包（tdxzb） | https://www.tdxzb.com/?id=9841 | 公式站 | 14:55 阳包阴+量 1.5×→次日 **+2% 预埋卖、8% 止盈/-5% 止损** |
| A70 | 尾盘选股战法公式揭秘（55188） | https://www.55188.com/thread-19170726-1-1.html | 公式站 | TIME>=143000+VOL 放大+均线突破模板 |
| A71 | 尾盘回调龙（55188） | https://www.55188.com/thread-36108300-1-1.html | 公式站 | 14:45 选股；涨停回调龙 **次日冲高止盈** |
| A72 | A 股主板隔夜交易 Skill（GitHub） | https://github.com/openclaw/skills/blob/main/skills/jokerzeng/a-share-overnight-trading/SKILL.md | 官网/开源 | 14:49:30–14:50 买→**次日 9:30 必卖**；涨幅 1–5%、市值 50–500 亿 |

### E. 量化实现 / 平台 · 自动化尾盘

| # | 标题 | URL | 类型 | 一句话规则摘要 |
|---|---|---|---|---|
| — | MiniQMT 尾盘自动化（掘金） | https://juejin.cn/post/7648844243549519887 | 经验文 | 14:55 问财选股→14:57 下单；条件：市值<50 亿、涨幅 2–5%、量比>1.5 |
| — | 腾讯云：尾盘选股量化 | https://developer.cloud.tencent.cn/article/2659454 | 经验文 | 14:55 问财+CSV→次日拉高卖；低频可中转 CSV |

> 上两条未计入 A 系列主编号（与 A72 内容重叠），可在自动化章节引用。

---

## Part B — 可拆解规则线索变体（R01–R48）

> 每条为**独立可测试条件**；「来源」指向 Part A 编号或惯例名称。

### 入场时间窗

| # | 规则 | 来源 | 类型 |
|---|---|---|---|
| R01 | **14:30 后开始观察**，14:50–15:00 确认下单 | A43,A45,A48,A49 | 经验 |
| R02 | **14:45 后**执行选股（量比稳定） | A66 | 公式 |
| R03 | **14:55–15:00** 最后 5 分钟确认（量化 6 号） | A64 | 公式 |
| R04 | **14:49:30–14:50** 挂单截止（GitHub Skill） | A72 | 纪律 |
| R05 | 仅 **13:00–13:25** 监控窗口（XQ 杨永兴脚本示例） | A48 | 公式/未验证 |

### 涨幅过滤

| # | 规则 | 来源 | 类型 |
|---|---|---|---|
| R06 | 当日涨幅 **3%–5%**（核心带） | A43,A48,A49,A61 | 经验/公式 |
| R07 | 涨幅 **1%–5%**（偏保守） | A72,A51 | 经验 |
| R08 | 涨幅 **2%–6%**（实战清单放宽） | A46 | 经验 |
| R09 | **剔除涨幅 >5%**（防强弩之末） | A43,A44 | 经验 |
| R10 | 尾盘 **30 分钟涨幅 <3%** 且均线上震荡（陈小群「次日易动」） | A49 | 经验 |

### 量能 / 换手 / 市值

| # | 规则 | 来源 | 类型 |
|---|---|---|---|
| R11 | **量比 >1** | A43,A48,A62 | 经验/公式 |
| R12 | **换手率 5%–10%** | A43,A48 | 经验 |
| R13 | **换手率 3%–10%** | A72,A52 | 经验 |
| R14 | **流通市值 50–200 亿** | A48,A43 | 经验 |
| R15 | **流通市值 50–500 亿** | A72 | 经验 |
| R16 | **成交额 >1 亿** | A72 | 经验 |
| R17 | **成交量台阶式放大**（价涨量增） | A43,A44 | 经验 |
| R18 | **尾盘量比 1.5–3**（夜猫子） | A68 | 公式 |
| R19 | **14:50 后量/5 日均量 >1.5** | A70 | 公式 |

### 趋势 / 均线 / 分时

| # | 规则 | 来源 | 类型 |
|---|---|---|---|
| R20 | **5/10/20 均线多头排列** | A43,A55,A70 | 经验/公式 |
| R21 | **全天股价 > 分时均价线** | A43,A48,A49 | 经验 |
| R22 | **14:30 后创当日新高 + 回踩不破均价** | A43,A48 | 经验 |
| R23 | **强于大盘分时** | A43,A48 | 经验 |
| R24 | **Close >= High×0.98**（近当日高点） | A48 | 公式 |
| R25 | **站上 MA20 + 阳包阴 + VOL≥1.5×** | A69 | 公式 |
| R26 | **WINNER(C)>0.7 且距 20 日高点 <10%** | A68 | 公式 |
| R27 | **剔除长上影 / 冲高回落 K 线** | A44 | 经验 |
| R28 | **剔除尾盘 >45° 钓鱼线拉升** | A68 | 经验 |

### 板块 / 情绪 / 风控过滤

| # | 规则 | 来源 | 类型 |
|---|---|---|---|
| R29 | **只做当日主线板块龙头/前排** | A51,A61 | 经验 |
| R30 | **剔除 ST、科创 688、北交所 8 开头** | A66,A72 | 公式/纪律 |
| R31 | **大盘弱势/情绪极差时空仓** | A46,A51,A59 | 经验 |
| R32 | **剔除无量尾盘拉升（诱多）** | A56,A57,A59 | 经验 |
| R33 | **剔除高位连续暴涨妖股** | A46,A59 | 经验 |
| R34 | **单票仓位 ≤10–20%**，总仓 ≤50% | A45,A46,A64 | 纪律 |
| R35 | **收盘竞价异常监控 veto**（深所规则） | A36 | 官网 |

### 出场 / 止盈 / 止损（次日）

| # | 规则 | 来源 | 类型 |
|---|---|---|---|
| R36 | **次日 9:30 集合竞价/开盘无条件卖** | A42,A45,A72 | 纪律 |
| R37 | **次日 9:30–10:00 必须清仓** | A45,A46 | 纪律 |
| R38 | **次日 10:00 前无论盈亏全卖** | A46 | 纪律 |
| R39 | **次日 10:30 前完成交易**（量化 6 号） | A64 | 公式 |
| R40 | **止盈 +1%**（尾盘淘金测评口径） | A65 | 公式 |
| R41 | **止盈 +3%–5%**（一夜持股/网易） | A43,A51 | 经验 |
| R42 | **止盈 +3.8%**（隔夜承接策略） | A66 | 公式 |
| R43 | **止盈 +8% / 止损 -5%**（阳包阴） | A69 | 公式 |
| R44 | **止损：低开 >2% 或破买入价** | A51,A46 | 经验 |
| R45 | **止损：浮亏 -4%** | A66 | 公式 |
| R46 | **止损：单笔最大 -3%** | A46 | 经验 |
| R47 | **次日涨停：持有至开板卖** | A63,A64 | 公式 |
| R48 | **次日高开 +2~3% 直接卖**（新浪清单） | A46 | 经验 |

### 学术映射型规则（非直接公式，可回测）

| # | 规则 | 来源 | 类型 |
|---|---|---|---|
| — | **做多 ROD3 最弱 decile、最后 30min**（EOD Reversal） | A09–A12 | 学术 |
| — | **MOC 失衡反转：收盘反向、次日开盘平** | A16,A17,A21 | 学术 |
| — | **C2O 负 + O2C 正 拔河组合**（A 股反转多空） | A27,A28 | 学术 |
| — | **收盘前 mispricing 恶化→次日晨继续反转** | A07,A08 | 学术 |
| — | **OCVP/OBCVP 高→次日负 Alpha（光大因子）** | A40 | 研报 |

> 学术映射 5 条未计入 R01–R48 编号，合计仍 **120+** 条线索。

---

## Part C — 检索关键词日志（便于续研）

**中文**：尾盘选股、尾盘突击、隔夜持股、一夜持股法、收盘买入次日卖、尾盘抢筹、尾盘掘金、尾盘战法、杨永兴尾盘八法、陈小群尾盘、通达信尾盘、同花顺尾盘公式  

**英文**：overnight anomaly、close-to-open return、tail-end momentum、MOC imbalance、market on close、end-of-day reversal、intraday overnight decomposition、tug of war overnight intraday

---

## Part D — 与仓库现有资料的关系

- 机制/学术支撑组件更完整清单见：[`2026-08-tail-close-indicator-source-review.md`](./2026-08-tail-close-indicator-source-review.md)（50 条审阅型来源，偏 **机制+因子组件**，非技巧文）
- 本 scratch 清单偏 **策略线索+公式+经验战法**，与之互补

---

## 免责声明

- 公式站宣称的胜率/收益**未经本仓库回测验证**
- URL 可能存在失效、付费墙或地区限制
- 实施任何规则前须用 **PIT 数据、真实成交价、涨跌停、T+1、成本** 在库内回测
