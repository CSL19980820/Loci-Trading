# 2026-08 Phase 2 证据快照（31–60 天闸门）

> 采集日：2026-08-08（本机 Windows）。输入为合成脱敏样本，**不**代表全市场热路径；用于闸门决策，不替代持续两周对照。

## 1. 性能基线（`tests/benchmarks/baseline_benchmark.py`）

产物：`output/benchmarks/performance-baseline.json`（gitignore；可用 `LOCI_BASELINE_ARTIFACT` 改路径）。

| 用例 | p50 ms | p95 ms |
|---|---:|---:|
| market_panel_64x240 | 59.6 | 64.4 |
| market_panel_256x240 | 230.1 | 237.9 |
| research_profile | 67.8 | 69.9 |
| backtest_classic | 14.4 | 16.6 |
| backtest_fast | 13.4 | 14.1 |
| kline_dimension | 9.2 | 13.1 |
| candidate_pool_1000 | 51.3 | 53.1 |
| candidate_pool_5000 | 340.8 | 366.3 |
| market_slot_lock_wait | 20.6 | 20.9 |
| job_claim_lock_wait | 31.0 | 31.7 |

- `summary.errors = 0`；进程峰值 RSS ≈ 215 MiB（`process_peak_rss_bytes`）。
- 环境：Python 3.12 / pandas 3.0 / Windows AMD64。

## 2. 只读引擎对照（`tests/benchmarks/polars_benchmark.py`）

产物：`output/benchmarks/polars-poc.json`（`LOCI_POLARS_BENCHMARK_ARTIFACT`）。夹具约 8×32；三引擎结果 hash 一致。

| 引擎 | p50 ms | p95 ms | 数值 hash |
|---|---:|---:|---|
| pandas | 7.9 | 8.9 | 一致 |
| polars | 9.1 | 12.6 | 一致 |
| duckdb | 60.2 | 71.3 | 一致 |

**闸门结论（本轮）**

- 小面板上 pandas 仍最快；Polars 数值对齐但无 p95/RSS 明确优势。
- **不默认开启** `LOCI_MARKET_POLARS` / `LOCI_RESEARCH_POLARS`；保留旁路与回退。
- DuckDB 继续按 ADR-002 仅在大面板/热读有证据时用 `LOCI_MARKET_DUCKDB=1`。
- 默认化条件仍是：更大真实窗口连续两周稳定优于 pandas，且回滚开关可用。

## 3. 前端包体（`bun run build`，rolldown-vite 7.3）

主体积集中在 Monaco / 入口：

| chunk | raw | gzip |
|---|---:|---:|
| `editor.api-*.js` | ~2657 kB | ~684 kB |
| `index-*.js` | ~2026 kB | ~658 kB |
| `toggleHighContrast-*.js` | ~1167 kB | ~294 kB |
| `QuantView-*.js` | ~219 kB | ~62 kB |
| `OpsView-*.js` | ~77 kB | ~23 kB |
| `BasicTable-*.js` | ~15 kB | ~5.5 kB |
| `PoolView-*.js` | ~9 kB | ~3.7 kB |

**闸门结论**

- 虚拟表本身不构成主包体问题；瓶颈是 Monaco（Ops）与入口聚合。
- 下一刀优先：Monaco 语言 worker / 高对比主题的更懒加载，而不是换表格体系。
- `bun run build:rolldown` 仍作并行试构建，不替换默认 `build`。

## 4. Job / 行情锁等待观测

- 基线已含 `market_slot_lock_wait` / `job_claim_lock_wait`。
- 生产路径：`market_heavy_slot`、`market_write_lock` 在 `LOCI_OBSERVABILITY=1` 时写入
  `loci.lock.wait_ms` / `loci.lock.acquire`（标签仅 `component/kind/operation/outcome/reason`）。
- 超时/busy 另打结构化事件 `market_gate_lock_timeout` / `market_write_lock_busy`。

## 5. 明确仍不做（本阶段）

- 不默认 Polars / DuckDB；不引入 Taskiq / FastMCP（无 API/UI 被长任务拖死或 MCP 对外暴露证据）。
- 不换框架、不迁 palace、不加第二套表格库。

## 复现

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/benchmarks/baseline_benchmark.py --tb=line
$env:LOCI_POLARS_BENCHMARK_ARTIFACT='output/benchmarks/polars-poc.json'
.\.venv\Scripts\python.exe -m pytest -q tests/benchmarks/polars_benchmark.py --tb=line
cd frontend; bun run build
```
