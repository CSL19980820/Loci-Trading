# 行情（market）

选股行情门禁按目标交易日检查：未指定日期时，上海时区盘中/盘后使用当天，休市及开盘前使用上一已收盘交易日；显式历史日期保持原值。历史日覆盖未达 90% 仍阻断，并提示补齐该日历史行情，绝不调用今日现价或按盘中降级放行。`resolve_screen_trade_date` 与选股任务共用日期解析，回执 `coverage.trade_date` 标识实际检查日。

## 职责
标的、日 K、同步编排、数据线路适配器、股票池。

股票池默认包含主板、创业板和科创板并剔除 ST；高级筛选可显式加入北交所，并支持行业、代码包含/排除。默认值与可选能力必须分开描述，不能把“默认不选”实现成领域层永久禁止。
创业板分类覆盖六位ASCII数字证券代码的整个 `30` 前缀（含 `302132` 中航成飞），不能只列举 `300` / `301`，否则单选创业板会漏票、单选主板会错收该票。身份依据见[巨潮上市公司要览](https://static.cninfo.com.cn/finalpage/enpage/302132_1.pdf)；该归类不替代证券列表对实际上市标的的约束。

## 边界
只写 market.db；禁止写 palace.db。

热库窗口检查按真实日 K 的日期主键逐日跳跃计数，避免为约 700 个交易日扫描数百万条股票行；日历存在但行情日期缺失时仍判定为浅窗口并重建。

区间选股可使用 `panel_read_window(store, start=预热起点, end=区间末日)` 在当前任务和连接内复用原始面板；每日股票范围、有效根数及 qfq/hfq 基准照旧计算。预读按行分块，数字缓存有 2400 万单元上限，超范围/超预算回退原读取；同连接写入、其他连接提交及事务状态会使复用失效，退出上下文立即释放。

同一上下文也复用行情取证：先将窗口事实按日期、代码、回执和有效性标记编码为每行 14 字节，再按每日范围精确聚合。取证缓存及临时空间单独受 192MB 预算约束；完整回执和 attempts 仍按原口径读取。无上下文或预算不足时回退单遍 SQL 聚合，字段覆盖、来源、缺失及无效 OHLC 判据不变。

增量镜像先在热库写事务内逐块比对行情与日历的完整值，未变时不重写；回执和 attempts 也只写入新增或变化行。它不依赖可能漏记旁路修订的版本号，同日改价格、成交量、换手率或回执仍会同步。`quotes=0` 表示本次没有重写行情；显式 `mirror_to_hot` 继续强制重建。

## 关键入口
`MarketStore` / `sync_quotes`；HTTP：`/api/market/*` `/api/universe/*`（现由 app.legacy.quant_router 挂载）；CLI：`python -m cli.market`

### 权威行情保护（2026-09-11）

- `tdx_daily` 建连后必须真正取到一根日 K 才采用该节点；握手成功但只回数量头的节点会关闭并换台。排序超时保留已成功的节点，候选池见 `tdx_servers.py`，包含生产验证过的公开券商节点。连接起点按计数器轮询，不能用线程 ID 取模（线程 ID 的内存对齐会让所有线程挤在同一台）。
- `sync_quotes(authoritative_only=True)` 仅请求通达信、关闭交叉合并与回退，并绕过当天水位和上市日跳过；仍按增量近窗取数，`force=True` 才全历史重拉。不能同时传自定义 `sources`。
- 已入库的 `source='tdx'` 正式日 K 只能被正式通达信数据更新，回退源和盘中 spot 不得覆盖；当日 15:00 前仍允许现价刷新，防止把盘中累计值冻结。写入数按实际更新行数返回，失败回执照常留存。
- 腾讯历史日 K / flashdata 未提供成交额时 `amount` 留空，禁止再用 `close×volume` 合成；腾讯现价仍使用接口真实成交额。历史遗留假值须用权威源重写，不通过改阈值或清空数据消除告警。
- 回退源水位不阻止同日重试；日终定稿和 `scripts/resync_market_authoritative.py` 均使用严格权威模式。回归：`tests/market/test_authoritative_integrity.py`。

`load_panel` 对所有请求字段共用一次 `(trade_date, code)` pivot，避免逐字段重复编码和排序；
返回值仍是按日期排序、按证券对齐的 pandas 数值面板，缺失值、复权与 `min_bars` 口径不变。
可选 Polars 读取旁路按列转 NumPy 后交给 pandas，不再构造逐行字典。

## 如何扩展

盘中选股的 `fetch_live_spot_bars(..., strict=True)` 为精确形态筛选提供严格输入模式：绕过已完成的 20 秒缓存，要求请求代码有当日完整、有限的 OHLCV；有成交时 OHLC 须为正。明确零量快照允许 O/H/L 为零但 C 须为正，原样留存，由严格预筛路径记入 `zero_volume_codes`，不叠成当天新 K。缺字段、NaN、负量不能当成零量；缺字段不能用现价回填，不根据成交额猜测改量，缺代码则明确中止。默认模式保持原有兼容行为。严格和普通请求的缓存键隔离，同一在途请求仍可共享。`screen()` 在结果快照中记录调用起止时刻；批量行情并非全市场原子同刻快照。

新行情源：**写 fetcher（只取原始报文）+ 在 `domain/source_contract.py` 声明 FieldSpec**，再注册到 lane。
归一（列映射 / 数值化 / 手→股 / 百分数→小数 / 缺列质检）只走 `infrastructure/pipeline.py`，
**禁止**在 adapter 里再手写 rename 或乘除 100。对方改字段名 = 改契约一行；改 URL = 改 fetcher。

例外：无中文源列的二进制/CSV 解析（如腾讯 qt 字符串、通达信协议）可在 fetcher 内定单位，
管线对已是英文仓内口径的列（`volume`/`turnover`）不二次换算；中文「成交量」/`turn` 仍只交给契约。

## 以通达信为准（权威源语义）

`hist_daily` 与 `spot_batch` 的**权威源**是 `tdx`，定义在 `router_live.AUTHORITATIVE_BY_LANE`。

「注册表第一位」和「权威」不是一回事：粘性赢家（`peek_sticky`）会把上一轮命中的源提到最前，
通达信偶尔抖一次、腾讯顶上并被钉住 600 秒，接下来这 600 秒里冲突日就按腾讯的值落库——
而腾讯的 `amount` 是 `close × volume` 合成的假值。`authoritative_order()` 让权威源免疫粘性重排；
`pin_authority()` 为真时调用方跳过钉粘性。用户在运维「数据源」页**手选** provider 仍然优先，
那是明确的人工决定。`LOCI_LANE_AUTHORITY="hist_daily=sina"` 可覆盖，空值表示该 lane 无权威源。

### 指数伪代码必须声明 `instrument_type`（踩过的坑）

通达信的指数与个股是**两套协议**：`000300` / `000905` / `000852` 必须走 `get_index_bars` +
`market=1`。用 `get_security_bars` 问同一个代码**不会报错**，它安静地返回深市同号**个股**的行情——
实测中证 500 当天 7717，串回来的个股是 8.54。这批值曾被写进生产库基准指数 1.2 万行，
基准一歪，复盘里每一条相对收益都跟着错。

所以 `tdx_daily.fetch_daily_bars` / `fetch_daily_many` 的 `instrument_type` / `instrument_types`
**必须由调用方传对**，缺省按 `STOCK` 处理（`000905` 在深市确实有一只同号个股，不能靠代码前缀猜）。
回归见 `tests/market/test_tdx_index_routing.py`。

### 实时日 K（spot）也走通达信

`TdxAdapter.fetch_spot` 取每只票日线的**最后一根**，而不是 `get_security_quotes`：
后者一次能问 80 只、更省往返，但**不带交易日**，且混市场批量会整批失败（实测沪+深+北一起问返回 0 条）。
日线接口每只多一次往返，却自报 `datetime`——当日 K 线必须由源自报日期才能写库，
否则法定节假日会把昨天的收盘价盖上今天的日期，还往交易日历插假交易日。
因此 `spot_declares_trade_date=True`，它在 `dated_spot_adapter_ids()` 的写库白名单里。
实测 16 路并发 249 票/秒，全市场约 22s。

## 同步为什么快（先读这段再改同步）

全市场 5544 只的 `sync_quotes` 实测从 **1.61 票/秒 / 57.5 分钟** 降到 **36 票/秒 / 2.6 分钟**（`scripts/benchmark_sync_path.py`，走真实 router/store 代码路径，种一个临时库避免污染生产）。四个改动，缺一个都会退回去：

| 改动 | 改前 | 改后 |
|---|---|---|
| 前置状态查询（`sync_prefetch.py`） | 每票 4 条点查 ≈ 2.2 万次 | 5 条全市场聚合（含上市日） |
| SQLite 连接 | 每票新建 + 关闭，5500 次 | 主线程一条，取数线程完全不碰库 |
| 写事务 | 每票一次 `BEGIN IMMEDIATE` | 按批一次（`persist_quote_frame_receipts`） |
| 多源协作合并 | 每票都对所有启用源拉一遍 | 抽样（`should_cross_check`），多数票只打主源 |

- **限速器语义变了**：`_RateLimiter`（现居 `sync_engine.py`）的 `min_interval` 是**每个 worker 槽位**的间隔，不是全局串行队列。旧实现无论开几个 worker 都要付 `票数 × 2 × interval` 的排队地板（5500 × 2 × 0.15s ≈ 1650s），这是原先最大的单点。真正的礼貌约束是每个 (lane, 源) 的在途名额门闩。
- **在途名额按源定**：`router_live.ADAPTER_SOURCE_CONCURRENCY` 覆盖 lane 级默认。通达信是二进制协议、每线程各自一条长连接，给 24；HTTP 源怕被判爬虫，仍留在 lane 级的 4。环境变量 `LOCI_ADAPTER_CONCURRENCY="hist_daily:tdx=32"` 可调。
- **交叉校验改抽样**：`fetch_daily_routed(code)` 默认按 `should_cross_check(code)`（代码对 `CROSS_CHECK_SAMPLE_EVERY=50` 取模，稳定可复现）决定是否做多源合并；未抽中的票只打主源，**未请求的源在回执里明确记 `skipped` 并写明原因**，不会伪装成「校验过且一致」。`LOCI_CROSS_CHECK_EVERY=0` 关闭抽样（全部只打主源），`=1` 恢复每票都校验。
- **上市日空历史软跳过**：`sync_prefetch.py` 同步预热 `instruments.list_date`。上市日尚无定稿日 K（盘中可能只有 `_spot` 临时行）时，历史源不发请求，终态记 `skipped` 并留回执；水位以 `status=ok/source=listing_calendar` 清掉旧失败，但该来源不命中“今日已同步”短路，收盘后下一轮再正常回填。这样新股不会把各来源误报成失败或触发熔断，旧票的真实连接/解析故障仍按失败处理。
- **TDX 服务器探测**：公开行情服务器十台里常有大半是死的，串行探测每台吃满超时（实测 10.4s）。`tdx_daily.rank_servers()` 改并发探测 + 落磁盘缓存（`data/tdx_servers.json`，TTL 6 小时），冷启 2.0s、热缓存 0s。
- **取数与落库分离**：`sync_engine.py` 里取数线程只做网络、结果进**有界**队列，单写线程按批落库。队列有界是刻意的——全量回填单票几千行，无界队列会把内存吃穿；队满自然回压取数线程。批大小 `CHUNK_FULL=40`（全量）/ `CHUNK_INCREMENTAL=200`（增量）。
- **有界队列的代价是收尾必须主动**：`sync.py` 的收尾写死在 `finally: pool.shutdown(wait=True)`。「队列有界」加上「消费者可能提前离场」就是一条**确定性死锁**——`drain` 循环体里任何一处抛异常（progress 回调抛错、写线程 MemoryError、Ctrl-C 的 KeyboardInterrupt），控制权跳到 finally 时队列是满的、消费者已经走了，而池里还有几千个 code 没跑完，worker 全堵在 `outcomes.put()` 上永远醒不过来，`shutdown(wait=True)` 于是 join 一条永不返回的线程，**同步线程与进程退出双双挂死**。5544 只票配 600 深的队列，这不是概率问题。所以队列是带 abort 闸的 `OutcomeQueue`（`put_or_abort` 每 0.1s 回头看一眼闸）、池是 `FetchPool`，收尾三步缺一不可：**掀闸**（放出堵在 `put()` 上的 worker）→ **cancel 未起跑的任务**（否则用户都 Ctrl-C 了还要把剩下五千只票拉完）→ **边抽干边等**（兜住掀闸的时间差）。
  - **光给 `get()` 加 timeout 不算修好**：超时之后 `drain` 无非再等一轮，真正堵着的是 worker 那一侧的 `put()`，不从那头把人放出来 `shutdown` 照样挂死。**单独 `cancel_futures=True` 也不够**：它只能取消**还没起跑**的任务，已经跑起来、正堵在 `put()` 上的那几条一根都动不了——而恰恰是它们让 join 永远等不完。
  - **`get()` 的 timeout 不是放弃条件**：单票取数几秒钟很正常（TDX 冷启探服务器就要 2s），超时即放弃会把慢源误判成结束、让同步报告凭空少票——那是比死锁更难查的静默错误。它只是让主线程周期性醒过来看一眼闸。同理 `fan_out` 的扇出循环整个包在 try 里：`submit` 中途抛错时调用方连 pool 引用都拿不到，得由 `fan_out` 自己收尸。
- 回归测试 `tests/market/test_sync_engine_shutdown.py`：子线程跑完整调用形状 + `join(timeout=)` 断言不挂死（仓里没装 pytest-timeout）。**修复前 5 条挂满 15s 超时**，快照是 `已消费=5 已取数=21 队列积压=12`（队列 maxsize 恰好 12，堵死）。

## 存储层拆分（infrastructure）
对外符号不变：`from src.market import MarketStore, normalize_code, …` 与
`from src.market.infrastructure.store import MarketStore, normalize_code, …`。
内部按职责拆文件（均 ≤600 行）：

| 文件 | 内容 |
|---|---|
| `store_codes.py` | `MarketError` / `normalize_code` / `guess_market` / `to_sina_symbol` |
| `store_schema.py` | DDL、字段常量、`DEFAULT_DB` |
| `store_quote_payload.py` | 落库前归一：`partition_valid_ohlc_rows` 按四价约束拆「可落盘 / 拒绝」，走 numpy 比较且**全部合法时原样返回入参、不做防御性 copy**（250 行帧 1.69 → 0.12 ms，调用方只准读它）；`quote_value_columns` 按 `QUOTE_VALUE_FIELDS` 逐列把 NaN 换成 NULL —— 该常量刻意不复用 `PANEL_FIELDS`（后者 `turnover` 排在 `outstanding_share` 前，照它拼参数会把两列对调而不报错） |
| `store_rw.py` | 写入与基础读取 mixin；`upsert_quote_bars` / `set_watermarks` 供当日 spot 单事务批量落库（一次 DataFrame 归一，按 code+date 去重，禁止逐票建表）；`history(..., limit=)` 单票最近 N 根；`history_many` 批量 `code IN` + 窗口截断供龙头地图热路径。`_prepare_quote_frame` **只挑要落库的列重建一张帧、且保持数值 dtype**（NaN→NULL 交给 `store_quote_payload.quote_value_columns`，整帧 `astype(object)` 会把 OHLC 校验拖慢一个量级）；写日历时按 `trade_date` 去重再喂（全市场 spot 是 5500 行同一天，5500 条 `DO NOTHING` 降到 1 条） |
| `store_summary.py` | 概览查询：`latest_bars` 走日历近窗+索引；`recent_amounts` 供 review 容量校验；`coverage` 走日历/证券表，行数取 `store_row_count.py` 的缓存 |
| `store_row_count.py` | `quotes_daily` 行数缓存 `meta.quotes_daily_rows_v2 = "{base_date}\|{base_rows}"`：**冻结基数 + 活动尾巴**。总数 = 基数（`< base_date`）+ 主键前缀范围计数（`>= base_date`，只有近一两日）。写入路径增量维护：`store_rw` 上传落在基数区的行**批量**探测「是否已存在」（每 400 对主键拼一条 `VALUES` 临时表 JOIN 主键索引，不再逐对 `SELECT`——回填一票 250 个交易日原本就是 250 次往返）只计真正新增，批内出现新交易日就推进冻结线；热库裁窗 `note_trim_below` 按将删行数递减、重灌 `track_hot_window_rewrite` 按区间前后差修正（重灌深入基数区 >30 日即作废重建）。只有无缓存时才全表 COUNT 一次。**为什么**：上一版绑 `quotes_revision`，盘中每 5 分钟同步一次就作废，随后的 `coverage()` 要冷扫 400 MB 覆盖索引——线上 2026-09-04 实测 `GET /api/ops/data-location` 26～30 s，设置页遮罩跟着蒙 30 s |
| `store_rw.trading_days` | 带 `start`/`end` 的空结果**不会**触发 `rebuild_calendar`（热库常见「尚无下一交易日」）；仅全局日历为空且有日 K 时才从 `quotes_daily` 重建 |
| `store_provenance.py` | 来源回执原子写入；`persist_quote_bar_receipts` **先按 code 把载荷索引成 `dict[str, list[row]]` 再分发回执**（逐 code 过滤/计数是 5500×5500 次比较，实测占整次 spot 落库的 96%），同一 code 的多个交易日必须整段留在列表里，只留最后一行会静默丢数据；`store_provenance_query.py` 负责 `source_evidence(codes,start,end)` 只读查询（code 分片 + 先取 receipt_id 再反查，避免 EXISTS 扫千万行日 K）。默认保留完整详情；显式 `include_details=False`（`data_snapshot` 对应 `include_source_details=False`）仍保留全部实际报价关联 receipt/attempt，额外历史失败范围只做 SQL 汇总，标记 `receipt_details_omitted`，严格 PIT 拒绝。汇总失败范围可能与实际引用回执重叠，不可直接相加计算去重总量 |
| `store_board_page.py` | 行情台分页：所属行业过滤、换手率排序/下限 |
| `store_panel.py` | 全市场面板与 `_consolidate`；`_require_bounded_range` 拒绝 codes/start/end 全空的无范围调用 |
| `duckdb_panel.py` | 可选 DuckDB 只读旁路（`LOCI_MARKET_DUCKDB=1`；失败回退 pandas） |
| `polars_panel.py` | 可选 Polars 只读 POC（`LOCI_MARKET_POLARS=1`；未安装/失败回退 pandas 或 DuckDB） |
| `sync.py` / `sync_spot.py` | 历史日 K / 当日 spot 同步；后者维护单飞（key = **代码集合 sha1 指纹**＋交易日＋batch_size，board/screen/sync/ops 请求同一批代码时能合流；**失败只负缓存 3s**、成功才留 30s，一次抽风不会被重放半分钟）、**跨进程 spot 文件锁**、逐代码回执与失败终态；写库遇 locked/busy 有限退避，错误用人话中文 |
| `application/screen_spot.py` | **收盘后**选股前「当日行情就绪」：覆盖率≥门禁下限则**跳过 spot**；spot 失败但覆盖已够则软放行；真正不足才阻断 |
| `application/screen_live.py` | **盘中**选股（09:15–15:00 选今天）：自己拉 `spot_batch` 叠内存面板，**不写** `market.db`、不拿写锁。历史只读热库。拉不到实时就中止，不回退昨日本地日 K |
| `em_industry.py` | 东财行业板块 → `code→行业名`:磁盘缓存 + 7 天 TTL + **失败兑现旧缓存** + **30 分钟失败冷却**。从 `sources.py` 拆出——那边是「证券列表与回退链」,行业名只是路上一步锦上添花,却带着自己一整套缓存/冷却/并发取数 |
| `application/data_quality.py` | 行情库体检（阈值与 `Finding` 见下一行的 `data_quality_thresholds.py`，本文件是判据与编排）:权威源占比(全库)、**最后一个交易日的权威源占比**、合成成交额、缺回执、当日覆盖、基准指数量级、非权威源水位。**只读只判不改库**;由运维托管任务 `data_quality`(工作日 16:30)天天跑,超阈值出中文告警。合成成交额判据有**两道排除**,都是为了不把真数据报成假值:①只在会合成的源上算(`FABRICATING_SOURCES`),通达信给的是真实成交额;②**跳过 `high == low` 的单一价格成交日**——整天只成交在一个价位时 `amount = close×volume` 是算术恒等。②是实测逼出来的:生产库曾报 8128 行,其中 **7721 行(95%)当日 `high==low`**(1990 年代薄成交、北交所/新三板低流动性个股),而通达信自己的单一价格日里也有 33% 满足该等式——**是物理规律,不是某个源在造假**;且它给的处置建议(跑 resync)实测**修正 0 行**,因为 98.4% 的日期通达信根本够不到。**当日覆盖判据用比率不用绝对行数**(`min_last_day_coverage=0.95`,分母取 `instruments` 里的 STOCK 只数):曾写死 `min_last_day_rows=5000`(注释称「全市场约 5540」),而生产库实际只有 4932 只,覆盖 4935 行已是 **100.1%** 却天天报警。**天天响、照着做又没用的告警比没有告警更糟**,它会把整张体检表训练成噪音。`instruments` 读不到时退回绝对地板 `min_last_day_rows_floor=500` 并写明,不让空库蒙混过关;辅助探测走 `_scalar_optional`(容错),主判据仍走严格的 `_scalar` |
| `application/data_quality_thresholds.py` | 体检的**阈值与结论载体**:`QualityThresholds`(每个默认值都带标定依据)、`Finding`、`FABRICATING_SOURCES` / `AUTHORITATIVE_PREFIX` / `PROVISIONAL_SUFFIX`。**只有数据定义,不碰库**。从 `data_quality.py`(638 行)拆出:改阈值的人要读满屏「这个数字是怎么标定出来的」,改判据的人要读 SQL 与分支,两拨读者原先谁来都得先翻过另一半。`data_quality.py` 原样 re-export 全部符号,`from src.market.application.data_quality import QualityThresholds / Finding` 继续成立。**取证归属**那段注释(开发机 2026-08-26 只读实测 / 同日生产库健康 / 别把开发机数字写成生产实测;根 AGENTS.md §3.5 指着它)仍在 `data_quality.py::_check_last_day_authoritative` 的 docstring 里,没有搬走 |
| `infrastructure/write_lock.py` | 跨进程行情写锁（`.market.db.write.lock`）：sync/spot 互斥，杜绝 Loci 与 CLI 双写把库顶成 locked；**同线程可重入，跨线程等待与文件锁共用 `_LOCK_WAIT_SEC` deadline**（等不到抛 `MarketWriteBusy` 并指名持锁者，绝不无限期挂起）；`current_write_holder()` 供诊断；`LOCI_OBSERVABILITY=1` 时记 `loci.lock.wait_ms`（busy/reentrant/local_deadline）。**fd 与锁文件必须成对归还**：`os.open(..., O_CREAT\|O_EXCL)` 一成功磁盘上就已经躺着锁文件，所以从那行到 `yield` 整段都包在 try/finally 里走 `_release_lock_file()`（先 close 后 unlink，顺序不能反，Windows 上文件开着删不掉）。以前只有 `os.write` 一行裸露在外，它抛 OSError（磁盘满 / 只读挂载 / 杀软拦截）时本进程漏 fd，更贵的是残留锁的 holder 前缀不是别人的 pid、age 又不到 `_LOCK_STALE_SEC`，于是**把其它进程整整挡满 30 分钟**——一次写失败换来半小时行情库瘫痪。保护范围覆盖整段而非只包 `os.write`：中间的 `record_lock_wait` / logger 抛错是同一种双重泄漏。回归测试 `tests/market/test_write_lock_fd_leak.py`（修复前 5 条失败，其中「下一次取锁」直接等满 deadline）。**残留锁按 pid 探活立刻接管**（`_holder_pid_is_dead` + `src.shared.process_alive.pid_alive`）：旧逻辑只认「holder 是本进程 pid」或「锁文件超过 `_LOCK_STALE_SEC`(30 分钟)」两条接管理由，于是一次崩溃 = 半小时行情库全面瘫痪（2026-08-26 现场：锁里躺着 `18848:sync:full`，而 18848 在 08-25 就没了，同步/spot/选股补数全部 `MarketWriteBusy`）。现在 pid 明确已死即接管，留 `_LOCK_DEAD_PID_GRACE_SEC`(30s) 宽限挡住「刚 `os.open` 还没 `os.write`」和 pid 复用；**探不出来一律当还活着**（回落时间窗）——误判活着只是多等，误判已死会把正在写库的进程踢掉。接管会打 WARNING + `market_write_lock_dead_holder_evicted` 事件，「谁掀了锁」必须留痕。 |
| `adapters/router.py` / `router_live.py` / `daily_merge.py` | 日线协作拉取（排队取齐 → 交叉优先序校验/互补合并 → 再交同步落库）、spot/live 竞速、粘性与来源门闩 |
| `store.py` | `MarketStore` 组合、连接生命周期、schema 迁移与 re-export |

### 「主源今天开始退化」为什么要单独一条判据

`_check_authoritative` 的分母是**全部历史**,对单天回落基本失明。**开发机**只读实测
(2026-08-26,该机通达信自 07-28 起被限流):全库 16,966,403 行里 tdx 占 16,376,434
行 = **96.5%**,判绿;而同一时刻最后一个交易日的 5542 行里 tdx **0 行**——主源当天
一行都没写进来。要把全库压到 95% 以下还得再灌 271,948 行非权威数据,按每天 5542 行
算是 **49 个交易日**;那台机器从 07-28 起当日权威源占比就从 ~98% 掉到 ~20.7%、后来
归零,20 个交易日过去全库口径一声没吭。所以
`_check_last_day_authoritative`(key `last_day_authoritative`)只看最后一个交易日。

> **取证归属**:同一天的**生产库是健康的**(全库 97.1%,近 8 个交易日逐日 99.9%~100%
> tdx)。上面那组数字来自开发机。这条判据补的是**算术上必然存在**的盲区——分母十六年、
> 分子一天,比值天生对单天不敏感——不是在修某次生产事故。两台机器当天一好一坏,把开发机
> 的数字写成「生产实测」会让后来人照着一个不存在的故障去排查。

- **spot 临时行单独归一类**(`PROVISIONAL_SUFFIX = "_spot"`),这是不误报的关键。盘中
  spot 落的行 source 带 `_spot` 后缀,日终同步收尾才用正式日 K 覆盖;体检虽然托管在 16:30,
  但人随时会手动点。于是占比**只在已定稿的行之间算**,`tdx_spot` 也算临时行——盘中
  spot 走了通达信、日终正式日 K 根本没落,恰恰是要抓的形态,不能拿它把占比洗绿。
- **临时行占比 > `max_last_day_provisional_ratio`(0.5)= 当天还没定稿**,此时不判占比,
  结论里写明「尚未定稿」。但这个豁免**带时限**(`last_day_settle_hour=16`,依据:日终重刷
  15:10、热库重建 16:10、体检 16:30):过点还满屏 spot 就报,否则「日终同步整个失败」
  会被当成「还没定稿」白白放过,而那恰恰最该当天知道。

  > **这条判据上线当天(2026-08-26)就抓到了真问题,而且不在体检这一侧**:`today_refresh`
  > 只刷复权因子 + `apply_today_spot`,从不调 `sync_quotes`;而 `quotes_daily` 的 upsert 是
  > 后写覆盖先写,`apply_today_spot` 又是每种 mode 里最后一个写库的。于是 spot 只要成功,
  > **当日必然 100% 临时行**,正式日 K 得等第二天早上增量近窗回头重写才落——当天的 15:30
  > 选股、当日回测与复盘读到的全是没有回执、`amount` 可能是 `close×volume` 合成假值的行。
  > 修在流水线侧:`ops/application/jobs/sync.py::_finalize_today_with_authoritative`,日终在
  > spot **之后**再用权威源重写当日(通达信近窗 20 根,全市场约 2 分钟)。**顺序不能反**,
  > 反过来 spot 会把刚定稿的正式日 K 重新盖成临时行。
- **阈值 `min_last_day_authoritative_ratio=0.90`** 的依据是日水位实测:2026-01-01~07-27
  的 135 个交易日,当日权威源占比稳定在 **97.85%~98.24%**(够不到的 2% 是通达信代码段
  不支持的票,归 `watermark_source` 管)。0.90 留了 8 个百分点、约 430 行/日的余量;
  真退化那一侧是 20.7% 与 0%,离阈值很远。**不用绝对行数**——旧的 `min_last_day_rows=5000`
  已经在 4932 只的库上天天误报过一次;全市场只数还在漂,而且**两台机器同一天都不一样**
  (生产 4932、开发机 5544)——绝对阈值连「此刻全市场有多少只」都锚不住。
- **级别是 `warn` 不是 `block`**:block 在本模块表示「库整体不可信」(全库权威源塌了、
  基准指数串成同号个股),会让每一次回测与选股都错;单天走回退源是可以定点重灌补回来
  的。而 `warn` 一样进 `build_alert`、企微推送的判据是「`blocked` 或有 `alert`」,
  **定成 warn 不会少通知一个人**,只是不把「库不能用」那面旗插上。

## 热读库（market_hot.db）
滚动热读库是近 `HOT_WINDOW_TRADING_DAYS`（700）交易日的行情窗口镜像，与全量库物理隔离。决策见 [ADR-007](../../docs/adr/ADR-007-market-hot-readonly-window.md)。

- 路径：`paths.market_hot_db()`（默认 `data/market_hot.db`；`PALACE_MARKET_HOT_DB` 可覆盖，测试已隔离到 tmp）。
- schema 与 `MarketStore` 完全一致：日 K / 日历只保留窗口，`instruments` / `adjust_factors` 全量复制，回执只保留与窗口内日 K 关联的行。
- 入口：`open_market_hot()`（接口同 `MarketStore`）；增量镜像 `mirror_recent_to_hot`（同步 / 当日 spot 写全量库成功后调用；若热库窗口偏浅会自动升级为全量重建），全量重建 `mirror_to_hot`（幂等，可随时重跑）。`instruments` / `adjust_factors` 两张小表按 `<table>_revision` 做脏检查（热库侧记 `mirrored_<table>_revision`），没变就跳过重灌——增量镜像在选股热路径上每次都会调到，无条件整表重写会把一次写事务压进交互。全量重建走 `force=True`，始终重灌，保住「热库损坏时重跑即可」这条修复路径。`hot_window_shallow` 检测浅窗口；`hot_unusable_reason` 查窗口深度 + 末日是否跟上全量库（窗口够深但缺当日也会被拒）。**选股路径统一走 `hot_fallback_reason(full, hot, *, trade_date, warmup_bars, end=None, live_overlay=False, window_trading_days=700)`**——它在前两条之上再校验第三条：从 `trade_date` 往前数 `warmup_bars` 个交易日的起点到 `end`（默认同 `trade_date`）之间，热库的交易日历必须与全量库一致；返回空串表示可用，否则是人话回退原因。第三条不能省：前两条都是相对**今天**的判据，看不出「用户要选的是 2020 年而热库只有近 700 个交易日」；缺了它，`screener._resolve_start` 的 `max(0, len(days) - bars)` 会把预热起点无声钳位到热库首日，历史日选股静默少票、结果还照常入库。`live_overlay=True` 只跳过末日判据（盘中今日价走独立实时 overlay），预热日历照查。`warmup_bars` 收整数而**不是** engine 对象：market 不得反向依赖 strategy，预热长度由调用方 `signal_history_bars(engine)` 算好再传。两者复制后都会按全量库当前窗口起点裁掉 `trade_date < start` 的日 K / 日历并清理孤儿回执（增量 copy 起点可能是近几天，裁剪仍用 `_window_start(full, HOT_WINDOW_TRADING_DAYS)`）。
- 读写物理隔离：写操作（`apply_today_spot` / `sync_quotes` / bootstrap POST）仍走全量库 `paths.market_db()`；行情 HTTP 读端（coverage/session/board/quotes/search/industries/minute 本地名与复权）走热库。选股默认读热库；`requires_full_history`、镜像失败、热库落后于全量、或**目标日的指标预热日历不在热库窗口内**时回退全量库（判据见上条 `hot_fallback_reason`）。触价提醒（`GET /api/alerts/today`）、notify alerts、MCP `instruments_search` 只读热库。
- `open_screen_store(market_db, hot_db, *, trade_date, warmup_bars)` 是只读选股入口（助手战法、Screen Skill 试跑）：不镜像（镜像是同步 / 选股任务的写职责），内部过 `hot_fallback_reason`。两个关键字参数**故意没有默认值**——留默认就等于把「历史日静默少票」的缺口原地保留给下一个调用方。
- **故意读全量**：`GET/POST /api/market/bootstrap`（回填进度看全库 coverage）、`/api/universe/*`、health/repair/sync、board `live&persist=true` 后台 spot 落盘（写鉴权，成功后镜像热库）、review 长窗（equity/trips/candidates/plans/winrate）、回测与研究路由。
- 可重建派生缓存：日 K 历史不可变，热库损坏时删掉重建即可（`hot_rebuild` 任务），零双真相。镜像失败不阻断 sync。
- **窗口搬运分批，但事务不拆**：`_copy_quotes_window` 在热库写锁内把全量库 `[start, ∞)` 的日 K / 日历搬进热库。原实现对全量库 `fetchall()` 整个窗口（rebuild ≈ 700 交易日 × 5500 只 ≈ **390 万行**）再 `[tuple(row) for row in rows]` 复制第二份，峰值是两份全量、全程持锁。现在读侧 `fetchmany(_COPY_BATCH_ROWS=5000)` + 写侧 `executemany` 分批（`_stream_copy`）。合成库实测（同机同库，`tracemalloc` 峰值）：

  | 窗口行数 | 改前峰值 | 改后峰值 | 改前耗时 | 改后耗时 |
  |---|---|---|---|---|
  | 35 万（700 × 500） | 264.6 MB | **6.1 MB**（43.8×） | 10.98s | 9.45s |
  | 140 万（700 × 2000） | 1059.8 MB | **6.1 MB**（175.3×） | 49.64s | 42.41s |

  峰值与窗口大小**解耦**（只随批大小走，生产 390 万行窗口按旧实现外推是 GB 级），耗时顺带降约 14%。**删 + 灌仍在同一个写事务里，不要拆成一批一提交**：热库是选股的在线只读库，`hot_unusable_reason` / `hot_window_shallow` 只看窗口起点、天数与末日，看不出「窗口中间少了几百万行」；按批提交会让「删完、灌一半」的残缺窗口对选股可见，跑出静默少票少日的结果，比直接失败坏得多。所以这一步降的是峰值内存与 GC 压力，**不是持锁时长**（该写的行一行不少）。同链路上的 `_replace_linked_receipts` 仍一次性取窗口内 DISTINCT `receipt_id`（量级 ≈ 同步批次数，比日 K 行数小两三个数量级），本轮未动。回归见 `tests/market/test_bounded_reads.py`。

## 查询纪律（`quotes_daily` 千万行，写错谓词会挂死）
`quotes_daily` 主键 `(trade_date, code)` 且 `WITHOUT ROWID`——**按日期聚簇**。顺着这个键做区间扫描是顺序读，逆着写就是灾难。实测同一份数据、同一个语义：

| 写法 | 查询计划 | 耗时 |
|---|---|---|
| `trade_date` 给上下界 + 全市场 60 日 | 聚簇顺序读 | **0.68s**（33 万行） |
| `code LIKE '688%' OR code LIKE '689%'` | `SCAN ... USING INDEX` | **>24 分钟未返回** |
| `code >= '688000' AND code <= '689999'` | `SEARCH ... (code>? AND code<?)` | 8.98s |

规则：

- **日期必须给上下界**。只写 `trade_date >= ?` 时优化器可能改走 `(code, trade_date)` 索引去满足 `ORDER BY`，退化成全表扫。
- **代码前缀用范围比较，不用 `LIKE`**。`OR` 会让优化器放弃索引查找。
- **不在全表上 `SELECT DISTINCT trade_date`**（实测 402s）；日期边界一律查 `trading_calendar` 小表。
- 逐代码跨全历史聚合是最贵的形态（二级索引每行都要回表随机寻道）：先用 `trade_date` 限定探测窗口，再按代码范围收敛。
- 长扫描挂 `conn.set_progress_handler(guard, N)` 做超时闸，别让一条查询把进程挂死。
- 全市场统计必须按 `instruments.instrument_type='STOCK'` 过滤：表里混着 `000300`/`000852`/`000905` 三个指数伪代码，其 `amount` 是垃圾值（单日合计可达数百万亿）。
- **`load_panel` 拒绝无范围调用**。`codes` / `start` / `end` 三个参数全空时 where 子句是空串，SQL 退化成 `SELECT trade_date, code, <6 列> FROM quotes_daily WHERE 1=1`——1696 万行 × 8 列一次性进 pandas，无 LIMIT 无护栏。现在 `store_panel._require_bounded_range` 在发 SQL 之前抛 `MarketError`：本页「选股必须传 codes+窗口」从约定变成硬约束。三者至少给一个——选股/回测传 `codes + start + end`，全市场截面至少传 `start`（默认值不该等于「扫全库」；小库上跑得通不代表生产库上跑得通）。回归见 `tests/market/test_bounded_reads.py`。

## 成交量单位（按源 × 板块，不能一刀切）
腾讯**日 K** 对科创板（688/689）返回「股」，其余板块返回「手」——见 `tencent.daily_volume_scale`。现价接口（`qt.gtimg.cn` 第 36 列）各板块统一为「手」，不适用该规则。

该源的 `amount` 由 `close * volume` 合成，所以 `amount/(volume*close)` 恒为 1，`scale_lot_volumes` 的比值判据识别不出这类错位；修复走 `rescale_star_daily_volumes`（代码级判据：隐含换手 > 100%，或历史线量级比自身 spot 行高 20 倍以上）。**检测与更新同处一把 `market_write_lock`**——判据只在串行下幂等，并发副本会各除一次 100。

## 盘中留存带（intraday）

**这是本仓唯一「丢了就永远拿不回来」的缓存。** AkShare 侧 21 个接口只有当天快照、
东财 `trends2` 的 `ndays` 上限是 5，集合竞价在 AkShare 全库没有第二个入口——不每天
自己落盘就永久没有历史。口径与威胁模型见
[ADR-014](../../docs/adr/ADR-014-encrypted-intraday-tape-retention.md)。

- 落点：`<data_dir>/intraday/<YYYY-MM-DD>/<dataset>.parquet.enc` + 明文 `manifest.json`。
**不进 `market.db`**：行存会把同一份数据放大 5.6~5.7 倍，而按天分目录让过期删除退化
  成 `rmtree`（实测删 30 天 0.011 秒，零碎片、无 2× 磁盘峰值）。
- 加密：DuckDB 原生 Parquet Modular Encryption（`AES_GCM_V1` 256-bit）+ 每库一个随机
  DEK，DEK 经 **Windows DPAPI**（带 entropy）包裹落 `intraday/.dek`。实测无密钥与错密钥
  读取均 **硬失败**（`InvalidInputException`），不会静默返回空表。非 Windows 无 DPAPI 时
  **如实降级为明文并标注 `protection="none"`**——不拿明文 keyfile 冒充加密。
- 入口：`capture_snapshots(data_dir, specs)` / `default_specs()` / `write_intraday_snapshot`
  / `read_intraday_snapshot` / `read_intraday_manifest` / `list_intraday_days`
  / `describe_intraday` / `intraday_status` / `prune_intraday`。
- **空表即失败**：上游返空与「今天真的没有涨停股」在下游是同一个形状（AkShare 涨停池
  越界时就是静默返空表），所以 `write_snapshot` 对空表直接报错，让它落进 `failures`。
- **存原始不存归一**：`pipeline.normalize` 对选填列缺席是静默丢列、对坏值是静默 NaN。
  快照的价值在于「当时上游到底返回了什么」。`manifest.json` 记录本次实际列名，同时就是
  AkShare 上游列漂移的比对基线。
- `spot_close` 先要东财 23 列原表，`RemoteDisconnected` 时回退本仓 `fetch_spot_routed`
  多源路由（列会变少，但**宁可列少也不要今天这一格是空的**）；实际来源写进 manifest。
- 保留窗口 60 天，由 `prune` 托管任务顺带执行（不新建任务类型）。三道安全闸门：根必须
  是 `<data_dir>/intraday`、只删严格 `YYYY-MM-DD` 目录、单次删除上限 30。
- 采集由托管任务「托管盘中留存采集」（`intraday_capture`，工作日 15:35）执行；
  CLI：`python -m cli.market intraday-capture | intraday-prune | intraday-status`。

## 磁盘回收（reclaim）

`idx_quotes_receipt` 只服务热库 `_purge_orphan_receipts` 的 `NOT EXISTS` 逐行探测，
在权威库上实测占 **1,049 MB** 却没有热路径消费者。**schema v8 起权威库不再建它**
（`MarketStore(..., keep_receipt_index=True)` 只有 `open_market_hot()` 传）。

`DROP INDEX` 只把页归还库内空闲链，要真正缩小文件得 `VACUUM`：
`python -m cli.market reclaim`。生产库实测 **5,740.2 MB → 4,172.3 MB（释放 1,567.9 MB）**，
`quick_check` 通过、16,966,403 行一行不少。VACUUM 需要约等于库大小的额外磁盘且持写锁，
因此它是显式命令，不塞进启动迁移。

## Live TTL（盯盘快照）
- `application/live_cache.py`：进程内 quote/minute TTL 缓存与 `build_monitor_snapshot`；供纸面 `strategy_monitor` 使用。
- **不写** `market.db` / 热库权威表；不进 research run card / 回测证据。数字以适配器现价为准，AI 不得编造 snapshot 外价格。见 [ADR-008](../../docs/adr/ADR-008-paper-quant-cabin.md)。

## 实时推流与实时信号（大屏）

**铁律：大屏是纯读路径。** `live_hub` / `watchlist` / `live_bars` / `realtime_signals`
以及 `/api/market/stream/*` 三个端点**都不写 `market.db`**：不调 `apply_today_spot`、
不走 `board?persist=true`、不落 research run card。要落盘走
`POST /api/market/board/spot`（写鉴权），与推流彻底解耦。

### 为什么是「一个进程一个采集线程」

改造前每个客户端 tick 各自触发一次上游取数，而 `(spot_batch, sina/tencent)` 的
在途名额门闩默认只有 **1**（`infrastructure/adapters/router_live.py:25
DEFAULT_ADAPTER_CONCURRENCY`）。多客户端大屏把同一条 lane 排成长队，上游看到的
却是同一个 IP 的高频重复整表下载——直接被打成 403 / 截断。
`application/live_hub.py` 因此改成 **N 个订阅者共享一条 feed、一份快照**：
`get_live_hub().subscribe(preset, codes)` 拿上下文管理器，`Subscription.wait()` 靠
`threading.Condition` 唤醒；订阅者归零**自动停表**，不留常驻空转线程。

### 刷新频率预算（被上游缓存卡死的物理上限，不是拍脑袋）

| 场景 | 周期 | 依据 |
| --- | --- | --- |
| 指数 / 自选（≤400 只） | **3s** | `infrastructure/live_tape.py:28 _CACHE_TTL` 就是 3s，更快只会拿到同一份 payload |
| 全市场截面（东财整表 ~5500 行 23 列） | **6s** | 东财原始表 TTL 4s（`adapters/eastmoney_adapter.py:44 _SPOT_RAW_TTL_SEC`），整表归一还要百毫秒级 |
| 非交易时段 | **60s** | 只刷一份收盘快照，不空转 |
| SSE 侧轮询共享快照 | 0.25s | 纯内存读，与 `assistant_stream.py` 对齐 |

全速档要 `build_session_status(...)["live_allowed"]` **且** `board_phase() ∈ LIVE_PHASES`
（`pre_market` / `morning` / `afternoon` / `closing_auction`）同时点头——闸门不判午休、
相位判，只看闸门会在 11:30–13:00 照样 3s 打上游。
**相位词表只有一份**（`application/session.py`）：采集周期、SSE 的 `session.live` 与前端
`sessionCopy.PHASE_LABELS` 共用它。曾经后端发 `session_clock()` 的 `regular`、前端认
`morning`，而 `build_session_status` 压根没有 `phase` / `live` 两个键，于是每一帧都被读成
「已收盘」：大屏在连续竞价里挂着「已收盘·展示最近快照」，实时看门狗也永不触发。
单次取数异常不带死线程：记 `errors` + 指数退避（上限 30s）；**解析失败还会退回上一轮的
代码表改走逐票线路**（`source=fallback_live_quotes`），一条上游挂掉不该让整块大屏停摆。
指标走 `shared/observability` 的 `loci.market.stream.*`。

#### 全市场截面的瞬时重试（2026-08）

`watchlist.default_cross_section()` 是大屏与 `signals` 预设的**唯一**数据源，且只有东财一家
（`eastmoney_spot_all`，没有回退源）。它一抛异常，这一 tick 就没有帧可发——生产日志曾连续数小时刷
`东财全市场截面失败：ConnectionError: RemoteDisconnected`，对端偶发掐连接，而我们一次都不重试，
于是大屏整片空白，用户报成「动不动就连接中断」。

现在 `EastmoneyAdapter._fetch_spot_em_resilient()` 对**瞬时连接类**错误
（`ConnectionError` / `TimeoutError`，含 requests 同名子类）重试**一次**，间隔
`_SPOT_RETRY_SLEEP_SEC=0.4s`。业务错（空表、字段缺失）不重试——重试解决不了，只会把一次失败
拖成两倍延迟。用例：`tests/market/test_adapters_eastmoney_retry.py`。

前端侧对应的是「链路 ≠ 数据」：链路好但没帧时界面报「数据源暂无更新·链路正常」而不是「连接中断」，
见 `frontend/src/features/live/README.md`。

### 模块职责

- `application/watchlist.py`：preset → 代码。`index`（静态指数篮子，`instrument_type=INDEX`）、
  `gainers`/`losers`/`turnover`/`amount`（东财全市场截面排序 Top N，**解析时顺带把行带回**，
  全链只取一次数）、`watchlist`（显式 codes）。**硬上限 400 只**，对齐新浪 hq 单批。
  `all` / `signals` 走 `movers_universe()`：**四榜合集**（涨幅 120 / 跌幅 80 / 成交额 120 /
  换手 80，去重后按 |涨跌幅| 补满 400）。**不许再写 `rows[:400]`**——
  `ak.stock_zh_a_spot_em()` 按代码倒序发表（`fid=f12` + `po=1`），表头 400 行清一色北交所，
  信号引擎整天盯着一批与用户无关的标的跑规则，涨停就在屏幕上而信号栏永远「无信号」。
  `all` 另带 `index_codes`（指数不在东财截面里，由 hub 单独补一次，指数带才跟着推流跳）。
- `application/live_hub.py`：单采集器 + 广播；`Snapshot(seq, as_of, source, rows, session)`，
  `seq` 单调递增供 `Last-Event-ID` 续传；`stats()` 喂 `/api/market/stream/stats`。
- `application/live_bars.py`：live 报价 → 内存分钟 bar（环形缓冲，按交易日重置）。
  **不走 `minute_bars` lane**——那是逐票 HTTP，几百只票的热循环里跑不动。
  分钟量取相邻快照的累计差；当日第一笔没有前值可减，记 0（不造假巨量柱）。
- **实时信号拆在三个文件里**（原来是一个 899 行的文件，规则表与引擎的变更频率完全不同）：
  - `application/realtime_rules.py`：6 条轻量规则（均线金叉 / MACD 金叉 / 放量突破 /
    快速拉升 / 临近涨停 / 炸板）+ 参数规格 + 注册表 `RULES`。**加规则只动这里。**
  - `application/realtime_rule_config.py`：ops.db 里的阈值覆盖怎么进内存（读取、30s TTL
    缓存、对外形状）。库里只存被改过的键，默认值的唯一真相源是代码里的注册表。
  - `application/realtime_signals.py`：引擎调度（面板缓存、去抖、涨速采样、进程单例），
    并把上面两个模块的公开符号原样重导出——调用方不必知道拆过。

  热路径两处快路径特例，等价性由 `tests/market/test_realtime_signal_internals.py` 钉死：
  `_tail_series` 用 numpy 直接拼「历史 + 今日未完成 bar」并返回 RangeIndex（规则全部按
  位置取值，日期索引只让每 tick 多付一次索引对齐）；`_crossed_now` 是 `CROSS(...).iloc[-1]`
  的标量版。500 只票 x 6 条规则实测 766ms → 219ms/tick。

### 实时信号的三条口径

1. **每条信号带 `provisional: true`**：盘中 close 每 tick 都在变，CROSS 类信号会被下一
   tick 抹掉又长出来，只能当候选。
2. **去抖**：同 `(code, rule, 交易日)` 只报一次；标为可重复的规则（临近涨停 / 快速拉升）
   再叠 cooldown（默认 300s）。语义抄 `ops/application/alert_rules.py:120 _can_trigger`，
   **内存实现，不写库**。
3. **复权口径整条链 `adjust="none"`**：面板默认 qfq 而 live 报价不复权，两者接在一起会在
   除权日附近造出假金叉。历史面板经 `open_market_hot()` + `load_panel(adjust="none")` 取，
   **日 K 当日不变，整个交易日只加载一次并缓存复用**，尾部再追一根「今日未完成 bar」。

## 盘口情报 tape
- `domain/tape.py` 定义 `TapeRequest` / `TapeResult` / `TapeProvenance` 及情绪、涨停池、炸板、题材、竞价 DTO；`provenance.provider_id` 只有一个赢家，其他尝试只留在 `attempts`。
- `infrastructure/tape/router.py` 按 provider first-healthy-wins；失败有短暂进程内冷却，缺数返回 `degraded`，不跨 provider 拼接、不抛业务异常。
- **provider 默认顺序是 `cache` → `wudao` → `local`，缓存排在悟道前面**（`registry.py`）。改这个顺序前先读那里的四条注释，这里给结论：

  - **为什么调**：`WudaoTapeProvider` 只肯用调用方注入的 store（`_cache_store`：不自己开库，避免跨线程连接与意外写盘），而在产三条链路有两条**根本没注入**——`ops/skill_watch/market_regime.py` 的 `make_legacy_tape_call()` 和 `ops/jobs/paper_quant_support.py` 直接传的 `legacy_call_tool`。没有 store，`call_mcp_tool(cache=True)` 整段是空转：每轮盯盘都真调、都真扣 skill 池。而悟道健康时总是第一个返回健康结果，排在它后面的缓存 provider 永远走不到——这才是「缓存成了死代码」的真身。`CachedTapeProvider` 会自己开只读连接（`_store_from_request`），正好补上这两条链路。
  - **不会拿到昨天的数据**：缓存行主键含 `trade_date`，`read_tape_cache` 按 `WHERE trade_date = request.requested_date` 取，还会再比一次载荷自报的 `actualTradeDate`。跨交易日兑现在结构上不可能（回归 `tests/market/test_tape_cache_first.py::test_cache_never_serves_another_trade_date`）。
  - **盘中也不会更陈**：`cache_provider._freshness` 借的是 intel 那套（惰性 import `src.intel.application.fetch` 的 `_settled_at` / `_effective_cache_max_age` / `_cache_matches_session`），与悟道 provider 内部 `call_mcp_tool` 读同一张表时用的是**同一个函数**：盘中 TTL 钳到 10 分钟、收盘后不认盘中抓的半截数据。默认 TTL 5 分钟还比 intel 的盘中上限更严，所以调换顺序只会更新、不会更旧。原来这里是 `request.cache_max_age_minutes or 5` 照单全收，盘后档给的 120 分钟会在盘中原样生效——那才是真正会「盘中兑现两小时前快照」的写法，已一并修掉。（`src.intel.application` 不在 import-linter 的 protected 名单里，受保护的是 `src.intel.infrastructure`，这条依赖过门禁。）
  - **数据形状不变**：生产上 `route_tape` 的唯一消费者是 `legacy_bridge._raw_payload`，悟道 DTO 走 `dto.payload`、缓存外壳走 `payload["structured"]`，两者归到同一个 structured root。
- 缓存未命中时 `is_available` 返回 `False`，router 立刻落到悟道，行为与改顺序前一致。
- **tape 侧只做精确 key 复用**：intel 那边同工具同交易日已经能按「覆盖度」跨入口复用（`limit=80` 的快照直接兑现给 `limit=60`），但那套规则在 `src.intel.infrastructure.intel_cache`，是 import-linter 的 protected 模块，market **不能深掏**。所以 `CachedTapeProvider._key_arguments` 仍只试「请求原参数」和「悟道 lane 实际写入的参数」两把精确 key；tape lane 的跨入口复用改由悟道 provider 那条路承担——它调的 `call_mcp_tool(cache=True, market_store=…)` 用的就是 intel 自己的读侧。要让缓存 provider 也享受覆盖度复用，得先从 `src/intel/__init__.py` 导出 `cache_identity_key` / `coverage_covers`。
- 六条 tape lane 为 `market_emotion`、`limit_up_pool`、`broken_limit_up`、`theme_board`、`theme_members`、`auction_snapshot`。provider 注册复用既有 `lane_providers` / `lane_routes` 语义。
- `wudao_provider.py` 是可选 provider，延迟使用 `src.intel` 包根；无悟道时只返回降级结果。`cache.py` 仅封装已有 `intel_snapshots`，只接受同交易日且 TTL 内的缓存，不新增表。
- **tape 的 date / tradeDate 是一张表，不是一个 if**（`wudao_provider.DATE_ARG_BY_TOOL`）。悟道两种键名并存，且 schema 多为 `additionalProperties: false`：键名写错不是被忽略，而是整条调用被 `INVALID_ARGUMENTS` 拒掉，本 provider 会把它读成「悟道没数据」→ 整条 lane 无谓降级。

  | 工具 | 交易日键 | 依据 |
  |---|---|---|
  | `short_term_emotion` / `limit_up_ladder` / `theme_intraday_capital` | `tradeDate` | `ops/skill_watch/market_regime.py` 在产调用 |
  | `broken_limit_up` | `tradeDate` | `ops/skill_watch/limit_up_momentum.py` 在产调用 |
  | `auction_opening_snapshot` | `tradeDate` | `ops/skill_watch/auction_confirm.py` 在产调用；**只认 `tradeDate`** |
  | `theme_stocks` / `sector_analysis` / `limit_up_filter` | `tradeDate` | 同族当日截面；tape 请求一直按 `tradeDate` 传 |
  | `approaching_limit_up` | `date` | `intel/application/daily_recipe._DATE_REQUIRED` |
  | 表外工具 | `DEFAULT_DATE_ARG = "tradeDate"` | 悟道多数派 |

  另一条同样致命：**调用方已经带了日期就不要再补第二个同义键**。旧实现对 `limit_up_filter` / `auction_opening_snapshot` 无条件 `setdefault("date", …)`，而 tape 请求本来就带 `tradeDate`，于是一次请求里同时出现 `date` 与 `tradeDate` → 整条作废。现在先查 `_DATE_ALIASES`（`tradeDate`/`date`/`trade_date`/`requestedDate`），一个都没有才补规范键。改这张表前先核服务端 `tools/list` 的 schema——权威来源是它，不是这里。
- `local_provider.py` 对情绪、涨停池和炸板池严格派生日 K；`theme_members` 先定行业/代码再取行（避免全市场 JOIN）；`as_of_date` 可复用已探测交易日。`local_theme.py` 将 `instruments.industry` 明确投影为本地题材，题材强度是按日线涨跌/成交额排序的 `0-100` rank，并带 `local_industry_derived` 告警，不能当成盘中资金流。
- **盘口取数不许全表扫**：`local_provider._rows_for_date` 是 `limit_up_pool` / `broken_limit_up` / `market_emotion` / `theme_board` 四条 lane 的公共取数入口。它原来用一条**没有下界**的 `previous` CTE（`SELECT code, MAX(trade_date) ... WHERE trade_date < ? GROUP BY code`）求每只票的上一根日 K：真库 EQP 实测 `MATERIALIZE previous` + `SCAN quotes_daily USING COVERING INDEX idx_quotes_code_date`——为了给当日 5542 只票各配一个昨收，先把 1696 万条索引目录扫一遍，单次 **1915ms**；`market_emotion` 还要为「昨日封板集合」再调一次，一次情绪请求付两遍全库扫。现在改成逐代码在 `idx_quotes_code_date` 上做 `(code, < 当日)` 上界寻道（`ORDER BY x.trade_date DESC LIMIT 1` 标量子查询，见 `_PREV_CLOSE_SQL`），EQP 只剩 `SEARCH q USING PRIMARY KEY (trade_date=?)` + 每票一次 `SEARCH x USING INDEX idx_quotes_code_date (code=? AND trade_date<?)`，同日同库 **1915ms → 57ms（34×）**，5542 行逐列相等。**没有新增索引**，吃的是本来就在的 `(code, trade_date)`。
  - **为什么不给 CTE 加窗口**：无论「固定自然日下界」还是「先查 `trading_calendar` 求上一交易日」，都会在**停牌边界**上改结果——复牌那天个股的上一根日 K 不是上一个交易日。真库实测 2020 年以来仍有 113 个「距上一根日 K 超过 30 自然日」的复牌日（2021 年最长 468 天、全历史 1016 天）。窗口取小了，复牌首日 `prev_close` 变 NULL：涨跌幅、涨跌停判定、情绪宽度当场少一只票**且不报错**；取大了（400 天实测 1278ms）又基本没省下什么。逐代码寻道回看无上限，天然没有这个取舍——寻道成本与回看多远无关。
  - **兑底分支的 `CORRELATED SCALAR SUBQUERY` 是误报**：EQP 里那行看着吓人，但每次执行只是一次 `(code=? AND trade_date<?)` 索引寻道，5542 行实测 **109ms**，比它兜底的那条 CTE 快 18 倍。「相关子查询=慢」是看计划不测量得出的结论。现在主查询与 `except` 兑底共用同一个 `_PREV_CLOSE_SQL` 常量，兑底只少 `instruments` 的 name/industry，两条分支不可能算出两套昨收。
  - 回归 `tests/market/test_tape_prev_close_scan.py`：含停牌/新股/退市的 20 万行合成库，逐行 parity（全市场 / 按 codes / 多个历史截面 / 主查询 vs 兑底）、停牌 420 自然日复牌仍取到正确昨收、30 天窗口方案的反例、以及「计划里不许出现 `SCAN quotes_daily`」的守门；合成库上同机实测 **约 40ms → 1~3ms**（用例自己打印当次数字，断言只要求新写法快 3 倍以上，免得机器抖动把 CI 刷红）。**改 `_rows_for_date` 的 SQL 前先跑它**。
- 龙头地图的日 K 已优先读取 market 热库/注入的 `MarketStore`，缺票才走排除 `wudao` 的 `fetch_daily_routed`；日 K 真相不再来自 AI/Wudao MCP。`legacy_bridge.py` 将旧工具名统一映射到六条 lane，成员参数必须带题材 code/name 或 codes，避免回退成无关全市场。
- `auction_snapshot` 没有本地等价物时明确 `degraded/pending`；`tape_readiness()` 逐 lane 返回 provider、可用性、缺口与告警，不参与扫描器跳过闸门。

## 给 Agent 的用法
- 仓：`from src.market import MarketStore, sync_quotes, apply_today_spot`
- 手动同步：`POST /api/market/sync` 在完成后返回报告（`200`）；同一 ASGI 进程内并发的第二个 HTTP `/sync` 请求返回 `409`，避免重复并发写入 `market.db`。**`execute_sync` 自身已占 `ops.market_gate` 的 sync 写槽**，因此 HTTP / bootstrap / CLI / 调度四个入口共用同一把闸门——不再出现「bootstrap 在闸门视野之外占着写锁、选股与日终同步互相打架」。
- bootstrap：证券列表刷新有 instruments 心跳文案与单源墙钟超时（默认 90s，见 `fetch_instruments_routed`）；完成后立即回报行情总数；首只行情请求未完成时进度仍可能是 `0%`，但会显示 `0/total`，首个标的完成或失败后才递增，失败会进入报告而不会无限等待。完整交易所快照会把已从上市列表消失的旧普通股票标为 `delisted`（历史日 K 保留）；某所列表失败或较本地骤减超过 20% 时保留该所旧目录，禁止一次残表批量误退市。行业归属由 `sources.fetch_em_industry_map` 补齐（东财 ~90 个行业板块各一次 akshare）：结果落 `data_dir()/em_industry_map.json`，默认 **7 天 TTL**（`LOCI_EM_INDUSTRY_TTL_DAYS` 可调，`LOCI_SKIP_EM_INDUSTRY=1` 仍整体跳过），过期才重拉，**重拉失败或拿回空表时用旧缓存兑现**——行业以月为单位变，不值得每次 `sync_instruments` 都在关键路径上重跑，更不能让一次网络抖动把全市场行业清空。**远端连不上时另有 30 分钟失败冷却**（`LOCI_EM_INDUSTRY_RETRY_COOLDOWN_SEC`，见 `_em_industry_in_cooldown`）:磁盘缓存只在「成功取到过一次」之后才挡得住，全新机器 + 端点故障两头落空，每次刷新都要为一个已知打不通的端点白等 19-22 秒（akshare 内部 requests 重试到超时才放弃，实测 `instruments` lane 因此整条探测超时）。冷却后同进程内第二次起 0.001s 返回，有旧缓存仍照常兑现旧的。
- 数据快照：`store.data_snapshot(codes=…, start=…, end=…)` 返回 `quotes / adjust_factors / instruments` 三段水位与 `market_revision`，并附 `source_evidence`（实际落盘来源、字段覆盖率、坏 OHLC、未解析代码）；顶层 `rows/last_date/fetched_at` 仍代表日 K 摘要，供回测/选股结果复现。**选股必须传 codes+窗口**，禁止无范围全库扫证据（千万行库上易 disk I/O error）；同一条线在 `load_panel` 上已是硬报错（见「查询纪律」）。日 K 行数用水位 meta 缓存，不每次 `COUNT(*)`。连接 `busy_timeout=60s` + WAL。它只能证明已落盘来源，未观测到的网络尝试必须保持显式缺口。
- 只要版本号：`store.market_revision()`（一次 meta 单行查询）。判断「这份结果是不是在当前行情快照上算的」用它，**不要为此调 `data_snapshot()`**——后者会连带跑无范围 `source_evidence`，正是上一条禁止的全库扫。
- 会话闸门：`build_session_status`（`/api/market/session` / bootstrap 附带）；补数时返回 `coverage_last_date`、`backfill_from`/`backfill_to`（将补交易日区间）与 `lag_trading_days`；**15:00 前** `expected_last_date` 不含今日（不催补未定稿日线）。**行情库日历不覆盖的日子（今天、缺口日）按交易所公告休市日程判断**（`exchange_calendar.exchange_open_days` / `exchange_is_open`：内置年度公告 + 盘外刷新快照，该年度未公布才按周一至周五兜底）：`trading_calendar` 由已入库日 K 重建，永远不含今天也不知道节假日，旧版按工作日粗判，2026-09-25 中秋收盘后仍报“落后 1 个交易日”并整市场补数；落后数与补数区间现只数真实交易日（国庆后不再按自然日报“落后 8 个交易日”），行情库落后多日时“上一已收盘日”也不再从缺口百出的库内日历里找。现价刷新闸门、选股现价闸门、体检落后估计、盘中选股时钟、竞价确认窗口与纸面量化交易日闸共用同一判定。回归：`tests/test_market_holiday_calendar.py`
- 健康门禁：`guard_market_health` / `check_market_health`；`to_dict` 含 `score`/`grade`（体检分，仅展示）、`repair_plan`、`catalog`、`include_network`。仓内检查 + 扩展项（复权因子刷新覆盖 / 线路关空 / session 补数 / capabilities / schema / 库体积 / 回执 OHLC 拒绝比 / 证据缺口 / 竞速回退比 / 托管 sync Job 时效）；`include_network=True` 另探测 hist/spot/factor/instruments 连通（深度扫描，选股门禁默认关）。因子空表为 **block**；Sprint C 回执/Job 项默认 **warn**，不单独阻断选股。finding 的 `remediation` 供单项修复。门禁仍认 `blocked`。`staleness` 看仓内最新日相对墙钟是否过旧，以及是否覆盖选股基准日；**故意选历史基准日做复盘不会被当成过期**。
  - **回执表要有「最近 N 条」的排序索引**（`idx_source_receipts_recent`，`SCHEMA_VERSION>=7`）。`check_ohlc_reject_rate` / `check_race_fallback_rate` 都用 `ORDER BY generated_at DESC LIMIT 200` 取近窗；生产库 `source_route_receipts` 有 106 万行，没索引时 EQP 是 `SCAN` + `USE TEMP B-TREE FOR ORDER BY`——为拿 200 行排序 106 万行，单条实测 948ms，两条占掉体检 4.08s 的一半。加索引后单条 0.1ms、体检热态 4.08s → 1.65s。**加索引必须同时 bump `SCHEMA_VERSION`**：`init_schema()` 只在版本不符时才跑 DDL，不 bump 的话新索引永远只出现在新建的库上，已有生产库一辈子享受不到（这一脚已经踩过）。剩下的 1.65s 主要是 `check_source_evidence_gap`，尚未优化。
  - **孤儿回执探测也要有界**（`ORPHAN_RECEIPT_SAMPLE=20000`）。`check_source_evidence_gap` 的 docstring 一直写着「故意不扫全表」，但里面查「回执缺 attempts」的 `NOT EXISTS` 原先无界：生产库 106 万条回执逐条相关子查询，实测 **2593ms**，比该函数其余部分加起来还贵，且与近窗抽样的设计自相矛盾。按 `generated_at` 倒序取样是对的轴——写回执坏掉会在最近生成的那批里现形，远古孤儿既查不动也没法补。`observed.orphan_scanned` 会标出抽样口径，避免「0 条孤儿」被误读成「全库干净」。**体检整体:4.08s → 1.65s(加索引) → 0.32s(有界孤儿扫描)。**
  - `grade` 在 `blocked=True` 时最高只到「中」：单条 block 只扣 25 分（100→75）本会显示「良」，体检拦下了选股却写「良」是虚假安心。分值 `score` 口径不变。
  - `factor_age` 看 `MAX(fetched_at)`，只要**有一只**票刚刷过因子就报「新鲜」；`factor_coverage`（warn）按标的统计有多少只的最新因子行超过 `max_factor_age_days`，补上这个偏科盲区。因子过旧不会报错，只会让前复权面板静默失真。
  - `source_evidence_gap` **不做全表 `COUNT(receipt_id IS NULL)`**（千万行库上体检页会卡在「连接行情仓」）：近窗逐日精确统计（`evidence_gap_lookback_days`，默认 20 交易日）**＋** 近窗之外按主键前缀抽样若干历史交易日（`evidence_gap_history_samples`，默认 5 天）。日 K 增量只重写最近约 20 个交易日，只看近窗等于只检查刚被重写的那批行，会退化成恒真断言。`observed` 里带 `window_first/window_last` 与 `history_sample_days/history_ratio`，消息里也写清覆盖范围。全历史逐行缺口仍由 `source_evidence(codes,start,end)` 按实际窗口判定。
- 换手率修补：`backfill_missing_turnover` / `load_shares_asof` / `repair_inflated_turnover`（`infrastructure/turnover_repair.py`）。当日 spot 用「严格早于交易日」的最近流通股本估换手；反推股本优先 `amount/(close*turnover)`，避免东财「手」与新浪「股」混用把换手撑到上千%。`upsert_quotes` 对股本/换手 `COALESCE` 禁止 NULL 抹旧值；`apply_today_spot` 经 `persist_quote_bar_receipts` 将日 K 与逐代码回执**同一事务批量写入**，成功后才推进 watermark；写库路径对 locked/busy 做短退避重试（与 ops 侧 screen 共享读闸门配合，避免多选股串行假互斥后仍被 SQLite 短锁打崩）。体检「回填换手率」→ `POST /api/market/repair/turnover`（带 `since` 时先清 spot/离谱换手并把手量×100）。**as-of 股本一轮只算一次**：`backfill_missing_turnover(shares_asof={日期: {code: 股本}})` 直接吃调用方算好的那份，`apply_today_spot` 估换手用的 `load_shares_asof(today)`（固定倒扫 60 个交易日、约 33 万行）落库后被回填复用，不再重算第二遍；逐日全量修复走 `_RollingSharesAsOf` 按日期**升序滚动复用**（只增量吸收新过去的那几天，每 90 个自然日重播一次以免留住超窗的陈旧股本），几百个交易日的股本查询从 O(天数 × 60 日) 降到约 O(天数)。当日 spot 的代码归一与日期解析也合并成一轮（`normalize_code` 按原始代码去重缓存、日期整列向量化），5500 行不再扫三遍。新浪日 K 的换手率来自 `sina._cached_outstanding_share`：流通股本变动表按 symbol 走 **12 小时进程内 TTL 缓存**（上限 8000 条、满了淘汰最旧、加锁；取不到只负缓存 10 分钟），同一轮全市场同步不再为每票在日 K 之外多打一次新浪，该线路请求量减半。股本只在增发/回购/解禁时变，缓存过期前不会掩盖变动。
- 健康门禁当日覆盖率：目标日=今天且不足时提示「盘中 spot 未写完」（历史同步不含当日），勿与 hist 未跑完混淆。
- **写当日 K 线只用自报交易日的现价源**：`AdapterMeta.spot_declares_trade_date=False`（东财现价表没有日期列，只能本地补今天）的源会被 `sync_spot.dated_spot_adapter_ids()` 挡在写库路径外，probe 与顶栏展示不受影响。否则落在周一至周五的法定节假日，`_is_current_trading_day` 的 weekday 兜底判为交易日、补出来的今天又骗过「spot 未返回今天就报错」那道闸门，昨天的收盘快照会被写成当日 K 线，还往 `trading_calendar` 插一个假交易日（T+N 复盘、回测持有期、会话闸门整体错位一天）。
- **近窗增量的已知代价**：历史行不再每天被重写，因此老库里没有 `receipt_id` 的历史日 K **不会自动补上**回执，严格 PIT 研究会持续拒绝这些输入。要补齐只能跑一次 `force=true` 的全量重同步；`source_evidence_gap` 因此才要在近窗之外抽样历史交易日，否则只检查刚被重写的那批行、恒为绿。
- **tape 诚实度**：悟道 provider 拿不到结构化段（正文超限被截断是常见成因）时返回 `degraded` 并在错误里点名 `wudao_payload_unparsed[:wudao_payload_truncated]`，不再产出一份「今日、未降级、零行」的假结果；`dateStatus=mismatch` / 实际日早于请求日时 `degraded=stale=True` 并带 `wudao:stale_trade_date`。本地题材载荷带 `row_total` / `truncated`，截断会加 `local_theme_rows_truncated` 警告。本地涨跌停判定的容差是 `_PRICE_EPSILON=0.005`（半个最小价位，只吸收取整噪声）——按涨停价百分比设容差会把「+9.5% 且收在最高价」记成封板，虚增涨停家数、最高板与炸板率分母。
- 日 K 增量近窗：`sync_quotes` 按 watermark 与库内最早日决定这票要 `fetch_daily`（全历史）还是 `fetch_daily_window(bars=…)`（近窗）。库内已有更早历史、断档 ≤180 自然日时只补最近 `max(20, 断档天数+5)` 根，顺带重写最近几天订正盘中 spot 落的临时行；**无 watermark、新票（库内最早日晚于窗口起点）、断档过久、`force=True` 一律全量**。近窗时回执 `request_start` 写真实窗口起点，不再谎称 1990-01-01。适配器侧 `MarketAdapter.fetch_daily_window` 默认回落 `fetch_daily`；腾讯（单页 640 根内）/ 东财 / 证券宝 / 悟道已实现真·近窗，`window_start_date(bars)` 是共享的「根数 → 起始自然日」换算。没这层时盘中增量每天会把全市场三十年历史重拉一遍，直接把来源打到连接超时。
- 线路：`fetch_daily_routed` / `fetch_live_quotes_routed` / `fetch_instruments_routed` / `fetch_minute_routed`（可选 `trade_date`，**不写库**） / `fetch_capital_flow_routed` / `enabled_adapter_ids` / `lane_route_policy` / `ALL_LANES`。每个 lane 可为 `auto`，或选择一个手动 provider；手动模式默认不回退，只有显式 `fallback=true` 才按后续优先级降级。**hist_daily 协作**：多工人可并行跑不同代码；对单票则对各启用源**排队取数、全部结束后**按优先序冲突校验、缺失日/空字段互补合并，再交给 `sync_quotes` 落库——不再「谁快谁赢、取消其余」。粘性赢家只提高合并优先序。手选且 `fallback=false` 时仍只打手选源，此时若该源失败，错误里会写明「已手动锁定 X 且未开失败回退」，避免被误读成整条线路挂了。被 `lane_providers` 关掉的源不进日常协同合并；**hist_daily 启用源全灭时会按注册表顺序把关掉的源当最后回退**（命中不钉粘性，腾讯恢复后下一票仍走启用源）。仍全灭时错误写「只剩 N 个启用源；X、Y 已关闭，最后回退仍失败」，用 `lane_disabled_provider_ids(lane)` 取该名单（与 `provider_disabled_lanes` 互为转置）。**门闩**：每个 lane/来源有固定的在途请求名额，占满即排队。名额表是 `router_live.ADAPTER_LANE_CONCURRENCY`，默认 1（单飞）；`hist_daily` 为 4——全市场五千多只票，日 K 单飞会把 `sync_quotes` 的 workers 全堵在一条连接上（实测单轮 40 分钟以上），来源礼貌仍由同步侧 `_RateLimiter(min_interval)` 兜住。`hist_daily` / `spot_batch` 排队等待（默认 120s）；live 顶栏竞速仍可非阻塞跳过以便换源。现价整批挂掉时作业侧软跳过，不把全市场记成硬失败。策略保存在本机 `loci.config.json` 的 `lane_routes`，变更会清该 lane 的粘性赢家，不写入 `market.db`。启停是两级，都记在 `loci.config.json` 的 `lane_providers`：`{"sina": {"enabled": true, "lanes": {"hist_daily": false}}}` —— `enabled` 是源总开关（关掉这家全线停用），`lanes` 是逐 lane 覆盖（只停那一条）。读取用 `lane_provider_enabled` / `provider_master_enabled` / `provider_disabled_lanes`；缺记录视为启用。`enabled_adapter_ids(lane, config=...)` 可复用已读到的 config，避免一次请求里反复读盘。必需 lane 被关空**不在这一层拦**（复权因子、证券列表都是单源，拦了就永远关不掉），由界面红字提醒。`list_catalog()` / `AdapterMeta.base_url` 另给每家来源一个站点地址，仅供人核对来源、不参与请求；交易所列表横跨三家交易所，没有单一域名，故留空。`probe_lane` 单源默认 25s 墙钟超时，超时立刻回失败且线程池 `shutdown(wait=False)`，避免运维探测页被挂死 SDK 拖死；`speedtest_daily` 与 `fetch_instruments_routed`（默认各 90s）同款——线程池一律显式 `shutdown(wait=False, cancel_futures=True)`，否则退出上下文时的 `join` 会把超时重新吃掉，超时形同虚设。**每源熔断**（`adapters/circuit.py`）：`hist_daily` 某源连续 5 次**真失败**（异常 / 等门闩超时）即开路 180s，期间跳过该源并在回执写 `skipped`「已熔断，Ns 后自动重试」；冷却到点只放行一个探针（half-open），探针成功才合闸。**空表不计入**——源正常应答但没有这只票（退市/新股）≠ 源挂了。熔断只决定「要不要再打这个源」，不改写任何取到的数字，也不改多源合并优先序。没有这层时，一个稳定不可达的源会让每只票先把门闩 `claim_wait_sec`（默认 120s）耗满才放弃，全市场同步从十几分钟退化到几小时且毫无提示。
- 悟道 `wudao` 是可选 `hist_daily` 旁路（同一 MCP 的 `kline`）：`enabled_adapter_ids` / `adapters_for_lane` 每次重读可用性；未配置/过期/停用/未同步工具时排除。**不进 `list_catalog()`**——数据源目录只露一张 `mcp:wudao`。
- HTTP：`GET /api/market/minute/{code}` 实时分钟线（不落库；见 `api/README.md`）。源（含通达信）无前复权分时；`adjust=qfq|hfq` 时用本地 `adjust_factors` 缩放价格与 `prev_close`，与日 K 复权对齐。
- 同步回执：`sync_quotes()` 的 `SyncReport.source_receipts` 逐标的保留请求源、每次尝试、实际命中、fallback、失败、watermark skip 和未解析代码；历史日 K、spot 日 K 与 `source_route_receipts` / `source_route_attempts` 在同一 SQLite 事务落盘，成功日 K 以 `quotes_daily.receipt_id` 关联最终回执。`coverage` 明确记录源返回行数、同事务实际 `rows_written` 与 `rejected_ohlc_rows`；全拒绝为失败回执且不推进 watermark。竞速未采用的慢源明确记为 `cancelled` 或已完成终态；`source_evidence(codes,start,end)` 以 quote 关联和 receipt 的覆盖/请求日期范围过滤失败与 skip，并保留未解析请求代码。批量源夹带的未请求代码不入库，避免产生没有 receipt 的遗留行情。历史无关联回执，或已关联回执却没有任何 attempt 的日 K，均明确标为 `attempts_not_observed`；严格研究会拒绝该输入。回执是研究输入证据，不是供应商质量评分。
  - 每条 receipt 都输出 `source_url`、`published_at`/`publication_status`、`fetched_at`、`as_of`、`payload_sha256`、`parser_revision`、`available_at`/`availability_status`；最终命中的 attempt 同步保留相同字段。`payload_sha256` 是实际归一并写入的日 K 载荷指纹，`parser_revision` 是仓内归一契约版本。
  - 自动同步只能证明“本次何时抓到、写入了什么”，无法证明供应商对历史数据的发布时间或某历史时点可见性，故始终写空 `published_at`/`available_at` 并标为 `not_observed`。严格 PIT 研究必须拒绝；只有受外部证据约束的导入才可显式写 `observed`，且值缺失会被归一回 `not_observed`。
- 列名中英对照：`domain/column_glossary.py` 的 `CN_TO_EN` 是唯一真相（纯标准库），`gloss_column` 给单个列名标 `{raw, cn, en}`，认不出的一侧留空、不猜译。出口契约：`domain/source_contract.py` 的 `LaneContract` / `FieldSpec` / `Unit` 声明每条 lane 的目标列、候选源列与单位（`unit_by_source`：仅命中中文「成交量」「换手率」或 baostock `turn` 时换算；现价/live 中文成交量同样手→股）。资金流 `涨跌幅 → pct_chg` 写在契约里。`EASTMONEY_*_RENAME` 由契约派生。Source（东财/证券宝）只出原始表，`Adapter` 与遗留 `fetch_with_fallback` 统一过 `infrastructure/pipeline.normalize`。录制夹具见 `tests/market/fixtures/` + `test_source_contracts.py`。新增列名先加 glossary，再进契约。
- AkShare 目录：`infrastructure/akshare_catalog.py`（发现/探测）+ `akshare_catalog_limits.py`（参数校验/归一）只发现本机已安装版本中来自 `akshare.*` 的 `stock_*` callable；目录项记录模块、签名、上游来源、参数描述、样例参数和执行模式，另含从完整 docstring 解析的 `param_docs` / `returns`（解析与来源/类目推断在 `infrastructure/akshare_catalog_meta.py`）。试跑结果在 `columns` 之外附 `columns_detail` 中英对照。目录内每个条目均可试跑，`status=available|needs_parameters` 只表示是否已具备必填参数，`execution_mode` 才表示是否已接入业务编排。试跑按签名归一 `int` / `float` / `bool` 参数，分页限制为 1-5、行数限制为 1-5、字符串至多 128 字符、日期窗口至多 31 天；请求 JSON 限制 16 KiB、4 层、128 个值。生产调用受 8 秒/2 并发预算约束，固定 `spawn` 子进程执行，超时会确认 `terminate/kill/join` 后才释放槽位；容量耗尽返回 429 并附 `Retry-After`，启动失败返回 503。`cli.serve` 默认单 Uvicorn 进程；若外部改为多 worker，必须另行按 worker 数协调总并发。结果和 IPC 摘要也限制字段、嵌套与字节数，不写库，它不是同步管道注册器。`probe_stock_capability(..., max_sample_rows=N)` 只放宽样本行数（上限 `MAX_MCP_SAMPLE_ROWS=50`，给 MCP 工具调用用），超时、并发与参数校验一律不变。
- AkShare 目录辅助：`infrastructure/akshare_tools.py` —— **无上桌/启用名单**。提供 `catalog_entries` / `clear_catalog_cache`、`probe_stock_capabilities_batch`（分页一键全测，单页上限 `MAX_BATCH_PROBE`）、`check_akshare_version`（本机 vs PyPI）。内置 MCP 只挂单一工具 `akshare_call`（按名调用目录内任意 `stock_*`），避免把四百多个接口塞进工具清单。
  - **读路径一律走 `catalog_entries()` 的进程内缓存**：`application/akshare.py` 的 `discover_stock_capabilities()` 是唯一对外读入口，两个读端点（`GET /api/market/akshare/catalog`、`/sources`）与批量探测共用同一份缓存，反射（`vars(akshare)` 全量 + 每条 `inspect.signature`/`getdoc`/docstring 解析）每进程只做一次，别再从 `infrastructure/akshare_catalog.discover_stock_capabilities()` 绕过去。缓存失效只有既有的 `clear_catalog_cache()` 一条路（换 akshare 版本、测试之间），不另造版本号机制；测试要打桩请打 `akshare_tools.discover_stock_capabilities`（缓存边界），打 `akshare_catalog` 那层已经打不到读路径了。
  - 目录条目的样例参数（`default_params` 与每个 `parameters[].sample`）同源，`_capability_entry` 只算一次 `_sample_params` 再传给 `_parameter_descriptions`；改这块别退回「两边各算一遍」，那等于每条能力多跑一趟签名遍历 + 安全日期改写。
  - 适配器默认顺序：日线 **`tdx`（通达信二进制，主源）→ `tencent` → `eastmoney`（akshare `stock_zh_a_hist`）→ `baostock` → `sina`**。主源换成通达信是实测选型的结果（`scripts/benchmark_data_sources.py`，样本 40 只 × 320 根、并发梯度 1/4/8/16/32）：

    | 源 | 最佳吞吐 | 单票 p50 | 折算全市场 5544 只 | 字段 |
    |---|---|---|---|---|
    | **通达信 tdx** | **217 票/秒** | **28ms** | **26s** | 7/8（缺换手率） |
    | 新浪 sina | 17.6 票/秒 | 275ms | 315s | 8/8 |
    | 腾讯 tencent | 12.5 票/秒 | 202ms | 445s | 7/8（缺换手率） |
    | 证券宝 baostock | 0.57 票/秒 | 1675ms | 9726s | 8/8 |
    | 东财 eastmoney | 本机代理下取数失败 | — | — | — |

    通达信不只是快，**成交额还比原主源准**：腾讯日 K 的 `amount` 是 `close × volume` 合成值（库内实测 `amount/(close*volume)` 恒为 1.0000），通达信给的是真实成交额。价格对照库内 3000 个格点零偏差。缺的换手率由仓内 `turnover_repair` 按流通股本推算，本就不依赖源。北交所（`920xxx`）走 TDX `market=2`，漏了这条会静默缺 339 只——`tdx_daily.tdx_market()` 是唯一映射入口。

    **代价（如实记录）**：TDX 的 `vol` 是整数手，×100 后 `volume` 总是 100 的倍数；腾讯给的是精确股数。单根偏差 < 100 股（典型成交量上约 0.0001%）。换手率按 `amount/(close × 流通股本)` 算，不受影响；但若某个策略真的依赖股数末两位，得知道这件事。校验脚本 `scripts/verify_sync_written.py` 会把窗口外的旧腾讯行一并列出来，看到「成交量不符」先确认日期是否落在本轮重写窗口内。

    现价同序；**live 顶栏**另硬优先 sina/tencent 竞速，东财全表仅回落。东财全市场现价表（`stock_zh_a_spot_em`，~5500 行数 MB）由 `_load_spot_raw` 的 **4s 进程内 TTL 缓存**（加锁、只存一份）兜住：`fetch_spot` 与 `fetch_live_quotes` 共享同一份，board「live + persist」一轮只下载一次；TTL 与 `application/live_cache._QUOTE_TTL_SEC`（5s）同量级，失败与空表不进缓存、照旧抛 `AdapterError`。新浪/腾讯的 spot 与 live 分批由 `MarketAdapter._spot_via_symbols` / `_live_via_symbols` 以 **`_SPOT_FETCH_WORKERS=6` 路有界并发**发出（5500 个代码原本是新浪 14 批、腾讯 69 批全串行）：**单批失败仍只记 errors、不中断整轮**，结果按**批次序**而非完成序拼接（下游按先出现的行去重，完成序会让胜出者随网络抖动漂移）；`batch_size=None` 的腾讯线路先均分成 6 片，片内照旧由来源自行分批。路数取 6 而不是更大：`hq.sinajs.cn` / `qt.gtimg.cn` 对同 IP 突发并发敏感，十几路会被限流成 403 或截断报文，且 `market_session()` 每批新建连接、并发路数就是并发 TCP 数。`minute_bars`：**通达信优先**（`tdxpy` 历史分时，可跨历史日期；源只提供价格/成交量，输出 `datetime`/`close`/`volume`，不伪造 OHLC 或成交额），失败再东财（`eastmoney_minute` 直连 `push2his`/`push2delay`，指定日走 kline、近窗走 trends2；kline 成交量为「手」，均价按 `额/(量*100)`，trends 均价会做 100× 脏值回正），再新浪 `quotes.sina.cn`（近约 9 个交易日；均价按 `额/量`，100× 脏值同样回正）。所有分钟线都不写 `market.db`。不引入美股/加密/QVeris 等跨市场源。
- 资金流 `capital_flow` 是**双源**：`eastmoney`（akshare `stock_individual_fund_flow`，主源）→ `sina`（`sina.fetch_capital_flow`，`MoneyFlow.ssl_qsfx_zjlrqs`，回退）。注册表里新浪本就排在东财之后，回退顺序不靠额外配置。**新浪只有主力（`netamount`/`ratioamount`）与超大单（`r0_net`/`r0_ratio`）两组**，`large_/medium_/small_net_inflow` 与对应 `_net_pct` 六列**整列缺席**（不是 NaN 列，是列名根本不在表里；契约里它们 `required=False`，缺了不算失败）。上游要判断就用 `in frame.columns`，别把「新浪回退」当成「这票没有大单」——也不许用「主力 − 超大单」去凑一个假的大单。
  - 单位：东财给百分数（`涨跌幅`=2.45 表示 2.45%），新浪给小数（`changeratio`=0.0245）。同一列被两家源填，口径必须统一，于是 `Unit` 多了一个 `RATIO_TO_PERCENT`（小数 → 百分数，×100），只在契约里对新浪那三个键（`changeratio` / `ratioamount` / `r0_ratio`）声明；东财的中文候选列与它们的既有单位一个都没动。差 100 倍的口径错不会抛异常，只会让「主力净占比 > 5」这类阈值在换源那天静默失效。
  - `sina.fetch_capital_flow` 只把原始报文转成 DataFrame（原始键 `opendate`/`trade`/`changeratio`…，行序按 `opendate` 升序，与东财一致，调用方照旧 `tail(n)`），rename 与乘除全在 `pipeline.normalize` + 契约里。错误语义与 `fetch_hfq_factors` 一致：**请求失败 / 404 / 超时 / 报文变形抛 `SinaFetchError`**，只有新浪明确回空数组才是空表；`SinaAdapter` 包成 `AdapterError`，回退链才知道该继续往下试。`keep_unmapped=True` 会留下新浪自有列，其中 `turnover` 是**成交额（亿元）**，与日 K 的同名换手率列不是一回事。
- 复权因子（新浪，`sina.fetch_hfq_factors`）：**取数失败抛 `SinaFetchError`，不再吞成空表**。404 / 超时 / 报文变形与「这只票真的没有除权除息」必须分开——吞成空表时上层看到的是「无需复权」，前复权面板就按不复权价画，除权跳空被当成真跌。只有新浪明确回 `data` 为空才返回空表；有行却一行都解析不出来同样报错。`SinaSource.fetch_adjust_factors` 包成 `SourceError`，`SinaAdapter` 包成 `AdapterError`，于是 `fetch_adjust_factors_routed` 的错误里写的是真实原因而不是「空表」。
- 新源：写 fetcher + 契约 FieldSpec，注册到 lane；禁止在 adapter 手写 rename / 乘除 100。只有契约稳定、入库策略明确后才接入同步。
- HTTP：`infrastructure/http_client.py` — 行情域名默认直连 / 遇 `ProxyError` 直连重试；`market_get` 把 `timeout` 拆成「握手 ≤6s + 读取」，并对连接/超时类失败重试一次（幂等 GET 才可以），避免全市场同步时单点丢包整票失败；腾讯日 K 先打 `proxy.finance.qq.com` 的 fqkline，主 path 被 WAF/5xx 时换同 host 的 kline path；握手超时则跳过该 host 上的其余 path，直连 `web.ifzq.gtimg.cn` 用 2s 快败（该主机常被 WAF 拦成 501 或 SYN 黑洞）；近窗再失败才走 `data.gtimg.cn` flashdata。打包必须带上 `py_mini_racer` 原生库（`loci.spec` collect_all）
- 实时条：`/api/market/live-tape`（`infrastructure/live_tape.py`）**只回指数**——实盘账本下线后路由不再读 palace 持仓（`build_live_tape(use_cache=…)`，`build_market_router` 也不再接 `palace_db`）；`position_codes` 形参保留给托盘/调用方自带的自选清单。指数主展示为**今日涨跌 `pct`**。托盘悬停文案由包根导出的 `format_tray_title` 生成（**总长 ≤128**，对齐 Windows `NotifyIcon` tip，超长 pystray 会抛错并被误显示成「行情暂不可用」；CLI/桌面勿深掏 `live_tape`）。
- 大屏推流：`/api/market/stream/{quotes,signals,stats}`（`api/stream_router.py` + `application/live_hub.py`）。包根导出 `get_live_hub` / `LiveHub` / `LiveSnapshot` / `get_signal_engine` / `resolve_preset` / `MAX_PRESET_CODES`。**纯读，不写库**；频率预算见上文表格。
- HTTP 前缀见 `api/README.md`（现多由 `app.legacy.quant_router` 挂载）
- 禁忌：写 palace.db；在 adapter 外写死厂商 if-else；跨上下文深掏 `infrastructure`

## README 维护
改同步语义、适配器契约、公开导出或 store 拆分边界时必须更新本文。

## 相关测试
`tests/market/`（含 `test_duckdb_panel.py` 与可选 `test_polars_panel.py`：旁路只读且与经典面板对齐；显式基准见 `tests/benchmarks/polars_benchmark.py`；`test_http_client.py`：行情代理回退与握手重试；`test_daily_window.py`：日 K 增量近窗；`test_bounded_reads.py`：`load_panel` 范围护栏与热库窗口分批搬运的峰值内存对照；`test_live_hub.py`：单采集器 / N 订阅者只取一次数、周期预算、失败退避与自动停表、SSE 首帧形状；`test_realtime_signals.py`：去抖与 cooldown、`provisional`/`adjust=none` 口径、面板日缓存；`test_watchlist.py`：preset 排序与 400 只硬上限；`test_store_row_count.py`：行数缓存在追加/回填/重复写/新交易日/热库裁窗与重灌后仍等于真 COUNT，且缓存建好后稳态不再全表 COUNT）

报告未来交易日程：公开scheduled_trading_days读取已核验的交易所年度休市安排（当前2026）；它用于盘前/周末判定，不代表该日行情已入库。未知年度拒绝猜测，年度公告需更新。

交易所休市日历由盘外任务自动读取官方页面并原子保存全局快照，导出scheduled_trading_days/calendar_trading_day/refresh_exchange_calendar；盘中不联网，超过72小时未核验按不可用处理。
