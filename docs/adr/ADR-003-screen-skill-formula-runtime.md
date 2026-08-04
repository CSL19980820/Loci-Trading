# ADR-003：Screen Skill 公式运行时归属 `src.formula`

> 状态补充（2026-07-29）：公式运行时的单一归属决定继续有效；“Screen Skill
> 不执行 Python”的产品限制由 [ADR-004](ADR-004-explainable-multi-runtime-screen-skills.md)
> 取代。Python 是并列的本地运行时，不在 `src.formula` 内实现。

**状态**：已采纳  
**日期**：2026-07-29  
**相关**：[`screen-skill-tech-design.md`](../architecture/screen-skill-tech-design.md)、[`src/formula/README.md`](../../src/formula/README.md)、[`src/strategy/README.md`](../../src/strategy/README.md)

## 背景

Screen Skill 需要把 `formula.tdx` 编译成可执行信号。早期接入曾在 `strategy/application/screen_formula.py` 内同时实现 parser、类型判断和 evaluator，虽然能快速接入选股链路，但会与 `src.formula` 的向量函数形成两套语义来源。

双实现会导致：

- 同名函数在公式工坊与内置公式中出现 NaN、窗口或边界差异。
- 前视审计、资源限制和错误码只能在一条路径生效。
- 扩展函数时需要同步修改多处注册表，容易静默漂移。
- `strategy` 同时承担语言运行时与业务适配，职责边界失真。

## 决策

1. Screen Formula 的 parser、IR、类型检查、窗口推导、前视审计、函数注册和 evaluator 只在 `src.formula` 实现。
2. `src.formula` 通过 `compile_screen_formula()` 和 `evaluate_screen_formula()` 暴露稳定公共 API。
3. `src.strategy.application.screen_formula` 只负责：
   - 将 Screen Skill 顶层 payload 归一为 `ScreenFormulaManifest`；
   - 把 formula 错误转换为 strategy 错误；
   - 把编译结果适配成 `FormulaScreenEngine` / `SignalResult`。
4. P0 函数必须路由到 `src.formula` 既有向量实现，并用 NaN、窗口边界和形状对拍测试锁定语义。
5. 未注册函数显式拒绝；禁止 `eval`、`exec`、动态 import 或任意脚本回退。
6. `strategy_revision` 由 compiler 版本、规范化公式和 manifest 语义共同计算；修改编译语义时必须更新 compiler 版本或保持兼容性证明。

## 方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| parser/evaluator 留在 `strategy` | 接入改动少 | 语义重复、边界混乱 | 拒绝 |
| 抽成独立顶级 language context | 边界最纯 | 当前规模下目录与依赖成本过高 | 暂不采用 |
| 归属 `src.formula`，strategy 薄适配 | 复用向量语义、依赖清晰 | formula 公共 API 需要稳定维护 | 采用 |

## 后果

### 正面

- 公式工坊、选股、回测和 Job 共用同一语言语义。
- 前视审计、资源限制、参数校验和诊断码集中维护。
- `strategy -> formula` 符合模块职责，`strategy` 保持业务适配层。
- 扩展函数只需注册一次，并可与既有向量实现直接对拍。

### 负面

- `src.formula` 的公共 API 成为跨上下文契约，变更需要兼容性与回归测试。
- P0 不承诺完整通达信兼容；未支持公式需要显式扩展，不能静默降级。
- compiler 语义变化可能改变 `strategy_revision`，必须在发布说明中声明。

### 中性

- Screen Skill 的文件发现和持久化仍归 `ops`，不因公式运行时迁移而改变。
- `ui.json` 不参与公式求值；未来条件树能力需要单独决策。

## 验证

- `tests/formula/test_screen_formula.py` 覆盖函数对拍、前视矩阵、资源限制与运行护栏。
- `tests/strategy/test_screen_formula_engine.py` 覆盖薄适配和 revision 稳定性。
- import 边界继续由 `lint-imports` 约束。
