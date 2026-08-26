# 龙回头·筹码锚 + 热度门槛：数据可得性与一手证据核验（2026-08-12）

> **类型**：Explanation（口径尽调 + 数据源核验 + 学术原文核验 + 本仓落点评估）  
> **调研日**：2026-08-12  
> **需求原话**（微信群 + 用户转述，逐条核验）：  
> 「用心理学角度算，同花顺/东方财富等等渠道热度进过前10、20日涨幅进过前十，以下跌前出现的最大量或最高价格那根K线为第一根回归五日线/十日线/二十日线，出现止跌迹象的前一天或者当天作为买卖点。实例：金安国际（前几天）、欣天科技（昨天）。」  
> 筹码口径：「用 100 减 前十大流通股东持股大于5%之和」「按龙回头筹码计算的」「算筹码要每天收盘后才能算」  
> **范围**：只读。核验官方指数编制规则、证监会/交易所披露规则、开源库源码、论文原文，以及本仓 `src/formula` / `src/strategy` / `src/ops` / `src/intel` / `src/market`。**未改任何代码**，未跑回测，未写爬虫，未批量请求，未使用任何凭据。  
> **证据分级**：`V` 本轮实际发请求/执行并记录了真实返回；`E1` 源码或 PDF 全文已读；`E2` 摘要/元数据/检索片段；`E3` 官方或平台文档正文；`E4` 经验主张（不可当收益承诺）。  
> **相关**：[`2026-08-dragon-return-double-pullback-backtest.md`](2026-08-dragon-return-double-pullback-backtest.md)（同一用户上一版公式的回测）、[`2026-08-dragon-return-quant-implementation.md`](2026-08-dragon-return-quant-implementation.md)、[`2026-08-ths-heat-tail-close-picker.md`](2026-08-ths-heat-tail-close-picker.md) 与 [`2026-08-heat-tail-attention-proxy-backtest.md`](2026-08-heat-tail-attention-proxy-backtest.md)（热度源尽调与终态判定，本文不重复）。

---

## 0. 诚实边界（先读这一节）

### 0.1 本机出站链路会伪造「接口挂了」的假象

本轮实测本机 DNS 解析（`socket.gethostbyname`）：`V`

| 主机 | 解析结果 |
|---|---|
| `datacenter-web.eastmoney.com` | `198.18.0.26` |
| `emweb.securities.eastmoney.com` | `198.18.0.27` |
| `data.eastmoney.com` | `198.18.0.28` |
| `www.csindex.com.cn` | `198.18.0.29` |
| `push2.eastmoney.com` | `198.18.0.202` |
| `q.10jqka.com.cn` | `198.18.0.196` |

**全部落在 `198.18.0.0/15`**，即本地隧道客户端的 Fake-IP 段。`src/intel/README.md` 第 36 行已写过这条坑与对策（解析到该段时打开 `trust_env` 走系统代理出站，「否则直连 198.18 必挂」）。

因此**本文所有 HTTP 证据都来自异地只读通道，不是本机直连**。任何「东财/中证接口挂了」的说法都必须先排除这一层。反过来也要记住：**本文验证通的东财接口，在本机上不做 Fake-IP 修正是打不通的**——实现时这是必须先解决的前置条件，不是可选项。

### 0.2 我验证过什么 / 我没验证到什么

| 事项 | 状态 |
|---|---|
| 东财 `RPT_F10_EH_FREEHOLDERS` 全市场十大流通股东接口 | **已验证**：两次单发 GET，无凭据，返回真实分页元数据与逐行字段，见 [A3.3] `V` |
| 该接口是否支持自定义 `columns=` 精简字段 | **已验证**：只请求 7 个字段，返回即只有这 7 个 `V` |
| 该接口是否带公告日（可做 point-in-time） | **已验证**：`NOTICE_DATE` / `UPDATE_DATE` 逐行存在 `V` |
| akshare 1.18.56 股东类函数全表 | **已验证**：本机安装包内省 + 源码逐个读 `E1` |
| akshare `stock_gdfx_free_holding_detail_em` 丢字段 | **已验证**：源码 540–577 行，rename 了 `FREE_HOLDNUM_RATIO` 却没选进输出 `E1` |
| 悟道 MCP `shareholder_structure` 的 inputSchema | **已验证**：本轮取到工具 schema 原文 `E3` |
| 华证《股票指数计算与维护细则》自由流通量定义 | **已验证**：PDF 全文已读并逐条摘录 `E1` |
| 万得《指数计算维护规则》非自由流通股本定义 | **已验证**：PDF 全文已读，原文见 [A1.3] `E1` |
| 中证《沪深300指数编制方案》4.4 条 | **部分验证**：直连 `oss-ch.csindex.com.cn` 那份官方 PDF **两次超时未取到全文**；正文片段来自检索引擎对该官方 PDF 的抽取 `E3`。与华证/万得两份全文互为印证 |
| 证监会《上市公司信息披露管理办法》第十三条 | **已验证**：中国政府网公报版与证监会官网版正文均已读 `E3` |
| 上交所《股票上市规则》季度报告时限 | **已验证**：sse.com.cn PDF 正文 + `one.sse.com.cn` 服务页 `E3` |
| 百度股市通 `day` 参数是否真返回历史 | **未能验证**：两次 GET 均超时，见 [B2.3] |
| 东财人气榜 `getHisList` 的真实返回长度与粒度 | **未能验证**：它是 **POST** 接口，只读通道发不出 POST；只读了 akshare 源码里的 URL 与 payload `E1` |
| 同花顺是否存在逐票热度历史接口 | **未找到**，见 [B2.2]。「未找到」不等于「不存在」 |
| 金安国际 / 欣天科技两个实例 | **未复核**：本文不回测、不个股取数，两个实例只作需求语境，未验证其形态是否符合描述 |

**没有验证到的一律不写字段名，也不写「文档声称」之外的话。**

---

## 结论摘要

| 问题 | 结论 |
|---|---|
| 「筹码 = 100 − 十大流通股东>5%之和」**能不能算** | **能，而且比预想容易**。东财 `RPT_F10_EH_FREEHOLDERS` 一个报告期一次拉全市场：实测 `2025-12-31` 期 **55,603 行 / 112 页**（`pageSize=500`），且 `FREE_HOLDNUM_RATIO`（持股占流通股比）、`HOLDER_RANK`、`HOLDER_TYPE`、`NOTICE_DATE` 齐全 `V` |
| **能不能回测** | **能做全市场 2 年**。约 **10 个报告期 × 112 页 ≈ 1,120 次分页 GET**，一次性拉完落本地即可。**注意：走悟道 MCP 不可行**（单票工具、日配额 5000），**照抄 akshare 封装也不可行**（它把比例列丢了） |
| 与**官方自由流通口径**的差距 | **它不是自由流通比例的近似，是另一个量。** 四处系统性偏差：①剔除范围过宽（官方只剔「创始人/家族/高管、国有、战投、员工持股」四类身份且≥5%，用户剔所有≥5%）；②剔除范围过窄（真正锁仓的**限售股根本不在「流通股东」名单里**）；③分母错位（前者除流通股本，后者除总股本）；④港股通/结算代理人等**通道户**被当成锁仓。实测反例见 [A2] |
| 「热度进过前10」有无**可回测历史源** | **免费路径下没有直接可用的**。唯一免费历史是东财人气榜 `getHisList`，但它 **POST、单票一请求、只给排名不给热度值**，全市场逐日回溯不现实；同花顺逐票热度历史本轮**未找到**。最低成本路径仍是先用东财排名对**候选池**做代理验证，或走 Tushare `ths_hot`（6000 积分） |
| 学术证据对「大量/高点 K 线作锚 + 回踩均线」是**支持还是证伪** | **锚本身有强支持，但用户用错了方向；回踩均线在 A 股被证伪。** Grinblatt-Han (2005) 的参考价**就是换手加权的历史价格**（与本仓 `chips.py` 同一递推），但它预测的是「悬空**为正且大**→未来收益高」；用户买的恰是悬空回落到零附近的时点，**方向相反**。均线侧**证据分裂但共识明确**：三份 A 股 data-snooping 检验里两份判负（Physica A 2015 原文「一旦计入交易成本，交易利润被完全消除」；SPA 版本发现沪深300 上有效性消失、只在 2005–07 泡沫期显著），一份判正（IRF 2017，28,000 信号 stepwise SPA，称计入成本后仍成立）。共识是**原始回测会被 data-snooping 大幅高估，且有效性随市场效率衰减**——均线周期必须自己扫且先划 OOS |
| 规则里**不可实现**的部分 | 「**止跌迹象的前一天**」买入需要预知未来，无法实现；「卖点」用户完全没给；「回归五日/十日/二十日线」三选一未定；「最大量」与「最高价」不同根时取哪根未定；「下跌前」起止未定；两处「进过前十」的池子与回看窗口未定。共 7 处，见 [D] |
| 报告路径 | `docs/research/2026-08-dragon-return-chip-anchor-feasibility.md`（本文） |

**一句话**：筹码那一半的**数据比想象的好拿、口径比想象的错得多**；热度那一半的**数据仍然拿不到历史**；学术那一半告诉你**锚是对的、方向是反的**。

---

## A. 「筹码 = 100 − 前十大流通股东持股>5%之和」

### A1. 官方「自由流通量」到底怎么定义

#### A1.1 中证指数（沪深300 编制方案 4.4 条）

来源：[`000300_Index_Methodology_cn.pdf`](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf)（csindex.com.cn 官方 OSS）。`E3` —— **本轮直连该 PDF 两次超时，正文片段取自检索引擎对该 PDF 的抽取，非我逐字读到的全文**。原文片段：

> 4.4 自由流通量
> 为反映市场中实际流通股份的变动情况，沪深 300 指数剔除了上市公司股本中的限售股份，以及由于战略持股或其他原因导致的基本不流通股份，剩下的股本称为自由流通股本，也即自由流通量。
> （1）公司创建者、家族、高级管理者等长期持有的股份
> （2）国有股份
> （3）战略投资者持有的股份
> （4）员工持股计划
> **上市公司公告明确的限售股份和上述四类股东及其一致行动人持股达到或超过 5% 的股份，被视为非自由流通股本。**
> 自由流通量 = 样本总股本 − 非自由流通股本

#### A1.2 华证指数《股票指数计算与维护细则》（全文已读）

来源：[`《股票指数计算与维护细则（征求意见稿）》`](https://www.chindices.com/attach/%E3%80%8A%E8%82%A1%E7%A5%A8%E6%8C%87%E6%95%B0%E8%AE%A1%E7%AE%97%E4%B8%8E%E7%BB%B4%E6%8A%A4%E7%BB%86%E5%88%99%EF%BC%88%E5%BE%81%E6%B1%82%E6%84%8F%E8%A7%81%E7%A8%BF%EF%BC%89%E3%80%8B.pdf)（chindices.com）。`E1`，全文 878 行已读。附录四原文：

> **1．自由流通量范围**
> 自由流通股本等于样本总股本剔除限售股份以及以下四类基本不流通的股份，具体为：
> - 公司创建者、家族和高级管理人员长期持有的股份⋯⋯
> - 国有股份：由政府或者其分支机构持有的股份；
> - 战略投资者持有的股份⋯⋯
> - 员工持股计划：雇员持股计划所持有的股份。
>
> **2．自由流通量的认定**
> - 在限售期内的限售股份均被认定为非自由流通股份；
> - 非限售股份中，**如果属于上述四类股份，且股东持有股份量达到或超过 5%** 或具有一致行动人关系的股东合计持有股份量达到或超过 5%，认定为非自由流通量，**低于 5% 的，认定为可以自由流通**；
> - 限售股份解禁后，其处理方式与非限售股份的处理方式相同。
>
> **4．自由流通量的调整**
> ⋯⋯对股东行为造成的自由流通量变化**每半年定期调整一次**。

同文 4.4 条给出**分级靠档**：`自由流通比例 = 自由流通量 / 样本总股本`，再按 9 档上靠（≤15% 上调至最接近的整数值，其后 20/30/40/50/60/70/80，>80% 一律 100%）。文中实例：证券 A 总股本 100,000、非自由流通 95,100 → 自由流通比例 4.9% → 加权比例 5%。`E1`

#### A1.3 万得《指数计算维护规则》——**这条最关键**

来源：[`Wind_Index_Calculation_and_Maintenance_Rules.pdf`](https://www.windindices.com/indicesWebsite/api/preview?file=Wind_Index_Calculation_and_Maintenance_Rules.pdf)。`E1`，全文已读。第 311–314 行原文：

> 自由流通股本 = 流通股本 − 非自由流通股本
> 流通股本量：该上市公司所持有的流通股总数。
> 非自由流通股本量：股东或股东及其一致行动人共同持有的股数达到或超过上市公司总股本数的 5%，**且该股东不为基金、投资者计划、专用账户等产品类股东和账户类股东**，视为非自由流通股股本。

**这句「且该股东不为基金、投资者计划、专用账户等产品类股东和账户类股东」正是用户口径缺失的那一半。** 三家规则表述不同但共识一致：**≥5% 只是门槛，身份才是判据**。

### A2. 用户口径与官方口径的四处偏差（含实测反例）

反例数据来自本轮实测的东财 `RPT_F10_EH_FREEHOLDERS`（`END_DATE='2025-12-31'`）第 1 页 500 行（覆盖 50 只股票）。`V`

该页 500 个「十大流通股东」席位中，持股占流通股比 ≥5% 的有 **99 个**，身份分布：`其它 63 / 投资公司 19 / 保险产品 4 / 个人 3 / 私募基金 3 / 保险公司 2 / 证券公司 2 / 证券账户 2 / 其他理财产品 1`。**50 只股票无一例外都至少有一个 ≥5% 的流通股东**。

| # | 偏差 | 后果 | 实测反例 `V` |
|---|---|---|---|
| 1 | **剔除范围过宽**：官方只剔四类身份，用户剔所有 ≥5% | 把真实可交易筹码当成锁仓 | `000039` 香港中央结算(代理人)有限公司 **57.91%**；`000063` 香港中央结算代理人有限公司 **15.73%**；`000035` 香港中央结算有限公司 **5.89%**（陆股通/结算通道**名义持有人户**，背后是成千上万个真实可交易账户）；`000010` 湖南钜银文丰一号私募证券投资基金 **5.72%**；`000031` 太平人寿-普通保险产品-022L-CT001深 **6.01%**；`000048` 中恒通启航1号私募证券投资基金 **5.04%**——按万得规则这些**全部是产品/账户类，不得剔除** |
| 2 | **剔除范围过窄**：真正锁仓的限售股**不在「流通股东」名单里** | 控股股东的限售部分完全漏掉；解禁前后同一家公司的「筹码」会跳变，而跳变原因与股东行为无关 | 官方规则第一句就是「在限售期内的限售股份均被认定为非自由流通股份」（[A1.2]），而十大**流通**股东表按定义只列无限售条件股 |
| 3 | **分母错位** | 数值不可与任何官方「自由流通比例」对照 | 东财 `FREE_HOLDNUM_RATIO` 分母是**流通股本**，同一行另有 `HOLD_RATIO` 分母是总股本——实测 `688121` 第一大流通股东两者分别为 **29.61% / 25.68%**；官方 `自由流通比例 = 自由流通量 / 总股本`。所以「100 − Σ」得到的是「**流通盘中未被前十大占据的部分**」，不是自由流通比例 |
| 4 | **截断在第 10 名** | 第 10 名仍 ≥5% 时会漏 | 逻辑上 10 个席位全部 ≥5% 需要合计 ≥50%，并非罕见——同页 `000031` 仅 ≥5% 的席位就合计 **75.29%** |

**一个能说明问题的算例**（同页实测）：按用户公式，`000031` 的「筹码」= 100 − 75.29 = **24.71**；`000039` = 100 − 63.01 = **36.99**。但 `000039` 那 57.91% 是**结算代理人名义户**，把它算成锁仓等于把整个港股通/B 股通道的真实流动性判成死筹。

**判定**：这个口径**不是自由流通比例的近似，是一个不同的量**。它可以作为一个自造因子存在（自造因子没有原罪），但**不能声称它等于/近似「自由流通比例」，也不能用官方口径的学术文献给它背书**。若要贴近官方口径，用同一份数据里的 `HOLDER_TYPE` 做身份过滤即可（东财已给出 `个人 / 保险公司 / 保险产品 / 私募基金 / 证券公司 / 证券账户 / 投资公司 / 其他理财产品 / 其它` 等分类），成本几乎为零。

### A3. 数据从哪来、多深、多快

#### A3.1 悟道 MCP `shareholder_structure`（本仓已接入的那条）

本轮取到的 inputSchema 原文要点 `E3`：

| 参数 | 类型 | 说明（原文） |
|---|---|---|
| `code` | string | **必填。股票代码或名称。** |
| `startDate` / `endDate` | string | 可选。区间开始/结束日期；默认近三年 |
| `limit` | number | 十大股东/流通股东返回数量，默认 10，最大 30 |
| `sections` | array | `top10/floatHolders/holderNumbers/pledge/dividends/repurchases/all`；不传 = `top10+holderNumbers` |
| `detailLevel` / `embedStock` / `format` | — | 输出档位 |

`additionalProperties: false`，`required: ["code"]`。

**四条硬结论**：

1. **没有 `codes` 数组** —— 参数是单数 `code: string`。悟道 server instructions 也明写「financial_summary、`shareholder_structure`、minute_data 单股数据量大，**不批量**，逐股调即可」。
2. **要拿「十大流通股东」必须显式传 `sections`**，默认只回 `top10`（十大股东，含限售）+ 户数。这两张表**不是一回事**——十大股东里可能全是限售股，`floatHolders` 才是用户口径要的那张。
3. **支持历史**：`startDate`/`endDate` 是区间，默认近三年。但本轮**未实际调用**（会扣真实配额），返回字段名未验证，**不写字段名**。
4. **本仓代码里没有任何地方调用它**：全仓 `rg shareholder_structure` 只命中 `docs/research/2026-08-wudao-mcp-utilization-assessment.md:39`，那句原话就是「研究/助手按票点查即可；**不要**做成日更权威仓」。`V`

**配额算术**：本仓 MCP 日配额默认「总 5000 / structured 3000 / skill 2000」（`src/intel/README.md:38`）。全市场约 5,500 只票 × 1 次 = **5,500 次 > 5,000 日总额**。也就是说 **MCP 路线连跑完一个报告期都不够，更不用说 2 年 × 10 个报告期。**

> **结论：悟道 MCP 只能用来点查候选票、做交叉核对，不能作为回测数据源。** 这与 `src/intel/README.md:47`「大批量量价仍走 market，不走 MCP 扫全市场」是同一条纪律。

#### A3.2 akshare 1.18.56（本机安装包全表核验）

本机内省命中的股东类函数 15 个 `V`，逐个读源码 `E1`（文件：`.venv/Lib/site-packages/akshare/stock_feature/stock_gdfx_em.py`，上游 [`akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py`](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_gdfx_em.py)）：

| 函数 | 入参 | 真实请求 URL / `reportName` | 粒度 | 关键返回列 | 凭据 |
|---|---|---|---|---|---|
| `stock_gdfx_free_top_10_em` | `symbol='sh688686'`, `date='20240930'` | `emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageSDLTGD` | **单票 × 单报告期** | 名次 / 股东名称 / **股东性质** / 股份类型 / 持股数 / **占总流通股本持股比例** / 增减 / 变动比率 | 无 |
| `stock_gdfx_top_10_em` | `symbol`, `date` | `⋯/PageSDGD` | 单票 × 单报告期 | 名次 / 股东名称 / 股份类型 / 持股数 / **占总股本持股比例** / 增减 / 变动比率 | 无 |
| **`stock_gdfx_free_holding_detail_em`** | **`date` 单参** | `datacenter-web.eastmoney.com/api/data/v1/get`，`reportName=RPT_F10_EH_FREEHOLDERS` | **全市场 × 单报告期** | 见下方警告 | 无 |
| `stock_gdfx_holding_detail_em` | `date`, `indicator`, `symbol` | 同上，`RPT_DMSK_HOLDERS` | 全市场，但**必须按股东类型 × 变动方向切片**（`个人/基金/QFII/社保/券商/信托` × `新进/增加/不变/减少`） | 含 `股东排名` | 无 |
| `stock_gdfx_free_holding_analyse_em` | `date` | 同上，`RPT_CUSTOM_F10_EH_FREEHOLDERS_JOIN_FREEHOLDER_SHAREANALYSIS` | 全市场 × 单报告期 | 另附「公告日后涨跌幅-10/30/60 个交易日」 | 无 |
| `stock_gdfx_free_holding_statistics_em` / `_change_em` / `_teamwork_em` 及其 `holding` 对应版 | `date` 或 `symbol` | `RPT_COOPFREEHOLDERS_ANALYSIS` / `RPT_FREEHOLDERS_BASIC_INFO` / `RPT_COOPFREEHOLDER` 等 | **按股东聚合**，不是按股票 | — | 无 |
| `stock_circulate_stock_holder` / `stock_main_stock_holder` | `symbol` | 新浪 `vip.stock.finance.sina.com.cn/corp/go.php/vCI_CirculateStockHolder|vCI_StockHolder/stockid/{code}.phtml` | 单票全历史 | — | 无。**docstring 自述「特定股票特定时间只有前 5 名」** |

> ### ⚠️ akshare 的封装恰好丢掉了这个战法唯一需要的那一列
>
> `stock_gdfx_free_holding_detail_em` 源码第 540–560 行把 `FREE_HOLDNUM_RATIO` 重命名成「期末持股-持股占流通股比」、把 `HOLDER_RANK` 重命名成「股东排名」，**但第 562–577 行的输出列选择里两列都没有**。最终返回只有：
>
> `序号 / 股东名称 / 股东类型 / 股票代码 / 股票简称 / 报告期 / 期末持股-数量 / 期末持股-数量变化 / 期末持股-数量变化比例 / 期末持股-持股变动 / 期末持股-流通市值 / 公告日`
>
> 也就是说，**照抄 akshare 这个函数拿不到「持股占流通股比」，用户的公式直接算不出来**。`E1`
>
> 三条出路：①拿 `期末持股-数量` ÷ 本地流通股本自己算（本仓 `quotes_daily.outstanding_share` 有）；②直接打原始端点自己选列（见下）；③退回单票版 `stock_gdfx_free_top_10_em`（比例列在，但要 5,500 次请求）。

#### A3.3 东财原始端点（**本轮实测，这是可行方案**）

```
GET https://datacenter-web.eastmoney.com/api/data/v1/get
    ?reportName=RPT_F10_EH_FREEHOLDERS
    &columns=SECURITY_CODE,END_DATE,HOLDER_RANK,HOLDER_NAME,HOLDER_TYPE,FREE_HOLDNUM_RATIO,NOTICE_DATE
    &filter=(END_DATE='2025-12-31')
    &sortColumns=SECURITY_CODE,HOLDER_RANK&sortTypes=1,1
    &pageSize=500&pageNumber=1&source=WEB&client=WEB
```

单发一次 GET，**无 cookie、无 token、无 Referer**，返回 `success:true, code:0`。`V`

| 实测项 | 值 |
|---|---|
| `result.count`（`END_DATE='2025-12-31'`） | **55,603** 行 ≈ 5,560 只票 × 10 个席位 |
| `result.pages`（`pageSize=500`） | **112** |
| 本页返回行数 / 覆盖股票数 | 500 / **50** |
| **`columns=` 自定义是否生效** | **生效**——只请求 7 列就只回 7 列，`columns=ALL` 时单行 40+ 字段。传输量差一个数量级 |
| 首行实测 | `{"SECURITY_CODE":"000001","END_DATE":"2025-12-31 00:00:00","HOLDER_RANK":1,"HOLDER_NAME":"中国平安保险(集团)股份有限公司-集团本级-自有资金","HOLDER_TYPE":"保险公司","FREE_HOLDNUM_RATIO":49.565794988742,"NOTICE_DATE":"2026-03-21 00:00:00"}` |

另一次探测（`END_DATE='2026-03-31'`，`columns=ALL`）返回 `count: 55855`，单行含 `FREE_HOLDNUM_RATIO / HOLD_RATIO / HOLDER_RANK / HOLDER_TYPE / SHARES_TYPE / HOLDER_NEWTYPE / HOLDNUM_CHANGE_NAME / IS_SJKZR / LISTED_SHARES_RATIO / UPDATE_DATE / NOTICE_DATE / REPORT_DATE_NAME` 等。`V`

**三个对回测至关重要的字段**：

1. **`NOTICE_DATE` / `UPDATE_DATE`（公告日）** —— 有了它才能做 point-in-time。实测 `2025-12-31` 报告期的公告日是 `2026-03-21`；另一条 `2026-03-31`（一季报）的 `*ST卓然` 公告日晚到 `2026-08-06`。**回测必须按 `NOTICE_DATE <= 决策日` 过滤，而不是按报告期**——按报告期切等于在 1 月 1 日就用上了 3 月才公告的股东表，是标准的前视偏差。
2. **`HOLDER_TYPE`** —— 实测取值含 `个人 / 保险公司 / 保险产品 / 私募基金 / 证券公司 / 证券账户 / 投资公司 / 其他理财产品 / 其它`。这是把用户口径向官方口径收敛的现成钥匙（[A2] 偏差 #1）。
3. **`FREE_HOLDNUM_RATIO`** —— 用户公式的被减数，**正是 akshare 封装丢掉的那一列**。

**合规与礼貌**：该端点是东财数据中心网页的后端 API，无官方文档、无 SLA、无字段承诺。License 只授权代码不授权数据（本仓 `2026-08-market-data-source-intake.md` 已立此规矩）。**自用研究可以，不得再分发**；一次性拉取要限速、不做并发扇出。

### A4. 披露频率与滞后：「每天收盘后算筹码」在数据上成立吗

#### A4.1 官方时限

| 报告 | 时限 | 出处 |
|---|---|---|
| 年度报告 | 会计年度结束之日起 **4 个月**内 | 《上市公司信息披露管理办法》（证监会令第 182 号）**第十三条**，[中国政府网公报版](https://www.gov.cn/gongbao/content/2021/content_5605111.htm)、[证监会官网版](https://www.csrc.gov.cn/csrc/c106256/c1653948/content.shtml) `E3` |
| 中期（半年）报告 | 上半年结束之日起 **2 个月**内 | 同上 |
| **季度报告** | 会计年度**前 3 个月、前 9 个月结束后的 1 个月内**；第一季度报告披露时间不得早于上一年度年报 | **不在证监会令里**——2021 年修订后季报制度下沉到交易所业务规则。见上交所《股票上市规则》**6.1 条**（[sse.com.cn PDF](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785193/files/a58091aef75c46c0a43ce2cd11d1379c.pdf)）与上交所[信息披露服务页](https://one.sse.com.cn/onething/xxpl/) `E3` |

> 一个容易抄错的细节：很多二手材料把「季报 1 个月内」写成证监会规章。**2021 年 5 月 1 日起施行的第 182 号令第十二条只保留「年度报告、中期报告」两种定期报告**，同时废止了《公开发行证券的公司信息披露编报规则第 13 号——季度报告的内容与格式》；证监会同期新闻稿原文是「下一步，证监会将指导沪深证券交易所在业务规则层面做好季度报告制度安排」。`E3`

#### A4.2 直接回答

**不成立——至少「筹码」这一半不成立。**

- 十大流通股东是**季报字段**，一年只变 4 次，且变更生效时点是**公告日**（实测 `2025-12-31` 期 → `2026-03-21` 公告）。在两次公告之间，用户公式的分子分母**逐字不变**。
- 所以「100 − Σ」在时间轴上是一条**阶梯常量**：一年 4 级台阶，每级台阶上连续 60 个交易日数值完全相同。「每天收盘后重算」得到的是同一个数。
- **真正需要每天收盘后重算的是价格/成交量那一半**——也就是通达信意义上的**筹码分布**（`COST` / `WINNER`），它靠逐日换手衰减递推，确实每天都变。见 [C3] 与 [E1]。

> **这很可能是一次术语撞车。** 微信群里的「筹码」在 A 股散户语境下通常指通达信筹码峰（换手衰减模型）；而「100 − 十大流通股东>5%之和」是个**股东结构**指标。前者日频、后者季频，两者只是名字相同。**动手前必须先跟需求方确认到底要哪一个**——这两条路的数据源、更新频率、实现难度、学术依据全都不一样。

### A5. 回测可行性判定

目标：全市场、2 年、逐日可用的「筹码」列。

| 路线 | 请求量 | 判定 |
|---|---|---|
| **东财 `RPT_F10_EH_FREEHOLDERS` 原始端点** | 覆盖 2024-08~2026-08 需要 2024Q1 起共约 **9–10 个报告期**（含一个前置期，因为公告滞后 1 个月）× 112 页 ≈ **1,120 次分页 GET**，一次性。约 55.6 万行 × 7 列，落 SQLite 只有几 MB | **可行**。礼貌限速 1 req/s 约 19 分钟跑完；此后每季度增量 112 次 |
| akshare `stock_gdfx_free_holding_detail_em` | 同上量级，但**拿不到比例列**（[A3.2] 警告） | **不可用**（除非自己补算比例） |
| akshare `stock_gdfx_free_top_10_em`（单票版） | 5,500 票 × 10 期 = **55,000 次** | **不可行** |
| 悟道 MCP `shareholder_structure` | 5,500 票/期，**> 日配额 5,000** | **不可行**。只能点查候选池 |
| 新浪 `stock_circulate_stock_holder` | 单票全历史，但**只有前 5 名** | **不可用**（口径就是「前十大」） |

**判定：全市场 2 年回测可行，唯一现实路径是东财原始端点 + 自己选列 + 按 `NOTICE_DATE` 做 point-in-time。**

三条必须一起立的闸门：

1. **按公告日而非报告期切片**，否则前视（[A3.3]）。
2. **新股与退市票的缺口要显式回执**（热榜/新股 join 不上是常态，见 `2026-08-ths-heat-tail-close-picker.md` [C3] 同一坑）；不许静默丢票。
3. **落库位置**：按 `src/AGENTS.md` 的「是否入库」清单，这是**可重建缓存**（丢了能重新拉），归 `market.db`，可整表删除重建；**不进 `palace.db`**。目前 `market.db` 没有任何股东表（`store_schema.py` 现有表：`meta / instruments / quotes_daily / adjust_factors / trading_calendar / ingest_watermark / source_route_receipts / source_route_attempts / intel_snapshots`）`V`，新增需要一张新表 + README/ADR。

---

## B. 热度「进过前10」的数据可得性

### B1. 先读这两篇，本文不重复

- [`2026-08-ths-heat-tail-close-picker.md`](2026-08-ths-heat-tail-close-picker.md)：同花顺热度接口实测可用但**无历史**；akshare 1.18.56 **无任何同花顺热度函数**（`stock_hot_rank_wc` 已被上游静默移除）；Tushare `ths_hot` 是唯一带 `trade_date` 的官方文档化历史源，需 6000 积分。
- [`2026-08-heat-tail-attention-proxy-backtest.md`](2026-08-heat-tail-attention-proxy-backtest.md)：**终态判定**。用注意力代理做的两轮回测，交叉搜索 top20 组合**无一前后两段都为正**，负期望。

本仓 `intel_snapshots` 从加 `platform="ths"` 那天起才开始攒同花顺口径热度（`src/intel/README.md:42`「热度双口径」），积累时长远不够回测。

### B2. 本轮补的核验

#### B2.1 东财 `stock_hot_rank_detail_em` 的 `getHisList`：读源码的确切结论

akshare 源码原文 `E1`（`.venv/Lib/site-packages/akshare/stock/stock_hot_rank_em.py`）：

```python
url_rank = "https://emappdata.eastmoney.com/stockrank/getHisList"
payload = {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38",
           "marketType": "", "srcSecurityCode": symbol, "yearType": "5"}
r = requests.post(url_rank, json=payload)
...
temp_df.columns = ["时间", "排名", "证券代码"]
```

外加第二个 POST `⋯/stockrank/getHisProfileList` 取 `newUidRate` / `oldUidRate` → 「新晋粉丝」/「铁杆粉丝」。

**四条硬事实**：

1. **是 POST，不是 GET。** 我的只读通道发不出 POST，因此**返回长度与时间粒度本轮未能验证**。`yearType: "5"` 从字面看是 5 年，但这是 akshare 作者写死的入参，**不是接口文档**——不能据此断言「有 5 年历史」。
2. **只按 `srcSecurityCode` 单票查，没有按日期批量的入口。** payload 里没有任何 date 字段。要拿「某一天全市场排名」只能 5,500 票各发一次。
3. **只有「排名」，没有热度值。** 返回列就三列（时间/排名/证券代码）。「进过前10」这种**序数**条件它能答，「热度值多高」答不了。
4. akshare 里其余 `*hot*` 函数签名本轮已全表核验 `V`：`stock_hot_rank_em()` / `stock_hot_up_em()` 无参（当前快照）；`stock_hot_rank_latest_em(symbol)` / `stock_hot_rank_relate_em(symbol)` / `stock_hot_keyword_em(symbol)` / `stock_hot_rank_detail_realtime_em(symbol)` 单票；`stock_hot_follow_xq / _tweet_xq / _deal_xq(symbol='最热门')` 雪球当前榜。**只有 `stock_hot_search_baidu` 带 `date` 参数。**

#### B2.2 同花顺是否有逐票热度历史：未找到

本轮在 akshare 1.18.56 全表内省中**没有任何同花顺热度函数**（与前篇结论一致）；`dq.10jqka.com.cn/fuyao/*` 那两个端点前篇实测只返回当前快照，参数空间里没有日期维度。**结论：未找到同花顺侧的逐票历史接口。**「未找到」不等于「不存在」——同花顺 App 里有个股热度历史曲线，说明后端一定存在某个接口，只是本轮没有一手证据，**不猜 URL、不写字段名**。

#### B2.3 百度股市通：唯一带 `date` 的线索，但未能验证

akshare `stock_hot_search_baidu(symbol='A股', date='20250616', time='今日')` 源码 `E1`：

```python
url = "https://finance.pae.baidu.com/selfselect/listsugrecomm"
params = {..., "market": symbol_map[symbol], "type": time,
          "day": date, "hour": hour_str, "pn": "0", "rn": "12", ...}
```

- `day` / `hour` 是**真实 URL 参数**，`rn: "12"` 是 akshare 写死的行数（不是服务端上限，`rn` 本身是分页参数）。
- 返回列：`名称/代码`、`涨跌幅`、`综合热度`——**有热度值**。
- **本轮两次 GET（`day=20260731` 与 `day=20260812`，`rn=20`）均超时，未能验证 `day` 是否真返回历史。** 不排除服务端忽略该参数只回当前榜。

> 这是本轮唯一新增的、值得再花一次探测成本的线索：如果 `day` 真的生效，那它就是**免费、带日期、带热度值**的历史注意力源。但即便生效，它是**百度搜索热度**，不是同花顺 App 热度——换源即换策略（前篇 [A7] 已论证）。

#### B2.4 其它平台

| 源 | 是否有带 `trade_date` 的历史 | 证据 |
|---|---|---|
| Tushare `ths_hot` | **有**，官方文档化，出参含 `trade_date` / `rank` / `hot` / `rank_time` | [Tushare doc_id=320](https://tushare.pro/document/2?doc_id=320) `E3`（前篇已读全文）。需 6000 积分 |
| 东财人气榜 | 逐票有排名史，无热度值，POST 单票 | [B2.1] |
| 雪球 / 淘股吧 / 开盘啦 | 本轮**未找到**带历史的公开入口；悟道 `smart_hotlist` 是当前快照 | 前篇 [A7] |
| 聚宽 / 米筐 | **未验证**：需注册账号，本轮不注册、不使用凭据 | — |

### B3. 若要回测「热度曾进过前10」，最低成本路径

按成本从低到高，每一步都能独立停下：

1. **先不取数，先看结论。** [`2026-08-heat-tail-attention-proxy-backtest.md`](2026-08-heat-tail-attention-proxy-backtest.md) 已经用注意力代理把这件事跑到了终态：**负期望，ADR-011 不进第 2 步**。在拿出新证据推翻它之前，为「热度进过前10」再投一轮取数成本是不划算的。
2. **若仍要做，用东财排名对「候选池」做代理。** 龙回头的候选池本来就只有几十到几百只（先过「20 日涨幅前十」和形态闸），逐票 POST `getHisList` 一次拿全历史排名是可承受的；全市场逐日不可行。
3. **同时从今天起自采。** 本仓 `intel_fetch` 已在跑 `smart_hotlist` 双口径（`src/intel/README.md:42`），落 `market.db.intel_snapshots`，可整表重建。这是零边际成本的历史积累。
4. **最后才考虑 Tushare 6000 积分。** 只有前三步都指向「热度确有增量」时，这笔钱才有依据。

---

## C. 心理学 / 学术一手依据

### C1. 锚定效应与 52 周高点

**George & Hwang (2004), "The 52-Week High and Momentum Investing", *JF* 59(5):2145-2176.**
[作者主页 PDF](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf)（全文已读 `E1`）、DOI [10.1111/j.1540-6261.2004.00695.x](https://doi.org/10.1111/j.1540-6261.2004.00695.x)

摘要原文：

> When coupled with a stock's current price, a readily available piece of information—the 52-week high price–explains a large portion of the profits from momentum investing. **Nearness to the 52-week high dominates and improves upon the forecasting power of past returns** (both individual and industry returns) for future returns. **Future returns forecast using the 52-week high do not reverse in the long run.**

正文原文：「**price levels are more important determinants of momentum effects than are past price changes**」。

| 项 | 内容 |
|---|---|
| **结论方向** | **支持「用价格水平相对某个历史锚的位置」作为预测变量**，且优于用固定窗口涨幅 |
| **时间尺度** | 组合形成期 6 个月、持有期 6 个月（月频）；长期**不反转** |
| **对本战法的含义** | 支持「以某根历史 K 线的价格作锚」这个**建模范式**。但它的信号方向是「**越接近高点越好**」，而用户买的是「**从高点回落之后**」——[C6] 详述 |

### C2. 处置效应 / 资本利得悬空

#### C2.1 Grinblatt & Han (2005) —— 本节最重要的一篇

**"Prospect theory, mental accounting, and momentum", *JFE* 78(2):311-339.**
[Rotman 全文 PDF](https://www-2.rotman.utoronto.ca/facbios/file/momentum_JFE.pdf)（全文已读 `E1`）、DOI [10.1016/j.jfineco.2004.10.006](https://doi.org/10.1016/j.jfineco.2004.10.006)

摘要原文：

> A variable proxying for aggregate unrealized capital gains appears to be the key variable that generates the profitability of a momentum strategy. **Past returns have no predictability for the cross-section of returns once this variable is controlled for.**

模型核心，参考价更新（Eq. 5）：

> R<sub>t+1</sub> = V<sub>t</sub>P<sub>t</sub> + (1 − V<sub>t</sub>)R<sub>t</sub>
> 「We believe that the updating weight, **V<sub>t</sub>, should be related to the stock's turnover ratio**」

迭代展开后的实证参考价（Eq. 9）：

> R<sub>t</sub> = Σ<sub>n</sub> [ V<sub>t−n</sub> · Π<sub>τ=1..n−1</sub>(1 − V<sub>t−n+τ</sub>) ] · P<sub>t−n</sub>
> 「where V<sub>t</sub> is date t's turnover ratio in the stock. **The weight on P<sub>t−n</sub> is the probability that a share was last purchased at date t−n and has not been traded since then.**」

预测式（Eq. 8）：

> E<sub>t</sub>[(P<sub>t+1</sub> − P<sub>t</sub>)/P<sub>t</sub>] = (1 − w)·V<sub>t</sub>·(P<sub>t</sub> − R<sub>t</sub>)/P<sub>t</sub>
> 「a stock's expected return is **monotonically increasing in the marginal investor's (percentage) unrealized capital gain**」

正文另一句直指用户的「最大量 K 线」直觉：

> 「It is the pattern of past returns, **combined with the pattern of past trading volume**, that determines whether the stock has experienced an aggregate unrealized capital gain or loss.」

| 项 | 内容 |
|---|---|
| **结论方向** | **支持「成交量加权的历史价格」作为心理参考价**，且它比过去收益率更有解释力 |
| **时间尺度** | 周频数据（1962-07~1996-12，1,799 周），预测下一周；Fama-MacBeth 横截面 |
| **对本战法的含义** | 这是「把大成交量那根 K 线的价格当锚」**最直接的一手学术依据**——但学术版本是**整段历史的换手加权平均**，不是**单独一根**。单根是这个加权平均的极端退化情形（假设那一天换手率≈100%、其余天≈0）。**方向问题见 [C6]** |

#### C2.2 Frazzini (2006)

**"The Disposition Effect and Underreaction to News", *JF* 61(4):2017-2046.**
[作者主页 PDF](https://pages.stern.nyu.edu/~afrazzin/pdf/The%20Disposition%20Effect%20and%20Underreaction%20to%20news%20-%20Frazzini.pdf)（全文已读 `E1`）、DOI [10.1111/j.1540-6261.2006.00896.x](https://doi.org/10.1111/j.1540-6261.2006.00896.x)

摘要原文：

> I use data on mutual fund holdings to construct a **new measure of reference purchasing prices** for individual stocks, and I show that **post-announcement price drift is most severe whenever capital gains and the news event have the same sign**. ⋯ An event-driven strategy based on this effect yields **monthly alphas of over 200 basis points**.

正文假设 UR 原文：「When most of the current holders are facing a **capital gain**, stock prices underreact to **positive** news and in turn generate a **positive** post-announcement price drift.」

| 项 | 内容 |
|---|---|
| **结论方向** | **条件成立**：漂移只在「悬空符号 = 消息符号」时出现。**这是一个交互项，不是主效应** |
| **时间尺度** | 事件后数周至数月（月度 alpha 口径） |
| **对本战法的含义** | 「筹码/悬空」要产生收益必须**配一个同号的催化事件**。用户的规则里没有任何消息/事件维度——按 Frazzini，缺了这一半，漂移预期本身就打折 |

### C3. 成交量作为锚：本仓已经实现了学术版本

**这是本节最有工程价值的发现。**

`src/formula/domain/chips.py` 第 9–15 行（模块 docstring 原文）：

> 真正的筹码分布是**逐日递推的换手衰减模型**：
>
> ```
> chips(t) = chips(t-1) × (1 − 换手率) + 换手率 × 今日成交价格分布
> ```
>
> 含义是「每天有换手率那么大比例的筹码换了手，新持有者的成本落在今日价格区间内」。历史成本因此被逐日稀释而不是被窗口一刀切掉。

把它与 Grinblatt-Han Eq. (5) `R_{t+1} = V_t·P_t + (1−V_t)·R_t` 并排看：**同一条递推**。通达信筹码分布是 Grinblatt-Han 参考价的**分布版**（保留整条成本分布而不只是均值），`COST(p)` 是它的分位数，`WINNER(p)` 是它的累积分布。

也就是说：

- 「用最大量那根 K 线的价格当锚」这件事，本仓**已经有一个理论更干净、实现更完整、且每天真的会变**的替代品：`COST` / `WINNER`。
- 它也正好回答了 [A4.2] 的术语撞车问题——**微信群里说的「每天收盘后才能算的筹码」，在本仓里已经存在，就是 `chips.py`**，跟十大流通股东毫无关系。

**但有两条硬约束**（`src/formula/README.md:25`，原文）：

> `COST/WINNER` 已实现为 Python 公式 API，但**暂不进入 Screen Formula 目录**；它们依赖跨全历史的筹码递推，短窗口求值会产生伪精确结果。

以及 `README.md:28`：遇到可观察的行情/换手缺失会从该日后返回空值，「不用旧状态冒充准确成本」。本仓 `volume` 存在「手 vs 股」历史单位分歧、有整个 `turnover_repair` 模块在修（见 double-pullback 回测第 27 行），**换手率质量直接决定筹码质量**。

**未找到的东西（如实写）**：把「**单独一根**最大成交量 K 线的价格」当参考价的一手学术研究，本轮**未找到**。找到的都是「整段历史换手加权」（Grinblatt-Han）或「52 周最高价」（George-Hwang）这类**整段/极值**锚。相关但不等价的一条：Huddart, Lang & Yetman 关于 52 周高低点附近成交量异常放大的研究，本轮**只见到题录、未读原文**，故不引述其结论。

### C4. 均线回归 / 支撑位：反驳链完整，A 股结论偏负

| 论文 | 入口 | 结论方向 | 时间尺度 |
|---|---|---|---|
| **Brock, Lakonishok & LeBaron (1992)**, "Simple Technical Trading Rules and the Stochastic Properties of Stock Returns", *JF* 47(5):1731-1764 | RePEc 条目见下方 STW 引文 `E2`（本轮**未读全文**，只经 STW 转述） | **支持**：DJIA 1897–1986，26 条规则（含简单均线、固定均线、区间突破）「provide superior performance」 | 日频，90 年样本 |
| **Sullivan, Timmermann & White (1999)**, "Data-Snooping, Technical Trading Rule Performance, and the Bootstrap", *JF* 54(5):1647-1691 | [PDF 全文](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf)、[LSE FMG dp303 全文](https://researchonline.lse.ac.uk/id/eprint/119144/1/dp303.pdf)（均已读 `E1`）、DOI [10.1111/0022-1082.00163](https://doi.org/10.1111/0022-1082.00163) | **一半支持、一半证伪**：用 White's Reality Check 把规则宇宙扩到 7,846 条后，**BLL 样本期内最优规则仍然显著**；但**「does not provide superior performance when used to trade in the subsequent 10-year post-sample period」**。作者原话：「it is possible that, historically, the best technical trading rule did indeed produce superior performance, but that, more recently, the markets have become more efficient and hence such opportunities have **disappeared**」 | 样本内 1897–1986 有效；1987–1996 OOS 失效 |
| Bajgrowicz & Scaillet (2012), *JFE* 106(3):473-491 | 经 STW 后续文献转述 `E2`（本轮**未读原文**） | **证伪**：同一 7,846 条规则宇宙，控制 FDR 后 1986 年后不再跑赢 | 日频 |

**A 股复现（两条独立、结论相反，必须一起看）**：

| 研究 | 入口 | 结论 |
|---|---|---|
| Zhu, Zhou, Xiong et al., "Profitability of simple technical trading rules of Chinese stock exchange indexes", *Physica A* (2015) | DOI [10.1016/j.physa.2015.07.032](https://doi.org/10.1016/j.physa.2015.07.032)、[arXiv 1504.04254](https://doi.org/10.48550/arxiv.1504.04254) `E3`（摘要与方法段已读） | **证伪**。上证 1992-05~2013-12、深证 1991-04~2013-12，MA 与 TRB 规则 + White's Reality Check：「the best trading rule outperforms the buy-and-hold strategy **when transaction costs are not taken into consideration**. **Once transaction costs are included, trading profits will be eliminated completely.**」结论句：「simple trading rules like MA and TRB **cannot beat** the standard buy-and-hold strategy for the Chinese stock exchange indexes」 |
| "Testing the performance of technical trading rules in the Chinese markets based on superior predictive test", *Physica A* (2015) | [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0378437115006391) `E3`（摘要已读） | **条件成立**。7,000+ 条规则 + SPA 检验：上证综指（1992–2013）显著，**沪深 300（2005–2013）这一能力消失**；把上证截成同期子样本后有效性「severely weakened」；2005–2007 泡沫期最强。作者归因：「the predictive ability of technical trading rules **appears when the market is less efficient**」 |
| Pätäri et al., "Technical Analysis Profitability Without Data Snooping Bias: Evidence from Chinese Stock Market", *International Review of Finance* (2017) | DOI [10.1111/irfi.12161](https://doi.org/10.1111/irfi.12161) `E3`（摘要已读） | **支持**。28,000+ 信号 + stepwise SPA，19 年中国市场日频数据：「substantial evidence on the profitability of technical trading rules ⋯ **remain valid under the presence of transaction costs**」 |

**如何读这三条互相打架的结果**：它们的标的（综指 vs 沪深300）、口径（择时 vs Sharpe gain）、样本期都不同。共识只有两条：**①原始回测数字会被 data-snooping 大幅高估；②有效性高度依赖市场效率阶段，越有效的市场越没得赚。** 对本战法的含义是——**「回踩 MA10 支撑」这个条件必须在本仓自己的数据上跑参数扫描，且必须先划 OOS**，任何外部数字都不能借用。

本仓 [`2026-08-dragon-return-quant-implementation.md`](2026-08-dragon-return-quant-implementation.md) 第 229–235 行已经独立得出同一结论：市面上对「回踩哪条均线」的说法（5/8/10/15/20/30/60 日各有主张）**互相冲突且无一给出样本量**，原文判定「**均线周期选择目前无可靠外部依据，属于必须自己扫描的参数**」。

### C5. A 股散户处置效应实证

| 研究 | 入口 | 结论 | 尺度 |
|---|---|---|---|
| **Chen, Kim, Nofsinger & Rui (2007)**, "Trading performance, disposition effect, overconfidence, representativeness bias, and experience of emerging market investors", *JBDM* 20(4):425-451 | DOI [10.1002/bdm.561](https://doi.org/10.1002/bdm.561)、[SSRN 957504](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=957504) `E2`（摘要已读，未读全文） | **支持**：中国券商账户数据，「they tend to sell stocks that have appreciated in price, but not those that have depreciated」；且「their disposition effect appears **stronger**」than U.S. investors | 账户层面行为 |
| **Feng & Seasholes (2005)**, "Do Investor Sophistication and Trading Experience Eliminate Behavioral Biases in Financial Markets?", *Review of Finance* 9(3):305-351 | DOI [10.1007/s10679-005-2262-0](https://doi.org/10.1007/s10679-005-2262-0)、[SSRN 694769](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=694769) `E2` | **条件成立**：中国账户数据，「Sophisticated investors are **67% less prone** to the disposition effect」；老练+经验可消除「不愿止损」，但只把「急于止盈」削弱 37%，**未消除** | 账户生命周期 |
| 《一项关于中国个人投资者处置效应的研究：非理性信念视角》，《金融研究》 | [期刊页](http://www.jryj.org.cn/EN/abstract/abstract713.shtml) `E2` | **支持**：177 万个人投资者、2007–2009 交易级数据，「the likelihood of a sale for Chinese stock investors is **20% higher when a gain is realized** than when a loss is realized」；且**市场情绪越高、处置效应越弱** | 月度面板 |

**对本战法的含义**：处置效应在 A 股散户里**确实存在且比美股更强**——这为「筹码/成本悬空是有效状态变量」提供了**机制层面**的本土支持。但注意最后一条：处置效应强度**随市场情绪变化**，意味着基于它的信号天然是**状态依赖**的，不是常数效应。这与 [C4] A 股均线研究「泡沫期最强」是同一个现象。

### C6. 方向冲突：本文最需要用户回答的一条

把 [C1]/[C2] 的结论摆在一起：

- George-Hwang：**越接近 52 周高点，未来收益越高**。
- Grinblatt-Han Eq. (8)：**期望收益随「未实现资本利得」(P<sub>t</sub> − R<sub>t</sub>)/P<sub>t</sub> 单调递增**。
- Frazzini：**悬空为正时，正面消息带来正向漂移**。

三篇的方向一致：**「价格远高于成本锚」是高预期收益状态**。

而用户的规则是：

> 「以下跌前出现的最大量或最高价格那根 K 线为⋯⋯**回归**五日线/十日线/二十日线⋯⋯」

**买入时点恰好是价格从锚上方回落、悬空收窄到接近零的时候**——按 Grinblatt-Han，那正是 (P<sub>t</sub> − R<sub>t</sub>) 变小、期望收益变低的状态。

**必须说清楚的三点**：

1. **这不等于战法错。** 上述三篇都是**月频/周频横截面**结论，用户的战法是**日频事件择时**，尺度差一个量级。横截面月频的单调关系不保证日频事件窗口内同号——这是尺度错配，不是逻辑矛盾。
2. **但它意味着不能拿这三篇给战法背书。** 引用 Grinblatt-Han 支持「以大量 K 线为锚」是对的；引用它支持「回踩到锚附近买入」是**把结论用反了**。
3. **它给出了一个廉价且必须做的对照实验**：同一套信号，把「回踩到锚」和「站在锚上方」两个方向都跑一遍。如果学术方向对，后者应该更好。这正是 `2026-08-ths-heat-tail-close-picker.md` [C6] 第 7 条立下的规矩——「回测**必须同时跑正反两个方向**，否则等于只找支持性证据」。

### C7. 反面证据（单列）

1. **技术形态在 data-snooping 检验下的存活率极低。** STW (1999) 把规则宇宙从 26 条扩到 7,846 条后，样本内最优规则仍显著，但**后续 10 年 OOS 完全失效**；Bajgrowicz & Scaillet (2012) 控制 FDR 后 1986 年之后不再跑赢。`E1`/`E2`
2. **A 股「回踩均线买入」计入成本后收益归零。** Physica A (2015) 的 WRC 检验原文：「Once transaction costs are included, trading profits will be **eliminated completely**」。`E3`
3. **有效性集中在市场无效期。** SPA 版本发现沪深 300 上完全失效、上证有效性主要来自 2005–2007 泡沫期。`E3`
4. **本仓自己的负面证据。** [`2026-08-dragon-return-double-pullback-backtest.md`](2026-08-dragon-return-double-pullback-backtest.md)：同一用户上一版公式在 2.5 年只有 281 次信号、中位净 **−0.403%**（多数交易亏钱）、正期望完全靠不设止损换来、逐笔串联回撤 −96%，且存活偏差方向乐观。[`2026-08-heat-tail-attention-proxy-backtest.md`](2026-08-heat-tail-attention-proxy-backtest.md)：热度维度已被判负期望。
5. **龙池退役先例。** `src/ops/README.md:89-92`：同类「曾大涨 + 回撤到位」战法（龙池）在 300 个交易日 / 199 笔样本上，配对超额 T+3 仅 **+0.53%（t=1.00，95% 区间跨 0）**，最赚的 3 笔贡献 38% 盈利，已整体退役。README 原话：「**想重做这类「曾大涨 + 回撤到位」的战法，请先复现这份对照再动手，别直接把参数抄回来。**」

---

## D. 规则本身的可编程性审查

以下 7 处必须由需求方定夺，本文只列选项、不替用户决定。

### D1. 「热度进过前10」

| 待定 | 候选 |
|---|---|
| 平台 | (a) 同花顺（无历史，[B1]）；(b) 东财人气榜（有排名史，无热度值，单票 POST）；(c) 悟道 `smart_hotlist` 综合榜；(d) 百度搜索热度（`day` 参数未验证）。**注意换源即换策略**：不同平台是不同人群的不同行为 |
| 名次门槛 | 前 10 / 前 20 / 前 50。用户原话同时出现「前10」与「前10、20」，需定死 |
| 「进过」的回看窗口 | 近 5 / 10 / 20 个交易日内曾出现过 |
| 榜的时点 | 同花顺是 hour 榜（盘中滚动）。用收盘那一档还是全天任意一档「进过」？盘中滚动榜取哪一刻**必须固定**，否则同一天不同时刻算出不同答案 |

### D2. 「20 日涨幅进过前十」

| 待定 | 候选 |
|---|---|
| 池子 | (a) 全市场前 10（5,500 只里的前 10，极稀疏——约 0.18%）；(b) 热度榜内前 10；(c) 同题材内前 10；(d) 某个市值/板块子集内前 10 |
| 回看窗口 | 「进过」指近 N 日内曾进过前十，N 待定 |
| 涨幅口径 | 必须用**前复权**价。不复权时一次除权就能伪造出反向假信号（double-pullback 回测第 33 行已踩过） |
| 是否用排名 | 「前十」是**排名**条件，需要每日全市场排序；等价的阈值条件（如「20 日涨幅 ≥ X%」）实现成本低一个量级，且不受当日市场整体强弱影响。**两者不等价，需明确选哪个** |

> 参考量级：double-pullback 回测里「近 20 日翻倍」这一条在 311 万个「日 × 票」格子里只命中 **5,247 个（0.17%）**，并把全部条件的最终命中压到 281 个。「全市场 20 日涨幅前十」的稀疏度与之同量级——**这一条会单独决定整个战法的信号密度**。

### D3. 「下跌前出现的最大量或最高价格那根 K 线」

| 待定 | 候选 |
|---|---|
| 最大量与最高价**不同根**时取哪根 | (a) 取最大量那根；(b) 取最高价那根；(c) 两根都算、取更近的；(d) 取更远的（更保守的锚）；(e) 要求两者同根，否则不出信号（最严，样本最少） |
| 「下跌前」的**终点** | (a) 从当日往回数；(b) 从「首阴」那根往回数；(c) 从阶段高点往回数 |
| 「下跌前」的**起点/回看根数** | 必须是**常量或受限 int 参数**——本仓公式编译器拒绝变量窗口（`E_WINDOW_DYNAMIC`，`screen_formula_compiler._window_range`）。候选 20 / 30 / 60 根 |
| 「最大量」的量口径 | `VOL`（成交量，本仓有「手 vs 股」历史单位分歧）还是 `AMOUNT`（成交额，无单位歧义）还是 `HSL`（换手率，可跨股比较）。**推荐 `AMOUNT` 或 `HSL`** |
| 锚**价**取该根的哪个价 | 收盘价 / 最高价 / 均价（`AMOUNT/VOL`）/ 中位价。学术侧（Grinblatt-Han Eq. 9）用的是该期**成交价**，最接近「均价」 |

本仓现成函数：`HHVBARS(HIGH, N)` 取「最近 N 根内最高值距今根数」、`LLVBARS`、`BARSLAST`、`BARSSINCE`、`REF` 均在 Screen Formula 目录内（`src/formula/domain/screen_formula_catalog.py:12-14, 49-50`）。**「最大量那根」没有现成函数**——需要用 `HHVBARS(AMOUNT, N)` 拿根数，再 `REF(CLOSE, HHVBARS(AMOUNT,N))` 取价，但 **`REF` 的偏移量必须是常量**，动态偏移会撞 `E_WINDOW_DYNAMIC`。可行的等价写法是枚举 `n = 1..N` 再合并（double-pullback 回测第 28 行已用过同一手法，且论证了与通达信动态周期语义**完全等价**，不是近似）。

### D4. 「第一根回归五日线/十日线/二十日线」

| 待定 | 候选 |
|---|---|
| 三条均线**取哪条** | 用户写「五日线/十日线/二十日线」，含义可能是 (a) 三选一（哪条？）；(b) 任一条触发；(c) 三条同时满足；(d) 按市场阶段切换（拾荒网的主张，本仓 quant-implementation 第 570 行已记录且判为「无可靠外部依据」） |
| 「回归」= 什么 | (a) 最低价触及（`LOW <= MA`）；(b) 收盘跌破（`CLOSE < MA`）；(c) 收在其上但下影穿透（`CLOSE > MA AND LOW < MA*1.02`，通达信社区常见写法，容差 2% 无依据）；(d) 收盘价距均线 ≤ x% |
| 「第一根」从哪儿数 | 从锚 K 线之后第 1 根满足条件的？还是本轮下跌以来第 1 根？两者在「锚之后曾反弹再跌」的路径上不同 |
| 均线用什么价 | `MA(CLOSE, N)` 还是 `MA(AMOUNT/VOL, N)`。默认 `CLOSE` |

**一条硬约束**：若 `entry_timing="close"`（尾盘买），**当日 `HIGH`/`LOW` 不可用**（见 [E2]）。所以「最低价触及均线」这个定义在尾盘档**编译不过**，只能用 `next_open` / `next_dip`，或改成只用 `CLOSE` 的定义。这不是实现偷懒，是防前视。

### D5. 「出现止跌迹象的**前一天**」—— 数据上不可实现

**买在「止跌信号出现的前一天」需要在 T 日就知道 T+1 日会不会出止跌信号。这是标准的前视偏差，无法实现。**

本仓有两道闸会直接拦住它：

- Screen Formula 编译期：`_audit_entry_timing` 抛 `E_ENTRY_TIMING_LOOKAHEAD`（`src/formula/domain/screen_formula_compiler.py:389-408`）。
- Python 策略：`audit_source` 抓负向 `shift(-n)` 报 warn，`audit_truncation` 截断重跑不一致直接 `block`（`src/strategy/application/audit.py:163-184, 276-367`）。后者是行为证据，绕不过去。

**可实现的替代（三选一，需求方定）**：

| 替代 | `entry_timing` | 说明 |
|---|---|---|
| **止跌信号当天收盘买** | `close` | 信号用当日 `OPEN/CLOSE/VOL/AMOUNT/HSL`（不含 `HIGH`/`LOW`）。这是最贴近原意的一档 |
| **次日开盘买** | `next_open` | 信号可用当日全部 OHLC。**double-pullback 回测里唯一前后两段都为正的口径就是这一档**（次开买·持 5 日，均净 +0.886%） |
| **次日盘中挂预埋价** | `next_dip` | 信号日收盘后按 `dip_pct` 生成次日预挂价，成交由回测引擎统一判断（`src/formula/README.md:31`） |

> **强烈建议先做 `next_open`。** 同一族公式的既有回测（double-pullback）已经给出明确证据：**尾盘买的九个口径全部为负**，且尾盘那档还是「假设 14:50 已知全天高低收」的**乐观口径**；换成次日开盘买才转正。原因是 A 股高波动票的隔夜跳空单向伤人。

### D6. 「买卖点」—— 卖点规则完全缺失

用户原话只给了买点。**卖点一个字都没有**，而卖点决定收益分布的一半以上。

double-pullback 回测在这一点上已有可直接复用的实测结论：

| 发现 | 数字 |
|---|---|
| 有效持有窗口是 **3–5 个交易日** | 持 5 日 +0.886%，持 10 日 **−0.647%** |
| **加止损反而更差** | 无障碍持 5 日 +0.886%，加 −5%/+10% 障碍变 **−0.214%**（170 笔止损 / 104 笔止盈）。刚大涨过的票日内振幅大，−5% 在噪声区间内 |
| **高胜率不等于赚钱** | 尾盘买·持 1 日胜率 49.82%（全表最高），但盈亏比 0.986 < 1，保本要 50.35%，净仍为负 |
| **中位数为负** | 最优档中位净 −0.403%，正期望来自右偏。实操含义：**必须无差别执行每一个信号，不能挑** |

**卖点至少要定死四件事**：固定持有期 / 止盈线 / 止损线（或明确不设并接受尾部风险）/ 时间止损。

### D7. 其它两处

| 待定 | 说明 |
|---|---|
| **票池范围** | 是否含科创板（20% 涨跌幅）与创业板？double-pullback 回测第 109 行明记「板块含科创板，涨跌幅 20% 与主板 10% 混在一起，原稿未声明板块范围，本轮未拆分统计」。**同样的坑不要踩第二次** |
| **ST / 停牌 / 一字板** | 信号成立不等于能成交。涨停、封板、停牌、价格笼子拒单都要 veto |

---

## E. 落到本仓的实现落点（只读，未改代码）

### E1. `src/formula`：可用函数与筹码函数的现状

| 项 | 位置 | 内容 |
|---|---|---|
| Screen Formula 已开放函数 | `src/formula/README.md:26`；注册表 `src/formula/domain/screen_formula_catalog.py:12-14` | `REF MA EMA SMA WMA DMA SUM HHV LLV STD AVEDEV COUNT EVERY EXIST FILTER BARSLAST BARSSINCE BARSCOUNT HHVBARS LLVBARS IF ABS MAX MIN CROSS ZTPRICE TR ATR RSI ROC WR CCI OBV MACD_DIF MACD_DEA MACD BOLL_MID BOLL_UPPER BOLL_LOWER` |
| **P0 日线字段** | `src/formula/README.md:23`；`screen_formula_catalog.py:27` | `OPEN/HIGH/LOW/CLOSE/VOL/AMOUNT/HSL`，其中 `HSL` 运行时映射 `turnover * 100` |
| 位置类函数（本战法要用的） | `screen_formula_catalog.py:46-50` | `BARSLAST(COND)`（当日满足为 0）、`BARSSINCE(COND)`、`BARSCOUNT(X)`、`HHVBARS(X,N)`、`LLVBARS(X,N)` |
| `HHVBARS/LLVBARS` 并列最值 | `src/formula/README.md:28` | 「遇到相同最值时取**离当前最近**的一根」——[D3] 的「最大量有多根」在函数层已有默认行为，但需求方仍应显式确认 |
| **`COST` / `WINNER`** | `src/formula/README.md:25`；实现 `src/formula/domain/chips.py` | 「已实现为 Python 公式 API，但**暂不进入 Screen Formula 目录**；它们依赖跨全历史的筹码递推，**短窗口求值会产生伪精确结果**」 |
| 筹码递推模型 | `src/formula/domain/chips.py:9-15` | `chips(t) = chips(t-1) × (1 − 换手率) + 换手率 × 今日成交价格分布`；默认 100 档、`DEFAULT_DECAY = 1.0` |
| 筹码函数的缺数行为 | `src/formula/README.md:28`；`chips.py:233-241, 286-292` | 换手缺失时**从该日后返回空值**，「不用旧状态冒充准确成本」。缺失换手率会让衰减率变 0、分布永远停在第一天 |
| 变量窗口 | `screen_formula_compiler._window_range`（`:369-382`） | 窗口/偏移必须是整数常量或受限 int 参数，否则 `E_WINDOW_DYNAMIC`。[D3] 的动态 `REF` 要靠枚举合并绕开 |

**「`COST`/`WINNER` 为何未进目录」直接影响本战法的选型**：如果需求方确认要的是「通达信筹码」而非「股东结构」（[A4.2]），那么走 Screen Formula 这条路**当前不通**——要么先把 `COST/WINNER` 进目录（需要解决「短窗口伪精确」这个已声明的问题，属公开行为变更，要配 README/测试），要么改走 `runtime=python` 的 Screen Skill（可直接 `from src.formula import COST, WINNER`）。

### E2. `entry_timing` 前视审计：`close` 档为何不许用当日 `HIGH`/`LOW`

两套引擎，同一口径：

**公式侧** `src/formula/domain/screen_formula_compiler.py:389-408`：

```python
def _audit_entry_timing(self, name: str, expr: BoundExpr) -> None:
    allowed = {
        "next_open": {"OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AMOUNT", "HSL"},
        "next_dip":  {"OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AMOUNT", "HSL"},
        "close":     {"OPEN", "CLOSE", "VOL", "AMOUNT", "HSL"},   # ← 第 393 行，无 HIGH/LOW
        "open":      {"OPEN"},
    }[self.manifest.entry_timing]
    for field, lag in expr.field_lags:
        if lag > 0 or field in allowed:
            continue
        raise _compile_error([FormulaDiagnostic(code="E_ENTRY_TIMING_LOOKAHEAD", ...)])
```

**Python 侧** `src/strategy/application/audit.py`：

- 第 36 行 `INTRADAY_FIELDS = ("close","high","low","volume","turnover","amount")`（`open` 不在其中：竞价结束时开盘价已确定）
- 第 41 行 `CLOSE_TIMING_FORBIDDEN_FIELDS = ("high","low")`，注释原文：「尾盘（14:50 前后）决策时仍未确定的字段。**收盘价已基本定型可以用，但全天最高/最低要等收盘才知道**——与公式编译器 `_audit_entry_timing` 的 `close` 白名单保持同一口径」
- 第 50 行 `CURRENT_BAR_INCLUSIVE_CALLS`：`MA(close,5)` 的窗口是 `[t-4, t]`，仍读到当日 close，公式侧直接报错，Python 侧报 warn
- 第 276-367 行 `audit_truncation`：截断重跑，信号不一致直接 `block`——「这是行为层的证据」，静态 AST 查不出的 `.iloc[-1]` / 整列 `max()` 都会露出来

**理由**（`audit.py` 模块 docstring 第 5 行）：「前视偏差是量化里最贵的错误，因为它**只让回测变好看，不让代码报错**。」

**对本战法的直接后果**：[D4] 的「最低价触及均线」和 [D3] 的「最高价那根 K 线」若引用**当日** `HIGH`/`LOW`，在 `close` 档编译不过。这正是 double-pullback 回测把 `next_open` 定为「严格口径」、把 `close` 标为「乐观口径」的原因（该文第 30 行）。

### E3. 「盘中提示」：本仓现成能力覆盖到什么程度

**已有的（可以直接复用，不需要新建）**：

| 能力 | 现状 | 位置 |
|---|---|---|
| **盘中定时扫描** | 龙回头 `skill_watch` **每 10 分钟扫一轮**，时段 `09:20-11:30`、`13:00-14:50`；盘后复盘固定 `15:30` | `src/ops/README.md:37` |
| **扫描链骨架** | `payload`（悟道载荷解析）→ `kline_stats`（日线派生指标）→ `market_regime`（龙空龙闸门）→ `leader_map`（角色地图）→ `auction_confirm`（09:15–09:30 竞价复核）→ `dragon_return`（回头形态） | `src/ops/README.md:69-88`；`src/ops/application/skill_watch/` |
| **引擎注册表** | `engine_registry.py:54-63` 的 `_DRAGON_RETURN`：`needs_market_store=True` / `uses_market_gate=True` / `emits_observe=True` / `eod_rescan=True` / `label_zh="龙回头"` / `default_push_wecom=True`。README 原话：「新增战法：注册表加一条 + 能力字段，**勿再散写 slug 字面量**」 | `src/ops/README.md:83-88` |
| **每段可启停、每档可调** | 段开关 `market_gate / theme_interval / auction_confirm / role_history / paper_candidates`；阈值分 `gate / roles / scan / auction` 四段；**三套命名预设** `aggressive / balanced / defensive`（`tuning.py:130-180`）；值域表只在 `tuning._RANGES` 维护一份（`tuning.py:66` 起）；`tuning_schema()` 出中文名/步长/值域给前端。HTTP `GET\|PUT\|DELETE /api/skills/{slug}/watch-tuning` | `src/ops/README.md:99-108` |
| **角色留痕（只追加）** | `leader_role_snapshots`（`store_watch.py`）。README 原话：「`intel_snapshots` 是按 (交易日, 工具) 覆盖的缓存，同日多次扫描只剩最后一次，**角色演进会被抹掉**；这张表专门留住「谁从龙头掉成走弱」。」表里**只存观测事实**，存活天数/转移矩阵/预警提前量都即时算（`role_stats.py`）；保留窗由 `prune` 收口（默认 60 天） | `src/ops/README.md:109-122` |
| **企微推送 + 降噪** | 龙回头 `skill_watch` 的扫描摘要**不推**（`push_wecom=False`，「扫描摘要每轮复读整池，不该进企微」）；出声交给纸面跟随推送，只在**有动作**时发一条「监测·龙回头」。**两者只能有一个出声**，否则同一轮发两遍 | `src/ops/README.md:59-64` |
| **统一监察池** | `unified_monitor_pool:{slug}` 是唯一事实源；同一代码只有 `holding/buy/observe/sell/rebalance` 一个当前动作；持股≤3、非持仓监察≤5、共≤8 | `src/ops/README.md:26-27` |
| **MCP 软降级** | 悟道不可用时 `skill_watch` 记 `skipped`，不影响盘面/账本/本地选股 | `src/ops/README.md:130-133` |
| **只读预览** | `POST /api/skills/{slug}/watch-preview` 用实时数据试跑一次同一套扫描，不写纸面舱、不推送、不调 LLM | `src/ops/README.md:137-138` |

**结论：「盘中提示」这件事本仓的基础设施是完备的。** 定时、扫描链、闸门、调参、留痕、推送降噪、软降级、只读预览——全都有，且已经在给龙回头跑。**新战法要做的是加一个引擎函数 + 注册表一条，不是新建一套盘中系统。**

**缺什么（三条，都在数据侧不在工程侧）**：

1. **股东结构数据完全没有。** `market.db` 无任何股东表（[A5]）；`src/` 里没有任何地方调用 `shareholder_structure`（[A3.1]）。要用 [A2] 那个筹码口径，必须新增一条采集链 + 一张可重建缓存表 + README/ADR。
2. **热度历史仍然没有。** [B] 的结论未变。当前扫描链里的热度来自悟道 `smart_hotlist` 当前快照，**做不了「进过前10」这种带回看窗口的条件**——除非先攒够历史。
3. **盘中扫描每 10 分钟一轮，与「回归均线的那一刻」有粒度差。** 均线是日线量，盘中价格穿越均线可能在 10 分钟窗口内来回；扫描器看到的是采样点而不是穿越事件。这不是 bug，但**信号定义必须容忍这个粒度**（例如用「收盘价距均线 ≤ x%」而不是「精确触及」）。

### E4. 与既有 `dragon_return` 的重叠与冲突

既有实现 `src/ops/application/skill_watch/dragon_return.py`：

**可买区硬门槛** `_buy_zone_status`（第 329-358 行）：

| 条件 | 阈值 | 可调键 |
|---|---|---|
| 有高度或阶段涨幅 | `ladder_level >= 2` **或** `gain_20_pct >= 15` | `leader_min_level` / `leader_min_gain_20` |
| 确有回撤 | `1 <= pullback_days <= 10` | — |
| 回撤深度 | `5 <= pullback_depth <= 32` 且 `drawdown <= 28` | — |
| 结构未破 | `close >= ma20 * 0.94` | — |

**形态打分** `score_pullback`（第 156-182 行）：连板天数 ×8（上限 35）、`gain_20 >= 15` +4、梯队层级 +6/14/20、回撤深度 8–28% +18、回撤天数 3–10 天 +10、缩量 ≤0.65 +10、`close >= ma10*0.98` +8、`close >= ma20*0.96` +4、放量反抽 +12/+6、破位放量 −15。默认可买线 `candidate_score = 65`（`tuning.py:44`）。

**三层联合审计**（`_suite_checks`，第 45-94 行）：龙头身份 + 龙空龙市场闸门 + 龙回头形态，**任何一层失败都只能观察，不能买入**。

| 维度 | 既有实现 | 用户新版 | 关系 |
|---|---|---|---|
| **「曾大涨」** | `ladder_level >= 2`（连板）**或** `gain_20_pct >= 15` | 「20 日涨幅进过**前十**」 | **重叠但不等价**。既有是**绝对阈值**（≥15%），用户是**横截面排名**（前十）。排名口径稀疏度高一到两个量级，且随市场强弱漂移 |
| **「回撤到位」** | 天数 1–10、深度 5–32%、`close >= ma20*0.94` | 「回归 5/10/20 日线」 | **高度重叠**。既有已经在用 MA10/MA20 做结构判定（打分项 `close >= ma10*0.98` / `close >= ma20*0.96`） |
| **「锚」** | **没有**。既有用「区间高点回撤率」，不定位具体某根 K 线 | 「下跌前最大量或最高价那根 K 线」 | **这是用户版真正的增量**。既有实现里完全没有「成交量锚」这个概念 |
| **「热度」** | **没有**热度条件。用「龙头角色」（题材内排序 + 当日涨停纠偏）代替 | 「热度进过前10」 | **冲突**：两套不同的「人气」定义。既有走题材结构，用户走平台榜单 |
| **市场闸门** | **有**：龙空龙三态（进攻/观察/空仓），空仓日不开仓 | **没有** | **既有更严**。接入时必须明确：新战法是否也吃这道闸？`engine_registry` 的 `uses_market_gate` 就是这个开关 |
| **竞价复核** | **有**：09:15–09:30 `auction_confirm`，放弃就地改写角色为 `failed` | **没有** | 既有更严 |
| **买入时点** | 次日（预案 + 竞价确认 + ≥09:30 连续竞价才允许开仓） | 「止跌前一天或当天」 | **用户版不可实现**（[D5]）；既有版本已经是合规的 `next_open` 语义 |
| **卖点** | **有**：`rules_exit_orders` 四档（止损默认 −6% / 止盈 / 高抛减半 / 高开减仓） | **完全没有** | 既有可直接复用 |

**判定：不建议新开一个引擎。** 用户这套与既有 `dragon_return` 是同一族，真正的增量只有**两条**——「成交量/高点锚」和「平台热度」。前者可以作为 `score_pullback` 的一个新打分项 + `_buy_zone_status` 的一个新可选门槛（走 `tuning` 的调参体系，默认关闭）；后者受制于 [B] 的数据缺口，短期做不了。

[`2026-08-dragon-return-double-pullback-backtest.md`](2026-08-dragon-return-double-pullback-backtest.md) 第 121 行已经写过同一句话：「仓内已有的 `龙回头` 战法监测（`src/ops/application/skill_watch/dragon_return.py`）与本公式是同一族思路，**接入前应先比对两者信号重叠度，避免同一逻辑上两套**。」

### E5. 与 double-pullback 回测的关系：新旧两版

| 项 | 上一版（`2026-08-dragon-return-double-pullback-backtest.md`） | 本版（用户新描述） |
|---|---|---|
| 「曾大涨」 | `C/REF(C,10) >= 2`（**十日翻倍**，绝对阈值） | 「20 日涨幅进过前十」（**横截面排名**） |
| 稀疏度 | 十日翻倍单独命中 0.17%，全条件 281 次 / 2.5 年（日均 0.45 个） | 未知。「全市场前十」的稀疏度同量级或更极端 |
| 「回撤」 | 充分回调 + 回调活跃 + 有首阴 + 企稳（四条宽条件） | 「回归 5/10/20 日线」 |
| 「锚」 | 无显式锚，用 `HHVBARS(H,20)` 定位阶段高点 | **显式锚**：最大量或最高价那根 K 线 |
| 「热度」 | 无 | 有（「进过前10」） |
| 入场 | `next_open` 为严格口径，`close` 标为乐观 | 「止跌前一天或当天」→ 不可实现，需替代 |

**关系判定：本版是上一版的「加装饰」，不是「换内核」。**

上一版回测已经用数字告诉我们：**这个公式的选择性几乎全部来自第一条（十日翻倍）**，「后面四条（回调、首阴、活跃、企稳）都是宽条件，改它们的阈值对结果影响有限，改『十日翻倍』才会动筋骨」（该文第 49 行）。

本版把「十日翻倍」换成「20 日涨幅前十」、把四条宽条件换成「回归均线」、再加两个新门槛（热度、锚）。**按上一版的归因，最可能发生的是：新的第一条（20 日涨幅前十）继续决定 95% 的选择性，新加的锚与热度只是把 281 个信号进一步砍成几十个，从而把统计显著性砍没。** 上一版在 279 笔上的 +3.72pp 保本缺口**已经不到两个标准误**（该文第 99 行）；再砍一半样本，就没有可检验的东西了。

**因此建议的验证顺序是**：

1. **先只换第一条**（十日翻倍 → 20 日涨幅前十/阈值），其余照抄上一版，看信号密度和期望怎么变。这是单变量对照。
2. **再单独加锚**，看边际贡献。锚是唯一有一手学术依据的新增维度（[C2]/[C3]），值得单独测，且**正反两个方向都要测**（[C6]）。
3. **热度放最后**，因为它既缺历史数据（[B]）又已被同期回测判负（[`2026-08-heat-tail-attention-proxy-backtest.md`](2026-08-heat-tail-attention-proxy-backtest.md)）。
4. **全程沿用上一版立下的三条待办**（该文第 6 节）：用历史成分表复核存活偏差、划训练/验证/OOS、定仓位与止损。

---

## 附：本轮实际发出的请求与本机执行

只读、无凭据。HTTP 每个 URL 单次（超时的除外）。

| # | 请求 / 执行 | 结果 |
|---|---|---|
| 1 | `GET datacenter-web.eastmoney.com/api/data/v1/get?...RPT_F10_EH_FREEHOLDERS...columns=ALL...END_DATE='2026-03-31'&pageSize=2` | `200`，`success:true`，`count=55855`，`pages=27928`，逐行 40+ 字段 |
| 2 | 同上，`columns=` 7 列，`END_DATE='2025-12-31'`，`pageSize=500` | `200`，`count=55603`，`pages=112`，本页 500 行 / 50 只票，只回 7 列 |
| 3 | `GET oss-ch.csindex.com.cn/.../000300_Index_Methodology_cn.pdf` | **两次超时，未取到全文** |
| 4 | `GET finance.pae.baidu.com/selfselect/listsugrecomm?...day=20260731...` 与 `...day=20260812...` | **两次超时，未验证** |
| 5 | 检索并取回全文：华证《股票指数计算与维护细则》PDF、万得《指数计算维护规则》PDF | 已读并摘录 |
| 6 | 检索并取回全文：Grinblatt & Han (2005) JFE PDF、George & Hwang (2004) PDF、Frazzini (2006) PDF、Sullivan-Timmermann-White (1999) PDF 与 LSE FMG dp303 | 已读并摘录 |
| 7 | `GET gov.cn` 公报版《上市公司信息披露管理办法》、`csrc.gov.cn` 官网版、`sse.com.cn` 上市规则 PDF、`one.sse.com.cn` 信披服务页 | `200`，正文已读 |
| 8 | 悟道 MCP `shareholder_structure` **工具 schema** 读取（**未调用该工具，未扣配额**） | 取到 inputSchema 原文 |
| 9 | 本机只读：`socket.gethostbyname` 6 个主机；`akshare` 1.18.56 包内省 + 源码逐读；已下载 JSON 的本地解析 | 见 [0.1]、[A3.2]、[A2] |
| 10 | 本机只读：`rg shareholder_structure`（全仓）、`src/formula` / `src/strategy` / `src/ops` / `src/market` 源码与 README 阅读 | 见 [E] |

**未做**：批量抓取、带凭据请求、注册账号、POST 任何接口、调用悟道 MCP 工具、写入任何数据库、跑回测、修改除本文与 `INDEX.md` 之外的任何文件。

---

## 未解决的问题

1. **「筹码」到底指哪一个。** 「100 − 十大流通股东>5%之和」（季频股东结构）与通达信筹码峰（日频换手衰减）是两个完全不同的量，而群里那句「每天收盘后才能算」只对后者成立（[A4.2]）。**这是动手前必须先问清的第一件事。**
2. **东财 `getHisList` 的真实历史长度与粒度。** POST 接口，只读通道发不出，`yearType="5"` 只是 akshare 作者写死的入参，不是文档（[B2.1]）。
3. **百度股市通 `day` 参数是否真返回历史。** 两次探测超时（[B2.3]）。若生效，它是唯一免费、带日期、带热度值的历史注意力源——值得再花一次探测成本。
4. **同花顺逐票热度历史接口是否存在。** 本轮未找到；App 里有历史曲线说明后端应该存在，但无一手证据，不猜 URL（[B2.2]）。
5. **中证官方 PDF 全文未读到。** 4.4 条正文靠检索引擎抽取 + 华证/万得两份全文互证（[A1.1]）。若要写进 ADR，应补一次直连取全文。
6. **「单独一根最大成交量 K 线作参考价」的一手学术研究未找到。** 找到的都是整段换手加权（Grinblatt-Han）或极值锚（George-Hwang）（[C3]）。单根版本目前只有工程直觉，没有文献支撑。
7. **两个实例（金安国际、欣天科技）未复核。** 本文不做个股取数，未验证其形态是否符合描述，也未验证按该规则能否在实盘时点选出它们。
8. **锚方向的对照实验未做。** [C6] 提出的「回踩到锚 vs 站在锚上方」双向回测是本文最重要的可执行建议，但本轮**不跑回测**，未执行。
