# 中文 / A 股圈开源量化系统体系对比（scratch）

> **日期**：2026-08-25 ｜ **检索日期**：2026-08-25 ｜ **stars / release 快照日期：2026-08-25**
> **用途**：供上层综述与本仓存储层 / 策略抽象决策引用。回答四个问题：①这些系统各自把数据放在哪、为什么；②A 股全市场日线这个量级为什么几乎没人用 SQLite 做主存、**我们用 SQLite 是不是错的**；③分钟线 / tick 到底多大、有没有「只留最近 N 天」的先例；④我们的 `StrategyEngine` Protocol 相对 Hikyuu / vn.py / RQAlpha 的组件化抽象缺了哪几件。
> **范围**：只读 + 临时目录基准测试。除本文件外未改任何仓库文件；未 commit / push；未写任何 `data/*.db`。基准测试全部在 `/tmp/qbcn/bench/` 生成合成数据，与真实行情库物理隔离。
> **证据分级**：`P1` 源码 / 官方文档原文本轮已读；`P2` 官方页面摘要或二手可核验记录；`M1` 本轮本机实测（脚本与数字均可复现）；`M2` 主 agent 本轮 dbstat 实测（2026-08-25，只读）；`✗` 未取到一手来源。
> **与既有文档的关系**：`2026-08-github-open-source-technology-radar.md` 是**项目级技术雷达**（197 仓库、只到 stars / license 层），本文是**体系级源码对比**（8 个框架 + 6 个数据源，逐个读实现）。`2026-08-market-data-source-intake.md` 侧重「本仓接哪些源」，本文 §6 侧重「这些源横向对比 + 组合判断」。`2026-08-vibe-trading-data-layer*.md` 锁的是另一个外部 commit，不重叠。**§2 / §3 是本篇的核心交付**，其余章节服务于这两节。

---

## 0. 一句话结论

**存储**：八个框架里，做「全市场 + 分钟/tick」的三家（Hikyuu / WonderTrader / vn.py 的 DolphinDB-Arctic-ClickHouse 分支）全部离开了通用关系库，走**定长记录 + 一票一 dataset/一文件 + 块压缩**；留在关系库里的三家（zvt / vn.py 默认 / QUANTAXIS）要么**按 provider × 周期分库**（zvt），要么**换成文档库**（QUANTAXIS MongoDB），要么**只当默认兜底**（vn.py 找不到驱动才 fallback SQLite）。**qteasy 干脆不提供 SQLite 选项**（只有 csv/hdf/feather 或 MySQL）。

**我们用 SQLite 错没错**：**日线不算错，但已经踩到边界，而且踩的那部分是我们自己加的。** 本轮 1,336.5 万行同数据四种落法实测：仓库现行 DDL **193.78 B/行**，把列精简成 8 列 + INTEGER 主键 + 去掉二级索引后 **69.96 B/行**（降 2.77×），Hikyuu 的打包结构 **40 B/行**，Parquet+zstd **19.29 B/行**。也就是说**「SQLite 天生贵」只占 1.75×，剩下 2.77× 是我们的 schema 决定的**。主 agent dbstat 同日实测真库：`market.db` 5,740.2 MB 里 **44.8% 是溯源审计**（receipts + attempts + 其索引 + `idx_quotes_receipt`），行情本体只有 3,153 MB。

**分钟/tick**：A 股全市场 1 分钟线 **一年 3.235 亿行**，按各家结构落地 **12.9 GB（Hikyuu 40 B）～ 62.7 GB（我们现行 SQLite DDL 193.78 B）**；L1 逐笔快照（3 秒一笔）**一年 64.7 亿笔 / 3.31 TB（WonderTrader 512 B tick 结构，未压缩）**。「只留最近 N 天」有**明确先例**：WonderTrader 的 `rt/` 实时块整目录 `remove_all()`、tick/逐笔按 `his/ticks/{exchg}/{date}/{code}.dsb` **按日期分目录**（删一天=删一个目录）、`disable_tick`/`disable_min1`/… 逐粒度开关；本仓 `market_hot.db` 的 700 交易日滚动窗口（`HOT_WINDOW_TRADING_DAYS = 700`）本身就是同一模式。

**策略抽象**：我们的 `StrategyEngine` 只吐 `signals + factors`，对照 Hikyuu 的 **九件套**（TM/MM/EV/CN/SG/ST/TP/PG/SP，不是六件），我们缺的是 **ST（止损）、TP（止盈）、PG（盈利目标）、MM（资金管理）、TM（账户）** 这五个**出场与仓位**部件。Hikyuu 源码里 ST 与 MM 是**硬耦合**的：`System.cpp:732-743` 先算止损价 → 若 `planPrice <= stoploss` 直接**放弃这笔买入** → 否则把 `planPrice - stoploss` 作为 `risk` 传给 MM 定仓位（`MM_FixedRisk::_getBuyNumber` 就是 `risk_budget / risk`）。**「所有战法 MFE 远高于净收益、退出纪律系统性缺失」正是这条链整条缺失的直接后果**：没有 ST 就没有风险距离，没有风险距离就没有仓位，没有仓位与止损就只剩「信号消失才出场」这一种出场。

**A 股约束**：**RQAlpha 实现得最全，而且是唯一把「涨跌停价当行情字段存进 bundle」而不是「按板块算」的**（`SecuritiesDayBarStore` 的 dtype 里就有 `limit_up`/`limit_down`）。这一条直接可抄——它自动正确地覆盖主板 10% / 双创 20% / 北交所 30% / ST 5%→10% 新规 / 新股首日无限制，不需要维护任何板块规则表。**我们的 `quotes_daily` 没有这两列。**

**数据源**：短线量化最值得接的免费组合 = **通达信（tdxpy/mootdx）主取日线与分钟（本仓实测 217 票/秒、全市场 26 秒、成交额是真值）+ AkShare 补衍生面（资金流/龙虎榜/概念/公告）+ baostock 作独立对账源（8/8 字段全，但 0.57 票/秒，只适合抽检不适合全量）+ 新浪/腾讯作 spot 与复权因子**。Tushare 免费档 120 积分**只给非复权日线、8000 次/天**，分钟线**不在积分体系内、单独 2000 元/年**——对短线不可用。

---

## 1. 主表

活跃度口径：`stars` 与 `latest release` 均取自 GitHub REST API `GET /repos/{owner}/{repo}` 与 `/releases/latest`，**快照 2026-08-25**。`pushed` = 仓库最后一次 push（含非 release 提交）。

| 项目 | 定位 | 语言 | 数据存储选型 | 回测模型 | 实盘接入 | 组合与风控 | 活跃度（快照 2026-08-25） | 许可证 |
|---|---|---|---|---|---|---|---|---|
| [vn.py / VeighNa](https://github.com/vnpy/vnpy) | 事件驱动全栈交易平台，功能以 App 插件组装 | Python | **抽象层**：[`vnpy/trader/database.py`](https://github.com/vnpy/vnpy/blob/master/vnpy/trader/database.py) 定义 `BaseDatabase`（`save/load/delete_bar_data` + `get_bar_overview`），实现在独立包：`vnpy_sqlite`（**找不到驱动时的兜底默认**）/ `vnpy_mysql` / `vnpy_postgresql` / `vnpy_mongodb` / `vnpy_influxdb` / **`vnpy_dolphindb`** / **`vnpy_arctic`** / **`vnpy_clickhouse`** / `vnpy_leveldb` / `vnpy_taos` | 事件驱动（`vnpy_ctastrategy` 的 `BacktestingEngine`，bar 与 tick 双模） | **最强**：CTP / CTP Mini / 飞创 / 易盛 / 中泰 XTP / 华鑫奇点 / QMT 等数十个原生柜台网关 | [`vnpy_portfoliostrategy`](https://github.com/vnpy/vnpy_portfoliostrategy)（多合约组合 CTA）+ `vnpy_riskmanager`（下单流控：撤单数/委托数/成交量上限） | release **4.4.0 @ 2026-05-14**；**44,745★** / 12,402 fork；pushed 2026-08-10 | MIT |
| [Hikyuu](https://github.com/fasiondog/hikyuu) | C++ 内核研究框架，主张「策略部件资产化」 | C++ 内核 + pybind11 Python 绑定 | **HDF5 主存**：[`H5KDataDriver`](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/data_driver/kdata/hdf5/H5KDataDriver.cpp) + [`H5Record`](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/data_driver/kdata/hdf5/H5Record.h)（**40 B 定长定点整数**）。另有 [SQLite](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/data_driver/kdata/sqlite/SQLiteKDataDriver.cpp) / [MySQL](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/data_driver/kdata/mysql/MySQLKDataDriver.cpp) / [TDX 本地文件](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/data_driver/kdata/tdx/TdxKDataDriver.cpp) 驱动 | 事件驱动逐 bar（`System::runMoment`）+ Indicator 向量化 | 弱：`hikyuu/strategy` 有实盘骨架与 `lastSuggestion()`，**无原生柜台网关** | `Portfolio` + [`AllocateFundsBase`](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/trade_sys/allocatefunds/AllocateFundsBase.h)（AF_EqualWeight / FixedWeight / FixedAmount / MultiFactor）；单系统层 MM/ST/TP/PG 四件 | release **2.8.2 @ 2026-08-20**；**3,465★** / 822 fork；pushed 2026-08-22 | Apache-2.0 |
| [WonderTrader](https://github.com/wondertrader/wondertrader) | C++ 全栈，「数据落地 / 回测 / 实盘同一套代码」 | C++ 内核 + [wtpy](https://github.com/wondertrader/wtpy) (Python) | **自定义二进制块**：[`WtDataStorage`](https://github.com/wondertrader/wondertrader/tree/master/src/WtDataStorage) —— `.dsb`（历史块，**zstd 压缩**）/ `.dmb`（实时块，mmap）。结构见 [`DataDefine.h`](https://github.com/wondertrader/wondertrader/blob/master/src/WtDataStorage/DataDefine.h) 与 [`WTSStruct.h`](https://github.com/wondertrader/wondertrader/blob/master/src/Includes/WTSStruct.h)。另有 [`WtDataStorageAD`](https://github.com/wondertrader/wondertrader/tree/master/src/WtDataStorageAD)（**LMDB** 后端） | 事件驱动，CTA / HFT / SEL / UFT 四个引擎；**回测与实盘跑同一份策略代码** | CTP / CTPMini / CTPOpt / XTP / 中泰 / 华鑫 等（`src/API/`） | SEL（选股）引擎做组合调仓；`WtRiskMonExecuter` + 风控模块 | **无 GitHub Release**（`/releases/latest` → 404）；pushed **2025-09-30**；**6,296★** / 1,183 fork | MIT |
| [RQAlpha](https://github.com/ricequant/rqalpha) | 事件驱动回测框架 + mod 插件体系 | Python | **bundle = HDF5 + npy + pickle**：[`storages.py`](https://github.com/ricequant/rqalpha/blob/master/rqalpha/data/base_data_source/storages.py) 的 `DayBarStore`（`h5py`，**一个 `order_book_id` 一个 dataset**，固定 numpy dtype `int64 datetime + 6×float64` = 56 B）；`trading_dates.npy`；`instruments.pk` | 事件驱动（`rqalpha_mod_sys_simulation` 的 `SimulationEventSource` + `BaseMatcher`），bar / tick / 集合竞价三态 | 通过第三方 `rqalpha-mod-*`（框架自身只提供 `sys_simulation` 撮合） | `Portfolio` / `Account` / `Position` 三层（[`rqalpha/portfolio/`](https://github.com/ricequant/rqalpha/tree/master/rqalpha/portfolio)）+ [`sys_risk`](https://github.com/ricequant/rqalpha/tree/master/rqalpha/mod/rqalpha_mod_sys_risk/validators) 四个 validator（cash / is_trading / price / self_trade） | release **release/6.3.0 @ 2026-07-23**；**6,717★** / 1,786 fork；pushed 2026-08-24 | **NOASSERTION**：自定义双轨授权——非商业用途走 Apache-2.0，**商业用途（含任何法人组织的任何用途）须米筐授权**。**不是 OSI 意义上的开源**，见 [`position_model.py` 文件头许可证声明](https://github.com/ricequant/rqalpha/blob/master/rqalpha/mod/rqalpha_mod_sys_accounts/position_model.py) |
| [QUANTAXIS](https://github.com/yutiansut/QUANTAXIS) | 分布式数据 / 回测 / 模拟 / 交易全家桶 | Python | **MongoDB**：集合 `stock_day` / `stock_min` / `stock_xdxr` / `stock_adj` / `index_day` / `index_min` / `stock_transaction`，索引一律 `create_index([('code',ASC),('date_stamp',ASC)])`（**非 unique**），见 [`QASU/save_tdx.py`](https://github.com/yutiansut/QUANTAXIS/blob/master/QUANTAXIS/QASU/save_tdx.py)。另有 [`QAFetch/QAClickhouse.py`](https://github.com/yutiansut/QUANTAXIS/blob/master/QUANTAXIS/QAFetch/QAClickhouse.py) | 事件驱动（QABacktest / QAStrategy）+ QADataStruct 向量化 | 社区维护（QATdx_adv / QAREALTIME 等） | QAData / QAAccount / QAPortfolio / QARisk 分层 | release **1.10.2 @ 2020-12-21（约 5.7 年未发版）**；pushed 2026-02-28；**11,041★** / 3,444 fork；**239 open issues** | MIT |
| [zvt](https://github.com/zvtvz/zvt) | schema-first 模块化量化，recorder / factor / trader 四层 | Python | **SQLAlchemy + SQLite，按 (provider, db_name) 分库**：[`contract/storage.py`](https://github.com/zvtvz/zvt/blob/master/src/zvt/contract/storage.py) 的 `SqliteStorageBackend`，路径 `{data_path}/{provider}/{provider}_{db_name}.db`；`db_name` 即 `stock_1d_kdata` / `stock_1m_kdata` / `stock_1d_hfq_kdata` 等，**每个周期 × 复权口径 × provider 一个独立 .db 文件** | 事件驱动 `Trader` + factor 层 pandas MultiIndex 向量化 | 无（研究框架） | `TargetSelector` 组合选标的 + `Trader`；无独立风控层 | release **v0.13.5 @ 2026-01-18**；**4,283★** / 1,013 fork；pushed 2026-07-01 | MIT |
| [qteasy](https://github.com/shepherdpp/qteasy) | 本地 DataSource + 多策略混合器 | Python（少量 C 扩展） | [`DataSource`](https://github.com/shepherdpp/qteasy/blob/master/qteasy/database.py)：`source_type='file'`（**csv / hdf(pytables) / feather**）或 `source_type='db'`（**MySQL**，pymysql + PooledDB）。**没有 SQLite 选项**；缺 pytables/pyarrow 时回退 csv | 向量化为主（历史数据 3D ndarray + numba 加速的 [`blender.py`](https://github.com/shepherdpp/qteasy/blob/master/qteasy/blender.py) 信号混合）+ live `trader.py` | `broker.py` 抽象层（QMT / 迅投等由用户实现） | `qt_operator` 多策略混合器 + `risk.py` / `finance.py` | release **2.6.4 @ 2026-08-21**；**152★** / 55 fork；pushed 2026-08-24 | BSD-3-Clause |

**主表读法上的三条提醒**

1. **stars 与活跃度不同向**。QUANTAXIS 11,041★ 排第二，但**最后一个 release 是 2020-12-21**、239 个 open issue；qteasy 只有 152★，却是本表**发版最勤**的之一（2026-08-21）。选型看 release 节奏与 issue 处理，不看 star。
2. **WonderTrader 没有 GitHub Release**（API 返回 404），版本靠 `dist/` 目录与文档发布；最后一次 push 是 **2025-09-30**，是本表七个项目里唯一近一年无提交的。
3. **RQAlpha 的许可证是本表唯一的坑**。GitHub API 报 `NOASSERTION`，源码文件头写明：非商业用途 Apache-2.0，**「任何法人或其他组织不得出于任何目的使用本软件」**。抄它的思路可以，直接依赖它的包做任何机构性用途都要先谈授权。

---

## 2. 数据存储选型的横向对比（核心交付之一）

### 2.1 谁用什么：一览

| 存储形态 | 用它的项目 | 具体实现与源码定位 |
|---|---|---|
| **HDF5** | Hikyuu（主存）、RQAlpha（bundle）、qteasy（可选 `file_type='hdf'`） | Hikyuu：`{market}_{ktype}.h5`，组 `data`/`week`/`month`/`min15`/…，**每只票一个 dataset，命名 `{market}{code}`**（如 `SH600000`），见 [`H5KDataDriver.cpp:214-272, 594-660`](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/data_driver/kdata/hdf5/H5KDataDriver.cpp)。RQAlpha：`stocks.h5` 等，`h5[order_book_id]` 直接取一只票的全历史（[`storages.py` `DayBarStore.get_bars`](https://github.com/ricequant/rqalpha/blob/master/rqalpha/data/base_data_source/storages.py)） |
| **自定义二进制** | WonderTrader | `.dsb` 历史块（`BlockHeaderV2` + zstd 压缩体）/ `.dmb` 实时 mmap 块。见 [`DataDefine.h`](https://github.com/wondertrader/wondertrader/blob/master/src/WtDataStorage/DataDefine.h)、压缩用 [`WTSCmpHelper.hpp`](https://github.com/wondertrader/wondertrader/blob/master/src/WTSUtils/WTSCmpHelper.hpp)（`ZSTD_compress`，默认 level 1） |
| **LMDB** | WonderTrader 的第二套存储 | [`WtDataStorageAD`](https://github.com/wondertrader/wondertrader/tree/master/src/WtDataStorageAD) + [`LMDBKeys.h`](https://github.com/wondertrader/wondertrader/blob/master/src/WtDataStorageAD/LMDBKeys.h) |
| **MongoDB** | QUANTAXIS（主存）、vn.py（`vnpy_mongodb`） | QUANTAXIS 每根 K 线一个 BSON 文档，字段名逐文档重复 |
| **DolphinDB** | vn.py（`vnpy_dolphindb`） | [`dolphindb_database.py`](https://github.com/vnpy/vnpy_dolphindb/blob/main/vnpy_dolphindb/dolphindb_database.py)：`dfs://` 分布式库，`PartitionedTableAppender(..., "datetime", pool)` **按 datetime 分区**写入；`bar` / `tick` / `baroverview` / `tickoverview` 四张表 |
| **ClickHouse / Arctic(ArcticDB) / InfluxDB / TDengine / LevelDB** | vn.py 的其余数据库包 | `vnpy_clickhouse` / `vnpy_arctic` / `vnpy_influxdb` / `vnpy_taos` / `vnpy_leveldb`，全部实现同一个 `BaseDatabase` 抽象 |
| **MySQL** | qteasy（`source_type='db'` 的唯一选项）、Hikyuu（可选驱动）、vn.py（`vnpy_mysql`） | qteasy 走 pymysql + `PooledDB(mincached=3, maxconnections=5)` |
| **SQLite** | zvt（**默认主存，但分库**）、vn.py（**兜底默认**）、Hikyuu（可选驱动）、**本仓** | zvt：一个 `(provider, db_name)` 一个 `.db`。vn.py：`get_database()` 里 `import_module(f"vnpy_{name}")` 失败才 `import_module("vnpy_sqlite")`，表结构是 peewee 的 `DbBarData`（`AutoField id` + 4 个 CharField + 7 个 FloatField + 一个四列唯一索引） |
| **csv / feather** | qteasy（`file` 模式默认 csv） | 缺 pytables 或 pyarrow 时**静默回退 csv**并 warn |

**所以「A 股圈没人用 SQLite」这个前提本身不成立。** 准确的说法是三条：

- 用 SQLite 的都**分片**（zvt 按 provider × 周期 × 复权口径分库）或**只当兜底**（vn.py）。
- **没有任何一家把分钟线 / tick 放进单张未分片的 SQLite 表**。
- **明确排除 SQLite 的只有 qteasy 一家**——它给了 csv/hdf/feather/MySQL 四选一，唯独没给 SQLite。

### 2.2 为什么打包结构这么小：三个记录结构的字节账（`P1`）

| 结构 | 来源 | 字段布局 | 字节 |
|---|---|---|---|
| `H5Record` | [Hikyuu H5Record.h](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/data_driver/kdata/hdf5/H5Record.h) | `uint64 datetime` + `uint32 open/high/low/close`（**定点整数，非浮点**）+ `uint64 transAmount` + `uint64 transCount` | **40** |
| `DayBarStore.DEFAULT_DTYPE` | [RQAlpha storages.py](https://github.com/ricequant/rqalpha/blob/master/rqalpha/data/base_data_source/storages.py) | `int64 datetime` + `float64 open/close/high/low/volume/total_turnover` | **56** |
| `WTSBarStruct` | [WonderTrader WTSStruct.h](https://github.com/wondertrader/wondertrader/blob/master/src/Includes/WTSStruct.h)（`#pragma pack(push,8)`） | `uint32 date` + `uint32 reserve_` + `uint64 time` + `double open/high/low/close/settle` + `double money/vol` + union `hold\|bid` + union `add\|ask` | **88** |
| `WTSTickStruct` | 同上 | `char exchg[16]` + `char code[32]` + 13×double + 4×uint32 + 3×double + **`bid_prices[10]`/`ask_prices[10]`/`bid_qty[10]`/`ask_qty[10]` 共 40×double** | **512** |

三个关键设计：

- **Hikyuu 用定点整数存价格**（`uint32`），不是 `double`。四个价格从 32 B 压到 16 B，这就是它比 RQAlpha 省 16 B 的全部原因。
- **RQAlpha 的 `SecuritiesDayBarStore` 在基础 dtype 上多两列 `limit_up` / `limit_down`**（见 §5）。
- **Hikyuu 的周/月/季/半年/年周期不重复存 bar**：这些组里放的是 `H5IndexRecord { uint64 datetime; uint64 start; }`（16 B），`start` 是回指日线基表 `data` 组的偏移（[`H5KDataDriver.cpp:643-660`](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/data_driver/kdata/hdf5/H5KDataDriver.cpp)）。**多周期只存索引不存副本**——`min15/min30/min60/hour2` 对 `MIN5` 基表同理。这是本对比里最值得直接抄的一条存储设计。

### 2.3 本轮实测：同一份 1,336.5 万行数据，四种落法（`M1`）

**环境**：Windows / Python 3.12.13 / SQLite 3.50.4 / polars 1.43.2 / duckdb 1.5.5。
**数据**：5,500 只 × 2,430 交易日（≈10 年）= **13,365,000 行**，合成 OHLCV + 成交额 + 流通股本 + 换手率，价格两位小数。
**脚本**：`/tmp/qbcn/bench_size.py`（仅写临时目录，未触碰 `data/`）；结果 `/tmp/qbcn/bench/result_size.json`。

| 落法 | 文件大小 | **B/行** | 相对 Hikyuu | 写入耗时 |
|---|---|---|---|---|
| **SQLite（本仓现行 DDL）**：13 列，`trade_date TEXT` + `code TEXT` 主键，`WITHOUT ROWID`，含 `idx_quotes_code_date` | 2,589,933,568 B（2,470 MiB） | **193.78** | **4.84×** | 插入 49.0 s + 建索引 10.7 s |
| **SQLite（精简）**：8 列，`trade_date INTEGER` + `code INTEGER` 主键，`WITHOUT ROWID`，**无二级索引** | 935,002,112 B（891.7 MiB） | **69.96** | 1.75× | 31.3 s |
| WonderTrader `WTSBarStruct`（88 B/行，解析值） | 1,176,120,000 B | 88.00 | 2.20× | — |
| RQAlpha `DayBarStore` dtype（**实写 raw 文件校验**） | 748,440,000 B | **56.00**（实测=解析值） | 1.40× | — |
| Hikyuu `H5Record`（40 B/行，解析值） | 534,600,000 B | 40.00 | 1.00× | — |
| **Parquet + zstd-3，按年分片** | 257,876,863 B（245.9 MiB） | **19.29** | **0.48×** | 4.0 s |

**读法**：

- **`193.78 → 69.96` 这一步（2.77×）完全是 schema 造成的**，与 SQLite 引擎无关。差额来自三件事：`TEXT` 主键（`'2026-08-25'` 10 B + `'600519'` 6 B，对 INTEGER 的 4+3 B）、三列逐行溯源（`source` / `receipt_id` 32 字符 / `fetched_at`）、以及 `idx_quotes_code_date`。
- **`69.96 → 40` 这一步（1.75×）才是「SQLite 天生贵」**：`WITHOUT ROWID` B-tree 的 cell header + payload varint + **每行重复一遍列类型头**（serial types）。1.75× 是行存通用格式的固定税，不是 bug。
- **Parquet 的 19.29 B/行有水分**，必须打折看：合成价格由 `sin + 正态噪声` 生成再 round(2)，列内相关性远高于真实行情，zstd 压得过于漂亮。**真实 A 股日线的 parquet 通常在 30–45 B/行**，请按 **1.5–2×** 放大后再用于容量规划。这个数字是**乐观下限，不是承诺**。

### 2.4 查询实测：SQLite 慢在哪、不慢在哪（`M1`）

脚本 `/tmp/qbcn/bench_query.py`，结果 `/tmp/qbcn/bench/result_query.json`。取 N 次中的最小值（页缓存已热），单位 ms。

| 查询 | 返回行数 | **SQLite** | **DuckDB / Parquet** | 倍数 |
|---|---|---|---|---|
| 单票 10 年历史（走 `idx_quotes_code_date`） | 2,430 | **7.2** | — | — |
| 单日全市场截面（走 PK 前缀） | 5,500 | **4.1**（tuple）/ 7.1（pandas） | — | — |
| **250 交易日全市场面板 → tuple** | 1,056,000 | **1,313** | **111** | **11.8×** |
| **250 交易日全市场面板 → DataFrame** | 1,056,000 | **1,864** | **196** | **9.5×** |
| 50 只票 × 10 年（本仓「codes + 窗口」护栏路径） | 121,500 | **427** | — | — |
| `SELECT DISTINCT trade_date`（冷进程） | 2,430 | **24.8 – 57.1** | — | — |
| `SELECT COUNT(*)` 全表（冷进程） | 1 | **174 – 589** | — | — |
| 全表 `GROUP BY code AVG(close)` | 5,500 组 | — | **68** | — |
| **相关子查询「每票最后一天」** | 5,500 | **6,721** | — | — |
| **DuckDB `sqlite_scanner` 读同一 SQLite 取 250 日面板** | 1,056,000 | — | **5,404** | **比裸 pandas 慢 2.9×** |

四条结论：

1. **SQLite 的点查完全够用**。单票 7.2 ms、单日 4.1 ms——前端 K 线、个股详情、单日复盘这三类主力读路径，换任何存储都不会有可感知收益。
2. **宽面板扫描是唯一真痛点**：1,864 ms vs 196 ms，**9.5×**。这正是 `load_panel` 的形状，也正是本仓 `store_panel.py:50-63` 为什么要硬报错强制传范围。
3. **相关子查询是断崖**：6,721 ms。这与 `tape/local_provider.py:150-160` 记录的真库现象同源（那里记的是 `MATERIALIZE previous` + 覆盖索引全扫 **1,950 ms**）。**这类查询要改写成窗口函数或两段式，不是换存储能救的**。
4. **⚠ 一条对现有开关的负面发现**：`LOCI_MARKET_DUCKDB=1` 走的 DuckDB `sqlite_scanner` 路径，在本轮同一查询上是 **5,404 ms，比裸 `pd.read_sql_query` 的 1,864 ms 慢 2.9×**。原因很直接——`sqlite_scanner` 仍然要逐行经 SQLite 的 VDBE 取值，只是把结果搬进 Arrow，**列存的收益一点都拿不到，还多付一次转换**。收益只在「DuckDB 读 Parquet」时才出现（196 ms）。[ADR-002](../adr/ADR-002-duckdb-readonly-panel.md) 的旁路应当重新基准化；本轮结论是 **DuckDB 的价值在换格式，不在换引擎**。

### 2.5 与真库 dbstat 的互相印证（`M2` × `M1`）

主 agent 2026-08-25 只读 dbstat 实测（真实数据目录 `E:\entertainment_software\Loci\data`，**不是仓库里那个空的 `data/`**）：

| 对象 | 实测 | 折算 B/行（16,966,403 行） |
|---|---|---|
| `market.db` 总计 | **5,740.2 MB** | — |
| `quotes_daily` 数据页 | 2,723.0 MB | **160.5** |
| `idx_quotes_code_date` | 424.9 MB | 25.0 |
| **`idx_quotes_receipt`** | **1,049.0 MB** | **61.8** |
| `source_route_attempts`（204.9 万行） | 724.7 MB | — |
| `source_route_receipts`（106.9 万行） | 450.9 MB | — |
| 其余溯源索引（source/recent/code_lane/autoindex/lane_state） | 344.4 MB | — |
| **溯源审计合计** | **2,569 MB = 全库 44.8%** | — |
| `market_hot.db`（3,748,806 行 / 700 交易日窗口） | 1,022.1 MB（其中 `idx_quotes_receipt` 238.3 MB） | 272.6 |

**交叉验证**：真库 `数据页 + idx_quotes_code_date` = **185.5 B/行**；本轮合成 `full.db` 整文件 = **193.78 B/行**。**差 4.4%**，差额来自合成库给每一行都写满 32 字符 `receipt_id`、以及文件级空闲页与 `ANALYZE` 表。**两条完全独立的测量在同一个数量级上对上了**，193.78 这个数可以直接用于容量规划。

真库覆盖 1990-12-19 ~ 2026-08-25、5,547 只、16,966,403 行；逐年分布 2010 年前累计 3,305,994 行（19.5%）、2021 年起 6,833,221 行（40.3%）、2025 单年 1,307,392 行。

**如果只把 `quotes_daily` 换成 Parquet**：16,966,403 × 19.29 B = **327 MB**（乐观下限；按真实数据 1.5–2× 折算约 **500–650 MB**），对 2,723 MB 数据页省 **~76%–88%**。**但这远不是省得最多的地方**——溯源审计那 2,569 MB（44.8%）才是。

### 2.6 判定：我们用 SQLite 到底是不是错的

**结论：日线主存用 SQLite 不算错；错的是三件叠在它上面的事。**

**支持「不算错」的证据（四条）：**

1. **同行也在用**。zvt 的默认主存就是 SQLite（分库），vn.py 的兜底默认也是 SQLite。**没有一条「A 股日线不能用 SQLite」的行业共识存在**。
2. **量级配得上**。1,697 万行 / 2.7 GB 数据页，对 SQLite 是舒适区。SQLite 官方的容量上限是 281 TB；这里离约束十万八千里。
3. **主力读路径的实测延迟没有问题**：单票 7.2 ms、单日 4.1 ms、`DISTINCT trade_date` 24.8 ms。
4. **单文件 + 零运维 + WAL + 事务，对「单机桌面工作台」这个形态是正确的默认**。换 DolphinDB / ClickHouse 会引入一个必须常驻的服务进程，与本仓的产品形态直接冲突（[技术雷达](./2026-08-github-open-source-technology-radar.md) 已把 ClickHouse 列入 Reject）。

**支持「已经踩到边界」的证据（四条）：**

1. **44.8% 的库体积是溯源审计**，其中 `idx_quotes_receipt` 单个索引 1,049 MB —— 比整张 `quotes_daily` 数据页的 38% 还多，而它服务的只是「这行数据是哪次抓来的」。热库里它又占了 238.3 MB。**这是本仓最大的一笔存储浪费，与 SQLite 无关。**
2. **宽面板扫描 9.5× 慢**，且这是选股/回测的主形状。护栏（`load_panel` 强制传范围）是在**绕开**问题，不是解决它——而且实测「codes + 窗口」护栏路径（427 ms / 121,500 行 = 2.9 µs/行）**每行反而比聚簇日期扫描（1.24 µs/行）更慢**，因为它走二级索引做随机寻道。
3. **写锁与读扫描互斥的问题已经被承认过一次**：`store_hot.py` 头部原文「全量库被同步写锁 + 千万行扫描 → 尾盘选股 disk I/O error」，解法是**再建一个物理隔离的 700 日热库**。这是一个正确但昂贵的补丁（多 1,022 MB + 一致性维护）。
4. **分钟线一进来这个方案就崩**（见 §3）：按现行 193.78 B/行，全市场 1 分钟线一年 **62.7 GB**，五年 313 GB，单个 SQLite 文件。

**三条具体动作（按性价比排序）：**

| 优先级 | 动作 | 依据 | 预期 |
|---|---|---|---|
| **P0** | **砍溯源的粒度**：`receipt_id` 从「每行一列 + 全表索引」改成「按 (code, 同步批次) 一条区间记录」，删掉 `idx_quotes_receipt` | 该索引真库 1,049 MB / 热库 238.3 MB；`source_route_attempts` 204.9 万行 724.7 MB。溯源需要的是「哪批数据从哪来」，不是「每一行从哪来」 | 立减 **~1,300 MB**（全库 23%），零查询回归风险 |
| **P1** | **把 `quotes_daily` 的 TEXT 键换成 INTEGER**（`trade_date` YYYYMMDD、`code` 6 位数字）；`board`/`source` 走字典表 | 本轮实测 193.78 → 69.96 B/行（含上一条） | 数据页再减 **~50%**，面板扫描线性变快 |
| **P2** | **给宽面板加 Parquet 只读镜像**（按年/按月分片），DuckDB 直读 Parquet；SQLite 仍是唯一写侧真相 | 实测 1,864 ms → 196 ms（9.5×）；**注意不是** DuckDB `sqlite_scanner`（那条实测反而慢 2.9×） | 选股/回测冷启动从秒级到亚秒级 |

**不建议做的**：换 DolphinDB / ClickHouse / MongoDB。前两个要常驻服务，与单机桌面形态冲突；MongoDB 在这个访问模式下只会更差（每文档重复字段名，QUANTAXIS 的 `stock_min` 是本对比里存储效率最低的方案）。

---

## 3. 分钟线 / tick 的存储与保留（核心交付之二）

### 3.1 量级：可核验的算式（`M1` 计算 + `M2` 输入）

**输入参数（全部可核验）**：
- 全市场股票数 `N = 5,547`（主 agent dbstat 实测 `quotes_daily` distinct code，2026-08-25）
- 年交易日 `D = 243`（2023/2024 各 242、2025 为 243；取 243 为保守上界）
- 日连续竞价分钟数 `M = 240`（9:30–11:30 + 13:00–15:00；收盘集合竞价 14:57–15:00 并入最后一根）
- L1 快照频率 `T = 3 秒/笔` → 日快照数 `4 × 3600 ÷ 3 = 4,800`

**行数**：

```
分钟线：240 × 5,547 × 243 = 323,501,040 行/年   ≈ 3.235 亿
L1快照：4,800 × 5,547 × 243 = 6,470,020,800 笔/年 ≈ 64.7 亿
```

**体积 = 行数 × §2.2/§2.3 实测的每行字节**：

| 落法 | B/行 | **全市场 1 分钟线 / 年** |
|---|---|---|
| Parquet + zstd-3 | 19.29 | **6.24 GB**（乐观下限，真实数据按 1.5–2× 计 = **9–13 GB**） |
| Hikyuu `H5Record` | 40 | **12.94 GB** |
| RQAlpha dtype | 56 | **18.12 GB** |
| **SQLite 精简 schema** | 69.96 | **22.63 GB** |
| WonderTrader `WTSBarStruct` | 88 | **28.47 GB** |
| **SQLite 本仓现行 DDL** | **193.78** | **62.69 GB** |

| 落法 | B/笔 | **全市场 L1 快照 / 年** |
|---|---|---|
| WonderTrader `WTSTickStruct`（未压缩） | 512 | **3.31 TB** |
| vn.py `DbTickData`（30+ 个 FloatField，估 ~400 B） | ~400 | **~2.59 TB** |

**这两个数就是答案**：分钟线在**十 GB 量级**，本机可承受（但用现行 DDL 会到 62.7 GB/年，不可承受）；**tick 在 TB 量级，本地全量保存不是工程问题而是硬件问题**——这就是为什么 WonderTrader 要给 tick 单独上 zstd 压缩 + 按日期分目录，也是为什么其余六家框架**没有一家默认落 tick**。

**两条必须打的折**：
- 分钟线**不是每票每天满 240 根**。停牌日无数据；小票有大量零成交分钟（多数数据源直接跳过，不填空 bar）。**真实行数通常是上限的 60%–90%**。上表是上界。
- tick 侧 3.31 TB 是**未压缩**。WonderTrader 用 zstd（[`WTSCmpHelper::compress_data`，默认 level 1](https://github.com/wondertrader/wondertrader/blob/master/src/WTSUtils/WTSCmpHelper.hpp)），tick 结构里 40 个盘口 double 高度相关，实际压缩比通常 3–5×，落到 **0.7–1.1 TB/年**。仍然不是本机方案。

### 3.2 各家怎么存分钟线 / tick（`P1`）

| 项目 | 分钟线 | tick / 逐笔 | 分片粒度 |
|---|---|---|---|
| **Hikyuu** | `{market}_MIN.h5`（1 分钟）与 `{market}_MIN5.h5`（5 分钟）**两个独立文件**；`min15/min30/min60/hour2` 只在 MIN5 文件里存 **`H5IndexRecord`（16 B）索引**，不存副本 | `{market}_TRANS.h5`（`H5TransRecord`：3×uint64 + uint8 = 逐笔成交）与 `{market}_TIMELINE.h5`（`H5TimeLineRecord`：3×uint64 = 分时） | 文件 = 市场 × 周期族；dataset = 单票 |
| **WonderTrader** | `his/min1/{exchg}/{code}.dsb`、`his/min5/{exchg}/{code}.dsb`（**一票一文件，全历史追加，zstd 压缩**）；实时侧 `rt/min1/`、`rt/min5/` 的 `.dmb` mmap 块 | **`his/ticks/{exchg}/{date}/{code}.dsb` —— 按日期分目录**；`his/trans/`、`his/orders/`、`his/queue/` 同构。实时 `rt/ticks/{exchg}/{code}.dmb` | **bar 按票、tick 按「日期 × 票」** |
| **vn.py** | `DbBarData` 表带 `interval` 列，日线分钟线同表；唯一索引 `(symbol, exchange, interval, datetime)` | `DbTickData` 单表，30+ FloatField 含五档盘口。DolphinDB 后端则 `PartitionedTableAppender(..., "datetime", pool)` 按时间分区 | SQLite/MySQL 后端**不分片**（这正是它只适合单品种研究的原因）；DolphinDB 后端按 datetime 分区 |
| **RQAlpha** | **bundle 里没有分钟线**。`rqalpha download-bundle` 只给日线（`stocks.h5`/`indexes.h5`/`futures.h5`）+ `trading_dates.npy` + `instruments.pk` + 分红/拆股/复权因子。分钟需 `rqdatac`（米筐商业数据服务） | 同上，无 | — |
| **QUANTAXIS** | MongoDB `stock_min` **单集合装全市场全历史**，索引 `[('code',ASC),('time_stamp',ASC),('date_stamp',ASC)]` | `stock_transaction` 单集合 | **不分片**。这是本对比里最不可扩展的分钟方案 |
| **zvt** | `Stock1mKdata` → **独立 SQLite 文件** `{provider}_stock_1m_kdata.db`；`stock_1m_hfq_kdata` 又是另一个文件 | 无 | 文件 = provider × 周期 × 复权口径 |
| **qteasy** | DataSource 表（csv/hdf/feather/MySQL）。**源码自述 file 模式的增量写要「将下载的数据与本地数据合并，本地数据必须全部下载，数据量大后非常费时，因此本地文件系统承载的数据量非常有限」**（[`database.py` `update_table_data`](https://github.com/shepherdpp/qteasy/blob/master/qteasy/database.py)） | 无 | — |
| **本仓（现状）** | **不落库**。`GET /api/market/minute/{code}` 明确不写 `market.db`（`src/market/api/README.md:5`「分钟线外网拉取本身不写库」）；live 只有进程内 3–5 秒 TTL 缓存（`M2`） | 无 | **实时数据留存能力为零** |

### 3.3 「只留最近 N 天」的先例（`P1` + 本仓 `P1`）

**有，而且不止一处：**

1. **WonderTrader 的 `rt/` 整目录清空**（[`WtDataWriter.cpp:2291-2304`](https://github.com/wondertrader/wondertrader/blob/master/src/WtDataStorage/WtDataWriter.cpp)）：收到清理指令时对 `rt/min1/`、`rt/min5/`、`rt/ticks/`、`rt/orders/`、`rt/queue/`、`rt/trans/` 逐个 `boost::filesystem::remove_all()`。实时块是**当日易失**的，历史在盘后 dump 进 `his/` 才落定。
2. **WonderTrader 的 tick 按日期分目录**：`his/ticks/{exchg}/{date}/{code}.dsb`。**删一天 = 删一个目录**，不影响任何 bar 文件。这是「保留最近 N 天 tick、永久保留 bar」的最小成本实现，直接可抄。
3. **WonderTrader 的逐粒度开关**：`disable_tick` / `disable_min1` / `disable_min5` / `disable_day` / `disable_trans` / `disable_ordque` / `disable_orders`（同文件 `init` 段日志）。**「哪些粒度根本不落地」是一个配置项，不是一次代码改动。**
4. **WonderTrader 过期代码清理**：`WtDataWriter.cpp:2206-2208` 直接 `delete_file` 掉已退市代码的 `rt/ticks/{exchg}/{code}.dmb`。
5. **vn.py 提供了删除原语但没有策略**：`BaseDatabase.delete_bar_data(symbol, exchange, interval)` / `delete_tick_data(symbol, exchange)`，`vnpy_datamanager` 的 UI 里暴露为按合约删除。**是「手动删」不是「自动滚动」**。
6. **本仓已经有一份同型实现**：`src/market/infrastructure/store_hot.py` 的 `HOT_WINDOW_TRADING_DAYS = 700`（≈2.8 年）滚动窗口 + `MIRROR_BUFFER_TRADING_DAYS = 6` 增量缓冲 + `_trim_hot_before()` 裁剪 + 孤儿回执清理。头部注释写明设计动机是**锁隔离**而不是省空间，但机制本身正是「只留最近 N 天」。

### 3.4 对「诉求 3（分钟线/实时留存）」的直接结论

**技术上完全可行，四条设计约束：**

1. **不要进 `market.db`**。分钟线走独立文件，格式二选一：
   - **Parquet 按 `年/月` 分片**（推荐）：实测 19.29 B/行（真实数据按 30–45 B/行规划），DuckDB 直读 196 ms/百万行；工具链已在仓内（polars 1.43.2 + duckdb 1.5.5，无需新依赖）。**一年 9–13 GB，五年 45–65 GB。**
 - Hikyuu 式定长二进制 + `numpy.memmap`：40–56 B/行，零依赖，但要自己写索引。
2. **抄 WonderTrader 的分目录**：`minute/{year}/{month}/{code}.parquet` 或 `minute/{yyyymm}.parquet`。保留策略 = 删目录，零 SQL、零 VACUUM。
3. **抄 Hikyuu 的「多周期只存索引」**：只落 1 分钟基表，5/15/30/60 分钟一律**运行时 resample**，不落副本。落四份副本会把 12.9 GB 变成 ~17 GB 且引入四份不一致风险。
4. **tick 直接放弃全量**。3.31 TB/年（压缩后 0.7–1.1 TB）不是本机方案。真要 tick，只留**当日 + 最近 N 日的观察池成分股**（几十只 × N 天 = 几百 MB 级），用 WonderTrader 的 `{date}/{code}` 目录结构。

**当前的真实缺口不是「分钟线太大」，而是「一根都没有」**：`GET /api/market/minute/{code}` 不写库、live 只有 3–5 秒 TTL 进程内缓存（`M2`）。任何需要盘中回放、竞价复盘、封板时点回溯的研究**现在都无法做事后复核**。这是比存储选型更紧迫的一件事。

---

## 4. 组件化策略框架的抽象对照

### 4.1 Hikyuu：不是六件套，是**九件套**（`P1`）

题面写的 `SYS_Simple = SG+MM+ST+TP+PG+SP` 是**不完整的**。[`SYS_Simple.h`](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/trade_sys/system/crt/SYS_Simple.h) 的实际签名是九个部件：

```cpp
SystemPtr HKU_API SYS_Simple(
  const TradeManagerPtr& tm,   // TM 账户
  const MoneyManagerPtr& mm,   // MM 资金管理
  const EnvironmentPtr&  ev,   // EV 市场环境
  const ConditionPtr&    cn,   // CN 系统前提条件
  const SignalPtr&       sg,   // SG 信号
  const StoplossPtr&     sl,   // ST 止损
  const StoplossPtr&     tp,   // TP 止盈（复用 Stoploss 接口）
  const ProfitGoalPtr&   pg,   // PG 盈利目标
  const SlippagePtr&     sp);  // SP 移滑价差
```

对应枚举 [`SystemPart.h`](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/trade_sys/system/SystemPart.h) 共 10 个值（另加 `PART_ALLOCATEFUNDS` / `PART_PORTFOLIO` 两个组合层部件）。

**关键不是「有九个盒子」，而是盒子之间的三条硬连线**（[`System.cpp`](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/trade_sys/system/System.cpp)）：

**连线 ①：ST 可以否决 SG 的买入。**
```cpp
// System.cpp:732-740
price_t stoploss = _getStoplossPrice(today, src_today, today.closePrice);
if (planPrice <= stoploss) {   // 计划价已经跌破止损 → 这笔不做
    return result;
}
```

**连线 ②：ST 的止损距离就是 MM 的仓位输入。**
```cpp
// System.cpp:743
double number = _getBuyNumber(today.datetime, planPrice, planPrice - stoploss, from);
//     ^price     ^risk = 止损距离
```
而 [`MM_FixedRisk`](https://github.com/fasiondog/hikyuu/blob/master/hikyuu_cpp/hikyuu/trade_sys/moneymanager/imp/FixedRiskMoneyManager.cpp) 的全部实现就是一行：
```cpp
return getParam<double>("risk") / risk;   // 固定风险预算 ÷ 每股风险 = 股数
```
这就是经典 fixed-fractional sizing。**没有 ST 就没有 `risk`，没有 `risk` 就没有 MM。**

**连线 ③：出场优先级 ST → PG → SG-sell，且止损价随持仓走。**
```cpp
// System.cpp:637-643
if (src_current_price <= position.stoploss) {           // ① 止损优先
    tr = _sell(today, src_today, PART_STOPLOSS);
} else if (src_current_price >= _getGoalPrice(...)) {   // ② 盈利目标
    ...
}
```
止损价存在 **持仓记录 `position.stoploss`** 上（`m_tm->buy(..., stoploss, goalPrice, planPrice, from)`），不是每次重算——所以「移动止损」是天然支持的（`tp_ascend` 参数控制止盈是否单调递增）。

`MoneyManagerBase` 还有 `_buyNotify` / `_sellNotify` 与 `currentBuyCount` / `currentSellCount`，**MM 知道自己已经连续加了几次仓**——金字塔加仓 / 减仓是一等公民。

### 4.2 vn.py：CtaTemplate 生命周期（`P1`）

[`vnpy_ctastrategy/template.py`](https://github.com/vnpy/vnpy_ctastrategy/blob/main/vnpy_ctastrategy/template.py) 的 `CtaTemplate` 是**回调式**而非部件式：

- **状态**：`inited` / `trading` / `pos`（三个变量自动进 `variables`）
- **生命周期回调**：`on_init`（abstract）→ `on_start` → 运行中 `on_tick` / `on_bar` / `on_order` / `on_trade` / `on_stop_order` → `on_stop`
- **动作**：`buy` / `sell` / `short` / `cover` 四个方向语义的下单，统一收敛到 `send_order(direction, offset, price, volume, stop, lock, net)`
- **`stop=True` 是本地停止单**：由 CTA 引擎在本地维护、条件触发时才真发委托（`on_stop_order` 回调），这是 vn.py 对「止损」的答案——**它是一个订单类型，不是一个策略部件**
- **参数/变量声明式**：`parameters: list` / `variables: list` 两个类属性，引擎据此做 UI 表单、参数优化与状态持久化

**与 Hikyuu 的根本差异**：vn.py 把 MM/ST 的责任**推给策略作者自己在 `on_bar` 里写**。框架只保证「你发的单会被正确执行、状态会被正确持久化」。这对期货单品种 CTA 够用，对多标的组合就要上 `vnpy_portfoliostrategy`（把 `pos` 换成 `dict[vt_symbol, int]`）。

### 4.3 RQAlpha：mod 机制（`P1`）

[`rqalpha/mod/__init__.py`](https://github.com/ricequant/rqalpha/blob/master/rqalpha/mod/__init__.py) 的 `ModHandler`：

- 从 `config.mod` 读所有 mod，`enabled` 为假直接跳过
- 名字解析：系统 mod（`SYSTEM_MOD_LIST` 七个：`sys_accounts` / `sys_analyser` / `sys_progress` / `sys_risk` / `sys_simulation` / `sys_transaction_cost` / `sys_scheduler`）映射到 `rqalpha.mod.rqalpha_mod_{name}`，第三方映射到 `rqalpha_mod_{name}`
- **`_mod_list.sort(key=lambda item: getattr(item[1], "priority", 100))`** —— **加载顺序由 mod 自己声明的 `priority` 决定**，不是配置顺序
- 生命周期：`start_up(env, mod_config)` 正序、`tear_down()` **逆序**（含 `ExceptionGroup` 聚合异常）

**这个设计的真正价值在于：撮合、账户、风控、成本、分析全部是可替换的 mod。** 想换撮合规则就换 `sys_simulation`，想换手续费模型就换 `sys_transaction_cost`，框架内核（事件循环 + Environment）不动。`AbstractFrontendValidator` 是风控的扩展点，`AbstractTransactionCostDecider` 是成本的扩展点，`AbstractMatcher` 是撮合的扩展点。

### 4.4 对照本仓 `StrategyEngine`：缺了哪几件

本仓 `src/strategy/domain/base.py` 的 Protocol（`P1`，本轮已读）：

```python
class StrategyEngine(Protocol):
    slug / name / description / entry_timing
    def default_params(self) -> dict
    def required_fields(self) -> tuple[str, ...]
    def min_bars(self) -> int
    def compute(self, panels, params) -> SignalResult   # signals + factors + watch_signals
```

`SignalResult` = `signals: DataFrame`（日期 × 代码的布尔面板）+ `factors: dict[str, DataFrame]`（归因）+ `watch_signals`。**只有「今天买哪些」，没有「买多少」「什么时候卖」「亏多少认输」。**

| 部件 | Hikyuu | vn.py | RQAlpha | **本仓** | 缺位的直接后果 |
|---|---|---|---|---|---|
| **SG 信号** | `SignalBase` | `on_bar` 里发单 | 策略函数 `handle_bar` | ✅ `compute() → signals` | — |
| **EV 市场环境** | `EnvironmentBase`（大盘可交易否） | 无 | 无 | ⚠ 部分：`watch_signals` 弱市降级、部分战法带 `breadth` 因子，但**不是独立可替换部件** | 择时与选股混在同一个 `compute` 里，无法单独关掉择时做归因（`2026-08-tail-1450-next-day-touch-backtest.md` §「日内截面中性化是分水岭」已踩过） |
| **CN 系统前提** | `ConditionBase`（+ `CN_Logic` 与或非组合） | 无 | `sys_risk` validator | ⚠ 混在 `compute` 的布尔表达式里 | 无法把「前提」与「信号」分开统计命中率 |
| **ST 止损** | `StoplossBase.getPrice(dt, price)` | 本地停止单（`stop=True`） | 无（用户自己 `order_target`） | ❌ **完全没有** | **`MFE >> 净收益` 的直接成因。**没有止损价 → 没有风险距离 → 没有仓位模型 → 唯一出场是「持有 N 日到期」 |
| **TP 止盈** | 复用 `StoplossBase`，`tp_ascend` 支持单调递增（移动止盈） | 同上 | 无 | ❌ **完全没有** | 回测里只能用固定持有期；`2026-08-tail-1450-next-day-touch-backtest.md` 实测「止盈越紧盈亏比越低（0.5%→0.166、2%→0.709、不封顶→1.049）」——这个单调序**本该是 TP 部件的参数网格，现在是一次性脚本** |
| **PG 盈利目标** | `ProfitGoalBase`（`PG_FixedPercent` / `PG_FixedHoldDays`） | 无 | 无 | ⚠ 只有「持有 N 日」硬编码在回测器里 | `PG_FixedHoldDays` 正是我们在用的东西，但它现在是回测器的选项而不是策略声明的一部分 |
| **MM 资金管理** | `MoneyManagerBase._getBuyNumber(dt, stock, price, risk, from)`，8 个内置（FixedRisk / FixedPercent / FixedUnits / WilliamsFixedRisk / …），带 `buyNotify` 加仓计数 | 策略自己算 volume | `order_target_portfolio` API | ❌ **完全没有**。组合层只有「Top-N 等权」 | 无法做风险平价、无法按波动率缩放仓位、无法金字塔加仓。`2026-08-dragon-survivorship-and-portfolio-fragility.md` 记录的「信号数差 3.4%、组合收益差 187%」正是组合层缺乏仓位模型时的脆弱性表现 |
| **TM 账户** | `TradeManager`（含权息调整交易记录） | `OmsEngine` | `Portfolio/Account/Position` | ❌ 回测器内部临时对象，**`strategy_backtests` / `strategy_versions` 两张表 0 行**（`M2`）——回测结果零持久化 | 无法跨版本比对、无法回放 |
| **SP 滑点** | `SlippageBase` | 引擎参数 | `SlippageDecider`（可插拔模型） | ⚠ 回测器里的固定成本参数（3/5/10 bp） | 无法建模冲击成本随成交额变化 |
| **AF 资金分配** | `AllocateFundsBase`（EqualWeight / FixedWeight / MultiFactor） | `vnpy_portfoliostrategy` | `order_target_portfolio` | ⚠ Top-N 等权硬编码 | 同 MM |

**最小可行补齐（不改 `compute` 契约，只加声明）**：

`StrategyEngine` 的优点是「一个 `compute` 打天下」，不该推翻。建议**加一组可选声明**，让回测器有地方读：

```python
class StrategyEngine(Protocol):
    ...
    # 新增（都可选，缺省即现状）
    def exit_rule(self) -> ExitRule: ...   # ST/TP/PG 三合一：止损价函数 + 止盈价函数 + 最大持有日
    def position_sizer(self) -> Sizer: ...      # MM：给 (price, risk, cash, n_signals) 出股数
```

其中 `ExitRule` 至少要能表达 Hikyuu 那三条连线：

1. **`stop_price(entry_price, bars) -> float`** —— 有了它，回测器就能在 `planPrice <= stoploss` 时**拒绝这笔入场**（Hikyuu `System.cpp:736`），这一条本身就会改变信号集。
2. **`risk = entry_price - stop_price` 喂给 `position_sizer`** —— 这是把「MFE 高」变成「净收益高」的机械路径：波动大的票自动少买。
3. **出场优先级固定为 ST → TP/PG → 信号消失**，并在逐笔记录里标出 `exit_reason`（Hikyuu 的 `PART_STOPLOSS` / `PART_PROFITGOAL` / `PART_SIGNAL`）。**现在所有战法的逐笔记录里没有这一列，所以「退出纪律缺失」只能靠 MFE 间接推断，无法直接归因。**

**这三条里第 3 条成本最低、信息量最大，建议先做。**

---

## 5. A 股特有约束的实现对照

| 约束 | **RQAlpha** | Hikyuu | vn.py | QUANTAXIS | zvt / qteasy | WonderTrader | **本仓** |
|---|---|---|---|---|---|---|---|
| **T+1** | ✅ `StockPosition.t_plus_enabled = True`；`apply_trade()` 里开仓即 `self._non_closable += trade.last_quantity`；`closable` 属性扣掉 `_non_closable`；`market_tplus` 来自 instrument（A 股 = 1，公募基金 = 0）。[position_model.py](https://github.com/ricequant/rqalpha/blob/master/rqalpha/mod/rqalpha_mod_sys_accounts/position_model.py) | ⚠ 靠 `TradeManager` 的 `getHoldNumber`，无显式 T+1 标志 | ❌ 面向期货，无 | ⚠ QAAccount 有 `sell_available` 概念 | ❌ | ⚠ 由柜台/交易所侧保证 | ✅ 隐含（`entry_timing` 四值全部是隔日或同日单向，无同日买卖） |
| **涨跌停不可成交** | ✅✅ **两层**：事前 [`PriceValidator`](https://github.com/ricequant/rqalpha/blob/master/rqalpha/mod/rqalpha_mod_sys_risk/validators/price_validator.py) 拒绝越界限价单；撮合时 [`BaseMatcher.match`](https://github.com/ricequant/rqalpha/blob/master/rqalpha/mod/rqalpha_mod_sys_simulation/matcher/base.py) 调 [`reaches_limit()`](https://github.com/ricequant/rqalpha/blob/master/rqalpha/utils/price_limits.py) —— **限价单抛 `OrderNotMatchable`（保持 Active），市价单抛 `OrderRejected`**。判据是 `price >= limit_up - tick_size + 1e-6`（**留一个最小变动价位的容差**） | ❌ | ❌ | ⚠ | ❌ | ⚠ | ❌ **未实现，且缺数据基础**（见下） |
| **涨跌停价的来源** | ✅✅ **当成行情字段存进 bundle**：`SecuritiesDayBarStore.DEFAULT_DTYPE = 基础 dtype + ('limit_up', f8) + ('limit_down', f8)`（[storages.py](https://github.com/ricequant/rqalpha/blob/master/rqalpha/data/base_data_source/storages.py)）。**不按板块算规则** | — | — | — | — | tick 结构里有 `upper_limit`/`lower_limit`（[WTSStruct.h](https://github.com/wondertrader/wondertrader/blob/master/src/Includes/WTSStruct.h)） | ❌ `quotes_daily` 无这两列（`src/market/infrastructure/store_schema.py`），只能按 `classify_board` + 名称是否含 ST 反推 |
| **停牌** | ✅ [`IsTradingValidator`](https://github.com/ricequant/rqalpha/blob/master/rqalpha/mod/rqalpha_mod_sys_risk/validators/is_trading_validator.py) → `data_proxy.is_suspended()`；另有 `_inactive_limit`（bar volume==0 直接撤单） | ❌ | ❌ | ⚠ | ❌ | ⚠ | ⚠ `instruments.status` 有 `suspended` 枚举，但回测未消费 |
| **除权除息 / 复权因子** | ✅✅ **两条线并行**：①价格侧 [`adjust_bars()`](https://github.com/ricequant/rqalpha/blob/master/rqalpha/data/base_data_source/adjust.py) 用 `ex_cum_factor` 前/后复权，**`limit_up`/`limit_down` 也在 `PRICE_FIELDS` 里一起复权，`volume` 反向除**；②账户侧 `StockPosition.before_trading()` 真实模拟：先 `_handle_dividend_book_closure`（除息日调 `_avg_price` 与 `_last_price`）→ `_handle_split`（拆股）→ `_handle_dividend_payable`（**到 `payable_date` 才真正到账**，支持 `dividend_reinvestment`） | ⚠ 有权息调整交易记录 | ❌ | ✅ `stock_xdxr` + `stock_adj` 两个集合，`_QA_data_stock_to_fq` | ✅ zvt 有 `stock_1d_hfq_kdata` 独立库 | ❌ | ⚠ `adjust_factors` 稀疏表（只有除权日有行，读时前向填充），**只做价格复权，不模拟分红到账** |
| **ST / 退市** | ✅ `Instrument.special_type`（`Normal`/`ST`/`StarST`/`PT`/`Other`）+ `status`（`Active`/`Delisted`/`TemporarySuspended`/`PreIPO`/`FailIPO`）；退市在 `settlement()` 里处理：`de_listed_at(next_date)` → 先查 `get_share_transformation()`（**股改换股，按 `conversion_ratio` 转成继承标的**），否则 `cash_return_by_stock_delisted` 折现返还 | ❌ | ❌ | ⚠ | ⚠ | ❌ | ❌ **硬伤**：`M2` 实测 `instruments.delist_date` **填充数 = 0**，`status` 分布 `delisted=1 / normal=5546`。存活偏差在 `2026-08-dragon-survivorship-and-portfolio-fragility.md` 已被判定「本地不可测」，本轮 dbstat **实锤了成因** |
| **板块不同涨跌幅** | ✅ **不需要规则表**——`limit_up`/`limit_down` 逐日来自数据。另有 `Instrument.board_type`（`MainBoard`/`GEM`/`KSH`）供策略过滤 | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠ `classify_board` 按代码前缀分类（含 `920xxx` 北交所），但**没有涨跌幅数据** |
| **最小 100 股 / 科创板 1 股递增** | ✅✅ `Instrument.round_lot`：**`if type == CS and board_type == "KSH": return 1`**，否则读数据里的 `round_lot`（A 股 100）。撮合侧 `round_order_quantity(instrument, volume_limit)`；部分成交时按 `instrument.min_order_quantity` + `order_step_size` 递减 | ✅ `Stock::minTradeNumber()`，`System.cpp:744-746` 里 `number = int64_t(number / min_num) * min_num` | ⚠ 合约 `size` | ⚠ | ❌ | ⚠ | ⚠ 组合层等权分配，未见 100 股取整 |
| **印花税单边 + 税率历史切换** | ✅✅ [`StockTransactionCostDecider`](https://github.com/ricequant/rqalpha/blob/master/rqalpha/mod/rqalpha_mod_sys_transaction_cost/deciders.py)：`_calc_tax()` 里 **`if side == BUY or instrument.type != CS: return 0`**（单边、且只对股票不对 ETF）；`pit_tax` 开启后挂 `PRE_BEFORE_TRADING` 事件，以 **`STOCK_PIT_TAX_CHANGE_DATE = datetime(2023, 8, 28)`** 为界在 0.001 / 0.0005 之间切换。佣金侧还实现了「最低佣金 5 元只收一次、分笔成交时逐笔抵扣」的完整逻辑 | ⚠ `TradeCostBase` 可自定义 | ⚠ 参数 | ⚠ | ❌ | ⚠ | ⚠ 回测器固定成本参数 3/5/10 bp（双边合计），**未区分买卖、未处理 2023-08-28 税率切换** |

**结论：RQAlpha 是唯一把 A 股八条约束都做到「可核验源码级」的框架，而且做法最省事的一条是「把涨跌停价当行情字段存下来」。**

**对本仓最高性价比的三条抄袭：**

1. **`quotes_daily` 加 `limit_up` / `limit_down` 两列**（+16 B/行）。这一条同时解决：主板/双创/北交所差异、ST 5%→10% 新规（2026-07-06 生效，已在 `_scratch_2026-08-tail-close-external-primary-sources.md` §2.1 核验）、新股首日无限制、以及最重要的——**回测里「一字板买不进」这件事**。现在所有涨停相关战法的回测都默认能在涨停价成交，这是**系统性高估**。
2. **印花税改成单边 + 按日期切换税率**。现行 3/5/10 bp 双边参数会**高估买入成本、低估卖出成本**；在换手极高的短线战法上这个偏差不小。RQAlpha 的 `STOCK_PIT_TAX_CHANGE_DATE = 2023-08-28` 可以直接照抄。
3. **`instruments.delist_date` 必须回填**。`M2` 实测 0 条填充、`delisted` 只有 1 只。这不是「难测」，是「没采」。

---

## 6. 数据源生态

### 6.1 横向对比（`P1` = 官方文档/源码；`M1` = 本仓实测）

| 源 | 接入方式 | 免费额度 | 是否爬网页 | 历史深度 | 更新延迟 | 分钟线 | 活跃度（快照 2026-08-25） | 许可证 |
|---|---|---|---|---|---|---|---|---|
| [**AkShare**](https://github.com/akfamily/akshare) | pip，无需 key | **完全免费、无额度** | ✅ **是**——本质是东财/新浪/同花顺/交易所页面与内部 JSON 接口的封装。上游改版即断 | 依上游，日线通常全历史 | 日线盘后；spot 实时 | ✅（东财 push2his） | release **v1.18.94 @ 2026-08-21**；**22,223★**；**0 open issues**（维护极勤） | MIT |
| [**Tushare** Pro](https://tushare.pro/) | pip + token | **120 积分 = 50 次/分、8,000 次/天，且仅「非复权日线」**（[积分与频次权限对应表](https://tushare.pro/document/1?doc_id=290)，`P1` 本轮读到原文） | ❌ 自有服务器 | 日线全历史；**历史分钟 2009 年起** | 盘后 | ❌ **分钟不在积分体系内，单独 2,000 元/年**；实时分钟 1,000 元/月 | GitHub 仓库 [waditu/tushare](https://github.com/waditu/tushare) **最后 push 2024-03-13**、755 open issues（**旧版 SDK，Pro 走 HTTP API**）；15,364★ | BSD-3-Clause（SDK） |
| **baostock** | pip，`bs.login()` 无需注册 | **完全免费** | ❌ 自有数据服务器（[官网 baostock.com](http://baostock.com)，**本轮该站返回空页面，`✗` 未取到官方文档原文**；接口签名取自 [PyPI 包描述](https://pypi.org/pypi/baostock/json)，`P2`） | 日线全历史 | 盘后 | ✅ 5/15/30/60 分钟（`frequency` 参数） | PyPI **0.9.3**（发布节奏极慢，最早版本 2018-01） | BSD License（PyPI 元数据） |
| [**pytdx**](https://github.com/rainx/pytdx) | pip，直连通达信行情服务器（二进制协议） | 免费（服务器为券商公共行情站） | ❌ 二进制协议 | 日线/分钟均较深 | 准实时 | ✅ | **仓库已 archived**，最后 push **2020-04-15**；1,553★ | 无 LICENSE 文件 |
| [**mootdx**](https://github.com/mootdx/mootdx) | pytdx 的现代化封装 | 同上 | ❌ | 同上 | 准实时 | ✅ | release **v0.11.7 @ 2024-05-05**；pushed 2024-07-16；2,225★；99 open issues | MIT |
| [**adata**](https://github.com/1nchaos/adata) | pip，多源聚合（东财/百度/腾讯/同花顺）+ 代理池 | 免费 | ✅ 是 | 日线全历史 | 盘后 | ⚠ 有限 | release **v2.9.0 @ 2025-04-02**；pushed 2025-12-26；5,123★；36 open issues | Apache-2.0 |
| [**efinance**](https://github.com/Micro-sheep/efinance) | pip，东财接口封装 | 免费 | ✅ 是（东财） | 日线全历史 | 盘后/实时 | ✅ | release **v0.5.5 @ 2025-03-15**；pushed 2026-07-17；3,955★；**151 open issues** | MIT |
| [**easyquotation**](https://github.com/shidenggui/easyquotation) | pip，实时行情多源（新浪/腾讯/集思录） | 免费 | ✅ | **只有实时，无历史** | 秒级 | ❌ | **无 Release**；pushed 2026-02-28；5,370★ | MIT |

### 6.2 本仓一手实测（`M1`，源自 `src/market/README.md:207-224` 与 `scripts/benchmark_data_sources.py`）

样本 40 只 × 320 根、并发梯度 1/4/8/16/32：

| 源 | 最佳吞吐 | 单票 p50 | 折算全市场 5,544 只 | 字段完整度 |
|---|---|---|---|---|
| **通达信 tdx** | **217 票/秒** | **28 ms** | **26 s** | 7/8（缺换手率） |
| 新浪 sina | 17.6 票/秒 | 275 ms | 315 s | 8/8 |
| 腾讯 tencent | 12.5 票/秒 | 202 ms | 445 s | 7/8（缺换手率） |
| 证券宝 baostock | **0.57 票/秒** | 1,675 ms | **9,726 s（2.7 小时）** | 8/8 |
| 东财 eastmoney | 本机代理下取数失败 | — | — | — |

**两条被实测推翻的直觉**：

- **「字段全 = 源好」是错的**。baostock 字段 8/8 最全，但 0.57 票/秒 —— 全市场一轮 2.7 小时，**只能做抽检对账，不能做主源**。
- **「成交额都是真的」是错的**。腾讯日 K 的 `amount` 是 `close × volume` **合成值**（库内实测 `amount/(close*volume)` 恒为 1.0000），通达信给的是**真实成交额**。任何依赖成交额的因子（换手、量比、金额分位）在腾讯源下都是错的。
- **通达信的代价也如实记录**：`vol` 是整数手，×100 后 `volume` 总是 100 的倍数，单根偏差 <100 股（典型 ~0.0001%）；北交所（`920xxx`）必须走 `market=2`，漏了会静默缺 339 只。

### 6.3 判断：A 股短线量化最值得接的免费数据源组合

**推荐组合（四层）**：

| 层 | 源 | 理由 |
|---|---|---|
| **主源：日线 + 分钟线** | **通达信（tdxpy / mootdx）** | 217 票/秒、全市场 26 秒、成交额是真值、分钟线可跨历史日期。**唯一能让「全市场分钟线每日增量」在分钟级完成的免费源。** 短线量化对「盘后 30 分钟内拿到全市场数据」的刚性需求，只有它满足 |
| **衍生面** | **AkShare** | 资金流、龙虎榜、概念板块、公告、股东、竞价——这些通达信协议里没有，且 AkShare 是唯一免费全覆盖的。**代价是爬网页，上游改版即断**，所以只能放在「衍生面」不能放在「行情主源」 |
| **对账 / 独立性** | **baostock** | 8/8 字段全 + **不经东财/新浪，是真正的独立第三方**。用法是**抽检**：每天随机 50–200 只票与主源逐格对账，命中偏差即告警。0.57 票/秒在抽检量级完全够 |
| **实时 spot / 复权因子** | **新浪 + 腾讯** | 本仓已在用（live 顶栏 sina/tencent 竞速、复权因子走新浪 `fetch_hfq_factors`）。easyquotation 是同一批上游的另一层封装，**没有增量价值，不建议再引** |

**明确不推荐**：

- **Tushare 免费档不可用于短线**。120 积分只给非复权日线、8,000 次/天；全市场 5,547 只单是日线增量就要 5,547 次，**一天只够跑 1.4 轮**。分钟线在积分体系之外，2,000 元/年。它的定位是「稳定的付费数据服务」，不是「免费源」。
- **pytdx 已 archived（2020-04-15），新项目不要直接依赖**。要用通达信协议就用 mootdx 或本仓已在用的 tdxpy。
- **adata / efinance 与 AkShare 高度重叠**（同为东财系爬取），引入第三个同源封装只增加维护面，不增加独立性。**除非需要 adata 的代理池来扛封 IP。**
- **easyquotation 无历史数据**，能力被现有 sina/tencent adapter 完全覆盖。

**一条结构性提醒**：上表七个免费源里，**五个（AkShare / adata / efinance / easyquotation / 部分 baostock 场景）最终指向东财或新浪**。所谓「多源冗余」在上游是同一批服务器。**真正的源级独立只有三条腿：通达信二进制协议、baostock 自有服务器、交易所官网。** 本仓的 lane 回退链（tdx → tencent → eastmoney → baostock → sina）在这个意义上是健康的——它跨了三个协议族。

---

## 7. 给本仓的可执行清单（按性价比）

| # | 动作 | 依据章节 | 成本 | 收益 |
|---|---|---|---|---|
| 1 | 逐笔记录加 `exit_reason` 列（`stoploss` / `takeprofit` / `holddays` / `signal`） | §4.4 | 极低 | 「退出纪律缺失」从 MFE 间接推断变成直接归因 |
| 2 | 溯源从「每行一列 + 全表索引」改为「按批次区间」，删 `idx_quotes_receipt` | §2.5 / §2.6 | 低 | 立减 ~1,300 MB（全库 23%） |
| 3 | `quotes_daily` 加 `limit_up` / `limit_down` 两列 | §5 | 低（+16 B/行） | 涨停战法回测从「系统性高估」变成可信；一次性解决所有板块差异 |
| 4 | 印花税改单边 + 按 2023-08-28 切换税率 | §5 | 低 | 高换手战法的成本模型不再系统性偏斜 |
| 5 | 回填 `instruments.delist_date` | §5 | 中 | 存活偏差从「本地不可测」变成可测 |
| 6 | `StrategyEngine` 加可选 `exit_rule()` / `position_sizer()` 声明 | §4.4 | 中 | MM/ST 从「每个战法自己在脚本里凑」变成框架能力 |
| 7 | 分钟线落 Parquet（`minute/{yyyy}/{mm}/`），按目录做 N 天保留 | §3.4 | 中 | 补上「实时留存能力为零」这个洞；一年 9–13 GB |
| 8 | 重新基准化 `LOCI_MARKET_DUCKDB` | §2.4 | 低 | 本轮实测该旁路比裸 pandas 慢 2.9×，可能是净负收益 |
| 9 | TEXT 主键 → INTEGER | §2.6 | 高（迁移） | 数据页再减 ~50%（建议与 #2 合并做一次迁移） |

---

## 8. 缺口与未核验清单

| # | 项 | 状态 |
|---|---|---|
| 1 | **baostock 官方文档原文** | `✗` `baostock.com` 与 `www.baostock.com` 本轮均返回空页面（JS 渲染或拦截）。接口签名与字段列表取自 [PyPI 包描述](https://pypi.org/pypi/baostock/json)（`P2`）。**「历史深度 1990-12-19 起」「分钟线 5/15/30/60」两条未由官方原文确认** |
| 2 | **vn.py 子仓 stars / release** | `✗` GitHub 匿名 API 配额（60 req/h）本轮耗尽，`vnpy_ctastrategy` 等 13 个仓的 stars 未取到。主表七个核心项目的数字均已取到 |
| 3 | **Parquet 19.29 B/行** | `M1` 但**合成数据**。真实 A 股日线压缩率更差，规划请按 30–45 B/行。已在 §2.3 显式标注 |
| 4 | **tick 3.31 TB/年** | `M1` 计算，输入参数（3 秒快照、4,800 笔/日）为**行业通行口径，本轮未取交易所官方原文**。`WTSTickStruct` 512 B 是从源码字段逐个加出来的（`P1`） |
| 5 | **`WTSBarStruct` 88 B / `WTSTickStruct` 512 B** | `P1` 结构定义已读，但**未编译验证 `sizeof()`**。`#pragma pack(push,8)` 下按字段累加，与 8 字节对齐一致 |
| 6 | **WonderTrader `rt/` 清空的触发条件** | `P1` 代码路径已读（`remove_all` 六个目录），但**未确认是「每日盘后自动」还是「手动指令」**。源码上下文是一个命令队列的分支 |
| 7 | **QUANTAXIS 的 MongoDB 单文档字节数** | `✗` 未实测。BSON 逐文档重复字段名，估计在 200–400 B/文档，但**未验证**，故未进 §2.3 表 |
| 8 | **`DISTINCT trade_date` 与仓库注释矛盾** | `M1`：`EXPLAIN QUERY PLAN` 报 `SCAN quotes_daily`，但冷进程实测 **24.8–57.1 ms**（2,430 个值），远快于真扫 2.47 GiB 所需时间 → SQLite 在 `WITHOUT ROWID` 的 PK 前缀上做了跳跃寻道。`store_schema.py:71-74` 注释里「全市场会涨到近 10s」在 SQLite 3.50 + 当前 schema 下**不再成立**。`trading_calendar` 表现在的价值是**语义**（哪天是交易日 ≠ 哪天有行情行），不再是性能 |
| 9 | **本轮所有耗时数字** | Windows / 单机 / 页缓存状态不完全受控。数量级可信，绝对值不可跨机复用 |

---

## 9. 一手来源清单

**GitHub 仓库（stars / release 快照 2026-08-25，经 REST API）**
- vn.py <https://github.com/vnpy/vnpy> ｜ Hikyuu <https://github.com/fasiondog/hikyuu> ｜ WonderTrader <https://github.com/wondertrader/wondertrader> ｜ RQAlpha <https://github.com/ricequant/rqalpha> ｜ QUANTAXIS <https://github.com/yutiansut/QUANTAXIS> ｜ zvt <https://github.com/zvtvz/zvt> ｜ qteasy <https://github.com/shepherdpp/qteasy>
- AkShare <https://github.com/akfamily/akshare> ｜ Tushare <https://github.com/waditu/tushare> ｜ adata <https://github.com/1nchaos/adata> ｜ efinance <https://github.com/Micro-sheep/efinance> ｜ pytdx <https://github.com/rainx/pytdx>（archived）｜ mootdx <https://github.com/mootdx/mootdx> ｜ easyquotation <https://github.com/shidenggui/easyquotation>

**源码文件（`P1`，本轮逐个读过）**
- vn.py：`vnpy/trader/database.py`、`vnpy_ctastrategy/template.py`、`vnpy_sqlite/sqlite_database.py`、`vnpy_dolphindb/dolphindb_database.py`、`vnpy_datamanager/engine.py`
- Hikyuu：`trade_sys/system/crt/SYS_Simple.h`、`system/System.h`、`system/System.cpp`、`system/SystemPart.h`、`moneymanager/MoneyManagerBase.h`、`moneymanager/imp/FixedRiskMoneyManager.cpp`、`stoploss/StoplossBase.h`、`data_driver/kdata/hdf5/H5Record.h`、`H5KDataDriver.cpp`
- WonderTrader：`src/WtDataStorage/DataDefine.h`、`WtDataWriter.cpp`、`src/WtDataStorageAD/DataDefineAD.h`、`src/Includes/WTSStruct.h`、`WTSMarcos.h`、`src/WTSUtils/WTSCmpHelper.hpp`
- RQAlpha：`data/base_data_source/storages.py`、`data/base_data_source/adjust.py`、`data/bundle/__init__.py`、`model/instrument.py`、`mod/__init__.py`、`mod/rqalpha_mod_sys_simulation/matcher/base.py`、`matcher/bar_matcher.py`、`mod/rqalpha_mod_sys_accounts/position_model.py`、`mod/rqalpha_mod_sys_transaction_cost/deciders.py`、`mod/rqalpha_mod_sys_risk/validators/price_validator.py`、`is_trading_validator.py`、`utils/price_limits.py`
- QUANTAXIS：`QUANTAXIS/QASU/save_tdx.py`
- zvt：`src/zvt/contract/storage.py`、`src/zvt/contract/api.py`、`src/zvt/domain/quotes/stock/stock_1d_kdata.py`
- qteasy：`qteasy/database.py`、`qteasy/blender.py`

**官方文档（`P1`）**
- Tushare 积分与频次权限对应表 <https://tushare.pro/document/1?doc_id=290>（本轮读到全文，含表一/表二完整价目）
- AkShare README <https://github.com/akfamily/akshare/blob/main/README.md>
- baostock PyPI 元数据 <https://pypi.org/pypi/baostock/json>（`P2`，官网未取到）

**本轮本机实测（`M1`）**
- `/tmp/qbcn/bench_size.py` → `/tmp/qbcn/bench/result_size.json`（四种落法的体积）
- `/tmp/qbcn/bench_query.py` → `/tmp/qbcn/bench/result_query.json`（九类查询的延迟 + `EXPLAIN QUERY PLAN`）
- 环境：Windows / Python 3.12.13 / SQLite 3.50.4 / numpy 2.4.6 / pandas 3.0.5 / polars 1.43.2 / duckdb 1.5.5

**主 agent dbstat 实测（`M2`，2026-08-25，只读）**
- 真实数据目录 `E:\entertainment_software\Loci\data`：`market.db` 5,740.2 MB 全表/全索引分解、`market_hot.db` 1,022.1 MB、`ops.db` 13.8 MB、`palace.db` 0.8 MB、`instruments` 填充度、`quotes_daily` 逐年行数

**本仓源码（`P1`）**
- `src/strategy/domain/base.py`（`StrategyEngine` Protocol）
- `src/market/infrastructure/store_schema.py`（`quotes_daily` DDL）
- `src/market/infrastructure/store_hot.py`（700 交易日滚动窗口）
- `src/market/infrastructure/store_panel.py`、`tape/local_provider.py`（宽扫护栏与相关子查询的既有实测记录）
- `src/market/README.md:207-224`（数据源吞吐实测表）
- `src/market/api/README.md:5`（分钟线不写库）

**本仓既有研究文档（交叉引用）**
- `2026-08-dragon-survivorship-and-portfolio-fragility.md`（存活偏差、组合层脆弱性）
- `2026-08-tail-1450-next-day-touch-backtest.md`（止盈松紧与盈亏比的单调序）
- `2026-08-incumbent-strategy-full-sample-benchmark.md`（战法全样本标尺）
- `_scratch_2026-08-tail-close-external-primary-sources.md`（三所交易规则，含 ST 涨跌幅 5%→10% 新规）
- `2026-08-github-open-source-technology-radar.md`（项目级雷达，ClickHouse 已列 Reject）

---

## 摘要（≤300 字）

做分钟/tick 的三家都离开关系库，走定长记录+一票一 dataset；用 SQLite 的一律分库。每行字节实测：现行 DDL 193.78、精简 69.96、Hikyuu 40、Parquet 19.29——天生税只 1.75×，其余 2.77× 出自我们的 schema；真库 44.8% 是溯源审计，宽面板慢 9.5×。分钟线 3.235 亿行/年 =12.9–62.7 GB，tick 3.31 TB/年；保留先例见 WonderTrader 按日期分目录。策略缺 ST/TP/PG/MM/TM——止损距离即 MM 的 risk，即 MFE 高而净收益低的成因。A 股约束 RQAlpha 最全，最该抄 limit_up/limit_down 存为行情字段。
