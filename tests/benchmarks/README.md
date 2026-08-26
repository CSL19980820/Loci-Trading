# 性能基线

## 职责

用固定种子生成脱敏 OHLCV 与候选池，在 `tests/conftest.py` 的临时数据根下显式运行生产读路径和计算路径，输出可归档的 JSON 基线。

## 如何运行

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/benchmarks/baseline_benchmark.py --tb=line
```

普通 `pytest tests/` 不会自动收集该基线；产物默认写入被忽略的 `output/benchmarks/performance-baseline.json`，可用 `LOCI_BASELINE_ARTIFACT` 指定 CI 归档路径。

可选只读引擎对照（需已安装 Polars；`requirements.txt` 已列 `polars>=1.0.0`）：

```powershell
$env:LOCI_POLARS_BENCHMARK_ARTIFACT='output/benchmarks/polars-poc.json'
.\.venv\Scripts\python.exe -m pytest -q tests/benchmarks/polars_benchmark.py --tb=line
```

闸门解读见 [`docs/research/2026-08-phase2-evidence.md`](../../docs/research/2026-08-phase2-evidence.md)。

## 覆盖范围

基线记录输入 SHA-256、p50/p95、错误率、进程峰值 RSS，并覆盖 market panel、研究 profile、经典/快速回测、K 线维度、1000/5000 行候选池以及进程内和 SQLite Job 锁等待。
