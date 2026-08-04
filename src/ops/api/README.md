归属：`/api/jobs*` `/api/skills*` `/api/skill-runs*` `/api/ops/*`。

技能定时绑定：`GET|PUT|DELETE /api/skills/{slug}/job`（`name=skill:{slug}`，`config.push_wecom` 控制结束后企微推送）。

挂载：
- `src.ops.api.jobs.build_jobs_router`（含 `GET /api/jobs/runs`、`POST /api/jobs/runs/batch-delete`、`GET /api/jobs/schedule`：未启调度器时仍按 cron 推算 `next_run_at`）
- `src.ops.api.skills.build_skills_router`
- `src.ops.api.settings.build_ops_settings_router`（lanes / 数据目录 / 桌面偏好 / 企微 / 行情同步）

由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

线路（lanes）契约：
- `GET /api/ops/lanes`：每家源回 `enabled`（源总开关）+ `disabled_lanes`（被单独关掉的工具）；每条 lane 回 `policy` 与 `effective_provider_ids`（生效顺序，界面据此判断有没有可用源）。`summary` 仍是占位 0，没有真实健康聚合，别当探测结果用。
- `PATCH /api/ops/lanes/providers/{id}`：`{"enabled": false}` 改源总开关；带 `{"lane": "hist_daily"}` 只改这家在该线路上的单个工具（lane 不属于该源 → 422）。停用后只清受影响 lane 的粘性。必需 lane 被关空不拦，界面负责警告。
- `POST /api/ops/lanes/probe`：不传 `lane` 就逐 lane 探测；传 `adapter_id` 时即使该源已停用也照测（「测这家」），且只测它自己支持的 lane，`results` 每行带 `lane` + 中位 `rtt_ms`。
- `POST /api/ops/lanes/probe` / `POST /api/ops/lanes/speedtest`：会消耗外部数据源配额，要求浏览器会话或 Agent Bearer；不能因不写本地库而匿名调用。
- `GET|POST /api/ops/data-location`：生产首启只允许直接本机回环请求免登录；远端或经代理转发的读取、改写数据目录始终要求浏览器会话或 Agent Bearer。
