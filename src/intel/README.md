# 情报（intel）

## 职责
MCP/外部情报接入与限流；补本地行情仓算不出的数据。

## 边界
配置 mcp.json；大批量量价仍走 market。

## 关键入口
`McpClient` / registry / builtin_market_mcp；HTTP：`/api/mcp/*`

## 如何扩展
新 MCP server：写入 mcp.json 或 registry API。


## 给 Agent 的用法
- MCP：`from src.intel import McpClient, McpTool, build_client, collect_tools, list_effective_mcp_servers`
- 配置读写：`load_mcp_json_raw` / `upsert_mcp_server_json` / `get_mcp_server_from_json` / `list_mcp_servers_from_json`；文件 `data/mcp.json`
- 带配额调用：`call_mcp_tool(tool, args, pool="structured"|"skill", cache=…)`；已有 `McpClient` 时用 `guarded_client_call`。入口统一 `clamp_mcp_arguments`（`application/arg_clamp.py`）裁扫池 `limit/codes/days`。配额耗尽抛 `McpQuotaError`，余量查 `quota_snapshot()`。**裁剪上限的权威来源是服务端 schema**：`limit ≤ 200`、`maxRows ≤ 150`、`days ≤ 150`（`maxRows` 与 `days` 同为 150，别再拿 `limit` 的 200 兜——比 schema 大的值会被服务端整条拒掉，裁剪器反倒成了废调用的来源）
- **裁剪要留痕**：`clamp_mcp_arguments_with_notes` 额外回报 `["codes:120->50", …]`，`call_mcp_tool` / `guarded_client_call` 把它放进 payload 的 `clamped`。静默截断会让调用方把「只扫了前 50 只」当成「全市场都没有」，新调用方请透传这条警告
- **模型只读 `text`**：Agent 环只把工具结果的 `text` 交给模型，`clamped` / `truncated` 这类旁路字段它看不见。`guarded_client_call` 在裁剪或正文截断时会往 `text` 末尾追加 `[取数范围提示] …`，明说「不是全量、别据此计数或断言没有」。新增 AI 可见的工具出口请照此办理
- **截断要留痕**：`McpClient` 对超长正文的截断标记透传为 payload 的 `truncated`。正文被截断后 JSON 必然解析不出结构化段，消费方（如 tape 的悟道 provider）据此判「解析失败」，**不得**当成「查到了但没数据」
- **缓存 key 分两层：存储 key 与复用 key**。`cache=True` 必须同时传 `market_store`，否则整段缓存是空转（每次真调、真扣配额）。**存储 key** = `hash(tool, 裁剪后的 arguments)` + `trade_date_today()`，一变体一行，**字节序列不许动**——`market/infrastructure/tape/cache.py` 有一份同算法副本，两边算不出同一个 digest，tape provider 就读不到 `call_mcp_tool` 写的行；改它等于让全库既有快照一次性失效（= 一轮真调用、真扣配额）。**复用 key**（`intel_cache.cache_identity_key`）只含「身份参数」：哪一天、哪个工具、哪批标的。`limit` / `maxRows` / `topN` / `includeBoomReason` / `detailLevel` 这些只决定「回多少行、回多细」的参数**不进复用 key**，`format` 这种纯传输编码既不进 key 也不校验。读侧先按存储 key 精确命中，未命中再回扫同交易日同工具的行，找一份「复用 key 相同 + 覆盖度不小于本次要求」的兑现（命中时载荷上补 `cache_reused_arguments`）。缓存读写失败一律降级为「未命中 / 已忽略」，绝不吞掉已经扣过配额的成功结果。**key 只锁到「日」，不锁到「收盘没收盘」**：10:03 抓的半截当日 bar 与 15:40 抓的收盘 bar 落在同一行，所以 `call_mcp_tool` 另外把抓取时点的收盘态写进载荷（`session_state=live|settled`），收盘后**不复用**盘中抓的那份（回源一次、用定稿覆盖），只拦「已收盘 ← 盘中数据」这一向
- **为什么复用只发生在读侧，不合并存储**：实测 `theme_intraday_capital` 一天产生 4 个互不复用的 key（配方三档 `limit=80/60/100` + tape lane 的 `limit=20`），根因是上游参数在各子系统各拼一份。**但直接把 `limit` 踢出存储 key 会更糟**：宽窄两个入口会互相顶掉对方的行（tape 的 20 覆盖不了配方的 80，80 又覆盖不了收盘的 100），5 分钟一轮的盯盘和 15 分钟一轮的配方来回作废彼此的缓存，真调次数比现在还多。所以行照旧一变体一行，只在读侧做**覆盖度兑现**：大的 `limit` 覆盖小的、`True` 覆盖 `False`、`detailed` 覆盖 `standard`；缺席的 `limit` 是「服务端默认条数」，不可比，只与缺席互相兑现。宁可多回几行，也不能把 limit=60 的半张榜当成 limit=100 的全榜发下去
- **剩下的收口方向**（本轮没做，改动面在允许范围外）：① 各调用点仍各写一份参数，真正的单一真相源应该是「一个工具一个参数构造器」，像 `application/wudao_keys.py` 收敛日期键那样把 `daily_recipe` 三档与 tape lane 的 `limit`/`includeBoomReason` 收进一张表；② `market/infrastructure/tape/cache.py::_args_hash` 是 `intel_cache._args_hash` 的复制品，应当由 intel 包根导出后由 tape 引用，删掉副本；③ tape 侧目前只能做精确 key 复用（`src.intel.infrastructure` 是 import-linter 的 protected 模块，market 不能深掏），要让 `CachedTapeProvider` 也享受覆盖度复用，得先把 `cache_identity_key` / `coverage_covers` 从 `src/intel/__init__.py` 导出
- **缓存与收盘的关系**：收盘态由 `ops/application/session_clock.py` 判定（复用，不另写一份交易时段判断）；注意 `phase="closed"` 还含 11:30–13:00 午休，午休的当日数据只是暂停变动、不是定稿，所以还要看钟点是否 ≥15:00。盘中 TTL 被压到 `_INTRADAY_CACHE_MAX_AGE_MINUTES=10` 分钟（调用方给更长也不认），**收盘后才允许长 TTL**（`情报·盘后` 的 120 分钟就是给这一档的）。判定不出来（时钟不可用、时间戳畸形）一律按盘中处理：宁可多打一次，也不把半截数据钉成权威收盘值。没有 `session_state` 的旧行/别的写入方（tape 的 `write_tape_cache`）退回看 `cache_fetched_at`。这是全仓唯一一处 intel → `src.ops.application` 的深引用：`session_clock` 是只依赖标准库的叶子模块、包根 `src.ops` 没导出它，而「再抄一份交易时段判定」比这条依赖更糟（两份判定迟早对不上）；引用点是函数内惰性 import，import 期不成环，`import-linter` 12 条契约全过
- **托管 Job 的 TTL 必须小于采集间隔**：`情报·盘中` 的 cron 是 `*/15`，TTL ≥ 15 分钟时下一次 run 会整轮命中缓存、一次真调用都不发，Job 却记绿——一半的 run 是空转，数据还是上一轮的。默认已改成 12 分钟并对盘中档强制钳制（`jobs/intel_fetch.py`）；实际生效值是它与上面 10 分钟盘中上限的较小者
- **废调用不扣配额**：`is_error` 分两类。**参数被服务端直接拒**（`INVALID_ARGUMENTS` / 未知参数 / 缺必填 → 服务端根本没执行）不记账，payload 里 `quota_charged=false` 并打 WARNING；**能执行到业务错误**（今日无数据、该股停牌）照扣，因为供应商那边真算了一次。分不出来的一律按「扣」处理——本地计数低于服务端计数会让我们以为还有余量、实际已被限流，比多扣几次更难查。识别特征表在 `application/fetch.py::_NOT_EXECUTED_ERROR_MARKERS`，`call_mcp_tool` 与 `guarded_client_call` 共用同一条口径
- **失败也要进缓存（负缓存 / 冷却）**：`is_error` 的结果原来**从不入缓存**，而业务错误是照扣配额的——于是每一次重试都真调一次、真扣一次额，一天几十轮全花在一个已知打不通的调用上。现在失败结果写进独立 key 命名空间（`args_hash` 里带 `kind=error`），冷却期内直接兑现那份失败，**不进配额闸门、不出网**，载荷带 `error_cached=true` / `retry_after_minutes` / `quota_charged=false`。冷却分档（`application/fetch.py`）：参数被拒 60 分钟（同一份参数必然再被拒，与「数据还没出来」无关，本来也不扣额，省的是延迟和白跑的建连）、盘中业务错误 5 分钟（可能只是这一刻还没出数，9:25 问涨停池）、收盘后业务错误 30 分钟（当日结论基本定稿）。三个逃生口：`cache=False` 的调用永不读负缓存；成功写入立刻清掉同 key 的冷却行（不留惩罚期，与 `market/infrastructure/em_industry.py` 的失败冷却同一条口径）；负缓存**不会**顶掉同参数上一份还能用的成功快照——「这次调用失败了」和「上午那份数据还在」是两件事。`list_latest_snapshots` 也会跳过失败载荷，盘面摘要要的是事实、不是一条错误正文
- **缓存自报时点**：`read_cached_snapshot` 命中时在 payload 上补 `cache_fetched_at`（ISO）与 `cache_age_minutes`。`trade_date` 只锁到「日」，盘中 14:50 拿到 09:31 的快照如果不标时刻就是拿早盘冒充实时；消费方（含 tape provenance、模型正文）请把它一起带出去。`cache_age_minutes()` 对旧库遗留的无时区 `fetched_at` 返回 `None`，此时按「不可信、回源」处理，**不会**把 `TypeError` 抛给调用方
- **统一软降级**：`call_mcp_tool` 对悟道在缓存未命中且 `wudao_availability().available=false` 时返回 `{is_error, unavailable, unavailable_reason}`，**不抛错、不扣配额**；业务侧仍应用 `wudao_availability()` 做提前跳过（`intel_fetch` / `skill_watch` / 纸面闸门）
- 悟道常驻：`BUILTIN_WUDAO_NAME` / `ensure_resident_wudao()` / `resident_wudao_record()` / `wudao_hist_daily_primary()`
- 悟道是否可用：`wudao_availability()` → `{available, reason}`（未配 Key / 旧密文已清需重录 / 已过期 / 已停用 / 未同步工具都算不可用）
- MCP API Key **明文**写在 `mcp.json` 的 `token` 字段；LLM 供应商 Key **明文**写在 `ops.db` 的 `encrypted_key` 列（列名历史遗留）。**无主密钥**。启动时清掉旧 `encrypted_token` / 非明文密文残留；需重录的请在运维页补 Key。
- 缺少 `data/mcp.json` 或没有悟道条目是正常状态：数据目录初始化可创建 `{"mcpServers": {}}` 空配置，列表返回合成的未配置名片；启动、Agent 工具汇总和 `GET /api/mcp` **不会注入悟道占位条目**，只有用户保存悟道配置时才写入该条目。
- 悟道 `kline` 解析：`kline_payload_to_frame(payload)` → 标准日线 DataFrame；批量 `codes` 查询用 `kline_payload_frames(payload)` → `{code: DataFrame}`（空/解析失败给空表，报错由调用方决定）。行情适配器与战法监测共用，勿各自重写
- **缺价的 K 线行整行丢弃，不补 0**：上游改名/缺字段时补 0 会造出一根 0 元 K 线，还能通过列契约校验（拦截只在 store 的 `partition_valid_ohlc_rows`，隔了两层）。现在四价缺一、非正数或不可解析（`"--"`）即丢该行并打 WARNING；成交量/额缺失仍记 0（真停牌就是 0）。因此「解析出来行数变少」是正常的降级信号，不要理解成当天只有这几根
- 内置行情工具见 `builtin_market_mcp`（经包根 registry 导出）；日线、分钟线、资金流都只经 `src.market` 的公开 routed API 取数，必须尊重 lane 启停与用户的 auto/manual/fallback 策略，返回实际 source。
- **内置清单跟着数据源启停走**：`list_builtin_tools()` 先按 `_LANE_BY_TOOL` 用 `enabled_adapter_ids(lane)` 过滤（该 lane 没有可用源就不给模型这个工具），再追加已上桌的 AkShare 接口。`instruments_search`（本地热读库 `market_hot.db` 的 `page_instruments`；`instruments` 表全量镜像，失败再走远程 `fetch_instruments_routed`）与 `lanes_catalog`（元信息）不依赖线路，始终在清单里。
- **UI 全量目录**：`builtin_server_record()["tools_catalog"]` 含全部内置行情工具（`group=lane`，无源标 `available=false`）+ 已上桌 AkShare（`group=akshare`）。运维 MCP 详情读这个字段；`tools` 仍只给 AI/兼容用的生效清单，勿把 catalog 塞进 `collect_tools`。
- **连通性探测**：`probe_mcp(name)` / `POST /api/mcp/{name}/probe` 只做握手、工具发现与清单刷新，绝不执行第三方工具；请求体不接受 `tool` 或 `arguments`。
- **外部 HTTP MCP**：默认直连公网 HTTPS且 `trust_env=False`（不读恶意 `HTTPS_PROXY`）；本地 HTTP 仅在 `PALACE_MCP_LOOPBACK_HTTP_HOSTS` 明确列出回环主机时可用。主机名经 Clash/Surge Fake-IP 解析到 `198.18.0.0/15` 时：URL 放行（禁止字面量），且 `needs_system_proxy` 打开 `trust_env` 走系统代理出站——否则直连 198.18 必挂。首次发现/调用前 `initialize` 并复用会话 ID；`mcp.json` 自定义 `headers` 原样传递。工具分页拒绝重复游标和超过 50 页；响应/schema/参数有上限；刷新不可用时 `503`，整服探测 `ok=false`。
- **悟道 / stock.quicktiny.cn**：唯一 MCP 名 `wudao`（旧键 `wudao-a-stock` 启动时迁并），URL `https://stock.quicktiny.cn/api/mcp`。HTTP 握手对齐 Hermes：`protocolVersion=2025-03-26` + `Mcp-Protocol-Version` 头；Clash Fake-IP 时读系统代理。数据源目录只露一张「悟道」牌；日 K 优先走同一 MCP 的 `kline`。运维 MCP 页配 Key；未配/过期 `is_usable=false`。
- **配额分池按「谁发起的」**：默认日总 5000、structured 3000（**日常情报配方**，即托管 `intel_fetch` 三档）、skill 2000（Agent/Skill 临机 + **战法盯盘 / tape lane**）。环境变量 `LOCI_MCP_QUOTA_*` / `LOCI_MCP_RATE_PER_MIN` 可覆盖；`GET /api/mcp/quota` 查剩余。表 `mcp_quota` DDL 归属 ops.db（`OpsStore` / `store_quota`），本模块经 `OpsStore` 读写计数，**禁止**裸连 ops.db CREATE。
  - **池名不再硬编码在调用点**：`ops/application/jobs/intel_fetch.py` 认 Job 配置键 `pool`（`resolve_pool`，默认 structured），`market/infrastructure/tape/wudao_provider.py` 认 `TapeRequest.context["quota_pool"]`（`tape_quota_pool`，默认 skill）。写错的池名忽略并回落默认池 + WARNING——记到一个不存在的池，等于这批调用不受任何预算约束。
  - **tape 为什么归 skill**：那条 lane 服务的是盯盘（`skill_watch` 每 5 分钟一轮、一轮 3~8 条 lane、tape 缓存只有 5 分钟），单个盯盘战法就是几百次/日。压在 structured 上会把情报配方挤爆，而 skill 池常年闲置。日 K 适配器（`market/infrastructure/adapters/wudao_adapter.py`）仍记 structured：它是取数补库，不是盯盘。
- **配额按租户算，三个口径必须一致**：悟道 token 只来自 `mcp.json`，而 `paths.mcp_json_path()` 是**按租户**的（`_tenant_scoped`：`PALACE_MCP_JSON` 这类环境变量只对主租户生效，子租户不回落主租户那份文件）。一个租户 = 一个悟道账号 = 服务端各算各的 5000/天、50/分。所以日计数（ops.db，本来就按租户）、在途占位（`_INFLIGHT`，key 是 `(租户, pool)`）、每分钟名额窗口（`_MINUTE_WINDOW`，key 是租户）**三者同口径**。`loci.config.json` 里的配额数字是全局的，但那是**限额档位**不是**用量**，别拿它当「配额是全局的」的证据。修之前只有日计数按租户、另两个按进程：租户 B 的在途调用会把 A 的已用额度撞高，A 收到一条**假的**「配额已用尽」。哪天真改成全平台共用一个悟道账号，这三者要**一起**改回全局——只改一个又会撕裂。回归 `tests/intel/test_quota_tenant.py`。
- **配额是「先占位再记账」**：日计数落 ops.db 且只在调用成功后 +1，并发扫描（题材成分 4 线程并行）会在同一个旧计数上一起过闸。`acquire_quota` 现在把「读计数 → 判闸 → 占位」放进同一把进程锁，`record_quota_call` 先落库再释放占位；失败路径不记账，占位 120s 自动到期（比 `McpClient` 60s 超时长），调用方不需要显式回滚。测试用 `clear_quota_reservations()` 复位（同时清空每分钟名额窗口）。**限制**：占位只在单进程内有效，多进程并发仍以 ops.db 计数为准。
- **日配额与每分钟名额处理方式不同**：前者今天真没了 → 立刻抛 `McpQuotaError`；后者只是这一瞬发太快，且是**本地**节流器（保护供应商的 50/分），→ `acquire_quota` 在锁外**排队等**下一个名额（最多 `_MINUTE_WAIT_MAX_SECONDS`≈65s，超时才抛）。把限流判成失败等于自己的节流器把自己的活干掉：情报 Job 会因 `stats.failed>0` 整体刷红，Skill 侧更糟——取数失败按红线要走失败关闭，一次限流就能把结论改成空仓。等待必须在锁外，否则一个被节流的调用会把其它线程一起堵住。
- **结构化采集**：托管任务 `情报·开盘/盘中/盘后`（`kind=intel_fetch`），确定性拉涨停梯队/题材/资金流等，结果缓存 `market.db.intel_snapshots`（DDL 经 `MarketStore.ensure_intel_snapshots_schema`，可重建）；部分调用失败时 Job 记 `failed`（不假绿）。
- **盘中扇出有专用上限**：`daily_recipe.INTRADAY_THEME_TOP_N=40` 只作用于 intraday 档的 `theme_stocks` 扇出（Job 配置键 `intraday_theme_top_n` 可调）；open / close 仍按完整 `theme_top_n` 采——开盘与收盘的截面才是复盘要用的那两张，不能砍。盘中题材榜十几分钟内不会翻天，而这一档一天要跑 24 轮，题材数是唯一被轮次放大的旋钮：120→40 一天省 (120-40)×24 = 1920 次。
- **估算器必须对齐调度器**：`estimate_daily_calls` 的 `intraday_runs` 不再写死 20，而是按 cron 数（`intraday_runs_from_cron`；托管 `*/15 9-14` 实际 **24 轮/日**，写死 20 天生低估两成）；follow-up 条数也不再手抄公式，直接把 `build_followup_calls` 跑一遍数长度——旧公式把盘后 `capital_flow` 的 12 批算成 5 批、把 `minute_data` 的 20 次算成 80 次，两个方向都错。调用方（`intel_fetch`）会把 ops.db 里三条托管任务的真实 config 与 cron 经 `phase_params` / `intraday_cron` 传进来，`scheduler_source` 标明这次估算是 `ops_db` 还是 `defaults`。
- **超预算只报警、不静默截断**：`structured_budget_alert(estimate)` 在预估超出池预算时返回一条中文告警（超多少 + 该拧哪个旋钮：盘中 cron / `intraday_theme_top_n` / 盘后三个上限 / 改记 skill 池），`intel_fetch` 在开跑前调用它，写日志 + job payload 的 `quota_alert` 与 `summary`，然后**照原配方跑完这一轮**。悄悄少拿数据会让下游把「只扫了前 N 只」读成「全市场就这些」，那比超配额贵得多。
- **当前配额账（默认托管配置，盘中 24 轮/日）**：

  | 档 | 池 | 静态 | follow-up 上限 | 每轮 | 轮/日 | 日计（改前 → 改后） |
  |---|---|---|---|---|---|---|
  | 开盘 | structured | 28 | 162 | 190 | 1 | 190 → 190 |
  | 盘中 | structured | 7 | 126 → 46 | 133 → 53 | 24 | 3192 → **1272** |
  | 盘后 | structured | 29 | 264 | 293 | 1 | 293 → 293 |
  | 盯盘 / tape | structured → **skill** | — | — | 3~8 条 lane | 72 | 约 300~600（整体移出 structured）|

  structured 合计 **3675 → 1755**（预算 3000，已压在预算内）；skill 侧从约 0 涨到约 300~600（预算 2000）。tape 那一行是量级估计（缓存命中率随行情波动），structured 三档是 `estimate_daily_calls` 直接算出来的上限。**2026-08-31 起**再加：截面工具扩面 +8 次/日（open 2 + close 6）、简报四档最多 +12 次/日（含未出稿的重试），structured 约 1763~1775，仍在预算内。
- **「配了悟道就用起来」的扩面（2026-08-31）**：open 档加 `auction_theme_strength`（竞价资金打哪条主线；**必须 `detailLevel=summary`**，standard 档正文默认吐 JSON 明细，实测单次 63KB vs 5KB）与 `market_catalyst_calendar`（未来两周催化，不传日期不传 country）；close 档加 `board_break_analysis`（昨涨停×今日：断板率/高标杀/`sentimentSignal`）、`limit_down`（权威跌停口径 + 今日封板率与炸板数）、`margin_trading`（两融汇总）、`unlock_events`（未来一个月解禁，区间在 `_with_dates` 里补）。**都不进盘中档**：盘中一天 24 轮，一条截面工具就是 24 次配额。这六张表本地库一张都算不出来。明确不接的清单与理由见 [ADR-017](../../docs/adr/ADR-017-wudao-briefing-relay-and-intel-widening.md) 决策 1。
- **悟道 AI 简报（`briefings`）只转发、不入账**：`application/briefing.py` 负责取数 + 解析 + Markdown→txt；推送在 ops（`jobs/intel_brief.py` + 四条 `简报·*` 托管任务，各比悟道出稿晚 10 分钟）。三条实测格式陷阱：①不传 `format` 时 `content[0].text` 只有**一行带省略号的 headline**，不是全文；②全文只在 `detailLevel=raw` 的 `structuredContent.rawData[0].content.fullContent`，且是 **Markdown**；③「这一档还没生成」不是错误（`success=true` + `data.count=0` + 正文「暂无简报」），`parse_briefing` 对此返回 `None`，调用方记 `skipped`。四档全文实测：开盘 3424 字 / 8323 字节、午间 1530 字、收盘 1359 字、晚间 1611 字。**简报不进复盘数字、不喂选股引擎、不写权威表**，正文首行固定标注「悟道 AI 生成，仅作旁注」——与评估报告「不建议入库当事实」同一条：可以转发，不可以当账。
- **热度双口径**：open / close 两档各采两次 `smart_hotlist`——默认的 `combined` 综合榜与 `platform="ths"` 同花顺单平台榜。两者是**不同参数、不同缓存行**（key 含 `args_hash`），读侧要复现同一份参数才命中，别把其中一份当成全部热度。同花顺榜单独采是因为热度尾盘战法要两榜交集，且 MCP 不返回 `hot_rank_chg`，注意力增量只能靠 open→close 两档差分。见 [ADR-011](../../docs/adr/ADR-011-ths-heat-tail-close-picker.md) 决策 3、4。
- **配方入参必须照 schema 写**（`application/daily_recipe.py`）：悟道多数工具是 `additionalProperties: false`，多传一个它不认的键会被 `INVALID_ARGUMENTS` **整条拒掉**，不是忽略该键——「顺手加个 `limit`」等于这次采集白跑，而且 `stats.failed>0` 会把整个 Job 刷红。已知约束：`index_market` 无 `summaryOnly`；`sector_analysis` / `approaching_limit_up` / `broken_limit_up` / `dragon_tiger` 不收 `limit`；`limit_up_filter.limit ≤ 100`；`limit_up_premium` 必填 `startDate`/`endDate`（区间统计，单日样本达不到 `minLimitUpCount`）。`arg_clamp` 只防扇出、不懂各工具 schema，别指望它兜底
- **参数键名走表，不写 if-else**（同一件事两个键名，是本仓踩过的坑）：

  | 语义 | 工具 | 键名 | 表 |
  |---|---|---|---|
  | 一批股票代码 | `capital_flow` | `stockCodes` | `daily_recipe._CODES_ARG_BY_TOOL` |
  | 一批股票代码 | `intraday_main_flow` / `kline` | `codes` | 同上 |
  | 交易日 | `approaching_limit_up` / `trading_calendar` | `date` | `daily_recipe._DATE_REQUIRED` |
  | 交易日 | `limit_stats` / `limit_up_ladder` / `broken_limit_up` | `tradeDate` | 同上 |
  | 交易日 | `limit_down` / `anomaly_detection` | `date` | 同上（2026-08-31 双向实调验证） |
  | 交易日 | `board_break_analysis` / `auction_theme_strength` / `margin_trading` / `northbound_holdings` | `tradeDate` | 同上（同日双向实调验证）|
  | 区间（**不传单日**）| `margin_trading`（配方口径：两融是 T+1 数据，问当天必空）| `startDate`/`endDate` | `daily_recipe._with_dates` |
  | **一个日期键都不补** | `sector_analysis` / `unlock_events`（服务端全拒）、`macro_calendar` / `market_catalyst_calendar`（语义是向前看的日历，补今天等于砍成一天） | — | `wudao_keys.DATELESS_TOOLS` |
  | 交易日（tape lane） | 见 `market/README.md` 盘口情报 tape 段 | 逐工具 | `tape/wudao_provider.DATE_ARG_BY_TOOL` |

  `capital_flow` 用 `stockCodes` 是因为它还支持 `flowType=theme`，键名带上了主体类型；`intraday_main_flow` 只做个股，就叫 `codes`。两者都是「传一批代码」，但键名写反 = 整条调用作废，而不是被忽略。**新增工具往表里加一行**，别在 `_batch_flow_calls` 里重开分支——上一次这条链路作废就是因为分支里手抄了 `codes`。表里 `trading_calendar`/`limit_stats` 两行**尚未经在线 schema 复核**（改动期间禁止发起真实调用），下次接触真实 MCP 时用一次 `tools/list` 确认；**权威来源始终是服务端 schema，不是这张表**。
- **盘面只读摘要**：`build_intel_brief(store, trade_date=…)` / `GET /api/intel/brief` 从缓存投影情绪/题材/梯队 + **复盘与排雷六段**（`board_break` 断板分析、`limit_down` 跌停池、`auction_themes` 竞价题材、`catalysts` 未来催化、`margin` 两融、`unlocks` 解禁）；**不调 MCP**、不发明数字；未跑 `intel_fetch` 时 `available=false`，未采到某工具时该段为 `null` / 空数组。列表读缓存用 `list_latest_snapshots`（同工具多参取最新 `fetched_at`）。情绪字段兼容悟道 `sealedLimitUp` / `brokenBoardRate` / `promotionRates.firstToSecond`；晋级率、炸板率、断板率、竞价一致性统一成 0–100 百分数（`_percent`；悟道的 `breakRate`/`consistency`/`rate` 都是 0–1 比例）；题材附带 `pct_chg` / `main_net_amount_text`，避免把开盘啦内部 strength 当人话展示。三个已知坑：**两融要先挑最新一个交易日、再把交易所三行加起来**（服务端 `latest` 只是第一行，实测是 BSE 的 83 亿；配方给的是七天窗口——两融是 T+1 数据，问当天必空——一锅加起来就是把一周余额摞在一起；全市场实测 2.63 万亿）；**催化在消费侧筛**「今天及以后 + 中国」（服务端 `country` 过滤对不上就是静默 0 行）；跌停家数三级兜底（情绪表 → 涨跌停统计 → 跌停池，后者最权威但只有收盘档采）。
- **可选依赖铁律**：无悟道 Key / 悟道不可用时，**不得影响**盘面、账本、本地选股、行情同步等主体功能。统一入口：`wudao_availability` + `call_mcp_tool` 软失败（含建连失败、配额用尽、调用中途异常）；`intel_fetch` / `skill_watch` Job 记 `skipped`；纸面闸门降级为空仓拦截开仓（不抛）；`/api/intel/brief` 不 5xx；日 K 悟道适配器仅在显式开启且可用时才进路由。跨上下文只经包根（含 `probe_mcp`），禁止深掏 `infrastructure`。
- AkShare 接口工具：`builtin_akshare_tools.py`，固定工具名 `akshare_call`（兼容旧 `ak_<接口名>`），经 `probe_stock_capability` 受控执行；**不再维护上桌名单**。目录浏览 / 一键全测 / 版本检查在工坊「数据源」→「按接口」。
- 大批量量价仍走 market，不走 MCP 扫全市场
- 禁忌：跨上下文深掏 `src.intel.infrastructure.*`；也不要从 intel 深掏 `src.market.infrastructure.*`

## README 维护
改 MCP 契约、限流、内置工具时必须更新本文。

## 相关测试
`tests/intel/`
