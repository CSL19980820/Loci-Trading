# 运维（ops）

## 职责
定时任务、技能包、通知、调度器、运维配置。
其中 `application/screen/` 负责 formula/Python Screen Skill 包的磁盘存储、历史归档、zip 路径校验与 revision 锁；不负责编译或执行选股。

## 边界
写 ops.db；技能文件在 data/skills。

## 企微推送
- 出站**只发 text**（`send_wecom_text`）；`send_wecom_markdown` 仅为兼容壳，内部仍转 text。
- 选股模板可在系统「推送」联配置（ops.db `wecom_screen_template`）：预设 default / compact / with_date / custom。
- 渲染：`format_screen_picks_text`（`notify_screen_template.py`）；占位符 `{title}` `{kind}` `{date}` `{name}` `{code}` `{pct}` `{n}`。
- `screen` / 绑定战法任务 `push_wecom=true` → 量化标记；`skill` 且结果含 picks → 技能标记。成功推送后写入 `wecom_push_marks`（`job_id:trade_date`）；同日再跑只记 `already_pushed`，不重复发企微。

## 关键入口
`OpsStore` / `run_job` / `discover_skills`；HTTP：`/api/jobs/*` `/api/skills/*` `/api/ops/*`；CLI：`python -m cli.ops`

## 如何扩展
新 Job kind：在 `application/jobs/<kind>.py` 写 `execute_*`，再注册到 `application/jobs/registry.py` 的 `EXECUTORS`，并加入 `JOB_KINDS` 与 `JobCreate.kind`。

托管任务：
- 行情：`MANAGED_SYNC_INTRADAY` / `MANAGED_SYNC_EOD`，由 `ensure_managed_market_sync_jobs` 幂等创建；**首次默认开启**盘中增量 + 日终重刷（默认 15:25，`today_refresh` + `with_factors`，赶在 15:30 选股前）
- 候选兑现：`MANAGED_OUTCOME_TRACK`（`kind=outcome`，默认 cron `45 15 * * 1-5`），由 `ensure_managed_outcome_job` 幂等创建；lifespan 启动（含未开调度器时预写）确保存在
- 盘后选股：每个引擎战法绑定 `screen:{slug}`，默认 cron `30 15 * * 1-5`（工作日 15:30），由 `ensure_managed_screen_jobs` 幂等创建/对齐；战法可声明自己的托管时点与输出上限，`qianlong-tail-v1` 固定 14:50 且最多 1 只，`sanyuan-tail-v1` 固定 15:30 且最多 2 只；用户在详情页保存的 `universe`（行情范围）会保留，手动选股未传 universe 时也回落该配置（见 `screen_job_config.resolve_screen_universe`）；无 `screen_schedule` 声明的战法还会保留用户自定义定时；执行前默认 `refresh_spot` 刷当日 OHLC
- 活动目录收缩：`ensure_managed_screen_jobs` 会删除 `screen:*` 前缀下不再注册的旧 `screen` 任务，避免废弃战法继续调度或推送；其它同名前缀任务和非 `screen` 任务不受影响
- 调度器：`loci.py` / `cli.serve` 默认 `PALACE_ENABLE_SCHEDULER=1`（pytest 不设）；启动时确保上述托管任务并 `reload`
- **启动补跑**：调度器起来后后台执行 `eod_catchup`——对 `screen` / 日终 `sync` / `outcome` 等「工作日定点」cron，若最近交易日触发点已过且尚未跑过，则 `trigger=catchup` 补跑一次。`last_run_at` 无时区时按 UTC/上海本地**任一覆盖**即跳过；若当日已有成功 run，也跳过。选股企微另有 `wecom_push_marks` 防连推。
- `GET /api/jobs/schedule`：未启调度器时仍用 `preview_upcoming_jobs` / `next_cron_fire_at` 按 cron 推算 `next_run_at`，供详情页展示
- **执行互斥**：`run_job` 通过 ops.db 原子认领同一任务的执行槽；调度、API、CLI 和助手重叠触发时，后到者返回 `skipped` 和当前 `run_id`，不重复执行副作用。运行超过 24 小时的残留记录会标记失败后自动回收；即时分析预先分配独立运行槽，因此不同请求仍可并行。

### 全局助手调度

全局助手可管理 `sync`、`screen`、`backtest`、`compare`、`optimize`、`prune`、`outcome` 任务，并在创建、更新、删除后请求组合根重载调度器。它不能创建、修改或触发 `skill`、`notify` 等可扩展任务，避免经助手间接取得 CLI、文件或外部 MCP 执行面。助手立即触发任务时必须传入当前工作台的 `JobContext(market_db, palace_db)`。

## 包结构（jobs）
`application/jobs/`：`context`（JobContext/JobError）· 各 kind 执行器（含 `outcome`）· `registry`（EXECUTORS + `run_job`）。对外仍从 `src.ops` / `src.ops.application.jobs` 导入。

## 存储层拆分（infrastructure）
对外仍从 `store` 入口导入：`OpsStore` / `OpsError` / `JOB_KINDS` / `MANAGED_SYNC_*` / `new_id` 等。
内部按职责拆文件（均 ≤600 行）：

| 文件 | 内容 |
|---|---|
| `store_helpers.py` | 常量、`OpsError`、`new_id` / `dumps` / `loads` |
| `store_schema.py` | DDL、`SCHEMA_VERSION`、迁移清单 |
| `store_jobs.py` | 任务 / meta 设置 / 执行历史 mixin |
| `store_providers.py` | LLM 供应商 mixin |
| `model_catalog.py` | `models_json` 规范化 / 发现合并 / 启用 id 派生 |
| `store_strategy.py` | 战法档案与策略版本 mixin |
| `store.py` | `OpsStore` 组合 + 连接/迁移 + re-export |

## 给 Agent 的用法
- 任务：`from src.ops import run_job, OpsStore, OpsError, new_id`
- 技能：`discover_skills` / `install_skill`；根目录每次运行时解析
- Screen Skill 文件存储：`src.ops.application.screen.*`；HTTP 契约与公式编排由 `src.app.screen_skills*` 负责
- `runtime=formula` 的执行文件是 `formula.tdx`；`runtime=python` 是 `strategy.py` 与可选包内模块；两者共用原子保存和历史归档
- Screen Skill 上传必须走 `/api/screen-skills/import`；`/api/skills` 只接受普通技能包，并对误投/损坏的 screen 包返回受控 422
- Screen Skill 历史只列出非当前 package revision；恢复归档时会将回滚前的 current 包原子归档，避免当前版本和历史版本重复展示
- 新 Job kind：写执行器后注册到 `application/jobs.EXECUTORS`
- 调度 cron 一律按 `Asia/Shanghai` 解析（`validate_cron(..., timezone=...)`）

## README 维护
改 Job 种类、技能约定、ops.db 语义、企微模板或 store 拆分边界时必须更新本文。

## 相关测试
`tests/ops/`
