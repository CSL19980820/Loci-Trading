# Loci 地基夯实后 · 前进方向（2026-07）

> P0 POC + 地基 + 下一批 + **下一轮选型包**已落地。下文保留「明确仍不做」与更远可选。

## 已落地

| 项 | 状态 | 入口 / 开关 |
|---|---|---|
| Lw K 线 | **默认开** | `loci.market.useLwChart`（从未写过 key 时为 `true`；已有偏好不覆盖） |
| Pool `el-table-v2` + Colada quotes / candidates | 已上 | `useQuotesQuery` / `useCandidatesQuery` |
| Colada 只读扩面 | 已上 | equity / trips / outcomes / screen history / jobs / runs |
| DuckDB `load_panel` 旁路 + ADR-002 | 默认关 | `LOCI_MARKET_DUCKDB=1`；对照测见下 |
| 回测加速旁路 | 默认关 | `LOCI_BACKTEST_FAST=1`；对照测见下 |
| 指标 Web Worker + Comlink | 已上 | `prepChartOffthread` |
| Ops Monaco | 已上 | `features/ops/components/CodeEditor.vue`（技能 config / Job JSON） |
| async 审计文档 | 已写 | `2026-07-async-route-audit.md` |
| `lint-imports` | 9 合约 | 本地 + CI |
| Vitest + Playwright | 已上 | `bun run test` / `test:e2e`；CI 含 e2e job |
| rolldown-vite 试构建 | 并行 | `bun run build:rolldown` |
| GitHub Actions CI | 已上 | `.github/workflows/ci.yml`（python / frontend / e2e） |

## Lw K 线默认开

- **默认**：`useLocalStorage('loci.market.useLwChart', true)` — 仅当浏览器从未写过该 key 时为开。
- **关回 ECharts**：详情面板右上角开关切到 `EC`（写入 localStorage `false`）。
- **验收清单**
  - [ ] 首次打开（无该 key）主图为 Lightweight Charts
  - [ ] 十字线跟随、滚轮/捏合缩放可用
  - [ ] 副图指标（MACD/KDJ）在 ECharts 路径仍可用；Lw 路径以 POC 能力为准
  - [ ] 切到 EC 后刷新仍保持 ECharts（偏好已持久化）

## DuckDB / 快回测对照测法

- DuckDB：`tests/market/test_duckdb_panel.py` — 未装 duckdb 则 skip；装了则同夹具经典 vs `LOCI_MARKET_DUCKDB=1` 对齐。
- 快回测：`tests/backtest/test_fast_engine.py` — hold 场景 fast vs 经典关键字段一致；有止损止盈必须回退经典。
- **允许的差异**：fast 的 `config.engine` 可为加速引擎名；交付结论前用经典路径复核。

## 更远可选（非本轮）

- Taskiq（仅 ops 真排队时）
- Polars 面板实验（与 DuckDB 二选一）
- Lw 副图能力对齐 ECharts
- StrategyConverter 大段编辑是否也上 Monaco

## 明确仍不做

换 Nuxt/React、整库 shadcn、palace→PG、AI 权威数字、恢复旧报告链。
