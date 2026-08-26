# Vibe-Trading 固定版本对比研究

> 审计日期：2026-08-04
>
> 对象：[`HKUDS/Vibe-Trading`](https://github.com/HKUDS/Vibe-Trading)
>
> 固定 commit：[`3a752d5a8ed088633040893de1cc9e6dc712596f`](https://github.com/HKUDS/Vibe-Trading/commit/3a752d5a8ed088633040893de1cc9e6dc712596f)
>
> 固定提交信息：`docs: add the 2026-08-04 correctness-pass news to all five READMEs`

本文是只读对比研究，没有安装 Vibe-Trading、没有运行它的行情下载或回测，也没有修改本仓策略默认参数、数据库或研究结果。外部项目结论以固定 commit 的源码为准；README 中的项目自述只在其能被源码路径佐证时使用。本仓对比的是当前工作树：其中 `src/research/` 尚未提交，文中会单独标识为“当前工作树能力”，不把它表述为已发布基线。

## 结论

Vibe-Trading 最值得借鉴的不是“大量因子、LLM 或多 Agent”，而是把研究过程做成可追溯的工程对象：一次回测有 run card、输入/策略 hash、验证产物和风险解释；一个因子/想法有状态与证据链接；复杂研究流水线有依赖、失败阻断和事件记录。

本仓已经具备更贴近 A 股单市场的策略、行情快照和回测基础。下一阶段应优先补“研究证据链”，而非扩大策略/因子数量：

1. 增加统一的 `research run card`，将策略 revision、参数、股票池、行情快照、指标、验证、产物 hash 和结论绑定；
2. 在现有回测之上增加严格随机对照、真正隔离的样本外区间、时间分段、实际换手和风险透视；
3. 将策略版本历史升级为有证据链接的 hypothesis 生命周期；
4. 把当前只读 `src/research` 的输入快照/`stale` 语义接到上述 run card；
5. 交易流水复盘可借鉴 Shadow Account，但仅作为未来 A 股、只读、规则可审计的研究工具。

不建议照搬 Vibe-Trading 的因子库、跨市场资金曲线、LLM/Swarm 选股结论、券商连接器或广泛 MCP 权限。它们会扩大数据、执行和安全边界，但不能提高本仓现有策略结论的可信度。

## 1. 固定版本中已核验的能力

### 1.1 回测不是只返回一个指标，而是保留可复核证据

Vibe-Trading 的 `write_run_card()` 会写入配置 hash、策略文件 hash、数据源/有效来源、指标、验证结果以及每个 artifact 的 SHA-256；结果同时输出 `run_card.json` 和可读 Markdown。这种设计把“这次结果是如何产生的”与净值/收益指标放在同一记录中，而不是依赖调用者日志。

证据：[run_card.py#L25-L81](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/run_card.py#L25-L81)、[run_card.py#L147-L167](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/run_card.py#L147-L167)。

指标侧不止有收益/回撤：`calc_metrics()` 优先采用实际成交推导的 turnover，并记录基准收益、超额、信息比率、tracking error 与 beta。风险透视和调仓说明也分别写成独立 artifact。

证据：[metrics.py#L365-L407](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/metrics.py#L365-L407)、[metrics.py#L440-L593](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/metrics.py#L440-L593)、[risk_xray.py#L86-L352](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/risk_xray.py#L86-L352)、[rebalance_notes.py#L25-L110](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/rebalance_notes.py#L25-L110)。

### 1.2 严格因子检验把“强于零”改成“强于同宇宙随机对照”

`run_bench_strict()` 明确要求传入 `random_control`，以同一日期、同一股票池内的行随机因子作为基线；可选 train/test 切分，并将结果分类为 `confirmed_alive`、`train_only`、`reversed_strict`、`noise`。该模块的源码注释也直接指出：只对零做 t 检验会产生大量假阳性。

证据：[bench_runner_strict.py#L1-L45](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/factors/bench_runner_strict.py#L1-L45)、[bench_runner_strict.py#L96-L180](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/factors/bench_runner_strict.py#L96-L180)、[bench_runner_strict.py#L317-L366](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/factors/bench_runner_strict.py#L317-L366)。

这是本次最有价值的研究方法启发。它不会证明策略未来有效，但能显著降低“偶然样本中看起来有 alpha”的误判。

### 1.3 假设和回测产物有最小生命周期关联

Hypothesis Registry 定义 `exploring`、`testing`、`validated`、`rejected`、`monitoring` 五个状态，并允许向一条假设附加 `run_card_path` 或 `backtest_run_dir`。这比仅在策略元数据中存一组静态指标更接近研究账本。

证据：[registry.py#L21-L25](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/hypotheses/registry.py#L21-L25)、[registry.py#L82-L109](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/hypotheses/registry.py#L82-L109)、[registry.py#L286-L318](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/hypotheses/registry.py#L286-L318)。

### 1.4 流程编排将“失败”和“未执行”变成显式状态

Swarm 使用 YAML 声明任务依赖，先校验 DAG，再按拓扑层并行执行。上游失败会使下游标记 `blocked` 并不派发；运行期间持久化事件，任务允许有限重试。这个模式的价值不取决于是否调用 LLM，而在于避免把部分失败的研究误报为完整成功。

证据：[models.py#L15-L30](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/swarm/models.py#L15-L30)、[task_store.py#L151-L245](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/swarm/task_store.py#L151-L245)、[runtime.py#L1-L5](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/swarm/runtime.py#L1-L5)、[runtime.py#L477-L555](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/swarm/runtime.py#L477-L555)。

### 1.5 执行语义和数据正确性是显式模块，不隐藏在信号里

其 A 股引擎把 T+1、禁止做空、涨跌停、100 股整手、佣金/印花/过户费写成交易规则；组合引擎遇到混合结算货币会直接拒绝，而不是把不同币种直接相加。后二者是值得本仓坚持的“宁可拒绝，也不制造一个看似精确的数字”的原则。

证据：[china_a.py#L4-L37](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/engines/china_a.py#L4-L37)、[china_a.py#L45-L87](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/engines/china_a.py#L45-L87)、[composite.py#L65-L95](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/engines/composite.py#L65-L95)。

### 1.6 数据来源与时点安全也需要成为研究输入

行情获取会保留请求源、识别源、实际使用源、fallback 与未解析代码；显式请求本地源失败时不会悄悄改用网络数据。loader 边界统一校验 OHLC 结构，避免坏 bar 在下游静默变成 `NaN`/`inf` 指标。对本仓而言，最值得复用的是把每次来源尝试、实际命中、未解析代码和字段/覆盖率异常写入 run card，而不是引入其整套多市场 loader。

证据：[market_data.py#L95-L214](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/market_data.py#L95-L214)、[registry.py#L117-L242](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/registry.py#L117-L242)、[base.py#L50-L120](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/base.py#L50-L120)。

其 SEC fundamentals loader 以公告 `filed` 日而非报告期末使财务值可见，并处理部分重述/季度口径；CSI300 股票池在可得历史成分时显式输出 `pit_membership`、`survivorship_bias` 和 `degraded`。本仓未来接入财务、公告、事件或指数成分时，应建立 `available_at`/`published_at` 和历史成分快照；缺失时必须标记偏差，不能以今天的名单回填历史。

证据：[fundamentals_loader.py#L1-L120](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/loaders/fundamentals_loader.py#L1-L120)、[alpha_bench_tool.py#L368-L456](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/alpha_bench_tool.py#L368-L456)。

## 2. 与本仓的能力对照

| 维度 | 本仓当前事实 | Vibe-Trading 的可借鉴点 | 建议 |
|---|---|---|---|
| 行情可追溯性 | `MarketStore` 保存原始价与稀疏复权因子，`data_snapshot()` 输出行情 revision、行数和时间摘要。 | run card 再保存本次的配置/策略/artifact hash。 | 复用本仓 `market_revision`，不要引入另一套行情仓。 |
| 策略身份 | 策略有 `strategy_revision`、`version`、`version_history`；前端/API 已支持读取、回滚、删除版本。 | 把版本与假设、回测证据、审批结论关联。 | 新增 hypothesis/run-card 关联，不改变现有四战法展示或默认参数。 |
| 回测结果 | 已有入场时点、T+1、止损/持有期、MAE/MFE、胜率、盈亏比、PF、基准超额、股票池漏斗、行情健康度和数据快照。 | 增加实际换手、时间分段、风险透视和结构化 artifact 清单。 | 先扩展回测输出契约，再考虑 UI。 |
| 研究阶段产物 | 当前工作树中的 `src/research` 已有 `input/profile/review`、input hash、`as_of`、`market_revision`、reuse/resume/stale，并且只读业务库。 | 用统一 run card 把研究产物和回测产物交叉引用。 | 将其作为研究账本底座；提交前仍需完成该模块自身测试与边界验收。 |
| 研究验证 | 现有回测能给出历史表现；近期组合研究已强调固定资金槽位、持仓重叠与闲置现金。 | 同宇宙随机对照、严格 OOS、分段一致性和风险解释。 | 不以一次全样本 PF/胜率决定上线。 |
| 流程编排 | 已有任务/作业体系和研究阶段写盘。 | DAG、失败阻断、阶段事件、有限重试。 | 先将确定性研究阶段建模为 DAG，不导入多 Agent 投票。 |
| 复盘 | 已有复盘上下文，但没有从交易流水抽取规则并反事实回放的稳定闭环。 | Shadow Account 的“流水 -> 规则 -> 回放 -> 归因”框架。 | 只做单市场、只读、规则和输入可审计的实验性功能。 |

本仓源码证据：

- 行情快照和复权模型：[src/market/infrastructure/store.py#L1-L17](../../src/market/infrastructure/store.py)、[src/market/infrastructure/store.py#L93-L117](../../src/market/infrastructure/store.py)；
- 策略选股输出中的 `strategy_revision`、健康度、股票池漏斗和数据快照：[src/strategy/application/screener.py#L41-L60](../../src/strategy/application/screener.py)、[src/strategy/application/screener.py#L135-L189](../../src/strategy/application/screener.py)；
- 回测任务的策略/参数/基准传递与结果采样：[src/ops/application/jobs/backtest.py#L9-L41](../../src/ops/application/jobs/backtest.py)；
- 策略版本和回测指标 API 类型：[frontend/src/shared/types/screenSkill.ts#L56-L83](../../frontend/src/shared/types/screenSkill.ts)、[frontend/src/shared/types/screenSkill.ts#L424-L445](../../frontend/src/shared/types/screenSkill.ts)；
- 当前工作树的 research 契约与恢复语义：[src/research/README.md#L1-L25](../../src/research/README.md)、[src/research/application/run.py#L104-L187](../../src/research/application/run.py)。

## 3. 建议的落地顺序

### P0：定义统一 `research run card`（优先做）

在本仓新增一个只追加的研究运行记录，至少包含：

```text
run_id
strategy_slug / strategy_revision / version
hypothesis_id（可为空）
requested_as_of / actual_as_of / market_revision
universe + universe_funnel + params + BacktestConfig
data_snapshot / input_sha256 / source evidence
metrics / validation / risk_xray / conclusion
artifact manifest（path、sha256、created_at）
status：running | completed | stale | failed | rejected
```

约束：计算输入不可被成功后的 UI 编辑覆盖；策略或行情 revision 改变时，旧 run 保持可读但标记 `stale`；报告只引用具体 `run_id`，不引用“最新一次”。这可直接复用当前 `src/research` 的 artifact store 和 `market_revision` 语义，避免另起一套文件协议。

### P1：在回测内建立分层的证据门禁

建议按确定性程度排序，而不是一次性加入所有统计工具：

1. 真实交易/组合层的 turnover、资金占用、空仓比例、月度/年度分段与最大回撤；
2. 固定训练区间和独立 OOS 区间，参数仅可在训练区间选择；
3. 同日、同宇宙、同覆盖率的随机对照；
4. 风险透视：按市场状态、行业/板块、持有期、入场类型、极端亏损和跳空失效拆解；
5. Bootstrap/Monte Carlo 仅作为不确定性描述，不能替代 OOS 或随机对照。

这些结果应写入 run card，且由状态机决定是否从 `testing` 变成 `validated`。`validated` 的含义应是“满足已声明门槛的历史研究结论”，不是“可保证未来收益”，也不自动授权改动生产默认参数。

### P2：把策略版本接入 hypothesis 生命周期

建议最小实体为 `Hypothesis`，字段包括 thesis、假设日期、适用市场/股票池、预注册指标和阈值、失败条件、关联 strategy revision、关联 run ids、当前状态和人工结论。每次状态迁移保留时间、操作者和证据；不要只有可变的一份 JSON 快照。

这比直接复制 Vibe-Trading 的注册表更稳妥：其代码已经给出状态和 run card 关联的好模型，但本仓应利用已有 DDD 边界和持久化方式实现审计历史与并发安全。

### P3：仅在资料齐备时试验 A 股 Shadow Account

实验边界应为：导入用户明确授权的成交流水；解析出结构化 roundtrip；所有价格特征严格截止于买入日前；规则由可解释区间表达；反事实回放必须使用同一 A 股交易规则、股票池和数据快照；每项归因标为“启发式估计”而非真实因果。

Vibe-Trading 的提取器确实设有盈利 roundtrip 数量下限，并以买入日之前的数据计算价格特征；这部分可作为防止小样本和前视偏差的参考。证据：[extractor.py#L64-L144](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/shadow_account/extractor.py#L64-L144)、[extractor.py#L227-L300](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/shadow_account/extractor.py#L227-L300)。

### P4：采用 DAG 思想，不采用“Agent 多数表决”

适合本仓的确定性阶段可以是：`capture_input -> calculate -> validate -> render -> review -> publish`。任何上游数据不足、验证失败或 review 未通过，都应让下游产生 `blocked`，而不是生成一份看似完整的结论。LLM 可以为证据做摘要，但不得生成指标、填补缺失数据或绕过门禁。

## 4. 不应照搬及原因

| 不照搬项 | 原因 |
|---|---|
| 整个 Alpha Zoo 或以因子数量作为能力指标 | 因子数量不是样本外有效性；严格对照本身就说明大规模枚举容易产生假阳性。 |
| 将 Monte Carlo / bootstrap 称为 OOS 证明 | Vibe 的 Monte Carlo 是重排既有 trade PnL，walk-forward 是基于已生成曲线的事后切窗；两者有研究价值，但都不等于重新训练/参数隔离的样本外验证。证据：[validation.py#L1-L8](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/validation.py#L1-L8)、[validation.py#L131-L203](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/backtest/validation.py#L131-L203)。 |
| 多市场混合资金曲线 | 固定版本主动拒绝混币种，证明它没有统一 FX 层；本仓应继续聚焦 A 股资金规则。 |
| Shadow Account 的多市场输出作为排名/交易证据 | 其 v1 `per_market` 会复用 combined metrics，且归因是算术启发式而非完整交易路径重建。证据：[backtester.py#L336-L349](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/shadow_account/backtester.py#L336-L349)、[backtester.py#L393-L514](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/shadow_account/backtester.py#L393-L514)。 |
| 把 fallback 成功当成无差别的同一份数据 | 不同源、未解析代码、字段缺失、缓存命中与 OHLC 异常会改变可交易覆盖率。只应吸收其 provenance/显式降级语义，不能让 fallback 掩盖输入变化。 |
| 报告期末或今日指数成分直接用于历史回测 | 这会分别造成财务前视和生存者偏差；只有 `available_at` 与历史成分快照齐备时，才可声明 point-in-time。 |
| Swarm/LLM 输出直接改变选股或资金分配 | 依赖模型判断的文本结论不可替代确定性信号、回测和风险门禁；它适合整理证据和驱动工作流。 |
| 券商连接器、shell 工具与宽泛 MCP | 本仓当前任务是研究/策略工作台；这些能力会引入密钥、交易授权、网络访问和供应链边界，且未获得本次授权。 |

固定版本还有不宜直接投入生产的实现错位：Shadow codegen 写 `initial_capital`，而执行引擎读取 `initial_cash`，自定义资金可能静默退回默认值；默认扫描工具既未注入 `price_frames` 也未注入 `fetcher`，会得到空候选；profile 保存非原子且加载未校验 `shadow_id` 路径成分。Swarm 虽有 DAG 阻断、工具白名单和 operator 配置的 MCP 边界，但 prompt 要求 `bash`，默认又关闭 shell 工具；重试也只覆盖 `failed`，不覆盖 timeout/token-limit，且行情 grounding 只在运行开始抓取一次。上述问题足以说明它们只能作为设计参考，不能直接纳入本仓研究或交易路径。

证据：[codegen.py#L178-L186](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/shadow_account/codegen.py#L178-L186)、[shadow_account_tool.py#L346-L367](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/tools/shadow_account_tool.py#L346-L367)、[scanner.py#L77-L97](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/shadow_account/scanner.py#L77-L97)、[storage.py#L66-L85](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/shadow_account/storage.py#L66-L85)、[worker.py#L270-L285](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/swarm/worker.py#L270-L285)、[runtime.py#L640-L730](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/swarm/runtime.py#L640-L730)、[grounding.py#L120-L220](https://github.com/HKUDS/Vibe-Trading/blob/3a752d5a8ed088633040893de1cc9e6dc712596f/agent/src/swarm/grounding.py#L120-L220)。

## 5. 采纳前的验收标准

任何实现都应先满足以下条件，再讨论是否改变策略候选或生产默认值：

1. 同一 `run_id` 在相同输入快照下可重放，且能定位策略/参数/行情/artifact hash；
2. 所有统计和风险输出都带样本数、时间范围和失败/跳过原因；
3. OOS 与随机对照使用预先声明的切分和随机种子，不能在看到全样本后再选阈值；
4. 缺数据、数据版本变化、验证失败和人工拒绝必须显式呈现，不能被“报告生成成功”掩盖；
5. 任何新候选先进行只读历史验证，不自动替换四战法现有默认参数；
6. 没有引入真实 `data/` 污染、外部写操作、密钥或交易权限。

## 6. 本次研究边界

- 版本固定在上述 commit；上游 `main` 后续变更不包含在本文结论内。
- 已阅读固定 commit 的回测、严格因子验证、假设注册、Shadow Account、Swarm 及 A 股/组合引擎关键路径；未安装依赖或运行第三方数据源，因此不宣称运行可用性、性能或外部数据质量。
- 本仓 `src/research/` 为当前工作树能力；其最终可用性仍以独立测试、导入边界检查和后续提交为准。
- 本文是工程与研究方法建议，不构成收益预测、投资建议或生产参数变更授权。
