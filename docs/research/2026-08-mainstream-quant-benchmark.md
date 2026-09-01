# 主流量化体系对标与后续路线（2026-08）

> **调研日**：2026-08-25（UTC+8）
> **方法**：8 个并行 agent（1 内部只读审计 + 6 外部源码级调研 + 1 AkShare 全景）+ 主 agent 本机实测。产出 8 篇证据分册（合计 5,967 行），本文只保留结论与决策，数字全部可回溯到分册或本机实测。
> **与前序的关系**：[`2026-08-github-open-source-technology-radar.md`](./2026-08-github-open-source-technology-radar.md)（2026-08-08）是**清单式**雷达（197 个仓库、stars/license 快照）。本文不重复清单，做的是**体系与架构层面的分层对标**——人家的数据层/因子层/回测层/组合层/执行层/实验层各长什么样、为什么那样设计、我们缺哪一块、值不值得补、最小代价路径是什么。
> **免责**：仅供方法论与工程决策参考，不构成投资建议。

---

## 0. 这篇回答四个问题

| # | 用户原话 | 回答在 |
|---|---|---|
| 1 | 距主流量化系统差距非常大；引入的 AkShare 数据该用的没用起来 | §2 §3 §4 §5 |
| 2 | 实际需要的历史数据不需要那么庞大 | §6 |
| 3 | 实时数据加密留存 30–60 天做量化分析 | §7 |
| 4 | 调研主流开源量化体系，考虑后续怎么做 | §3 §8 §9 |

---

## 1. 先给结论

1. **「差距非常大」这个判断，一半对一半不对。** 我们在**证据链、防前视、人工签署、溯源回执**这几件事上比绝大多数开源量化系统做得更狠（Qlib / backtrader / vn.py 都没有 run card + 冻结重放 + 强制人工签署这一套）。真正落后的只有五块：**数据宽度、截面因子、组合账户、盘中留存、实验记录**。这是偏科，不是全面落后。

2. **「AkShare 用不起来」的机械原因不是没接口，是面板只有 8 列。** `PANEL_FIELDS` = `open/high/low/close/volume/amount/turnover/outstanding_share`（`src/market/infrastructure/store_schema.py:14-16`），通达信公式 DSL 只认 7 个字段别名。本机 akshare 1.18.56 有 **1,093 个顶层 callable、403 个 `stock_*`**，真正进入数据链路的 **9 个**——即便把另外 394 个都接上，它们也没有任何一条通路能进入选股表达式。**先修管道，再谈接口。**

3. **真正被浪费掉的不是「少调了几个接口」，是「21 类只有当天快照的数据一天都没存过」。** 集合竞价、盘口异动、全市场 spot 截面、人气榜、千股千评、板块资金排名——AkShare 侧**没有任何参数能取到过去某一天**，东财 `trends2` 的 `ndays` 上限是 5。**每拖一天就永久少一天历史。** 这一条直接把诉求 1 和诉求 3 焊在一起了。

4. **「历史数据太庞大」的真凶不是年份长，是行存 + 逐行溯源。** 生产 `market.db` 实测 **5,740.2 MB**（文档记的 2.4 GB 早已过时），其中 **44.8%（2,569 MB）是溯源审计表与索引**；同一份 16,966,403 行导出 Parquet+Zstd 只要 **395.6 MB（10.6×）**。**正确解法是换格式，不是删年份**——36 年全历史一个 400 MB 文件装得下。

5. **`DROP INDEX idx_quotes_receipt` + 用 Parquet 面板取代 `market_hot.db`，一年历史都不删就省 2.3 GB，主查询还快 7.1 倍**（实测 289 ms vs 现状 2,040 ms）。这是全篇性价比最高的一条。

6. **盘中留存的技术路已经跑通实测**：DuckDB 1.5.5 原生 Parquet Modular Encryption，A/B 实测 **343 ms vs 明文 354 ms（无劣化）**、体积 0.977×、无密钥硬失败、**零新增依赖**。SQLCipher 因为 `sqlcipher3-binary` **零 Windows wheel** 在本项目上装不上，直接出局。最有价值的六类盘中数据 **60 交易日合计 2.03 GB**——删掉该删的 `market_hot.db`（1,022 MB）就覆盖一半。

7. **发现两处必须修的硬缺陷**（本轮新增，不在既有文档里）：
   - `research_portfolio.py:367` 的 `equity = cash + Σ 入场名义额` —— **未实现盈亏恒为 0**。历史上那个「组合回撤 −37.55%」量的是**已实现盈亏回撤**，不是账户回撤。组合层退化成会计程序，不是模拟器。
   - `quotes_daily` **没有 `limit_up` / `limit_down` 两列**，涨跌停按板块规则现算。RQAlpha 的做法是把这两列**当行情字段存进 bundle**——一次性覆盖主板 10% / 双创 20% / 北交所 30% / ST / 新股首日。我们所有打板类回测因此**系统性高估**。

8. **`optimize` 网格扫描把 48 条 trial 的收益序列当场丢掉**，`strategy_backtests` 表建了但 **0 行**。后果是 DSR / PBO 这两个防过拟合的标准门禁**现在算不出来——不是算法问题，是数据问题**。而同一个库里，44.8% 的磁盘花在证明「我什么时候抓的」，「结论怎么得出的」投入 **0 字节**。

---

## 2. 现状实测：四组硬数字

> 全部为 2026-08-25 只读实测（`file:...?mode=ro` + `dbstat`），真实数据目录 `E:\entertainment_software\Loci\data`（仓库里的 `data/*.db` 是 0 字节空壳）。`OurSystemAudit` 独立重跑，与主 agent 逐位一致。

### 2.1 5.74 GB 里只有 55% 是行情

| 对象 | 大小 | 归类 |
|---|---:|---|
| `quotes_daily`（表体） | 2,723.0 MB | 行情 |
| `idx_quotes_receipt` | **1,049.0 MB** | 溯源 |
| `source_route_attempts` | 724.7 MB | 溯源 |
| `source_route_receipts` | 450.9 MB | 溯源 |
| `idx_quotes_code_date` | 424.9 MB | 行情（主查询索引） |
| `idx_source_attempts_source` | 127.3 MB | 溯源 |
| `idx_source_receipts_recent` | 71.9 MB | 溯源 |
| `idx_source_receipts_code_lane` | 62.3 MB | 溯源 |
| `sqlite_autoindex_source_route_receipts_1` | 49.2 MB | 溯源 |
| `idx_source_receipts_lane_state` | 33.7 MB | 溯源 |
| `intel_snapshots` | 15.1 MB | 快照缓存 |
| `adjust_factors` / `ingest_watermark` / `instruments` / `trading_calendar` | 8.0 MB | 行情 |
| **合计** | **5,740.2 MB** | |

**溯源审计小计 2,569.0 MB = 44.8%。** 另外，`quotes_daily` 表体内部还有三个逐行溯源列——实测平均 `source` 3.14 B + `fetched_at` 19.0 B + `receipt_id` 31.97 B，含列头合计 **968.9 MB，占表体 35.6%**。而 `source` 的取值分布是 `tdx` 16,376,434 行（**96.5%**）、`tencent` 497,458、`baostock` 66,773、`sina` 24,545、其余 1,193 行——一个近乎常量的列，每行付 4 字节。

> 对照：`ChineseOSSQuant` 在 13,365,000 行合成数据上逐格式实测 B/行 —— 本仓现行 DDL **193.78**、精简 schema **69.96**、Hikyuu `H5Record` **40**、RQAlpha dtype **56**、WonderTrader `WTSBarStruct` **88**、Parquet+Zstd3 **19.29**。结论很清楚：**「SQLite 天生贵」只解释 1.75×，其余 2.77× 是我们自己 schema 造成的**（TEXT 主键 + 三列逐行溯源 + 二级索引）。

### 2.2 面板 8 列，公式 7 字段，AkShare 进链路 9 个

| 层 | 可见字段/接口 | 数量 |
|---|---|---:|
| `quotes_daily` 物理列 | trade_date, code, OHLC, volume, amount, outstanding_share, turnover + 3 溯源列 | 13 |
| `PANEL_FIELDS`（策略能拿到的） | open, high, low, close, volume, amount, turnover, outstanding_share | **8** |
| 公式 DSL 字段别名 | OPEN, HIGH, LOW, CLOSE, VOL, AMOUNT, HSL | **7** |
| 公式 DSL 函数 | REF/MA/EMA/SMA/WMA/DMA/SUM/HHV/LLV/STD/AVEDEV/COUNT/EVERY/EXIST/FILTER/BARSLAST/BARSSINCE/BARSCOUNT/HHVBARS/LLVBARS + TR/ATR/RSI/ROC/WR/CCI/OBV/MACD×3/BOLL×3 | 33，**截面算子 0 个** |
| akshare 顶层 callable（本机 1.18.56） | — | 1,093 |
| 其中 `stock_*` | — | 403 |
| 目录能发现的 | 只匹配 `stock_` 前缀 | 403（漏掉 690 个） |
| **真正进入数据链路的** | `stock_zh_a_hist`、`index_zh_a_hist`、`stock_info_sh/sz/bj_name_code`、`stock_board_industry_name_em`、`stock_board_industry_cons_em`、`stock_individual_fund_flow`、`stock_zh_a_spot_em` | **9** |

三道闸依次卡死：**接口没接（394 个）→ 接了也无处入库（无表）→ 入了库也进不了面板（`PANEL_FIELDS` 白名单）→ 进了面板公式也认不出（7 个字段别名）**。

> 顺带发现两个 bug 级事实：① `index_zh_a_hist` 在生产日线链路上被调用，却因不带 `stock_` 前缀被目录漏掉 —— `src/market/api/README.md:15` 的「目录即全部可用面」对指数不成立。② 本机 1.18.56 带着 `stock_zh_a_gbjg_em` 的分页截断 bug（`pageSize=20` 无循环，1.18.73 才修），另有 **40 个接口设了 pageSize 却无分页循环**，超出部分**静默丢失不报错**。

### 2.3 36 年历史，短线用得上的不到三成

| 区间 | 行数 | 占比 |
|---|---:|---:|
| 全库（1990-12-19 ~ 2026-08-25） | 16,966,403 | 100% |
| 2010 年前 | 3,305,994 | 19.5% |
| 2015 年前 | 5,746,560 | 33.9% |
| 2018 年前 | 7,611,125 | 44.9% |
| 2021 年前 | 10,133,182 | 59.7% |
| `market_hot.db` 窗口（近 700 交易日） | 3,748,806 | 22.1% |

热库已经在做 700 交易日（≈2.8 年）滚动窗口，说明「短窗够用」在读路径上**已经是既成事实**——但全量库仍保留全部 36 年且**没有任何保留策略**（grep 全仓：`market.db` 无 DELETE、无 VACUUM、无归档；只有 hot 的滚动窗口与 ops 的三段 prune）。

### 2.4 三处零覆盖

| 能力 | 实测状态 |
|---|---|
| 盘中/实时数据留存 | **零**。分钟线明确不落库（`GET /api/market/minute/{code}`），live 只有进程内 3–5 秒 TTL 缓存，`market.db` 里根本没有分钟/tick/盘口表（9 张表已穷举）。唯一在做快照的是 `intel_snapshots`（479 行 / 15.1 MB，且无 TTL） |
| 实验可复现 | **零落地**。`strategy_backtests` 0 行、`strategy_versions` 0 行；62 个研究脚本的结果散在 `output/` 的 22 个目录；`output/*/summary.json` 三缺二（有参数，无代码版本、无行情快照）；`candidate_reviews` 有 `strategy_revision` 但**没有 `market_revision` 列**。`src/research` 那套完备的 run card（`market_revision` + `input_sha256` + 冻结重放 + 状态机）**实测零使用**——`data/research_runs/` 只有 1 个含 3 条测试夹具的文件 |
| 加密设施 | **零**。`src/ai/infrastructure/crypto.py` 已被削成 9 行、只剩 `mask_secret()`；无 Fernet / AES / 主密钥 / SQLCipher；`.palace_ai_master_key`（46 B）是无人读取的死文件。唯一在用的加密是分享包的 `pyzipper` AES-zip |

另有存活偏差实锤：**`instruments.delist_date` 填充数 = 0**，`status` 分布 `delisted=1` / `normal=5546`。

---

## 3. 分层对标：六层能力成熟度

评级口径：**A** 达到或超过主流开源水准 / **B** 能用但有明确短板 / **C** 有雏形但不成体系 / **D** 缺失。

| 层 | 主流参照 | 主流的关键设计 | Loci 现状 | 评级 |
|---|---|---|---|---|
| **数据层** | Qlib `.bin`、Hikyuu HDF5、WonderTrader `.dsb`、RQAlpha bundle | 列存/定点整数（40–88 B/行）；按日期分目录做过期；`limit_up/limit_down` 当**行情字段**存 | SQLite 行存 193.78 B/行、逐行溯源占 44.8%、8 个面板字段、无涨跌停列、无分钟/tick、无保留策略 | **C** |
| **因子层** | alphalens-reloaded、Alpha158/360、WQ101 | 截面 `rank`/`Corr`/`Slope`/`Resi`/`Quantile`；IC / ICIR / 分组单调性 / 换手率自相关三件套；`max_loss=0.35` 强制报丢弃率 | 33 个纯时序算子，**截面算子 0 个**；策略吐布尔掩码不吐分数；从未算过一次 IC | **D** |
| **回测层** | zipline-reloaded、backtrader、Lean | 事件驱动 + 不可变 `Portfolio`/`Account`/`Position`；`VolumeShareSlippage` 成交量截断；两阶段除权除息 | 信号级逐笔 + MFE/MAE + T+1 + 一字板 + 26 bps 成本 + 双引擎一致性守卫 + 信号截断一致性测试。**A 股规则实现质量高于 backtrader**，但无成交量约束、无组合反馈 | **B** |
| **组合与风控层** | zipline `Portfolio`、Hikyuu 九件套 TM/MM/EV/CN/SG/ST/TP/PG/SP | 现金守恒、未实现盈亏逐日盯市、`order_target_percent`；**止损距离直接是仓位算法的 risk 入参**（`System.cpp:743`）；ST 可否决 SG 的买入（`:736`） | `research_portfolio` 有固定槽位账本，但 **`equity = cash + Σ 入场名义额`，未实现盈亏恒为 0**；策略协议只吐 signals+factors，**缺 ST/TP/PG/MM/TM 五件** | **C** |
| **执行/盯盘层** | vn.py Gateway/EventEngine/OmsEngine、Lean `RiskManagementModel` | 订单对象 + pre-trade 风控 + 回报 + 持仓同步 + 落库 | `paper_exec.py` 已有 `PaperOrder`（9 种 action）+ `validate_and_normalize_order`（8 类 pre-trade 检查，拒单落 `paper_rejects`）；二波盯盘已挂 `*/5 9-14 * * mon-fri`。**不接实盘是正确选择**，缺的是每段的可观测性 | **B** |
| **实验管理层** | Qlib `R` recorder + MLflow + `SignalRecord`/`SigAnaRecord`/`PortAnaRecord` | 一次实验记录代码版本、数据快照、参数、指标、产物；DSR/PBO 需要的 trial 序列全部留痕 | `src/research` 的 run card 设计**完备到超过 Qlib**（冻结重放 + hash 自校验 + 人工签署状态机），但**零落地**；生产侧 `strategy_backtests` 0 行、`optimize` 丢弃 trial 序列 | **D**（设计 A，落地 D） |

### 3.1 三个必须点破的反直觉结论

**① Qlib 的 `.bin` 不该抄。** 它是「每股票每字段一个文件」，因为它的并行模型是「一个 worker 一只票」（`qlib/data/data.py:548-598`，源码注释 `# One process for one task, so that the memory will be freed quicker.`）。取「某票全历史」= 1 次 seek；取「全市场某日截面」= **5,500 次 open + 5,500 次 seek**。而后者恰好是我们选股/回测 100% 的用例。实测官方 `qlib_data_cn_1d_latest` 解压 271.3 MB / 27,125 个 `.bin`；在 NTFS 上 44,000 个小文件内容 43 MB 却实占 195 MB。**方向相反，抄了是负担。**

**② Qlib 的 `Rank`/`Quantile` 是时序不是截面。** Alpha158 的 158 个特征**无一个截面算子**，截面只出现在 processors 与逐日 IC 里。真正的截面 `rank` 在 WorldQuant 101 那边。这个区分很重要——照抄 Alpha158 拿不到截面能力。

**③ `LOCI_MARKET_DUCKDB` 旁路接错了头。** 两个 agent 独立实测：走 `sqlite_scanner` 挂 `market_hot.db` 是 **2,040 ms**（另一次测到 5,404 ms，比裸 pandas 慢 2.9×），而改读 Parquet 是 **289 ms**。DuckDB 的价值在它自己的列存 reader，不在把它当 SQLite 的前置。**ADR-002 需要重新基准化。**

### 3.2 我们领先的地方（别在重构里弄丢）

| 项 | 主流开源的状态 |
|---|---|
| 信号截断一致性守卫（同一天算两遍，喂全历史 vs 喂到当天，必须完全一致） | Qlib / backtrader / vn.py **都没有**。这是防未来函数最有效的一条,且新策略自动纳入 |
| 逐条 receipt 记录 `source_url` / `payload_sha256` / `parser_revision` / `availability_status` | 开源量化系统里基本不存在 |
| run card 冻结输入 + hash 自校验 + replay 比对 + **强制人工签署**才能 completed | Qlib recorder 记录完整但**无签署门禁** |
| 「自动同步无法观察发布时间 → 一律写 `not_observed`，strict PIT 直接拒绝」 | 绝大多数系统把抓取时间冒充可见时间 |
| 面板合并成单块内存（实测 `shift(1)` 98.55 ms → 0.60 ms，164×） | 属于工程细节，多数框架没做 |

> **这五条是资产。** 后面所有改造都不能以牺牲它们为代价——尤其第 1 条：引入截面算子会天然违反它的**列**截断一致性，必须先把判据改成**行**截断（见 §5.3）。

---

## 4. 差距的真实形状

### 4.1 按「可修复性 × 收益」排序的落后项

| 落后项 | 现状 | 修复难度 | 修复后收益 | 优先级 |
|---|---|---|---|---|
| 盘中数据留存 | 零 | 低（无算法难点，纯工程） | **不可逆**——每天不做就永久少一天 | **P0** |
| 实验 trial 台账 | 表 0 行，序列丢弃 | 低（1 张表 + 2 处改） | 解锁 DSR/PBO 门禁 | **P0** |
| 存活偏差 | `delist_date` 全空 | 中（一次性约 1,300 次调用） | **在它修好前，任何组合层收益数字不可信** | **P0** |
| 组合 equity 口径缺陷 | 未实现盈亏恒 0 | 低（一个公式 + 8 条不变式） | 现有回撤数字全部要重算 | **P0** |
| 涨跌停字段缺失 | 按板块现算 | 低（2 列 + 一次回填） | 打板类回测不再系统性高估 | **P1** |
| 截面因子算子 | 0 个 | 低（16 个算子，实测 311 ms / +97 MB） | 从「布尔掩码战法」升级到「打分排序 Top-N」 | **P1** |
| 数据宽度（AkShare） | 面板 8 列 | 中（要建表 + 扩白名单 + 扩 DSL） | 让 394 个接口有处可去 | **P1** |
| 存储格式 | 行存 193.78 B/行 | 中（L1 Parquet 面板旁路） | 省 2.3 GB + 主查询 7.1× | **P1** |
| 组合层五件套（ST/TP/PG/MM/TM） | 缺 | 中高 | 直指「MFE 远高于净收益」这个系统性病 | **P2** |
| 上游漂移防线 | 8 种破坏模式覆盖 1.5 种 | 低（三个小函数） | 防静默错数据 | **P2** |

### 4.2 明确**不是**差距的（别浪费力气）

- **不换回测引擎。** 自测同机同数据：向量化 **13.63 ns/bar-asset-combo**（93 组 × 5,500 只 × 1,358 天 = 7.0 亿格，9.465 秒），剥光的事件循环 **325.86 ns/bar-asset**，差 **24×**（且这是事件驱动的**下界**，没有 Order 对象、没有事件分发、没有 ledger）。七条缺口里五条发生在信号**之后**，换引擎解决不了；且**分钟线不落库**，事件驱动最值钱的能力（部分成交/订单簿/盘中触发）在本机**无数据可喂**。正确做法是**向量化选股 + 事件驱动组合层**两段式。
- **不换交易日历。** `exchange_calendars` **根本没有 XSHE**（实读文件树 + 注册表确认），XSHG 的 docstring 明说「no known early closes」，预计算只到 2026-10-07。我们「有行情=交易日」在半天/临时休市上**反而更强**。改为加一个只读 `audit_calendar` 对账闸即可。
- **不碰机器学习那一层。** Qlib 官方 benchmark：Alpha158 上 Linear IR **0.9209** vs LightGBM **1.0164**（线性拿到九成）；而 Alpha158→Alpha360 的特征差异让同一个 MLP 年化从 **8.95% 掉到 0.29%**、Transformer **−2.70%**、TabNet **−3.69%**。这些数还是持 50 只的口径，我们持 3–10 只。**性价比不成立。**
- **不引组合优化库。** 均值方差在 N=10 时要估 65 个参数，DeMiguel-Garlappi-Uppal (2009) 给出的样本需求是 3000/6000 个月；HRP 解决的病态问题在小 N 下不存在；风险平价等于偷偷加回**已被本仓明确拒绝**的低波因子；cvxpy 还带编译依赖。替代方案在 §8。
- **不引 MLflow。** 服务器只剩约 1.1 GB 可用内存；一个 `manifest.json` + 一张表就够。
- **不引 SQLCipher。** `sqlcipher3-binary` 0.4.0→0.6.0 全量扫描 **零 Windows wheel**，`pysqlcipher3` 仅 sdist 且 2023-01-29 后停更——而我们发的是 PyInstaller 打的 Windows exe。
- **不接那 183 个逐票循环接口的大部分。** 它们是配额陷阱，日线上已经付过一次学费。

---

## 5. 诉求一：AkShare 怎么才算「用起来」

### 5.1 先认清损失的形状

`AkShareSurface` 把 403 个 `stock_*` 按「有无历史」逐个填完（90 个价值接口，无一空缺）：

| 类别 | 数量 | 含义 |
|---|---:|---|
| `H全` 全历史可回溯 | 45 | 什么时候接都不晚 |
| `H窗` 有限窗口 | 6 | 越界静默返空 |
| `H近` 只承诺「近期」 | 7 | 不可假设深度 |
| `H冻` 已冻结停更 | 2 | 死数据 |
| **`S今` 只有当天快照** | **21** | **不自存就永久丢失** |
| `S期` 只有最新一期 | 3 | 同上 |

**21 + 3 = 24 个接口的历史，只能由我们自己每天落盘产生。** 而按调用模式分类，403 个接口里有 **51 个是「按日/事件驱动」**——接入成本最低（一天一次、全市场单表、无 py_mini_racer、稳定性风险低），涨停池 6 个 + 龙虎榜 + 停复牌 + 两融明细 + 大宗交易全在这批里，且全是 P0。**「该用的没用起来」主要指的就是这 51 个。**

### 5.2 三个必须知道的坑（都有硬证据）

1. **涨停池 6 个接口只承诺「近期数据」**，官方文档全站「历史数据从」出现 0 次。越界时 `data_json["data"] is None` → **静默返回空 DataFrame**，回测会读成「那天没有涨停股」。**这是最危险的一条。**
2. **PIT 的正确锚点是 `stock_yysj_em.实际披露时间`（20081231 起），不是 `stock_yjbb_em.最新公告日期`**——后者会被重述前移，系统性低估当时可见性。
3. **`stock_info_sh_delist` 把上游 `DELIST_DATE` 重命名成「暂停上市日期」——列名是错的、值是退市日**（`COMPANY_STATUS=3` 即终止上市）；且 `pageHelp.pageSize=500` 单页无循环。要修存活偏差就得用它，但不能信它的列名。

另：`docs/quant-toolkit.md:499` 说 `stock_info_a_code_name` 依赖 py_mini_racer —— **1.18.56 源码已改为拼接三所列表 + `@lru_cache`，无 JS 引擎**，上游采纳了本仓当年的绕行方案。这条文档要更正。

### 5.3 三层落地（顺序不能颠倒）

```
第 0 层：管道           第 1 层：接入       第 2 层：进面板
──────────────────         ──────────────                ──────────────
① 快照落盘设施（§7）    → ⑤ 51 个按日/事件接口     →    ⑧ 扩 PANEL_FIELDS
② 扩 quotes 派生表           ⑥ 修存活偏差（4 步）      ⑨ 扩公式 DSL 字段别名
③ 16 个截面算子          ⑦ 补 PIT published_at   ⑩ 扩 DSL 截面函数
④ guard 判据改行截断
```

- **第 0 层不做，第 1 层全是白干**——数据落进来无处可去。
- **③④ 是一对**：截面算子天然违反 `guard_strategy` 的**列**截断一致性（少一列会改变全市场排名），必须先把判据改成**行**截断。这是唯一有架构成本的一处。
- **⑧⑨⑩ 有现成钩子**：`screen_rank_factor` + `picks_on(rank_by=)` 已经存在，`qianlong.py` / `tail_resonance.py` 已经在用 `rank(axis=1)` 做 Top-N。**S4 那一步可以零业务改动拿到现役战法评分的第一个 IC。**

### 5.4 上游漂移防线：8 种破坏模式覆盖 1.5 种

近 12 个月 AkShare 发了 **273 个版本**（1.32 天/版），98.2% 带 `fix` 前缀，**132 个版本点名 A 股接口、76 个不同接口被动过，官方改名 0 次、文档化删除 0 次**。

| 破坏模式 | 现有防线 | 判定 |
|---|---|---|
| 版本落后 | `check_akshare_version` | 覆盖，但**无任何门禁** |
| 必填列消失 | `source_contract` → `NormalizeError` | 半覆盖——**被 `router.py:204-207` 的 `except Exception` 吞成静默降源** |
| 选填列改名 | — | 裸奔 |
| 列名微调 | — | 裸奔 |
| **值语义变更** | — | 裸奔。1.18.73 第 14 条「修复 `stock_zh_a_hist_tx` 的成交量/换手率/成交额字段语义」= **列名不动、数值口径全变**，`source_contract` 100% 抓不到 |
| 分页截断 | — | 裸奔（40 个接口） |
| **静默删除** | — | 裸奔。`stock_hot_rank_wc` 被「修复」6 次后消失，**changelog 里删除记录 0 条**——AkShare 删接口不写 changelog，这是制度性的 |
| 接口新增 | — | 无感知 |

三个小函数能补上大半：**列名基线比对**（每次探测把实际列名存进基线，变了就告警）、**契约失败不静默降源**（`NormalizeError` 单独 catch 并计数）、**接口存在性冒烟**（每周对已接接口跑一次 `hasattr`）。

---

## 6. 诉求二：历史数据瘦身

### 6.1 「到底要几年」——实测给出分裂的答案

在生产库 **10,290,060 条样本 / 4,037 个交易日**上实测（2010 起，剔停牌与异常，成交额 ≥3,000 万）：

- **超额口径的截面残差 σ**，2010–2026 四段只在 **4.75%–5.35%** 抖动 → **测 alpha，3–5 年够。**
- **总收益 σ**，2015 年是 2017 年的 **1.98 倍** → **测回撤，必须留极端年份。**
- 但那些年份带**双重存活偏差**：2015 年可交易票只有 2,082 只 vs 今天 5,018，且 `delist_date` 填充数为 0 → **本地的极端年份数据不可信。**

还要除设计效应：同日信号共享市场因子，实测 **ICC = 0.2822**。代入本仓两个战法：

| 战法 | 笔数 | k（信号/日） | deff | **N_eff** | t（超额） | 判定 |
|---|---:|---:|---:|---:|---:|---|
| 潜龙原版 | 24,878 | 39.6 | 11.9 | **2,090** | **2.13** | ✗ 不显著 |
| 分手快乐 | 495 | 1.2 | 1.06 | **466** | **3.14 / 3.80** | ✓ 显著 |

**24,878 笔的那个不显著，495 笔的那个显著。** 这条比任何「要几年历史」的讨论都重要——**样本大不等于结论强，日均信号数才是分母。**

### 6.2 结论：不删年份，换格式

同一份真实 16,966,403 行导出实测：

| 格式 | 体积 | 倍数 |
|---|---:|---:|
| SQLite 现状（表体 + 全部索引） | 4,196.9 MB | 1.0× |
| DuckDB 原生 | 671.4 MB | 6.3× |
| Parquet + Snappy | 484.7 MB | 8.7× |
| **Parquet + Zstd-3（date-major）** | **395.6 MB** | **10.6×** |
| Parquet + Zstd-3，按年 hive 分区 | 410.8 MB | 10.2× |
| Parquet + Zstd-9 | 385.0 MB | 10.9× |

**去掉三个溯源列在 Parquet 里只省 0.6 MB**——溯源开销是**行存的产物**，不是数据成本。

主查询实测（全市场 × 最近 250 交易日 = 1,365,143 行）：

| 路径 | 耗时 |
|---|---:|
| DuckDB ← 按年分区 Parquet | **289 ms** |
| DuckDB ← 单文件 date 排序 | 326 ms |
| DuckDB ← 单文件 **code 排序** | **1,554 ms** ← 压缩最优的排序，查询最慢 |
| DuckDB ← `sqlite_scanner` 挂 `market_hot.db`（**本仓现状**） | 2,040 ms |
| pandas ← `market.db` | 2,732 ms |

**分区必须 date-major。** 这条会被拍脑袋拍反。

### 6.3 六层保留方案

| 层 | 内容 | 保留 | 格式 | 体量 |
|---|---|---|---|---:|
| **L0 权威** | `quotes_daily` + `adjust_factors` + `instruments` + `trading_calendar` | 全量永久 | SQLite（不动） | 2.73 GB |
| **L1 面板**（新） | L0 的 OHLCV+换手+股本，按年分区 | 全量永久 | Parquet+Zstd3，date-major | **411 MB** |
| **L2 溯源** | receipts / attempts + 索引 | 近 24 个月留 SQLite，更早导出 Parquet 后删 | Parquet+Zstd3 | 2,569 MB → **约 300–400 MB** |
| **L3 热窗** | `market_hot.db` | **删除，由 L1 取代** | — | **−1,022 MB** |
| **L4 盘中留存**（新） | 见 §7 | 滚动 60 交易日 | 加密 Parquet，按天分目录 | +2.03 GB |
| **L5 可重建缓存** | `intel_snapshots` 等 | 随时可清 | — | 15 MB |
| **L6 运维留痕** | `job_runs` 等 | 现有 `MANAGED_PRUNE` | SQLite | 13.8 MB |

**净效果：`market.db` + `market_hot.db` 从 6,762 MB → 约 3,200 MB，另加 411 MB 的 L1，总盘子 6.76 GB → 约 3.6 GB，主查询快 7.1 倍，一年历史都没删。** 加上 L4 的 2.03 GB 盘中数据后仍低于今天。

L2 那一行的算式（避免过度承诺）：`idx_quotes_receipt` 直接 DROP 省 **1,049.0 MB**（它只服务「按回执反查日 K」这一个低频运维查询）；6 个 receipts/attempts 索引随表收缩；两张表按 10.6× 导出 Parquet 约 111 MB。**保守估计省 2.2 GB，精确值需实跑，本轮未实跑。**

### 6.4 两个静默失效陷阱（实测复现，仓库文档没记）

1. `PRAGMA journal_mode=WAL` 排在 `auto_vacuum` **之前**，会让后者**静默变 0**。
2. Python 里 `PRAGMA incremental_vacuum` **不 `.fetchall()` 等于没执行**（实测 102.5 MB 纹丝不动 vs 正确执行的 51.3 MB）。

**这也是为什么滚动窗口推荐按天分目录而不是 SQLite DELETE**：删 30 天 **0.011 秒**、零碎片、无 2× 磁盘峰值。

---

## 7. 诉求三：加密留存 30–60 天

### 7.1 存什么（按「价值 / 存储代价」排序，60 交易日）

| 排名 | 数据 | 60 日代价 | 不可重建 | 判定 |
|---:|---|---:|:---:|---|
| 1 | **涨停/炸板事件流** | **0.42 MB** | ✓✓ | **必存。** 连板梯队、首封时间、炸板次数、封单额、回封标签——A 股短线的核心状态量，**日 K 里一个都没有**。代价小到不值得讨论 |
| 2 | 龙虎榜 | 1.08 MB | ✗ | **必存**（1 MB，存了省事） |
| 3 | 板块/概念资金流（5 分钟） | 43.9 MB | ✓✓ | **必存。** 盘中快照过期即失，第三方不回补 |
| 4 | **集合竞价逐笔（9:15–9:25，3 秒）** | **654.2 MB** | ✓✓✓ | **必存，全表不可逆性最高。** 9:15–9:20 可撤单段的撤单行为、9:20 后的真实意愿、尾秒抢筹——**9:25 一到，这段数据在所有免费源上彻底消失**。AkShare 全库无第二个入口（grep「集合竞价」= 0），东财 `trends2` 的 `ndays` 上限是 5 |
| 5 | 全市场分钟 K | 1,059.8 MB | ✗ | **建议存**。可回补，但每次回补是 5,500 次远程请求 |
| 6 | 全市场 spot 快照（5 分钟，9 列） | 269.0 MB | ✓ | **建议存**。5 分钟是甜点；市场宽度时间序列、涨速榜、盘中最低/最高路径 |
| — | **合计 1–6** | **2,028.4 MB ≈ 2.03 GB**（加密后 +55 KB） | | |
| 8 | spot + **五档**，1 分钟 | 6,866 MB | ✓ | **不建议**。免费源的五档是 L1 最优五档快照不是 L2 委托流；能看到的封单信息第 1 项已用 0.42 MB 给了——**16,000 倍代价换重复信息** |
| 12 | 全市场 3 秒快照 | 21,588 MB | ✓ | 不建议。无 L2 配合时对 1–5 日策略没有可验证的增量 alpha |

**同一份数据存 SQLite 要 5.6–5.7 倍**：分钟 K 变 6,070 MB、3 秒快照变 121 GB。**行存把这件事从「能做」变成「不能做」。**

### 7.2 怎么存

- **存原始 DataFrame，不存归一后的结果。** `pipeline.normalize` 对选填列缺席是**静默丢列**（`pipeline.py:72`）、对无法解析的值是 `to_numeric(errors="coerce")` **静默变 NaN**（`pipeline.py:52`）。快照的价值在于「当时上游到底返回了什么」，归一会把证据抹掉。
- **每份快照带三个元数据**：`akshare.__version__`、抓取时刻、**本次返回的列名列表**。第三项同时就是 §5.4 的漂移基线。
- **独立于 `market.db`**，按天分目录：

```
<data_dir>/tape/
  2026-08-25/
 auction_3s.parquet.enc    # 集合竞价逐笔
    spot_5m.parquet.enc       # 全市场 spot 5 分钟断面
    minute_1m.parquet.enc         # 全市场分钟 K
 limitup_events.parquet.enc    # 涨停/炸板事件流
    sector_flow_5m.parquet.enc    # 板块/概念资金流
    lhb.parquet.enc       # 龙虎榜
    manifest.json   # 明文：akshare 版本 / 抓取时刻 / 各文件列名与行数 / sha256
  2026-08-26/
  ...
```

- **过期 = 目录级 `unlink`**（实测删 30 天 0.011 秒）。挂进现有 `MANAGED_PRUNE`，**不需要新建任务类型**。
- **三道安全闸门**：只删 `tape/` 下匹配 `^\d{4}-\d{2}-\d{2}$` 的目录、只删早于 `today - retention_days` 的、单次删除上限。

### 7.3 加密方案：单一推荐

> **DuckDB 1.5.5 原生 Parquet Modular Encryption（`AES_GCM_V1`，256-bit）+ 每库一个随机 DEK + Windows DPAPI（带 entropy）包裹 DEK。**
> **L0 权威库与 L1 面板不加密**（可重建、无隐私、加密只会挡住排障）。

选它的实测理由：

| 候选 | 判定 | 依据 |
|---|---|---|
| SQLCipher | **出局** | `sqlcipher3-binary` 0.4.0→0.6.0 **零 Windows wheel**；`pysqlcipher3` 仅 sdist、2023-01-29 停更。我们发 PyInstaller Windows exe |
| SQLite SEE | 出局 | 商业许可（$2,000 档），闭源 |
| Fernet | 出局 | 实测 **+33.33% 体积**、AES-128、无 AAD |
| 应用层逐 blob AES-GCM | 可行但次优 | 「能加密的是 value，不能加密的是你要 WHERE 的那列」——要维护明文索引列，复杂度高 |
| **Parquet Modular Encryption** | **✅ 采纳** | A/B 实测主查询 **343 ms vs 明文 354 ms（无劣化）**、体积 **0.977×**、**无密钥硬失败**、保留列裁剪与谓词下推、**零新增依赖**（duckdb 已在 `requirements.txt`） |

**威胁模型（必须写清，否则又是一次自欺）**：
- **防**：设备失窃 / 硬盘被拆 / 未加密备份泄露 / 误发到云盘 / 分享包误带盘中数据。
- **不防**：本机已登录用户的进程（DPAPI 按用户解密，同用户任何进程都能读）、内存 dump、有 root/管理员的攻击者。
- **为什么 `.palace_ai_master_key` 那次失败不会重演**：① 那次是**主密钥明文躺在被加密数据旁边**，等于没加密；这次密钥进 DPAPI，与密文**不在同一爆炸半径**。② 那次加密的是 LLM Key，一旦解不开**功能直接不可用**，于是被迫回退明文；这次加密的是**可重建的盘中缓存**，解不开最坏是丢 60 天快照，不阻断任何主体功能。**「加密的对象能不能丢」是这两次决策的分水岭。**

### 7.4 与既有铁律的冲突检查

| 铁律 | 冲突？ | 说明 |
|---|---|---|
| `market` 不写 `palace.db` | 否 | `tape/` 是独立文件目录，不进任何 db |
| 「是否入库」决策表 | 否 | 盘中快照属「默认不落库；重算贵再缓存」——但它**重算不了**（永久丢失），因此升格为「必须留存的可重建缓存」，且**整目录可删** |
| 秘密不上库 | 强化 | DEK 不进任何 db、不进配置文件、不进分享包 |
| 单文件 ≤600 行 | 需注意 | 新增落盘模块要拆成 `tape_writer` / `tape_reader` / `tape_prune` 三个文件 |
| 分享包「一键打包」 | **需改** | 必须**默认排除** `tape/`，否则加密白做（换机后 DPAPI 也解不开，只会变成一堆废字节） |

---

## 7.5 落地进度（2026-08-25 当日）

报告写完当天就动了手，0–30 天那批里已完成 4 项，实测结果与预测的偏差写在这里：

| 路线图项 | 状态 | 实测 vs 预测 |
|---|---|---|
| #2 `DROP INDEX idx_quotes_receipt` | ✅ 已上 | 预测省 1,049 MB，**实际释放 1,567.9 MB**（VACUUM 顺带回收了 256,107 个已存在的空闲页）。5,740.2 → 4,172.3 MB，`quick_check` 通过、1,697 万行一行不少 |
| #3 修 `research_portfolio` equity 口径 | ✅ 已上 | 未采用「换算法」，采用**如实披露 + 保守上界**：新增 `metrics.assumption`（`equity_basis="cost_until_exit"`）与 `mae_bound_max_drawdown_pct`，并把现金守恒做成会抛错的不变式 |
| #1 每日盘中快照 | ✅ 已上（第一批） | 5 个数据集落盘，**0.40 MB/日**，比预测的 <2 MB/日 还小。托管任务工作日 15:35，过期删除挂进既有 `prune` |
| 加密（原排 30–60 天 #12） | ✅ 提前 | DuckDB Parquet Modular Encryption + DPAPI，实测无密钥/错密钥均硬失败 |
| #6 文档更正 | ✅ 已上 | `quant-toolkit.md` 的 2.4 GB、py_mini_racer 两处已改 |

两处**预测被实测推翻**，已改进设计：

1. **`idx_quotes_receipt` 不能无条件删。** 报告说它「只服务一条低频运维查询」，
   实际上热库 `_purge_orphan_receipts` 的 `NOT EXISTS` 逐行探测**真的靠它**。改成
   按库区分：schema v8 起权威库不建、热库建（`keep_receipt_index`）。
2. **分享包不用改。** ADR-014 原本把「默认排除 `intraday/`」列为唯一必须同批改的既有
   功能，实测 `build_share_pack` 是白名单，本来就进不去。改为加测试锁住该性质。

一处**上游现实**：`stock_zh_a_spot_em` 与 `stock_sector_fund_flow_rank` 当日持续
`RemoteDisconnected`（重试 3 次仍失败）。前者已回退到本仓 `fetch_spot_routed` 多源路由
（代价是 8 列而非 23 列），后者当日未采到并如实记进 `failures`——这正是 §5.4「8 种破坏
模式只覆盖 1.5 种」的日常形态。

## 8. 路线图

> 每项带**验收门禁**。没有门禁的条目一律不排期。

### 0–30 天：止血 + 不可逆的先做

| # | 动作 | 验收门禁 |
|---:|---|---|
| 1 | **开始每日快照 §7.1 的 1–3、6 项**（事件流 / 龙虎榜 / 板块资金 / spot 5 分钟断面），先明文落 `tape/`，加密随后补 | 连续 5 个交易日无缺日；`manifest.json` 三字段齐全；单日体积 < 10 MB |
| 2 | `DROP INDEX idx_quotes_receipt` | `market.db` 减少 ≥1,000 MB；`pytest tests/market -q` 绿；按回执反查日 K 的运维查询仍可用（允许变慢） |
| 3 | **修 `research_portfolio.py:367` 的 equity 口径**，补 8 条不变式（I1 现金守恒 … I8 T+1） | 新增单测：任一时点 `equity == cash + Σ(持仓数量 × 当日收盘)`；历史「−37.55% 回撤」重算并在文档中更正 |
| 4 | **trial 台账**：`optimize` / `compare` 每条 trial 的收益序列落 `strategy_backtests` | `strategy_backtests` 行数 > 0；能对一次已跑过的网格算出 PBO |
| 5 | 修存活偏差第一步：用 `stock_info_sh_delist` / `stock_info_sz_delist` 回填 `delist_date`（**注意列名是错的，值才是退市日**） | `delist_date` 覆盖率 ≥ 95%；`status='delisted'` 数量从 1 变成三位数 |
| 6 | 更正 `docs/quant-toolkit.md`：2.4 GB → 5,740.2 MB；`stock_info_a_code_name` 的 py_mini_racer 说明已过时 | 文档与实测一致 |

### 30–60 天：把管道打通

| # | 动作 | 验收门禁 |
|---:|---|---|
| 7 | **L1 Parquet 面板旁路**（按年 hive、date-major），选股/回测读路径切过去 | 主查询 ≤ 400 ms（现状 2,040 ms）；与 SQLite 逐值 parity 测试通过 |
| 8 | **删 `market_hot.db`**，由 L1 取代 | 磁盘 −1,022 MB；选股端到端不慢于现状 |
| 9 | **16 个截面算子** + `guard_strategy` 判据改行截断 | 700×5547 面板上 `rank(axis=1,pct=True)` ≤ 400 ms；截断一致性守卫在**行**维度仍然红/绿正确 |
| 10 | **`factor_report`**：IC / ICIR / 分组单调性 / rank autocorr / 换手 | 对现役战法的 `screen_rank_factor` 跑出第一份 IC 报告 |
| 11 | 接 51 个「按日/事件驱动」接口里的 8 个 P0：涨停池 4 个 + 龙虎榜 + 停复牌 + 两融明细沪深 | 每日 8 次调用；**涨停池必须显式处理 `data is None` → 不得静默返回空表** |
| 12 | 加密落地（Parquet Modular Encryption + DPAPI）；分享包默认排除 `tape/` | 无密钥读取硬失败；主查询相对明文劣化 < 5%；分享包解出来不含 `tape/` |
| 13 | `quotes_daily` 加 `limit_up` / `limit_down` 两列并回填 | 打板类回测的「一字板买不进」判定改用字段而非板块规则；差异样本数落文档 |

### 60–90 天：把结论变可信

| # | 动作 | 验收门禁 |
|---:|---|---|
| 14 | **DSR / PBO 门禁**（stdlib `NormalDist` + `math.erf`，零新依赖） | 复现论文算例（N=100 → 0.9004、N=46 → 0.9505）；对已有网格算出 PBO 并纳入 CI 报告 |
| 15 | **22 条因子门禁数值化**：`tot_loss ≤ 0.35`、`delist 覆盖 ≥ 95%`、`Rank ICIR ≥ 0.30`、`NW t ≥ 3.0`、`Q5−Q1 净夏普 ≥ 0.5`、`0.60 ≤ rank autocorr ≤ 0.99`、`DSR ≥ 0.95`、`PBO ≤ 0.25`、单立项参数组合 ≤ 200 | 写成断言；新因子不过关不得注册为活动战法 |
| 16 | **L2 溯源分层**：近 24 个月留 SQLite，更早导出 Parquet | 省 ≥ 2.0 GB；导出后仍可按 receipt_id 查到（允许变慢） |
| 17 | **策略协议补 `exit_rule()` / `position_sizer()` 两个可选声明**；逐笔记录加 `exit_reason` 列 | `exit_reason` 分布可出表——**这是成本最低、信息量最大的一步**，直接量化「浮盈为什么没拿住」 |
| 18 | PIT：接 `stock_yysj_em.实际披露时间`，把 `published_at` 从恒空改成公告日 | `strict_pit=true` 的回测从「全量拒绝」变成「日级 PIT 可用」 |
| 19 | 上游漂移三道防线：列名基线比对 / 契约失败不静默降源 / 接口存在性冒烟 | 人为改一个列名，CI 必须红 |
| 20 | **`loci-experiment-manifest-v1`** 落地（代码 commit + `market_revision` + 参数 + 种子 + 环境 + 结果指纹） | `output/` 下新产物 100% 带 manifest；能从 manifest 重跑出同一结果 |

---

## 9. 明确不做

| 不做 | 理由（一句话，全部有实测或一手依据） |
|---|---|
| 换事件驱动回测引擎 | 向量化快 24×，七条缺口里五条在信号之后，且分钟线不落库时事件驱动无数据可喂 |
| 抄 Qlib `.bin` | 「每票每字段一文件」对「全市场某日截面」是最差布局，而那是我们 100% 的用例；NTFS 上 44,000 个小文件 43 MB 实占 195 MB |
| 抄 Qlib Disk 缓存 / `eval` 表达式引擎 | 要 Redis；`eval` 在安全/性能/防前视三方面都是倒退 |
| 换 `exchange_calendars` | **它根本没有 XSHE**；我们「有行情=交易日」在半天/临时休市上更强 |
| 引 MLflow / W&B / DVC | 服务器只剩 1.1 GB 内存；一个 manifest + 一张表够了 |
| 引 riskfolio-lib / PyPortfolioOpt / cvxpy | 小 N 短持有下均值方差/HRP/风险平价都不成立，风险平价还偷偷加回已被拒绝的低波因子 |
| 引 quantstats | 按周期非按笔的口径与本仓全部研究文档冲突；只抄 PSR 与 smart sharpe 两个指标 |
| 引 ArcticDB | BSL 1.1：生产/商用需付费许可 |
| 引 ClickHouse | 常驻服务端，与「单机桌面 + 双击 exe」形态根本冲突 |
| 引 SQLCipher / SEE | 零 Windows wheel / 商业许可 |
| 上 LightGBM / MLP / Transformer 那一层 | Qlib 官方 benchmark：线性拿到 LightGBM 九成 IR；深度模型换个特征集年化从 8.95% 掉到 0.29%~−4.65% |
| 接 183 个逐票循环接口的大部分 | 配额陷阱，日线上已付过学费 |
| 存 L2 五档 / 3 秒快照 | 16,000 倍代价换重复信息；无真 L2 委托流时对 1–5 日策略无可验证增量 alpha |
| 恢复 analyze/fetcher/reporter 旧链 | 项目铁律 |

---

## 10. 证据分册

| 分册 | 行数 | 核心交付 |
|---|---:|---|
| [`_scratch_2026-08-qb-our-system.md`](./_scratch_2026-08-qb-our-system.md) | 585 | 本仓只读审计：能力面 / AkShare 三分类（9 用 / 395 未用 / 690 不可见）/ 数据体量 / 分钟线与实时 / 加密盘点 / 可复现性 / 依赖 |
| [`_scratch_2026-08-qb-qlib.md`](./_scratch_2026-08-qb-qlib.md) | 730 | Qlib 源码级拆解（锁 commit `79633dd9`）：`.bin` 二进制回环实测、表达式引擎、Alpha158、PIT、workflow recorder、TopkDropout |
| [`_scratch_2026-08-qb-cn-oss.md`](./_scratch_2026-08-qb-cn-oss.md) | 549 | 7 个中文开源系统对比 + 六格式 B/行实测 + 分钟/tick 体量算式 + Hikyuu 九件套 + A 股约束 8×7 对照 |
| [`_scratch_2026-08-qb-backtest-engines.md`](./_scratch_2026-08-qb-backtest-engines.md) | 1,215 | 向量化 vs 事件驱动自测（24×）、组合层 4 对象 + 8 不变式、zipline 滑点模型考据、DSR/PBO 公式与数值验证 |
| [`_scratch_2026-08-qb-factor-stack.md`](./_scratch_2026-08-qb-factor-stack.md) | 860 | alphalens 逐行拆解、16 个缺失算子表、截面改造 5 步、22 条数值门禁、ML 与组合优化的否定结论 |
| [`_scratch_2026-08-qb-storage-encryption.md`](./_scratch_2026-08-qb-storage-encryption.md) | 783 | 九格式实测体积、分区策略实测、统计功效表、加密方案横向对比与单一推荐、滚动窗口四模式、盘中留存 12 行价值表 |
| [`_scratch_2026-08-qb-akshare-surface.md`](./_scratch_2026-08-qb-akshare-surface.md) | 644 | 403 个 `stock_*` 全景、90 行价值排序表（有无历史列无空缺）、**24 个必须自存的接口**、伪历史陷阱、调用模式分类、changelog 12 个月统计、8 种破坏模式覆盖评估 |
| [`_scratch_2026-08-qb-live-ops.md`](./_scratch_2026-08-qb-live-ops.md) | 601 | 实盘最小骨架 9 段、22 项 pre-trade + 9 条看板风控、`loci-experiment-manifest-v1` JSON Schema、18 条静默失败检查、19 条入库断言 |

**读法**：想知道「为什么这么判」看分册；想知道「做什么」看本文 §8。分册里的数字带证据分级（P1 源码逐行 / M 本机实测 / M\* 主 agent dbstat / P2 多源互证 / ✗ 未核验），**标 ✗ 的不得当结论引用**。

---

## 11. 本轮的边界

- **未联网调用任何 AkShare 数据接口**（避免消耗第三方配额与封 IP）。所有「实际返回多少行/历史多深」均为源码或官方文档口径。
- **未改任何生产代码、未改任何数据库、未 commit**。本轮只新增 8 篇分册 + 本文。
- 三项**落地前必须实测**：东财是否保留退市股日 K（备选：通达信本地 vipdoc，零配额，`tdxpy` 已在依赖里）；`stock_zh_a_hist_min_em` 5/15/30/60 分钟的真实历史深度；L2 溯源导出 Parquet 的精确节省值。
- 本仓已装但**未声明且零 import** 的 `scipy 1.17.1` / `scikit-learn 1.9.0` / `vectorbt 1.1.0` / `numba 0.66.0` —— 要么声明并用起来，要么从环境里清掉，不要留着当薛定谔依赖。实装 `pandas==3.0.5` 而声明只写 `>=2.0.0`，也该收紧。
