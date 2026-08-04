# Loci Screen Skill 技术设计

> 状态：v5 统一工作台与双运行时核心已实现；厂商方言兼容矩阵仍在扩充  
> 日期：2026-07-30  
> 读者：后端、前端、测试、后续 Coding Agent  
> 类型：Explanation / 技术设计  
> 决策：[`ADR-003`](../adr/ADR-003-screen-skill-formula-runtime.md)、
> [`ADR-004`](../adr/ADR-004-explainable-multi-runtime-screen-skills.md)

## 0. 结论

Screen Skill 的产品目标不是让用户面对一段难懂代码，而是让用户能清楚回答：

1. 这套选股逻辑分几步，每一步为什么成立；
2. 用了哪些行情字段、复权口径和股票范围；
3. AI 或导入转换依据了哪些文档、章节和原文；
4. 最终由哪种运行时执行，哪些语法已验证兼容；
5. 本次运行用的技能版本、参数和数据选择是什么。

因此 v5 采用“**可解释契约 + 多运行时 + 统一执行链**”：

- 前台用中文逻辑脉络、数据和来源帮助理解，中央执行源编辑器仍允许直接修改完整代码。
- `formula` 运行时提供可编译、可诊断的公式子集，并保留 Loci/TDX/THS 输入方言。
- `python` 运行时提供本地程序所需的完整扩展能力。
- 两种运行时都适配为同一个 `StrategyEngine`，复用选股、回测、Job 和候选入库。
- AI 草稿没有详细来源和逐条引用时不视为合格草稿。
- 通达信/同花顺的支持程度由真实编译诊断与样本测试证明，不用一个模糊布尔值宣称。

## 1. 用户体验原则

### 1.1 统一工作台，默认给人看

`/strategy-converter` 是一个 Screen Skill 工作台，不再把编辑、AI、测试拆成彼此孤立的页面：

| 位置 | 当前组件 | 职责 |
|---|---|---|
| 左侧 | `ScreenWorkbenchCatalog` | 从目录 API 浏览函数、日线字段和常用片段，并插入或应用到当前草稿 |
| 中间 | `ScreenWorkbenchEditor` | 编辑当前 formula 或 Python 执行源，并显示字段、参数、窗口和入口摘要 |
| 右侧 | `ScreenAiCopilot` | 基于当前草稿和资料来源提出或应用 AI 修改建议 |
| 底部 | `ScreenSkillTestReport` | 展示编译/试跑诊断、命中摘要、由 IR 或 manifest 生成的中文解释，以及逐条逻辑引用的资料标题、定位和关键引文 |

名称、参数、逻辑、数据和资料来源在 `ScreenSkillSettingsDrawer` 中编辑；它们和中央执行源、AI
建议、目录片段共用同一个 `ScreenSkillDraftModel`，不是独立表单或第二份草稿。

逻辑说明不做第二套 evaluator。实际信号始终来自 formula 或 Python 执行源；底部报告把编译器
派生字段、窗口、因子和试跑结果与说明并排展示，用于发现说明与执行源漂移。

报告从 preview 顶层 `logic[].citations` 与 `references[]` 按 ID 关联资料，不依赖 explanation step
ID；formula 的 compiler step ID 与 manifest 逻辑 ID 没有强制对应关系。即使编译失败、没有生成
中文 explanation，已有逻辑引用仍需展示，避免诊断阶段丢失资料脉络。

### 1.2 人和 AI 共用同一份草稿

前端以 `ScreenSkillDraftModel` 作为单一可编辑状态。人通过左侧目录、中央编辑器或导入改变草稿，
AI 也只返回并应用到这份草稿；保存和预览都从同一个 payload 构造。AI 不能绕过预览直接写入
技能包，也不能在运行期决定信号。

### 1.3 AI 生成是一份有证据的草稿

AI 生成请求必须产出完整技能草稿，而不是只产出公式：

- 逐条逻辑说明；
- 每条逻辑引用的资料 ID；
- 资料 URL 或本地路径、章节和关键摘录；
- 数据字段、复权方式和默认股票池；
- formula 或 Python 执行源；
- 方言、运行时、参数与入场时点。

后端负责结构和引用完整性校验，公式编译器或 Python loader 负责可执行性校验。用户预览后
显式保存，AI 不在运行期决定信号，也不生成权威行情数字。

## 2. 能力矩阵

| 输入/运行方式 | 可创建编辑 | 可预览 | 可选股/回测/Job | 能力边界 |
|---|:---:|:---:|:---:|---|
| Loci formula | 是 | 是 | 是 | 编译器支持的字段与函数 |
| 通达信原稿 | 是 | 是 | 当前编译器通过后是 | 保留 `dialect=tdx`；当前先走公共公式子集，未支持语法给真实诊断 |
| 同花顺原稿 | 是 | 是 | 当前编译器通过后是 | 保留 `dialect=ths`；当前先走公共公式子集，未支持语法给真实诊断 |
| Python | 是 | 是 | 是 | 当前本地 Python 环境与包内模块 |
| 自然语言 + AI | 是 | 是 | 生成源编译/加载通过后是 | 必须有详细引用 |

“支持 TDX/THS”当前指有独立输入入口、保留原始方言，并由同一个公式编译器返回真实结果；
它不等于已有完整厂商兼容层，也不等于无条件执行全部私有函数。遇到未覆盖函数时，用户可
扩充 formula runtime，或转换到 Python runtime。方言专用归一器和真实样本矩阵属于 v5.3。

当前编辑目录来自 `GET /api/screen-skills/catalog`，不是前端复制的常量。目录已公开 26 个可编译
函数、7 个日线字段和 formula/Python 常用片段；“目录出现”只代表当前 Loci formula runtime 已
开放，不能推导为通达信或同花顺所有同名函数、边界条件和画线语义均已兼容。

## 3. 架构

```text
可解释策略工坊
  │  logic / references / data / source
  ▼
src.app.screen_skills
  │  DTO、错误映射、revision、跨上下文编排
  ├──────────────► src.ops.application.screen
  │                技能包发现、原子保存、导入、归档
  │
  └──────────────► runtime dispatcher
                   ├─ formula -> src.formula -> FormulaScreenEngine
                   └─ python  -> package loader -> PythonScreenEngine
                                             │
                                             ▼
                                      StrategyEngine
                                             │
                         ┌───────────────────┼───────────────────┐
                         ▼                   ▼                   ▼
                       screen             backtest             Job
                         │
                         ▼
                    candidate ledger
```

### 3.1 上下文职责

| 上下文 | 负责 | 禁止 |
|---|---|---|
| `formula` | 公式 parser、IR、类型、前视、求值 | 包 IO、数据库、Python loader |
| `strategy` | 两种 runtime 的 `StrategyEngine` 适配、统一目录 | 依赖 `ops`、复制 formula parser |
| `ops` | 文件包、Zip、revision、归档、恢复 | 计算交易信号 |
| `app` | 严格 DTO、runtime 分派、AI/方言草稿编排 | 承载行情公式实现 |
| `market` | 字段面板、股票池解析、复权 | 读取技能包 |
| `ledger` | 候选事实、版本、有效参数 | 编译或执行技能 |

依赖继续满足：

```text
app -> ops public API, strategy public API
strategy -> formula public API, market public API
ops job -> strategy public API
```

## 4. 技能包

```text
<data>/skills/<slug>/
  SKILL.md
  screen.yaml
  formula.tdx              # runtime=formula 时必需
  strategy.py              # runtime=python 时必需
  modules/**/*.py          # Python 可选模块
  ui.json                  # 可选 UI 元数据
  references/**/*          # 可选原始资料

<data>/skill-history/<slug>/<package_revision>.zip
```

### 4.1 SKILL.md

Front matter 保存包级身份：

```yaml
slug: ma-breakout
name: 均线放量突破
description: 收盘站上均线且成交量放大
version: 1.0.0
capability: screen
enabled: true
runtime: formula
dialect: tdx
```

正文是给人的技能摘要，不能替代结构化逻辑和引用。

### 4.2 screen.yaml

```yaml
schema_version: 2
runtime: formula
dialect: tdx
entry_timing: next_open
min_bars: 120
params:
  N: {type: int, default: 20, min: 5, max: 250, label: 均线周期}
output: {signal: PICK}
factors: [BASE_MA, VOL_RATIO]
data:
  fields: [open, high, low, close, volume, amount, turnover]
  adjust: qfq
  universe:
    preset: default_a_share
    boards: [main, chi_next, star]
    exclude_st: true
    min_list_days: 60
    industries_include: []
    industries_exclude: []
    codes_include: []
    codes_exclude: []
logic:
  - id: trend
    title: 站上中期均线
    expression: CLOSE > MA(CLOSE, N)
    explanation: 收盘价高于 N 日均线，确认价格位于中期趋势上方。
    citations: [tdx-ma]
  - id: volume
    title: 成交量放大
    expression: VOL / MA(VOL, 5) >= VOL_MULT
    explanation: 当前成交量相对 5 日均量达到阈值。
    citations: [tdx-vol, strategy-note]
references:
  - id: tdx-ma
    title: 通达信公式系统 MA 函数说明
    kind: official
    path: references/tdx-ma.md
    section: 引用函数 / MA
    quote: 生成时使用的关键原文摘录
  - id: strategy-note
    title: 用户本地策略说明
    kind: local
    path: references/strategy-note.md
    section: 放量条件
    quote: 对应规则原文
```

### 4.3 兼容

- 旧 `schema_version: 1` 公式包继续加载。
- 旧包缺少 `runtime` 时按 `formula`，缺少 `dialect` 时按 `loci`。
- 旧包没有 `logic/references/data` 时详情页显示“待补充”，不伪造来源。
- 新建和 AI 生成默认使用 v2。

## 5. 运行时

### 5.1 Formula

公式公开入口仍只有：

```python
from src.formula import compile_screen_formula, evaluate_screen_formula
```

编译成功后派生：

- `required_fields`
- `min_bars_required`
- `signal`
- `factors`
- `strategy_revision`

函数、字段和片段由 `src.formula.domain.screen_formula_catalog` 集中定义，并通过目录 API 提供给
工作台。当前 formula runtime 开放 26 个函数：`REF`、`MA`、`EMA`、`SMA`、`WMA`、`DMA`、
`SUM`、`HHV`、`LLV`、`STD`、`AVEDEV`、`COUNT`、`EVERY`、`EXIST`、`FILTER`、`BARSLAST`、
`BARSSINCE`、`BARSCOUNT`、`HHVBARS`、`LLVBARS`、`IF`、`ABS`、`MAX`、`MIN`、`CROSS`、
`ZTPRICE`。可用日线字段为 `open/high/low/close/volume/amount/turnover`，公式别名 `VOL/HSL`
分别映射到成交量和百分比口径换手率。

formula 预览会从 Bound IR 确定性生成中文步骤、字段、函数、最少 K 线和入场时点说明；这不是
LLM 翻译，也不应被描述为通达信的完整“动态翻译”兼容。

方言适配器可以做确定性词法归一，但不能吞掉未知函数或悄悄改交易语义。未覆盖项必须以
结构化诊断返回。

### 5.2 Python

默认入口：

```python
def compute(panels: dict[str, pd.DataFrame], params: dict[str, object]):
    return {
        "signals": signals,
        "factors": {"trend": trend, "volume_ratio": volume_ratio},
    }
```

也可返回 `SignalResult`。约束是接口契约，不是能力沙箱：

- `signals` 必须为与输入面板索引/列可对齐的 `Series` 或 `DataFrame`；
- `factors` 的值必须可对齐；
- 未知参数仍由统一 `merge_params` 拒绝；
- 包导入、加载和执行错误返回稳定诊断码，并带入口、包内相对文件与有界 trace 摘要；
- 运行修订必须包含代码、manifest 和 loader 版本。

Python 技能可以 import 当前环境已安装依赖和包内模块。依赖声明用于诊断，不在保存时静默
联网安装；本地环境由用户控制。

## 6. 数据选择

### 6.1 字段

`data.fields` 是 Python runtime 的实际加载字段，也是工作台的数据清单。Formula runtime 以编译器
派生字段为准；若声明清单与派生字段不一致，预览返回 warning，并可由编辑器补齐诊断字段。

基础日线字段：

```text
open high low close volume amount turnover outstanding_share
```

公式别名如 `VOL/HSL` 在 formula adapter 中映射到实际面板字段。新增财务、行业、指数、分钟、
逐笔数据时必须通过 data catalog 注册语义、频率、单位、可用时点和 provider，而不是只给 UI
添加一个字符串。

### 6.2 股票池

默认预设保持保守，但高级用户可覆盖：

- `boards`: `main/chi_next/star/bse`
- `exclude_st/exclude_delisting/exclude_suspended`
- `min_list_days`
- `industries_include/industries_exclude`
- `codes_include/codes_exclude`

运行请求显式传入 `universe` 时覆盖技能默认值；否则使用技能声明；再否则使用系统默认预设。
响应回显最终 `universe` 和漏斗计数。

## 7. 可解释与来源契约

### 7.1 逻辑步骤

每条逻辑包含：

| 字段 | 说明 |
|---|---|
| `id` | 稳定 ID，供引用、diff 和 UI key 使用 |
| `title` | 用户可扫描的规则标题 |
| `expression` | 与代码对应的表达式或函数名 |
| `explanation` | 这条规则的含义和使用原因 |
| `citations` | 指向 `references[].id` |

后端校验引用必须存在。预览可追加以下一致性提示：因子未解释、解释引用的因子不存在、代码
派生字段未在数据清单中。

### 7.2 引用

引用至少包含 ID、标题、类型、定位和原文。网络资料用 URL，本地资料用包内 path；`section`
和 `quote` 让用户无需重新搜索整篇文档。引用参与 `package_revision` 和历史归档。

描述生成要求至少一条引用、每条逻辑至少一条 citation。生成服务以用户提交的 `references` 覆盖
模型返回的引用，避免模型改写摘录或补造来源；手工创建允许先保存“待补充”草稿，但 UI 必须显式
展示来源完整度，不能标成“AI 已核验”。

## 8. API

| 方法 | URL | 行为 |
|---|---|---|
| `GET` | `/api/screen-skills` | 列出 formula/python 技能及 runtime/dialect |
| `GET` | `/api/screen-skills/catalog` | 返回运行时、方言、26 个公式函数、日线字段和常用片段目录 |
| `GET` | `/api/screen-skills/{slug}` | 返回当前草稿、manifest、执行源与 revisions |
| `POST` | `/api/screen-skills/preview` | 校验、加载并可选小范围试跑，不落盘 |
| `POST` | `/api/screen-skills` | 创建并刷新统一目录 |
| `PUT` | `/api/screen-skills/{slug}` | `expected_revision` 乐观锁更新 |
| `DELETE` | `/api/screen-skills/{slug}` | 归档后删除 |
| `POST` | `/api/screen-skills/import` | 导入完整技能包 |
| `POST` | `/api/screen-skills/generate` | description/tdx/ths/python 生成或归一草稿 |

Preview 成功示意：

```json
{
  "ok": true,
  "diagnostics": [],
  "runtime": "python",
  "dialect": "python",
  "derived": {
    "required_fields": ["close", "volume"],
    "min_bars_required": 120,
    "signal": "PICK",
    "factors": ["trend", "volume_ratio"]
  },
  "data": {"adjust": "qfq", "universe": {"preset": "default_a_share"}},
  "package_revision": "...",
  "strategy_revision": "...",
  "run_result": null
}
```

## 9. 保存、版本与恢复

| 字段 | 语义 |
|---|---|
| `version` | 作者声明的人类版本 |
| `package_revision` | 包内全部文件内容哈希；并发与归档 |
| `strategy_revision` | runtime/loader/compiler、执行源、manifest 语义哈希 |
| `effective_params` | 本次实际参数 |
| `effective_universe` | 本次实际股票池 |
| `adjust` | 本次复权口径 |

`data_snapshot` 当前同时记录 `quotes`、`adjust_factors`、`instruments` 三段水位并生成
`market_revision`。复权因子值或证券元数据单独变化也会改变 revision；provider、字段映射版本
仍属于 v5.4 数据血缘扩展。

保存继续使用 staging、完整回读、旧包归档、同盘原子换盘和失败恢复。Formula/Python 仅改变包内
必需文件，不复制两套 revision/归档实现。

## 10. 安全与本地能力边界

本产品是本地程序，因此 Python runtime 提供当前本地 Python 环境和包内模块的完整能力，不做
“只能算几个白名单函数”的限制。它不是互联网多租户沙箱；仅有文件包工程完整性约束：

- 路径必须位于技能包内，拒绝 zip-slip 和符号链接；
- 保存、删除、导入必须可恢复；
- Formula 与 Python 加载错误显式失败；
- 不自动执行压缩包安装脚本，不静默安装依赖；
- UI 明确显示运行时和代码，用户知道自己正在运行什么。

## 11. 实施阶段

### v5.1 可解释契约

- 扩展 DTO、包记录、详情和 preview。
- AI prompt 强制逻辑、数据、引用。
- 前端完成逻辑/数据/来源/代码四视图。
- 股票池增加北交所显式选择与行业包含/排除。

### v5.2 Python 主能力

- `PythonScreenEngine`、包内模块加载、入口校验。
- 无数据预览也会导入模块并解析 callable，提前暴露语法、导入和入口错误；只有试跑才调用计算函数。
- CRUD、preview、screen、backtest、Job 全链复用。
- Python 模板和回归测试。

### v5.3 方言兼容库

- TDX、THS 独立 adapter 与诊断编号。
- 收集用户真实公式样本，按函数/语法建立兼容测试矩阵。
- 未支持项可转换到 Python，但保留原稿、转换说明和引用。

### v5.4 数据目录与血缘

- 注册更多数据集及字段语义。
- 运行结果记录 provider、数据更新时间、复权与字段映射版本。
- 候选和回测详情展示同一 data snapshot。

## 12. 验证矩阵与验收边界

| 验收项 | 已实现证据 | 已执行验证 | 不可据此承诺 |
|---|---|---|---|
| 统一工作台 | 左目录、中执行源编辑器、右 AI、底部报告与设置抽屉共享 `ScreenSkillDraftModel` | 桌面/移动端完成目录插入、双正文切换、片段、设置、编译报告和抽屉交互；CRUD/回读由 API 测试覆盖 | 不把多个界面区域等同于多套执行逻辑 |
| formula | 编译器、39 函数目录、IR 中文解释、预览诊断 | 39 函数编译与向量求值对拍，未知函数、前视、窗口和标量参数边界均有回归 | 不宣称完整 TDX/THS 语法或指标绘图兼容 |
| Python | `strategy.py:compute`、包内模块、统一选股/回测/Job 链路 | 创建、更新、导入和预览均验证语法、导入、入口 callable；浏览器编译返回 manifest 中文逻辑 | 不宣称沙箱或第三方依赖自动安装 |
| 数据选择 | 字段、复权和股票池写入 manifest；预览回显有效数据要求 | 浏览器核对字段、复权、板块、ST/退市/停牌、上市天数、代码和行业包含/排除；API 覆盖请求回显 | 不把 UI 声明误称为任意外部数据源能力 |
| AI 来源 | reference 定位校验、logic citation 校验、用户来源覆盖模型来源 | 缺引用和未知引用有回归；编译报告实测展示资料 ID、标题、path、section 和 quote | 不把 citation 当作事实正确性背书 |
| TDX/THS 导入 | 保留 `dialect`，共享 formula 编译器和诊断 | 公共公式子集由目录和编译测试覆盖；方言保留与失败诊断有 API 回归 | 不承诺厂商全函数、专家系统、五彩 K 线或画线指标等价 |

## 13. 后续工作

1. 使用真实 TDX/THS 样本建立按函数、语法、输出形态和边界值划分的兼容矩阵。
2. 在可写测试环境运行后端专项、`lint-imports`、前端 typecheck/test/build，并完成两种视口的浏览器验收。
3. 如 Python runtime 的使用范围从可信本地用户扩展到不可信来源，再单独设计进程隔离、资源限制和权限边界；当前设计不包含该承诺。

`lint-imports` 已运行，但当前工作树中既有的
`src.review.application.outcomes -> src.ledger.infrastructure.store_types` 跨上下文导入导致失败；
该问题不在 Screen Skill v5 改动范围内，因此本轮不将整项 DoD 标为通过。

## 14. Definition of Done

- [x] 一个统一工作台承载人工编辑、AI 修改、Formula/Python 执行源、设置和测试报告。
- [x] Formula 目录公开 26 个已实现函数，编译器、IR 中文解释和向量 evaluator 通过专项回归。
- [x] Python 使用本地完整运行时；创建、更新、导入和预览都会加载模块并校验入口。
- [x] `logic`、逐条 `citations`、可定位 `references`、数据字段、复权和股票池进入同一 manifest。
- [x] 报告在编译成功或失败时都能从 `logic[].citations` 解析并展示资料定位，不依赖 compiler step ID。
- [x] 前端全量 31 项测试、`vue-tsc --noEmit` 和生产构建通过；运行时切换入口均复用规范化逻辑；后端全量 470 项测试与 180 个子用例通过。
- [x] 1280×720 与 375×812 浏览器验收通过：核心交互可用，无文档级横向溢出、无控件重叠、无 console error。
- [x] 本功能文件均不超过 600 行，功能范围 `git diff --check` 无空白错误。
- [ ] 全仓 `lint-imports` 尚有一条既有跨上下文违规；8 个其余契约已通过，本功能未新增违规。

TDX/THS 厂商完整兼容矩阵、更多数据源/频率和不可信 Python 的进程隔离属于后续版本，明确不作为
本版本完成条件。
