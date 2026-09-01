# 数据层：体量、分层保留与加密留存（scratch）

> **日期**：2026-08-25 ｜ **检索日期**：2026-08-25
> **用途**：直接回答用户诉求 2（历史数据不需要那么庞大）与诉求 3（实时数据加密留存 30–60 天）。供上层综述引用。
> **范围**：**只读 + 本机实测**。除本文件外未改任何仓库文件，未 commit / push，未写任何生产库。所有实测脚本落在系统临时目录 `%TEMP%/qbstore/`，不入仓。对生产库 `E:\entertainment_software\Loci\data\*.db` 全部走 `READ_ONLY` / `mode=ro` 挂载，只跑 SELECT。
> **证据分级**：`M` 本轮本机实测（脚本与命令在正文给出，可复跑）；`M*` 主 agent dbstat 实测 2026-08-25（直接引用）；`P1` 官方原文全文已读；`P2` 官方/权威页摘要或社区多源互证；`✗` 未找到一手来源。
> **与既有文档的关系**：`docs/quant-toolkit.md` 记的「5532 只 / 1671 万行 / **2.4 GB**」**已过时**，真实是 **5,740.2 MB**（见 §A1.1，⚠ 修正）。[`ADR-002`](../adr/ADR-002-duckdb-readonly-panel.md)（DuckDB 只读旁路）与 [`ADR-007`](../adr/ADR-007-market-hot-readonly-window.md)（700 日热窗）是本文 §A2 的评估对象。`docs/master-plan-2026-07.md` §4.2 当年拍板「不上 DuckDB，量级到 1250 万行再说」——现在是 1,697 万行，那个触发条件**已经到了**。

---

## 0. 一句话结论

**体量问题的真凶不是历史长度，是行存 + 逐行溯源。** 全市场 1,697 万行日线在 Parquet+Zstd 里只有 **395.6 MB**（实测），而同一份数据在 SQLite 里连索引一共 **4,196.9 MB**——**10.6 倍**。整个 `market.db` 5,740.2 MB 里 **44.8% 是溯源审计表和它们的索引**，而这三列在列存里加起来只值 **0.6 MB**。所以「历史数据太庞大」的正确解法不是删年份，是**换格式**：36 年全历史 + 全部溯源列，一个 400 MB 的文件装得下。

**历史该留多长，取决于你要测什么，实测给出两个不同答案。** 用生产库 2010 年以来 1,029 万条样本实测：短周期收益的**截面残差 σ（超额口径）**在 2010–2014 / 2015–2018 / 2019–2021 / 2022–2026 四段里只在 **4.75%–5.35%** 之间抖动——**测截面 alpha 不需要长历史，3–5 年够**。但**总收益 σ** 在 2015 年是 **9.57%**、2017 年是 **4.83%**，差一倍——**要诚实的回撤和组合风险，就必须留住 2015/2018 这些年份**。结论：**按列分层，不按年份分层**。

**「样本大不等于结论强」这句话有确切的数值。** 实测同日截面相关 **ICC = 0.2822**（3 日持有）。潜龙原版 24,878 笔的日均信号数是 39.6，设计效应 11.9，**有效独立样本只有 2,090 笔**，t(超额)=**2.13**；分手快乐 495 笔日均只发 1.2 个信号，t(超额)=**3.14**。24,878 笔输给 495 笔，不是玄学。

**加密方案有一个明确赢家，而且是免费的。** DuckDB 1.5.5 **原生支持 Parquet Modular Encryption**（AES-GCM），实测：体积持平、主查询 **343 ms vs 明文 354 ms（无劣化）**、无密钥直接报错。而 SQLCipher 在本项目**根本装不上**——`sqlcipher3-binary` 从 0.4.0 到 0.6.0 **一个 Windows wheel 都没有**，`pysqlcipher3` 只有 sdist 且 2023 年起停更，而本项目是 PyInstaller 打的 Windows `.exe`。**推荐：DuckDB 原生 Parquet 加密 + DPAPI 包裹的 256-bit 随机数据密钥 + 按天分目录**（§B4.6）。

**滚动窗口不要在 SQLite 里 DELETE。** 实测删掉一半数据后文件**一个字节都不缩**，freelist 占到 **50.0%**；`auto_vacuum=INCREMENTAL` 还有两个静默失效陷阱（§B5.2）。**按天分文件 + 删目录：0.011 秒，零碎片，零 VACUUM，零 2× 磁盘峰值。**

⚠ **一个前置事实**：本仓**当前实时留存能力为零**——分钟线不落库，live 只有进程内 3–5 秒 TTL 缓存（`M*`）。诉求 3 不是「改造现有留存」，是**从零建**。

---

# A. 体量与格式（诉求 2）

## A1. A 股全市场数据的真实体量

### A1.1 起点：生产库到底多大（`M*` 主 agent dbstat 实测 2026-08-25）

| 对象 | 大小 | 行数 | 备注 |
|---|---:|---:|---|
| **`market.db` 合计** | **5,740.2 MB** | — | ⚠ 文档记的 2.4 GB 已过时 |
| ├ `quotes_daily` 数据段 | 2,723.0 MB | 16,966,403 | 5,547 只 / 1990-12-19 ~ 2026-08-25 → **160.5 B/行** |
| ├ `idx_quotes_receipt` | **1,049.0 MB** | — | 61.8 B/行，**单个索引就占全库 18.3%** |
| ├ `source_route_attempts` | 724.7 MB | 2,049,000 | 溯源 |
| ├ `source_route_receipts` | 450.9 MB | 1,069,000 | 溯源 |
| ├ `idx_quotes_code_date` | 424.9 MB | — | 25.0 B/行 |
| ├ `idx_source_attempts_source` | 127.3 MB | — | 溯源 |
| ├ `idx_source_receipts_recent` | 71.9 MB | — | 溯源 |
| ├ `idx_source_receipts_code_lane` | 62.3 MB | — | 溯源 |
| ├ receipts autoindex | 49.2 MB | — | 溯源 |
| ├ `idx_source_receipts_lane_state` | 33.7 MB | — | 溯源 |
| ├ `intel_snapshots` | 15.1 MB | — | MCP 快照缓存 |
| ├ `adjust_factors` | 4.2 MB | — | 稀疏复权因子 |
| └ `instruments` + `trading_calendar` | 0.9 MB | — | |
| **溯源审计小计** | **2,569 MB** | — | **= 全库 44.8%** |
| `market_hot.db` | 1,022.1 MB | 3,748,806 | 700 交易日窗口；其中 `idx_quotes_receipt` 又占 238.3 MB |
| `ops.db` | 13.8 MB | — | `job_runs` 11.36 MB / 706 行 ≈ **16 KB/行** |
| `palace.db` | 0.8 MB | — | |

**这张表已经回答了一半问题**：用户说「历史数据太庞大」，但 5.7 GB 里只有 2.7 GB 是行情本体，2.57 GB 是「这行数据是哪来的」的元数据。

### A1.2 九种格式的实测体积（`M`，同一份真实 16,966,403 行）

方法：DuckDB `sqlite_scanner` 只读挂载生产 `market.db`，`COPY (SELECT …) TO …` 导出到临时目录后 `stat` 量体积。SQLite 行无法直接「换格式」的部分（Arrow IPC / qlib `.bin` / `.day`）用**同 schema 的 1,375,000 行合成数据**测出 B/行后外推，并已用合成 SQLite（163.6 B/行）与生产实测（160.5 B/行）**互相校准，偏差 1.9%**。

| 格式 | 实测大小 | B/行 | 相对 SQLite(表+2索引) | 来源 |
|---|---:|---:|---:|---|
| **SQLite 本仓 DDL（表 + 2 索引）** | **4,196.9 MB** | **247.4** | 1.0× | `M*` |
| SQLite `quotes_daily` 数据段 | 2,723.0 MB | 160.5 | 1.5× | `M*` |
| SQLite 合成同 schema（表 + 1 索引） | 224.9 MB / 1.375M 行 | 163.6 | 1.5× | `M` 校准用 |
| SQLite 合成（仅 `WITHOUT ROWID` 主键） | 194.4 MB / 1.375M 行 | 141.4 | 1.7× | `M` |
| Arrow IPC / Feather（未压缩） | — | 188.0 | 1.3× | `M` 合成 |
| Arrow IPC + LZ4 | — | 58.2 | 4.3× | `M` 合成 |
| **DuckDB 原生表** | **671.4 MB** | **39.57** | **6.3×** | `M` 真实 |
| 通达信 `.day`（32 B 定长） | ≈543 MB | 32.0 | 7.7× | 算式，`P2` |
| Parquet + Snappy | 484.7 MB | 28.57 | 8.7× | `M` 真实 |
| Arrow IPC + Zstd | — | 28.5 | 8.7× | `M` 合成 |
| **Parquet + Zstd-3（`trade_date, code` 排序）** | **427.7 MB** | **25.21** | **9.8×** | `M` 真实 |
| Parquet + Zstd-3（按年 hive 分区，37 文件） | 410.8 MB | 24.21 | 10.2× | `M` 真实 |
| qlib `.bin`（float32 裸数组 × 6 字段） | ≈407 MB *内容* | 24.0 | 10.3× | 算式 6×4 B，`P1` |
| **Parquet + Zstd-3（`code, trade_date` 排序）** | **395.6 MB** | **23.32** | **10.6×** | `M` 真实 |
| Parquet + Zstd-3（**去掉 3 个溯源列**） | 395.0 MB | 23.28 | 10.6× | `M` 真实 |
| Parquet + Zstd-9（`code, trade_date`） | 385.0 MB | 22.69 | 10.9× | `M` 真实 |
| ClickHouse | 不适用（需常驻服务端） | — | — | `P1` 见 §A1.5 |
| ArcticDB | 未实测（未安装 + BSL 许可） | — | — | `P1` 见 §A1.5 |
| HDF5 | 未实测（本机无 `h5py`/`tables`） | — | — | `✗` 见 §A1.5 |

**三个反直觉的实测结论：**

1. **去掉 `source` / `receipt_id` / `fetched_at` 三个溯源列，Parquet 只省 0.6 MB**（395.6 → 395.0 MB，0.035 B/行）。在 SQLite 里这三列 + `idx_quotes_receipt` 值 **2,569 MB**，在列存里字典编码后**几乎免费**。→ **44.8% 的溯源开销是行存的产物，不是数据本身的成本。不要为了省空间去砍溯源，砍格式就行了。**
2. **排序键值 8%**：`code, trade_date` 比 `trade_date, code` 小 32.1 MB（−7.5%）。但 §A2.3 会证明它在主查询上**慢 4.8 倍**——这是一个必须做的取舍，不是白拿的。
3. **Zstd-9 只比 Zstd-3 省 2.7%**（385.0 vs 395.6 MB），写入慢 33%（36 s vs 27 s）。**Zstd-3 是甜点，不要调高。** 与 zstd 官方 benchmark 的形状一致（`P1`：Silesia 语料上 zstd-1 ratio 2.896 / 510 MB·s⁻¹，提高等级换来的比例收益递减）。

### A1.3 外推：5500 只 × N 年（算式 = 5500 × 250 交易日 × N × B/行）

日线，行数 = 1,375,000 × N。

| 格式 | B/行 | 1 年 | 3 年 | 5 年 | 10 年 | 真实全历史(16.97M) |
|---|---:|---:|---:|---:|---:|---:|
| SQLite 本仓 DDL（表+2索引） | 247.4 | 340 MB | 1.02 GB | 1.70 GB | 3.40 GB | **4,196.9 MB** |
| SQLite 数据段 | 160.5 | 221 MB | 662 MB | 1.10 GB | 2.21 GB | **2,723.0 MB** |
| Arrow IPC 未压缩 | 188.0 | 259 MB | 776 MB | 1.29 GB | 2.59 GB | 3.19 GB |
| DuckDB 原生 | 39.57 | 54.4 MB | 163 MB | 272 MB | 544 MB | **671.4 MB** |
| 通达信 `.day` | 32.0 | 44.0 MB | 132 MB | 220 MB | 440 MB | 543 MB |
| Parquet+Zstd3（date,code） | 25.21 | 34.7 MB | 104 MB | 173 MB | 347 MB | **427.7 MB** |
| qlib `.bin` f32×6 | 24.0 | 33.0 MB | 99 MB | 165 MB | 330 MB | 407 MB |
| **Parquet+Zstd3（code,date）** | **23.32** | **32.1 MB** | **96 MB** | **160 MB** | **321 MB** | **395.6 MB** |

分钟线与 3 秒快照（`M`，同 schema 8 列实测单行成本，见 §B6）：

| 数据 | 行/年（5500 只 × 243 日） | Parquet+Zstd3 | SQLite |
|---|---:|---:|---:|
| 分钟 K（240 根/日） | 3.208 亿 | **13.38 B/行 → 4.3 GB/年** | 76.59 B/行 → 24.6 GB/年 |
| 3 秒快照（4800 点/日） | 64.15 亿 | **13.63 B/行 → 87.4 GB/年** | 76.70 B/行 → 492 GB/年 |

> A 股公开免费数据拿不到 Level-2 逐笔委托；「tick」在这里的现实含义是**交易所 3 秒行情快照**。真正的逐笔成交（约 2–4 亿笔/日全市场）不在可得范围，故不列。

### A1.4 qlib `.bin` 的隐藏成本：小文件

qlib 的 `.bin` 是 `np.hstack([date_index, values]).astype("<f").tofile()`（`P1`，[`scripts/dump_bin.py`](https://raw.githubusercontent.com/microsoft/qlib/main/scripts/dump_bin.py) `_data_to_bin`）——小端 float32 裸数组，**每 (票, 字段, 频率) 一个文件**，文件头就是一个 float32 的日历起点下标。5,547 只 × 6 字段 = **33,282 个文件**。

**独立交叉验证**：同批次 [`_scratch_2026-08-qb-qlib.md`](./_scratch_2026-08-qb-qlib.md) 实测官方 `qlib_data_cn_1d_latest.zip`——3,875 只 × 7 字段 = 27,125 个 `.day.bin` 共 271.1 MB，单字段 40,604,372 B 对应 10,147,218 个 (票,日) 槽位，即 **4.0 B/槽位**。与本文 6 字段 × 4 B = 24.0 B/行 的算式**完全一致**，两条独立路径互证 `.bin` 就是裸 float32。

实测（`M`）：250 天 × 5500 票 × 8 字段的目录，**内容 43 MB，NTFS 实占 195 MB**（`du` 对照 `du --apparent-size`），**4.5 倍**——4 KiB 簇 × 44,000 个 1,004 B 的文件。

按 NTFS 4 KiB 簇的算式：

| 每票天数 | 内容/文件 | 实占/文件 | 33,282 文件内容合计 | 实占合计 | 浪费 |
|---:|---:|---:|---:|---:|---:|
| 250 | 1,004 B | 4,096 B | 33.4 MB | 136.3 MB | **308%** |
| 1,000 | 4,004 B | 4,096 B | 133.3 MB | 136.3 MB | 2% |
| 4,000 | 16,004 B | 16,384 B | 532.6 MB | 545.3 MB | 2% |
| 8,700（全历史） | 34,804 B | 36,864 B | 1,158.3 MB | 1,226.9 MB | 6% |

**结论**：全历史场景下 slack 只有 6%，可以接受；但 **33,282 个文件本身**是备份、杀软扫描、云同步、增量校验的持续税。qlib 格式适合「一次落盘、只读全扫」的因子研究，不适合本仓这种「每天增量 + 要备份 + 要打分享包」的桌面工作台。

### A1.5 三个不实测但要说清的选项

- **ClickHouse**（`P1` [CREATE TABLE 文档](https://clickhouse.com/docs/sql-reference/statements/create/table#column_compression_codec)）：列级 `CODEC(ZSTD)`、`Delta`、`DoubleDelta`、`Gorilla` 全都有，压缩比会优于 Parquet。但它是**常驻服务端**，与本仓「单机桌面 + PyInstaller onedir + 用户双击 `Loci.exe`」的形态根本冲突。**排除，不是因为不好，是因为形态不对。**
- **ArcticDB**（`P1` [README](https://github.com/man-group/ArcticDB)）：Man Group 出品，Pandas in / Pandas out，支持 LMDB 本地后端和 Windows x86_64 wheel，天然适合「20 年 × 40 万标的存一个 symbol」。**但许可是 BSL 1.1**：README 原文「Use of ArcticDB in production (including business or commercial environments) or for a Database Service requires a paid for license」。个人自用不触发，但一旦这个工作台要分发/商用就是雷。且 6.21 版要到 **2028-08-04** 才转 Apache 2.0。**排除（许可风险 > 收益），保留为未来选项。**
- **HDF5**：本机无 `h5py` / `tables`，**未实测**。按公开经验它的定位介于 Arrow IPC 与 Parquet 之间，但对本场景没有任何 Parquet 没有的优势，且并发读写与文件损坏恢复的口碑差。**不推荐，也不值得为它装依赖。**
- **SQLite 官方 SEE**：一次性商业许可（$2,000 档），单机自用**一句话排除**。

---

## A2. 列存对量化面板的意义

### A2.1 为什么 `index=date, columns=code` 天然适合列存

本仓 `docs/quant-toolkit.md` §0 已经把计算侧说透了：面板 = `DataFrame(index=交易日, columns=股票代码)`，`MA(close,20)` 就是 `close.rolling(20).mean()`，一次覆盖 5,500 只。存储侧的对应事实是三条：

1. **选股只读 4–6 列，从不读 13 列。** `PANEL_FIELDS` 是 `open/high/low/close/volume/amount/turnover/outstanding_share`（[`store_schema.py:14-16`](../../src/market/infrastructure/store_schema.py)），而表里有 13 列。行存必须把 `source`/`receipt_id`/`fetched_at` 的字节一起读进来再丢掉；列存直接不碰那三个 column chunk。实测（`M`）：只取 3 列时 Parquet **182 ms**，SQLite **1,334 ms**，**7.3 倍**。
2. **同一列的值分布高度同质。** 一列全是 2 位小数价格 / 全是整数股 / 全是同一天的日期字符串——字典编码 + RLE + Zstd 能吃掉绝大部分。这正是 §A1.2 里三个溯源列在列存中「几乎免费」的原因：`source` 只有 2–3 个取值，`fetched_at` 每天一个值重复 5,500 次。
3. **谓词下推 = 只读该读的 row group。** Parquet 每个 row group 的每列都带 min/max 统计；`WHERE trade_date >= '2025-08-14'` 在 `trade_date` 有序时可以直接跳过 97% 的 row group。**这一条在 `code` 排序时完全失效**——见 §A2.3。

### A2.2 DuckDB 直读 Parquet 的路径（说清楚「零拷贝」到底零在哪）

`SELECT … FROM read_parquet('x.parquet')` 不经过 SQLite、不经过 pandas 的 Python 层：DuckDB 用自己的 C++ Parquet reader 把 column chunk 解压进它自己的向量化执行引擎，再一次性物化成 Arrow / pandas。

**「零拷贝」是个被滥用的词，这里必须说准**：Parquet 是压缩+编码格式，**不能** mmap 后直接当数组用。pyarrow 官方文档原文（`P1`）：「Because Parquet data needs to be decoded from the Parquet format and compression, it can't be directly mapped from disk.」真正零拷贝的是 **Arrow IPC / Feather**（未压缩时可 mmap），代价是体积 188 B/行——比 SQLite 数据段还大。

所以本仓能拿到的收益不是「零拷贝」，是**「少读 + 少解码 + 不过 Python 层」**。实测数字在下面。

### A2.3 分区策略对主查询的影响（`M` 实测，主查询 = 全市场 × 最近 250 交易日 = 1,365,143 行）

每项取 3 次最优，同一台机器，冷/热态一致。

| 读取路径 | 耗时 | 相对本仓现状 |
|---|---:|---:|
| DuckDB ← DuckDB 原生表 | **287 ms** | **7.1×** |
| DuckDB ← Parquet **按年 hive 分区**（37 文件） | **289 ms** | **7.1×** |
| DuckDB ← 单文件 Parquet（**`trade_date, code` 排序**） | **326 ms** | **6.3×** |
| DuckDB ← 单文件 Parquet（`code, trade_date` 排序） | 1,554 ms | 1.3× |
| **DuckDB ← `sqlite_scanner` 挂 `market_hot.db`（本仓 `LOCI_MARKET_DUCKDB=1` 现状）** | **2,040 ms** | **1.0×** |
| `pandas.read_sql` ← `market_hot.db`（本仓默认路径） | 2,661 ms | 0.77× |
| `pandas.read_sql` ← `market.db` 全量 | 2,732 ms | 0.75× |
| DuckDB ← `sqlite_scanner` 挂 `market.db` 全量 | 8,728 ms | 0.23× |
| **[仅 3 列] DuckDB ← 单文件 Parquet** | **345 ms** | — |
| [仅 3 列] `pandas` ← `market_hot.db` | 1,334 ms | — |

**四个必须记住的结论：**

1. **压缩最好的排序键是查询最差的排序键。** `code, trade_date` 省 7.5% 空间，主查询慢 **4.8 倍**（1,554 vs 326 ms）——因为「最近 250 日」这个谓词在 code 排序下命中**每一个** row group。**主查询是日期切片，分区/排序就必须 date-major。** 这是本文里最容易被拍脑袋拍错的一条。
2. **按年分区（289 ms）≈ DuckDB 原生（287 ms）> 单文件 date 排序（326 ms）**，且按年分区只比单文件大 4.5%（410.8 vs 427.7 MB）。**按年 hive 分区是综合最优**，还顺带解决了增量重写（只重写当年那个文件）。
3. **本仓现有的 `LOCI_MARKET_DUCKDB` 旁路，性能收益接近于零**——2,040 ms vs pandas 的 2,661 ms，只有 1.3 倍，还不如直接 pandas 读全量库（2,732 ms）差不多。**瓶颈从来不是执行引擎，是 SQLite 行存的 I/O 和解码。** ADR-002 里那句「性能收益需实盘数据验证后再考虑默认开启」，本轮的验证结论是：**这条旁路以现在的形态不值得扶正，因为它把 DuckDB 接在了错误的那一头。**
4. **`sqlite_scanner` 挂全量库是灾难**（8,728 ms，比 pandas 慢 3.2 倍）。DuckDB 对 `WITHOUT ROWID` 表拿不到 rowid 做并行分片（本轮还实测到 `SELECT count(*)` 直接报 `no such column: ROWID`），退化成单线程逐行拉取。**ADR-002 的旁路只在热库上勉强能用，在全量库上是负优化——这一点现有文档没记。**

### A2.4 判断：该不该把 Parquet/DuckDB 扶正为主存

**该，但只扶正「读」，不扶正「权威」。** 具体主张：

| 角色 | 现状 | 建议 | 理由 |
|---|---|---|---|
| 权威事实 | `market.db` SQLite | **不动** | 事务、崩溃恢复、`upsert` 语义、回执同事务写入（`sync_spot_receipts`）都在这儿。列存文件没有这些。 |
| 选股/回测热读 | `market_hot.db`（700 日 SQLite 镜像） | **换成 `panel/daily/year=*/…parquet`** | 实测 289 ms vs 2,040 ms，**7.1×**；体积 411 MB vs 1,022 MB，**2.5×**。且热库自己那 238.3 MB 的 `idx_quotes_receipt` 在列存里直接消失。 |
| `LOCI_MARKET_DUCKDB` 旁路 | 挂 SQLite 的 DuckDB | **改成读 Parquet；`sqlite_scanner` 分支删掉** | 现形态收益 1.3×，改后 7.1×。 |
| `polars_panel.py` | `LOCI_MARKET_POLARS=1` POC，读 SQLite | **保留但降级为对照** | Polars 也能直读 Parquet，但 DuckDB 的谓词下推 + hive 分区已经够；两个 POC 旁路不必并存。 |

**这与 ADR-002/ADR-007 的核心原则完全兼容**：「派生缓存可整段删除重建，零双真相」。`panel/` 就是把 `market_hot.db` 换了个格式的**同一个东西**——同样可删、同样可 `hot_rebuild` 重建、同样不是第二套权威。**唯一需要新写的是一个 `mirror_to_parquet()`，替换 `mirror_to_hot()` 的落点。**

⚠ **不建议做的**：把 `palace.db`（账本）或 `market.db`（权威）换成列存。Parquet 没有行级更新，`upsert_quotes` 的 `COALESCE` 语义无法表达，崩溃恢复也没有。**列存管读，行存管写，这条线不要越。**

---

## A3. 历史数据到底需要多少：统计功效

### A3.1 参数全部实测，不引用文献估计（`M`）

只读挂载生产 `market.db`，2010-01-01 起、剔停牌与 `|r|<0.8` 异常、要求当日成交额 ≥ 3,000 万（贴近可实际成交的票池），得 **10,290,060 条样本 / 4,037 个交易日**。

| 持有期 | σ_总（净收益口径） | σ_日间 | **σ_残差（超额口径）** | **ICC** | 独立日数上限/年 |
|---|---:|---:|---:|---:|---:|
| 1 日 | 3.402% | 1.774% | **2.928%** | **0.2719** | 894 |
| 3 日 | 6.050% | 3.214% | **5.180%** | **0.2822** | 861 |
| 5 日 | 7.807% | 4.145% | **6.690%** | **0.2819** | 862 |

- σ_残差 = 剔掉当日全市场截面均值后的残差标准差，**这就是「超额」那一列该配的 σ**。
- ICC = 日间方差 / 总方差 = 同一天两个信号收益的相关系数。**0.28 意味着：同一天发 100 个信号，它们不是 100 个独立观测。**

### A3.2 「样本量 = 交易日数 × 日均信号数」是错的，要除以设计效应

对一天发 k 个信号的策略，同日信号共享市场因子，有效样本量：

```
N_eff = N / deff ,  deff = 1 + (k − 1) · ICC
```

当 k → ∞ 时 `N_eff → 交易日数 / ICC`。即**无论一天发多少信号，独立观测数被交易日数除以 0.2822 卡死**——每年最多 861 个。这就是「样本大不等于结论强」的确切形式。

**但这只对「净收益」成立。** 「超额」已经把共同因子减掉了，ICC 近似为 0，k 个信号近似独立——代价是 σ 从 6.050% 降到 5.180%（分母也小了）。**两种口径要分开算，这是下面两张表的由来。**

### A3.3 达到 t ≥ 3.0 所需年数（`N* = 9σ²/μ²`；表内数字 = 年数）

**A) 超额口径**（σ = 5.180%，3 日持有，信号近似独立，年数 = N*/(243·k)）

| 目标超额/笔 | N*(t=3) | k=1/日 | k=3/日 | k=10/日 | k=30/日 | k=100/日 | k=300/日 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.20% | 6,037 | 24.8 | 8.3 | 2.5 | 0.8 | 0.2 | 0.1 |
| **0.30%** | **2,683** | **11.0** | **3.7** | **1.1** | **0.4** | **0.1** | **0.0** |
| **0.50%** | **966** | **4.0** | **1.3** | **0.4** | **0.1** | **0.0** | **0.0** |
| 0.73% | 453 | 1.9 | 0.6 | 0.2 | 0.1 | 0.0 | 0.0 |
| 1.00% | 241 | 1.0 | 0.3 | 0.1 | 0.0 | 0.0 | 0.0 |
| 1.50% | 107 | 0.4 | 0.1 | 0.0 | 0.0 | 0.0 | 0.0 |

**B) 净收益口径**（σ = 6.050%，`deff = 1+(k−1)·0.2822`，年数 = N*·deff/(243·k)）

| 目标均净/笔 | N*(t=3) | k=1/日 | k=3/日 | k=10/日 | k=30/日 | k=100/日 | k=300/日 | **k→∞ 下限** |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.20% | 8,236 | 33.9 | 17.7 | 12.0 | 10.4 | 9.8 | 9.6 | **9.6 年** |
| **0.30%** | **3,660** | 15.1 | 7.9 | 5.3 | 4.6 | 4.4 | 4.3 | **4.3 年** |
| **0.50%** | **1,318** | 5.4 | 2.8 | 1.9 | 1.7 | 1.6 | 1.5 | **1.5 年** |
| 0.73% | 618 | 2.5 | 1.3 | 0.9 | 0.8 | 0.7 | 0.7 | 0.7 年 |
| 1.00% | 329 | 1.4 | 0.7 | 0.5 | 0.4 | 0.4 | 0.4 | 0.4 年 |
| 1.50% | 146 | 0.6 | 0.3 | 0.2 | 0.2 | 0.2 | 0.2 | 0.2 年 |

**读法**：想证明一个「均净 +0.3%/笔」的战法真实存在，**无论你一天发多少信号，都至少要 4.3 年数据**。想证明 +0.5%/笔，1.5 年。**滥发信号买不到统计显著性。**

### A3.4 代入本仓两个已知战法（`M`，数据取自 `docs/quant-toolkit.md` 横向对比表）

| 战法 | 笔数 n | 覆盖交易日 | k（信号/日） | deff | **N_eff** | t（超额） | t（均净，用 N_eff） | 判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 潜龙原版 /3d | 24,878 | ≈628 | **39.6** | **11.9** | **2,090** | **2.13** | 2.27 | ✗ 不显著 |
| 分手快乐 /3d | 495 | ≈405 | 1.2 | 1.1 | 466 | **3.14** | 3.28 | ✓ 显著 |
| 分手快乐 /1d | 495 | ≈405 | 1.2 | 1.1 | 466 | **3.80** | 3.24 | ✓ 显著 |

**24,878 笔的 t = 2.13，495 笔的 t = 3.14。** 这独立复现了 `quant-toolkit.md` 那句「潜龙原版 24878 笔但超额只有 +0.07%——信号这么多说明条件太松」，并把它从定性变成了定量：潜龙的 24,878 笔在扣掉设计效应后只值 **2,090 个独立观测**，而 +0.07% 的超额需要 **49,300 个**独立观测才能到 t=3。**它不是「样本够但效应小」，是「样本远远不够」。**

### A3.5 那到底要不要 2015 / 2018 / 2021？——实测给出分裂的答案

**逐年 σ（3 日持有，净收益口径，成交额 ≥3,000 万）：**

| 年 | 交易日 | 日均在交易 | 样本 n | 均值% | **σ%** |
|---|---:|---:|---:|---:|---:|
| 2010 | 242 | 1,276 | 308,908 | +0.0016 | 5.555 |
| 2011 | 244 | 1,065 | 259,764 | −0.6766 | 5.263 |
| 2012 | 243 | 903 | 219,444 | −0.1917 | 5.316 |
| 2013 | 238 | 1,254 | 298,377 | +0.0148 | 5.639 |
| 2014 | 245 | 1,550 | 379,741 | +0.3661 | 5.473 |
| **2015（股灾）** | 244 | 2,082 | 507,938 | +0.5703 | **9.572** |
| 2016 | 244 | 2,306 | 562,668 | −0.1032 | 5.898 |
| 2017 | 244 | 2,243 | 547,351 | −0.3362 | **4.825** |
| **2018（熊市）** | 243 | 1,893 | 460,085 | −0.6929 | 5.644 |
| 2019 | 244 | 2,318 | 565,643 | +0.2431 | 5.502 |
| 2020 | 243 | 2,872 | 697,985 | +0.1664 | 6.165 |
| **2021（抱团）** | 243 | 3,101 | 753,506 | +0.1668 | 6.098 |
| 2022 | 242 | 3,568 | 863,396 | −0.1960 | 5.839 |
| 2023 | 242 | 3,773 | 912,957 | −0.0460 | 4.895 |
| 2024 | 242 | 4,124 | 997,981 | +0.0700 | **7.134** |
| 2025 | 243 | 4,926 | 1,196,995 | +0.4648 | 5.462 |
| 2026(至今) | 153 | 5,018 | 767,679 | −0.1396 | 6.345 |

**分段 σ_残差（超额口径，3 日持有）：**

| 区间 | 样本 n | σ_残差 |
|---|---:|---:|
| 2010–2014 | 1,466,224 | **4.748%** |
| 2015–2018（含股灾+熊市） | 2,078,034 | **5.280%** |
| 2019–2021（抱团） | 2,017,014 | **5.351%** |
| 2022–2026 | 4,728,788 | **5.191%** |

**这两张表给出的答案是分裂的，必须分开说：**

- **测截面 alpha → 短历史够。** σ_残差 在 16 年里只在 **4.75%–5.35%** 之间抖（极差 12.7%）。你用 2022–2026 估出来的超额分布，和用 2010–2014 估的几乎一样。**用户诉求 2 在这个口径下成立：历史数据确实不需要那么庞大。**
- **测回撤、组合风险、爆仓概率 → 必须要 2015。** σ_总 在 2015 年是 **9.572%**，2017 年是 **4.825%**——**差 1.98 倍**。只用 2022 年以后的数据估风险，会把 2015 型行情的尾部风险低估掉一半。`2026-08-dragon-survivorship-and-portfolio-fragility.md` 已经警告过组合层收益数字不可信；这里补上一条独立的量化理由。
- **⚠ 但 2015 年的数据你其实用不了。** 2015 年日均在交易（成交额≥3000万）只有 **2,082 只**，2026 年是 **5,018 只**——**你今天的策略票池里有 59% 的股票在 2015 年不存在或没有流动性。** 叠加 `M*` 实测的 **`instruments.delist_date` 填充数 = 0、`status` 里 `delisted` 只有 1 只 / `normal` 5,546 只**——退市股行情根本没进库。**在这个数据集上跑 2015 年，测出来的是「今天还活着的、当年就有流动性的那 2,082 只」的表现，是双重幸存者偏差。**

**综合判断（这是对诉求 2 的正面回答）：**

> **历史长度不是问题，历史宽度和干净度才是。** 3–5 年的日线足够验证任何日均信号数 ≥ 3 的短线战法（表 A）。留 36 年全历史的代价在换成 Parquet 后只有 **395.6 MB**——**便宜到不值得为省它做任何取舍**。真正该砍的是「每一行都背着 247 字节」这件事，以及「拿一个有双重幸存者偏差的 2015 去算回撤」这个错觉。

### A3.6 分层保留方案

| 层 | 内容 | 保留 | 格式 | 体量 | 理由 |
|---|---|---|---|---:|---|
| **L0 权威** | `market.db` 的 `quotes_daily` + `adjust_factors` + `instruments` + `trading_calendar` | **全量永久** | SQLite（不动） | 2.73 GB | 唯一可写事实源，事务/崩溃恢复不可替代 |
| **L1 面板**（新） | L0 的 OHLCV+换手+股本，按年分区 | **全量永久** | Parquet+Zstd3，`year=` hive，date-major | **411 MB** | 选股/回测/研究唯一读路径；可整目录删除重建 |
| **L2 溯源** | `source_route_receipts` / `source_route_attempts` + 4 个索引 | **近 24 个月留 SQLite，更早导出 Parquet 后从 SQLite 删** | Parquet+Zstd3 | 从 2,569 MB → 约 **60 MB** | PIT 研究只查近窗；历史回执导出后仍可查，只是慢。**这是单笔最大的一块省** |
| **L3 热窗** | `market_hot.db` | **删除，由 L1 取代** | — | −1,022 MB | 实测 L1 比它快 7.1×、小 2.5× |
| **L4 盘中留存**（新） | spot / 分钟 / 竞价 / 事件流 / 板块资金 | **滚动 60 交易日** | 加密 Parquet，按天分目录 | 见 §B6 | 诉求 3 |
| **L5 可重建缓存** | `intel_snapshots`、DuckDB 临时物化 | 随时可清 | — | 15 MB | 已是「可重建」语义 |
| **L6 运维留痕** | `job_runs`（16 KB/行!）、`leader_role_snapshots`(60d)、`second_wave_signals`(180d) | 现有 `MANAGED_PRUNE` 保持 | SQLite | 13.8 MB | ⚠ `job_runs` 16 KB/行 应单独查一次为什么这么胖 |

**净效果**：`market.db` + `market_hot.db` 从 **6,762 MB → 约 3,200 MB**（L0 保持 2,723 MB + L2 瘦身后残留），另加 **411 MB** 的 L1。**总盘子从 6.76 GB 降到约 3.6 GB，且主查询快 7.1 倍**——而且**一年历史都没删**。

> **L2 那一行的算式**（避免过度承诺）：溯源合计 2,569 MB = 表 1,175.6 MB + 6 个索引 344.4 MB + `idx_quotes_receipt` 1,049.0 MB。三块的处置不同：**① `idx_quotes_receipt` 直接 DROP 省 1,049.0 MB**（它只服务「按回执反查日 K」这一个低频运维查询，退化为全扫可接受，或由 L1 Parquet 承担）；**② 6 个 receipts/attempts 索引在导出后随表一起收缩**；**③ 两张表按 §A1.2 实测的 10.6× 压缩比导出 Parquet 约 111 MB**，SQLite 侧只留近 24 个月。保守估计 **2,569 MB → 300～400 MB**，节省 2.2 GB 左右。精确值需实跑，本轮**未实跑**。

---

# B. 加密留存（诉求 3）

## B4. 加密方案横向对比

### B4.0 先看清约束：单机桌面 + 单用户 + Python + PyInstaller `.exe`

| 约束 | 事实 | 出处 |
|---|---|---|
| 分发形态 | **PyInstaller onedir**，产物 `Loci.exe` + `_internal/`，装到 `E:\entertainment_software\Loci` | [`scripts/build-loci.ps1:183`](../../scripts/build-loci.ps1)、[`scripts/README.md`](../../scripts/README.md) |
| Python | 3.12.13（venv 实测） | `M` |
| 已有依赖 | `duckdb>=1.0.0`、`polars>=1.0.0`、`pyzipper>=0.3.6`（AES zip） | [`requirements.txt`](../../requirements.txt) |
| **不在** `requirements.txt` | `cryptography`、`pyarrow`、`pywin32`、`keyring`、`argon2-cffi` | `M` |
| 但 venv 里实际有 | `cryptography 48.0.0`、`pywin32 312`（**均为传递依赖，不保证**；`pywin32` 只是 `psutil` 的 `dev`/`test` extra） | `M` |
| **无** `pyarrow` | venv 实测 `ModuleNotFoundError`；Parquet 由 polars/duckdb 自带 writer 产出 | `M` |
| 历史包袱 | 曾用 AES-256-GCM 加密 LLM Key，**已迁回明文**；`.palace_ai_master_key` 明文密钥文件仍在忌讳清单里 | [`src/ai/infrastructure/crypto.py`](../../src/ai/infrastructure/crypto.py)、[`providers.py:45-49`](../../src/ai/infrastructure/providers.py)、[`ops/README.md:217`](../../src/ops/README.md) |

### B4.1 SQLCipher —— **在本项目上装不上，直接出局**

**设计**（`P1`，[Zetetic 官方 Design 页](https://www.zetetic.net/sqlcipher/design/)原文）：AES-256-CBC，逐页加密，每页独立随机 IV（写时重新生成），每页尾部带 **HMAC-SHA512**，口令经 **PBKDF2-HMAC-SHA512 默认 256,000 轮** + 每库 16 字节随机盐派生，WAL 与 rollback journal 同样加密。安全设计本身没问题。

**性能**（`P1`，[官方 Performance 页](https://www.zetetic.net/sqlcipher/performance/)原文）：「It's not unusual to see as little as **5-15% overhead** for SQLCipher encryption.」但同页也给了三个前提：不要反复开关连接（密钥派生很贵）、写操作必须包事务、必要时用 RAW key 跳过派生或 `PRAGMA kdf_iter=64000` 降四倍。**注意官方同时在推销商业版「up to 3-4x faster than free Community Edition」——所以 5-15% 这个数字应理解为商业版语境下的乐观值。**

**致命问题：Windows 上没有可用的 Python 轮子。**

| 包 | 最新版 | Windows wheel | 结论 |
|---|---|---|---|
| `sqlcipher3-binary` | 0.6.0（2025-12-31） | **0 个**。0.4.0→0.6.0 全部只有 `manylinux*_x86_64` | `M`（[PyPI JSON](https://pypi.org/pypi/sqlcipher3-binary/json) 全量扫描，`win_amd64` 零命中） |
| `pysqlcipher3` | 1.2.0（**2023-01-29**，已停更） | **无 wheel，只有 sdist**；且 README 要求「Prior to installation, **libsqlcipher must already be installed** on your system」 | `M`（[PyPI JSON](https://pypi.org/pypi/pysqlcipher3/json)） |

要用它就必须：在 Windows 上用 MSVC 编译 OpenSSL → 编译 SQLCipher amalgamation → 编译 Python 扩展 → 把 DLL 手工写进 `loci.spec` 的 `binaries` → 每次 Python 小版本升级重来一遍。**为了一个我们并不需要的「整库透明加密」付这个代价，不合理。** 本仓要加密的是**写一次就不改的每日文件**，不是一个需要事务的活库。

**出局。**

### B4.2 SQLite 官方 SEE —— 一句话排除

商业许可（一次性 $2,000 档），闭源，单机自用场景**排除**。

### B4.3 应用层加密：Fernet vs AES-256-GCM（`M` 实测）

对 37.37 MB 的真实 Parquet 文件加密，同一台机器：

| 方案 | 密文体积 | **膨胀** | **吞吐** | 认证 | AAD |
|---|---:|---:|---:|---|---|
| AES-256-GCM 整块（1 nonce） | 37.37 MB | **+0.0001%** | **3,254 MB/s** | ✓ | ✓ |
| **AES-256-GCM 分块 1 MiB** | 37.37 MB | **+0.0027%** | **536 MB/s** | ✓ | ✓ |
| AES-256-GCM 分块 4 MiB | 37.37 MB | +0.0007% | 862 MB/s | ✓ | ✓ |
| AES-256-GCM 分块 64 KiB | 37.39 MB | +0.0428% | 646 MB/s | ✓ | ✓ |
| ChaCha20-Poly1305 分块 1 MiB | 37.37 MB | +0.0027% | 480 MB/s | ✓ | ✓ |
| **Fernet（AES-128-CBC + HMAC + base64）** | **49.83 MB** | **+33.3336%** | **208 MB/s** | ✓ | **✗** |

小 blob 场景（200 B 明文，模拟逐行加密）：**Fernet 356 B（+78%）**，AES-GCM 12+16 字节开销共 228 B（+14%）。

**Fernet 出局，三条理由，每条都是实测或规范原文：**
1. **+33.33% 体积**——因为 Fernet 规范（`P1`，[fernet/spec Spec.md](https://github.com/fernet/spec/blob/master/Spec.md)）强制 base64url 编码整个 token。对 60 天 22 GB 的盘中数据，这是白扔 7 GB。
2. **AES-128 而非 256**——规范原文：「A fernet key is the base64url encoding of Signing-key ‖ Encryption-key，各 128 bits」「All encryption in this version is done with **AES 128 in CBC mode**」。
3. **无 AAD**——不能把「哪一天、哪张表、schema 版本」绑进认证标签，防不住文件互换。

**AES-256-GCM 分块是正解**，分块大小取 1–4 MiB：整块加密虽快（3.2 GB/s）但**必须整文件读进内存才能验签**，且单 key 的 GCM 调用次数受 NIST SP 800-38D §8.3 的 2³² 限制（Parquet 规范 `P1` 明确引用了这条）。1 MiB 分块下 536 MB/s，加密 22 MB 的日文件耗时 **41 ms**——可以忽略。

### B4.4 「能加密的是 value，不能加密的是你要 WHERE 的那列」——把这个权衡讲透

这是应用层加密（逐 blob 加密 + 明文索引列）**唯一真正的设计约束**，也是绝大多数「给数据库加密」方案翻车的地方。

假设把盘中快照存成 `spot(ts TEXT, code TEXT, payload BLOB)`，`payload` 是 AES-GCM 密文：

| 你想做的查询 | 能不能做 | 为什么 |
|---|---|---|
| `WHERE ts BETWEEN … AND …` | ✅ | `ts` 是明文列，走索引 |
| `WHERE code = '600519'` | ✅ | `code` 是明文列 |
| `WHERE price > 100` | ❌ | `price` 在密文里。**必须把全部候选行拉回内存、逐行解密、再在 Python 里过滤** |
| `SELECT avg(amount) GROUP BY code` | ❌ | 同上，且要全表解密 |
| `ORDER BY turnover DESC LIMIT 50` | ❌ | 同上 |

**代价的量级**：全市场 60 天 1 分钟快照约 8,000 万行。逐行解密（每行 ~200 B，Fernet/GCM 各自的固定开销 + Python 层往返）在本机实测的小 blob 路径上是 **10 万级 ops/s 量级**，8,000 万行 = **十几分钟**。而同一份数据在明文 Parquet 上做同样的聚合是 **亚秒级**。

**所以逐 blob 加密只有在一种情况下成立**：你 WHERE 的列恰好全是低敏感度的键（时间、代码），而被加密的是「不需要被查询、只需要被整块取回」的东西——比如**账本明细、API Key、用户备注**。

**盘中行情不属于这一类。** 它的全部价值就在于「按价格/成交额/涨速筛选」。把它逐 blob 加密，等于把它变成一个只能顺序回放的磁带。

**这正是 Parquet Modular Encryption 存在的理由**（下一节）：它在**列级**加密，但把每个 column chunk 的 min/max 统计和 row group 结构留在**加密的 footer 里**——持有密钥的读者仍然能做谓词下推和列裁剪，**加密和「可查询」不再互斥**。

### B4.5 列存路线：Parquet Modular Encryption（`M` 实测——这是本节的转折点）

**规范**（`P1`，[Apache Parquet 官方 Encryption 页](https://parquet.apache.org/docs/file-format/data-pages/encryption/)，即 PARQUET-1178）：把 pages / page headers / column indexes / offset indexes / bloom filters / footer 各自作为「module」独立加密，「allowing for a regular Parquet functionality (**columnar projection, predicate pushdown**, encoding and compression)」。两种算法：`AES_GCM_V1`（全部 GCM）与 `AES_GCM_CTR_V1`（页用 CTR 提速，元数据仍 GCM）。每 module 12 字节随机 nonce，AAD = 文件内标识 + module 类型 + row group / column / page 序号，**天然防 module 互换与整文件回滚**。

**pyarrow 路线：不可行。** 官方文档（`P1`）要求编译时 `-DPARQUET_REQUIRE_ENCRYPTION=ON`，且要用户自己实现 `KmsClient` 子类接一个 KMS 服务。而**本仓 venv 里根本没有 pyarrow**。为一个单机单用户场景引入 pyarrow + 自建 KMS，过度工程。

**DuckDB 路线：可行，而且几乎免费。** DuckDB 1.5.5（本仓已声明 `duckdb>=1.0.0`）**原生实现了 Parquet 加密**。实测（`M`，同一条 `COPY` 语句写出明文/密文两份，真实 16,966,403 行）：

```sql
PRAGMA add_parquet_key('k1', '<base64 of 32 random bytes>');
COPY (SELECT … ) TO 'x.parquet'
(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3, ENCRYPTION_CONFIG {footer_key: 'k1'});
SELECT … FROM read_parquet('x.parquet', encryption_config={footer_key: 'k1'}) WHERE trade_date >= '…';
```

| 指标 | 明文 | 加密 AES-GCM | 比值 |
|---|---:|---:|---:|
| 文件体积 | 427.7 MB | **417.8 MB** | **0.977**（−2.3%，属写出参数差异，**不应解读为「加密省空间」**） |
| 写入耗时 | 23.3 s | 28.9 s | 1.24× |
| **主查询（全市场×250 日，9 列，1,365,143 行）** | 354 ms | **343 ms** | **0.97×（无劣化，在噪声内）** |
| 列裁剪查询（仅 3 列） | 182 ms | 210 ms | 1.16× |
| 无密钥读取 | — | **硬失败**：`Invalid Input Error: File '…' is encrypted, but 'encryption_config' was not set` | ✓ |
| 密钥长度 | — | 必须 128 / 192 / 256 bit，其它长度被拒（实测 20 B → `Invalid AES key`） | ✓ |

**这是整个 B 部分的关键发现**：**加密的读代价约等于零**（343 vs 354 ms），因为 AES-NI 的解密吞吐远高于 Zstd 解压 + 列物化的成本；瓶颈根本不在加密上。**你不需要在「能查询」和「加密」之间二选一。**

⚠ **两个已知限制**（必须记）：① `PRAGMA add_parquet_key` **不支持预处理参数**（实测 `Binder Error: Unexpected prepared parameter`），只能字符串拼接——**密钥会短暂出现在 SQL 文本里**，不要把 DuckDB 的 query log 打开。② polars 的 `write_parquet` 不支持加密，加密写必须走 DuckDB `COPY`。

### B4.6 密钥管理：Windows DPAPI + 随机数据密钥

| 方案 | 防什么 | 不防什么 | 本仓适配 |
|---|---|---|---|
| **Windows DPAPI**（`win32crypt.CryptProtectData`） | 换机器、换 Windows 用户账户、离线拷走文件 | 同一用户账户下运行的任何进程 | ✅ 最合适 |
| `keyring` | 同上（Windows 后端本质就是 DPAPI/凭据管理器） | 同上 | 多一层依赖，无额外收益 |
| Argon2id 从口令派生（`argon2-cffi`） | 一切离线攻击，包括账户被攻陷 | 忘记口令 = 数据永久丢失 | ❌ 每次启动要用户输口令，与「双击就用的桌面工作台」冲突 |
| 明文 keyfile | **什么都不防**（密钥和密文同目录） | 一切 | ❌ 这正是 `.palace_ai_master_key` 的失败模式 |

**DPAPI 实测**（`M`）：`pywin32 312`，32 B 密钥 → 288 B 密文 blob，`CryptUnprotectData` 回读一致；**`pOptionalEntropy` 确实生效**——不带 entropy 解封失败（`(13, 'CryptUnprotectData', '数据无效。')`），带 entropy 成功。官方文档（`P1`，[MSDN CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)）原文：「Typically, only a user with logon credentials that match those of the user who encrypted the data can decrypt the data. In addition, decryption usually can only be done on the computer where the data was encrypted.」且「The function also adds a Message Authentication Code (MAC) … to guard against data tampering.」

⚠ `pywin32` **目前只是 `psutil` 的 dev/test extra 带进来的**，不保证存在。**采用即须在 `requirements.txt` 显式加 `pywin32; sys_platform == "win32"`**，否则会在用户机器上随机失踪。

### B4.7 ⚠ 评估历史决策：`.palace_ai_master_key` 这次会不会重蹈覆辙

**上次发生了什么**：`docs/master-plan-2026-07.md` §设计里写「Key 安全：AES-256-GCM 加密（AAD 绑定 `provider_id`），主密钥 `PALACE_AI_MASTER_KEY`」。今天 [`src/ai/infrastructure/crypto.py`](../../src/ai/infrastructure/crypto.py) 全文只剩一个 `mask_secret()`，文件 docstring 写着「**本机 LLM/MCP Key 明文存储，不再做主密钥加密**」；[`providers.py`](../../src/ai/infrastructure/providers.py) 的 `decode_provider_secret` 注释是「**旧 AES 密文一律视为失效**」，解不开的让用户去运维页重录。

**为什么失败？** 不是因为 AES-256-GCM 不好，是因为**密钥和密文在同一个爆炸半径里**。桌面版的主密钥是本地文件 `.palace_ai_master_key`，就躺在 `data/` 旁边。唯一现实的威胁是「有人拿到了这个目录」——而那个人同时也就拿到了密钥。**加密没有减少任何一种现实攻击的成功率，却新增了一个失败模式（密钥丢失 = Key 全废，用户被迫重录）。** 于是它被正确地删掉了。

**这次是否不同？必须逐条对齐，否则就是重蹈覆辙：**

| 上次失败的原因 | 这次的处置 | 是否真的不同 |
|---|---|---|
| 密钥与密文同目录，明文 keyfile | **数据密钥不以可用形式落盘**：32 B 随机 DEK 经 **DPAPI + entropy** 包裹后才写 `_keys/wrapped.key`。拷走整个 `data/` 到另一台机器/另一个 Windows 账户 → **解不开** | **✅ 真的不同** |
| 密钥丢失 = 数据永久损失，且损失的是不可再生的用户输入 | 被加密的是 **L4 盘中留存**——**可重建/可再采集的派生数据**，不是账本、不是用户输入的 Key。DPAPI blob 损坏最坏情况是「这 60 天的盘中回放没了」，不是「用户要重录 API Key」 | **✅ 真的不同** |
| 加密不减少任何现实攻击成功率 | 现实威胁变了：这次要防的是**「打分享包 / 备份到网盘 / 误提交」时把 60 天全市场盘口带出去**。DPAPI 密文在别的机器上无意义，**这个威胁是真的被防住的** | **✅ 真的不同** |
| 有性能/复杂度成本 | 实测读 **0.97×**、体积 **1.00×**、写 1.24×、代码约 40 行 | **✅ 成本近似为零** |

**判定：不会重蹈覆辙，但有一条硬约束——绝不把 L0/L1（权威日线与面板）加密。** 那两层是可公开的市场数据，加密它们只会重演「无收益 + 新失败模式」。**只加密 L4。**

### B4.8 ✅ 单一推荐方案

> **对 L4 盘中留存：DuckDB 原生 Parquet Modular Encryption（`AES_GCM_V1`，256-bit）+ 每库一个随机 DEK + Windows DPAPI（带 entropy）包裹 DEK + 按天分目录。**
> **对 L0 权威库与 L1 面板：不加密。**

选它的五条理由，全部有实测支撑：
1. **零新增依赖**——`duckdb` 已在 `requirements.txt`；只需显式补 `pywin32; sys_platform=="win32"`。
2. **零读性能代价**——343 ms vs 354 ms（`M`）。
3. **零体积代价**——0.977×（`M`）。
4. **零原生编译**——不碰 OpenSSL/MSVC，PyInstaller onedir 直接能打包（对比 SQLCipher 的必须自行编译）。
5. **保留列裁剪与谓词下推**——避免 §B4.4 的「加密即降级为磁带」陷阱。

**威胁模型（防谁 / 不防谁，必须写进 README）**

**防住：**
- 设备丢失/被盗后，从硬盘直接读取 `tape/` 目录 → DPAPI 绑定用户 SID + 机器，密文无意义
- 备份/网盘同步/误发分享包把 `tape/` 带出机器 → 同上（且 `ops/application/share_pack_sanitize.py` 的 `find_forbidden_files` 应追加 `tape/_keys/`）
- 同一台机器上**其它 Windows 用户账户**读取 → DPAPI 默认不带 `CRYPTPROTECT_LOCAL_MACHINE`，跨账户解不开
- 文件被篡改/被换成旧版本 → AES-GCM 认证标签 + Parquet AAD（含文件内标识与 module 序号）

**不防（必须明说，不要给用户虚假安全感）：**
- **以当前 Windows 用户身份运行的任何恶意进程**——DPAPI 对同用户任意进程解封，这是它的设计而非缺陷
- **应用运行期间**——DEK 必然在进程内存里，内存 dump 可取
- **勒索软件**——加密不阻止别人再加密一遍或直接删除；**这是备份的职责，不是加密的**
- **上游数据源**——数据在到达本机之前已经过第三方
- **凭据窃取 / 键盘记录 / 完整机器沦陷**
- **L0 `market.db` 与 L1 `panel/`**——按设计明文，任何人拿到即可读（它们本来就是公开市场数据）

---

## B5. 30–60 天滚动保留的工程模式

### B5.1 四种模式对比

| 模式 | 过期成本 | 碎片 | 峰值磁盘 | 适配 |
|---|---|---|---|---|
| SQLite 单表 `DELETE` | O(行数)，且**不还盘** | **严重** | 1× | ❌ |
| SQLite `DELETE` + `VACUUM` | O(全库) 重写 | 无 | **2×** | ❌ |
| SQLite `auto_vacuum=INCREMENTAL` | O(freelist) | 中（官方称可能更糟） | 1× | ⚠ 有两个静默陷阱 |
| TimescaleDB 式 chunk drop | O(1) `DROP TABLE` | 无 | 1× | 需 PostgreSQL，形态不符 |
| **按天/按周分文件 + 删目录** | **O(1) `unlink`** | **无** | **1×** | ✅ |

### B5.2 SQLite 三条路的实测（`M`，5,500 码 × 60 天 × 4 快照 = 1,320,000 行）

| 阶段 | A：`auto_vacuum=NONE` | B：`auto_vacuum=INCREMENTAL` | C：按天分文件 |
|---|---:|---:|---:|
| 建库后 | 119.0 MB | 119.2 MB | 119.5 MB（60 个文件） |
| 删掉前 30 天 | **119.0 MB**（`freelist=14,528/29,062` 页 = **50.0% 空洞**） | **119.2 MB**（`freelist=14,528/29,097` = 49.9%） | **59.8 MB（0.011 s）** |
| 回收 | `VACUUM` → 53.1 MB（0.6 s，需 2× 磁盘） | `PRAGMA incremental_vacuum` → **119.2 MB（无效！见下）** | **不需要** |

**为什么大表 DELETE 不还盘**（`P1`，[SQLite PRAGMA 文档](https://www.sqlite.org/pragma.html#pragma_auto_vacuum)原文）：「When auto-vacuum is disabled and data is deleted from a database, **the database file remains the same size**. Unused database file pages are added to a 'freelist' and reused for subsequent inserts.」而 `VACUUM` 文档（`P1`，[lang_vacuum](https://www.sqlite.org/lang_vacuum.html)）原文：「as much as **twice the size** of the original database file is required in free disk space.」

**⚠ `auto_vacuum=INCREMENTAL` 的两个静默陷阱（本轮实测踩到，仓库文档没记）：**

**陷阱 1 —— PRAGMA 顺序。** `auto_vacuum` 必须在**建表前**且在 `journal_mode=WAL` **之前**设置。实测四种顺序：

| 执行顺序 | `PRAGMA auto_vacuum` 实际值 |
|---|---:|
| `auto_vacuum=INCREMENTAL` → `journal_mode=WAL` | **2 ✅** |
| `journal_mode=WAL` → `auto_vacuum=INCREMENTAL` | **0 ❌ 静默失效** |
| 只 `auto_vacuum=INCREMENTAL` | 2 ✅ |
| 只 `journal_mode=WAL` | 0 |

官方文档对此有伏笔（`P1`）：「When in write-ahead log mode, **only the auto_vacuum support property can be changed using VACUUM**」——即进了 WAL 之后想改 auto_vacuum 必须跑一次全量 `VACUUM`。**没有任何报错，`PRAGMA auto_vacuum` 就是悄悄返回 0。**

**陷阱 2 —— Python 里必须 `.fetchall()`。** `PRAGMA incremental_vacuum` 是**返回结果集的 pragma**，`con.execute(...)` 不消费游标就等于没跑。实测对照：

| 调用方式 | 文件大小变化 | freelist |
|---|---|---|
| `con.execute("PRAGMA incremental_vacuum")` | 102.5 → **102.5 MB（纹丝不动）** | 12,499 → 12,499 |
| `con.execute("PRAGMA incremental_vacuum").fetchall()` | 102.5 → **51.3 MB（0.37 s）** | 12,499 → **0** |
| `…("PRAGMA incremental_vacuum(2000)").fetchall()` | 51.3 → **43.1 MB（0.06 s）** | 6,249 → 4,249 |

**如果非要在 SQLite 上做滚动窗口，正确配方是：**

```python
con = sqlite3.connect(path, isolation_level=None)
con.execute("PRAGMA auto_vacuum=INCREMENTAL")   # ① 必须最先，且必须在建表前
con.execute("PRAGMA journal_mode=WAL")          # ② 顺序反了 auto_vacuum 静默变 0
con.execute("PRAGMA synchronous=NORMAL")
con.execute(DDL)
...
con.execute("DELETE FROM spot WHERE ts < ?", (cutoff,))
# ③ 必须 .fetchall()：不消费游标 = 完全没执行（实测 102.5 MB 纹丝不动）
# 　 分批 2000 页，避免一次长事务卡住盘中写入
con.execute("PRAGMA incremental_vacuum(2000)").fetchall()
con.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # ④ 否则 -wal 只涨不缩
```

**写放大与 WAL 增长**：删掉 66 万行会把每个受影响的页写进 WAL；不做 `wal_checkpoint(TRUNCATE)`，`-wal` 文件会一直保持峰值大小（本轮建库阶段实测 WAL 峰值与主库同量级）。而按天分文件方案**根本没有 WAL 增长问题**——过期日的文件从来不被写入。

### B5.3 ✅ 推荐方案：按天分目录 + 目录级过期删除

**为什么选它**（不是「都行」，是有实测理由）：
1. **过期是 O(1) 的 `unlink`**：0.011 s vs `VACUUM` 的 0.6 s（且 VACUUM 在真实体量下是分钟级 + 需要 2× 磁盘）
2. **零碎片、零 freelist、零写放大**：过期的是整个文件，不是文件里的行
3. **原子性天然**：写当天的文件不影响任何历史天；崩溃最多损失当天
4. **加密天然对齐**：一天一个文件 = 一个 AAD 前缀 = 一次 GCM 调用预算，符合 Parquet 规范 §4.4.1 的「file swapping 防护」设计
5. **备份/同步友好**：昨天以前的文件永不变更，增量备份只传今天
6. **与本仓既有哲学一致**：ADR-002/007 的「派生缓存可整段删除重建」

**目录布局**

```
data/
  market.db      # L0 权威：SQLite，不动，不加密
  panel/       # L1 面板（新）：不加密，纯派生，可整目录重建
    daily/
      year=2024/data.parquet
      year=2025/data.parquet
      year=2026/data.parquet
    _MANIFEST.json         # 生成时间 / 源库 mtime / 行数 / schema 版本
  tape/               # L4 盘中滚动留存（新）：加密，60 交易日滚动
    _keys/
      wrapped.key             # DPAPI(CryptProtectData) 包裹的 32B DEK，实测 288 B
      key.meta.json                  # {kid, created_at, alg:"AES_GCM_V1", entropy_label}
    2026-08-25/
      spot_5m.parquet          # 加密
      minute.parquet        # 加密
      auction.parquet         # 加密
      limit_events.parquet     # 加密
      sector_flow.parquet    # 加密
      dragon_tiger.parquet           # 加密
      _MANIFEST.json           # 明文：日期/各文件行数/schema 版本/SHA-256/kid（不含密钥）
    2026-08-26/
      ...
```

**为什么目录名就是 `YYYY-MM-DD`**：`ISO-8601` 的字典序 == 时间序，过期判断退化成一次字符串比较，不需要解析日期、不需要读文件内容、不需要索引。

**过期删除逻辑**（可直接落地，含三道安全闸门）

```python
RETENTION_TRADING_DAYS = 60      # 诉求 3 的 30-60 天，取上限
MAX_DELETE_PER_RUN     = 10    # 闸门①：一次最多删 10 天，异常时不会一夜清空
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
TAPE_ROOT = data_dir() / "tape"


def prune_tape(*, calendar: list[str], dry_run: bool = False) -> dict:
    """按交易日历保留最近 N 个交易日的盘中留存目录。calendar 为升序交易日列表。"""
    keep = set(calendar[-RETENTION_TRADING_DAYS:])
    # 闸门②：按交易日历而非自然日。长假后按自然日会多删 7-10 个交易日；
    #    日历读残了就整轮跳过——宁可涨库，不可误删。
    if len(keep) < RETENTION_TRADING_DAYS:
        return {"skipped": "calendar_too_short", "have": len(keep)}

    # 闸门③：正则白名单。_keys/ 与任何非 YYYY-MM-DD 目录永不进候选集。
    days = sorted(
        d for d in TAPE_ROOT.iterdir()
        if d.is_dir() and _ISO_DAY.fullmatch(d.name)
    )
    victims = [d for d in days if d.name not in keep][:MAX_DELETE_PER_RUN]

    freed = 0
    for d in victims:
        freed += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        if not dry_run:
            shutil.rmtree(d)
    return {
        "removed": [d.name for d in victims],
        "freed_bytes": freed,
        "kept": len(days) - len(victims),
        "truncated": len([d for d in days if d.name not in keep]) > MAX_DELETE_PER_RUN,
    }
```

**三道闸门的理由**：① `MAX_DELETE_PER_RUN` —— 如果交易日历读出来是空的或错的，没有它就是一次性删光 60 天；② 按**交易日历**而非自然日 —— 长假后按自然日会多删 7–10 个交易日；③ 正则白名单 —— `_keys/` 和任何非日期目录永远不进候选集。

**挂载点**：本仓已有 `MANAGED_PRUNE` 托管任务（`kind=prune`，默认 cron `30 2 * * mon-fri`，见 [`src/ops/README.md:238`](../../src/ops/README.md)），它已经在清 `job_runs` / `leader_role_snapshots` / `second_wave_signals`。**`prune_tape` 直接挂进 [`src/ops/application/jobs/prune.py`](../../src/ops/application/jobs/prune.py) 即可，不需要新建任务、不需要新 cron。**

**为什么不按周分文件**：按天 60 个目录，按周只有 9 个。周粒度会让「保留 60 天」实际变成保留 56–63 天的抖动，且过期时一次删掉 7 天的数据。**按天的文件数（60 × 5 = 300 个文件）完全在可接受范围**（对比 qlib .bin 的 33,282 个）。

---

## B6. 盘中实时数据存什么才有量化价值

### B6.0 前提与口径

- **没有 Level-2。** 公开免费源拿不到逐笔委托/委托队列/撤单明细。能拿到的最细粒度是**交易所 3 秒行情快照**（含最优五档），以及各家网站对它的重采样。下面所有「tick」都指这个，不是逐笔成交。
- **本仓当前留存 = 0。** 分钟线不落库（`GET /api/market/minute/{code}` 明确不写 `market.db`），live 只有进程内 3–5 秒 TTL 缓存（`M*`）。**这一节描述的是从零建的东西。**
- **60 天口径**：诉求 3 说「30–60 天」。60 **自然日** ≈ 41 交易日；下表按 **60 个交易日**给**上界**，实际盘子会小 1/3。
- **加密后**：按 §B4.3 实测的 AES-256-GCM 1 MiB 分块膨胀 **+0.0027%** 计（DuckDB 原生 Parquet 加密实测为 0.977×，属写出参数差异，两者都可视为 **1.00×**）。**加密在这张表上不改变任何一个数量级——这正是它值得做的原因。**

### B6.1 「每种数据 × 采样频率 × 60 交易日」磁盘占用（`M` 实测）

单行成本全部为本机实测：spot **17.0 B/行**（9 列，自相关价 + `code,ts` 排序）、分钟 K **13.38 B/行**（8 列）、3 秒快照 **13.63 B/行**。全部 Parquet + Zstd-3。

| # | 数据 | 采样频率 | 行/交易日 | 明文/日 | **明文 / 60 交易日** | **加密后 / 60 交易日** | 加密增量 |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | 涨停/炸板事件流 | 事件驱动（≈300 条/日） | 300 | 0.007 MB | **0.42 MB** | 0.42 MB | +1.8 KB |
| 2 | 龙虎榜 | 1 次/日（≈1,000 行） | 1,000 | 0.018 MB | **1.08 MB** | 1.08 MB | +1.6 KB |
| 3 | 板块与概念资金流 | 5 分钟（400 板块×48） | 19,200 | 0.732 MB | **43.9 MB** | 43.9 MB | +1.2 KB |
| 4 | 全市场 spot 快照（9 列） | 每小时（4/日） | 22,000 | 0.374 MB | **22.4 MB** | 22.4 MB | +0.6 KB |
| 5 | 全市场 spot 快照（9 列） | 10 分钟（24/日） | 132,000 | 2.24 MB | **134.5 MB** | 134.5 MB | +3.6 KB |
| 6 | **全市场 spot 快照（9 列）** | **5 分钟（48/日）** | 264,000 | 4.49 MB | **269.0 MB** | **269.0 MB** | +7.3 KB |
| 7 | **集合竞价逐笔（9:15–9:25）** | **3 秒（200 点/票）** | 1,100,000 | 10.90 MB | **654.2 MB** | **654.2 MB** | +17.7 KB |
| 8 | **全市场分钟 K** | 1 分钟（240 根/票） | 1,320,000 | 17.66 MB | **1,059.8 MB** | **1,059.9 MB** | +28.6 KB |
| 9 | 全市场 spot 快照（9 列） | 1 分钟（240/日） | 1,320,000 | 22.41 MB | **1,344.8 MB** | 1,344.9 MB | +36.3 KB |
| 10 | 全市场 spot + 五档（29 列） | 1 分钟（240/日） | 1,320,000 | 114.44 MB* | **6,866.4 MB** | 6,866.6 MB | +185 KB |
| 11 | 全市场 spot 快照（9 列） | 10 秒（1440/日） | 7,920,000 | 134.5 MB | **8,068.8 MB** | 8,069.0 MB | +218 KB |
| 12 | 全市场 3 秒快照（8 列） | 3 秒（4800/日） | 26,400,000 | 359.8 MB | **21,588 MB** | 21,589 MB | +583 KB |

\* 第 10 行用的是随机价合成上界；真实自相关数据会低约 28%（实测：随机 31.09 MB vs 自相关+排序 22.41 MB，同为 240 snap/日）。**其余行已使用自相关口径。**

**同一份数据存 SQLite 要多少**（对照，`M` 实测 76.6 B/行）：第 8 行分钟 K 变成 **6,070 MB**（5.7×），第 12 行 3 秒快照变成 **121,500 MB = 121 GB**（5.6×）。**行存把这件事从「能做」变成「不能做」。**

### B6.2 按「量化价值 / 存储代价」排序

评价「价值」的三条标准：**① 不可重建性**（过期就永远拿不到了）；**② 对 1–5 日持有策略的直接可用性**；**③ 是否已被本仓策略引用**。

| 排名 | 数据 | 60 日代价 | 不可重建 | 价值 | 判定 |
|---:|---|---:|:---:|---|---|
| **1** | **涨停/炸板事件流** | **0.42 MB** | **✓✓** | 连板梯队、首封时间、炸板次数、封单额、回封标签——**A 股短线的核心状态量**，且**全部是盘中事实，日 K 里一个都没有**。本仓 `limit_up_filter` / `limit_up_ladder` 已重度依赖 | **必存。代价小到不值得讨论** |
| **2** | **龙虎榜** | **1.08 MB** | ✗（交易所永久公开） | 游资席位追踪，本仓 `dragon_tiger` 已用 | **必存**（1 MB，存了省事） |
| **3** | **板块/概念资金流** | **43.9 MB** | **✓✓** | 判断当日主线、题材强度。盘中快照过期即失，第三方不回补 | **必存** |
| **4** | **集合竞价逐笔（9:15–9:25）** | **654 MB** | **✓✓✓ 最高** | 9:15–9:20 可撤单段的**撤单行为**、9:20 后不可撤单段的真实意愿、尾秒抢筹/撤退——**9:25 一到，这段过程数据在所有免费源上彻底消失**。本仓 `auction_*` 系列工具全靠它 | **必存。这是全表不可逆性最高的一项** |
| **5** | **全市场分钟 K** | **1,060 MB** | ✗（TDX/东财可回补） | 盘中进出场真实性、VWAP、分时形态。本仓已有 `tdx_minute.py` / `eastmoney_minute.py` 但**不落库** | **建议存**。可回补，但每次回补都是 5,500 次远程请求 |
| **6** | 全市场 spot 快照 **5 分钟** | **269 MB** | ✓ | 市场宽度时间序列、涨速榜、盘中最低/最高路径。`2026-08-dragon-second-wave-live-alert-spec.md` 的触发式（当日最低 ≤ MA10 < 现价）就吃这个 | **建议存**。5 分钟是甜点 |
| 7 | 全市场 spot 快照 1 分钟 | 1,345 MB | ✓ | 相对分钟 K 的边际信息很少（价格路径重合） | 可不存 |
| 8 | 全市场 spot + **五档** 1 分钟 | 6,866 MB | ✓ | 免费源的五档是 **L1 最优五档快照**，不是 L2 委托流；能看到的封单信息，第 1 项已用 0.42 MB 给了 | **不建议**。16,000 倍代价换重复信息 |
| 9 | 全市场 spot 10 秒 | 8,069 MB | ✓ | 免费源本身刷新就在 3–5 秒且延迟不稳，10 秒采样里大量是重复行 | 不建议 |
| 10 | 全市场 3 秒快照 | 21,588 MB | ✓ | 无 L2 配合时，3 秒粒度对 1–5 日策略没有可验证的增量 alpha | 不建议 |

### B6.3 ✅ 推荐留存组合

**第 1–6 项全存，60 个交易日合计：**

```
0.42 MB  涨停/炸板事件流
1.08 MB  龙虎榜
   43.9 MB  板块与概念资金流（5 分钟）
  654.2 MB  集合竞价逐笔（3 秒，9:15-9:25）
1,059.8 MB  全市场分钟 K
  269.0 MB  全市场 spot 快照（5 分钟）
────────────
2,028.4 MB ≈ 2.03 GB（加密后 2.03 GB，+55 KB）
```

**换算成 60 自然日（≈41 交易日）：约 1.39 GB。**

**这个数字要和两件事对照才有意义：**
- 现在那个 **`market_hot.db` 是 1,022 MB**，而 §A2.3 已经实测它比 411 MB 的 Parquet 面板**慢 7.1 倍**、大 2.5 倍，**建议删掉**。
- 删掉热库省下的 1,022 MB，**正好覆盖这套盘中留存的一半**。诉求 3 的净增磁盘占用只有约 **1 GB**。

**至于每天几分钟的采集成本**：第 4 项（竞价）只在 9:15–9:25 采 200 次；第 6 项（spot 5 分钟）全天 48 次；第 5 项（分钟 K）盘后一次性拉。**都不需要常驻高频轮询**，与本仓现有 `intel_fetch`（`*/15 9-14`，24 轮/日）的调度形态兼容。

---

# C. 落地清单（按「收益/风险」排序）

| # | 动作 | 收益 | 风险 | 前置 |
|---:|---|---|---|---|
| 1 | **`DROP INDEX idx_quotes_receipt`**（全量库 + 热库） | **省 1,287.3 MB**（1,049.0 + 238.3），一条 DDL | 低。仅影响「按回执反查日 K」的低频运维查询 | 先确认无热路径依赖 |
| 2 | 新增 `panel/daily/year=*/…parquet`（L1），date-major | 主查询 **2,040 → 289 ms**（7.1×），411 MB | 低。纯派生，可整目录删 | 写一个 `mirror_to_parquet()` |
| 3 | 选股/回测/行情读端切到 L1；**删除 `market_hot.db`** | 再省 **1,022 MB** | 中。要覆盖 ADR-007 列的全部读端 | 依赖 #2 |
| 4 | `duckdb_panel.py` 的 `sqlite_scanner` 分支改读 Parquet | 把现有旁路从 1.3× 提到 7.1× | 低。开关仍是 `LOCI_MARKET_DUCKDB` | 依赖 #2 |
| 5 | 溯源表按 §A3.6 分层（近 24 月留 SQLite，更早导 Parquet） | 省约 **1.2 GB** | 中。要保住 PIT 研究的可查性 | 需实跑确认压缩比 |
| 6 | 建 `tape/` 盘中留存（第 1–6 项，加密） | 实现诉求 3 | 中。**新采集链路，是本清单里唯一的「新建」** | `requirements.txt` 补 `pywin32` |
| 7 | `prune_tape` 挂进现有 `MANAGED_PRUNE` | 60 日滚动自动化 | 低。任务已存在 | 依赖 #6 |
| 8 | `share_pack_sanitize.find_forbidden_files` 追加 `tape/_keys/` | 防止密钥进分享包 | 低 | 依赖 #6 |
| 9 | 查 `ops.db` 的 `job_runs` 为什么 **16 KB/行** | 13.8 MB 里 11.36 MB 是它 | 低 | — |

**#1 + #3 两条加起来省 2.3 GB，都不需要写新代码，也不删任何一行历史数据。** 这是对「历史数据太庞大」最直接的回答。

---

# D. 一手来源清单

| 编号 | 来源 | 级别 | 用于 |
|---|---|---|---|
| S1 | 主 agent dbstat 实测 2026-08-25（生产 `market.db` / `market_hot.db` / `ops.db` / `palace.db` 分表体积、行数、逐年行数、依赖清单、分钟线不落库） | `M*` | §A1.1、§A3.6、§B6.0 |
| S2 | 本轮本机实测，脚本在 `%TEMP%/qbstore/`：`bench.py`（九格式合成对照）、`real.py`（真实 16.97M 行导出）、`query.py`（主查询）、`crypto_bench.py`（AEAD 膨胀/吞吐）、`rolling.py` + `av.py` + `av2.py`（滚动窗口）、`intraday.py` + `intra2.py` + `mt.py`（盘中体量）、`sigma.py` + `sigma2.py` + `icc.py`（σ 与 ICC）、`power.py`（功效表）、`duckenc.py` + `duckenc2.py`（DuckDB Parquet 加密） | `M` | 全文 |
| S3 | [SQLCipher Design](https://www.zetetic.net/sqlcipher/design/) —— AES-256-CBC / 逐页 IV / HMAC-SHA512 / PBKDF2 256,000 轮 | `P1` 全文已读 | §B4.1 |
| S4 | [SQLCipher Performance](https://www.zetetic.net/sqlcipher/performance/) —— 「as little as 5-15% overhead」原文 | `P1` 全文已读 | §B4.1 |
| S5 | [PyPI `sqlcipher3-binary` JSON](https://pypi.org/pypi/sqlcipher3-binary/json) —— 0.4.0→0.6.0 全量 wheel 清单，`win_amd64` 零命中 | `M` 全量扫描 | §B4.1 |
| S6 | [PyPI `pysqlcipher3` JSON](https://pypi.org/pypi/pysqlcipher3/json) —— 仅 sdist，末版 2023-01-29，要求预装 libsqlcipher | `M` 全量扫描 | §B4.1 |
| S7 | [Apache Parquet Modular Encryption](https://parquet.apache.org/docs/file-format/data-pages/encryption/)（PARQUET-1178）—— module 划分、AES_GCM_V1 / AES_GCM_CTR_V1、AAD prefix/suffix 构造、NIST SP 800-38D 2³² 调用上限 | `P1` 全文已读 | §B4.5 |
| S8 | [pyarrow Parquet 文档](https://arrow.apache.org/docs/python/parquet.html) —— 加密需 `-DPARQUET_REQUIRE_ENCRYPTION=ON` + 自实现 `KmsClient`；「Parquet data … can't be directly mapped from disk」 | `P1` 全文已读 | §A2.2、§B4.5 |
| S9 | [SQLite PRAGMA auto_vacuum / incremental_vacuum / freelist_count](https://www.sqlite.org/pragma.html#pragma_auto_vacuum) —— 「the database file remains the same size」「must be turned on before any tables are created」 | `P1` 全文已读 | §B5.2 |
| S10 | [SQLite VACUUM](https://www.sqlite.org/lang_vacuum.html) —— 「as much as twice the size … required in free disk space」 | `P1` 全文已读 | §B5.2 |
| S11 | [fernet/spec `Spec.md`](https://github.com/fernet/spec/blob/master/Spec.md) —— AES-128-CBC、base64url、无 AAD | `P1` 全文已读 | §B4.3 |
| S12 | [MSDN `CryptProtectData`](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) —— 用户+机器绑定、`pOptionalEntropy`、自带 MAC | `P1` 全文已读 | §B4.6 |
| S13 | [qlib `scripts/dump_bin.py`](https://raw.githubusercontent.com/microsoft/qlib/main/scripts/dump_bin.py) —— `np.hstack([date_index, values]).astype("<f").tofile()`，即小端 float32 + 4 字节头，每 (票,字段,频率) 一文件 | `P1` 源码已读 | §A1.2、§A1.4 |
| S13b | 同批次 `_scratch_2026-08-qb-qlib.md` 实测：官方 CN 日线包 3,875 只 × 7 字段 = 271.1 MB，单字段 40,604,372 B / 10,147,218 槽位 = **4.0 B/槽位**（与本文 24 B/行 算式互证） | `M`（姊妹篇） | §A1.4 |
| S14 | [qlib `docs/component/data.rst`](https://github.com/microsoft/qlib/blob/main/docs/component/data.rst) —— `.bin` 定位与生成流程 | `P1` 已读 | §A1.4 |
| S15 | [ArcticDB README](https://github.com/man-group/ArcticDB) —— BSL 1.1 原文、版本转 Apache 2.0 时间表、LMDB 本地后端、Windows wheel | `P1` 已读 | §A1.5 |
| S16 | [facebook/zstd README](https://github.com/facebook/zstd) —— Silesia 语料 lzbench 结果（zstd 1.5.7 -1：ratio 2.896 / 510 MB·s⁻¹ / 1550 MB·s⁻¹） | `P1` 已读 | §A1.2 |
| S17 | [ClickHouse CREATE TABLE 文档](https://clickhouse.com/docs/sql-reference/statements/create/table#column_compression_codec) —— 列级 CODEC | `P1` 已读 | §A1.5 |
| S18 | [RFC 9106 Argon2](https://www.rfc-editor.org/rfc/rfc9106) | `P1` 摘要与元数据已读，全文未逐节读 | §B4.6 |
| S19 | 通达信 `.day` 32 字节定长（`struct '<IIIIIfII'`：date/open/high/low/close 为 int32×100、amount 为 float32、vol 为 int32、1 个保留字段） | `P2` 多个独立社区实现互证，**官方无公开规范** | §A1.2 |
| S20 | 本仓：[`store_schema.py`](../../src/market/infrastructure/store_schema.py)、[`duckdb_panel.py`](../../src/market/infrastructure/duckdb_panel.py)、[`polars_panel.py`](../../src/market/infrastructure/polars_panel.py)、[`store_hot.py`](../../src/market/infrastructure/store_hot.py)、[`jobs/prune.py`](../../src/ops/application/jobs/prune.py)、[`crypto.py`](../../src/ai/infrastructure/crypto.py)、[`ADR-002`](../adr/ADR-002-duckdb-readonly-panel.md)、[`ADR-007`](../adr/ADR-007-market-hot-readonly-window.md)、[`quant-toolkit.md`](../quant-toolkit.md)、[`scripts/build-loci.ps1`](../../scripts/build-loci.ps1)、[`requirements.txt`](../../requirements.txt) | `P1` 已读 | 全文 |

---

# E. 本轮做了什么 / 未做

**做了（全部只读或写临时目录）**
- 以 `READ_ONLY` / `mode=ro` 挂载生产 `market.db`（5.74 GB）与 `market_hot.db`，只跑 SELECT / COPY-OUT：导出真实 16,966,403 行到 7 种列存布局并量体积；跑主查询 8 种读路径 ×3 次取最优；在 1,029 万条样本上算 σ / ICC / 分年分段离散度。
- 生成与 `quotes_daily` **同 schema** 的 1,375,000 行合成数据，测 SQLite / Parquet / Arrow IPC / DuckDB / qlib `.bin` / `.day` 共 17 种落盘形态，并用合成 SQLite（163.6 B/行）与生产实测（160.5 B/行）**互相校准**。
- 实测 AES-256-GCM（整块/64 KiB/1 MiB/4 MiB）、ChaCha20-Poly1305、Fernet 的密文膨胀与吞吐；实测 DuckDB 原生 Parquet 加密的体积/读写代价与无密钥拒绝行为；实测 Windows DPAPI 往返与 `pOptionalEntropy` 生效性。
- 实测 SQLite 滚动窗口三条路，**发现并复现两个静默失效陷阱**（`auto_vacuum` 与 `journal_mode` 的顺序；`incremental_vacuum` 必须 `.fetchall()`）。
- 全量扫描 `sqlcipher3-binary` / `pysqlcipher3` 的 PyPI 发布清单，确认 Windows wheel 缺失。

**未做（不要把下列内容当结论引用）**
- **未改任何仓库文件**（含 `INDEX.md`）、未 commit / push、未写任何生产库、未跑仓库测试。
- **未实测** HDF5、ArcticDB、ClickHouse（分别因缺 `h5py`/`tables`、BSL 许可、形态不符）。三者在 §A1.2 表中标注为未实测。
- **未实测** §A3.6 中 L2 溯源表分层后的精确体积（只给了算式与保守区间 300–400 MB）。
- **未实现** `mirror_to_parquet()` / `tape/` 采集链路 / `prune_tape()`；§B5.3 的代码是**设计草案**，未运行、未测试。
- **未验证**免费数据源在 3 秒/10 秒粒度上的**真实刷新率与延迟稳定性**——§B6.1 第 11/12 行的行数是理论上界，实际可采到的独立快照数可能显著更少。
- σ / ICC 的样本**带有本仓已知的存活偏差**（`delist_date` 填充数 = 0，退市股行情不在库内，`M*`）。§A3.5 已就此明确加注；**功效表的绝对年数应视为乐观值**。
- ICC 用的是**全市场**日内相关；具体战法若集中在单一题材，ICC 会更高、有效样本更少。**§A3.4 的 t 值是上界。**

---

## 摘要

**体量的真凶是行存与逐行溯源，不是历史长度。** 生产 `market.db` 实测 5,740.2 MB（文档记的 2.4 GB 已过时），其中 44.8% 是溯源表与索引；同样 16,966,403 行导出 Parquet+Zstd 只要 **395.6 MB**（10.6×），而那三个溯源列在列存里只值 0.6 MB。主查询实测 **289 ms vs 现状 2,040 ms（7.1×）**，但**压缩最优的 `code` 排序在主查询上慢 4.8 倍**——分区必须 date-major。仅 `DROP INDEX idx_quotes_receipt` + 用 Parquet 面板替掉 `market_hot.db`，**不删任何一年历史就省 2.3 GB**。

**历史长度分两个答案**：超额口径的截面残差 σ 在 2010–2026 四段间只在 4.75%–5.35% 抖动，**测 alpha 三到五年够**；但总收益 σ 在 2015 年是 2017 年的 1.98 倍，**测回撤必须留住极端年份**——只是那些年份带双重存活偏差，本地不可信。实测 ICC=0.2822：潜龙 24,878 笔的有效样本只有 2,090，t=2.13；分手快乐 495 笔 t=3.14。

**加密有唯一赢家**：DuckDB 1.5.5 原生 Parquet 加密，读 343 ms vs 明文 354 ms、体积持平、无密钥硬失败；SQLCipher 因 Windows wheel 全缺而出局，Fernet 因 +33.3% 膨胀出局。配 DPAPI 包裹的随机 DEK，**只加密盘中留存，不加密公开行情**。滚动窗口用按天分目录，删目录 0.011 秒、零碎片。**值得存的六类盘中数据，60 个交易日合计 2.03 GB。**
