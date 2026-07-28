# 运维（ops）

## 职责
定时任务、技能包、通知、调度器、运维配置。

## 边界
写 ops.db；技能文件在 data/skills。

## 关键入口
`OpsStore` / `run_job` / `discover_skills`；HTTP：`/api/jobs/*` `/api/skills/*` `/api/ops/*`；CLI：`python -m cli.ops`

## 如何扩展
新 Job kind：在 `application/jobs/<kind>.py` 写 `execute_*`，再注册到 `application/jobs/registry.py` 的 `EXECUTORS`。

## 包结构（jobs）
`application/jobs/`：`context`（JobContext/JobError）· 各 kind 执行器 · `registry`（EXECUTORS + `run_job`）。对外仍从 `src.ops` / `src.ops.application.jobs` 导入。

## 存储层拆分（infrastructure）
对外仍从 `store` 入口导入：`OpsStore` / `OpsError` / `JOB_KINDS` / `MANAGED_SYNC_*` / `new_id` 等。
内部按职责拆文件（均 ≤600 行）：

| 文件 | 内容 |
|---|---|
| `store_helpers.py` | 常量、`OpsError`、`new_id` / `dumps` / `loads` |
| `store_schema.py` | DDL、`SCHEMA_VERSION`、迁移清单 |
| `store_jobs.py` | 任务 / meta 设置 / 执行历史 mixin |
| `store_providers.py` | LLM 供应商 mixin |
| `store_strategy.py` | 战法档案与策略版本 mixin |
| `store.py` | `OpsStore` 组合 + 连接/迁移 + re-export |

## 给 Agent 的用法
- 任务：`from src.ops import run_job, OpsStore, OpsError, new_id`
- 技能：`discover_skills` / `install_skill`；根目录每次运行时解析
- 新 Job kind：写执行器后注册到 `application/jobs.EXECUTORS`

## README 维护
改 Job 种类、技能约定、ops.db 语义或 store 拆分边界时必须更新本文。

## 相关测试
`tests/ops/`
