# 研究文档索引

`docs/research/` 目前 75 篇 md、约 2.9 MB，占 `docs/` 体量的九成。此前 `docs/README.md`
只索引了其中 5 篇，20 篇没有任何入边——对人和 agent 都不可导航。本文件是导航入口。

## 读之前先看这两条

1. **研究文档记录的是「某一天、某一份输入下的判断」，不是系统现状。** 每篇头部都有执行
   日期，多数还锁了被审对象的 commit。判断现状请读代码与 `src/<context>/README.md`。
2. **同一主题有多轮时，只有最后一轮是终态。** 前几轮里被标为 P0 的问题很可能早已修复；
   下表的「状态」列标明了哪一篇是终态。

---

## 全系统审计（6 篇 · 2026-08-07 同日递进）

六轮是一条链，每轮 = 复核上一轮修复 + 本轮新发现，**不是六份重复**。

| 文件 | 状态 |
|---|---|
| `2026-08-system-wide-audit.md`（R1） | 已被 R2 复核 |
| `2026-08-system-wide-audit-r2.md` | 已被 R3 复核 |
| `2026-08-system-wide-audit-r3.md` | 已被 R4 复核 |
| `2026-08-system-wide-audit-r4.md` | 已被 R5 复核 |
| `2026-08-system-wide-audit-r5.md` | 已被 R6 收口 |
| `2026-08-system-wide-audit-r6.md` | **终态**，先读这篇 |

> 注意 R6 里的 `pytest 422 passed`、R1 里的 `lint-imports 9/9` 都是当时的数字，现已不同。

## 龙王 / 龙头族（11 篇）

各篇头部都声明了与姊妹篇的分工，分工真实存在，不建议合并。

| 文件 | 侧重 |
|---|---|
| `2026-08-dragon-pool-forward-validation.md` | **唯一带本机全市场实测的**（`dragon_pool_backtest.py`，5515 只），优先读 |
| `dragon-leader-identification.md` | 可回测的龙头识别口径 |
| `2026-08-dragon-leader-definition.md` | 市场上实际在用的说法（补上一篇刻意回避的另一半） |
| `2026-08-dragon-return-playbook.md` | 回封战法细则与扫描数据包 |
| `2026-08-dragon-return-quant-implementation.md` | 同一结论的可编程实现侧 |
| `2026-08-dragon-return-double-pullback-backtest.md` | 用户原稿通达信公式「十日翻倍回踩企稳」的回测。**本轮系列里第一个前后两段都为正的信号**（次开买持5日：胜率 48.39%、盈亏比 1.239、均净 +0.886%/笔）。但中位数为负、2.5 年仅 281 次、正期望靠不设止损换来；存活偏差方向乐观，待历史成分表复核 |
| `2026-08-dragon-return-chip-anchor-feasibility.md` | 同一用户**下一版**描述（热度前10 + 20日涨幅前十 + 大量/高点K线作锚 + 回踩均线）的一手核验。三条结论：①「筹码=100−十大流通股东>5%之和」**能算也能全市场回测**（东财 `RPT_F10_EH_FREEHOLDERS`，一个报告期 112 页 / 55,603 行实测），但它**不是**官方自由流通口径的近似（四处系统性偏差 + 实测反例）；②热度历史仍无免费全市场源；③学术上「换手加权价作锚」有强支持（Grinblatt-Han，与本仓 `chips.py` 同一递推），但**方向与用户相反**。另列 7 处不可编程/歧义处，含「止跌前一天」不可实现 |
| `2026-08-dragon-pool-trigger-chip-backtest.md` | 上一篇描述的**回测终态**。架构=监控池+盘中触发器（20日涨幅前十入池 → 盯20交易日 → 当日最低≤MAn 且收盘>MAn）。**MA10 是三条线里唯一站在保本线上的**；裸触发器不成立，叠筹码后有 8 个格前后两段皆正。获利盘与收益是 **W 形**（25-50% 最好、50-75% 是坑、75-100% 中等），G-H 与用户直觉都错在当成单调。触发日 20 日涨幅 50~100% 那档最可靠（394 笔、两段皆正） |
| `2026-08-incumbent-strategy-full-sample-benchmark.md` | **给所有战法定标尺的一篇**。潜龙/三源声明的头条数字都锁在各自调优的半年；放到 31 个月全样本重跑，每笔均净从 +2.97%/+1.47% 塌到 **+0.55%/+0.46%**，胜率双双跌破 50%，中位数转负，潜龙回撤 −6.7%→**−41.3%**。自跑复现了声明的笔数与胜率（78/64.10、125/56.00），框架可信。**别拿现役战法的声明值当目标** |
| `2026-08-incumbent-rank-levers.md` | **长效优化对照（线上参数未改）**。2021–2026、成本 3/5/10、只换 Top2 排序。潜龙改成「刚站上辰星线」均净 +0.14%→**+0.41%**、组合 +5%→**+82%**，2021–2025 只剩 2023 −0.12%；换手带不能关。三源现行评分已是对照里最好的排序，改涨幅/CLV/双阴全部更差。14 组无一通过逐年全正 |
| `2026-08-dragon-survivorship-and-portfolio-fragility.md` | **读这篇之前不要相信任何组合层收益数字。** 三条：①退市存活偏差**本地不可测**（`delist_date` 5540 条全空、`quotes_daily` 无库外代码、各年末在交易数单调升 5279→5535，退市票行情没同步）；②按当前名称排除 ST 是**剔掉赚钱的票**（那 203 只每笔 +4.39%、中位 +8.38%），方向与直觉相反；③**信号数差 3.4%、组合全期收益差 187%**（34.09% vs 97.80%）而逐笔只差 4.5%——组合层对信号扰动高度敏感，「月化 2.222%」须降级为量级参考 |
| `2026-08-dragon-second-wave-live-alert-spec.md` | **已退役（2026-08）**：引擎、技能包、监测任务与留痕表都已删，只留规格与数字备查。盘中提醒规格 + 观察期流程。触发 = `当日最低 ≤ MA10 < 现价` ∩ 距 20 日最高 ≤3 日 ∩ 市场宽度 ≥55%，不排除 ST；不需要分钟线（快照的 `low` 就是当日累积最低）。首轮实跑池子 38 只、触发 1 只。**未接 `skill_watch`、未建 Job**——观察期先跑 JSONL，四条验收过关才谈生产接入 |
| `2026-08-dragon-void-vs-pullback.md` | 断板 vs 回踩的证伪 |
| `dragon-pool-evidence-2026-08.md` | 一手证据核对（含「与本仓既有文档的分工」章节） |
| `2026-08-dragon-king-suite-audit.md` / `-external-evidence.md` | 套件级审计与外部证据 |

## 单因子候选（9 篇 · 结论一致：全部拒绝）

**`PTH252` / `TVOL` / `12-1 动量` / `REV21` 四个因子均已明确「不进入候选池，也不进入
函数目录」。** 再次提议前请先读对应的 streaming-exploration。

| 因子 | 一手来源核验 | 流式探索（结论） | 其他 |
|---|---|---|---|
| PTH252 | `2026-08-pth252-primary-source-validation.md` | `2026-08-pth252-streaming-exploration.md` | `-external-evidence-audit.md` |
| TVOL 低波 | `2026-08-low-volatility-primary-source-validation.md` | `2026-08-low-tvol-streaming-exploration.md` | — |
| 12-1 动量 | `2026-08-momentum-12-1-primary-source-validation.md` | `2026-08-momentum-12-1-streaming-exploration.md` | — |
| 21 日反转 | `2026-08-short-term-reversal-primary-source-validation.md` | `2026-08-short-term-reversal-streaming-exploration.md` | — |

上游选题依据：`2026-08-ohlcv-factor-candidate-primary-sources.md`。

## 外部项目对标

| 主题 | 文件 | 备注 |
|---|---|---|
| Vibe-Trading（7 篇） | `-comparison` / `-data-layer` / `-data-layer-audit` / `-data-layer-source-evidence` / `-data-layer-source-refresh` / `-data-layer-paper-source-audit` / `-implementation-brief` | 前六篇**锁同一外部 commit `3a752d5a`**，是对同一份不变输入的多轮审计 |
| UZI-Skill（3 篇） | `-capability-mapping` / `-primary-source-audit` / `-followup-audit` | 同锁 commit `fce996c3`；followup 头部自述以能力映射为背景 |
| PanWatch | `2026-08-panwatch-vs-loci.md` | |
| 量化指南针 | `quant-compass-quant-platform-2026-07-12-to-08-04.md` | |

## 尾盘 / 三角 / 隔夜

| 文件 | 备注 |
|---|---|
| `2026-08-yule-materials-tail-close-feasibility.md` | **本主题的终态判定，先读这篇**。基于用户 `D:\资料\娱乐` 96 个文件（解析成功 77）+ 制度与文献一手核验 + 439 万样本实测。三条结论：①**尾盘入场是一笔与持有期无关的固定过路费 −0.108pp**（持 1/2/3/5 日分别 −0.1096/−0.1088/−0.1085/−0.1087，两臂之差就是隔夜跳空）；②**过路费是「今天有多热」的函数**——换手率最冷十分位 **+0.0003%**（等于零）、最热 **−0.6611%**，热门票持 2 日亏损的 **77–90% 来自隔夜**，冷门票只有 0–20%；③**11 条预注册臂 11/11 次开买优于尾盘买**，尾盘代价排序就是信号热度排序，素材台账推荐第 2 名的 T36+T38 实测**全场最差**（−1.41pp，基线的 13 倍）。唯一活下来的是 **T28「杨氏六条」+ 次开买 + 持 2 日**（19,132 笔、均净 +0.5853%、胜率 50.71%、盈亏比 1.372、**逐年 6/6 不为负 + 两段皆正**），与潜龙/三源同水平但样本量 26–40 倍；但 §7.3 承认它**本质是小盘因子不是尾盘 alpha**、一半收益来自择时、日均 14.1 只需 Top-N。四条独立证据线（用户材料原话 / 交易所规则与文献 / 本机实测 / 本仓现役 `entry_timing=next_open`）合流于同一句：**尾盘该用来选股，不该用来买入**。含对既有文档的 3 处制度修正（北交所盘后固定价格**暂缓**、价格笼子只管连续竞价、0.19% 的重演窗口是 14:55–15:00 非现行 14:57–15:00）。**§10 是落地章**：176 组排序/Top-N 网格里 7 组通过稳健性判据且**全部来自「当日涨幅降序」**（其余 10 个因子 0/16，集中度即证据），定参为 Top1 + 持 3 日 + 宽度≥40%（组合 +328%、回撤 −32.6%、逐年全正），已实现并注册为 `yangshi-tail-v1` |
| `2026-08-tail-close-indicator-source-review.md` | 尾盘选股指标外部来源审阅 |
| `2026-08-triangle-tail-distill.md` / `-grid.md` | 材料抽取 + 网格回测；明细在 `_scratch_triangle_tail_grid.csv`（**该 CSV 是这两篇结论的全部原始数据，删了结论不可复核**） |
| `2026-08-loci-weipan-overnight-formula.md` | 尾盘隔夜公式，线索表与来源在两个 `_scratch_overnight_*.md` |
| `2026-08-ths-heat-tail-close-picker.md` | 「同花顺热度前 50 + 市值 ≤200 亿 + 尾盘买」设想的一手核验：热度接口实测可用（无历史），但注意力文献在 T+1~T+20 尺度上偏证伪 |
| `2026-08-heat-tail-attention-proxy-backtest.md` | **上一篇的终态判定**（两轮）。第一轮确认式：注意力把次日冲高命中率从 22.5% 抬到 38–47%，但放大的是双向波动，亏损全在隔夜，T+1 使"只吃盘中"不可交易。第二轮探索式（宽池子等权 + 9 维切片 + 交叉搜索）：把先验全部反过来（要大市值、热度榜尾部、低换手）确能改善，但 top20 组合**无一前后两段都为正**，后段清零 → **负期望，ADR-011 不进第 2 步**。含一处已修 bug 的披露（§9.7） |
| `2026-08-tail-1450-next-day-touch-evidence.md` | 「14:45–14:50 买入 + 次日最高价触及 +0.5% 算盈利」的一手核验 + 全市场实测（271 万观测）。**判定：标签本身就是坏的，与选股无关。** ①零 alpha 基线命中率就有 **76.06%**，保本胜率 **92.45%**，缺口 −16.10pp；②命中率与期望**反向**——Parkinson 波动率十分位命中率 64%→81%（+17.1pp，比整个 alpha 空间还大），均净同时从 −0.29% 恶化到 −0.86%；③**中位数在全部 38 个切片里恒等于 +0.24%**（= 0.5% − 成本），零信息量；④封顶止盈使盈亏比塌到 0.08，用户"盈亏比高"的验收标准与其方案自相矛盾。一手来源补上游未答的四点：上交所研究报告实测 **\|收盘价/VWAP(14:50-14:55)−1\| 均值 0.19%/最大 4.55%**；深交所价格笼子对卖单是**下限不是上限**（与预期相反）；Lo/MacKinlay/Zhang JFE 2002 点名 one-touch fill「very poor proxies」；qlib 官方 label **一个 `$high` 都不用**。含 6 条回测口径要求（R1–R6，波动率匹配对照臂是核心）与 2026-07-06 新规（盘后固定价格交易扩至全部 A 股）|
| `2026-08-tail-1450-next-day-touch-backtest.md` | **上一篇的姊妹篇：同一条规则的选股侧实证**（脚本 `scripts/tail_1450_next_day_touch_research.py`，2021-01 ~ 2026-08、1,358 日、440 万样本，比姊妹篇多两倍窗口）。口径与姊妹篇不同：**0.5% 只是「冲高算不算有效」的门槛，不是止盈价**，网格按「不封顶、持到次日收盘」排序，另给六种出场对照。**判定：全市场 −0.249%/笔，4,479 个过滤组合仅 1 个两段皆正（且日均 180 只、均净 +0.093%，不可执行）。** ①冲高率基准 **75.12%**，冲高幅度均值 +2.05%/中位 +1.33%，这个"胜率"没有判别力；②**中位数在 4,479 个组合里 0 个为正**（最好 −0.071%），它也不适合当验收指标——潜龙/三源全样本中位数同样为负；③冲高率是波动率的影子：`atr_pct≥5` 冲高率最高（79.58%）而均净最差之一（−0.272%），ATR 十分位 64.40%→78.03%；④**32 个单条件全部为负**；⑤**日内截面中性化是分水岭**：带 `breadth≥55` 的组合日中性一律转负（择时不是选股），带 `rsi6≤60` 的两个为正；⑥唯一值得继续的线索 `clv≥0.95 & vol_ratio≥1.5 & rsi6≤60`（日均 4.25 只、盈亏比 **1.400**、均净 +0.400%、**日中性 +0.209%**），但六年四年为负、前段 −0.49%，不能上；⑦出场单调序：止盈越紧盈亏比越低（0.5%→0.166、2%→0.709、不封顶→1.049、卖在次日最高的不可实现上界→3.685）。数据层两条硬发现：本机**无分钟线**（14:50 只能用收盘代理）、日线 `amount` **97.82% 是 `close×volume` 合成**（腾讯源），日线 VWAP 在本仓不可算。§10.1 披露了第一版把 0.5% 误读为止盈价的口径错误与哪些结论不受影响。明细在 `_scratch_tail_1450_touch_grid.csv`（4,479 行，**是第 5–6 节结论的全部原始数据**）|

## 主流量化体系对标（2026-08-25 · 1 篇终稿 + 8 篇证据分册）

| 文件 | 备注 |
|---|---|
| `2026-08-mainstream-quant-benchmark.md` | **终稿，先读这篇。** 8 个并行 agent 的合成：六层能力成熟度矩阵（数据 C / 因子 D / 回测 B / 组合 C / 执行 B / 实验 设计A-落地D）+ 三个用户诉求的直接回答 + 0/30/60/90 天路线图（每项带验收门禁）+ 14 条「明确不做」。核心实测：`market.db` **5,740.2 MB**（文档记的 2.4 GB 已过时），其中**溯源审计占 44.8%（2,569 MB）**；同一份 16,966,403 行导出 Parquet+Zstd 只要 **395.6 MB（10.6×）**；`DROP INDEX idx_quotes_receipt` + Parquet 面板取代热库，**一年历史不删就省 2.3 GB 且主查询快 7.1 倍**。三处新发现的硬缺陷：① `research_portfolio.py:367` 的 `equity = cash + Σ 入场名义额`，**未实现盈亏恒为 0**，历史「组合回撤 −37.55%」量错了对象；② `quotes_daily` 无 `limit_up`/`limit_down` 列，打板类回测系统性高估；③ `optimize` 丢弃 trial 序列 + `strategy_backtests` 0 行 → DSR/PBO **算不出来不是算法问题是数据问题**。判定「差距非常大」一半对一半不对：证据链/防前视/人工签署强于多数 OSS，落后的只有数据宽度、截面因子、组合账户、盘中留存、实验记录五块 |
| `_scratch_2026-08-qb-our-system.md` | 本仓只读审计（585 行）。akshare 1.18.56 有 1,093 个 callable / 403 个 `stock_*`，**真正进链路 9 个**（穷举带行号）、目录可见未用 395 个、目录发现不了 690 个。`crypto.py` 已削成 9 行只剩 `mask_secret()`，`.palace_ai_master_key` 是死文件。scipy/sklearn/vectorbt/numba **已装未声明且零 import** |
| `_scratch_2026-08-qb-qlib.md` | Qlib 源码级拆解（730 行，锁 commit `79633dd9`）。`.bin` 二进制回环实测（首元素是 float32 的日历起点下标）、官方 CN 日线包实测 271.3 MB / 27,125 个 bin。**判定：抄 recorder 与组合口径，不抄 `.bin`/Disk 缓存/`eval` 引擎**——「每票每字段一文件」对「全市场某日截面」是最差布局，而那是我们 100% 的用例 |
| `_scratch_2026-08-qb-cn-oss.md` | 7 个中文开源系统体系对比（549 行）。六格式 B/行实测：本仓 DDL **193.78** vs Hikyuu 40 / RQAlpha 56 / WonderTrader 88 / Parquet 19.29 → **「SQLite 天生贵」只解释 1.75×，其余 2.77× 是我们自己的 schema**。Hikyuu 是**九件套**（TM/MM/EV/CN/SG/ST/TP/PG/SP）不是六件，`System.cpp:743` 止损距离直接是 MM 的 risk 入参；我们缺 ST/TP/PG/MM/TM 五件，这就是「MFE 远高于净收益」的机械成因。RQAlpha 许可是 **NOASSERTION 双轨，非 OSI 开源** |
| `_scratch_2026-08-qb-backtest-engines.md` | 回测/组合/执行引擎对比（1,215 行）。自测向量化 13.63 ns vs 事件驱动 325.86 ns/bar-asset（**24×**，且是事件驱动下界）→ **不换引擎，做两段式**。给 4 对象 + 8 条不变式。zipline 的 2.5% 成交量上限**源码无任何推导依据**且同库自相矛盾。DSR 公式经三处论文算例数值验证；`exchange_calendars` **根本没有 XSHE** → 日历不换 |
| `_scratch_2026-08-qb-factor-stack.md` | 因子研究流水线（860 行）。**纠正流传很广的说法：alphalens 对因子不做任何去极值**；**Qlib 的 `Rank`/`Quantile` 是时序不是截面**，Alpha158 的 158 个特征无一截面算子。真缺 16 个算子；截面 rank 在 700×5547 上实测只要 **311 ms / +97 MB**，比现役 `AVEDEV` 还便宜。22 条数值门禁全可用 stdlib `NormalDist` 实现。**ML 与组合优化库均明确否定**（Qlib 官方 benchmark：线性拿到 LightGBM 九成 IR） |
| `_scratch_2026-08-qb-storage-encryption.md` | 数据层体量/分层/加密（783 行，29 张表）。九格式实测；**分区必须 date-major**（压缩最优的 code 排序主查询慢 4.8 倍）；`LOCI_MARKET_DUCKDB` 现状只有 1.3× 因为接错了头（**ADR-002 需重新基准化**）。统计功效：ICC=0.2822，**潜龙 24,878 笔有效样本仅 2,090、t=2.13 不显著；分手快乐 495 笔 t=3.14 显著**。加密单一推荐 DuckDB 原生 Parquet Modular Encryption（**SQLCipher 零 Windows wheel 出局**）。两个静默失效陷阱实测复现 |
| `_scratch_2026-08-qb-akshare-surface.md` | AkShare 全景（644 行）。90 行价值排序表，「有无历史」列无空缺：**21 个只有当天快照 + 3 个只有最新一期 = 24 个不自存就永久丢失**。**集合竞价在 AkShare 全库无第二个入口**（grep = 0）。涨停池 6 个接口越界时**静默返回空表**，回测会读成「那天没有涨停股」——最危险的一条。PIT 正确锚点是 `stock_yysj_em.实际披露时间`。近 12 月 273 个版本、76 个接口被动过、**删接口不写 changelog**；8 种破坏模式现有防线只覆盖 1.5 种 |
| `_scratch_2026-08-qb-live-ops.md` | 研究到实盘那一段（601 行）。**纠正两处过期前提**：`paper_exec.py` 已有 `PaperOrder` + 8 类 pre-trade 检查；二波盯盘已挂 Job。真正零覆盖的是**实验可复现**与**回测-实盘偏离**。给 `loci-experiment-manifest-v1` JSON Schema、22 项 pre-trade、18 条静默失败检查、19 条入库断言 |

决策落点：[`docs/adr/ADR-014-encrypted-intraday-tape-retention.md`](../adr/ADR-014-encrypted-intraday-tape-retention.md)（草案）。

## 平台产品与社区化对标（2026-08-27 · 1 篇）

| 文件 | 备注 |
|---|---|
| `2026-08-quant-platform-product-benchmark.md` | 与上一节分工明确：那节对标**开源体系的工程分层**，本篇对标**商业平台的产品面与社区面**（广场/克隆/榜单/跟单/订阅/大屏）。18 个平台（国内 9 + 国外 9）四态矩阵。三条核心结论：①**国内无一家把社区与引擎同时做透**——聚宽有克隆没榜单、果仁有榜单没编辑器、雪球社区最强但没有回测；②**排行榜是国内外差距最大的一格**：QuantConnect `score = 一年 Sharpe × 样本外折扣`、Collective2 把订阅费与佣金算进净收益、Numerai 按质押加权，国内基本是裸收益率；③**跟单国内全是 ❌ 是牌照原因不是技术原因**，果仁的「只推指令不给定义」是唯一合规解。含 Top 15 补齐功能的价值/成本排序（账号多租户与沙箱执行比值不高但是硬前置）与 5 条明确不做。取证受限说明单列一节：聚宽/掘金/雪球三家官网直读失败，相关判断标注为二手 |
| `2026-08-oauth-identity-research.md` | 微信开放平台「网站应用微信登录」与 QQ 互联的完整 endpoint/参数表、资质结论、Python 库选型（argon2-cffi / PyJWT ≥2.13.0 / aiosmtplib；**passlib 事实停维，Python 3.13 起不可用**）、users/identities/sessions 五表 DDL 草案、可插拔 provider 接口与扫码状态机、邮箱注册安全 7 条。两条被写进代码注释的硬事实：微信 `unionid`「当且仅当已获得 userinfo 授权时才出现」；QQ 的 token 与 me 两个接口**默认不返回 JSON**，必须显式 `fmt=json` |

决策落点：[`docs/adr/ADR-015-v2-multi-tenant-identity-and-community.md`](../adr/ADR-015-v2-multi-tenant-identity-and-community.md)。

## 技术雷达与工程

| 文件 | 备注 |
|---|---|
| `2026-07-loci-tech-radar.md` / `2026-08-github-open-source-technology-radar.md` | 选型备选 |
| `2026-07-foundation-next.md` / `2026-08-phase2-evidence.md` | 地基与 Phase 2 闸门证据 |
| `2026-07-async-route-audit.md` | FastAPI sync/async 路由审计 |
| `2026-08-market-data-source-intake.md` / `2026-08-wudao-mcp-utilization-assessment.md` | 数据源与 MCP 评估 |
| `2026-08-eastmoney-dk-bs-marker-feasibility.md` | 东财「DK点」B/S 买卖点标记的一手尽调 + 本仓落地评估。三条结论：①**DK 算法官方未公开且不可复现**——官方只说「多因子 / 人工智能演算 / 跟踪资金流向」，而资金流是东财 Level-2 派生数据，本仓拿不到同源输入，属一票否决（对照：同公司的**九转算法在官方帮助中心写全了**）；②DeMark 唯一一份同行评审实证（Lissandrin/Daly/Sornette，SFI 15-56）在 21 个商品期货上显著，但作者自述「**不能预测方向**」，A 股上**无一手检验**；③**画 B/S 这件事本仓零架构缺口**——`MarkPointComponent` 已注册、`klineLimitMarks.ts` 是现成模板、`ArchiveView` 已握有按 code 的 `TimelineEvent`，最小改动 5 源文件 + 2 README，真缺口是「战法信号按 code 的时间序列端点」与复权口径 |

## Scratch（临时产物）

`_scratch_overnight_clue_table.md`、`_scratch_overnight_sources.md`、
`_scratch_triangle_tail_grid.csv`、`_scratch_tail_1450_touch_grid.csv`。前两个仅被
`2026-08-loci-weipan-overnight-formula.md` 引用；两个 CSV 见上文，属原始数据不可删。

`2026-08-yule-materials-tail-close-feasibility.md` 的四份配套产物，**都不可删**：

| 文件 | 内容 | 为什么不可删 |
|---|---|---|
| `_scratch_2026-08-yule-tail-material-inventory.md` | 96 个文件的解析台账 + 75 条尾盘规则 + 19 条反向证据，全部带原文摘录与页/片/行定位 | 素材在 `D:\资料\娱乐`（仓库外，且 17 个 tn6 加密未解）。**这是那批材料在本仓唯一的可追溯记录** |
| `_scratch_2026-08-tail-close-external-primary-sources.md` | 三所交易规则逐条 + 10 篇论文一手核验，附 24 条来源清单与 P1/P2 证据分级 | 含对既有文档的 3 处修正；11 个「未找到一手来源」的缺口清单避免重复检索 |
| `_scratch_tail_close_entry_baseline.json` | 439 万样本的入场基线：8 条臂 + 逐年 + 4 个因子的十分位（收益与隔夜跳空各一套） | 终态文档 §2–§3 全部数字的原始出处 |
| `_scratch_tail_material_rules.json` | 11 条预注册臂 × 2 种入场 × 3 个持有期 + 逐年 | 终态文档 §6–§7 全部数字的原始出处 |
| `_scratch_yangshi_rank_portfolio.json` | 176 组排序/Top-N/宽度/持有期网格，每组含逐笔、逐年与组合层（收益/回撤/占用率） | 终态文档 §10 的原始出处，也是**已注册战法 `yangshi-tail-v1` 的定参依据**——删了就无法复核为什么选「当日涨幅降序 Top1」 |

---

## 维护

新增研究文档时在本文件登记一行。同一主题开新一轮时，把上一轮的状态改成「已被 X 复核」。
