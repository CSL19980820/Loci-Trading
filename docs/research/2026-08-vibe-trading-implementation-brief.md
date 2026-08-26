# Vibe-Trading 调研建议实施 Brief

## Goal

- 要达成的结果：把研究运行的行情证据、PIT 时点约束、历史股票池、run card、验证门禁和人工发布闭环落入 stock-analyzer 的真实代码与界面。
- 用户价值：任何研究结论都能回答使用了什么数据、当时是否可见、股票池是否有生存者偏差、是否经验证和人工审核。
- 不在本次范围内的结果：不修改四战法默认参数；不下载或写入真实行情；不接入交易账户、影子账户或外部写入型 MCP；不把 Vibe-Trading 的跨市场回退链、缓存或 LLM 交易链路搬入本仓。

## Context

- 相关系统：`src/market/` 作为行情仓，`src/research/` 作为研究账本，`src/backtest/` 提供回测，`frontend/src/features/research/` 提供操作界面。
- 一手研究依据：[数据层源码审计](2026-08-vibe-trading-data-layer-audit.md) 和 [数据层一手证据](2026-08-vibe-trading-data-layer-source-evidence.md)，外部对象固定为 Vibe-Trading commit `3a752d5`。
- 已知事实：当前工作树已有 provenance receipt、PIT/历史股票池、run card、人工否决以及前端研究面板的未提交实现，必须以代码、测试和浏览器结果复核，不能按意图判定完成。
- 约定：保持 DDD 依赖方向；本次不污染真实 `data/`；所有研究回测都必须预先声明完整、无重叠的 train/OOS 区间；严格 PIT 缺少可验证事实时拒绝，非严格研究必须带可见的降级警告。

## Constraints

- 可修改范围：`src/market/`、`src/research/`、必要的 `src/backtest/` 与 legacy API 适配、`frontend/src/features/research/`、对应测试和准确文档。
- 禁止修改范围：策略默认参数、真实行情数据库、交易/账户外部状态、无关业务模块和用户已有无关改动。
- 数据边界：缓存、来源名、HMAC 不得被表述为行情数据版本；没有同步层实际 telemetry 时必须显式标记为未观察，不能伪造失败链。
- 运行边界：优先复用已启动的本项目服务；仅在验收必要时启动并在完成后停止本次启动的服务；不安装或运行外部项目的数据下载。

## Done

| 验收项 | 验证方法 | 预期证据 | 状态 |
| --- | --- | --- | --- |
| 行情来源证据可进入研究输入 | 市场单测和 run card 序列化检查 | 来源、覆盖率、未解析标的、OHLC 异常及未观测 attempts 的结构化快照 | 已通过：`test_provenance.py`、`test_source_receipts.py`、`test_source_receipt_ohlc.py` 与全量后端测试覆盖；receipt/attempt 作为 `data_snapshot.source_evidence` 冻结。 |
| 严格 PIT 和历史股票池不能前视 | research API/领域/回测测试 | `available_at`、修订、历史成员快照；严格模式对缺失或降级输入拒绝 | 已通过：`test_temporal.py`、`test_temporal_api.py`、`test_backtest_run.py` 覆盖时点选择、历史快照缺失/降级拒绝和 API 边界。真实 PIT 事实仍必须由后续受证据约束的导入提供。 |
| 回测阶段没有训练/OOS 数据穿透 | research 回测支持测试 | 价格面板、signals、benchmark、股票池 mask 同步切分并在执行前对齐校验 | 已通过：`test_backtest_support.py`、`test_frozen_replay.py` 覆盖冻结面板、切片对齐与 OOS 仅消费冻结切片。 |
| run card、验证与人工结论形成闭环 | research 工作流和 publication 测试 | 不可变输入 hash、验证结果、DAG blocked、publish/reject 终态和 replay | 已通过：`test_backtest_run.py`、`test_workflow.py`、`test_publication_rejection.py` 覆盖 artifact hash、验证门禁、人工签署、否决和重放。 |
| 前端可完成历史数据导入、严格回测、审核和回放 | 类型检查、单测、构建及浏览器桌面/移动验收 | 真实 API 调用、错误呈现、`awaiting_human_review`、publish/reject 状态可见 | 已通过：`bun run typecheck`、Vitest `86 files / 267 tests`、`bun run build`，以及 `e2e/research.spec.ts` 桌面和 390px 移动端两项 Chromium 验收。 |
| 文档与实现一致且不超范围 | README/架构文档核对、`git diff --check` | API、严格/降级语义、数据边界准确，未改策略默认值或真实数据 | 已通过：`compileall`、`lint-imports`（9 kept / 0 broken）、`git diff --check`、本次范围内文件均不超过 600 行；未改 `src/strategy` 默认实现，未触碰真实行情或外部账户。 |

## 执行与交付

- 文件所有权：市场 provenance 由市场专项负责；研究前端由前端专项负责；主控负责研究后端集成、文档、跨端验收和最终审查。
- 风险：现有改动均未提交；历史股票池和 PIT 事实的真实性依赖后续导入的数据源，系统只能对证据存在性实施严格门禁，不能凭空提供历史事实。
- 最终交付：仅报告已改内容、实际验证结果和仍需外部数据支撑的风险。
