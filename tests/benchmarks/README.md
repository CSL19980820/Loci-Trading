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

## 阻断条件

`performance_budgets.json` 是版本化的资源上限。每个场景须完成至少 5 次采样，
预热和采样均无错误，耗时和 RSS 为有效正数，P95 与进程峰值 RSS 不得超过上限。
场景集合必须完整，经典/快速回测在相同 fixture 下的结果必须一致。
基线产物先保存再校验，失败时仍可查看超限值。门禁自身的失败注入测试由普通测试套收集。

首批阈值是 256 只 × 240 日合成场景的宽松退化上限，不代表生产延迟承诺，
也不能覆盖全市场、真实战法与并发压力。RSS 是整个基线进程历史峰值，不能把
两次峰值之差当成某场景的内存分配量。调整上限必须附同环境前后测量及原因。

基线另含 2000 只证券 × 370 根日线的潜龙 V3 计算、全分片动态审计，以及含止损的 14772 笔合成成交。各项预热后采样 5 次；这是生产算法上的合成负载，不是生产吞吐或 SLA。`classic/fast` 对照只检查兼容入口结果，成交正确性还依赖边界用例与旧版本逐笔对照。
