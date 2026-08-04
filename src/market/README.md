# 行情（market）

## 职责
标的、日 K、同步编排、数据线路适配器、股票池。

股票池默认包含主板、创业板和科创板并剔除 ST；高级筛选可显式加入北交所，并支持行业、代码包含/排除。默认值与可选能力必须分开描述，不能把“默认不选”实现成领域层永久禁止。

## 边界
只写 market.db；禁止写 palace.db。

## 关键入口
`MarketStore` / `sync_quotes`；HTTP：`/api/market/*` `/api/universe/*`（现由 app.legacy.quant_router 挂载）；CLI：`python -m cli.market`

## 如何扩展
新行情源：在 infrastructure/adapters 实现并注册到 lane。

## 存储层拆分（infrastructure）
对外符号不变：`from src.market import MarketStore, normalize_code, …` 与
`from src.market.infrastructure.store import MarketStore, normalize_code, …`。
内部按职责拆文件（均 ≤600 行）：

| 文件 | 内容 |
|---|---|
| `store_codes.py` | `MarketError` / `normalize_code` / `guess_market` / `to_sina_symbol` |
| `store_schema.py` | DDL、字段常量、`DEFAULT_DB` |
| `store_rw.py` | 写入与基础读取 mixin；`upsert_quote_bars` / `set_watermarks` 供当日 spot 单事务批量落库（一次 DataFrame 归一，按 code+date 去重，禁止逐票建表）；`latest_bars` 走日历近窗+索引，`coverage` 走日历/证券表+绑定 `quotes_revision` 的行数 meta 缓存（行情写入失效，旧格式自动重算，避免千万行全表 COUNT/窗口扫描） |
| `store_board_page.py` | 行情台分页：所属行业过滤、换手率排序/下限 |
| `store_panel.py` | 全市场面板与 `_consolidate` |
| `duckdb_panel.py` | 可选 DuckDB 只读旁路（`LOCI_MARKET_DUCKDB=1`；失败回退 pandas） |
| `store.py` | `MarketStore` 组合 + 连接生命周期 + re-export |

## 给 Agent 的用法
- 仓：`from src.market import MarketStore, sync_quotes, apply_today_spot`
- 手动同步：`POST /api/market/sync` 在完成后返回报告（`200`）；同一 ASGI 进程内并发的第二个 HTTP `/sync` 请求返回 `409`，避免重复并发写入 `market.db`。多 worker、调度器或 bootstrap 触发的并发互斥不在此接口的进程内闸门范围内。
- bootstrap：证券列表刷新完成后立即回报行情总数；首只行情请求未完成时进度仍可能是 `0%`，但会显示 `0/total`，首个标的完成或失败后才递增，失败会进入报告而不会无限等待。
- 数据快照：`store.data_snapshot()` 返回 `quotes / adjust_factors / instruments` 三段水位与 `market_revision`；顶层 `rows/last_date/fetched_at` 仍代表日 K 摘要，供回测/选股结果复现
- 会话闸门：`build_session_status`（`/api/market/session` / bootstrap 附带）；补数时返回 `coverage_last_date`、`backfill_from`/`backfill_to`（将补交易日区间）与 `lag_trading_days`；**15:00 前** `expected_last_date` 不含今日（不催补未定稿日线）
- 健康门禁：`guard_market_health` / `check_market_health`；`to_dict` 含 `score`/`grade`（印鉴分，仅展示）、`repair_plan`（一键修复去重：bootstrap/sync/sync_factors/repair_turnover）、`catalog`（扫描目录）；`include_ok=True` 保留通过项供体检页回放。finding 的 `remediation` 供单项修复。门禁仍认 `blocked`。`staleness` 看仓内最新日相对墙钟是否过旧，以及是否覆盖选股基准日；**故意选历史基准日做复盘不会被当成过期**。
- 换手率修补：`backfill_missing_turnover` / `load_shares_asof` / `repair_inflated_turnover`（`infrastructure/turnover_repair.py`）。当日 spot 用「严格早于交易日」的最近流通股本估换手；反推股本优先 `amount/(close*turnover)`，避免东财「手」与新浪「股」混用把换手撑到上千%。`upsert_quotes` 对股本/换手 `COALESCE` 禁止 NULL 抹旧值；`apply_today_spot` 经 `upsert_quote_bars` **单事务批量写入**（避免逐票 commit 写到一半覆盖率只剩个位数）。体检「回填换手率」→ `POST /api/market/repair/turnover`（带 `since` 时先清 spot/离谱换手并把手量×100）。
- 健康门禁当日覆盖率：目标日=今天且不足时提示「盘中 spot 未写完」（历史同步不含当日），勿与 hist 未跑完混淆。
- 线路：`fetch_daily_routed` / `fetch_live_quotes_routed` / `fetch_instruments_routed` / `fetch_minute_routed`（可选 `trade_date`，**不写库**） / `fetch_capital_flow_routed` / `enabled_adapter_ids` / `lane_route_policy` / `ALL_LANES`。每个 lane 可为 `auto`，或选择一个手动 provider；手动模式默认不回退，只有显式 `fallback=true` 才按后续优先级降级。手选日线在首选源成功时绝不被更快的回退源抢占。策略保存在本机 `loci.config.json` 的 `lane_routes`，变更会清该 lane 的粘性赢家，不写入 `market.db`。启停是两级，都记在 `loci.config.json` 的 `lane_providers`：`{"sina": {"enabled": true, "lanes": {"hist_daily": false}}}` —— `enabled` 是源总开关（关掉这家全线停用），`lanes` 是逐 lane 覆盖（只停那一条）。读取用 `lane_provider_enabled` / `provider_master_enabled` / `provider_disabled_lanes`；缺记录视为启用。`enabled_adapter_ids(lane, config=...)` 可复用已读到的 config，避免一次请求里反复读盘。必需 lane 被关空**不在这一层拦**（复权因子、证券列表都是单源，拦了就永远关不掉），由界面红字提醒。`list_catalog()` / `AdapterMeta.base_url` 另给每家来源一个站点地址，仅供人核对来源、不参与请求；交易所列表横跨三家交易所，没有单一域名，故留空。
- HTTP：`GET /api/market/minute/{code}` 实时分钟线（不落库；见 `api/README.md`）。源（含通达信）无前复权分时；`adjust=qfq|hfq` 时用本地 `adjust_factors` 缩放价格与 `prev_close`，与日 K 复权对齐。
- 列名中英对照：`domain/column_glossary.py` 的 `CN_TO_EN` 是唯一真相（纯标准库），`gloss_column` 给单个列名标 `{raw, cn, en}`，认不出的一侧留空、不猜译；东财适配器的四张 rename 表用 `select_columns` 从中挑子集，只有资金流的 `涨跌幅 → pct_chg` 因与现价表的 `pct` 撞名而就地覆盖。新增列名先加到这里。
- AkShare 目录：`infrastructure/akshare_catalog.py` 只发现本机已安装版本中来自 `akshare.*` 的 `stock_*` callable；目录项记录模块、签名、上游来源、参数描述、样例参数和执行模式，另含从完整 docstring 解析的 `param_docs` / `returns`（解析与来源/类目推断在 `infrastructure/akshare_catalog_meta.py`）。试跑结果在 `columns` 之外附 `columns_detail` 中英对照。目录内每个条目均可试跑，`status=available|needs_parameters` 只表示是否已具备必填参数，`execution_mode` 才表示是否已接入业务编排。试跑按签名归一 `int` / `float` / `bool` 参数，分页限制为 1-5、行数限制为 1-5、字符串至多 128 字符、日期窗口至多 31 天；请求 JSON 限制 16 KiB、4 层、128 个值。生产调用受 8 秒/2 并发预算约束，固定 `spawn` 子进程执行，超时会确认 `terminate/kill/join` 后才释放槽位；容量耗尽返回 429 并附 `Retry-After`，启动失败返回 503。`cli.serve` 默认单 Uvicorn 进程；若外部改为多 worker，必须另行按 worker 数协调总并发。结果和 IPC 摘要也限制字段、嵌套与字节数，不写库，它不是同步管道注册器。`probe_stock_capability(..., max_sample_rows=N)` 只放宽样本行数（上限 `MAX_MCP_SAMPLE_ROWS=50`，给 MCP 工具调用用），超时、并发与参数校验一律不变。
- AkShare 目录辅助：`infrastructure/akshare_tools.py` —— **无上桌/启用名单**。提供 `catalog_entries` / `clear_catalog_cache`、`probe_stock_capabilities_batch`（分页一键全测，单页上限 `MAX_BATCH_PROBE`）、`check_akshare_version`（本机 vs PyPI）。内置 MCP 只挂单一工具 `akshare_call`（按名调用目录内任意 `stock_*`），避免把四百多个接口塞进工具清单。
  - 适配器默认顺序：日线/现价 `eastmoney`（AkShare）优先，`sina` / `tencent` 直连作补充备源（新浪日 K 仍不经 akshare，避免 V8 崩溃）。`minute_bars`：**通达信优先**（`tdxpy` 历史分时，可跨历史日期；源只提供价格/成交量，输出 `datetime`/`close`/`volume`，不伪造 OHLC 或成交额），失败再东财（`eastmoney_minute` 直连 `push2his`/`push2delay`，指定日走 kline、近窗走 trends2；kline 成交量为「手」，均价按 `额/(量*100)`，trends 均价会做 100× 脏值回正），再新浪 `quotes.sina.cn`（近约 9 个交易日；均价按 `额/量`，100× 脏值同样回正）。所有分钟线都不写 `market.db`。
- 新源：在 `infrastructure/adapters` 实现并注册 lane；只有适配器契约稳定、字段映射和入库策略明确后才接入同步。
- HTTP：`infrastructure/http_client.py` — 行情域名默认直连 / 遇 `ProxyError` 直连重试；打包必须带上 `py_mini_racer` 原生库（`loci.spec` collect_all）
- 实时条：`/api/market/live-tape`（`infrastructure/live_tape.py`）指数与持仓主展示均为**今日涨跌 `pct`**；相对成本 `pnl_pct` 仅作旁路字段。托盘悬停文案由 `format_tray_title` 生成（仓置顶、指数两列、持仓按今日涨跌排序，▲▼ 代色；**总长 ≤128**，对齐 Windows `NotifyIcon` tip，超长 pystray 会抛错并被误显示成「行情暂不可用」）；仓位汇总按市值加权今日涨跌。`fetch_live_quotes_routed` **先竞速 sina/tencent**（按代码直连），东财全市场现价仅作回落——避免冷启动 SSL/全表卡超时。非法持仓/自选代码会被单条隔离；实时源全部失败时响应 `error` 会保留故障原因，避免把空行情伪装成正常行情。桌面托盘左键打开 `/peek` 小窗（可四边磁吸、闲置缩成应用图标半探出）；菜单「打开工作台」唤回主窗。
- HTTP 前缀见 `api/README.md`（现多由 `app.legacy.quant_router` 挂载）
- 禁忌：写 palace.db；在 adapter 外写死厂商 if-else；跨上下文深掏 `infrastructure`

## README 维护
改同步语义、适配器契约、公开导出或 store 拆分边界时必须更新本文。

## 相关测试
`tests/market/`（含 `test_duckdb_panel.py`：未装 duckdb 则 skip；装了则同夹具经典 vs `LOCI_MARKET_DUCKDB=1` 行数/关键价对齐；`test_http_client.py`：行情代理回退）
