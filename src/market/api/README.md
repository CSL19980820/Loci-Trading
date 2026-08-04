归属 URL：`/api/market/*` `/api/universe/*`。

挂载：`src.market.api.router.build_market_router`，由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

`GET /api/capabilities` 仍留在聚合层（system tag）。

`POST /api/market/sync`：同步执行并在完成后返回原有同步报告，状态码为 `200`（不是后台任务的 `202`）。同一 ASGI 进程内并发的 HTTP `/sync` 请求已有执行时返回 `409`，body 为 `{ "detail": "行情同步正在执行" }`；请求参数或无可同步标的返回 `422`，执行期其他异常仍为 `502`。

`GET/POST /api/market/bootstrap`：首次行情回填为后台任务，GET 轮询返回 `phase`、`done`、`total`、`percent`。证券列表刷新完成后立即设置 `total`，首个标的请求期间可能保持 `0%`，但会显示 `0/total` 和当前阶段；单标的完成或失败后递增。

`GET /api/market/board`：分页列表；可选 `industry`（所属行业模糊）、`sort=code|turnover_desc|turnover_asc|pct_desc|pct_asc`、`turnover_min`（百分数）、`codes`（逗号分隔最多 80，按码叠价）；`page_size` 允许 1–100；行内含 `industry` / `turnover`（小数）。`pct_*` 按库内最近日线相对前收排序（非全市场实时扫盘）；`live=true` 时对本页叠现价。
`GET /api/market/industries`：已入库行业名列表（刷新证券列表后才有半导体等）。

`GET /api/market/akshare/catalog`：从当前安装的 AkShare 运行时反射股票目录，返回版本、接口名、模块、签名、分类、来源、样例参数、按签名排序的 `parameters` 与执行模式；支持 `q`、`category` 和 `source` 筛选。参数项含 `name` / `required` / `kind` / `annotation` / `has_default` / `default` / `sample`。`param_docs` / `returns` 来自上游 docstring。响应另有 `sources: [{ "id", "count" }]`（始终基于未筛选目录）与 `batch_probe_max`。**不再返回** `enabled` / `enabled_names` / 上桌上限——目录即全部可用面。

`GET /api/market/akshare/sources`：只回 `akshare_version`、`sources`、`total`。

`GET /api/market/akshare/version`：本机安装版本；默认联网核对 PyPI（`fetch_latest=false` 可跳过）。返回 `installed` / `latest` / `update_available` / `error`。

`POST /api/market/akshare/catalog/probe-batch`：一键/分页批量探测。body `{ "names"?: string[], "offset"?: int, "limit"?: int }`；不传 `names` 则按目录全量续跑。返回本页 `results` 与 `next_offset` / `done`。不写库，但会消耗第三方源配额，要求浏览器会话或 Agent Bearer。

`POST /api/market/akshare/catalog/{name}/probe`：目录中的每个 `stock_*` 条目都可试跑，body 为 `{ "params": { ... } }`；目标始终从当前受控目录重新解析，不能传模块名、任意函数名或任意 Python 表达式。请求 body 最多 16 KiB，参数 JSON 最多 4 层、128 个值；未知函数、未知参数、不匹配签名或超出上述边界返回 422。按已发现签名归一基础 `int` / `float` / `bool` 值，分页和行数参数仅允许 1-5，字符串最多 128 字符，`start_date/end_date` 最多 31 天。项目默认单 Uvicorn 进程，运行受 8 秒、2 个并发 worker 预算约束；外部多 worker 部署需按 worker 数协调总并发。容量耗尽返回 429（`Retry-After: 2`），worker 启动失败返回 503；上游数据失败仍以受控 `error` 摘要返回，不写 `market.db`。结果除 `columns`（原样列名，保持向后兼容）外还给 `columns_detail: [{ "raw", "cn", "en" }]`，中英名来自 `domain/column_glossary.py`，认不出的一侧留空字符串，不猜译；两者共用同一个 40 列上限，失败分支同样返回 `columns_detail: []`。该端点同样要求浏览器会话或 Agent Bearer。

`GET /api/market/health`：行情仓体检。可选 `date`、`include_ok`（保留通过项供扫描回放）。响应含 `blocked`/`findings`/`score`/`grade`/`repair_plan`/`catalog`；门禁认 `blocked`，印鉴分仅展示。

`POST /api/market/repair/turnover`：回填/修复换手率（可选 `since=YYYY-MM-DD`）；写鉴权；不重拉 OHLC。带 `since` 时会把手单位成交量×100、清空 spot/turnover>100% 脏行再 as-of 回填。体检 remediation `repair_turnover` 走此接口。

历史日线 `quotes_daily` 字段：日期、OHLC、成交量、成交额、流通股本、换手率（小数）、来源、拉取时间。

`GET /api/market/quotes/{code}`：日线序列；`limit` 默认 60（`ge=20`），从末尾截最近 N 根；响应含 `total_rows`、`board` / `board_label`（主板等）、`industry`（所属行业）。

`GET /api/market/minute/{code}`：实时分钟线（**不写** `market.db`）；`period`=`1|5|15|30|60`；可选 `date=YYYY-MM-DD` 只取该交易日；`days` 在未指定 `date` 时控制回溯天数（默认 1）；`adjust`=`none|qfq|hfq`（默认 `none`）。默认路由顺序：通达信 → 东财 → 新浪。各源协议**都不提供前复权分时**，只给成交价；`adjust≠none` 时服务端用本地 `adjust_factors` 把价格列（含 `avg_price`）与 `prev_close` 缩放到与日 K 同口径（前复权锚定该票最新交易日因子）。通达信成功时 `bars` 仍只含源可证明的 `datetime` / `close` / `volume`（不补造 OHLC/成交额），`source=tdx`；东财/新浪另含 OHLC / `amount` / `avg_price`。
