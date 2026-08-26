归属：`/api/jobs*` `/api/skills*` `/api/skill-runs*` `/api/ops/*`。

技能定时绑定：`GET|PUT|DELETE /api/skills/{slug}/job`（`name=skill:{slug}`，`config.push_wecom` 控制结束后企微推送）。
专属战法配置：`GET|PUT /api/skills/{slug}/strategy-config`，系统成对管理
`skill:{slug}`（盘后 AI 选股）与 `监测·{slug}`（盘中信号监测）两个 Job。
`SKILL.md` 不得声明 `cron` / `schedule` / `default_cron`；运行时间、频率、启停和推送均属于系统配置。
响应含 `watch_available` / `watch_unavailable_reason`：悟道 MCP 未装配时前端应置灰监测与预览。

战法监测调参：`GET|PUT|DELETE /api/skills/{slug}/watch-tuning`。PUT 按段合并（只传 `stages` 不会重置阈值），
传 `preset`（`aggressive` / `balanced` / `defensive`）整档套用命名预设（段开关保留当前值）。
未知键丢弃、越界值钳到边界。响应含 `presets` 与 `schema.presets`（id / label / summary）。
段开关：`market_gate` / `auction_confirm` / `role_history` / `paper_candidates`。

角色留痕：`GET /api/skills/{slug}/leader-roles` 返回 `history`（只追加的观测事实）、
`transitions`（角色变化）、`summary`（存活/转移/预警提前量，即时推导）与 `suggestions`
（基于留痕频率的调参建议，**只读不改参**）。

战法监测预览：`POST /api/skills/{slug}/watch-preview` 用实时数据试跑一次确定性扫描，
返回龙空龙闸门、主线题材、龙头地图角色、竞价确认、角色变化、纸面候选、信号与 `suggestions`。
**只读**——不写纸面舱、不推送、不调 LLM；悟道不可用时返回 `skipped/reason=mcp_unavailable`，不消耗配额。
（`role_history` 段开启时仍会追加角色留痕，那是观测事实不是交易动作。）

二波监测首页快照：`GET /api/skills/dragon-second-wave/second-wave` 返回上一轮扫描
（池/触发/宽度/名单）并给列表票叠当日现价。不重跑扫描。其它 slug → 404。
达标观察票只上首页，不刷企微（`push_only_when_actionable` 把仅观察当无信号）。

龙头角色留痕：`GET /api/skills/{slug}/leader-roles?code=&trade_date=&limit=` 回 `history` 与 `transitions`
（角色变化）。只追加的观测流，可整表清空重建。

挂载：
- `src.ops.api.jobs.build_jobs_router`（含 `GET /api/jobs/runs`、`POST /api/jobs/runs/batch-delete`、`GET /api/jobs/schedule`：未启调度器时仍按 cron 推算 `next_run_at`）
- `src.ops.api.skills.build_skills_router`
- `src.ops.api.settings.build_ops_settings_router`（lanes / 数据目录 / 桌面偏好 / 企微 / 通知策略 / 行情同步 / 版本 / 一键打包 / 纸面量化）

由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

纸面量化与提醒：
- `GET|PUT /api/ops/settings/notify`、`POST /api/ops/settings/notify/test`：安静时段 / Bark / 渠道摘要。
- `GET|PUT /api/ops/alert-rules`、`DELETE /api/ops/alert-rules/{id}`、`POST /api/ops/alert-rules/scan`。
- `GET /api/ops/paper-cabins/{slug}`、`GET .../{slug}/unified-pool`、`PUT .../config`、`PUT .../style`、`POST .../style/absorb`、`GET .../memory/explore`、`POST .../memory/rebuild`、`POST .../orders`、`POST .../monitor`、`POST .../eod`、`POST .../nextday-plan`。`unified-pool` 是持股/买入/观察/卖出/调仓的唯一事实投影。
- `PUT .../config`：龙回头 `enabled=true` 时同步创建/启用 `skill_watch` 与 `paper_eod`，并停用旧 `strategy_monitor`。该 `skill_watch` 唯一触发纸面 AI，但 **`push_wecom=False`**——扫描摘要每轮都会复读整池，出声交给纸面跟随推送（成交/拒单/持仓巡检有变化才发）。其他纸面舱沿用 `strategy_monitor` + `paper_eod`；`enabled=false` 停用对应 Job；成功后 `scheduler.reload()`。
- `PUT .../config` 的 `llm_timeout_sec` 控制纸面盯盘与盘后记忆模型的单次调用预算，范围 120–1800 秒，默认 1800 秒。
- Job kinds：`alert_scan` / `skill_watch` / `strategy_monitor` / `paper_eod`（见 ADR-008；龙回头定时盘中任务使用 `skill_watch`，`strategy_monitor` 保留手工接口兼容）。

线路（lanes）契约：
- `GET /api/ops/lanes`：每家源回 `enabled`（源总开关）+ `disabled_lanes`（被单独关掉的工具）；每条 lane 回 `policy` 与 `effective_provider_ids`（生效顺序，界面据此判断有没有可用源）。`summary` 仍是占位 0，没有真实健康聚合，别当探测结果用。
- `PATCH /api/ops/lanes/providers/{id}`：`{"enabled": false}` 改源总开关；带 `{"lane": "hist_daily"}` 只改这家在该线路上的单个工具（lane 不属于该源 → 422）。停用后只清受影响 lane 的粘性。必需 lane 被关空不拦，界面负责警告。
- `POST /api/ops/lanes/probe`：不传 `lane` 就逐 lane 探测；传 `adapter_id` 时即使该源已停用也照测（「测这家」），且只测它自己支持的 lane，`results` 每行带 `lane` + 中位 `rtt_ms`。单源探测有墙钟超时（默认 25s），超时记失败不堵死请求。前端「探测线路」改为按用途逐 lane 请求并即时回填。
- `POST /api/ops/lanes/probe` / `POST /api/ops/lanes/speedtest`：会消耗外部数据源配额，要求浏览器会话或 Agent Bearer；不能因不写本地库而匿名调用。
- `GET|POST /api/ops/data-location`：生产首启只允许直接本机回环请求免登录；远端或经代理转发的读取、改写数据目录始终要求浏览器会话或 Agent Bearer。
- `GET /api/ops/version`：产品版本（与 `src/shared/version.py` / 前端 `release.ts` 对齐）。
- `GET /api/ops/share-pack/status`：是否已有编译产物、可选附件体积（**不**回传解压密码）。
- `POST /api/ops/share-pack`：`{"include":["algorithms","ledger",…],"password":"…"}` → 加密 zip；密码须匹配服务端固定值；`algorithms` 控制是否打入内置战法/公式；写操作需会话/Bearer。
