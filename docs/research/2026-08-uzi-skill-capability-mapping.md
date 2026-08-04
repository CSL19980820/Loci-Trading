# UZI-Skill 与 stock-analyzer 能力对标

> 调研日期：2026-08-04
> 外部仓库：[`wbh604/UZI-Skill`](https://github.com/wbh604/UZI-Skill)
> 外部固定版本：`fce996c33e70eddce8e375f53cd252b549eb3d7c`（当前 `HEAD`）
> 本地范围：`E:/my_space/stock-analyzer` 当前工作树；本次只读研究，不改变策略默认。

## 结论先行

UZI-Skill 的核心价值不是提供一个可以直接替换本仓的选股引擎，而是把“个股研究”组织成一条可恢复的流水线：数据采集、规则骨架、Agent 定性判断、结构化合并、质量门禁和报告组装。它更像一个面向多平台 Agent 的研究插件；本仓则已经是一个带账本、行情仓、策略/公式运行时、回测、复盘和本地 AI 工具总线的量化工作台。

本仓已有 UZI 的几个关键等价物：技能包安装与路径隔离、CLI/MCP/builtin 工具路由、子 Agent 与 HITL、行情健康门禁、数据快照、公式诊断、策略版本归档，以及统一 `StrategyEngine` 执行链。因此不建议照搬 UZI 的“多评委数量”和报告皮肤，最值得吸收的是三件工程机制：

1. 给研究型 Skill 建立统一的阶段产物契约，每个维度明确 `source / quality / gaps / error / retrieved_at`。
2. 在最终报告或 AI 结论前增加机械化 self-review gate；critical 阻断，warning 显式展示或要求确认。
3. 给长流程增加 `lite / standard / deep` 预算档位和阶段级 resume，避免一次运行既昂贵又无法判断失败发生在哪一段。

这些建议应先落在“研究/分析 Skill”边界，不改变已有信号计算、回测口径或生产策略目录。

## 外部项目事实

| 主题 | 已确认事实 | 一手证据 |
| --- | --- | --- |
| 产品定位 | 支持 A 股、港股、美股；根入口将完整研究、评委面板、龙虎榜、陷阱检测等请求路由到不同 Skill/command。 | [`SKILL.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/SKILL.md)、[`commands/analyze-stock.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/commands/analyze-stock.md) |
| 多平台入口 | 仓库同时提供 Claude、Codex、Cursor、Gemini、OpenCode 等安装/入口适配；根目录 `run.py` 仍提供 CLI 入口。 | [仓库目录](https://github.com/wbh604/UZI-Skill/tree/fce996c33e70eddce8e375f53cd252b549eb3d7c)、[`.codex/INSTALL.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/.codex/INSTALL.md) |
| 阶段化流水线 | v3 pipeline 由 `collect -> score -> synthesize` 编排；采集分为依赖波次，非依赖 fetcher 默认并发 `max_workers=6`，单 fetcher 有 120 秒超时，并保留 legacy fallback。 | [`pipeline/run.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/run.py)、[`pipeline/collect.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/collect.py)、[`AGENTS.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/AGENTS.md) |
| 产物边界 | 以 `.cache/{ticker}/` 保存 `raw_data`、`dimensions`、`panel`、`agent_analysis`、`synthesis` 和 review 产物；Agent 负责覆盖评委判断和定性分析，脚本负责合并与报告。 | [`skills/deep-analysis/SKILL.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/SKILL.md)、[`commands/analyze-stock.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/commands/analyze-stock.md) |
| 数据质量契约 | `DimResult` 显式记录 `source`、`quality`、`error`、`data_gaps` 和顶层字段；`Quality` 区分 `full / partial / missing / error`，且保留 legacy JSON 兼容层。 | [`pipeline/schema.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/schema.py)、[`pipeline/validators.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/validators.py) |
| 来源分层 | 数据源注册表按 Tier-1 HTTP、Tier-2 浏览器、Tier-3 官方披露分层，并按市场、维度和健康状态选择候选；注册表是提示，实际 fetcher 返回的 `source` 才是事实。 | [`data_source_registry.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/data_source_registry.py) |
| Agent 闭环 | 深度模式要求读骨架产物、并行 spawn 投资者分组、合并结果到 `panel.json`、写 `agent_analysis.json`，再执行 stage2。快速 CLI 模式允许跳过 Agent，但质量语义降级。 | [`commands/analyze-stock.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/commands/analyze-stock.md)、[`AGENTS.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/AGENTS.md) |
| 自检门禁 | `self_review.py` 汇总 critical/warning/info，并写 `_review_issues.json`；深度路径出现 critical 时拒绝组装 HTML，CLI/lite 场景部分检查降级为 warning。 | [`self_review.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/self_review.py)、[`agent_analysis_validator.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/agent_analysis_validator.py) |
| 评委/角色层 | 评委规则、persona、流派锁定和 Agent role-play 是分析叙事层，不是可验证的交易信号；项目明确要求脚本输出作为骨架，最终判断由 Agent 覆盖。 | [`skills/deep-analysis/SKILL.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/SKILL.md)、[`investor_personas.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/investor_personas.py) |
| 工程演进 | release notes 记录了 pipeline 拆分、fallback、数据源修复、self-review 和回归测试；公开文档声称 v3.9.1 为 `649/649` 全过，但本次没有在远端环境重跑。 | [`RELEASE-NOTES.md`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/RELEASE-NOTES.md) |

## 本仓当前事实

| 本仓能力 | 代码/文档证据 | 对标含义 |
| --- | --- | --- |
| 通用 Skill 包 | `src/ops/application/skills.py` 解析 `SKILL.md` YAML frontmatter，支持 zip 原子安装、文件白名单、Zip Slip/符号链接/zip bomb 防护、内容 hash、工具/`mcp_servers`/`agents`/`policy`/`isolation` 元数据。 | 已覆盖 UZI 的 Skill 入口和包级元数据，且本地安装安全边界更明确。 |
| Skill 运行与状态 | `src/ops/application/skill_runtime.py` 编排子 Agent、主 Agent、工具调用和 HITL；`skill_runs.py` 用 JSON + JSONL 记录 run、消息、事件和 `waiting_user` 续跑。 | 已有阶段/事件/恢复基础，但还没有 UZI 那种统一的“研究维度产物”协议。 |
| 工具总线 | `src/ai/application/toolbus.py` 支持 Skill 声明的 CLI、MCP、builtin；`src/ai/application/skill_cli.py` 使用无 shell、路径 jail、超时和输出上限。 | 已有可复用工具路由，不需要照搬 UZI 的脚本发现方式。 |
| Screen Skill | `docs/architecture/screen-skill-tech-design.md`、`src/app/screen_skills.py`、`src/ops/application/screen/storage.py` 提供 `SKILL.md + screen.yaml + formula/strategy.py`、预览、导入、revision/history、回滚和统一目录。 | 这是本仓自己的可执行策略包，不应被 UZI 的分析 Skill 取代。 |
| 双运行时与统一执行 | `src/strategy/application/screen_formula.py`、`screen_python.py` 将 formula/Python 适配为 `StrategyEngine`，复用选股、回测和 Job；`src/strategy/application/screener.py` 返回 `health`、`universe_funnel`、`data_snapshot`。 | 本仓在信号可复现、入场时点、数据快照和回测衔接上已有更强的领域契约。 |
| AI 工具治理 | `src/ai/application/system_toolbus.py` 对写工具使用 `ExecutionGrant`，区分 read-only，发出 tool/artifact/progress 事件；`assistant_manager.py` 处理后台运行、取消、Token 预算和会话恢复。 | 已具备 UZI self-review 之前的运行治理基础；缺的是统一的“结论质量门”。 |
| 行情来源与健康 | `src/market/infrastructure/adapters/registry.py`、`src/market/README.md`、`sentinel.py` 提供 provider/lane 路由、fallback、来源目录、行情健康门禁和 `market_revision`。 | 已有来源路由与仓内健康检查；可吸收 UZI 的“维度级质量”而不重建 provider 层。 |
| 量化研究纪律 | 当前研究记忆要求信号对齐、固定资金槽位、空仓/冲突/持仓占用、PF/回撤/时间分段，并将研究结果与生产默认分离。 | UZI 的大评委和报告分数只能作为叙事参考，不能直接进入策略默认或回测结论。 |

## 跨系统能力映射矩阵

| 原系统模块或能力 | 已确认事实 | 本地等价能力 | 处置 | 理由 | 验证边界 |
| --- | --- | --- | --- | --- | --- |
| 根 Skill + command 路由 | 根 `SKILL.md` 根据请求选择最窄工作流，`commands/` 提供用户意图入口。 | 通用 Skill 的 frontmatter 与 `ops` Job/Skill 入口；Screen Skill 目录和前端工作台。 | 等价 | 本仓已有技能发现和运行入口。 | 尚未对 UZI 的所有平台入口做安装实测。 |
| 22 维阶段产物 | UZI 固定 `raw -> dimensions -> panel -> agent_analysis -> synthesis -> report`。 | Screen preview/run、backtest config/data snapshot、Skill Run JSON/JSONL。 | 新增一层契约 | 本仓有分散产物，但没有研究型 Skill 的统一阶段 schema。 | 只建议先用于研究 Skill，不改变信号执行链。 |
| `DimResult` 数据质量 | 每个维度保留来源、质量、错误和缺口，允许 partial。 | `HealthReport`、adapter/provider、`data_snapshot`、字段/窗口诊断。 | 局部吸收 | 本仓已有仓级质量，缺维度/证据级质量。 | 需要先定义哪些“缺口”可重试、可降级或必须阻断。 |
| Agent role-play/评委 | 规则只产骨架，Agent 分组重评并写回结构化 JSON。 | `agents` frontmatter、`run_ammo_agents`、AI 只读子 Agent、Skill HITL。 | 局部吸收 | 本仓已有编排，但不应复制 66 人名单或把模拟观点当权威数字。 | 需要对每个角色定义输出 schema、来源要求和合并规则。 |
| self-review gate | critical 阻断报告，warning 可解释/确认，问题写文件供 Agent 修复。 | Screen formula diagnostics、行情 health gate、AI `EvidenceWarning` 设计、ToolBus 事件。 | 新增共享门 | 现有检查多在单域，缺 AI/研究终稿的一致性检查。 | 不能把“有引用”当作“事实正确”；仍需来源质量和数字回溯。 |
| resume/fallback | UZI 缓存每阶段并保留 legacy fallback，单源失败不会直接吞成成功。 | `skill_runs` 续跑、market adapter fallback、screen history/rollback、Job history。 | 等价但分散 | 本仓机制已存在，可统一研究工作流的状态模型。 | 需要确认跨进程并发、取消和过期 cache 的语义。 |
| 多层数据源注册 | Tier-1 HTTP / Tier-2 浏览器 / Tier-3 官方披露，按健康排序。 | market adapter registry、MCP registry、source catalog、lane route。 | 局部吸收 | 本仓已有行情源抽象；研究资料需要额外的证据等级/检索时间字段。 | 外部网页与 MCP 的可用性必须每次探针验证，不从配置推断可用。 |
| 静态 HTML/图片报告 | UZI 把结果组装成自包含 HTML、截图和分享产物。 | Vue 工作台、artifact 事件、前端报告/图表组件。 | 待定/低优先级 | 产品形态不同，本仓优先交互工作台和可复现数据。 | 只有出现离线交付或分享需求时再做导出快照。 |
| 多平台 plugin 适配 | UZI 同时维护 Claude/Codex/Cursor/Gemini/OpenCode 入口。 | 本仓是本地桌面 + FastAPI/Vue，Skill 包可导入。 | 忽略 | 不是当前产品目标；增加维护面会分散量化核心。 | 若未来公开分发 Skill，再单独设计适配层。 |

## 可落地启发与优先级

### P0：研究产物契约

在 `ai/ops` 的研究型 Skill 运行结果中增加一个轻量、可版本化的阶段产物结构，至少包含：

```text
stage
subject
source
quality: full | partial | missing | error
data_gaps
retrieved_at
evidence[]: url/path, title, section, quote, observed_at
derived_claims[]: claim, input_refs, confidence
runtime_revision
market_revision
```

它可以先是文件级 JSON/Markdown 约定，不必马上新建数据库表。行情数字仍由 market/backtest 产出，AI 只引用并解释；不能让研究产物成为第二套权威行情或盈亏真相。

### P0：统一终稿 self-review

沿用本仓现有的 `health`、`data_snapshot`、工具回执和 evidence warning，增加面向研究终稿的检查：

- 引用的数字是否能回溯到本轮工具结果或指定来源；
- 是否把 `missing/partial` 当成完整事实；
- 结论是否混入未执行的工具或未验证的外部资料；
- 运行时、策略版本、行情快照和参数是否齐全；
- 写操作/交易建议是否仍遵守 HITL 与“AI 不产出权威盈亏”的边界。

`critical` 只阻断“标记为已核验/可交付”的终稿，不阻断用户查看中间研究结果；`warning` 必须在 UI/Markdown 中显式展示。

### P0：阶段预算与恢复

可借鉴 UZI 的 `lite / standard / deep` 选择，但把它解释为耗时、Token、数据源和 Agent 深度预算，而不是质量分数。每一阶段保存输入摘要、输出路径、错误、耗时和版本；重复运行优先复用仍有效的阶段产物，失效时只重跑受影响阶段。

### P1：角色/子 Agent 输出契约

保留本仓已有的 `agents` 与只读子 Agent，但为每个角色增加固定 `id / responsibility / allowed_tools / output_schema / evidence_requirement`。合并前校验 schema，禁止子 Agent 直接写账本或改策略；这比复制 UZI 的大规模 persona 名单更适合本仓。

### P1：研究来源等级

行情 provider 继续复用现有 adapter registry；研究资料额外区分官方披露、正式文档、可信媒体、社区/叙事，并保留实际命中的来源、时间和失败原因。浏览器或 MCP 只作为有明确缺口时的补充，不把“注册过”当成“当前可用”。

### P2：离线报告快照

只有当用户需要把一次分析发给别人或长期归档时，再把现有 artifact、图表和引用打包为自包含 Markdown/HTML。它应携带 `market_revision`、strategy/package revision 和生成时间，不能只保存一张脱离数据上下文的图片。

## 不建议照搬

- 不把 UZI 的 65/66 位评委、角色分数或“综合评分”加入本仓量化策略默认；它们是研究叙事层，缺少本仓要求的可回测定义。
- 不把 UZI 的公共数据源数量当作数据质量证据；多源只说明有 fallback 选择，不证明字段口径、时点和授权正确。
- 不自动安装外部依赖或执行来源不明脚本；本仓现有 Skill CLI 的无 shell、路径 jail、超时和输出上限应继续保留。
- 不把 browser fallback 作为默认行情链；优先使用已登记、可探针验证、能记录快照的 provider。
- 不因对标项目有自称“全过”的测试数字就改变本仓生产默认；外部测试声明本次未在其环境独立重跑。

## 风险与验证边界

1. UZI 的 README/元数据存在版本口径漂移：README 和 `package.json` 写 `3.9.2`，根 `SKILL.md`、`.version-bump.json` 和 release notes 顶部仍显示 `3.9.1`。若借鉴其版本同步机制，应先做一致性校验。
2. UZI 的公开测试数字来自 release notes，本次只读取源码和文档，没有安装依赖、跑真实股票或独立复现 `649/649`。
3. 本地工作树在调研前已有大量未提交改动；本次没有运行会写入 `data/` 的任务，也没有修改这些改动。本文对本地能力的判断基于当前磁盘源码和已有设计文档，不等同于一次完整测试验收。
4. 本文没有验证 UZI 的投资结论、数据准确率、第三方来源授权或报告预测能力；这些不能从仓库结构和测试数量推导。

## 下一步验收建议

若后续要落地启发，先做一个只读研究 Skill 的最小实验：输入一只股票，产出两个阶段 JSON（数据证据、分析结论）和一份 self-review 报告；用现有 `market_revision`、ToolBus 事件和 AI 会话状态串起来。验收只看来源回溯、缺口标记、失败恢复和终稿门禁，不改变现有四个策略目录、回测默认或资金配置。

## UZI 数据地图与获取方式

### 口径先校正

UZI 的文档和注册表存在一个需要先记录的口径差异：注释、README 和部分命令称有 22 个 fetcher，但固定 commit 的 `FETCHER_REGISTRY` 实际只有 21 个 unique `dim_key`。`fetch_similar_stocks.py` 是额外的相似股票流程，没有进入主 registry，因此下表按 21 个注册维度统计，不把它伪装成第 22 个主维度。

主流程是 `collect -> score -> synthesize`。registry adapter 只负责把 `dim_key`、依赖、所需字段和 legacy `fetch_*.main()` 统一起来；真正命中的来源以 fetcher 返回的 `source` 为准，注册表只是候选提示。非依赖 fetcher 默认并发 6 路，单 fetcher 超时 120 秒，阶段产物支持缓存和 resume，失败维度可以标为 `partial/missing/error`。

### 21 个注册维度和实际获取链

| dim_key | UZI 额外数据 | 主要获取方式和回退 | 对本仓的差异 |
| --- | --- | --- | --- |
| `0_basic` | 名称、价格、行业、市值、PE/PB、EPS、实控人、上市日期 | 雪球 AkShare backend、东方财富 push2、腾讯 qt、 新浪、BaoStock 等路由和解析 | 本仓有标的目录和行情，但没有这些基本面字段的统一快照 |
| `1_financials` | ROE、净利率、毛利率、营收/净利历史、现金流、OCF/净利、财务健康、分红 | AkShare 财务摘要/分析指标/现金流/分红；核心字段缺失时 BaoStock 兜底 | 本仓没有报表、公告日和财务口径层 |
| `2_kline` | OHLCV、MA5/10/20/60/120/200、MACD、RSI、KDJ、OBV、Williams %R、Stage、VCP、筹码分布 | AkShare 东财日线和筹码分布，外加新浪、BaoStock、东财/新浪/腾讯直连等 6 路 fallback | 本仓有更完整的历史日线仓、复权因子、交易日历和面板计算；UZI 的技术指标可作为表达参考 |
| `3_macro` | 利率周期、汇率趋势、地缘风险、商品、增长动能 | DDGS 搜索片段和启发式情绪归纳，按行业依赖 `0_basic` | 本仓没有宏观定性维度；该维度不是稳定的历史因子 |
| `4_peers` | 同行表、同行 PE/PB、行业排名和比较 | AkShare 东财行业成分；失败后雪球 Playwright；港股可降级为同行宇宙排名或仅自身一行 | 本仓没有同行横截面和行业估值快照 |
| `5_chain` | 主营拆分、上下游、客户集中度 | AkShare `stock_zygc_em`、`stock_zyjs_ths`，必要时补网页资料 | 本仓没有产业链/客户集中度结构化字段 |
| `6_fund_holders` | 持有基金、基金数量、主动基金数量、基金经理、基金 5 年收益/回撤/夏普等 | AkShare `stock_fund_stock_holder`，失败时 `stock_report_fund_hold_detail`；基金净值/排名另调 `fund_open_fund_info_em`，部分详情只取 Top N | 本仓没有基金持仓和机构行为历史 |
| `6_research` | 研报覆盖数、评级分布、目标价均值、买入率 | 优先 AkShare `stock_research_report_em`，失败时 `stock_rank_forecast_cninfo` 等巨潮/研报接口；结果通常是当前截面 | 本仓没有卖方共识和目标价的点时序列 |
| `7_industry` | 行业增速、TAM、渗透率、行业 PE/PB、巨潮行业指标 | 巨潮 `stock_industry_pe_ratio`、行业估计值和可信搜索片段；按行业依赖 `0_basic` | 本仓标的可能有行业字段，但没有行业景气/估值数据集 |
| `8_materials` | 核心原材料、价格趋势、12 个月价格历史、材料成本占比 | 行业到期货/材料的静态映射 + AkShare `futures_main_sina` | 本仓没有公司到原材料的映射和成本占比 |
| `9_futures` | 关联合约、期货价格趋势、库存 | 行业到合约的静态 `INDUSTRY_FUTURES` 映射 + AkShare 期货主连；按行业依赖 `0_basic` | 本仓没有商品期货关联面板 |
| `10_valuation` | PE/PB、5 年历史分位、行业估值、简化 DCF | 百度股市通近五年 PE/PB、巨潮行业 PE、港股估值接口、脚本 DCF | 本仓暂无财务估值快照；不能直接把 UZI DCF 当估值真相 |
| `11_governance` | 质押、内部交易、董事长变更 | AkShare 质押比例、董监高增减持等接口 | 本仓没有治理事件结构化数据 |
| `12_capital_flow` | 北向、融资融券、股东户数、主力资金、机构持仓历史、解禁/大宗交易 | AkShare 多接口组合；港股部分使用雪球/AASTOCKS/HK 数据 | 本仓已有独立 `capital_flow` lane，但维度、历史口径和股东/基金明细不完整 |
| `13_policy` | 政策方向、补贴、监管、反垄断、搜索片段 | DDGS 行业搜索；按行业依赖 `0_basic` | 本仓没有政策文本证据链 |
| `14_moat` | 无形资产、转换成本、网络效应、规模、研发摘要和四项评分 | DDGS/网页搜索 + 关键词打分 | 本仓没有结构化护城河评分；只能作为研究解释，不是行情事实 |
| `15_events` | 公告时间线、新闻、催化剂、风险、披露数量 | 巨潮公告直连、AkShare 东财新闻、金十/东财快讯/同花顺多源新闻，港股用 HKEXNews，另有 web search | 本仓没有公告/事件时间线和公告日关联 |
| `16_lhb` | 近 30 日龙虎榜次数、明细、游资匹配、机构/游资对比 | AkShare 龙虎榜明细、统计和席位库 | 本仓没有龙虎榜数据 |
| `17_sentiment` | 雪球热度、情绪温度、正面比例、情绪标签、平台片段、热榜提及 | 雪球/新闻搜索/平台片段，部分需要浏览器或登录 | 本仓没有舆情热度时间序列 |
| `18_trap` | 风险分、拉抬出货信号、预警标志、陷阱概率 | 把公告、新闻、价格量能和舆情等输入做启发式风险规则 | 不是独立的反欺诈数据源，本仓不应把它当硬门禁直接照搬 |
| `19_contests` | 雪球组合、淘股吧提及、同花顺模拟、DPS 实盘赛 | 雪球 cubes HTTP，失败可选择 Playwright 登录；再抓淘股吧、同花顺模拟和 DPS | 本仓没有社交组合/实盘赛数据；且公开组合有幸存者偏差 |

补充流程 `fetch_similar_stocks.py` 会尝试找相似股票，但它不是主 registry 维度。UZI 的大部分“多数据”并不是一个统一数据库，而是多个 AkShare、直连 HTTP、搜索、HTML 解析和可选浏览器源在一次分析中拼成的研究快照。

本节一手源码索引：[`fetchers/registry.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/fetchers/registry.py)、[`data_source_registry.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/data_source_registry.py)、[`fetch_kline.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/fetch_kline.py)、[`fetch_financials.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/fetch_financials.py)、[`fetch_capital_flow.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/fetch_capital_flow.py)、[`fetch_events.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/fetch_events.py)。

### 来源注册表值得借鉴的结构

UZI 的 `DataSource` 字段是：

```text
id, name_cn, base_url, markets, dims, tier, access, health, notes
```

其中 `tier=1` 是 HTTP/AkShare/MX 主源，`tier=2` 是 Playwright 浏览器源，`tier=3` 是交易所/巨潮/HKEXNews 等官方披露源；`access` 区分 `http/akshare/mx_api/playwright/ddgs`；`health` 区分 `known_good/flaky/blocked_often/needs_browser`。这比只维护一个 provider 名单更适合研究型数据，因为它同时描述了市场范围、维度覆盖、访问成本和失败预期。

对本仓建议只吸收注册表字段和语义，不复制 UZI 的数据源实现：

1. 现有行情 `adapter registry` 继续负责可执行路由；研究维度另加 `dim_key -> source candidates` 映射。
2. 每次实际返回都记录 `actual_source`、`retrieved_at`、`fallback_reason`、`quality` 和字段缺口；注册表不能代替运行结果。
3. 把 `health` 拆成配置状态、最近探针状态和本次请求状态，不从“注册过”推断当前可用。
4. 对网页搜索、浏览器、社交源额外记录 `evidence_url`、标题/片段、观察时间和是否需要登录；不要把搜索摘要当成财报事实。
5. 不把密钥、Cookie 或真实数据库写入注册表；MX API 等凭据仍走环境变量。

还要保留一个重要限制：`FetcherSpec.sources` 在很多注册项里只是 `legacy:fetch_xxx`，并不代表本次请求真实命中的厂商或 URL。来源列表可以指导选择和 fallback，只有 fetcher 返回的 `source`、请求时间和证据片段才能作为报告事实。

UZI 的来源清单可作为“候选目录”参考，本仓若落地应先选择少量、可探针验证、字段口径明确的来源，避免为了覆盖面增加大量不可复现的 HTML/搜索依赖。

## 本仓已有与缺失能力对照

| 能力类别 | UZI 更强/更多 | 本仓当前能力 | 判断 |
| --- | --- | --- | --- |
| 财务与估值 | 报表派生、ROE/利润率/现金流、PE/PB 历史分位、同行估值、DCF | 主要是行情和标的目录，暂无统一财务快照 | 是真实缺口，但必须先解决公告日和 point-in-time 口径 |
| 产业与定性 | 产业链、原材料、期货、政策、护城河、事件、舆情、治理 | 有 AI/Skill 工具治理，没有这些结构化研究维度 | 适合先做只读研究产物，不应直接进入策略信号 |
| 机构与市场行为 | 基金经理/基金持仓、龙虎榜、实盘组合、研报共识 | 有资本流 lane、行情面板和回测 | 可做研究标签；历史回测前必须有可追溯的公告/披露时间 |
| 行情工程 | 多市场、多源 fetcher 和浏览器 fallback | 日线/实时/分钟/资金流 lanes，provider 路由、fallback、探针、健康门禁、复权、交易日历、快照 | 本仓的可复现行情基础更完整，不需要重建 UZI 路由 |
| 量化执行 | 单票条件命中、角色规则和技术指标 | 全市场 pandas/numpy 面板、统一 `StrategyEngine`、Formula/Python 双运行时、回测和前视审计 | 本仓更适合把经过验证的规则变成信号；UZI 的分数主要是研究骨架 |
| 运行产物 | 按维度 `DimResult`、阶段缓存、self-review、报告组装 | Skill run JSON/JSONL、工具事件、数据快照、策略 revision、health 和 HITL | 建议把 UZI 的维度证据契约补到本仓研究 Skill |

## UZI 的量化指标和公式清单

### `/screen` 的五套条件筛选

`run_idea_screen()` 对一只股票逐条件判断，再计算 `pass_rate = passed / total`；命中率达到 70% 才返回 `fits_screen=true`。它是单票条件覆盖率，不是横截面排序，也没有在代码中证明它是 alpha。

| screen | 代码中的条件 | 用途和可回测性 |
| --- | --- | --- |
| `value` | `PE < 15`；`PB < 1.5`；股息率 `> 3%`；`FCF > 0`；`0 < debt_ratio < 50%` | 价值初筛。PE/PB/股息率必须用当时可见数据；FCF 需要真实现金流，不能接受代理值 |
| `growth` | 3 年营收增速 `> 15%`；3 年 EPS 增速 `> 20%`；毛利率扩张；ROE `> 15%` | 成长初筛。当前代码存在 `rev_growth_3y/eps_growth_3y/roe_last` 与特征提取器常用的 `revenue_growth_3y_cagr/roe_latest` 命名不一致风险 |
| `quality` | 5 年至少 4 年 ROE `> 15%`；净利率 `> 15%`；FCF 持续为正；`0 < debt_ratio < 50%`；护城河 `>= 28/40` | 质量初筛。护城河是搜索评分，不能与财务字段同等看待 |
| `gulp` | `PEG < 1.5`；营收增速 `> 15%`；ROE `> 15%`；`Stage 2` | 实际是 GARP 风格，不是独立的“吞噬”因子 |
| `short` | `PE > 60`；营收增速 `< 0`；ROE `< 5%`；负债率 `> 70%` | 风险/空头候选筛查，不是做空交易策略 |

### K 线指标

| 指标 | UZI 实现 | 可借鉴边界 |
| --- | --- | --- |
| 均线 | MA5/10/20/60/120/200；多头为 `MA5 > MA10 > MA20 > MA60 > MA120` | 可在本仓日线面板重算；需要 200 根 warm-up，并保持信号日和成交日分离 |
| Weinstein Stage | `Stage 2 = close > MA200 且 MA200[t] > MA200[t-60]`；其余四种由价格在 MA200 上下和 MA200 是否上升组合得到 | 这是最容易直接做历史验证的一组，但不能用未来修订的当日数据替代当时可见值 |
| RSI | 14 日 RSI；代码还把 `>70` 标为超买、`<30` 标为超卖 | 可作为技术特征，不代表 UZI 证明了阈值有效 |
| MACD | EMA12、EMA26，`DIF=EMA12-EMA26`，`DEA=EMA9(DIF)`，柱体为 `2*(DIF-DEA)` | 可回测；需确认本仓 EMA 初始化和复权口径一致 |
| KDJ | 9 日 RSV/K/D/J，初始 K/D 为 50，`J=3K-2D` | 可作为实验特征，不宜直接加权到生产默认 |
| OBV | 上涨日加成交量、下跌日减成交量；`OBV[t] > OBV[t-20]` 视为趋势向上 | 对成交量单位、停牌和复权不敏感程度需单独验证 |
| Williams %R | 14 日；`(HH-close)/(HH-LL)*-100`；`>-20` 超买，`<-80` 超卖 | 公式清楚，但与 RSI 重叠度和边际收益要做消融 |
| VCP/量能 | 最近 30/60/90 日波动区间收缩启发式，另有 5 日/20 日量比 | 形态标记不是严格定义，不能把 `vcp_score` 当标准化因子 |

### `stock_features.py` 的派生公式

| 派生量 | 精确公式/规则 | 风险 |
| --- | --- | --- |
| ROE 稳定性 | 最近 5 年 ROE 均值、最小值、`>15%` 年数 | 财报期末值可能早于披露日，历史回测必须按公告日可见性截断 |
| 营收 3 年 CAGR | `((latest / value_4_periods_ago) ** (1/3) - 1) * 100` | 依赖至少 4 个历史点，缺失/负数时给 0 |
| 净利率 | `latest_net_profit / latest_revenue * 100` | 净利润为负或营收缺失时走备用字段/0，需保留缺口而不是伪造健康 |
| FCF 正值 | `fcf_positive = fcf_margin > 0` | `fcf_latest_yi = latest_net_income * 0.8` 是代理，不是现金流量表 FCF |
| PE/PB 和同行比较 | `pe_x_pb = pe * pb`；`(pe - industry_pe) / industry_pe * 100`；另算同行平均 PE 相对差 | 当前 PE/同行均值做历史回测会产生 point-in-time 和成分漂移问题 |
| 目标价空间 | `(target_price_avg - price) / price * 100` | 研报目标价是未来共识，直接用于过去信号属于前视/选择偏差 |
| 主力资金 | 取 `main_fund_flow_20d` 前 5 条的主力净流入求和 | 不是 20 日完整累计，且依赖当前返回排序和字段口径 |
| 护城河总分 | `intangible + switching + network + scale`，满分 40；通常 `>=24` 视为清晰，`>=28` 视为强 | 主要来自搜索和关键词打分，不能与 ROE 同权重 |
| PEG | 代码为 `pe / rev_growth_3y`，增速非正时默认 99 | 特征提取器同时主要产生 `revenue_growth_3y_cagr`，存在字段不一致，必须先修契约并加单测才能研究 |
| FCF/EBITDA/毛利率兜底 | `ebitda_yi = latest_net_income / 0.6`；毛利率缺失时 `net_margin + 18` | 都是展示/规则兜底，不能直接用于生产或回测 |
| 毛利率扩张 | `gross_margin_expanding = False` 固定默认 | `growth` screen 的该条通常无法通过，不能把输出解释成真实历史趋势 |

### 简化 DCF

`simple_dcf()` 在 FCF 为正时预测 10 年现金流：前 5 年增长 10%，后 5 年用 `(10% + 3%) / 2`，终值增长率 3%，WACC 10%，再用永续增长模型折现。实际 fetcher 的 FCF 主要来自“最新净利润乘 0.8”，总股本缺失时还会从市值/价格推导，仍缺失则默认 10 亿股。它适合作为敏感性展示模板，不适合作为本仓估值信号。

### 规则族中可作为研究候选的阈值

以下规则来自 `investor_criteria.py` 的客观检查项。它们是不同投资人/风格的加分规则，不是一个经过统一训练和回测的模型：

| 规则族 | 典型条件 | 研究用途 |
| --- | --- | --- |
| Buffett/质量 | 5 年至少 4 年 ROE `>15%` 且最低 ROE `>12%`；净利率 `>15%`；负债率 `<50%`；FCF 正；护城河 `>=24/40` | 质量过滤，可作为单因子或组合条件 |
| Graham/价值 | `0<PE<15`、`0<PB<1.5`、`PE*PB<22.5`、流动比率 `>2`、连续盈利/分红 | 价值因子；需处理负 PE、金融股和行业差异 |
| Lynch/GARP | `PEG<1` 理想；`1<=PEG<1.5` 可接受；PE `<40`；最新营收增速在 `20%-50%` | 估值和成长交叉；PEG 输入必须先做点时序和字段契约 |
| O'Neil/Minervini | 净利增速 `>25%`、3 年 CAGR `>20%`、距 60 日高点 `>-10%`、Stage 2、基金经理数 `>=3`；Minervini 还要求 MA 多头、距高点 `>-25%`、YTD `>0` | 动量/成长候选；技术部分可先用本仓行情验证 |
| Asness/量化因子 | PE `<20` 且 PB `<4`；ROE `>12%` 且负债率 `<60%`；YTD `>0` 且价格在 MA200 上；5 年最低 ROE `>8%`；PE `<80` | 价值 x 质量 x 动量的候选规则组，不能直接当综合分 |
| Rule of 40 | `revenue_growth + net_margin >= 40` | 软件/成长公司研究过滤，需统一百分比单位 |
| AI/科技 | AI/算力相关；营收同比 `>30%`；毛利率 `>=50%`；研发强度 `>=8%` | 主题研究标签，不应以关键词命中代替业务验证 |
| Burry/Chanos 风险 | PE `<60` 且 PS `<15`；负债率 `<70%`；FCF margin `>=5%`；OCF/净利偏离 `<40%`；另看内幕减持、审计和表外债务 | 风险排雷候选，不等价于做空收益模型 |
| 游资/短线 | 正向催化且情绪热度 `>=55`；近 30 日龙虎榜 `>=1` 或近期涨停；Stage 2 + 量能；距年高 `<-25%` 且有催化 | 只适合作为事件/短线研究标签，需要独立的入场、退出和容量规则 |

### 维度总分和评委分不是交易信号

`pipeline/score_fns.py::score_dimensions()` 还会把 21 个注册维度按报告面板打分。部分维度是数据驱动的，但宏观固定给 6 分、行业固定给 7 分、原材料固定给 6 分、期货固定给 5 分、政策固定给 6 分、护城河固定给 6 分；`18_trap` 当前是注释明确的 `stub -> safe by default`，直接给 9 分。同行数据不足时也可能因“有数据”得到默认分。这些值是报告骨架和缺省展示，不是历史样本估计的因子收益。

单个投资人由 `investor_evaluator.evaluate()` 计算加权规则通过率：

```text
rule_score = 100 * weight_pass / weight_total
score = clamp(rule_score + affinity_adjust, 0, 100)
score >= 65 -> bullish
score < 35  -> bearish
```

如果公开持仓匹配，还会插入一个权重为 6 的 `known_holding` 规则；同时还叠加能力圈/持仓等 reality adjustment。该分数没有统一入场日、成交价、退出、成本、滑点、容量或组合约束，所以只能表示“按某一投资人规则的当前研究态度”，不能直接回测成选股 alpha。

AI 卡位分还可拆成可解释的研究特征：AI 关键词命中、`switching + scale` 不可替代性、小市值弹性（市值 `<100/300/800/2000` 亿对应 `1.0/0.8/0.5/0.25`，更大为 `0.1`）、需求拐点（政策 `+0.4`、催化 `+0.3`、行业增速 `>=20%` `+0.3`）、证据倍率（strong/medium/weak 为 `1.0/0.85/0.70`）和最多 60% 的罚分。命中 AI 链时合成基数为：

```text
base = (0.35*keyword_strength + 0.30*irreplaceable_norm
        + 0.20*elasticity + 0.15*inflection)
base *= (0.70 + 0.30*tier_weight)
base *= evidence_multiplier
base *= (1 - penalty_total)
score = base * 100
```

不在 AI 链上时分数直接为 `8 * elasticity`。这是一套可解释的研究打分，不是已经被历史样本证明的因子；关键词、搜索结果和处罚项都需要独立标记证据强弱。

### “量化基金信号”的特殊例子

`quant_signal.py` 不识别基金名字白名单，而用结构性启发式：第一大持仓占净值 `<2%` 判为疑似量化基金；疑似量化基金 Top 10 含目标股票，且至少 3 家满足时触发。样本少于 20 家会自动扩大到最多 80 家，持仓年份当前硬编码为 `2025`，接口是 AkShare `fund_portfolio_hold_em`，并带季度缓存。它适合研究“机构结构”标签，不能直接变成日频因子。

公式一手源码索引：[`research_workflow.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/research_workflow.py)、[`stock_features.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/stock_features.py)、[`investor_criteria.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/investor_criteria.py)、[`fetch_valuation.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/fetch_valuation.py)、[`quant_signal.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/quant_signal.py)、[`score_fns.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/score_fns.py)、[`investor_evaluator.py`](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/investor_evaluator.py)。

## 不能直接复用的代理值和定性分数

1. `FCF = net_income * 0.8`、`EBITDA = net_income / 0.6`、缺失毛利率 `= net_margin + 18` 都是方便报告落地的代理，不能替代现金流量表和标准 EBITDA。
2. UZI 财务 fetcher 中的 `financial_health.fcf_margin` 实际由经营活动现金流/净利润比例派生，源码明确说明是 OCF，不是扣除资本开支后的 FCF；以 `fcf_positive` 命名判断会造成语义误导。
3. `gross_margin_expanding=False`、部分“商业模式易懂/简单”规则固定返回 True 或 False，属于占位逻辑，不是数据结论。
4. DDGS、新闻片段、雪球热度、护城河四项和 AI 关键词分数存在搜索噪声、重复报道、登录状态和叙事偏差；“有来源”不等于“来源可靠”。
5. 当前 PE/PB、研报目标价、基金持仓、解禁、龙虎榜和宏观搜索大多是分析时点快照；没有按历史披露日重建时，放进回测会把未来信息带回过去。UZI 的部分解禁查询还硬编码了 `2026`，没有统一 `as_of` 约束。
6. UZI 的规则是单票条件命中和角色加分，未给出横截面排名、固定资金、持仓冲突、退出、滑点、容量和组合回撤模型，不能用 `fits_screen` 或评委总分替代本仓回测。
7. `run_idea_screen()` 使用的 `rev_growth_3y`、`eps_growth_3y`、`roe_last` 与 `stock_features.py` 中主要生成的 `revenue_growth_3y_cagr`、`roe_latest` 不完全一致；`PEG` 也有同类字段问题。若本地尝试复刻，第一步应是字段契约测试，而不是调阈值。
8. registry、fetcher 和评分层之间还存在字段契约漂移，例如注册表写 `coverage`/`recent_news`，评分层读取 `report_count`/`news`/`recent_notices`；这说明“字段有名字”不等于“评分真的消费了该字段”。

## 只读历史验证建议

后续如果要验证这些候选规则，建议按以下顺序做研究，不改本仓策略默认、不接入 UZI 生产数据源：

1. 先只验证技术规则：用本仓 `quotes_daily`、复权因子和交易日历重算 MA/Stage/RSI/MACD/OBV/Williams；所有信号按 T 日收盘生成，执行价格和 `entry_timing` 按策略契约取 T+1，不使用 T 日未来 high/low 伪造成交。
2. 再验证财务规则：必须保存报告期、公告日、抓取时间和来源；没有 point-in-time 财务数据时，只做当前截面研究，不宣称历史 alpha。
3. 每个候选规则与基线分开跑，报告样本数/交易数、胜率、平均收益、payoff ratio、PF、最大回撤、账户/固定资金槽位影响、空仓现金、冲突和持仓占用，并做月份/前后半段/样本外分段。
4. 对阈值做 walk-forward 或时间切分，不用全样本最优阈值回填生产；同时做消融，区分财务、技术、情绪和搜索分的边际贡献。
5. 验收重点不是“多拿到几个字段”，而是每个字段能否回答：来源是什么、何时可见、缺失时怎么处理、是否可重建、能否在回测时对齐到同一交易日。

本轮结论仍是：先把 UZI 的“维度级来源/质量/缺口/证据”作为研究 Skill 的产物契约借鉴；候选公式优先从本仓已有历史行情能严谨验证的 Stage/均线/动量开始。财务、研报、基金、舆情和 AI 卡位等维度先保持只读研究标签，证据不足时宁可留空，不把弱来源补成强信号。
