# UZI-Skill 后续能力审计

> 审计对象：`wbh604/UZI-Skill`，固定 commit `fce996c33e70eddce8e375f53cd252b549eb3d7c`。
>
> 审计范围：该版本的一手源码/文档与本仓当前 `src/research`、`src/ops`、`src/ai`、`src/market`。本次只读，不运行外部数据采集、不写 `data/` 或数据库、不改变策略默认和生产信号。上一份能力映射已确认的结论在这里作为背景，本文件只记录仍需落地或明确拒绝的事项。

## 结论

真正值得继续吸收的不是 UZI 的 21 维数量、评委名单或综合分，而是五个工程闭环：

1. 研究阶段产物与可恢复状态；
2. 终稿前的机械 self-review 门禁；
3. 来源候选、实际探针、实际命中和证据回执的分离；
4. AI 只能读取研究产物、不能把研究草稿变成权威数字或写入生产域；
5. 研究输入的 point-in-time 快照，防止当前数据覆盖历史结论。

本仓已经有这些能力的若干零件，但尚未在 `research` 形成闭环。建议按下表处理：

| 项目 | 建议 | 优先级 | 核心判断 |
| --- | --- | --- | --- |
| 研究阶段产物、resume、失效重跑 | 实施 | P0 | `ops` 有通用 Skill Run，但研究剖面仍是同步临时结果 |
| 研究终稿 self-review 注册表 | 实施 | P0 | 当前质量快照有基础门禁，缺跨维度和终稿一致性规则 |
| 来源实际探针与命中回执 | 实施 | P0 | 本仓已有 adapter probe，可复用；UZI 的静态健康标签不够 |
| AI 只读研究工具 | 实施 | P1 | ToolBus 已有只读过滤，但没有 research catalog/profile 工具 |
| 历史安全 / point-in-time 输入 | 实施 | P0 | 当前有 revision/as_of 字段，但没有可重放的研究输入快照 |
| UZI 机构报告模块、角色面板 | 暂缓 | P2 | 依赖可信财务/公告/估值来源，当前接入会制造叙事伪精确 |
| UZI 评委分、代理估值、静态健康值 | 拒绝 | - | 不是经本仓回测验证的信号，且源码存在明确代理和时点问题 |

## 1. 阶段产物与 resume

### UZI 证据

- `skills/deep-analysis/scripts/lib/pipeline/run.py` 将流程拆为 `collect -> score_from_cache -> synthesize_and_render`；`_load_cache()` 读取 `.cache/<ticker>/raw_data.json`，阶段结果按文件保存，遇到不支持场景由 `_preflight_guards()` 抛异常回退 legacy 路径。
- `skills/deep-analysis/assets/data-contracts.md` 将 `raw_data.json`、`dimensions.json`、`panel.json`、`synthesis.json` 定为阶段契约，并记录 `fetched_at`、`source`、`fallback`。
- `commands/analyze-stock.md` 和 `skills/deep-analysis/SKILL.md` 要求 Agent 读取骨架产物后再写结构化分析，深度路径最终进入 stage2。

这套设计的可借鉴点是“按阶段复用和局部失效”，不是照搬其 cache 目录。UZI 的 resume 主要以文件存在和旧 raw cache 为依据，没有统一的输入版本、依赖 hash 或过期策略，因此不能直接视为历史安全。

### 本仓证据

- `src/ops/application/skill_runs.py:112` 的 `create_run()` 已持久化 run 状态、`result`、`error`，并用 JSON/JSONL 事件记录；`:76` 的 `claim_user_reply()` 支持原子领取 `waiting_user` 回复。
- `src/ops/application/skill_runtime.py:16`、`:61` 已支持子 Agent、主 Agent、HITL 和跨请求续跑。
- `src/research/application/profile.py:52` 的 `build_research_profile()` 每次直接从 `MarketStore` 读取当前标的、当前交易日和当前历史窗口；`src/research/api/router.py` 只提供 GET profile/catalog，没有研究 run、阶段状态或产物查询。
- `src/research/domain/contract.py:85` 的 `ResearchProfile` 是内存/响应契约，尚未成为带输入指纹的持久研究产物。

### 建议：实施（P0）

复用 `skill_runs` 的状态/事件思想，但新增研究专用的文件级产物契约，不新建第四个数据库：

- `input_snapshot`：代码、budget、截止交易日、market revision、各输入数据摘要/hash；
- `evidence`：维度级结果、真实来源、`retrieved_at`、`as_of`、缺口；
- `review`：规则版本、问题列表、门禁状态；
- `conclusion`：只允许引用上述产物的分析文本；
- 每阶段记录 `contract_version`、输入 hash、输出 hash、开始/结束时间、错误和依赖阶段。

复用条件是“输入指纹仍有效才复用”；市场 revision、截止日、预算或来源版本改变时只重跑受影响阶段。resume 失败时保留旧产物并标记 stale，不能静默当成成功。研究产物仍属于研究域，不能写 `palace.db`、`market.db`、`ops.db`，也不能自动进入策略信号。

## 2. self-review 门禁

### UZI 证据

`skills/deep-analysis/scripts/lib/self_review.py:8-20` 明确把自查做成机械模块：加载四类阶段产物，运行约 20 条检查，写 `_review_issues.json`；每个 `Issue` 至少含 `severity`、`category`、`dim`、`evidence`、`suggested_fix`。`check_all_dims_exist()` 会把应运行但完全缺失的维度判为 critical；stage2 遇 critical 拒绝生成 HTML。检查还区分 profile/lite 模式，避免把未启用维度误报为缺失。

可吸收的是问题结构、规则注册和“阻断而不是只打日志”。不应把 UZI 的具体股票/港股规则原样复制，因为那些规则绑定其字段和业务范围。

### 本仓证据

- `src/research/domain/review.py:19` 的 `build_quality_snapshot()` 已聚合维度质量；`0_basic`、`2_kline` error 和行情 health blocked 可产生 critical。
- `src/research/domain/contract.py:49` 的 `QualitySnapshot` 已有 `blocked`、完整率、`market_revision` 和 `findings`；`DimensionResult` 已有 `quality`、`data_gaps`、`evidence`。
- 当前规则主要检查“是否存在、是否有时点/证据、行情是否健康”。研究 profile 仍可返回 partial/missing，尚无独立的终稿阶段、规则版本、跨维度一致性检查或自动拒绝下游分析的执行点。

### 建议：实施（P0）

在研究域新增可注册的 review rule 集合，规则只读取研究契约，至少覆盖：代码/名称一致、`as_of` 不晚于研究截止日、行情 revision 与输入 snapshot 一致、证据 source 与实际命中回执一致、计算字段单位/窗口一致、缺失字段没有被下游结论引用、外部数据未验证时保持 missing。每条 issue 保留 `code`、`severity`、`dimension`、`evidence`、`suggested_fix` 和 rule version。

门禁应有两个层次：critical 阻止生成“可供 AI 引用的完整结论”，warning 允许展示但必须显式标注；lite 只能减少检查范围，不能降低历史时点和生产写入安全。将 review 结果作为研究 artifact 保存，并由 AI 工具返回，而不是只在 HTTP 响应里临时计算。

## 3. 来源探针、选择与实际命中

### UZI 证据

- `skills/deep-analysis/scripts/lib/data_source_registry.py` 用 `DataSource` 记录 id、市场、维度、tier、访问方式和 health，并提供 `by_dim()`、`http_sources_for()`、`official_sources_for()` 选择候选。
- `skills/deep-analysis/scripts/lib/network_preflight.py:30-37` 的 `DomainCheck` 记录域名、分组、可达性、延迟和错误；`NetworkProfile` 记录按 domestic/overseas/search 的可用计数、探测时间、diagnostics，并以 5 分钟缓存复用。
- `pipeline/collect.py` 的结果契约要求维度写 `source`/fallback，上一份数据地图也确认：registry 是候选提示，fetcher 返回的实际 source 才是事实。

局限也必须吸收：UZI 的 registry 有不少静态 `known_good`，网络域名可达不等于接口字段正确、授权可用或结果有历史时点；因此不能复制“登记即健康”。

### 本仓证据

- `src/market/infrastructure/adapters/base.py:93`、`router.py:104` 已有按 lane/adapter 的 `probe()`；结果含 `rtt_ms` 和错误信息。
- `src/ops/api/data_sources.py:138` 的 `/api/ops/lanes/probe` 已能对 adapter 做实际探测并返回 lane、adapter 和 RTT。
- `src/research/application/catalog.py:69` 返回研究来源名片，但 `akshare`、`intel.mcp` 等标为 `not_probed`，`market.adapters` 的注册状态也没有被写入本次 profile；`DimensionResult.source` 只有本地技术结果，未记录 fallback 链或外部实际命中。

### 建议：实施（P0）

研究来源层新增三态或四态语义：`registered`（目录候选）、`probed`（本次探针成功，含时间/RTT/字段校验）、`selected`（本次实际返回）、`failed`（含原因）。复用 market adapter probe 和现有 lane 路由；外部网页/MCP 只允许显式配置并在最小权限下探测，不凭配置文件推断可用。

每次 fetch 产出 `source_attempts` 和最终 `EvidenceRef`：实际 source id、URL、请求/发布时间、`as_of`、fallback 原因、payload hash、字段契约版本。域名 socket 通只能作网络诊断，不能作为数据质量通过条件。没有实际命中或无法核验时仍返回 `missing`，不拿 UZI 评委分补齐。

## 4. AI 只读研究工具

### UZI 证据与边界判断

UZI 的 `commands/analyze-stock.md`、`pipeline` 阶段契约和 `agent_analysis_validator.py` 体现了“脚本产生结构化事实骨架，Agent 读取并写结构化分析”的模式；它不是一个具有本仓执行授权模型的研究 ToolBus。UZI 的 Agent 仍可能写入目标价、评级和叙事字段，因此不能把 Agent 输出视为权威行情或交易信号。

### 本仓证据

- `src/ai/application/system_toolbus.py:28` 定义 `ToolSpec`，`:65-82` 支持 `read_only` 过滤，`:85-89` 暴露 schema/catalog；工具注册表 `:174-221` 当前有 `market_kline`、`market_search`、策略和账本工具，但没有 `research_catalog` 或 `research_profile`。
- `src/ai/README.md` 已明确 AI 不发明数字、不提供任意 URL/shell/raw SQL；写操作由 ExecutionGrant 保护。
- `src/research/api/router.py` 的研究接口是只读 HTTP，但没有进入 AI 的静态工具目录，也没有把 budget、quality blocked 和 evidence contract 作为工具返回边界。

### 建议：实施（P1）

增加两个最小只读工具：`research_catalog` 和 `research_profile`。参数限定为代码、`lite|standard|deep` 和可选截止日；工具只能调用 research 的公开 API/应用入口，禁止直接掏 market/ops infrastructure、任意 URL、MCP 或写库。返回值必须包含 `quality`、`blocked`、`market_revision`、维度缺口、证据引用和“不能作为生产信号”的契约字段。记录 tool start/end、输入摘要和 artifact id，避免把完整外部原文无界塞入上下文。

AI 只能解释已验证数字，不能修改研究 artifact、策略默认、账本或市场数据。需要生成定性结论时走独立 conclusion artifact，并强制引用 evidence；critical 门禁未通过时只允许输出缺口和下一步，不允许输出买卖结论。

## 5. 历史安全与 point-in-time

### UZI 证据

UZI 的 `data-contracts.md` 有 `fetched_at`、dimension `source`/`fallback`；`pipeline/run.py` 能复用 `.cache/<ticker>`。但固定版本的多个实现使用 `datetime.now()` 生成报告日期，部分 fallback/估值使用当前值或代理值，cache 不是不可变快照，且财务/研报/持仓/搜索数据未统一按公告日截断。故其阶段缓存提升了可恢复性，却不证明历史安全。

### 本仓证据

- `src/market/infrastructure/store.py:93` 的 `data_snapshot()` 已提供各表 `fetched_at`、revision/content digest 和 `market_revision`。
- `src/market/infrastructure/store_rw.py:555` 的 `history()` 支持 start/end 和复权；行情层还有交易日历、来源和调整因子。
- `src/research/application/profile.py:33-36` 以当前 `trading_days()` 取最近 N 根，并调用 `store.history(..., start=start, adjust="qfq")`；`:52` 没有截止日参数，profile 只绑定当次读取的当前 snapshot，未持久化输入行情内容或历史研究 run。
- `src/research/domain/contract.py:16-29` 已有 `observed_at`、`as_of`、`payload_sha256` 字段，但当前本地 basic/kline 结果并没有把完整输入快照保存为可回放 artifact。

### 建议：实施（P0）

把 `as_of` 从展示字段提升为研究输入约束：profile/run 必须指定截止交易日；所有行情、公告、财务、事件和外部证据只能使用该日已可见数据。保存输入摘要以及必要的可重建原始行/证据 artifact，绑定 market revision、复权方式、交易日历版本和 source payload hash。重跑使用 snapshot，而不是重新读当前 `market.db`；数据库 revision 变化只使旧 run 标为 stale，不覆盖旧结果。

先只对本仓已有行情做验证：T 日信号只读 T 日收盘前可见行，执行与回测继续遵循既有 T+1/固定资金槽位契约。财务、估值、研报、基金、舆情等没有公告日可见性时，只做当前截面研究，不能宣称历史 alpha，也不能接入生产信号。

## 6. 暂缓与拒绝项

### 暂缓：UZI 机构研究报告与大规模 persona 面板

UZI 的 `research_workflow.py` 提供 initiating coverage、earnings analysis、catalyst calendar、thesis tracker、morning note 等结构化输出，`assets/data-contracts.md` 也提供报告 schema。这些可以作为未来研究视图模板，但当前仓没有可信且 point-in-time 的财务、公告、研报共识和产业数据源。先做会把“报告完整”误当“事实完整”，因此暂缓；待来源回执和历史快照闭环后，优先做事件日历/业绩变化等可验证模块，不先做 target price/rating。

### 拒绝：静态评分、代理估值和默认安全值

拒绝复制以下实现为本仓数字或信号：`FCF = net_income * 0.8`、`EBITDA = net_income / 0.6`、缺失毛利率推导、`price * 1.15` 目标价兜底、共识值按最新值乘 `0.95`、固定维度分、角色加分和 `18_trap` 的 safe-by-default。它们可用于 UZI 报告骨架，但没有真实现金流、横截面排名、入场/退出、成本、容量、冲突和组合回撤定义；直接复制会违反本仓“数字由量化引擎产出、AI 不发明数字”和“宁空勿弱”约束。

## 落地顺序与验收证据

1. 先实现研究 run 的输入快照、阶段 artifact、依赖 hash、resume/stale 语义；验收：中断后只重跑失效阶段，旧结果不被覆盖。
2. 接入 review rule registry 和 critical/warning 门禁；验收：缺失证据、时点越界、revision 不一致能稳定阻断或降级。
3. 将 adapter probe、source attempts、实际命中回执接到 research profile；验收：目录注册、探针成功、实际返回三者可区分。
4. 将 `research_catalog`/`research_profile` 加入 AI 静态只读工具；验收：read-only bus 可读，任何写授权、任意网络和生产信号路径都不可达。
5. 仅在上述证据齐全后评估事件/财务研究模块；所有策略或回测变更仍需单独的只读历史验证，不由本审计授权。

## 审计核验方式

- UZI：通过 GitHub raw/blob 在固定 commit 上读取 `pipeline/run.py`、`pipeline/collect.py`、`pipeline/schema.py`、`self_review.py`、`data_source_registry.py`、`network_preflight.py`、`assets/data-contracts.md`、`commands/analyze-stock.md`；未运行 UZI 采集、未把 release notes 的测试数字当作本次证据。
- 本仓：使用 CodeGraph 探索既有 `ops/ai/market` 调用关系，并对新建 `src/research` 直接读取当前磁盘源码；用 `rg -n` 核对上述符号和路由。只读检查期间未执行写数据任务。
- 工作树约束：本次只新增本文件，保留其他已有修改，不提交、不回滚、不改变策略默认或生产信号。
