# ADR-010：2026-08 基线、可观测、虚拟表与 Polars 旁路

**状态**：已采纳  
**日期**：2026-08-08  
**相关**：`2026-08-github-open-source-technology-radar.md`（已从仓库移除，可在提交 d05e02d 中查看）、[`ADR-002`](ADR-002-duckdb-readonly-panel.md)

## 背景

技术雷达筛出一批可落地候选后，需要先建立可复现基线与可回滚增强，而不是换框架/换库。现有 SQLite 三库、Vue + Element Plus、APScheduler 单机边界保持不变。

## 决策

1. **性能基线**：`tests/benchmarks/` 用固定种子脱敏 OHLCV，显式跑生产读路径；产出 JSON（p50/p95、RSS、输入 hash、锁等待）；不进入默认 `pytest tests/` 收集。
2. **CI 供应链**：在 `.github/workflows/ci.yml` 增加独立、可回滚的报告型 job（基线、ruff report-only、uv 临时安装验证、pip-audit/SBOM、gitleaks、zizmor）；不改变默认 `requirements*.txt` / `.venv` 入口。
3. **可观测性**：`src.shared.observability` 提供 `trace_id/run_id/job_id/source_id/tool_receipt_id`；默认关闭。`LOCI_OBSERVABILITY=1` 才写本地 JSON 日志与内存 metrics；`LOCI_OBSERVABILITY_OTEL=1` 才桥接宿主 OTel（不配置 exporter）；`LOCI_OBSERVABILITY_EXPOSE=1` 才在响应返回 `X-Loci-Trace-ID`。
4. **大表虚拟化**：`BasicTable` 增加 `virtualized`，内部用 Element Plus `el-table-v2`；候选池与 Job 历史传完整数据 + 虚拟滚动。不兼容列自动回退经典 `el-table`；不引入第二套 UI。
5. **Polars 只读旁路**：`LOCI_MARKET_POLARS=1` / `LOCI_RESEARCH_POLARS=1` 时尝试 Polars；未安装或失败回退 pandas/DuckDB；不写 `palace.db`，不改变权威 DTO。默认关闭，需基准证明后再讨论默认开启。
6. **Taskiq / FastMCP**：本轮不引入。仅在长任务阻塞或 MCP 对外暴露有明确证据时再 POC。

## 后果

- 优点：增强可测、可回滚，不破坏 DDD/三库/单机桌面边界。  
- 约束：报告型 CI 不阻断主绿；Windows 下 pip-audit 需 `PYTHONUTF8=1`；Polars/虚拟表收益需实盘数据与 WebView2 再验收。  
- Phase 2 快照（2026-08）：小面板对照 pandas < polars ≪ duckdb（数值 hash 一致），**不默认开 Polars**；前端体积瓶颈在 Monaco/入口而非 `BasicTable`；锁等待经 `record_lock_wait` 记入 opt-in metrics。详见 [`2026-08-phase2-evidence.md`](../research/2026-08-phase2-evidence.md)。  
- 测试：`tests/benchmarks/`、`tests/shared/test_observability.py`、`tests/ops/test_market_gate_lock_metrics.py`、`tests/market/test_polars_panel.py`、`frontend/.../BasicTable.virtual.test.ts`、Playwright smoke。
