# 我们到底有什么：Loci / stock-analyzer 本仓只读审计（scratch）

> **日期**：2026-08-25 ｜ **审计对象**：`E:/my_space/stock-analyzer` 工作树当前状态（未锁 commit，本轮未做任何 git 查询）
> **用途**：回答「我们到底有什么、AkShare 到底哪些用起来了哪些没有、数据到底多大」。**这是台账不是结论文档**——供上层方案（存储加密留存 / 回测引擎选型 / 盘口快照留存）直接引用数字。
> **范围**：**只读**。除本文件外未改任何仓库文件，未 commit / push，未写任何数据库。所有 SQLite 连接一律 `file:...?mode=ro` URI + `PRAGMA query_only=1`。未跑 pytest / ruff / lint-imports / 前端构建。**未对 AkShare 发起任何联网试跑**，只做 `vars(akshare)` 本地反射。
> **证据分级**：`E1` 本轮亲自执行并贴出输出（SQLite 查询 / Python 反射 / pip freeze）；`E2` 仓内代码原文（给 `文件:行号`）；`E3` 仓内文档自述（可能过期，逐处标注）。
> **与主 agent 的关系**：§3 的 dbstat 分解由主 agent 先行实测（2026-08-25）。本轮**独立重跑并逐项复核，全部数字逐位一致**，故一律标 `E1`。
> **未登记 `INDEX.md`**：按只读约束，本轮不改除本文外的任何文件（含索引）。需要登记时由后续批次补。

---

## 0. 七个问题的一句话答案

| # | 问题 | 答案 |
|---|---|---|
| 1 | 有哪些能力 | **11 个限界上下文**对外暴露 **9 组 HTTP 前缀 + 5 个 CLI + 16 种 Job kind**；测试 ≥200 个文件，覆盖极不均衡（ops 73 / market 49 vs research 5、formula 2） |
| 2 | AkShare 用了多少 | 装了 **1.18.56**，顶层 `akshare.*` callable **1093** 个。真正进数据链路的 **9 个**（0.8%）；目录能看见但没人调的 **395 个**；目录**根本发现不了**的 **690 个**——其中 `index_zh_a_hist` **正在生产里被调用** |
| 3 | 数据多大 | 真实数据目录 `E:\entertainment_software\Loci\data`（仓库里的 `data/market.db` 是 0 字节空壳）。`market.db` **5,740.2 MB**，其中 **44.8% 是溯源审计元数据**，不是行情。`quotes_daily` 16,966,403 行 / 5,547 只 / 1990-12-19~2026-08-25。**market.db 无任何 TTL / 清理 / 归档** |
| 4 | 分钟线与实时 | 分钟线**不落库**（`market.db` 里根本没有分钟表）；`live_tape` 只存**进程内 3 秒**、只有 4 个指数。**盘中快照留存设施：零** |
| 5 | 加密设施 | `crypto.py` 已被削成 **9 行、只剩 `mask_secret()`**。无 Fernet / 无 AES / 无主密钥 / 无 SQLCipher。文档说的「LLM key 迁回明文」**核实属实**。唯一在用的加密是分享包的 pyzipper AES-zip。**加密留存要从零建密钥管理** |
| 6 | 可复现性 | 建了一套很完整的 run card（`market_revision` + `strategy_revision` + `input_sha256` + 冻结重放），但**实测零 run card**、`strategy_backtests` 0 行。实际出结论的 `output/*/summary.json` **只记参数，不记代码版本和行情快照** |
| 7 | 依赖 | 声明里量化相关只有 **pandas / numpy / duckdb / polars**。scipy / scikit-learn / vectorbt / numba **装了但没声明、且全仓零 import**；**statsmodels 没装**。实际 `pandas==3.0.5`（声明只写 `>=2.0.0`） |

---

## 1. 能力面盘点

### 1.1 限界上下文 → 对外能力 → 入口 → 测试覆盖

来源：`src/*/README.md` 与 `src/*/api/README.md` 的「归属 / 挂载 / 关键入口」段（`E3`），入口符号与 Job 注册表为 `E2`，测试文件数为 `E1`（`glob tests/**/test_*.py`）。

| 上下文 | 对外能力（HTTP 前缀） | 非 HTTP 入口 | 可写库 | 测试目录 | 文件数 | 覆盖判断 |
|---|---|---|---|---|---:|---|
| `market` | `/api/market/*`、`/api/universe/*` | `MarketStore` / `sync_quotes`；CLI `python -m cli.market` | `market.db`、`market_hot.db` | `tests/market/` | 49 | **强**（含并发死锁、锁 fd 泄漏、范围护栏、单位换算等回归） |
| `ops` | `/api/jobs*`、`/api/skills*`、`/api/skill-runs*`、`/api/ops/*` | `OpsStore` / `run_job` / `discover_skills`；CLI `python -m cli.ops` | `ops.db` | `tests/ops/` | 73 | **强**（生命周期契约、闸门、纸面舱、退役清理） |
| `strategy` | `/api/strategies*`、`/api/analysis/*`、`/api/screen/*`、`/api/insights/*`、`/api/screen-skills*` | `StrategyEngine` / `screen` | 写 `palace.db.candidate_reviews` | `tests/strategy/` | 12 | 中（前视审计与抽样有专测） |
| `backtest` | `POST /api/backtest`（挂在 strategy 前缀下） | `run_backtest` / `backtest_strategy_horizon` / `run_backtest_fast` | 不写库 | `tests/backtest/` | 5 | 中（含 fast 旁路与执行价对照） |
| `ledger` | `/api/candidates*`、`/api/plans`、`/api/reviews`、`/api/pools*`、`/api/timeline/*`、`/api/alerts/today` | `PalaceStore`；CLI `python -m cli.ledger` | `palace.db` | `tests/ledger/` | 5 | 弱偏中（迁移与时钟有专测） |
| `review` | `/api/review/*`、`/api/winrate/*` | `evaluate_candidates` / `track_candidate_outcomes`；CLI `python -m cli.review` | 只读(+可选缓存) | `tests/review/` | 3 | **弱** |
| `intel` | `/api/mcp*`、`/api/intel/*` | `McpClient` / `builtin_market_mcp` / `call_mcp_tool` | `ops.db.mcp_quota`、`market.db.intel_snapshots` | `tests/intel/` | 8 | 中（配额、负缓存、软降级有专测） |
| `ai` | `/api/providers*`、`/api/ai/*` | `chat` / `run_agent` / `build_toolbus` | `ops.db`（会话/记忆） | `tests/ai/` | 18 | 中偏强 |
| `research` | `/api/research/catalog`、`/profile/{code}`、`POST /runs`、`/factor-jobs*`、temporal / publication 路由 | `build_research_profile` / `run_research_backtest` | 只写 `data/research_runs/` | `tests/research/` | 5 | **弱且自认有大缺口**（见下） |
| `formula` | 无 HTTP（库） | `compile_screen_formula` / `evaluate_screen_formula` | — | `tests/formula/` | 2 | **弱** |
| `shared` | 无 HTTP（横切） | `paths` / `api_deps` / `boot_splash` | — | `tests/shared/` | 6 | 中 |
| `app`（组合根） | `GET /api/capabilities` + 聚合挂载 | `create_app` / `legacy.quant_router` | — | `tests/app/` | 11 | 中（含导入边界、异步边界、能力契约） |
| —（部署） | — | `deploy/deploy.ps1` | — | `tests/deploy/` | 2 | 弱 |
| —（脚本） | — | `scripts/*.py` | — | `tests/scripts/` | 1 | **几乎为零**（`scripts/` 下 60+ 个文件只有 1 个测试） |

合计 **200** 个文件匹配 `tests/**/test_*.py`（工具返回上限恰为 200，故实为 **≥200**），另有根级 `tests/test_market_session.py`、`tests/conftest.py` 与若干 `*_fixtures.py`。

`research` 的缺口是 README 自述（`src/research/README.md` 末段，`E3`）：本上下文约 9200 行，**未覆盖** `run_research_backtest` 的冻结/重放全链路、artifact manifest 的幂等与拒写、PTH252 因子实验、`api/router.py` 的 HTTP 契约。这一条与 §6 的「run card 零落地」互相印证。

### 1.2 Job 类型（16 种）

`E2`：`src/ops/infrastructure/store_helpers.py:13-30` 定义 `JOB_KINDS`；`src/ops/application/jobs/registry.py:48-65` 定义 `EXECUTORS`，两处一一对应。

| 类别 | kind | 托管任务名与默认 cron（`E3` ops/README.md） |
|---|---|---|
| 行情 | `sync` | `行情盘中增量` / `行情日终重刷`（15:10） |
| 行情 | `hot_rebuild` | `行情热库重建`，`10 16 * * mon-fri` |
| 行情 | `data_quality` | `行情库体检`，`30 16 * * mon-fri`（只读只报不改库） |
| 选股 | `screen` | `screen:{slug}`，默认 `30 15 * * mon-fri` |
| 研究 | `backtest` / `compare` / `optimize` | 非托管，按需创建 |
| 复盘 | `outcome` | `候选T+N跟踪`，`45 15 * * mon-fri` |
| 运维 | `prune` | `运维清理`，`30 2 * * mon-fri` |
| 情报 | `intel_fetch` | `情报·开盘/盘中/盘后`（盘中 `*/15 9-14` = 24 轮/日） |
| 战法 | `skill` / `skill_watch` | `skill:{slug}` / `监测·{slug}`（`*/5 9-14 * * mon-fri`） |
| 纸面 | `strategy_monitor` / `paper_eod` / `alert_scan` | 由 `ensure_paper_monitor_jobs` 幂等挂载 |
| 通知 | `notify` | 模板 `alerts` / `digest` |

**实测（`E1`，ops.db）**：`jobs` 表 14 行、`job_runs` 706 行。即 16 种 kind 里当前只有 14 条任务实例存在。

---

## 2. AkShare 实际用量

### 2.0 本机基线（`E1`）

```
PY 3.12.13
AK 1.18.56
顶层 akshare.* callable 总数       1093
其中 stock_*（= 目录可发现面）      403
其余（目录发现不了）   690
```

目录的发现判据只有两条（`E2` `src/market/infrastructure/akshare_catalog.py:218-220`，探测子进程在 `akshare_probe_worker.py:114-120` 再校验一次同样两条）：

1. 名字 `startswith('stock_')`；
2. `getattr(target, '__module__', '').startswith('akshare.')`。

### 2.1 (a) 真正进入数据链路的 —— **穷举 9 个**

判定方法：全仓 grep `\bak\.[a-z_]+\(` / `getattr\(ak,` / `akshare\.[a-z_]+\(`，范围 `src; cli; scripts`。命中全部落在 `src/market/infrastructure/` 三个文件里；`cli/` 与 `scripts/` **零命中**。

| # | 接口名 | 调用点（`E2`） | lane / 用途 | 位次 |
|---|---|---|---|---|
| 1 | `stock_zh_a_hist` | `sources.py:198` | `hist_daily`——东财日 K | 日线链**第 3 位**备源（tdx→tencent→**eastmoney**→baostock→sina） |
| 2 | `index_zh_a_hist` | `sources.py:191` | `hist_daily`——**指数**日 K（`EastmoneySource.fetch_daily` 的 `instrument_type=='INDEX'` 分支） | 同上 |
| 3 | `stock_info_sh_name_code` | `sources.py:266` | 上交所证券列表 | `fetch_instrument_list` 唯一源 |
| 4 | `stock_info_sz_name_code` | `sources.py:273`（`symbol='A股列表'`） | 深交所证券列表 | 同上 |
| 5 | `stock_info_bj_name_code` | `sources.py:280`（`getattr` 容缺兜底空表） | 北交所证券列表 | 同上 |
| 6 | `stock_board_industry_name_em` | `em_industry.py:233` | 东财行业板块列表 | 行业名补全，7 天磁盘缓存 |
| 7 | `stock_board_industry_cons_em` | `em_industry.py:245` | 每个板块成分（**约 90 次/轮**） | 同上 |
| 8 | `stock_individual_fund_flow` | `adapters/eastmoney_adapter.py:245` | `capital_flow` | **主源**（回退新浪） |
| 9 | `stock_zh_a_spot_em` | `adapters/eastmoney_adapter.py:296` | `spot_batch` / `live` 全市场现价表（约 5500 行） | 备源，带 4s 进程内 TTL |

**另有 1 处非接口引用**：`src/market/infrastructure/sina.py:109` `from akshare.stock.cons import hk_js_decode`——只借一个 JS 解密常量，不是接口调用。

**被明确拒绝、写进代码注释的 2 个**（`E2`，值得记住，别有人再提）：

- `stock_info_a_code_name()` —— `sources.py:216-219`：内部依赖 py_mini_racer 执行 JS，多线程同步下**原生崩溃**（不是 Python 异常，整个进程挂掉、无 traceback）。改用三家交易所各自的纯表格接口。
- `stock_zh_a_daily` —— `sina.py:5-8` / `sources.py:71-75`：每次调用新建一个 V8 isolate，多线程并发触发 `partition_address_space.cc` FATAL。改为直连新浪 + 只给 JS 解码加锁，实测 6 并发 48/48 成功、比走 akshare 快 4.7 倍。

**口径提醒**：9 个里只有 8 个是 `stock_*`。第 2 个 `index_zh_a_hist` 属于下面的 (c) 类——**目录看不见它，MCP `akshare_call` 也调不到它，但它就在生产日线链路上**。

### 2.2 (b) 目录里可调、但没有任何代码调用的 —— **395 个**

算式：目录可发现 403 − 已进链路的 `stock_*` 8 = **395**（`index_zh_a_hist` 不在目录内，不参与本式）。

这 395 个的可达面是真的：`GET /api/market/akshare/catalog` 列全部、`POST /api/market/akshare/catalog/{name}/probe` 每个都能试跑、MCP 单一工具 `akshare_call` 按名调用任意一个（`E2` `src/intel/infrastructure/builtin_akshare_tools.py:14,31,57`；`E3` `src/market/api/README.md:15-23`）。

#### 按目录自己的分类维度分布（`E1`，用 `akshare_catalog_meta.py` 原样规则重算 403 个）

| `infer_category` | 数量 | `infer_source` | 数量 | `execution_mode` | 数量 |
|---|---:|---|---:|---|---:|
| `reference` 参考数据 | 299 | `eastmoney` 东方财富 | 208 | `disabled` **未接入编排** | **317** |
| `financials` 财务报表 | 31 | `akshare` | 98 | `on_demand` | 65 |
| `spot_quotes` 实时行情 | 30 | `sina` 新浪 | 40 | `batch_cache_only` | 21 |
| `history` 历史行情 | 19 | `tonghuashun` 同花顺 | 38 | | |
| `corporate_actions` 公司行为 | 11 | `xueqiu` 雪球 | 8 | | |
| `capital_flow` 资金流 | 11 | `tencent` 腾讯 | 6 | | |
| `minute_bars` 分钟线 | 2 | `baidu` 百度 | 5 | | |

就绪度：`available` 401 / `needs_parameters` 2（`capability_status` 只看有没有必填参数，**不代表接入了业务**）。

**`execution_mode=disabled` 占 317/403 = 78.7%** —— 这是目录自己的诚实声明（`E2` `akshare_catalog_meta.py:50-57`：「当前 market 同步链未注册 AkShare 适配器；未知能力不能冒充同步可用」）。

#### 抽样 20 个高价值未用接口（`E1`，从 100 个关键词命中里挑）

挑选口径：与本仓已知缺口直接对应（龙虎榜 / 北向 / 两融 / 筹码 / 热度 / 股东 / 解禁 / 盘口），且 `src/research/domain/dimensions.py` 里对应维度当前是 `pending`。

| 接口名 | 能补什么 | 对应本仓缺口 |
|---|---|---|
| `stock_lhb_detail_em` | 龙虎榜每日明细 | `16_lhb` 维度 `pending`（`dimensions.py:120-124`） |
| `stock_lhb_stock_detail_em` | 个股龙虎榜买卖席位 | 同上 |
| `stock_lhb_jgmmtj_em` | 机构买卖统计 | 同上 |
| `stock_lhb_yyb_detail_em` | 营业部（游资）明细 | 同上 |
| `stock_hsgt_hold_stock_em` | 北向个股持股 | `12_capital_flow` 仅 `partial` |
| `stock_hsgt_individual_em` | 个股沪深港通明细 | 同上 |
| `stock_margin_detail_sse` / `stock_margin_detail_szse` | 沪深两融逐日明细 | 同上 |
| `stock_cyq_em` | **筹码分布（现成）** | 本仓 `chips.py` 自己递推 COST 分位，有停牌 NaN 坑 |
| `stock_zh_a_gdhs` / `stock_zh_a_gdhs_detail_em` | 股东户数及明细 | `11_governance` `pending` |
| `stock_hot_rank_em` / `stock_hot_rank_detail_em` | 东财人气榜（含历史明细） | **研究文档反复说「热度无免费全市场历史源」** |
| `stock_comment_em` | 千股千评（机构参与度 / 关注指数） | `17_sentiment` |
| `stock_tfp_em` | 停复牌 | 无对应设施 |
| `stock_restricted_release_queue_em` | 限售解禁排队 | `15_events` `pending` |
| `stock_yjyg_em` | 业绩预告 | `1_financials` `pending` |
| `stock_fhps_em` | 分红送配 | `corporate_actions` |
| `stock_gdzjc_em` | 股东增减持 | `11_governance` |
| `stock_jgdy_tj_em` | 机构调研统计 | `15_events` |
| `stock_research_report_em` | 研报覆盖 | `6_research` `pending` |
| `stock_intraday_em` / `stock_intraday_sina` | **日内分笔** | **§4 的盘中留存空白** |
| `stock_bid_ask_em` | **五档盘口** | 同上 |

最后两行值得单独标注：**「盘中快照留存」缺的数据源，目录里现成躺着，一次都没被调过。**

### 2.3 (c) 目录根本发现不了的 —— **690 个**

**判定方法**（可复算）：`vars(akshare)` 里 `__module__.startswith('akshare.')` 的 callable 共 1093 个，减去名字以 `stock_` 开头的 403 个 = 690。这 690 个既不进 `GET /api/market/akshare/catalog`，也不能经 MCP `akshare_call` 调用（`akshare_probe_worker.py:114-120` 会以 `unknown stock capability: {name}` 拒绝）。

按名字首段分布（`E1`，Top 20）：

| 前缀 | 数量 | 前缀 | 数量 |
|---|---:|---|---:|
| `macro_*` 宏观 | 226 | `currency_*` | 8 |
| `index_*` **指数** | 79 | `energy_*` | 8 |
| `fund_*` 基金 | 73 | `movie_*` | 8 |
| `futures_*` 期货 | 66 | `car_*` | 7 |
| `option_*` 期权 | 46 | `air_*` | 5 |
| `bond_*` 债券 | 44 | `article_*` | 5 |
| `get_*` | 24 | `fx_*` | 5 |
| `spot_*` 现货 | 16 | `news_*` | 5 |
| `amac_*` | 14 | `sw_*` 申万 | 4 |
| | | 其余（crypto/qdii/reits/forex/fred/…） | 约 47 |

**本类里最要命的一条**：`index_zh_a_hist` 与 `index_zh_a_hist_min_em` 都在这 690 里，而 `index_zh_a_hist` **正被 `sources.py:191` 在生产链路上调用**。因此 `src/market/api/README.md:15` 那句「**目录即全部可用面**」对指数**不成立**——目录漏掉了一个已经在用的接口，运维页「按接口」试跑不到它，MCP 也调不到它。

顺带：`index_zh_a_hist_min_em`（指数分钟线）同样不可见，而 §4 说本仓分钟线只有个股三源、指数分钟线无源。

---

## 3. 数据体量与保留策略

### 3.1 先确认查的是哪个目录

`E2` `src/shared/paths.py:196-208` `data_dir()` 解析顺序：环境变量 `LOCI_DATA_DIR`/`PALACE_DATA_DIR` → `loci.config.json` 的 `data_dir` → `{writable_root}/data`。

`E1` `loci.config.json:2`：`data_dir` = `E:\entertainment_software\Loci\data`。

**因此仓库内的 `data/market.db`（0 字节）与 `data/palace.db`（0 字节）是空壳，不是数据。**本节所有数字来自 `E:\entertainment_software\Loci\data`。

### 3.2 `market.db` —— 5,740.2 MB

`E1`：`page_size 4096 × page_count 1,401,420 = 5,740,216,320 B`；`freelist_count = 0`；`journal_mode = wal`；`-wal` 当前 0 字节。共 **9 张表 + 13 个索引**。

#### 3.2.1 dbstat 逐 btree 分解

| btree | 字节 | MB | 占比 | 性质 |
|---|---:|---:|---:|---|
| `quotes_daily` | 2,723,008,512 | **2,723.0** | 47.4% | 行情本体 |
| `idx_quotes_receipt` | 1,049,014,272 | **1,049.0** | 18.3% | **溯源**（`quotes_daily.receipt_id`） |
| `source_route_attempts` | 724,668,416 | 724.7 | 12.6% | **溯源** |
| `source_route_receipts` | 450,887,680 | 450.9 | 7.9% | **溯源** |
| `idx_quotes_code_date` | 424,919,040 | 424.9 | 7.4% | 行情二级索引 |
| `idx_source_attempts_source` | 127,262,720 | 127.3 | 2.2% | **溯源** |
| `idx_source_receipts_recent` | 71,860,224 | 71.9 | 1.3% | **溯源** |
| `idx_source_receipts_code_lane` | 62,271,488 | 62.3 | 1.1% | **溯源** |
| `sqlite_autoindex_source_route_receipts_1` | 49,197,056 | 49.2 | 0.9% | **溯源** |
| `idx_source_receipts_lane_state` | 33,673,216 | 33.7 | 0.6% | **溯源** |
| `intel_snapshots` | 15,069,184 | 15.1 | 0.3% | MCP 情报缓存 |
| `adjust_factors` | 4,214,784 | 4.2 | 0.1% | 复权因子 |
| `ingest_watermark` | 2,912,256 | 2.9 | 0.1% | 同步水位 |
| `instruments` | 548,864 | 0.5 | — | 证券列表 |
| `trading_calendar` | 352,256 | 0.4 | — | 交易日历 |
| 其余小 autoindex + `sqlite_schema` + `meta` | 约 217,000 | 0.2 | — | |

**溯源审计合计**（`idx_quotes_receipt` + `source_route_attempts` + `source_route_receipts` + 其 5 个索引）= **2,568.8 MB = 全库 44.8%**。行情本体侧（日 K + 其二级索引 + 因子 + 列表 + 日历 + 水位 + 情报缓存）= 3,171.4 MB。

> 一句话：**这个库有将近一半不是行情，是「这一行是谁在什么时候从哪抓来的」。**

#### 3.2.2 行数与范围（`E1`）

| 表 | 行数 | 备注 |
|---|---:|---|
| `quotes_daily` | **16,966,403** | 1990-12-19 ~ 2026-08-25；平均 **160.5 字节/行** |
| `source_route_attempts` | 2,048,634 | |
| `source_route_receipts` | 1,068,769 | |
| `trading_calendar` | 8,778 | 1990-12-19 ~ 2026-08-25 |
| `adjust_factors` | 68,010 | 5,543 只；1900-01-01 ~ 2026-08-24 |
| `instruments` | 5,547 | STOCK/normal 5,543、INDEX/normal 3、STOCK/delisted **1** |
| `ingest_watermark` | 5,547 | |
| `intel_snapshots` | 479 | |
| `meta` | 8 | |

`quotes_daily` DDL（`E1`）：`PRIMARY KEY (trade_date, code)` + `WITHOUT ROWID`，13 列，末三列 `source` / `fetched_at` / `receipt_id` 是**逐行溯源**。

**存活偏差硬伤（`E1`）**：`SELECT COUNT(*) FROM instruments WHERE COALESCE(delist_date,'') <> ''` = **0**；`status` 分布 `normal 5,546 / delisted 1`。即 **退市信息完全没有**——与 `docs/research/2026-08-dragon-survivorship-and-portfolio-fragility.md` 的判断一致，且本轮确认至今未修。

#### 3.2.3 逐年行数（`E1`，全 37 年）

| 年 | 行数 | 年 | 行数 | 年 | 行数 | 年 | 行数 |
|---|---:|---|---:|---|---:|---|---:|
| 1990 | 29 | 2000 | 188,340 | 2010 | 396,047 | 2020 | 906,328 |
| 1991 | 1,964 | 2001 | 215,493 | 2011 | 471,808 | 2021 | 1,027,620 |
| 1992 | 5,531 | 2002 | 226,150 | 2012 | 521,455 | 2022 | 1,133,252 |
| 1993 | 19,972 | 2003 | 245,402 | 2013 | 519,711 | 2023 | 1,230,759 |
| 1994 | 51,708 | 2004 | 268,108 | 2014 | 531,545 | 2024 | 1,277,772 |
| 1995 | 58,461 | 2005 | 273,705 | 2015 | 543,693 | 2025 | **1,307,392** |
| 1996 | 74,767 | 2006 | 261,041 | 2016 | 610,281 | 2026 | 856,426（至 08-25） |
| 1997 | 122,422 | 2007 | 296,438 | 2017 | 710,591 | | |
| 1998 | 153,050 | 2008 | 331,574 | 2018 | 778,367 | | |
| 1999 | 168,213 | 2009 | 343,626 | 2019 | 837,362 | | |

分段：**2010 年前累计 3,305,994 行 = 19.5%**；**2021 年起 6,833,221 行 = 40.3%**。

> 这两个数直接决定「砍历史能省多少」：把 2010 年前全删只回收约 19.5% 的日 K 体积（约 531 MB），**远不如删溯源表（2,569 MB）划算**。

### 3.3 `market_hot.db` —— 1,022.1 MB（滚动热读库）

`E1`：`quotes_daily` **3,748,806 行**，2023-10-10 ~ 2026-08-25，`trading_calendar` 恰好 **700** 行（= `HOT_WINDOW_TRADING_DAYS`）。

| btree | MB | 备注 |
|---|---:|---|
| `quotes_daily` | 584.2 | |
| `idx_quotes_receipt` | **238.3** | **占热库 23.3%**，而热库 `source_route_receipts` 只有 11,229 行 |
| `idx_quotes_code_date` | 94.7 | |
| `source_route_attempts` | 15.1 | 56,659 行 |
| `source_route_receipts` | 5.8 | 11,229 行 |
| `adjust_factors` | 4.2 | 68,010 行（全量复制） |

其余：`instruments` 5,547（全量复制）、`ingest_watermark` 0、`intel_snapshots` 0。

> 热库为了 **11,229 条回执**背着一个 **238 MB 的 `receipt_id` 索引**——而选股热路径根本不查回执。这是全仓最容易摘的一块。

### 3.4 `ops.db` —— 13.8 MB / `palace.db` —— 0.82 MB

`ops.db`（`E1`，31 张表）：`job_runs` **11.36 MB / 706 行 ≈ 16.1 KB/行**（最大单表）、`leader_role_snapshots` 0.64 MB / 1,392 行、`ai_agent_events` 0.38 MB / 2,204 行、`second_wave_signals` 0.14 MB / 632 行。

**关键的零**：`strategy_backtests` **0 行**、`strategy_versions` **0 行**、`ai_decisions` 0、`monitor_runs` 0、`paper_fills` 0、`paper_positions` 0、`alert_rules` 0、`alert_hits` 0。

`palace.db`（`E1`，7 张表）：`candidate_reviews` **212**、`stocks` 560、`meta` 2；`ai_judgments` / `candidate_batches` / `plans` / `reviews` **全 0**。

### 3.5 TTL / 清理 / 归档：逐库结论

grep 口径：`DELETE FROM`、`def prune`、`VACUUM`/`vacuum`、`retention`、`keep_days`、`purge_`，范围 `src/`。

| 库 | 有没有保留策略 | 证据 |
|---|---|---|
| **`market.db`** | **完全没有** | 全仓**不存在**任何针对全量库的 `DELETE FROM quotes_daily` / `source_route_receipts` / `source_route_attempts`。唯二的 `DELETE FROM quotes_daily` 在 `store_hot.py:130`（`_trim_window`）与 `:202`（`_replace_window`），两处游标都来自**热库**连接。`store_rw.py:303` 的 `DELETE FROM trading_calendar` 是 `rebuild_calendar` 重建，`store_rw.py:246` 的 `DELETE FROM meta WHERE key='quotes_daily_rows_v1'` 是缓存失效——都不是保留策略。**没有 VACUUM**（全仓唯一的 `VACUUM` 在 `ops/application/share_pack_sanitize.py:218`，作用于分享包里 ops.db 的**副本**）。 |
| `market_hot.db` | 有，滚动窗口 | 700 交易日窗口，每次镜像时 `_trim_window` 裁掉窗外日 K/日历并 `_purge_orphan_receipts`（`store_hot.py:106-132`）。托管任务 `行情热库重建`（`hot_rebuild`，`10 16 * * mon-fri`）。 |
| `ops.db` | 有，三段 | 托管 `运维清理`（`prune`，`30 2 * * mon-fri`）：`prune_runs(keep_per_job=200)`（`store_runs.py:387-400`，且**不删 `status='running'`**）、`leader_role_keep_days=60`、`second_wave_keep_days=180`（`jobs/prune.py:40-58`）。 |
| `palace.db` | 无自动清理（**刻意**） | 账本按仓规是不可变审计；`candidates.py:171-206` 的 DELETE 是「同日同池重选替换」与人工删除，不是 TTL。 |

**一次性人工工具**（不是自动策略）：`scripts/compact_evidence_blobs.py` —— 压 `ops.db.job_runs.result_json`。其 docstring（`E2`，`:1-21`）记录了历史峰值：**694 行 `job_runs` 的 `result_json` 合计 5.64 GB、单条最高 257 MB**，`GET /api/jobs/runs` 一次返回 1.5 GB、耗时 97 秒。现在 706 行只剩 11.36 MB，说明这个脚本跑过且 `finish_run` 侧已修。

> **对「加密留存 30-60 天」的直接影响**：本仓**没有任何按时间窗滚动淘汰行情数据的现成件**可复用。热库那套是「按交易日数保留窗口 + 整窗重灌」，语义是缓存镜像不是归档；ops 那套 `prune` 只会 `DELETE`，**没有「导出 → 加密 → 落冷存」的任何一环**。

---

## 4. 分钟线 / 实时数据现状

### 4.1 分钟线拉了之后落不落库？—— **不落**，而且库里根本没这张表

最硬的证据（`E1`）：`market.db` 的 9 张表是 `adjust_factors` / `ingest_watermark` / `instruments` / `intel_snapshots` / `meta` / `quotes_daily` / `source_route_attempts` / `source_route_receipts` / `trading_calendar`。**没有任何分钟 / tick / 盘口表。** `market_hot.db` 同 schema，同样没有。

代码侧一致（`E3`+`E2`）：

- `src/market/api/README.md:5`：「分钟线外网拉取本身不写库」；同文件 `GET /api/market/minute/{code}` 段标注（**不写** `market.db`）。
- `src/market/README.md:198`：「`GET /api/market/minute/{code}` 实时分钟线（不落库）」。
- 三个取数实现：`tdx_minute.py:120 fetch_minute_bars`、`eastmoney_minute.py:192 fetch_minute_bars`、新浪（`sina_adapter`）。路由 `fetch_minute_routed` / `adapters/aux_router.py:97`，默认顺序 **通达信 → 东财 → 新浪**。
- 通达信分钟只给 `datetime` / `close` / `volume`，**不伪造 OHLC**；各源都不提供前复权分时，`adjust=qfq|hfq` 时服务端用本地 `adjust_factors` 现算缩放。

唯一的「分钟缓存」是进程内的：`src/market/application/live_cache.py:19` `_MINUTE_TTL_SEC = 45.0`。

### 4.2 `live_tape` 存什么、存多久、存哪？

| 问题 | 答案 | 证据 |
|---|---|---|
| 存**什么** | **只有 4 个指数**：上证 `000001` / 深证 `399001` / 创业 `399006` / 科创 `000688`。主展示字段是今日涨跌 `pct` | `live_tape.py:19-24` `DEFAULT_INDICES`（`E2`） |
| 存**多久** | **3.0 秒** | `live_tape.py:28` `_CACHE_TTL = 3.0`（`E2`） |
| 存**哪** | **进程内一个 dict**：`_CACHE = {at, key, payload}` + `_INFLIGHT` single-flight 表。**进程退出即消失，一个字节都不落盘** | `live_tape.py:27-38`（`E2`） |

相邻的另两层同样是内存：`live_cache.py:18` `_QUOTE_TTL_SEC = 5.0`；东财全市场现价表 `eastmoney_adapter.py:44` `_SPOT_RAW_TTL_SEC = 4.0`。

实盘账本下线后，`build_live_tape` 已不再读 palace 持仓，`position_codes` 只是留给托盘的形参（`E3` `src/market/README.md:228`）。

### 4.3 `tape/` 目录是什么？（**别被名字骗了**）

`src/market/infrastructure/tape/__init__.py:1` 自述是「**盘口情报 tape provider 骨架**」——它**不是** tick tape / 逐笔流水，而是把「涨停梯队 / 题材资金 / 情绪」这类**情报 lane** 抽象成 provider（`wudao_provider` MCP、`local_provider` 本地算、`cache_provider`、`router`、`registry`、`legacy_bridge`）。

它的落盘只有一处：`market.db.intel_snapshots`（`E1`：**479 行 / 15.1 MB**），主键 `(trade_date, tool, args_hash)`。

**这张表按 `(交易日, 工具)` 覆盖写**——同日多次扫描只剩最后一次。`src/ops/README.md:121-124`（`E3`）明确承认这一点，并说这正是要另建 `leader_role_snapshots` 的原因：「角色演进会被抹掉；这张表专门留住『谁从龙头掉成走弱』」。

### 4.4 有没有任何「盘中快照留存」的现成设施？

**没有行情快照层面的。** 全仓只有两处「盘中留痕」，且都是**派生结论**不是行情：

| 设施 | 库/表 | 实测行数 | 保留 | 存的是什么 |
|---|---|---:|---|---|
| 龙头角色留痕 | `ops.db.leader_role_snapshots` | 1,392 | 60 天（`prune`） | 每轮扫描判出的 leader/secondary/follower/weakened/failed **角色标签** |
| 二波触发留痕 | `ops.db.second_wave_signals` | 632 | 180 天（`prune`） | 触发事件 + 强度分 + `alerted` 标记 |
| （对照）情报缓存 | `market.db.intel_snapshots` | 479 | 无 TTL，但**同日同工具覆盖** | MCP 返回的原始载荷 |

**结论**：要做「盘中快照留存」，本仓可复用的只有 (i) 三条已经能取到分钟线的 lane、(ii) `intel_snapshots` 那套 `(日期, 工具, args_hash)` 的写法。**存储表、滚动窗口、压缩、加密——四样一样都没有，全要新建。** 另见 §2.2 抽样表末两行：`stock_intraday_em` / `stock_bid_ask_em` 在 AkShare 目录里现成躺着，从未被调用。

---

## 5. 加密设施盘点

grep 口径：`Fernet|AES|cryptography|SQLCipher|sqlcipher|encrypt|master_key|palace_ai_master_key|pycryptodome|pyzipper`，范围 `src; cli; scripts; deploy`（另单独 grep 了 `loci.py`、`frontend/src`）。

### 5.1 现存加密代码清单

| 位置 | 算法 | 密钥来源 | 还在不在用 |
|---|---|---|---|
| `src/ops/application/share_pack.py:375-391` `_zip_encrypted` | **pyzipper `WZ_AES`**（AES zip） | 服务端固定 `SHARE_PACK_PASSWORD`，前端不展示 | ✅ **在用**——全仓**唯一**在跑的加密 |
| `src/ai/infrastructure/crypto.py` | **无** | **无** | ⚠️ 整个文件 **9 行**，只剩 `mask_secret()`（末四位脱敏）。docstring 原文：「本机 LLM/MCP Key 明文存储，**不再做主密钥加密**」 |
| `src/ai/infrastructure/providers.py:45-49` `decode_provider_secret` | 无（只做 bytes→str） | — | 保留 `aad` 形参但第一行就 `_ = aad` 丢弃；docstring：「**旧 AES 密文一律视为失效**」 |
| `src/ai/infrastructure/providers.py:66-67` `migrate_encrypted_llm_keys` | 无 | — | ✅ 在用，但它是**拆除器**：启动时把非明文 `encrypted_key` **清空**，迫使用户在运维页重录 |
| `src/intel/infrastructure/mcp_config.py:406-424` `migrate_encrypted_mcp_tokens` | 无 | — | ✅ 同上，清 `mcp.json` 的 `encrypted_token` |
| `.palace_ai_master_key`（仓库根，**46 字节**） | — | — | ❌ **死文件**。全仓唯一提及处是 `share_pack_sanitize.py:22-23`，把它列进**禁止打包**名单。**没有任何代码读它。** |

两个迁移器由组合根在启动时调用：`src/app/main.py:127-141`（`E2`）。

### 5.2 核实：文档说的「LLM key 已从 AES 密文迁回明文」—— **属实**

逐条对照：

1. `src/intel/README.md:34`（`E3`）：「MCP API Key **明文**写在 `mcp.json` 的 `token` 字段；LLM 供应商 Key **明文**写在 `ops.db` 的 `encrypted_key` 列（**列名历史遗留**）。**无主密钥**。」
2. 列名确实还叫 `encrypted_key`：`src/ops/infrastructure/store_schema.py:20` `encrypted_key BLOB`（`E2`）——**列名骗人，内容是明文**。
3. `src/app/legacy/quant_router.py:53-55`（`E2`）注释：「密钥早已不再加密（见 `src/ai/infrastructure/crypto.py`），继续拿 `cryptography` 当探针会让没装它的机器看不到 AI 入口」——连能力探针都从 `cryptography` 换成了 `httpx2`。
4. 有专门的回归测试钉住这件事：`tests/ai/test_provider_plaintext_keys.py`（`E1`，文件存在）。
5. `E1` ops.db 现有 `llm_providers` **1 行**（未读其内容）。

### 5.3 装了但没用的加密库

`E1` `pip freeze`：`cryptography==48.0.0`、`pycryptodomex==3.23.0` 都在 venv 里。前者是传递依赖且已被显式弃用为探针；后者是 `pyzipper` 的依赖。**`requirements.txt` 里两者都没声明。**

**全仓无 SQLCipher、无 Fernet、无任何数据库级 at-rest 加密。**三个 SQLite 库（5.74 GB + 1.02 GB + 13.8 MB）全部明文落盘。

### 5.4 对「加密留存 30-60 天」的结论

**能复用的现成件：几乎为零。**

- ✅ 可复用：`pyzipper` 已在依赖里且有 AES-zip 的调用范例（`share_pack.py:375-391`）——但那是**一次性整包**语义，不是滚动留存。
- ❌ **没有密钥管理**。主密钥方案（`.palace_ai_master_key` + AES）已被**整体拆除**，且拆得很干净：`crypto.py` 里连密钥派生、盐、AAD 处理的代码都不剩了，`decode_provider_secret` 只是把 `aad` 形参吃掉。想恢复不是「打开开关」，是重写。
- ❌ 没有行级 / 表级 / 流式加密的任何一行代码。
- ⚠️ 拆除是**有意决策**且带迁移器（启动即清残留密文）。要重新引入加密，必须先回答「为什么上次拆了」，否则下一轮启动的 `migrate_encrypted_*` 会把新密文当残留清掉。

---

## 6. 回测 / 研究可复现性

### 6.1 `output/` 怎么组织的

`E1`：`output/` 下 **20 个结果子目录** + 若干散件。惯例是 `output/<实验名>[-<起止日>]/summary.json`，大结果另出 `signals.csv` / `scan.jsonl`。

体量抽样：`heat-tail-attention-proxy-2024-01-02_2026-07-31/summary.json` **10.9 MB**、`dragon-pool-trigger-top10/summary.json` 939.9 KB、`heat-tail-pool-slice-…/signals.csv` 2.5 MB。另有 `benchmarks/performance-baseline.json`（CI 硬门禁基线）与 `data-source-benchmark/benchmark-<时间戳>.json`。

### 6.2 有没有记录「哪份代码 + 哪个行情快照 + 哪组参数 → 哪个结果」？

**三缺二。** 以 `output/incumbent-benchmark/summary.json` 逐字段核对（`E1`，全文已读）：

| 复现要素 | 有没有 | `summary.json` 里的字段 |
|---|---|---|
| **哪组参数** | ✅ **有** | `range`、`entry_timing`、`top_n`、`config{hold_days, stop_loss_pct, take_profit_pct, commission_bps, stamp_duty_bps, slippage_bps, allow_limit_up_entry, benchmark}` |
| **哪份代码** | ❌ **没有** | 无 git commit、无 `strategy_revision`、无 `version` |
| **哪个行情快照** | ❌ **没有** | 无 `market_revision`、无 `data_snapshot`、无 `as_of`、无数据行数水位 |

它确实有 `purpose` / `caveat` 两个诚实字段（记「声明值锁在调优区间」这类警告），但那是人写的话，不是机器可校验的锚点。

**产出者是 `scripts/*.py` 一次性脚本**，不是 `src/research` 的 run card 链路——而 `tests/scripts/` 只有 1 个测试文件。

### 6.3 `market_revision()` 的用法（`E2`）

定义：`src/market/infrastructure/store.py:119-126`——只读一行 meta；docstring 警告不要为此调 `data_snapshot()`（后者会连带跑无范围 `source_evidence`，是对 `quotes_daily` 的全表扫）。递增点在 `store_rw.py:23-27` `_bump_revisions`。

**生产库当前值（`E1`，`market.db.meta` 全 8 行）**：

```
market_revision     1205457    2026-08-25 04:26:19
quotes_revision        447122    2026-08-25 04:26:19
adjust_factors_revision    280622    2026-08-25 03:50:51
instruments_revision         14    2026-08-25 03:50:39
source_receipts_revision     477699    2026-08-25 04:26:19
quotes_daily_rows_v1    2026-08-25|447122|16966403
instruments_snapshot_date 2026-08-25
schema_version            7
```

消费者（`E2`）：

| 消费点 | 位置 | 用途 |
|---|---|---|
| 回测 runner | `backtest/application/runner.py:405,487-500` | `_data_snapshot` → 结果里的 `data_snapshot` 段 ✅ |
| 研究 run card | `research/application/backtest_run.py:169,180` | 写进 card ✅ |
| run_card.md + 指纹 | `research/application/backtest_support.py:464-503` | `Market revision` 行 + `_input_fingerprint`（codes + market_revision + membership 的稳定 hash）✅ |
| `stale` 判定 | `research/api/router.py:215-221,423-428` | ✅ |
| 研究剖面 | `research/application/profile.py:52,62` | ✅ |
| AI 只读投影 | `ai/application/system_toolbus_research.py:98` | ✅ |
| **strategy 选股入库** | — | ❌ **不记**（见 §6.4） |

### 6.4 两条实际在跑的路，都缺行情锚点

**路 A：`output/` 脚本结果** —— 见 §6.2，缺代码版本与行情快照。

**路 B：`palace.db.candidate_reviews`（212 行）** —— schema（`E2` `src/ledger/infrastructure/schema.py:95-98`）有 `strategy_slug` / `strategy_revision` / `effective_params_json` / `evidence_json` / `rule_version`，**但没有 `market_revision` 列**。所以这 212 条候选能回答「哪个战法、哪一版、哪组参数」，**回答不了「基于哪份行情快照选出来的」**。

### 6.5 建好了但空转的第三条路：`src/research` run card

这套设施在设计上是完备的（`E2`）：

- `backtest_run.py:168-181`：run card 同时记 `strategy_slug` / `strategy_revision` / `version` / `hypothesis_id` / `hypothesis_revision` / `market_revision` / `universe_funnel` / `input_sha256` / `requested_as_of` / `actual_as_of`。
- `frozen.py:110-112,208-212`：冻结产物记 `strategy_revision` + `entry_timing`，重放时漂移即**拒绝**（「冻结输入的 strategy revision 已漂移，拒绝重放」）。产物契约 `research-frozen-input-v2`，v1 会被明确拒收而不是静默走到 hash 不一致。
- 状态机：人工签署不可跳过（`running` 不能直达 `completed`）、否决不可翻案、终态只能降级为 `stale`——有专测 `tests/research/test_run_card_state_machine.py`。
- 落地目录 `paths.research_runs_dir()` = `<data_dir>/research_runs/`（`E2` `src/shared/paths.py`）。

**实测（`E1`）**：

```
E:\entertainment_software\Loci\data\research_runs\
  └── membership_snapshots.json   1.4 KB (2 周前)
```

**零个 run card 目录。**唯一那个文件里是 **3 条测试夹具**——`source_id` 为 `ui-fixture` / `browser-acceptance-fixture`，`source_url` 指向 `example.invalid` / `example.test`，成员只有 `000001` / `600519`。

配套地：`ops.db.strategy_backtests` **0 行**、`strategy_versions` **0 行**（`E1`）。

> **一句话**：可复现性设施建得比多数开源项目都完整，但**只存在于没人走的那条路上**；真正产出结论的两条路（`output/` 脚本、`candidate_reviews`）都没有行情快照锚点。**当前 `output/` 里的历史结论都不可严格复现**——不知道当时是哪版代码，也不知道当时库里有多少行。

---

## 7. 依赖清单

### 7.1 三份声明文件（`E1`，全文已读）

| 文件 | 内容 |
|---|---|
| `requirements.txt` | `akshare>=1.12.0`、`baostock>=0.8.8`、`tdxpy>=0.2.5`、`pandas>=2.0.0`、`numpy>=1.24.0`、`duckdb>=1.0.0`、`polars>=1.0.0`、`fastapi>=0.115.0`、`uvicorn>=0.30.0`、`httpx2>=2.9.0`、`itsdangerous>=2.2.0`、`python-multipart>=0.0.20`、`apscheduler>=3.10.0`、`PyYAML>=6.0`、`pyzipper>=0.3.6`、`pywebview>=5.0`、`pystray>=0.19`、`Pillow>=10.0`（`pyinstaller` 注释掉）→ **共 18 条** |
| `requirements-dev.txt` | `-r requirements.txt` + `pytest>=8.0.0` + `import-linter>=2.1`（**共 2 条**） |
| `deploy/requirements-server.txt` | 与根一致，**只去掉桌面三件套**（pywebview / pystray / Pillow），`uvicorn[standard]`。实际安装用同目录 `requirements-server.lock.txt`（全量钉版本） |

### 7.2 量化相关依赖：声明 vs 实装（`E1`，`pip freeze --all`）

| 库 | 声明？ | 实装版本 | 全仓 import？ | 判断 |
|---|---|---|---|---|
| **pandas** | ✅ `>=2.0.0` | **3.0.5** | ✅ 大量 | ⚠️ **实装是 3.x，声明只写 `>=2.0.0`**。pandas 3.0 有 CoW 等破坏性变更，下界形同虚设 |
| **numpy** | ✅ `>=1.24.0` | 2.4.6 | ✅ | 正常 |
| **duckdb** | ✅ `>=1.0.0` | 1.5.5 | ✅ `market/infrastructure/duckdb_panel.py`（`LOCI_MARKET_DUCKDB=1` 旁路） | 正常 |
| **polars** | ✅ `>=1.0.0` | 1.43.2 | ✅ `polars_panel.py` / `research/readonly_engine.py`（POC） | 正常 |
| **scipy** | ❌ | **1.17.1** | ❌ **零 import** | 传递依赖，**不可依赖** |
| **scikit-learn** | ❌ | **1.9.0** | ❌ **零 import** | 同上 |
| **vectorbt** | ❌ | **1.1.0** | ❌ **零 import** | 同上——**装着但完全没用** |
| **numba** | ❌ | 0.66.0（+ llvmlite 0.48.0） | ❌ 零 import | vectorbt 拖进来的 |
| **statsmodels** | ❌ | **未安装**（`PackageNotFoundError` 实测） | — | 没有 |
| TA-Lib / pyarrow / bottleneck | ❌ | 未安装 | — | 没有 |

验证 import 的 grep（范围 `src; cli; scripts; tests`）：`import scipy|from scipy|import sklearn|from sklearn|import vectorbt|import vbt|from statsmodels|import numba|import talib|import pyarrow` → **No matches found**。

> **给选型的直接结论**：想用 vectorbt / scipy / sklearn，**不能因为「本机已经有了」就当它可用**——`requirements.txt` 和 `deploy/requirements-server.lock.txt` 里都没有它们，服务器镜像上不存在，CI 也不装。要用必须先显式声明。技术指标目前是**自己实现**的（`src/formula/` 的 MA/REF 等 + `research/application/technical.py` 的 MACD/RSI/KDJ/OBV/WR），**没有 TA-Lib**。

### 7.3 其它值得记一笔的实装（`E1`）

- 行情源：`akshare==1.18.56`、`baostock==0.9.3`、`tdxpy==0.2.7`，另有**未声明**的 `mootdx==0.11.7` 与 `yfinance==1.3.0`（均零 import）。
- JS 引擎**装了两个**：`py-mini-racer==0.6.0` 与 `mini-racer==0.14.1`。`loci.spec` 需要 `py_mini_racer` 原生库（`E3` market/README.md）。
- 绘图：`matplotlib==3.11.1`、`plotly==6.9.0` —— 均未声明、零 import。
- 工具链：`pytest==9.1.1`（声明 `>=8.0.0`）、`ruff==0.9.10`、`import-linter==2.13`、`pip_audit==2.9.0`、`pyinstaller==6.21.0`。
- 文档处理：`pdfplumber` / `pypdf` / `weasyprint` / `openpyxl` / `olefile` —— 是此前研究批次（解析 `D:\资料\娱乐`）留下的，非产品依赖。

> venv 里共 **170 个包**，`requirements.txt` 只声明 18 个。二者差距很大，**不要把 `pip freeze` 的结果当成可依赖面**。

---

## 8. 交叉发现（不属于任何单一调查项，但影响上层决策）

1. **溯源元数据的边际成本已经超过行情本身**。`market.db` 里 2,569 MB 是溯源、日 K 本体 2,723 MB，比例 0.94:1；`quotes_daily` 平均 160.5 字节/行里末三列 `source`/`fetched_at`/`receipt_id` 也是溯源。而 §6 显示：**这么贵的溯源，实际没有被任何产出结论的链路消费**——`output/` 不记、`candidate_reviews` 不记、run card 零落地。
2. **热库的 `idx_quotes_receipt`（238 MB）为 11,229 行回执服务**，而热库是选股只读路径、根本不查回执。
3. **`instruments.delist_date` 全空 + `delisted` 只有 1 只**，意味着 §3 的 16,966,403 行日 K 里**不含已退市股票**，所有基于本库的组合回测都带乐观存活偏差。这条与 `2026-08-dragon-survivorship-and-portfolio-fragility.md` 一致，本轮确认**至今未修**。
4. **`ops.db.job_runs` 16.1 KB/行**仍偏大（706 行占 11.36 MB = 全库 82%），虽已比历史峰值（257 MB/行）好了四个数量级。`prune` 的 `keep_per_job=200` 是目前唯一的刹车。
5. **AkShare 目录的自我描述与事实有一处偏差**：`src/market/api/README.md:15` 称目录「即全部可用面」，但目录按 `stock_` 前缀过滤，漏掉 690 个接口——包括正在生产链路上跑的 `index_zh_a_hist`。

---

## 9. 本轮做了什么 / 没做什么

**做了**（全部只读）：

- 读 `src/*/README.md` × 11、`src/*/api/README.md` × 9、根 `AGENTS.md`、`src/AGENTS.md`。
- 全仓 grep：akshare 调用点、加密符号、`DELETE FROM`/`prune`/`VACUUM`/`retention`、`market_revision`/`strategy_revision`、量化库 import。
- `.venv/Scripts/python.exe` 反射 `vars(akshare)`（**纯本地反射，零网络**），并用 `akshare_catalog_meta.py` 的原样规则重算分类分布。
- `sqlite3` 以 `mode=ro` + `query_only=1` 打开 `market.db` / `market_hot.db` / `ops.db` / `palace.db`，跑 `dbstat` 聚合、全表 `COUNT(*)`、日期范围、逐年分组、`meta` 全量。
- `pip freeze --all`。

**没做**：

- 未跑 `pytest` / `ruff` / `lint-imports` / 前端构建（任务明令禁止）。
- 未对 AkShare 任何接口发起真实请求（未试跑、未联网）。
- 未写任何数据库、未 `VACUUM`、未改任何仓库文件（**本文件除外**）。
- 未 commit / push。
- **未登记 `docs/research/INDEX.md`**（只读约束）。
- 未锁 commit hash（本文描述 2026-08-25 工作树状态，不是某个提交）。
- 未读 `llm_providers` 行内容、未读 `mcp.json`（205.8 KB）正文——两者都含明文密钥。

---

## 10. 数字速查表（供其它文档直接引用）

| 指标 | 值 | 来源 |
|---|---|---|
| 真实数据目录 | `E:\entertainment_software\Loci\data` | `loci.config.json:2` |
| `market.db` | **5,740.2 MB** / 1,401,420 页 × 4096 B | dbstat 实测 2026-08-25 |
| └ 溯源审计占比 | **2,568.8 MB = 44.8%** | 同上 |
| └ `quotes_daily` | 2,723.0 MB / **16,966,403 行** / 160.5 B/行 | 同上 |
| └ 日期范围 | 1990-12-19 ~ 2026-08-25 | 同上 |
| └ 标的数 | 5,547（STOCK 5,544 / INDEX 3；delisted **仅 1**） | 同上 |
| └ `adjust_factors` | 68,010 行 / 5,543 只 | 同上 |
| └ `trading_calendar` | 8,778 行 | 同上 |
| └ 2010 年前 / 2021 年起 | 3,305,994（19.5%）/ 6,833,221（40.3%） | 同上 |
| `market_hot.db` | 1,022.1 MB / 3,748,806 行 / 700 交易日 | 同上 |
| `ops.db` | 13.8 MB（`job_runs` 11.36 MB / 706 行） | 同上 |
| `palace.db` | 0.82 MB（`candidate_reviews` 212） | 同上 |
| `market.db` 保留策略 | **无** | grep 实测 |
| akshare 版本 / 顶层 callable | 1.18.56 / **1093** | 反射实测 |
| akshare 进链路 / 目录可见未用 / 目录不可见 | **9 / 395 / 690** | 反射 + grep |
| `execution_mode=disabled` | **317 / 403 = 78.7%** | 反射实测 |
| 分钟线落库 | **否**（无表） | schema 实测 |
| `live_tape` 留存 | 进程内 **3.0 秒**，4 个指数 | `live_tape.py:19-28` |
| 加密算法在用 | 仅 pyzipper AES-zip（分享包） | `share_pack.py:375-391` |
| `crypto.py` 规模 | **9 行**，只剩 `mask_secret()` | 全文已读 |
| research run card 落地数 | **0** | `data/research_runs/` 实测 |
| `strategy_backtests` / `strategy_versions` | **0 / 0 行** | ops.db 实测 |
| 量化库：声明 / 装了未声明 / 未装 | pandas·numpy·duckdb·polars / scipy·sklearn·vectorbt·numba（**零 import**） / statsmodels | `pip freeze` + grep |
| 测试文件数 | ≥200（ops 73 / market 49 / research 5 / formula 2） | glob 实测 |
