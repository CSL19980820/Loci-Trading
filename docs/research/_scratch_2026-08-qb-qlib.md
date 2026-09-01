# Microsoft Qlib 体系设计拆解与单机 A 股工作台可借鉴点（scratch）

> **日期**：2026-08-25 ｜ **检索日期**：2026-08-25
> **被审对象**：`microsoft/qlib`，锁 commit **`79633dd9506ea689e5400dea0197717b5b3d74b7`**（main，2026-07-23，"feat(config): add explicit validation for required configuration fields (#2078)"）。MIT License。本轮 `git clone --depth 1` 到本地逐文件读源码，行号均指该 commit。
> **用途**：回答「Qlib 的数据层 / 表达式引擎 / Alpha158 / PIT / workflow / 回测 / RL 各是怎么设计的」，以及在 **SQLite + 1.1 GB 可用内存 + DDD 模块化单体** 约束下哪些该抄、哪些是负担。
> **范围**：只读。除本文件外未改任何仓库文件，未 commit / push，未写库，未安装 qlib，未下载完整数据包（只用 HTTP Range 读了官方 zip 的中央目录与两个 txt 成员）。
> **证据分级**：`P1` 源码本轮逐行读过并给出 `owner/repo/path:line`；`P1-实测` 本轮在本机跑出的数字（.bin 二进制回环、zip 中央目录、算子计数）；`P1-主` 主 agent 2026-08-25 dbstat 实测本机 `E:\entertainment_software\Loci\data`；`P2` 官方 docs / GitHub issue 原文；`推断` 由前述事实推导，已逐处标注。
> **与既有文档的关系**：[`2026-08-github-open-source-technology-radar.md`](./2026-08-github-open-source-technology-radar.md) 把 `microsoft/qlib` 列为 **P1**（"research 私有实验区，仅导入冻结 OHLCV/PIT 输入；不注册活动 strategy"）。本文是那一行的**源码级展开与再判定**，不复制其清单。组合口径脆弱性引用 [`2026-08-dragon-survivorship-and-portfolio-fragility.md`](./2026-08-dragon-survivorship-and-portfolio-fragility.md)。

---

## 1. 一句话结论

Qlib 是**为"多模型 × 多次重训 × 服务化"设计的研究平台**。它的三个核心资产——可复现的实验记录、组合层双成本口径、topk/n_drop 换仓语义——是纯协议、零基建，抄进来立刻见效；它三个"看起来最诱人"的资产——`.bin` 列存、Disk 缓存、`eval` 表达式引擎——都建立在"有多核、有 Redis、有 HDF5、数据只读且无逐行溯源"的前提上，与我们 SQLite 单进程 + 逐行 receipt + 1.1 GB 内存的边界**方向相反**，抄了是负担。

数据层的核心事实（**P1-实测**）：官方 `qlib_data_cn_1d_latest.zip` 下载 **196,549,189 B（196.5 MB）**，解压 **284,507,633 B（271.3 MB）**，31,008 个条目 = 3,875 只 × 7 字段 = 27,125 个 `.day.bin`（271.1 MB）+ 5 个 `.txt`（0.3 MB）。单字段 40,604,372 B ⇒ **10,147,218 个 (票, 日) 槽位**，平均每票 2,619 根。**全市场 CN 日线 7 字段的实际磁盘占用就是 271 MB**——因为每个值只花 4 字节，没有行头、没有索引、没有溯源列。

---

## 2. 数据层：`.bin` 到底怎么设计的

### 2.1 目录布局

```text
<provider_uri>/
├── calendars/
│   ├── day.txt                # 每行一个 YYYY-MM-DD，全市场唯一交易日历
│   └── day_future.txt                # 可选，含未来日历
├── instruments/
│   ├── all.txt         # <CODE>\t<start_datetime>\t<end_datetime>
│   └── csi100.txt / csi300.txt / csi500.txt  # 同格式；一只票可多行 = 多段成分区间
├── features/
│   └── <code 小写>/<field 小写>.<freq>.bin     # 例：sh600000/close.day.bin
└── financial/
    └── <code 小写>/<field>.data + <field>.index   # PIT，见 §5
```

- 路径由 `FileStorageMixin.uri` 拼成 `dpm.get_data_uri(freq)/<storage_name>s/<file_name>`（`microsoft/qlib/qlib/data/storage/file_storage.py:59-63`）；`FileFeatureStorage.__init__` 把 `file_name` 定为 `f"{instrument.lower()}/{field.lower()}.{freq.lower()}.bin"`（同文件 `:285-289`）。
- 写侧常量在 `microsoft/qlib/scripts/dump_bin.py:53-66`：`CALENDARS_DIR_NAME` / `FEATURES_DIR_NAME` / `INSTRUMENTS_DIR_NAME` / `DUMP_FILE_SUFFIX=".bin"`，`INSTRUMENTS_FILE_NAME="all.txt"`。
- 实测（**P1-实测**，HTTP Range 读 zip 中央目录 + inflate 两个成员）：`calendars/day.txt` 54,373 B / **4,943 行**，首行 `1999-11-10`、末行 `2020-09-25`；`instruments/all.txt` 124,000 B / **3,875 行 / 3,875 个唯一代码**，首行 `SH000300\t2005-01-04\t2020-09-25`；`instruments/csi300.txt` **820 行**（同一代码多行 = 多段成分区间，这就是它的历史成分表）。

### 2.2 单个 bin 文件的二进制结构 —— 首元素是起始索引，而且它是 float32

写：`np.hstack([date_index, _df[field]]).astype("<f").tofile(...)`（`scripts/dump_bin.py:245-269`，落笔在 `:269`）。`date_index = calendar_list.index(_df.index.min())`（`:242-243`）——**该股票第一根 K 线在全市场日历里的下标**。

读：

| 语义 | 实现 | 位置 |
|---|---|---|
| `start_index` | `int(np.frombuffer(fp.read(4), dtype="<f")[0])` | `file_storage.py:331-336` |
| `__len__` | `self.uri.stat().st_size // 4 - 1` | `file_storage.py:377-379` |
| `end_index` | `start_index + len(self) - 1` | `file_storage.py:339-343` |
| 点读 `i` | `fp.seek(4 * (i - start_index) + 4); struct.unpack("f", fp.read(4))` | `file_storage.py:358-362` |
| 切片 | `fp.seek(4*(si-start_index)+4); np.frombuffer(fp.read(4*count), dtype="<f")` | `file_storage.py:363-373` |

同一格式复用于表达式磁盘缓存：`read_bin(file_path, start_index, end_index)`（`qlib/utils/__init__.py:54-68`）逐字节等价。

**本轮实测回环**（P1-实测，复刻上面两段代码）：写入 `date_index=1234` + 5 个值 → 文件 24 B；`size//4-1 = 5`；头 4 字节 `00409a44`，按 `<f` 读是 `1234.0`，按 `<i` 读是 `1150959616` ⇒ **首元素确实是 float32 而非 int32**；`i=1236` 点读得 `10.029999732971191`（float32 精度）；切片 `[1235,1237)` 得 `[10.02 10.03]`。

三个由此推出的约束（**推断**，基于 IEEE-754，其中精度数字为实测）：

1. 起始索引用 float32 承载，**只能精确表示到 2^24 = 16,777,216**。实测 `float32(2**24+1) = 16777216`。日线（4,943 日）、1min（约 120 万根）都安全，tick 级不安全。
2. **数值本身也是 float32**，相对误差上界 2^-24 ≈ 6e-8。实测 `123,456,789 → 123,456,792`（差 3 元）、`16,777,217 → 16,777,216`。成交额、成交量这类大整数会掉精度——研究可接受，**账本不可接受**。
3. 没有 magic number、没有版本号、没有 dtype 头、行内没有日期。文件损坏或字段语义变更不可自检，只能靠 `scripts/check_dump_bin.py` 事后逐值比对源 CSV。

### 2.3 为什么按「每股票每字段一个文件」而不是按日期分区

答案在**并行模型**，不在存储本身。`DatasetProvider.dataset_processor` 为每只票生成一个 `delayed(inst_calculator)` 任务，用 `ParallelExt(n_jobs=workers, backend=C.joblib_backend, maxtasksperchild=...)` 跑（`qlib/data/data.py:548-598`；默认 `joblib_backend="multiprocessing"`、`kernels=NUM_USABLE_CPU`，`qlib/config.py:182,188`）。源码注释直说：`# One process for one task, so that the memory will be freed quicker.`（`data.py:555`）

这个布局的直接后果：

- **一个 worker 只碰自己那只票的 7 个小文件**：零跨进程共享、零锁、零大 DataFrame pickle。单票工作集 = 2,619 根 × 7 字段 × 4 B ≈ **71.6 KB**。
- 取"某票全历史某字段" = 1 次 open + 1 次 seek + 1 次连续 read。**这是"少票 × 长历史"的最优布局。**
- 反过来，取"全市场某日截面" = 5,500 次 open + 5,500 次 seek。**"全市场 × 短窗"是它最差的用例**——而那恰好是我们选股/回测 100% 的用例（`src/market/infrastructure/store_panel.py:71` `load_panel` 的语义就是"全市场面板"）。
- 若按日期分区则相反：加一天要改 5,500 个文件里的 1 行 vs 改 1 个文件。Qlib 选前者，是因为它假设"历史只读、每天只追加一次、追加由离线脚本做"。

### 2.4 读取时如何按 calendar 索引切片

`LocalExpressionProvider.expression`（`qlib/data/data.py:833-879`）四步：

1. `Cal.locate_index(start_time, end_time, freq, future=False)` 把时间转成**日历下标** `start_index/end_index`（`:852`）。
2. `lft_etd, rght_etd = expression.get_extended_window_size()` 问算子树"为了算这段我得往左/右多读几根"，然后 `query_start = max(0, start_index - lft_etd)`、`query_end = end_index + rght_etd`（`:853-854`）。这是**预热窗自动推导**：`Mean($close,60)` 自动多读 59 根，调用方不必手算。
3. `expression.load(instrument, query_start, query_end, freq)` 下推到 `Feature._load_internal → FeatureD.feature(...)` → 文件里 `seek(4*(si-start_index)+4)`。
4. 结果 `astype(np.float32)` 后 `series.loc[start_index:end_index]` 裁回请求区间（`:872-878`）。

所以**日历是全局唯一的整数坐标系**，bin 只存"我从第几号开始"；中间停牌日由 `data_merge_calendar` 的 `df.reindex(cal_df.index)` 补成 NaN（`dump_bin.py:227-240`）。**稠密对齐是这套设计成立的前提**，也是它最脆的地方。

### 2.5 增量更新 `dump_update` 怎么做，以及它的已知错位

`DumpDataUpdate`（`dump_bin.py:392-539`）：

- `__init__`：读旧 `calendars/day.txt` 与 `instruments/all.txt`；**把所有源 CSV 全量读进内存**（`_load_all_source_data`，`:449-472`，注释自承 `# NOTE: Need more memory`）；新日历 = 旧日历 + 所有票中晚于旧日历末日的唯一日期（`:445-447`）。
- `_dump_features`（`:493-530`）：按 `symbol` 分组。**已存在的票**只取 `date > all.txt 里该票 end_datetime` 的那些行，并把**这些行自己的日期**当作 `calendar_list` 传给 `_dump_bin`；**新票**用完整新日历重写。
- `_data_to_bin`（`:245-269`）在 `UPDATE_MODE` 且文件已存在时走 `bin_path.open("ab")` **纯追加，不写头、不校验位置**（`date_index` 在这条分支里算了但没用）。
- `dump()`（`:532-539`）最后落盘新日历和新 `all.txt`。

**问题（推断，有官方 issue 佐证）**：全局日历按"所有票的并集"增长，而单票追加的长度 = **它自己有数据的那几天**。若该票在更新窗内停牌，追加块比日历增量短，此后 `start_index + offset` 的映射整体**错位一天**，而且没有任何东西能发现——因为 bin 里没有日期。官方 issue [microsoft/qlib#1818](https://github.com/microsoft/qlib/issues/1818)（`bug` 标签，2024-06-27，**P2**，本轮读过原文）复现的正是这条：*"When align index, calendar_list does not contain dates such as 2024-05-06, but SH600306 data is empty in these days."* 维护者 `@SunsetWolf` 的回应是**绕开**（改用 yahoo collector 的 `update_data_to_bin`），未修 `dump_bin.py`，issue 已关闭。

> 这条对我们是**决定性的**：我们的 `quotes_daily` 每行自带 `trade_date`，停牌天然是"这行不存在"，不可能错位。放弃行内日期能换来 4 字节/值，代价是把"对齐"从**数据不变量**降级成**脚本纪律**。

### 2.6 磁盘占用：官方包实测 vs 我们的 SQLite

| 口径 | 数值 | 来源 |
|---|---|---|
| 官方 `qlib_data_cn_1d_latest.zip`（v2） | 下载 **196,549,189 B = 196.5 MB** | `Content-Length`（HEAD `github.com/SunsetWolf/qlib_dataset/releases/download/v2/qlib_data_cn_1d_latest.zip`；URL 由 `qlib/tests/data.py:19,41,84-92` 拼出） |
| 同包解压后 | **284,507,633 B = 271.3 MB**，31,008 条目 | P1-实测，Range 读 zip 中央目录逐条求和 |
| ├ `.day.bin` | 27,125 个 / **271.1 MB** | 同上 |
| ├ 每字段 | 3,875 文件 / 40,604,372 B / **38.7 MB**（7 字段各一份） | 同上；字段 = open/high/low/close/volume/change/factor（另有 1 个孤儿 `adjclose.day.bin`） |
| └ `.txt` | 5 个 / 0.3 MB | 同上 |
| **本机 `market.db`** | **5,740.2 MB** | **P1-主**（dbstat 实测 2026-08-25） |
| ├ `quotes_daily` 数据页 | **2,723.0 MB** / 16,966,403 行 / 5,547 只 / 1990-12-19~2026-08-25 ⇒ **160.5 B/行** | 同上 |
| └ 溯源审计（receipts + attempts + 其索引 + `idx_quotes_receipt`） | **2,569.0 MB = 全库 44.8%** | 同上（1,049.0+724.7+450.9+127.3+71.9+62.3+49.2+33.7，本轮加总核对） |

**等价换算（推断，纯算术）**：把这 16,966,403 行改写成 qlib `.bin`：

| 字段数 | `.bin` 体积 | vs `quotes_daily` 2,723.0 MB |
|---|---|---|
| 6（OHLCV+turnover） | 407.2 MB | **6.7×** |
| 7（+factor） | 475.1 MB（含 5% 停牌补 NaN 则 498.8 MB） | **5.7×** |
| 8（+amount+outstanding_share） | 542.9 MB | **5.0×** |

单值成本：qlib **4 B**，我们 160.5 B/行 ÷ 约 10 个数值列 ≈ **16 B/值**。差的 4 倍来自 SQLite 行头 + varint + B 树页 + 页内空洞；其余差距来自**我们多存了 `source / fetched_at / receipt_id` 三列逐行溯源**——那不是浪费，那是 `market` 上下文的立身之本。

> **关键判断**：即使 `quotes_daily` 从 2,723 MB 压到 475 MB，`market.db` 也只从 5,740 MB 降到约 3,492 MB，**因为真正的肥肉是 2,569 MB 的溯源审计（44.8%），而 `.bin` 根本装不下它**。抄 `.bin` 换来的是"省 39% 空间 + 放弃逐行溯源 + 读取模式反向 + float32 掉精度 + 停牌错位无校验"。不划算。

---

## 3. 表达式引擎

### 3.1 算子集合（本轮精确计数）

`OpsList` 有 **49** 项，`+ [TResample]` = **50**；`register_all_ops` 再注册 `P`、`PRef` ⇒ 运行时共 **52 个可调用算子名**（`microsoft/qlib/qlib/data/ops.py:1566-1616,1667,1670-1681`；`ops.py` 内共定义 53 个 class）。分族：

| 族 | 算子 | 位置 / 备注 |
|---|---|---|
| 元素级一元（6 + 2 基类） | `Abs Sign Log Not Mask ChangeInstrument` | `ops.py:122-229`；`Mask(feat, inst)`（`:185`）与 `ChangeInstrument(inst, feat)`（`:64`）**换标的取数**，用于算 beta vs 指数 |
| 二元（15） | `Power Add Sub Mul Div Greater Less Gt Ge Lt Le Eq Ne And Or` | `ops.py:338-637`，全部 `NpPairOperator`，走 `np.<func>` |
| 三元（1） | `If(cond, a, b)` | `ops.py:639-711`，`np.where` |
| 时序滚动（22） | `Ref Mean Sum Std Var Skew Kurt Max Min IdxMax IdxMin Quantile Med Mad Rank Count Delta Slope Rsquare Resi WMA EMA` | 全部继承 `Rolling`（`ops.py:713-779`） |
| 双序列滚动（2） | `Corr Cov` | `ops.py:1467-1527`；`Corr` 在任一侧滚动 std ≈ 0 时把结果置 NaN（`:1490-1499`） |
| 重采样（1） | `TResample` | `ops.py:1528` |
| PIT（2） | `P PRef` | `qlib/data/pit.py:24,63` |
| 叶子（2） | `Feature`（`$x`）、`PFeature`（`$$x`） | `qlib/data/base.py:223,243` |

四个必须记住的语义细节：

1. **`Rank` 是时序 rank，不是截面 rank**。`Rank(feature, N)` = 当前值在过去 N 根里的百分位（`ops.py:1133-1169`，`rolling.rank(pct=True)`，无 pandas 1.4 时退化为 `scipy.percentileofscore`）。**整个表达式引擎没有任何截面算子**——截面标准化只能放到 processor 层（`CSRankNorm` / `CSZScoreNorm`，见 §4.3）。这是它相对 WorldQuant Alpha101 风格 DSL 的**根本表达力缺口**，也是"表达式按票并行"这个架构选择的必然代价：截面需要同时看到所有票，而每个 worker 只有一只。
2. **所有滚动都是 `min_periods=1`**（`ops.py:751`）。`Mean($close,60)` 第 1 根就出值（1 个样本的均值）。**没有 NaN 预热期**，早期值统计上不可靠但不会缺失——这与通达信一致，但会让 `Std/Corr/Slope` 的前几十根变成噪声。
3. `N == 0` ⇒ `expanding()`；`0 < N < 1` 的 float ⇒ `ewm(alpha=N)`（`ops.py:748-752`）。同一个参数位三种语义。
4. **`Ref($close, -N)` 是合法的未来引用**，`get_extended_window_size` 会返回相应的右扩（`ops.py:815-822`）。**引擎不阻止前视**——防前视全靠标签约定（§4.2）和人的纪律。

`Slope/Rsquare/Resi` 不走 pandas，走 **Cython 扩展** `qlib/data/_libs/rolling.pyx:197-207` + `expanding.pyx`（`pyproject.toml:2` 的 build-requires 含 `cython`）。**装 qlib 需要编译工具链。**

### 3.2 表达式怎么解析成算子树 —— 正则改写 + Python `eval`

`qlib/utils/__init__.py:277-302` 的 `parse_field` 做三次 `re.sub`（`\w` 额外放行中文标点 `、：（）`）：

```
$$([\w…]+)      ->  PFeature("\1")     # $$ 必须先于 $
$([\w…]+)       ->  Feature("\1")
(\w+\s*)\(      ->  Operators.\1(
```

然后 `ExpressionProvider.get_expression_instance` 直接 **`eval(parse_field(field))`**（`qlib/data/data.py:392-407`，eval 在 `:397`），结果以原字符串为键缓存进 `self.expression_instance_cache`。

即 `"Mean($close, 5)"` → `'Operators.Mean(Feature("close"), 5)'` → `eval` → `Mean` 实例。**这不是解析器，是字符串改写 + Python 求值。** 后果：

- 表达式语言 = Python 表达式语言。运算符重载全在 `Expression.__add__/__gt__/__truediv__/...`（`qlib/data/base.py:32-137`），所以 `($close-$open)/$open` 天然可用，运算符优先级、括号、科学计数法全部免费继承。**这是它最省事的地方。**
- 代价：**任意用户输入的公式字符串 = 任意 Python 代码执行入口**。第三条正则会把 `foo(` 改写成 `Operators.foo(`，对裸函数调用形成了偶然的白名单效果，但属性访问、下标、`lambda`、生成器表达式、字符串字面量拼接都不经改写直达 `eval`。Qlib 的定位是"研究者在自己机器上写自己的公式"，这个取舍对它成立；对**允许用户在网页编辑器里写公式**的工作台不成立。

### 3.3 缓存：三层，两层默认关

| 层 | 键 | 失效策略 | 位置 |
|---|---|---|---|
| `MemCache H`（进程内） | 三个独立 LRU：`"c"` 日历 / `"i"` 标的 / `"f"` 特征 | 纯 LRU；**上限 `mem_cache_size_limit=500` 条，`limit_type="length"`（按条数不按字节）**；无 TTL、无失效（`mem_cache_expire=3600` 只服务 `DatasetURICache` 与 client 的 `D.calendar`） | `qlib/data/cache.py:44-179`；`qlib/config.py:190-194` |
| 特征表达式键 | `(str(expr), instrument, start_index, end_index, *args)` | 同上。**键含区间** ⇒ 同一表达式换窗口不复用 | `qlib/data/base.py:187-202` |
| `DiskExpressionCache` | `hash_args(instrument, field, freq)` —— **不含时间范围** | 按整条日历生成一次，读时 `read_bin(cache_path, start_index, end_index)` 切片；`update(sid, uri, freq)` 依 `.meta` 的 `last_update` 追加。`$close` 这类裸 Feature **不建缓存**（`cache.py:543-565`） | `cache.py:490-645`；`_uri` 在 `:502-505` |
| `DiskDatasetCache` | `hash_args(*normalize_uri_args(instruments, fields, freq), disk_cache, inst_processors)` | 三件套 `<hash>`(HDF5) + `.index` + `.meta`，`check_cache_exists` 三个都在才算命中（`cache.py:306-312`）；`.index` 是「timestamp → [start, end) 行号」的 HDF5 表（`:857-880`，**start 闭 end 开**）；`update()` 比对 `last_update` 与最新日历做增量追加 | `cache.py:647-1062`；`_uri` 在 `:656-657` |

**两条硬约束**：

1. `DiskExpressionCache.__init__` / `DiskDatasetCache.__init__` 第一句都是 `self.r = get_redis_connection()`（`cache.py:493,653`）——**读写锁靠 Redis**。`QlibConfig.set` 在 `can_use_cache()` 失败时**静默把两个 cache 置为 None** 并只打一条 warning（`qlib/config.py:485-500`）。
2. **默认就是 None**：`_default_config["expression_cache"]=None`（`config.py:176`）、`MODE_CONF["client"]["dataset_cache"]=None`（`config.py:290`，注释 `Disable cache by default. Avoid introduce advanced features for beginners`）。只有 `server` 模式才开 `DISK_EXPRESSION_CACHE/DISK_DATASET_CACHE`（`config.py:279-280`）。

⇒ **一般用户跑 Qlib，磁盘缓存是关的，唯一生效的是 500 条上限的进程内 LRU。**「Qlib 快」这件事主要来自 `.bin` + 多进程，不来自缓存。

### 3.4 `D.features()` 的调用契约

```python
D.features(instruments, fields, start_time=None, end_time=None,
           freq="day", disk_cache=None, inst_processors=[]) -> pd.DataFrame
```
（`qlib/data/data.py:1162-1190`）

- `instruments`：`str`（市场名，经 `D.instruments()`）/ `list` / `dict`（含 `market` 键 ⇒ 股票池配置，否则 ⇒ `{code: [(start,end),...]}`）——`DatasetProvider.get_instruments_d`，`data.py:511-529`。
- `fields`：**表达式字符串列表**；输出列名 = `str(表达式实例)`（`get_column_names`，`:531-540`），所以 `Mean($close,5)` 的列名就是 `"Mean($close,5)"`，需要人可读名要靠 `QlibDataLoader` 事后 `df.columns = names`（`qlib/data/dataset/loader.py:223`）。
- `disk_cache`：`0` skip / `1` use / `2` replace，默认 `C.default_disk_cache = 1`（`config.py:189`）；cache 为 None 时走 `except TypeError` 分支退回裸 provider（`data.py:1185-1190`）。
- 返回：`MultiIndex(instrument, datetime)` 的 DataFrame，**float32**（`data.py:872`）。`QlibDataLoader` 默认 `swap_level=True` 换成 `(datetime, instrument)`（`loader.py:224-225`）。
- `inst_processors`：每票各跑一遍的处理器（`inst_calculator`，`data.py:600-658`）。注意 **`DiskDatasetCache` 不支持 `inst_processors`**，会直接抛 `ValueError` 让你 `disk_cache=0`（`cache.py:761-765`）。

### 3.5 与我们「pandas 面板 + 通达信函数」的正面对比

我们的形状（`src/market/infrastructure/store_panel.py:71-156`）：一次 SQL → 扁平表 → 每字段 `pivot(index=trade_date, columns=code)` → `_consolidate` 压成**单块连续内存**（同文件 `:22-40`，注释里有实测：60×5509 面板 `shift(1)` 从 98.55 ms 降到 0.60 ms，**164×**）。所有通达信函数在这块 (T×N) 面板上一次调用覆盖全市场。

| 维度 | Qlib | 我们 | 谁赢 |
|---|---|---|---|
| **主序** | instrument-major：按票循环、时间向量化 | panel-major：时间 × 票一起向量化 | — |
| **算 Alpha158 的 pandas 调用次数** | 5,500 票 × 158 特征 = **869,000 次** `rolling`（每次序列长约 2,619） | **158 次**（每次 250×5,500 的块） | **我们**（Python 调用开销差 5,500 倍，Qlib 只能靠多进程摊） |
| **单机少核** | 依赖 `kernels=NUM_USABLE_CPU` 的多进程；核少即线性退化 | 单进程即满速，`_consolidate` 后与裸 numpy 同速 | **我们** |
| **峰值内存（增量取数）** | 单票工作集 71.6 KB，worker 用完即释放 | 必须先把整块 (T×N) 读进来 | **Qlib** |
| **峰值内存（158 宽特征矩阵，250×5500）** | **float32 = 869 MB** | 同尺寸 **float64 = 1,738 MB** | **Qlib**（我们必 OOM，见 §9） |
| **"某票全历史"** | 1 seek + 1 read | `idx_quotes_code_date`（424.9 MB，P1-主）索引查找 + 离散行取 | **Qlib** |
| **"全市场某窗口"** | 5,500 次 open/seek | `(trade_date, code)` 聚簇上的**连续区间扫描** | **我们** |
| **预热窗** | `get_extended_window_size()` 自动推导并多读（`data.py:853-854`） | 手动：调用方自己算 `start` 往前留几天 | **Qlib**（这一条值得抄，纯逻辑零成本） |
| **算子表达力** | 52 个，**无截面算子**，但有 `ChangeInstrument/Mask`（跨标的）、`Slope/Rsquare/Resi`（Cython 回归）、`Skew/Kurt/Quantile/Med/Mad/Corr/Cov` | 39 个公开（`src/formula/domain/screen_formula_catalog.py:11-18`）+ `COST/WINNER` 筹码（未进目录）+ `ZTPRICE` 涨停价 + 潜龙域（`src/formula/domain/qianlong.py`） | **平手，缺口互补**。我们缺回归/高阶矩/分位/相关（依赖清单无 scipy / statsmodels / sklearn，**P1-主**）；它缺涨停价、筹码、板块口径这些 A 股短线必需品 |
| **解析** | 正则改写 + `eval()`（`data.py:397`）——任意代码执行面 | tokenizer + AST（`Token/Expr/CallExpr/Statement`，`src/formula/domain/screen_formula_parser.py:8-56`）+ 显式白名单注册表 | **我们**（我们把编辑器暴露给用户，它不） |
| **前视防护** | 无。`Ref($x,-1)` 合法且无告警 | `guard_strategy`：AST 静态查负向 shift + 大宇宙分片截断一致性动态探测，fail-closed（`src/strategy/application/audit.py:163-220,397`；`audit_sampling.py:23-46`） | **我们**（最不该丢的资产） |

**一句话**：Qlib 的引擎为"多核 + 单票流式 + 无人值守"设计；我们的为"单机少核 + 全市场截面 + 用户可编辑公式"设计。**不是优劣关系，是用例关系。**

---

## 4. Alpha158 / Alpha360

### 4.1 Alpha158 的 158 个特征具体是哪几族

生成器是 `Alpha158DL.get_feature_config(config)`（`microsoft/qlib/qlib/contrib/data/loader.py:61-310`），`Alpha158.get_feature_config()` 喂给它的 config 是 `{"kbar": {}, "price": {"windows": [0], "feature": ["OPEN","HIGH","LOW","VWAP"]}, "rolling": {}}`（`qlib/contrib/data/handler.py:140-149`）。注意 **`volume` 族没有被启用**。

| 族 | 数量 | 窗口 | 明细 |
|---|---:|---|---|
| **KBAR** | **9** | 无窗口 | `KMID KLEN KMID2 KUP KUP2 KLOW KLOW2 KSFT KSFT2`（`loader.py:104-126`）。全是当日 OHLC 的无量纲比值：实体/开盘、振幅/开盘、实体/振幅、上影/开盘、上影/振幅、下影/开盘、下影/振幅、`(2C-H-L)/O`、`(2C-H-L)/(H-L)`。分母一律 `+1e-12`。 |
| **PRICE** | **4** | `[0]` | `OPEN0 HIGH0 LOW0 VWAP0` = `$open/$close`、`$high/$close`、`$low/$close`、`$vwap/$close`（`loader.py:127-133`）。**注意没有 `CLOSE0`**——`Alpha158` 的 `feature` 列表里没有 `"CLOSE"`（默认列表有，但被显式覆盖掉了）；`CLOSE0` 恒为 1 无信息。 |
| **VOLUME** | **0** | — | `"volume"` 不在 config 里（`loader.py:134-137` 未触发）。 |
| **ROLLING** | **145** | **`[5, 10, 20, 30, 60]`**（`loader.py:139`，`include=None` / `exclude=[]` ⇒ 全开） | **29 个族 × 5 个窗口**。本轮 `grep -c "if use("` = **29**，逐一为：`ROC MA STD BETA RSQR RESI MAX MIN(内部键 "LOW") QTLU QTLD RANK RSV IMAX IMIN IMXD CORR CORD CNTP CNTN CNTD SUMP SUMN SUMD VMA VSTD WVMA VSUMP VSUMN VSUMD`（`loader.py:150-309`） |

**9 + 4 + 0 + 29×5 = 158。** ✔（本轮脚本核算）

29 个滚动族按语义再分：

- **趋势/位置（9）**：`ROC`=`Ref($close,d)/$close`、`MA`、`STD`、`BETA`=`Slope($close,d)/$close`、`RSQR`=`Rsquare($close,d)`、`RESI`=`Resi($close,d)/$close`、`MAX`=`Max($high,d)/$close`、`MIN`=`Min($low,d)/$close`、`RSV`=`($close-Min($low,d))/(Max($high,d)-Min($low,d)+1e-12)`
- **分位/排名（3）**：`QTLU`(0.8 分位)、`QTLD`(0.2 分位)、`RANK`（**时序**百分位）
- **Aroon 时间距离（3）**：`IMAX`=`IdxMax($high,d)/d`、`IMIN`、`IMXD`=两者之差 /d
- **量价相关（2）**：`CORR`=`Corr($close, Log($volume+1), d)`、`CORD`=`Corr($close/Ref($close,1), Log($volume/Ref($volume,1)+1), d)`
- **涨跌计数（3）**：`CNTP`（涨天占比）、`CNTN`（跌天占比）、`CNTD`（差）
- **RSI 家族（3）**：`SUMP`（总涨幅/总绝对变动）、`SUMN`、`SUMD`
- **量能（6）**：`VMA`、`VSTD`、`WVMA`（成交量加权的涨跌幅波动）、`VSUMP`、`VSUMN`、`VSUMD`

**几乎所有价格类特征都除以 `$close`**——这是刻意的无量纲化，注释反复写 `divided by latest close price to remove unit`（`loader.py:152,157,161,...`）。这一点我们的通达信公式**没有做**：`MA(CLOSE,20)` 直接输出元，跨股票不可比。要把公式结果送进任何截面模型，必须补这一步。

### 4.2 Alpha360 与标签

`Alpha360DL.get_feature_config()`（`loader.py:16-58`）：6 个字段（`close open high low vwap volume`）× 60 个滞后（0..59）= **360**。价格除以 `$close`，成交量除以 `$volume+1e-12`，所以 `CLOSE0 ≡ 1`、`VOLUME0 ≡ 1`（注释 `loader.py:18-24` 自己承认："If further normalization are executed (e.g. centralization), CLOSE0 and VOLUME0 will be 0"）。**Alpha360 = 原始 60 日 OHLCV 序列，零人工特征**，专给序列模型。

**标签：`["Ref($close, -2)/Ref($close, -1) - 1"]`，名字 `LABEL0`**（`handler.py:89-90` Alpha360、`:151-152` Alpha158；vwap 变体在 `:94,156`）。

为什么是 -2/-1 而不是 -1/0？官方文档给了明确理由（**P2**，`microsoft/qlib/docs/component/data.rst:488` 原文）：

> *"In the `Alpha158`, `Qlib` uses the label `Ref($close, -2)/Ref($close, -1) - 1` that means the change from T+1 to T+2, rather than `Ref($close, -1)/$close - 1`, of which the reason is that when getting the T day close price of a china stock, the stock can be bought on T+1 day and sold on T+2 day."*

翻译成我们的语言：**特征用到 T 日收盘 ⇒ 决策发生在 T 日收盘之后 ⇒ 最早只能 T+1 成交 ⇒ 收益必须从 T+1 收盘量到 T+2 收盘。** 这与我们 `entry_timing="next_open"` 是**同一个约束的两种解法**：Qlib 把执行滞后写进**标签**（收益口径为 T+1收 → T+2收），我们把它写进**成交引擎**（信号 T 日、成交 T+1 开盘）。

两者的差别值得记下来（**推断**）：

- Qlib 的口径**丢掉了 T→T+1 的隔夜跳空**。这在 A 股是系统性的：[`2026-08-yule-materials-tail-close-feasibility.md`](./2026-08-yule-materials-tail-close-feasibility.md) 实测隔夜过路费为 **-0.108pp**、且是"今天有多热"的函数（最热十分位 -0.6611%）。Qlib 的标签把这段负漂移整段排除在训练目标之外，模型学到的"收益"和账户实际拿到的不是一回事。
- 好处是它**同时避开了开盘价的可成交性问题**（一字板买不进）——用 T+1 收盘作为买点，比 T+1 开盘更"总能成交"，但也更不真实。
- 我们的口径（次开成交 + 一字板方向掩码，`src/backtest/README.md`）在这一点上比 Qlib **更严格**。**不要为了对齐 Qlib 而改标签。**

### 4.3 预处理：顺序与理由

先分清两处：**类默认**和**YAML 里实际用的**。

**类默认**（`qlib/contrib/data/handler.py:37-45`）：
```python
_DEFAULT_LEARN_PROCESSORS = [{"class": "DropnaLabel"},
   {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}}]
_DEFAULT_INFER_PROCESSORS = [{"class": "ProcessInf"}, {"class": "ZScoreNorm"}, {"class": "Fillna"}]
```
`Alpha360` 两个都用（`:53-54`）；**`Alpha158` 的 `infer_processors` 默认是空列表 `[]`**（`:103`），因为树模型不需要标准化。

**GBDT 之外的模型在 YAML 里覆盖**，典型是 `examples/benchmarks/GRU/workflow_config_gru_Alpha158.yaml:12-32`：

```yaml
infer_processors:   # 作用于特征，训练/推断都跑
  - FilterCol(fields_group=feature, col_list=[20 个手挑特征])
  - RobustZScoreNorm(fields_group=feature, clip_outlier=true)
  - Fillna(fields_group=feature)
learn_processors:   # 只在训练时跑
  - DropnaLabel
  - CSRankNorm(fields_group=label)
```

**顺序的理由**（逐个对源码）：

1. **`FilterCol` 先**：先砍列再算统计量，省内存也避免被无用列的极值影响。
2. **`RobustZScoreNorm` 第二**（`qlib/data/dataset/processor.py:262-297`）：`mean = nanmedian`，`std = nanmedian(|x - median|) * 1.4826`（MAD 的正态一致估计），然后 `clip(-3, 3)`。用中位数/MAD 而非均值/标准差，是因为 Alpha158 里 `WVMA/VSTD/CORR` 这类比值特征有厚尾和 inf；**均值和标准差本身会被极值污染**，标准化后极值依然是极值。它的 `fit()` **只用 `[fit_start_time, fit_end_time]` 的切片**（`:281-288`），注释加了双重感叹号：`# NOTE: correctly set the fit_start_time and fit_end_time is very important !!!` / `fit_end_time **must not** include any information from the test data!!!`。**这是 Qlib 里唯一显式的防前视机制。**
3. **`Fillna` 最后**（`processor.py:179-193`，默认 `fill_value=0`）：必须在标准化**之后**。标准化后 0 = 分布中心；若先填 0 再标准化，那些 0 会把中位数和 MAD 拽偏。
4. **`DropnaLabel` 只在 learn 侧**（`processor.py:105-111`）：它重写了 `is_for_infer() -> False`，注释 `The samples are dropped according to label. So it is not usable for inference`——**推断时没有标签，不能按标签丢样本**，否则会漏预测。框架在 `_run_proc_l(..., check_for_infer=True)` 时遇到它会**直接抛 `TypeError`**（`handler.py:530-535`：`Only processors usable for inference can be used in infer_processors`）——**是硬错误不是静默跳过**。
5. **`CSRankNorm` 作用于 label 且只在 learn 侧**（`processor.py:326-357`）：`groupby("datetime").rank(pct=True)` 再 `-0.5`、`/0.3868`。docstring 解释了 3.46 和 0.5 的来历：rank-pct 是 U(0,1)，均值 0.5、`1/std ≈ 3.46`，所以减 0.5 除以 std 就变成近似标准正态。**它把"预测收益率"换成了"预测当日截面名次"**——这正是 §3.1 说的"截面能力只在 processor 层"。理由：日度收益率的截面分布逐日尺度剧变（大盘暴跌日和横盘日不可比），直接回归会让高波动日主导 loss；排名归一化后每天的 label 分布完全一致。
6. `ProcessInf`（`processor.py:161-176`）把 ±inf 换成该列非 inf 的均值（**按日 groupby**），源码自己吐槽 `# FIXME: Such behavior is very weird`。

**infer / learn 两条流水的接法**由 `DataHandlerLP.process_type` 决定（`qlib/data/dataset/handler.py:425-434,552-612`）：

- `PTYPE_A = "append"`（**Alpha158 默认**，`:445`）：`_learn = infer_processors(_shared) 之后再跑 learn_processors`。
- `PTYPE_I = "independent"`：`_infer` 和 `_learn` 各自从 `_shared` 分叉。MLP 的 YAML 显式设 `process_type: "independent"`。

差别在于 label 归一化会不会被特征标准化影响；`append` 更省内存（`_learn` 直接复用 `_infer` 的结果），`independent` 更干净。

---

## 5. Point-In-Time 财务库

### 5.1 存储格式：`.data` 是修订链表，`.index` 是期别跳转表

目录：`<provider_uri>/financial/<code 小写>/<field>.data` + `<field>.index`（`qlib/data/data.py:782-783`）。字段名必须以 `_q`（季）或 `_a`（年）结尾，否则 `raise ValueError`（`:779-781`）。

记录类型（`qlib/config.py:247-252`）：

```python
"pit_record_type": {"date": "I", "period": "I", "value": "d", "index": "I"}   # uint32/uint32/float64/uint32
"pit_record_nan":  {"date": 0, "period": 0, "value": NaN, "index": 0xFFFFFFFF}
```

- **`.data`**：定长记录数组 `(date, period, value, _next)` = 4+4+8+4 = **20 字节/条**。`date` 是 `YYYYMMDD` 整数（**公告日**），`period` 是报告期整数（`202001` = 2020Q1），`value` 是 **float64**（比行情 bin 的 float32 精一档），`_next` 是**同一 period 下一次修订记录在本文件中的字节偏移**，无后继则 `0xFFFFFFFF`。
- **`.index`**：`[first_year(uint32)] + [uint32 偏移数组]`，每个 period 槽位一个；季频每年 4 槽。偏移 = 该 period 第一条记录在 `.data` 里的字节位置，无数据填 `NA_INDEX`。省空间的手法在 `scripts/dump_pit.py:168-169` 的注释里：`To save disk space, we only store the first_year as its followings periods can be easily infered.`
- 槽位换算：`get_period_offset(first_year, period, quarterly)` = 季频 `(period//100 - first_year)*4 + period%100 - 1`，年频 `period - first_year`（`qlib/utils/__init__.py:101-106`）。

写侧：`DumpPitData._dump_pit`（`scripts/dump_pit.py:150-260`）先按 `first_year` 写 `.index` 头，再用 `NA_INDEX` 填满整段年份槽位，然后按 `date` 升序追加 `.data` 并回填链表。**docstring 里就画了这个格式**（`:156-169`）。

### 5.2 如何避免财报「未来数据」

核心只有两行（`qlib/utils/__init__.py:164-173`）：

```python
while _next != NAN_INDEX:
    fd.seek(_next); date, period, value, new_next = struct.unpack(DATA_DTYPE, fd.read(...))
    if date > cur_date_int: break     # ← 就是这一行
    prev_next = _next; _next = new_next; prev_value = value
```

沿修订链前进，**一旦某条修订的公告日晚于当前观察日就停下，返回上一条的值**。所以在 2019-04-01 查 2018Q4 的 ROE，拿到的是"2019-04-01 当天市场能看到的那一版"，而不是后来更正过的终版。

外层还有两道闸：

- `LocalPITProvider.period_feature` 开头 `assert end_index <= 0  # PIT don't support querying future data`（`data.py:754`），并要求 `cur_time` 必须是 `pd.Timestamp`，否则报错提示"你不能直接查 `$$roewa_q`，必须用 `P()` 包起来"（`:749-752`）。
- `P._load_internal` 在 `end_ws > 0`（算子树需要未来数据）时直接 `raise ValueError("PIT database does not support referring to future period ...")`（`qlib/data/pit.py:33-37`）。

**数据来源与覆盖面（P1 + P2）**：`scripts/data_collector/pit/collector.py` 走 **baostock**，映射 `{"pubDate": "date", "statDate": "period", "roeAvg": "value"}`（`:120`）与 `YOYNI`（`:170`），外加业绩快报/预告的 `performanceExpPubDate` / `profitForcastExpPubDate`（`:98,148`）。**即：官方 PIT 只覆盖 ROE 和净利同比两个指标**。README 首行自带免责：*"the data is collected from baostock and the data might not be perfect. We recommend users to prepare their own data"*（`scripts/data_collector/pit/README.md:3`）。

### 5.3 `P()` 表达式怎么用

`P(expr)` 把 `<period_time, value>` 的二维数据**塌缩**成 `<observe_time, value>` 的一维序列（`qlib/data/pit.py` 模块 docstring 有完整说明）：对请求区间里的**每一个交易日** `cur_time`，用该日可见的修订重算一次 `expr`，取结果的最后一个元素（`:26-48`）。`PRef(expr, period)` 则锁定某个具体报告期（`:63-72`）。

```
P($$roewa_q)     # 最新一期 ROE（按当日可见性）
P(Mean($$roewa_q, 4)) # 最近 4 个季度 ROE 均值
PRef($$roewa_q, 201903) # 锁定 2019Q3
P($$roewa_q) / PRef($$roewa_q, 201903) - 1
```

**代价**：`P` 对区间内**每一天**都重跑一次 `np.fromfile(data_path)`（`data.py:793`）。源码自己在 `:786-791` 承认 `# NOTE: The most significant performance loss is here.`，并说明作者为了保持接口简单而**故意放弃了加速**（被注释掉的 `# For acceleration` 代码块散落在 `:767-777, 813, 822-828`）。同一处还标了 `# NOTE: This class is not multi-threading-safe!!!!`（`:746`）。

### 5.4 判断：这块值不值得抄

**存储格式：不抄。语义：抄，且我们已经抄了。**

1. **格式没有优势**。`.data/.index` 的链表是为"顺序扫日历、每天重读一次全文件"这个（自承低效的）访问模式设计的。在 SQLite 里，等价查询是一条带索引的 SQL：
   `SELECT value FROM pit_facts WHERE code=? AND period=? AND ann_date<=? ORDER BY ann_date DESC LIMIT 1`
   —— O(log n)，天然线程安全，天然可加 `source/payload_sha256/parser_revision` 溯源列，而这些列 `.data` 里放不下。20 B/条的紧凑度对季频财务毫无意义（5,547 只 × 30 年 × 4 季 × 20 字段 ≈ 1,300 万条 × 20 B = 266 MB，SQLite 版大概 2 GB——但我们本来也没有 20 个 PIT 字段）。
2. **语义我们已经有，而且更严**。`src/research/README.md` 明确：PIT 事实写为 `PointInTimeObservation`，可见性**只认 `available_at`**，`tests/research/test_temporal_lookahead.py` 把"财报期已过但未披露""成分已生效但未公告"都钉成不可见；`strict_pit=true` 还要求 `publication_status` / `availability_status` 都为 `observed`，抓取时间不能冒充发布时间。Qlib 只有一个 `date`（= baostock `pubDate`），**没有"这条发布时间本身是不是观测到的"这一层**。
3. **唯一值得对照确认的是记录粒度**：`(date=公告日, period=报告期, value, _next=同一 period 的下一次修订)`。Qlib 把**修订链**显式建模——同一个 2018Q4 可以有 3 条记录，分别在业绩快报、正式年报、更正公告时发布。建议动作：拿这个四元组去核对我们 `PointInTimeObservation` 的字段是否齐全（尤其是"同 period 多 revision"能否表达、能否按 `available_at` 排序取最后一条），**这是一次半小时的字段核对，不是一次迁移**。
4. **前置条件不满足，现在抄了也空转**：我们目前**没有任何 PIT 财务源接入**，且 `src/research/README.md` 自述"当前技术回测的 PIT 输入范围仅为行情证据和历史股票池……PIT 财务/事件事实……尚未被技术回测选择、冻结或消费"。在有源之前，讨论存储格式是纯浪费。

---

## 6. 工作流与实验管理

### 6.1 `qrun` + YAML：一条命令的完整链路

入口 `qrun = "qlib.cli.run:run"`（`pyproject.toml:120`）→ `workflow(config_path, experiment_name="workflow", uri_folder="mlruns")`（`qlib/cli/run.py:86-148`）：

1. Jinja2 渲染 YAML（`render_template`，`:60-82`）——配置里可以写模板变量。
2. 支持 `BASE_CONFIG_PATH` 继承：先加载基配置，再用当前文件 `update_config` 覆盖（`:110-133`）。
3. `sys_config` 把 YAML 里 `sys.path` / `sys.rel_path` 加进 `sys.path`（`:136`）——自定义模型/算子不必安装。
4. 若 YAML 没给 `exp_manager`，就把 tracking uri 定成 `file:<cwd>/mlruns`（`:138-143`）。默认 `exp_manager` 是 `MLflowExpManager`（`qlib/config.py:239-246`）。**MLflow 是本地文件后端，不需要 server。**
5. `task_train(config["task"], experiment_name)`（`:147`）。
6. **`recorder.save_objects(config=config)`**（`:148`）——**把整份渲染后的 YAML 作为 artifact 存进这次 run**。

### 6.2 一次实验记录了哪些东西才叫可复现

`task_train` → `R.start(...)` 上下文里跑 `_log_task_info` + `_exe_task`（`qlib/model/trainer.py:108-128`）。清单：

| # | 记录物 | 形式 | 位置 |
|---:|---|---|---|
| 1 | `task` 配置**展平后逐项**存为 params | `R.log_params(**flatten_dict(task_config))` | `trainer.py:37` |
| 2 | `task` 配置**原样对象**（保类型） | `R.save_objects(**{"task": task_config})` | `trainer.py:38` |
| 3 | 主机名 | `R.set_tags(hostname=...)` | `trainer.py:39` |
| 4 | **训练好的模型** | `R.save_objects(**{"params.pkl": model})` | `trainer.py:50` |
| 5 | **dataset 对象**（`dump_all=False`：只存配置不存数据） | `R.save_objects(**{"dataset": dataset})` | `trainer.py:51-53` |
| 6 | **完整命令行** | `log_params(**{"cmd-sys.argv": " ".join(sys.argv)})` | `recorder.py:356` |
| 7 | `_QLIB_` 前缀的环境变量 | `log_params(...)` | `recorder.py:357-359` |
| 8 | **`git diff` / `git status` / `git diff --cached`** 三份文本 | `_log_uncommitted_code()` → `code_diff.txt` / `code_status.txt` / `code_cached.txt` | `recorder.py:362-379` |
| 9 | 整份 YAML | `recorder.save_objects(config=config)` | `cli/run.py:148` |
| 10 | MLflow 自带：run id、start/end time、status、git commit id | MLflow | `recorder.py:335-353` |
| 11 | 各 Record 的产物与指标 | 见 §6.3/6.4 | `record_temp.py` |

**第 8 条是这套设计里最值钱的一行。** 注释写得很直白：*"Mlflow only log the commit id of the current repo. But usually, user will have a lot of uncommitted changes. So this tries to automatically to log them all."*（`recorder.py:363-366`）——**光有 commit id 不叫可复现，因为研究时工作区永远是脏的。** 「commit id + 未提交 diff + 完整配置 + 命令行 + 环境变量 + 模型 + 预测 + 指标」这一整套，才是"可复现"的最小集合。

### 6.3 `SigAnaRecord` 输出哪些指标

`SigAnaRecord._generate`（`qlib/workflow/record_temp.py:310-349`）：

```python
ic, ric = calc_ic(pred.iloc[:, 0], label.iloc[:, label_col])
metrics = {"IC": ic.mean(), "ICIR": ic.mean()/ic.std(),
    "Rank IC": ric.mean(), "Rank ICIR": ric.mean()/ric.std()}
```

- `calc_ic`（`qlib/contrib/eva/alpha.py:160-183`）：**按 `datetime` 分组**逐日算 pred 与 label 的 Pearson（IC）和 Spearman（Rank IC），返回两条**逐日时间序列**。
- 所以 `IC` = 日度 IC 的均值，`ICIR` = 均值 / 标准差（**不年化**，注意这与很多文献里的 `ICIR = mean/std * sqrt(252)` 不同）。
- 产物：`ic.pkl`、`ric.pkl`（`:351-356`）。
- 可选 `ana_long_short=True` 追加 4 个多空指标，**这几个才乘 `ann_scaler`**（默认 252）：`Long-Short Ann Return`、`Long-Short Ann Sharpe`（`* ann_scaler**0.5`）、`Long-Avg Ann Return`、`Long-Avg Ann Sharpe`（`:331-341`）。
- 兄弟类 `HFSignalRecord`（`:248-292`）额外给 `Long precision` / `Short precision`。

依赖关系由 `depend_cls = SignalRecord` + `ACRecordTemp.generate` 的 `self.check()` 强制（`:212-246`）：**依赖产物不在就跳过并 warning，不会假装算出来。** `SignalRecord` 本身只产 `pred.pkl` + `label.pkl`（`:190-210`）。

### 6.4 `PortAnaRecord` 的组合回测口径

`PortAnaRecord`（`record_temp.py:358-556`）。默认 config（`:400-424`，与 `examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml:8-28` 一致）：

```yaml
strategy: TopkDropoutStrategy(signal=<PRED>, topk=50, n_drop=5)
executor: SimulatorExecutor(time_per_step="day", generate_portfolio_metrics=True)
backtest:
  account: 100000000     # 1 亿
  benchmark: SH000300
  exchange_kwargs:
    limit_threshold: 0.095        # ±9.5%
    deal_price: close
    open_cost: 0.0005   # 买入 5 bp
    close_cost: 0.0015       # 卖出 15 bp（含印花税）
    min_cost: 5         # 单笔最低 5 元
```

**双成本口径**（`:507-513`）——这是最值得抄的一段：

```python
analysis["excess_return_without_cost"] = risk_analysis(report["return"] - report["bench"], freq=...)
analysis["excess_return_with_cost"]    = risk_analysis(report["return"] - report["bench"] - report["cost"], freq=...)
```

并且还会把 **benchmark 自己的** `risk_analysis` 也打出来（`:525`）。⇒ **一次回测同时披露三条曲线：基准、不计成本超额、计成本超额。** 谁在赚 beta、成本吃掉多少 alpha，一眼可见。

`risk_analysis`（`qlib/contrib/evaluate.py:26-93`）返回 5 个数：`mean / std / annualized_return / information_ratio / max_drawdown`。两个必须记住的口径细节：

1. **默认 `mode="sum"`，收益是算术累加不是复利**。docstring 明说：*"Qlib tries to cumulate returns by summation instead of production to avoid the cumulated curve being skewed exponentially."*（`:31-32`）。于是 `annualized_return = mean * N`，`max_drawdown = (r.cumsum() - r.cumsum().cummax()).min()`——**回撤是绝对收益点数的回撤，不是净值百分比回撤**。
2. **日频年化因子是 `238` 不是 252**（`_freq_scaler[Freq.NORM_FREQ_DAY] = 238`，`:52`）——A 股实际年交易日。但 `SigAnaRecord` 的 `ann_scaler` 默认却是 **252**（`record_temp.py:305`），两处**不一致**。引用它的数字时要注意。

换手口径（`qlib/backtest/account.py`）：每笔成交把 `trade_val` 累加进 `accum_info.add_turnover(trade_val)`（`:185-186`，**买卖两边都算**），日度 `turnover_rate = now_turnover / last_account_value`（`:287`）。所以 topk=50 / n_drop=5 的日换手率 ≈ `2 × 5/50 = 20%`（买 5 卖 5，各按成交额计）。

产物落盘（`:492-497`）：`report_normal_<freq>.pkl`、`positions_normal_<freq>.pkl`（**逐日持仓明细**）、`indicators_normal_<freq>.pkl`（`pa`/`pos`/`ffr` 交易质量指标）、`port_analysis_<freq>.pkl`、`indicator_analysis_<freq>.pkl`，全部同时 `log_metrics` 进 MLflow。

---

## 7. 回测与嵌套执行

### 7.1 `TopkDropoutStrategy` 的 k / n_drop 语义

`qlib/contrib/strategy/signal_strategy.py:75-297`。参数（`:81-137`）：`topk`（持仓只数）、`n_drop`（每日最多换掉几只）、`method_sell`（`bottom`/`random`）、`method_buy`（`top`/`random`）、`hold_thresh=1`（最少持有 bar 数）、`only_tradable=False`、`forbid_all_trade_at_limit=True`。父类 `BaseSignalStrategy` 还有 `risk_degree=0.95`（`:32`，仓位上限 95%）。

核心算法（`:197-231`），**关键在 `comb` 那三行**：

```python
last  = pred_score.reindex(current_stock_list).sort_values(ascending=False).index   # 现有持仓按分排序
today = get_first_n(pred_score[~pred_score.index.isin(last)].sort_values(ascending=False).index,
       n_drop + topk - len(last))      # 候选买入
comb  = pred_score.reindex(last.union(pd.Index(today))).sort_values(ascending=False).index
sell  = last[last.isin(get_last_n(comb, n_drop))]     # 只卖"合并排序后掉到末 n_drop"的持仓
buy   = today[: len(sell) + topk - len(last)]    # 卖几只买几只
```

源码注释点破了设计意图：`# combine(new stocks + last stocks), we will drop stocks from this list # In case of dropping higher score stock and buying lower score stock.`（`:214-215`）

**这是整段代码里最聪明的一处**：如果直接"卖掉持仓里分数最低的 n_drop 只、买入候选里分数最高的 n_drop 只"，就可能出现"卖掉的那只分数比买进来的还高"（当候选池整体弱于持仓时）。**把持仓和候选放进同一个排序里再取末 n_drop，就自动消除了这种高抛低吸**——某天没有比持仓更好的票时，`sell` 会自然为空，当天不换手。

其余执行细节：

- 卖单是**清仓式**（`sell_amount = current_temp.get_stock_amount(code)`，`:246`），不做部分减仓。
- 买单等权：`value = cash * risk_degree / len(buy)`（`:266`），逐只 `buy_amount = value / buy_price` 后 `round_amount_by_trade_unit`（`:284-286`）。
- 卖单在策略里就**当场撮合**（`self.trade_exchange.deal_order(sell_order, position=current_temp)`，`:258-262`）以便回收现金给买单用；买单只生成不撮合，交给 executor。
- `hold_thresh` 用 `current_temp.get_stock_count(code, bar=time_per_step)`（`:242-244`；`qlib/backtest/position.py:432-437`）。

### 7.2 A 股约束在哪实现

**全部在 `qlib/backtest/exchange.py`，且默认值来自 region 配置。**

`qlib/config.py:316-332`：
```python
_default_region_config = {
    REG_CN: {"trade_unit": 100, "limit_threshold": 0.095, "deal_price": "close"},
    REG_US: {"trade_unit": 1,   "limit_threshold": None,  "deal_price": "close"},
    REG_TW: {"trade_unit": 1000,"limit_threshold": 0.1,   "deal_price": "close"},
}
```

| A 股约束 | 实现 | 位置 |
|---|---|---|
| **涨跌停** | `_update_limit`：`limit_buy = $change >= limit_threshold \| suspended`；`limit_sell = $change <= -limit_threshold \| suspended` | `exchange.py:273-292` |
| 阈值默认 | `limit_threshold is None` 时取 `C.limit_threshold` = **0.095**（CN） | `exchange.py:139-141`；`config.py:318` |
| 停牌 | `$close` 为 NaN 即视为停牌（`check_stock_suspended`）；不在标的表里也算停牌 | `exchange.py:378-402` |
| 可交易判定 | `is_stock_tradable = not (suspended or limited)`；`direction=None` 时买卖任一受限即不可交易 | `exchange.py:404-415` |
| 涨停时能否卖 | 由策略的 `forbid_all_trade_at_limit`（**默认 True**）决定。`True` = 涨停不卖、跌停不买，源码自承 `not consistent with reality`，TODO 里写着将来要翻转默认值 | `signal_strategy.py:76-80,117-127,232-239` |
| **最小交易单位 100 股** | `trade_unit = kwargs.pop("trade_unit", C.trade_unit)`；`round_amount_by_trade_unit` = `(amount*factor + 0.1) // trade_unit * trade_unit / factor` | `exchange.py:135,761-784`；`config.py:318` |
| 复权与手数的冲突 | 若 `factor.day.bin` 缺失或含 NaN ⇒ `trade_w_adj_price=True`，**手数取整整个失效**并 warning | `exchange.py:218-231` |
| **`deal_price`** | 默认 `C.deal_price = "close"`（CN/US/TW 都是 close）；可给字符串或 `(buy_price, sell_price)` 二元组；自动补 `$` 前缀 | `exchange.py:139-146,156-164`；`config.py:318` |
| 成本 | `trade_cost = max(trade_val * cost_ratio, min_cost)`，`cost_ratio = open/close_cost + impact_cost*(trade_val/total_trade_val)**2` | `exchange.py:889-895,919-920,948` |
| 成交量上限 | 可选 `volume_threshold`，支持 `("cum"\|"current", 表达式)`，如 `("cum", "0.2*DayCumsum($volume,'9:45','14:45')")` | `exchange.py:78-106,786+` |
| **T+1** | **没有专门实现。** 全仓 grep 无 T+1 相关代码 | — |

**T+1 是怎么"混过去"的**（**推断**，基于代码结构）：日频回测里一根 bar = 一天，`hold_thresh=1` 要求 `get_stock_count(code, bar="day") >= 1`，即**今天买的票 count=0，卖不掉**——于是在日频下**行为上等价于 T+1**。但这是 bar 粒度带来的副作用，不是显式约束：一旦上 `NestedExecutor` 做日内分钟级执行（§7.4），内层没有任何东西阻止当日买入当日卖出。**Qlib 的 A 股 T+1 只在日频下成立。**

### 7.3 与我们「信号级逐笔 + MFE/MAE」的口径差

我们有三条口径（`src/backtest/README.md`）：
- `compute_metrics`（**逐笔**、无资金假设）：胜率、盈亏比、期望、profit factor、**`avg_mfe` / `avg_mae`**（`src/backtest/application/metrics.py:36-76`）。
- `compute_trade_performance`（**诊断复利**）：明确声明 `assumption.model = trade_sequence_compounding`，"每笔占满名义资金""**不是**真实多仓组合""禁止把该曲线冒充账户净值"。
- `analyze_portfolio`（**真槽位账本**）：`max_positions` 个固定容量槽位、`slot_capital = initial_capital / max_positions`、`lot_size=100` 整手、退出日次日才释放槽位（`src/backtest/application/research_portfolio.py:70,273-366`）。

对齐后的差异清单：

| 维度 | Qlib（组合层） | 我们（逐笔层） | 备注 |
|---|---|---|---|
| 样本单位 | **交易日**（日度收益序列） | **信号/成交**（每笔一行） | 决定了能不能算超额、回撤、IR |
| 基准对齐 | `report["return"] - report["bench"]`，逐日对齐 CSI300 | **无**。逐笔只有 `benchmark_return_pct` 单笔对照，没有基准时间序列 | **这是我们最大的缺口** |
| 容量约束 | topk=50 硬上限 + `risk_degree=0.95` 现金约束 | 逐笔层**无**（180 只信号全算）；`analyze_portfolio` 才有 | 逐笔口径系统性高估 |
| 换仓语义 | **合并排序取末 n_drop**（§7.1），与信号到达顺序无关 | `analyze_portfolio` 是**先到先得占槽位**（`research_portfolio.py:310-314` `free_slots[0]`） | 见下 |
| 出场诊断 | 无 MFE/MAE。只有 `indicator_analysis` 的 `pa/pos/ffr`（成交质量，不是持仓质量） | **`avg_mfe` / `avg_mae`**，`ops/application/jobs/compare.py:54-56` 还派生出「回吐 = avg_mfe − avg_net_return」 | **我们比它强的地方** |
| 成本 | `max(val*ratio, min_cost=5元)`，买 5bp / 卖 15bp | 佣金 3bp + 印花税 10bp + 滑点 5bp，一趟约 **0.26%**；**无最低 5 元** | 小额单笔我们低估成本 |
| 涨跌停 | `$change >= 0.095` 一刀切 | 按方向区分：**一字涨停买不进但卖得掉**，只有一字跌停才顺延（`src/backtest/README.md`） | **我们更细** |

**为什么组合层口径才是主流**——三条理由，其中第三条是我们自己的实测：

1. **只有日度序列能算超额、回撤和 IR。** 逐笔序列没有共同时间轴：两笔重叠持仓的收益不能相加，也不能和当天的 CSI300 对齐。`risk_analysis` 的入参必须是 `pd.Series` 日度收益（`evaluate.py:26`）。逐笔层永远回答不了"这个策略跑赢沪深300了吗"。
2. **逐笔口径测的是"信号的条件期望"，组合口径测的是"一个有资金约束的账户"。** 二者之间隔着容量（同一天 180 只信号买不下）、错过（槽位满就不建仓）、相关性（同题材同时爆掉）、再投资顺序、以及成本对小仓位的放大。逐笔口径把这些全部假设为零。
3. **我们自己有实测证据说明这个差有多大**：[`2026-08-dragon-survivorship-and-portfolio-fragility.md`](./2026-08-dragon-survivorship-and-portfolio-fragility.md) 记录——**信号数差 3.4%、逐笔均净只差 4.5%，组合全期收益却差 187%（34.09% vs 97.80%）**，结论是"月化 2.222% 须降级为量级参考"。

**但 MFE/MAE 不该丢。** 它回答的是组合口径回答不了的问题："浮盈拿不住还是选股不行"。Qlib 之所以不需要它，是因为 `TopkDropoutStrategy` 把出场固化成了"掉出合并排序末 n_drop 就换"——**出场规则不是自由变量，自然不用诊断**。我们的战法出场规则是自由变量（止损/止盈/持有期/次日冲高），所以必须留着 MFE/MAE。

**最该抄的一条**：把 `analyze_portfolio` 的"先到先得占槽位"换成 TopkDropout 的"合并排序取末 n_drop"。我们已经实测出组合口径对信号扰动的 187% 敏感性——**而先到先得正是这种敏感性的主要来源**（同一天多个信号谁先进槽位取决于排序/到达顺序，与信号强度无关）。合并排序换仓天然消除它。

### 7.4 `NestedExecutor` 日频 → 分钟频嵌套的意义

`qlib/backtest/executor.py:310-...`。结构是「外层策略产出日频决策 → `NestedExecutor.execute` 在内部把这一天拆成分钟 bar → 内层策略（如 TWAP）把日频订单拆成分钟单 → 内层 executor 逐分钟撮合」。关键参数：`inner_executor`、`inner_strategy`、`skip_empty_decision`、`align_range_limit`。

三层意义（**推断 + 源码**）：

1. **把"信号 alpha"和"执行 alpha"分开度量。** 外层回答"选对票没有"，内层回答"这批单子按什么节奏下才不冲击自己"。`indicator_analysis` 的 `pa`（price advantage）、`ffr`（fulfill rate）就是内层的评分（`record_temp.py:531-546`）。
2. **让"日频信号在真实市场能不能执行"变成可测的**。50 只票 × 1 亿资金按收盘价一次性成交是虚构的；拆成分钟单 + `volume_threshold` 限制参与率后，容量瓶颈才会显形。
3. 它是 Qlib RL 执行优化（`qlib/rl`）的宿主环境——内层策略可以换成 RL agent。

**对我们的意义：接近零。** 我们**分钟线不落库**（`GET /api/market/minute/{code}` 明确不写 `market.db`，live 只有进程内 3–5 秒 TTL 缓存，**P1-主**）⇒ **没有内层可嵌套的数据**。这条在我们补齐分钟历史之前不可能落地，也不该为它补分钟历史（我们的战法容量是几只票、几万元，不存在冲击成本问题）。

---

## 8. RL / online serving / rolling

### 8.1 三个模块各是什么

| 模块 | 规模 | 干什么 |
|---|---|---|
| `qlib/rl/` | **38 个 .py**，示例只有 1 个 `examples/rl/simple_example.ipynb` | 订单执行的强化学习（拆单节奏），宿主是 §7.4 的 `NestedExecutor` 内层 |
| `qlib/workflow/online/` | 5 个文件 / 1,075 行（`manager.py` 382、`update.py` 298、`strategy.py` 208、`utils.py` 187） | 在线模型池管理。`OnlineManager` 的 docstring（`manager.py:5-60`）画了四象限：`Online+Trainer` / `Online+DelayTrainer` / `Simulation+Trainer` / `Simulation+DelayTrainer`，核心循环是 `for day in online_trading_days: models = trainer.train(strategy.prepare_tasks()); strategy.prepare_online_models(models); prepare_signals()` |
| `qlib/contrib/rolling/` | `base.py` 264 + `ddgda.py` 388 | 离线滚动重训 |

`Rolling`（`qlib/contrib/rolling/base.py:24-...`）的定位在 docstring 里写得很清楚：*"It only focus **offlinely** turn a specific task to rolling"*，且 *"Rolling is much simpler and is only for testing rolling models offline. It does not want to share the interface with OnlineStrategy."*（`:26-38`）。参数 `horizon=20, step=20`（`:57-58`）——**每 20 个交易日切一段，各段独立训练，把各段的 test 预测拼成一条连续预测序列**。用法是 `python -m qlib.contrib.rolling.base --conf_path <yaml> run`（`:44`）。

`PredUpdater` / `LabelUpdater`（`qlib/workflow/online/update.py:270-298`）负责把新一天的预测/标签**增量补进已有 recorder 的 `pred.pkl` / `label.pkl`**（`_replace_range`），而不是重跑整段。

### 8.2 DDG-DA 是什么

`qlib/contrib/rolling/ddgda.py`。它不是"换个窗口重训"，而是**学一个"样本权重"模型**：

1. 用一个 LGBM（`ddgda.py:24-38`，超参硬编码在文件里）算特征重要性/任务相似度。
2. 构造 `MetaDatasetDS` / `MetaTask`，训练 `MetaModelDS`（`qlib/contrib/meta/data_selection/`）——**元模型的输出是"训练每个 rolling 段时，历史各段样本该给多大权重"**。
3. 再用这组权重去训真正的预测模型（默认 Ridge，`LINEAR_MODEL`，`ddgda.py:40-47`）。

即"学习如何选训练数据以适应概念漂移"。它需要**两轮训练 + 一个可微/可加权的基模型**。

### 8.3 一句话判断

**不值得。三个模块的前置条件我们一个都不满足。**

- **我们没有模型。** 依赖清单里没有 scikit-learn / lightgbm / torch（**P1-主**：有 pandas / numpy / duckdb / polars / akshare / baostock / tdxpy / pyzipper）。滚动重训、在线模型池、元学习样本加权——**全都没有重训对象**。我们的战法是**参数化规则**（`qianlong` / `sanyuan` / 通达信公式），"重训"等价于"重新调参"，而 [`2026-08-incumbent-strategy-full-sample-benchmark.md`](./2026-08-incumbent-strategy-full-sample-benchmark.md) 已经实测过：调参出来的头条数字放到 31 个月全样本会从 +2.97% 塌到 +0.55%。**更频繁地重新调参只会更快地过拟合。**
- **RL 更远**：需要分钟线（我们不落库）+ 需要"拆单"这个问题存在（我们的单笔是几万元，一笔市价单就走完了）。
- **唯一值得借的是 `Rolling` 的评估协议**，不是它的代码：「按固定 step 切成若干 train/test 段、各段独立拟合、把各段 OOS 预测拼成一条连续序列再评估」比单次 train/OOS 更抗过拟合、更接近实盘的"每季度复核一次参数"。而这个协议我们用 `src/backtest/application/research_validation.py::TrainOOSSplit` 手写 20 行循环就有，**不需要引入 qlib 的任何模块**。

---

## 9. 判断：三件抄了立刻见效，三件抄了是负担

前提：SQLite 三库（`market.db` 5,740.2 MB / `ops.db` 13.8 MB / `palace.db` 0.8 MB）、服务器可用内存 **1.1 GB**、DDD 模块化单体、单 worker、单文件 ≤600 行、跨上下文只经包公开 API。以下判断全部在这个边界内。

### 9.1 抄了立刻见效（三件，都是纯协议、零新基建）

#### ① 实验记录的「最小可复现集合」——我们的 `strategy_backtests` 现在是 **0 行**

**现状（P1-主）**：`ops.db` 13.8 MB，`job_runs` 11.36 MB / 706 行（≈16 KB/行），而 **`strategy_backtests` 0 行、`strategy_versions` 0 行 ⇒ 回测结果零持久化**。也就是说，本仓 `docs/research/` 下几十篇回测结论，**没有一条能从库里重新取回它的输入**。

**抄什么**：不是 MLflow，是 `trainer.py:36-53` + `recorder.py:356-379` + `cli/run.py:148` 那张**清单**，落成 `strategy_backtests` 的列：

| 抄自 | 落成 |
|---|---|
| `save_objects(config=config)`（整份 YAML） | `config_json`（`BacktestConfig` 全量序列化，含 `entry_timing` / `execution_adjust` / 成本三件套） |
| `save_objects(task=task_config)` | `strategy_slug` + `strategy_revision`（我们已有 revision 概念） |
| `log_params(cmd-sys.argv)` | `invoked_by`（job / api / cli / assistant）+ 原始参数 |
| **`_log_uncommitted_code()`：`git diff` / `git status` / `git diff --cached`** | **`code_diff_sha256` + diff 正文**（研究期工作区永远是脏的，光有 commit id 不叫可复现——这是 Qlib 注释自己说的） |
| MLflow 的 commit id / start / end / status | `git_commit` / `started_at` / `finished_at` / `status` |
| `set_tags(hostname=...)` | `host` + `market_revision`（我们的行情版本，比 hostname 更有用） |
| `pred.pkl` / `label.pkl` | 我们已有 `frozen_input.json`（`research-frozen-input-v2`，`src/research/README.md`），**接上即可** |

**成本**：`ops.db` 现在 13.8 MB，加这张表不构成压力。**收益**：把"研究文档里的数字"和"能重跑出这个数字的输入"焊死。这是本轮最高优先级的一条。

**注意**：`job_runs` 已经 16 KB/行、706 行占 11.36 MB（**P1-主**）。新表要么只存 hash + 指向 `data/research_runs/<run_id>/` 的路径，要么进 `MANAGED_PRUNE` 的保留策略（`src/ops/README.md` 已有"每任务保留最近 200 条"的先例）。别让它变成第二个 `job_runs`。

#### ② `PortAnaRecord` 的三条曲线披露（基准 / 不计成本超额 / 计成本超额）

**现状**：我们的 `compute_trade_performance` 输出的是一条**自我复利诊断曲线**，README 里三次强调"**不是**真实多仓组合""禁止把该曲线冒充账户净值"。它没有基准对齐的超额序列，所以我们**永远回答不了"这个战法跑赢沪深300了吗"**——而这恰恰是每篇研究文档最后都想说的话。

**抄什么**（`record_temp.py:507-529` + `evaluate.py:26-93`，纯计算，零存储）：

```
excess_no_cost = portfolio_daily_return - benchmark_daily_return
excess_with_cost = portfolio_daily_return - benchmark_daily_return - cost_rate
risk_analysis(x) -> {mean, std, annualized_return, information_ratio, max_drawdown}
# 三份都打印：benchmark 本身、excess_no_cost、excess_with_cost
```

`analyze_portfolio` 已经产出 `equity_curve` 和逐日 `PortfolioDay`（`research_portfolio.py:367-369`），日度收益率现成；基准用现有的全市场等权或指数日线。**这是一个纯 application 层函数，几十行。**

**要注意两个口径坑**（本轮从源码里挖出来的）：Qlib `mode="sum"` 是算术累加、`max_drawdown` 是**点数回撤不是净值回撤**；`risk_analysis` 日频年化用 **238**，而 `SigAnaRecord.ann_scaler` 默认 **252**，**Qlib 自己两处不一致**。我们要抄就统一到一个数并写进 `assumption`。

#### ③ `TopkDropoutStrategy` 的合并排序换仓语义

**现状**：`analyze_portfolio` 是先到先得占槽位（`research_portfolio.py:310-314`：`free_slots[0]`）。**同一天多个信号谁先进槽位，取决于遍历顺序而非信号强度。**

**抄什么**（`signal_strategy.py:197-231`）：

```
comb = sort_desc(scores of (持仓 ∪ 今日候选))
sell = 持仓 ∩ last_n(comb, n_drop)  # 只卖合并排序后掉到末 n_drop 的
buy  = 候选[: len(sell) + topk - len(持仓)]
```

**为什么立刻见效**：我们已经实测出组合口径对信号扰动的 **187% 敏感性**（信号数只差 3.4%、逐笔只差 4.5%）。先到先得正是这种敏感性的主要来源——它让"谁进组合"由一个与 alpha 无关的量决定。合并排序换仓把这个自由度消掉，还顺带带来 Qlib 注释点明的性质：**当天没有比持仓更好的票时 `sell` 自动为空，不换手**（`signal_strategy.py:214-215`）。这既降低敏感性也降低成本。

同批可抄的三个小语义：`risk_degree=0.95`（留 5% 现金缓冲）、`hold_thresh`（最少持有 bar 数，我们的 T+1 可以显式化而不是靠 bar 粒度混过去）、卖单先撮合回收现金再下买单（`:258-266`）。

### 9.2 抄了是负担（三件）

#### ① `.bin` 目录式列存 —— 省错了地方，且读取模式反向

四条独立理由，任何一条都足够否决：

1. **省错了地方（P1-主 + 算术）**：抄了最多把 `quotes_daily` 2,723 MB → 475 MB，`market.db` 5,740 → 约 3,492 MB。**真正的肥肉是 2,569 MB 的溯源审计（44.8%），而 `.bin` 装不下 `source / fetched_at / receipt_id`。** 换句话说抄 `.bin` = 用"放弃逐行溯源"换 39% 空间——而逐行溯源是 `market` 上下文存在的理由。
2. **读取模式反向**：`.bin` 是"少票 × 长历史"最优（1 seek）、"全市场 × 短窗"最差（5,500 次 open）。我们 100% 的选股/回测用例是后者，而 `quotes_daily` 按 `(trade_date, code)` 聚簇**本来就是这个用例的最优布局**（连续区间扫描）。
3. **float32 掉精度**：实测相对误差上界 6e-8，`123,456,789 → 123,456,792`。研究可接受，账本不可接受，而我们的 `market.db` 同时服务两者。
4. **增量更新无校验**：停牌日错位且不可检测（§2.5），官方 issue #1818 至今是"绕开"而非修复。我们的行内 `trade_date` 让这个 bug 类别根本不存在——**这是我们花 160 B/行 买到的东西**。

**部分可借**：`instruments/*.txt` 的 `<CODE>\t<start>\t<end>` **多行 = 多段成分区间**格式（实测 csi300 820 行覆盖 300 只票）。这正好是我们缺的**历史成分表**格式——而 `instruments.delist_date` **填充数 = 0**、`status` 分布 `delisted=1 / normal=5546`（**P1-主**），生存偏差是实锤硬伤。**建议：借这个数据模型，不借这个文件格式**（在 SQLite 里就是 `(code, start_date, end_date, universe)` 一张表）。

#### ② `DiskExpressionCache` / `DiskDatasetCache` —— 要 Redis 和 HDF5，且 Qlib 自己默认关着

1. **要 Redis**：两个类构造函数第一句就是 `get_redis_connection()`（`cache.py:493,653`），读写锁全靠它。我们是单机桌面 + 单 worker，引 Redis = 引一个 broker 进程。
2. **要 HDF5**：`DiskDatasetCache` 的主体是 `pd.HDFStore`（`cache.py:685,917`），`.index` 也是 HDF5 表。这是第二个数据库。
3. **Qlib 自己默认是关的**：`client` 模式两个 cache 都是 `None`（`config.py:176,290`），注释 `Disable cache by default. Avoid introduce advanced features for beginners`。**连作者都不建议一般用户开。**
4. **我们已经有等价物**：`market_hot.db` 1,022.1 MB / 3,748,806 行 / 700 交易日窗口（**P1-主**）就是"热数据只读镜像"这个职能的实现，而且它是 SQLite、可被现有 `MarketStore` 直接读、不需要新进程。

**唯一值得抄的一行**：`get_extended_window_size()` 的**预热窗自动推导**（`ops.py:757-779`、`data.py:853-854`）。我们的 `load_panel` 要调用方自己算往前留几天，算少了指标全 NaN、算多了白读数据。让 Screen Formula 编译器从 AST 反推 `max(window)` 并自动扩 `start`，是纯逻辑、零依赖、直接消灭一类 bug。`src/formula/domain/screen_formula_compiler.py:35-40` 已有 `MAX_WINDOW=1000` 和 `_FULL_HISTORY_FUNCTIONS` 白名单，**信息已经在手上了，只差把它接到取数边界上**。

#### ③ 表达式引擎（`eval` + `Operators` 注册表）—— 安全性倒退 + 性能倒退

1. **安全性倒退**：Qlib 是正则改写后 `eval()`（`data.py:397`）。我们是 tokenizer + AST + 39 函数显式白名单（`screen_formula_parser.py` / `screen_formula_catalog.py:11-18`）。**我们把公式编辑器暴露给用户，Qlib 不。** 换过去等于把一个任意代码执行面装进 Web UI。
2. **性能倒退**：instrument-major 意味着 Alpha158 要 **869,000 次** pandas `rolling` 调用（5,500 × 158），Qlib 靠 `kernels=NUM_USABLE_CPU` 多进程摊；panel-major 是 **158 次**。我们是单机少核 + 1.1 GB 内存，多进程摊不动（每个 worker 一份 pandas + numpy 的常驻内存就吃不消）。
3. **前视防护倒退**：Qlib 引擎不阻止 `Ref($x,-1)`；我们有 `guard_strategy` 的静态 AST 检查 + 大宇宙分片截断一致性动态探测、fail-closed。
4. **要编译**：`Slope/Rsquare/Resi` 是 Cython（`_libs/rolling.pyx`），`pyproject.toml` build-requires 含 `cython`。我们的交付形态是 Windows 桌面 + `setup.ps1`，加一条编译链是实打实的负担。

**该做的是补算子，不是换引擎**：我们缺 `Slope / Rsquare / Resi / Skew / Kurt / Quantile / Corr / Cov`（依赖清单无 scipy / statsmodels，**P1-主**）。这些在面板上用 numpy 滑窗写出来，和现有 `AVEDEV` / `WMA` 的分块向量化是同一套手法（`src/formula/README.md` 记录过：256 列一批 `sliding_window_view`，因为 `(rows-N+1, cols, N)` 物化在 700 天 × 5500 只 × N=60 时是 4.3 GB，而可用内存 1.1 GB）。

### 9.3 三条「前置条件不满足，先别谈」

1. **Alpha158/360 特征矩阵在 1.1 GB 内存里放不下。** 250×5,500×158 = **float32 869 MB / float64 1,738 MB**；Alpha360 是 **1,980 / 3,960 MB**。即使全用 float32，Alpha158 也吃掉 79% 可用内存，再加 pandas 中间态必 OOM。要做必须先有 float32 面板 + 分块流式，那是一次大改。
2. **生存偏差没堵之前，任何截面因子研究都是幸存者研究。** `instruments.delist_date` 填充数 **0**、`status` `delisted=1 / normal=5546`（**P1-主**）；这与 [`2026-08-dragon-survivorship-and-portfolio-fragility.md`](./2026-08-dragon-survivorship-and-portfolio-fragility.md) 的结论一致（"退市存活偏差本地不可测"）。Qlib 的 `instruments/all.txt` 带 `start/end` 区间正是为了这个，**但那是数据问题不是格式问题**。
3. **PIT 财务源为零。** `src/research/README.md` 自述 PIT 财务/事件事实"尚未被技术回测选择、冻结或消费"。Qlib 的 PIT 也只有 ROE + 净利同比两个字段、来自 baostock、README 自带免责。**双方都缺，抄不来。**

### 9.4 一页纸决策表

| # | Qlib 资产 | 判定 | 落点 | 闸门 |
|---:|---|---|---|---|
| 1 | Recorder 最小可复现集合（含 git diff / argv / 全量 config） | **抄** | `ops.db::strategy_backtests`；接 `research-frozen-input-v2` | 进 `MANAGED_PRUNE` 保留策略；不引 MLflow |
| 2 | 三条曲线披露 + `risk_analysis` 五指标 | **抄** | `src/backtest/application/`（`analyze_portfolio` 旁边） | 年化因子统一（238 vs 252 二选一）并写进 `assumption`；累加 vs 复利显式声明 |
| 3 | TopkDropout 合并排序换仓 | **抄** | `research_portfolio.py` 的槽位分配 | 与现行"先到先得"做 A/B，用同一批信号复现 187% 敏感性是否收敛 |
| 4 | `get_extended_window_size()` 预热窗自动推导 | **抄（小）** | Screen Formula 编译器 → `load_panel` 的 `start` | 已有 `MAX_WINDOW` / `_FULL_HISTORY_FUNCTIONS`，只差接线 |
| 5 | `instruments/*.txt` 的多段成分区间**数据模型** | **抄（模型）** | SQLite `(code, start_date, end_date, universe)` | 先解决 `delist_date` 填充为 0 |
| 6 | 缺失算子 `Slope/Rsquare/Resi/Skew/Kurt/Quantile/Corr/Cov` | **自己写** | `src/formula/domain/` | 沿用 256 列分块 `sliding_window_view`；`tests/formula/test_vectorized_parity.py` 同款参考实现比对 |
| 7 | `.bin` 列存 | **不抄** | — | 省错地方 + 读取反向 + float32 + 停牌错位 |
| 8 | Disk 缓存（Redis + HDF5） | **不抄** | — | 已有 `market_hot.db`；Qlib 自己默认关 |
| 9 | `eval` 表达式引擎 | **不抄** | — | 安全 + 性能 + 前视防护三重倒退 |
| 10 | Alpha158/360 全量特征矩阵 | **暂缓** | — | 内存与生存偏差两个前置条件 |
| 11 | PIT `.data/.index` | **不抄格式**，对照字段 | `PointInTimeObservation` 字段核对 | 半小时核对，非迁移 |
| 12 | RL / online / rolling / DDG-DA | **不抄** | — | 无模型、无分钟线、无重训对象 |

---

## 10. 未核验与限制

1. **未安装、未运行 qlib**。所有源码结论来自阅读 commit `79633dd` 的文件；`.bin` 二进制布局与 float32 精度是本轮**复刻代码后实测**，不是运行 qlib 得到。
2. **未下载完整数据包**。271.3 MB 的解压体积由 zip 中央目录逐条求和得到（31,008 条全部解析，与 EOCD 声明数一致），未逐字节解压校验。`calendars/day.txt`、`instruments/all.txt`、`instruments/csi300.txt` 三个成员经 Range + inflate 读出真实行数。
3. **官方 cn_data 包停在 2020-09-25、只有 3,875 只**（实测），且 `qlib/tests/data.py:63` 的 warning 声明数据来自 Yahoo Finance、质量"might not be perfect"。**不要拿这个包的规模去推我们 5,547 只 / 1990–2026 的情况**——本文所有对我们的换算都用主 agent 的 dbstat 实测行数重算过。
4. **`dump_update` 停牌错位是代码推断**，未在本机构造停牌样本复现；由官方 issue #1818（bug 标签、维护者未修）佐证。
5. **T+1 "由 bar 粒度隐式满足"是推断**：全仓 grep 无 T+1 实现，结论由 `hold_thresh` + `get_stock_count(bar="day")` 的组合推出。
6. **未读的 Qlib 子系统**：`qlib/rl` 只看了文件规模与宿主关系、未读实现；`qlib/model/`（各家模型）、`qlib/contrib/model/`、`qlib/data/dataset/storage.py`、高频算子 `qlib/contrib/ops/high_freq.py`、`qlib/workflow/task/` 未逐行读。
7. **主 agent dbstat 数字未由本 agent 复核**，按约定原样引用并标 `P1-主`；`market.db` 的 MB 单位按 `2,723.0 MB ÷ 16,966,403 行 = 160.5 B/行` 反推为 10^6 口径（与主 agent 给的"平均 160 字节/行"一致）。
8. **本轮未做**：写任何数据库、改除本文件外的任何文件（含 `INDEX.md`）、commit、push、安装依赖、注册任何 strategy。

---

## 11. 摘要（≤300 字）

Qlib 的 `.bin` = float32 起始索引 + 连续 float32，每票每字段一文件，为按票多进程服务；cn_data 日线 7 字段实测 271.3 MB。引擎 = 正则 + `eval`，52 算子无截面算子，磁盘缓存要 Redis、默认关。Alpha158 = KBAR 9 + PRICE 4 + 29 族 ×5 窗；标签 −2/−1 因 T 日决策只能 T+1 买 T+2 卖。

抄：可复现实验记录（含 git diff，填 `strategy_backtests` 的 0 行）、三条曲线（基准/无成本/含成本超额）、合并排序换仓。不抄：`.bin`（肥肉是 44.8% 溯源）、Disk 缓存（要 Redis）、`eval` 引擎（安全/性能/防前视三重倒退）。
