# ADR-004：可解释的多运行时 Screen Skill

- 状态：Accepted
- 日期：2026-07-29
- 决策者：Loci maintainers
- 取代范围：ADR-003 中“Screen Skill 不执行 Python”的产品限制
- 保留范围：ADR-003 对 formula parser、IR、前视审计与 evaluator 单一归属的决定

## 背景

Screen Skill v4 已经打通公式包的 CRUD、编译、预览、选股、回测、Job、候选入库、
revision 和历史归档。但它仍有三个产品缺口：

1. 前台主要展示公式源码，普通用户无法快速读懂每条规则为什么存在、何时成立。
2. AI 草稿只有生成结果，没有逐条引用、原文摘录和假设，无法核对依据。
3. 数据范围主要在运行入口临时选择，技能自身没有声明字段语义、复权口径和默认股票池。

同时，本地高级用户需要完整 Python 能力，并希望导入通达信、同花顺公式。单纯扩大公式
白名单不能同时满足可读性、兼容性与扩展性。

## 决策

### 1. Screen Skill 以可解释契约为产品主模型

每个技能必须能表达四类信息：

- `logic`：按用户阅读顺序排列的规则步骤，包含标题、表达式、中文解释和引用 ID。
- `references`：资料标题、类型、URL/本地路径、章节、关键摘录。
- `data`：字段、复权方式和默认股票池。
- `runtime`：真正执行信号的运行时及入口。

公式或 Python 代码是执行源，不是前台唯一语义。前台以一个统一工作台承载同一份草稿：左侧目录
插入函数/字段/片段，中间编辑完整执行源，设置抽屉维护参数、逻辑、数据和来源，右侧 AI 只修改
当前草稿，底部报告展示中文 IR 解释、诊断和试跑结果。`logic` 不参与执行，避免出现第二套计算
真相；预览必须把它和编译器实际派生的字段、因子、窗口并排展示，以便发现描述漂移。

### 2. 支持 formula 与 python 两种运行时

`runtime: formula`：

- 继续由 `src.formula` 唯一负责 parser、IR、类型、前视与 evaluator。
- `dialect` 记录 `loci`、`tdx` 或 `ths`，用于导入、诊断和原文追踪。
- 当前可执行集合以编译器实际通过为准。目录 API 公开 26 个已开放公式函数、7 个日线字段和
  常用片段；不通过时返回结构化诊断。

`runtime: python`：

- 运行本地技能包中的 `strategy.py`，默认入口为 `strategy.py:compute`。
- 可使用当前 Python 环境中的 `pandas`、`numpy` 和已安装本地依赖，也可拆分包内模块。
- 入口接收 `panels` 与有效参数，返回 `SignalResult`，或返回包含 `signals`、`factors` 的映射。
- `required_fields`、`min_bars`、参数和入场时点仍由 manifest 声明，统一接入既有
  `screen/backtest/job/candidate` 链路。

这是本地单机产品的显式能力选择。Python 技能拥有与本地进程相同的文件、网络和解释器
能力；Loci 不把它描述成沙箱。包来源和代码内容由用户自己负责，平台负责可追踪、可回滚、
可诊断。

### 3. 方言与运行时分离

`dialect` 描述用户输入的语言，`runtime` 描述最终执行方式。通达信或同花顺原稿可以：

- 在 formula 编译器支持时直接以 `runtime: formula` 执行；
- 在公式函数不兼容时转换成 `runtime: python`，同时保留原稿和转换说明；
- 无法可靠转换时停留为带诊断的草稿，不能伪装成已兼容。

因此“支持通达信/同花顺”不是一个布尔值。API 和 UI 必须展示 `dialect`、编译诊断与实际
`runtime`。兼容率只能由真实公式样本测试库证明；当前不承诺厂商全函数、画线指标、专家系统或
五彩 K 线等价。

### 4. AI 生成必须带来源

自然语言生成的草稿必须同时返回：

- 至少一条 `reference`；
- 每条逻辑规则的 `citations`；
- 可定位的 URL 或本地路径、章节和关键摘录；
- 数据字段与复权口径；
- 生成的执行源与实际运行时。

模型输出缺少这些字段时，后端模型校验拒绝该草稿。生成服务以用户提交的 references 覆盖模型
输出，避免模型改写或补造来源。引用只代表“生成时依据”，不代表内容天然正确；用户仍需预览并
显式保存。

### 5. 数据选择是技能契约的一部分

技能声明 `data.fields`、`data.adjust` 和 `data.universe`。运行请求仍可覆盖股票池，但响应必须
回显最终生效的股票池、字段、窗口和复权口径。股票池支持：

- 主板、创业板、科创板、北交所任意组合；
- ST、退市、停牌、上市天数；
- 行业包含/排除；
- 代码包含/排除。

默认预设继续剔除 ST 且不含北交所；高级用户可显式解除，不设置不可绕过的领域硬编码。

## 包契约

```text
<data>/skills/<slug>/
  SKILL.md
  screen.yaml
  formula.tdx              # runtime=formula
  strategy.py              # runtime=python
  modules/**/*.py          # python 可选
  ui.json                  # 可选 UI 元数据
  references/**/*          # 可选原始资料
```

`screen.yaml` 语义示意：

```yaml
schema_version: 2
runtime: python
dialect: python
entrypoint: strategy.py:compute
entry_timing: next_open
min_bars: 120
params: {}
output: { signal: PICK }
factors: [trend, volume_ratio]
data:
  fields: [open, high, low, close, volume, amount, turnover]
  adjust: qfq
  universe:
    preset: default_a_share
logic:
  - id: trend
    title: 趋势向上
    expression: close > ma(close, 20)
    explanation: 收盘价站上 20 日均线。
    citations: [tdx-ma]
references:
  - id: tdx-ma
    title: MA 移动平均函数说明
    kind: official
    path: references/ma-function.md
    section: MA
    quote: MA(X,N) 返回 X 的 N 周期简单移动平均。
```

`schema_version: 1` 公式包继续可读；保存后的新包使用 v2 契约。

## 统一执行链

```text
可解释编辑器
  -> 严格 DTO
  -> runtime dispatcher
       -> formula compiler/evaluator
       -> python package loader
  -> StrategyEngine
  -> screen / backtest / job
  -> picks + factors + revisions + effective data selection
  -> candidate persistence
```

运行入口不得按 runtime 各写一套选股、回测或候选入库逻辑。

工作台通过 `GET /api/screen-skills/catalog` 获取运行时、方言、公式函数、字段和片段目录；目录
是 UI 与 formula 编译器共享的事实源，不由前端复制函数白名单。

## 后果

### 正向

- 普通用户先读逻辑和来源，高级用户仍能查看并修改完整代码。
- Python 提供本地能力上限，公式运行时提供确定性诊断和方言导入体验。
- AI 草稿具备可核对证据，不再只给一个“编译通过”的黑盒结果。
- 数据范围随技能版本归档，回测和正式运行更容易复现。

### 代价

- `logic` 与执行源可能漂移，必须通过预览派生信息和测试提示，而不能假设二者天然一致。
- Python 预览会导入模块并校验 callable，可提前发现语法、导入和入口错误；数据相关错误仍只能在
  试跑或正式执行时诊断，无法获得公式编译器同等级的静态语义检查。
- 通达信、同花顺的完整兼容需要真实样本库持续扩展，不能靠名称宣称完成。

## 验收

| 验收项 | 最小证据 | 明确边界 |
|---|---|---|
| 统一工作台 | 目录插入、人工编辑、AI 建议与测试报告都作用于同一草稿；保存后可回读 | 不建立第二套前台逻辑 evaluator |
| formula | 26 个目录函数、成功编译、未知函数/参数/前视错误均有结构化诊断 | 不承诺完整 TDX/THS 方言或厂商产品模式 |
| Python | 可信本地包可创建、预览、选股、回测和 Job，并返回可定位错误 | 不把本地完整 Python 能力描述为沙箱 |
| AI 来源 | 缺 reference、未知 citation 被拒；模型不能替换用户提交的引用 | citation 不是内容正确性的证明 |
| 数据 | 字段、复权、股票池及运行覆盖在响应中回显 | 不等价于新增任意数据源或频率 |
| 方言 | 导入后保留 `dialect` 并以真实编译诊断决定能否执行 | 需真实样本矩阵后才可报告兼容率 |
