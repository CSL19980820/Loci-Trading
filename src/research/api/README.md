# 研究 HTTP API

## 路由

由 `src.app.legacy.quant_router.build_quant_router` 聚合挂载，保持本仓 `/api/*` 路径风格：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/research/catalog` | 21 个研究维度、来源名片、预算和质量边界 |
| GET | `/api/research/profile/{code}` | 从本地行情仓生成临时研究剖面；`budget` 为 `lite`/`standard`/`deep`，可选 `as_of=YYYY-MM-DD` |
| POST | `/api/research/runs` | 显式归档输入快照、profile、review 三阶段；body 为 `code`、`budget`、可选 `as_of` |
| GET | `/api/research/runs/{run_id}` | 读取已归档 run；当前行情版本变化时响应标记 `stale`，不修改快照 |
| POST | `/api/research/runs/{run_id}/resume` | 从已保存的 input 阶段恢复缺失阶段；不读取新行情重算旧快照 |
| POST | `/api/research/backtest-runs` | 兼容研究回测入口，立即返回 `202` 和持久化 job |
| POST | `/api/research/backtest-jobs` | 持久化异步提交，立即返回 `job.id` |
| GET | `/api/research/backtest-jobs/{job_id}` | 查询 queued/running/completed/failed 状态及 `run_id` |
| POST | `/api/research/factor-jobs` | 提交固定的 PTH252 因子实验；返回 `202` 和持久化 job，不接受可调策略参数 |
| GET | `/api/research/factor-jobs/{job_id}` | 查询 PTH252 queued/running/completed/failed 状态、`run_id` 和失败原因 |
| POST | `/api/research/backtest-runs/{run_id}/replay` | 受写权限保护，校验冻结 artifact 后重放并写 comparison receipt |
| POST | `/api/research/backtest-runs/{run_id}/publish` | 受写权限保护的人工签署发布；仅 `validation=passed` 且 `awaiting_human_review` 的 run 可完成 |
| POST | `/api/research/backtest-runs/{run_id}/reject` | 受写权限保护的人工否决；仅等待审核的 run 可结束为 `rejected`，并写入 manifest 绑定的回执 |
| GET / POST | `/api/research/membership-snapshots` | 查询或追加一条带来源、版本和 PIT 标记的历史股票池快照 |
| POST | `/api/research/membership-snapshots/import` | 原子导入多条历史股票池快照；冲突内容拒绝覆盖 |
| GET / POST | `/api/research/point-in-time-facts` | 查询或追加带 `available_at`、披露来源和 revision 的财务/事件事实 |
| POST | `/api/research/point-in-time-facts/import` | 原子导入多条 PIT 事实；同 observation id 仅允许幂等重放 |

### 文件清单

研究回测的新执行字段放在 `backtest_config`：`signal_dataset`（安全ID）、`strict_limit_prices`、`economic_returns`、`valuation_end`；`account_model="daily_close"` 与 `initial_capital/max_positions/lot_size` 放在请求顶层。快照模板的缺省值可由后端继承，显式值优先。数据集必须已导入当前租户并覆盖区间，否则任务失败。

逐日账户摘要在 `conclusion.portfolio_summary`，完整明细在 `analysis.json`。该模式的重放响应增加 `portfolio_verification`，比较完整每日账户和未平仓；不一致会使 `matches_all_recomputed_execution=false`，不改变人工发布/否决权限和探索性状态。

| 文件 | 工厂 | 负责的端点 |
|---|---|---|
| `router.py` | `build_research_router` | `catalog` / `profile/{code}` / `runs*` / `hypotheses*`；并 `include_router(build_research_backtest_router(...))`，store factory 形参原样透传 |
| `backtest_router.py` | `build_research_backtest_router` | `backtest-runs*` / `backtest-jobs*`（提交、查状态、run card、workflow、artifact、publish、replay） |
| `factor_router.py` | `build_research_factor_router` | `factor-jobs*`（PTH252 固定合同） |
| `publication_router.py` | `build_research_publication_router` | `backtest-runs/{run_id}/reject` |
| `temporal.py` | `build_research_temporal_router` | `membership-snapshots*` / `point-in-time-facts*` |
| `backtest_models.py` / `factor_models.py` / `temporal_models.py` / `write_access.py` | — | 请求模型与写权限依赖 |

`backtest_router.py` 从 `router.py` 拆出来的理由不是行数，是它自带一份**进程级线程池** `_BACKTEST_EXECUTOR` 与围绕它的 job 状态机；`router.py` 剩下的都是同步请求，两拨东西的失败模式与并发约束完全不同（`factor_router.py` 更早因同样理由拆出）。

⚠️ **持有线程池的文件必须登记在 `tests/ai/test_tenant_threads.py::_GUARDED_FILES`**（那条 AST 守卫逐文件扫 `x.submit(...)` / `threading.Thread(...)`）。`router.py`、`backtest_router.py`、`factor_router.py` 都在清单里；**再拆时清单要跟着走**，否则守卫出现盲区，而且清单里写了不存在的路径会让用例直接 `FileNotFoundError`。投递一律走 `submit_with_tenant`：worker 线程的 Context 停在线程创建那一刻，裸 `.submit(...)` 会把 B 的实验产物写进管理员的 `research_runs_dir()`。


所有 GET 均为只读。`POST /runs`、temporal 写入和研究回测只写 `data/research_runs/` 的 JSON 产物，不写三套业务数据库；`profile` 和 run 均不调用外部网络。temporal 的单条和批量写入均需组合根注入的写权限，且只允许追加或幂等重放。标的/run 不存在返回 `404`，代码格式或预算不合法返回 `422`，不可恢复的缺失阶段或 manifest 不匹配返回 `409`。

研究回测的异步 job 使用研究域 JSON 状态文件，不依赖 `ops` 的 infrastructure。所有写入口都通过组合根注入的 `write_dependency`。回测 run 读取响应给出 `artifact_manifest_sha256`；人工批准或否决请求都需回传该值以及 `reviewer`、`reason`。相同结论可用签署时 manifest 重试；发布后刷新页面得到的当前 manifest 也可重试，但服务端会核验其恰好由签署前产物和固定终态回执组成。终态 run 只允许写入 `workflow-final.json`、`run_card.md`、`replay-comparison.json` 三类审计收尾 artifact；同一路径只有相同 hash 可幂等重放。`replay-comparison.json` 的 artifact hash、回放前完整 manifest、冻结输入 hash 和人工签署时 manifest hash 必须全部匹配；其他新增 artifact、回执结构错误或任一内容篡改都会拒绝重试。`strict_pit=true` 必须提交 `historical_universe_id`，且每个已选成功行情 receipt 都必须有实际来源、`source_url`、`fetched_at`、`as_of`、64 位 `payload_sha256`、`parser_revision`、`published_at`/`available_at`，并将 `publication_status`、`availability_status` 标为 `observed`；缺少完整历史证据会被拒绝。非严格运行保留 warnings 并处于 `degraded/exploratory`，不能作为 hypothesis 通过依据。hypothesis 的人工审核仍独立在服务端核对 completed run、validation、manifest hash、run card 指标和 hypothesis revision。

当前 `backtest-runs` 与 `factor-jobs` 只消费冻结的行情面板和历史股票池。`point-in-time-facts` 的写入/查询 API 是为未来财务或事件因子准备的时点事实登记簿，当前不会被技术回测自动选择、填充或视为严格 PIT 已覆盖；未来 API 必须显式提交并冻结所选 observation/revision/hash，才能把它们加入回测输入。

## PTH252 固定合同

`POST /api/research/factor-jobs` 仅接受 `factor_id="pth252"`、总样本和严格递增的 train/OOS 区间、`historical_universe_id`，以及下列固定值：最高十分位、每 20 个交易日调仓、持有 20 日、最多 20 个按分数排序的标的、`T+1 open`、3 bps 双边佣金、10 bps 卖出印花税、5 bps 双边滑点、基准 `000300`。输入中不得改变这些参数，也不能将候选注册为活动策略。

严格任务在缺少完整 PIT 股票池、行情来源 attempt 或 OHLC 覆盖时必定失败，不会降级为成功。若 run 已在执行阶段生成，job 在 `failed` 状态仍返回 `run_id`，客户端可读取其 `validation.json`、`factor-analysis.json`、`factor-sensitivity.json` 与 `factor-report.md` 诊断原因；这些产物均不构成发布或上线授权。

## 响应约定

每个维度都有 `quality`、`source`、`retrieved_at`、`as_of`、`data_gaps`、`evidence` 和可选 `error`。整体质量包含 `blocked`、`completeness_ratio`、`market_revision`、`market_health`、review rule 版本和修复建议；profile 同时返回本次 `source_attempts`、`requested_as_of` 与 artifact 状态。`blocked` 只表示研究结果不应被标为已核验，不阻止用户查看中间结果。

## 测试

**现状：本层没有测试。** `tests/research/` 目前只有 `test_readonly_engine.py`（22 行，只覆盖 pandas/Polars 等价性），路由、时点事实、成分快照、发布/否决状态机全部零覆盖——这是全仓最大的覆盖空洞，补测试时优先级最高。

新增测试的约定：用临时行情库和注入的 store/artifact factory；不得触发真实行情或 MCP 请求。
