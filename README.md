# stock-analyzer

A 股分析数据底座与定稿输出器。项目内所有 Python 程序只负责取数、整理结构化数据、接收 Codex 在线核验证据，并按固定模板输出 Markdown / HTML / PDF / JSON / CSV。

> ⚠️ **免责声明**：本工具仅用于**信息整理与方法论辅助**，输出内容**不构成任何投资建议**。
> A 股波动剧烈，**股市有风险，入市需谨慎**，决策与结果由您本人承担。

---

## 项目定位

- Python：抓取行情、K 线、资金流、财务、研报、持仓组合等结构化数据。
- Codex：读取程序输出，在线预览公告、网页、权威来源，补充核验结论。
- 固定模板：最终始终套用同一个定稿模板，不允许每次报告长得不一样。
- 固定视觉底板：`assets/report-cover.png` 作为 PDF/HTML 封面样式模板，由 image generation 生成。

## 强制规则

- 默认模式下，拿不到真实 K 线就必须失败，不允许伪造行情。
- 只有显式使用 `--evidence-only`，才允许输出证据版报告。
- 证据版只展示真实取得的公告、财务、资金流和在线核验，不运行伪技术分析。
- 用户明确要 PDF 时，必须生成真实 PDF 文件，不能只给 HTML 顶替。
- 所有在线补充内容必须进入 `online_evidence.json`，不能靠对话临时拼接到定稿里。

详细规则见：

- `docs/operating-rules.md`
- `docs/user-intent-routing.md`
- `docs/report-template-contract.md`
- `docs/codex-online-review.md`

---

## 核心能力

输入一只 A 股代码 + 您的成本价 + 持仓股数，自动产出：

- **持仓诊断**：浮盈亏、回本所需涨幅、成本在价格区间的分位
- **90 根 K 线回看** + **关键拐点**（±5% 以上异动日）
- **技术指标**：MA5/10/20/60、MACD、RSI14、BOLL、VWAP
- **筹码分布**：近 30 日成交在各价格区间的占比
- **资金面**：主力/超大单/小单 近 5 日汇总 + 散户接盘预警
- **基本面**：主要财务指标 + 机构研报评级 + 2026 EPS 预测
- **关键价位**：从高到低的支撑/压力/止损/止盈位 ASCII 图
- **回本概率**：基于波动率的 5/10/20/40 日概率估算
- **三档情景观察**：趋势延续 / 震荡修复 / 风险优先，含关键价位和压力测算
- **规则引擎观察**：根据趋势 + 资金态度 + 持仓状态给出重点观察情景
- **买入辅助检查**：趋势、均线、资金、RSI、波动、背离等条件成熟度评分
- **风险雷达**：持仓亏损、趋势、波动、资金流、关键位、数据完整性分层
- **组合持仓分析**：读取持仓 CSV，输出总盈亏、集中度、权重和单项盈亏
- **AI 上下文**：生成 `ai_context.json`，供 Codex 或其他模型继续做合规二次解读
- **多格式导出**：`md/html/pdf/json/csv/all`，PDF 后端缺失时自动保留 HTML 打印源
- **在线核验证据合并**：支持把 Codex 生成的 `online_evidence.json` 合并进最终报告
- **提前发现雷达**：读取 watchlist，按产业证据、趋势位置、量价资金、财务前置信号和反证规则输出观察池
- **潜龙记忆宫殿**：以 SQLite 事件账本连续管理候选裁决、作战预案、仓位、执行结果与 T+N 复盘

---

## 目录结构

```
stock-analyzer/
├── analyze.py              # 主入口 CLI
├── palace.py               # 潜龙记忆宫殿 CLI（事件账本 / 复盘）
├── run.ps1                 # PowerShell 快捷运行
├── setup.ps1               # Windows 环境初始化
├── requirements.txt        # 依赖清单
├── assets/
│   └── report-cover.png    # 固定 PDF/HTML 封面模板图（imagegen 生成）
├── docs/
│   ├── report-template-contract.md
│   ├── report-visual-design.md
│   └── codex-online-review.md
├── examples/
│   └── online_evidence.sample.json
├── src/
│   ├── fetcher.py          # 数据采集 (行情/K线/资金/财务/研报/股东)
│   ├── indicators.py       # 技术指标 + VWAP + 筹码 + 波动率 + 概率
│   ├── strategy.py         # 持仓诊断 + 三档情景观察规则引擎
│   ├── reporter.py         # 报告渲染 (Jinja2)
│   └── toolbox.py          # 买入检查/风险雷达/组合分析/导出
├── templates/
│   └── holding_report.md.j2  # 报告模板
├── output/                 # 生成的报告 (按 {code}_{name}_{date} 目录组织)
└── examples/               # 历史示例报告
```

---

## 快速开始

### 一、环境初始化（只需一次）

```powershell
cd E:\my_space\stock-analyzer
.\setup.ps1
```

脚本自动完成：
1. 检测 `uv` 或 `python`
2. 创建 `.venv` 虚拟环境
3. 安装 `akshare / pandas / numpy / scipy / jinja2`
4. 验证依赖

### 二、标准工作流

1. 先让 Python 出基础数据：

```powershell
.\.venv\Scripts\python.exe analyze.py 002460 --cost 84.363 --shares 600 --formats json,csv
```

2. 再让 Codex 读取 `summary.json` / `ai_context.json`，在线核验公告、网页和权威来源，生成 `online_evidence.json`。

3. 最后合并证据并出定稿：

```powershell
.\.venv\Scripts\python.exe analyze.py 002460 --cost 84.363 --shares 600 --online-evidence online_evidence.json --formats all
```

如果没有真实 K 线但用户明确接受证据版：

```powershell
.\.venv\Scripts\python.exe analyze.py 002460 --cost 84.363 --shares 600 --online-evidence online_evidence.json --evidence-only --formats all
```

### 三、提前发现雷达

先维护 watchlist：

```powershell
copy examples\discovery_watchlist.sample.csv watchlist.csv
```

再运行观察池排序：

```powershell
.\.venv\Scripts\python.exe discover.py --watchlist watchlist.csv --formats all
```

离线 K 线模式：

```powershell
.\.venv\Scripts\python.exe discover.py --watchlist watchlist.csv --kline-dir data\kline --offline --formats all
```

详细字段和规则见：`docs/discovery-radar.md`。

### 四、输出

报告保存到：`output/{股票代码}_{股票名称}_{日期}/`，包含：

- `{股票名称}持仓决策报告.md` — 完整 Markdown 报告
- `{股票名称}持仓决策报告.html` — 可打印 HTML 报告
- `{股票名称}持仓决策报告.pdf` — PDF 报告（需本机可用 PDF 后端）
- `kline.csv` — 前复权日 K 线 + 全部技术指标
- `summary.json` — 结构化摘要（供再加工/可视化）
- `ai_context.json` — AI 二次分析上下文
- `online_evidence.json` — Codex 在线核验证据（如提供）
- `portfolio_analysis.csv` — 组合持仓分析（提供 `--portfolio-csv` 时生成）

### 五、潜龙记忆宫殿

先初始化本地账本，再把候选、预案、真实成交和复盘按同一条链记录下来：

```powershell
.\.venv\Scripts\python.exe palace.py init
.\.venv\Scripts\python.exe palace.py dashboard
```

完整工作流、导入潜龙技能现有记忆和数据口径见 [`docs/qianlong-memory-palace.md`](docs/qianlong-memory-palace.md)。

PDF 导出优先使用 Python 包 `weasyprint`，其次使用系统命令 `wkhtmltopdf`。如果两者都不可用，主流程不会失败，会生成 HTML 打印源并在命令行标注 PDF skipped。

---

## 命令行参数

```
analyze.py CODE --cost COST --shares SHARES [选项]

位置参数:
  CODE                   股票代码 (6 位数字)

必填选项:
  --cost COST            持仓成本价 (元/股)
  --shares SHARES        持仓股数

可选:
  --days DAYS            K线回看天数 (默认 90)
  --output OUTPUT        输出根目录 (默认 ./output)
  --name NAME            股票名称 (不传会自动识别)
  --kline-csv PATH       离线 K 线 CSV，网络不可用时使用
  --portfolio-csv PATH   持仓组合 CSV
  --online-evidence PATH Codex 在线核验证据 JSON
  --cover-image PATH     定稿 PDF/HTML 的封面模板图
  --evidence-only        允许无真实 K 线时仅输出证据版报告
  --formats FORMATS      输出格式，逗号分隔：md,html,pdf,json,csv,all
```

### 持仓组合 CSV

`--portfolio-csv` 支持以下列：

```csv
code,name,cost,shares,current_price
000001,平安银行,10.00,1000,10.80
600519,贵州茅台,1800.00,100,1750.00
```

`current_price` 可留空；当前分析标的会自动使用最新 K 线收盘价，其他标的缺省时按成本价估算。

---

## 设计原则

### 1. 容错优先

每个数据源**独立 try/except**，单个接口失败不影响整体报告生成。
网络不稳时，仍能基于 K 线数据产出核心分析。

### 2. 参数化 + 规则化

- 止损位、目标价**不硬编码**，全部基于 MA20、近期高低、现价等动态计算
- 三档情景**根据持仓状态 + 趋势 + 资金面**规则生成
- 规则观察基于多因子**决策表**

### 3. 固定定稿模板

- 报告结构固定由 `templates/holding_report.md.j2` 控制。
- 模板契约见 `docs/report-template-contract.md`。
- 视觉规范见 `docs/report-visual-design.md`。
- 封面模板图默认使用 `assets/report-cover.png`。
- Markdown、HTML、PDF 共用同一份内容结构，不允许运行时随意换版式。

### 4. 分层解耦

| 层 | 职责 | 可独立使用 |
|---|---|---|
| `fetcher` | 数据采集 | ✓ 单独用作数据源 |
| `indicators` | 纯指标计算 | ✓ 可接入其他数据 |
| `strategy` | 情景规则引擎 | ✓ 观察框架可扩展 |
| `reporter` | 报告渲染 | ✓ 模板可替换 |
| `toolbox` | 买入检查/风险雷达/组合分析/导出 | ✓ 可独立复用 |

---

## 扩展指南

### 新增技术指标

在 `src/indicators.py` 添加函数，然后在 `analyze.py` 调用并传入 `reporter`。

### 修改定稿模板

直接编辑 `templates/holding_report.md.j2` 和 `docs/report-visual-design.md`。如果换封面风格，应重新生成并替换 `assets/report-cover.png`。

### 新增数据源

在 `src/fetcher.py` 的 `StockFetcher` 类添加方法 `fetch_xxx()`，
然后在 `fetch_all()` 中调用。

### 修改情景规则

编辑 `src/strategy.py` 的 `generate_strategies()` 和 `recommend_scheme()`。

---

## 数据源

- **AkShare**（免费、开源）：[github.com/akfamily/akshare](https://github.com/akfamily/akshare)
  - 东方财富：行情、资金流、龙虎榜、研报
  - 新浪：财务指标
  - 同花顺：部分口径

## 已知限制

1. **网络依赖**：AkShare 后端接口偶尔不稳，部分数据项可能采集失败（已做降级）。
2. **行业数据**：同业对比 / 板块资金流 依赖东方财富接口，偶尔失败。
3. **盘中数据**：实时行情为查询瞬间的快照，**分析以日线为主**，日内交易请结合实盘。
4. **模型局限**：回本概率基于正态分布近似，**无法预测黑天鹅 / 趋势反转**。
5. **PDF 依赖**：直接生成 PDF 需要本机安装 `weasyprint` 或 `wkhtmltopdf`；否则使用 HTML 打印源。
6. **不包含**：自动交易、期权、融资融券、ST 股规则深度核验（后续可扩展）。

## 不可退让的底线

- 不允许用占位值伪造真实行情。
- 不允许在没有真实 K 线时输出完整技术面结论。
- 不允许 PDF 失败却声称“已输出 PDF”。
- 不允许删章节来掩盖数据缺失。

---

## License

个人工具，无 License 限制，可自用/修改/分享。
但**不对任何使用本工具造成的投资损失负责**。

---

**股市有风险，入市需谨慎。本工具不构成投资建议。**
