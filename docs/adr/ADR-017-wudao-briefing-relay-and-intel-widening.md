# ADR-017：悟道 AI 简报转发企微 + 情报配方按「配了就用」扩面

**状态**：Accepted（已落地）
**日期**：2026-08-31
**相关**：[`ADR-009`](ADR-009-market-tape-provider-lanes.md)（可选悟道与 provider lanes）、[`ADR-011`](ADR-011-ths-heat-tail-close-picker.md)（热度双口径进配方）、[`docs/research/2026-08-wudao-mcp-utilization-assessment.md`](../research/2026-08-wudao-mcp-utilization-assessment.md)（本 ADR 修订它的两条结论）

## 背景

需求原话两条：

1. 「配置了 wudao 数据尽量利用起来，没配置的就别管他，配了就尽量利用起来」。
2. 「这个简报（悟道开发者页「每日市场动态中心」的开盘/午间/收盘/晚间四档）配置了就来个开关自动发到企微，需要先转为 txt 再发，**我们比他晚 10 分钟发，因为怕他延迟了**」。

落地前的事实（`rg` 全仓 + 生产 Key 实调，2026-08-31）：

- 悟道 MCP 共 **63 个工具**，本仓代码里出现过的只有 **21 个**；`briefings` 一次都没调过。
- 未被使用但对短线**确有增量**的截面工具：`board_break_analysis`（昨涨停×今日）、
  `auction_theme_strength`（竞价题材聚合）、`limit_down`（跌停池，含封板率/炸板数）、
  `margin_trading`（两融汇总）、`market_catalyst_calendar`（未来两周催化）、
  `unlock_events`（限售解禁）。本地库这六张表**一张都算不出来**。
- 生产 `data/mcp.json` 里悟道 Key 有效、63 个工具已同步；`ops.db` 企微 webhook 已配。

## 决策

### 1. 六条截面工具进 `daily_recipe`，只进 open / close 两档

| 工具 | 档 | 参数（实测键名） | 单次载荷 |
|---|---|---|---|
| `auction_theme_strength` | open | `tradeDate` + `limit=12` + `detailLevel=summary` | 5.4KB（standard 档 **63KB**，故取 summary） |
| `market_catalyst_calendar` | open | `limit=60`，**不传日期、不传 country** | 7KB |
| `board_break_analysis` | close | `tradeDate` + `focus=all` + `limit=80` | 15KB |
| `limit_down` | close | `date` | 0.8KB |
| `margin_trading` | close | `startDate`/`endDate`（今天往前 7 天）| 1.4KB |
| `unlock_events` | close | `startDate`/`endDate`（今天起 30 天）+ `limit=60` | 5KB |

**不进盘中档**：盘中 cron 是 `*/15 9-14`，一天 24 轮——一条截面工具就是 24 次
structured 配额。日耗合计 **+8 次/天**（open 2 + close 6），structured 池 1755 → 1763，
预算 3000 不动。

**上线实跑改掉的两处**（2026-08-31 生产实测，不是纸面推演）：

- `margin_trading` 原本按 `tradeDate=今天` 问，**收盘档必然空手**——两融是 T+1 数据。改成七天窗口，由 `brief._margin` 取窗口里最新那一天并把三所加起来（实测 2.63 万亿；服务端 headline 那个「融资余额 12789.74 亿」只是深交所一行）。
- 简报全文一度只剩 410 字：`fetch._resolve_structured` 把 `structured` 解包成服务端 `data` 段时，把兄弟节点 `rawData` 一起丢了，而全文就在那里。改成解包时保住 `rawData`；**不走 `format=json`** 那条路——`McpClient` 对正文有 12000 字截断，raw 档 JSON 实测 41KB，截断后必然解不出来。

**明确不接**：`northbound_holdings`（全市场明细无排序键，拿不到「净买入」这一层）、
`limit_events`（秒级事件流，配方粒度用不上）、`anomaly_detection`（键名已登记备用，
无产品故事前不采）、`watchlist_*`（自选真相在本机）、`sec_*` / `etf_market` /
`convertible_bond_market`（不在 A 股短线产品边界内）、四个 `*_workflow`（Agent 临机可用，
不做确定性 Job）。基本面四件套（`financial_summary` / `valuation_snapshot` /
`shareholder_structure` / `research_reports`）维持原判：**助手按票点查，不做日更权威仓**。

### 2. 日期键名照服务端 schema 登记，且**双向实调验证**

`wudao_keys.DATE_ARG_BY_TOOL` 加六行、`DATELESS_TOOLS` 加三个。每个工具都用「正键 +
对照键」各打一次真实调用，看服务端认哪个（2026-08-31）：

```
auction_theme_strength.tradeDate OK   / .date REJECTED
board_break_analysis.tradeDate   OK   / .date REJECTED
limit_down.date           OK   / .tradeDate REJECTED
margin_trading.tradeDate OK   / .date REJECTED
northbound_holdings.tradeDate    OK   / .date REJECTED
anomaly_detection.date        OK   / .tradeDate REJECTED
unlock_events / macro_calendar / market_catalyst_calendar：tradeDate REJECTED（只认区间）
```

`DATELESS_TOOLS` 从此有**两类**成员，注释里分开写：一类是「服务端不收任何日期键」
（`sector_analysis`、`unlock_events`），一类是「语义就是向前看的日历，补上今天等于把
日历砍成一天」（`macro_calendar`、`market_catalyst_calendar`）。

### 3. 采了就要有人消费：`build_intel_brief` 加六段投影

`board_break` / `limit_down` / `auction_themes` / `catalysts` / `margin` / `unlocks`。
盘面情报 tape（`PulseWatchRail`）把断板率+情绪信号、跌停+炸板、竞价主线、最近催化压进
同一行，高标杀名单/两融净额/最大解禁进 tooltip。

三个口径坑写进代码注释：

- `breakRate` / `consistency` / `rate` 是 **0–1 比例**，统一过 `_percent` 换成 0–100。
- **两融必须把交易所三行加起来**：服务端 `latest` 只是 rows 的第一行（实测是 BSE 的
  83 亿），正文 headline 用的也是那一行；全市场实测 2.63 万亿。
- 催化日历**在消费侧筛**「今天及以后 + 中国」：服务端 `country` 过滤值一旦对不上就是
  静默 0 行，而行里本来就带 `country`，本地筛错了看得见。

### 4. 简报只转发，不入账

`briefings` 的定位仍是 [评估报告](../research/2026-08-wudao-mcp-utilization-assessment.md)
写的「**不建议入库当事实**」——本 ADR **不改**这条：简报不进复盘数字、不喂选股引擎、
不写任何权威表；正文首行固定标注「悟道 AI 生成，仅作旁注」。**可以转发，不可以当账。**

取数格式实测（这一段是本决策最容易踩空的地方）：

- 不传 `format` 时 `content[0].text` 只有**一行带省略号的 headline**，不是全文。
- 全文只在 `detailLevel=raw` 的 `structuredContent.rawData[0].content.fullContent`，
  且是 **Markdown**（`### 【30秒核心】`/`【隔夜要闻】`/`【市场预判】`/`【🔥 今日热点】`/
  `【⚠️ 风险提示】`/`【📅 今日日程】`）。
- 四档全文实测：开盘 3424 字 / 8323 字节，午间 1530 字，收盘 1359 字，晚间 1611 字。
- 「这一档还没生成」**不是错误**：`success=true`、`data.count=0`、正文「暂无简报」。

### 5. 企微分片按**字节**，不靠截断

企微 `msgtype=text` 官方上限 **2048 字节**（中文一字三字节 ≈ 680 字），而既有
`MAX_TEXT_CHARS=2000` 是**字数**闸门（纯中文 ≈ 6000 字节）。新增
`split_text_for_wecom`：默认 1800 字节一片、优先在空行/换行/句末断开、片头带
`（i/n）`；超过 `max_chunks`（默认 6）时在尾部**明写「已截断」**。开盘档实测切 5 片。

### 6. 比上游晚 10 分钟，且一档挂多个触发点

新 Job kind `intel_brief`，四条托管任务（`ensure_intel_brief_jobs`）：

| 任务 | cron | 上游出稿 |
|---|---|---|
| 简报·开盘 | `10,25,40 9 * * mon-fri` | 09:00 |
| 简报·午间 | `10,25,40 12 * * mon-fri` | 12:00 |
| 简报·收盘 | `40,55 15 * * mon-fri` | 15:30 |
| 简报·晚间 | `10,25,40 21 * * mon-fri` | 21:00 |

「预计生成时间」不等于准时，所以每档留 10 分钟并**多挂两个触发点**：第一次没出稿记
`skipped`，下一个点再看一眼；出稿后由防重标记（复用选股那套 `wecom_push_marks`，指纹
含悟道 `generatedAt`）保证只推一条。收盘档挂 `40,55` 而不是 `40,55,10+1h`：15:40 已经
有 `情报·盘后` 在打悟道，不必再多一个点跟它抢每分钟名额。

四条任务名是**独立的字符串常量**（`MANAGED_BRIEF_OPEN` 等）：`job_quota.managed_job_names()`
靠「从 ensure_* 模块现取 `MANAGED_*` 字符串」认托管任务，认不出来就会去吃用户自建任务的
`job_slots` 额度（默认 5 条），四条一挂占掉一大半。

开关有三层，全在既有面板里，不新建设置项：**运维页任务启停**（四条独立）、
`config.push_wecom`（关掉只取数不出声）、`config.full_text`（关掉只发摘要，少几条消息）。

### 7. 缺配置一律软跳过

没配悟道 → `skipped/mcp_unavailable`；这一档还没出稿 → `skipped/not_published`；
最新一份不是当天的 → `skipped/stale_briefing`；安静时段/限流 → `skipped/quiet_hours`；
今天已推过 → `skipped/already_pushed`。**通用状态推送必须对这个 kind 闭嘴**（上线当天发现）：`_maybe_push_wecom` 的 `else` 兜底会给每次运行
再发一条「【任务✓ 简报推送】状态 已跳过」——四档 × 三个触发点 = 一天最多 12 条噪音。现在只有
`status=failed` 才出声；而「简报取回来了却一条都没发出去」（`push_error`）必须判 failed，不得假绿。

`registry.run_job` 的 skipped 白名单加
`intel_brief`——判成 failed 会让四档任务每天在运维页刷四个红叉，而什么都没坏。

## 后果

- 每天多 8 次 structured 配额（截面工具）+ 最多 12 次（四档简报，含未出稿的重试）。
- `intel_snapshots` 每天多约 34KB 截面 + 最多 4 × 43KB 简报（`detailLevel=raw` 的 `structuredContent` 带
  `relatedNews`）。该表定位仍是「可整表删除重建」的缓存。
- 企微每天最多 12 条简报消息（开盘 5 + 午间 3 + 收盘 2 + 晚间 2）。嫌多就关
  `full_text` 或关掉某一档任务。
- 回归：`tests/intel/test_wudao_review_tools.py`、`tests/ops/test_intel_brief_push.py`。
