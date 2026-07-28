归属：`/api/jobs*` `/api/skills*` `/api/skill-runs*` `/api/ops/*`。

挂载：
- `src.ops.api.jobs.build_jobs_router`
- `src.ops.api.skills.build_skills_router`
- `src.ops.api.settings.build_ops_settings_router`（lanes / 数据目录 / 企微 / 行情同步）

由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。
