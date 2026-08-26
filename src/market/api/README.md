归属 URL：`/api/market/*` `/api/universe/*`。

挂载：`src.market.api.router.build_market_router`（含 `board_router.register_board_routes`、`akshare` catalog、`quality_router`），由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

**读热库 / 写全量**：`coverage` / `session` / `board`（列表与本地 bar）/ `quotes` / `search` / `industries` / `minute`（本地名与 `adjust_factors`）走 `market_hot_store`；`bootstrap` GET/POST、`universe/*`、board `live&persist=true` 后台 spot 落盘（写鉴权）、以及 `quality_router`（sync/health/repair）仍走全量 `market_store`。分钟线外网拉取本身不写库。

`GET /api/capabilities` 仍留在聚合层（system tag）。
`POST /api/market/sync`：同步执行并在完成后返回原有同步报告，状态码为 `200`（不是后台任务的 `202`）。**并发闸门只有一处**——`execute_sync` 自身占 `ops.market_gate` 的 sync 写槽，HTTP / bootstrap / CLI / 调度四个入口共用同一把；路由层不再叠一层进程锁，因此**不再返回 `409`**。已有同步在跑时闸门判 skipped，本接口返回 `200`，body 为 `{ "ok": true, "status": "skipped", "skipped": true, "detail": "已有同步在跑，本次未重复启动", "reason": "<闸门原文>" }`——两次请求写的是同一批当日行情，排队不是冲突，调用方按「本次没启动、下轮再来」处理即可，不要当错误弹红。请求参数非法或无可同步标的仍返回 `422`，执行期其他异常仍为 `502`。

`GET/POST /api/market/bootstrap`：首次行情回填为后台任务，GET 轮询返回 `phase`、`done`、`total`、`percent`。证券列表刷新完成后立即设置 `total`，首个标的请求期间可能保持 `0%`，但会显示 `0/total` 和当前阶段；单标的完成或失败后递增。

`GET /api/market/board`：分页列表；可选 `industry`（所属行业模糊）、`sort=code|turnover_desc|turnover_asc|pct_desc|pct_asc`、`turnover_min`（百分数）、`codes`（逗号分隔最多 80，按码叠价）；`page_size` 允许 1–100；行内含 `industry` / `turnover`（小数）。`pct_*` 按库内最近日线相对前收排序（非全市场实时扫盘）；`live=true` 时对本页叠现价。`persist=true`（需 `live=true` 且写鉴权）才后台落盘当日 spot 并 `mirror_recent_to_hot`；默认只读轮询不写库。
`GET /api/market/industries`：已入库行业名列表（刷新证券列表后才有半导体等）。

`GET /api/market/akshare/catalog`：从当前安装的 AkShare 运行时反射股票目录，返回版本、接口名、模块、签名、分类、来源、样例参数、按签名排序的 `parameters` 与执行模式；支持 `q`、`category` 和 `source` 筛选。参数项含 `name` / `required` / `kind` / `annotation` / `has_default` / `default` / `sample`。`param_docs` / `returns` 来自上游 docstring。响应另有 `sources: [{ "id", "count" }]`（始终基于未筛选目录）与 `batch_probe_max`。**不再返回** `enabled` / `enabled_names` / 上桌上限——目录即全部可用面。

`GET /api/market/akshare/sources`：只回 `akshare_version`、`sources`、`total`。

`GET /api/market/akshare/version`：本机安装版本；默认联网核对 PyPI（`fetch_latest=false` 可跳过）。返回 `installed` / `latest` / `update_available` / `error`。

`POST /api/market/akshare/catalog/probe-batch`：一键/分页批量探测。body `{ "names"?: string[], "offset"?: int, "limit"?: int }`；不传 `names` 则按目录全量续跑。返回本页 `results` 与 `next_offset` / `done`。不写库，但会消耗第三方源配额，要求浏览器会话或 Agent Bearer。

`POST /api/market/akshare/catalog/{name}/probe`：目录中的每个 `stock_*` 条目都可试跑，body 为 `{ "params": { ... } }`；目标始终从当前受控目录重新解析，不能传模块名、任意函数名或任意 Python 表达式。请求 body 最多 16 KiB，参数 JSON 最多 4 层、128 个值；未知函数、未知参数、不匹配签名或超出上述边界返回 422。按已发现签名归一基础 `int` / `float` / `bool` 值，分页和行数参数仅允许 1-5，字符串最多 128 字符，`start_date/end_date` 最多 31 天。项目默认单 Uvicorn 进程，运行受 8 秒、2 个并发 worker 预算约束；外部多 worker 部署需按 worker 数协调总并发。容量耗尽返回 429（`Retry-After: 2`），worker 启动失败返回 503；上游数据失败仍以受控 `error` 摘要返回，不写 `market.db`。结果除 `columns`（原样列名，保持向后兼容）外还给 `columns_detail: [{ "raw", "cn", "en" }]`，中英名来自 `domain/column_glossary.py`，认不出的一侧留空字符串，不猜译；两者共用同一个 40 列上限，失败分支同样返回 `columns_detail: []`。该端点同样要求浏览器会话或 Agent Bearer。

`GET /api/market/health`：行情仓体检。可选 `date`、`include_ok`（保留通过项供扫描回放）、`include_network`（深度扫描：探测日 K/现价/复权/证券列表源连通，选股门禁勿开）。响应含 `blocked`/`findings`/`score`/`grade`/`repair_plan`/`catalog`/`include_network`；门禁认 `blocked`，体检分仅展示。目录含仓内质量 + 线路关空/补数意图/运行时依赖/schema/库体积 + 回执坏 OHLC 比/证据缺口（近窗，默认 20 交易日）/竞速回退/托管 sync Job 时效；网络连通项仅在 `include_network=true` 时进入 catalog 与 findings。

`POST /api/market/repair/turnover`：回填/修复换手率（可选 `since=YYYY-MM-DD`）；写鉴权；不重拉 OHLC。带 `since` 时会校正手单位成交量、去掉多余 ×100、清空 spot/turnover>50% 脏行再 as-of 回填。读路径与榜单排序优先 `amount/(close*shares)`。体检 remediation `repair_turnover` 走此接口。

历史日线 `quotes_daily` 字段：日期、OHLC、成交量、成交额、流通股本、换手率（小数）、来源、拉取时间。

`GET /api/market/quotes/{code}`：日线序列；`limit` 默认 60（`ge=20`），从末尾截最近 N 根；响应含 `total_rows`、`board` / `board_label`（主板等）、`industry`（所属行业）。

`GET /api/market/minute/{code}`：实时分钟线（**不写** `market.db`）；`period`=`1|5|15|30|60`；可选 `date=YYYY-MM-DD` 只取该交易日；`days` 在未指定 `date` 时控制回溯天数（默认 1）；`adjust`=`none|qfq|hfq`（默认 `none`）。默认路由顺序：通达信 → 东财 → 新浪。各源协议**都不提供前复权分时**，只给成交价；`adjust≠none` 时服务端用本地 `adjust_factors` 把价格列（含 `avg_price`）与 `prev_close` 缩放到与日 K 同口径（前复权锚定该票最新交易日因子）。通达信成功时 `bars` 仍只含源可证明的 `datetime` / `close` / `volume`（不补造 OHLC/成交额），`source=tdx`；东财/新浪另含 OHLC / `amount` / `avg_price`。
