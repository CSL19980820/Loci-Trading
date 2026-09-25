# 天才交易员执行契约

本文说明当前代码如何把研究结论转成可核账的报价模拟成交，以及失败、取消和通知如何收口。账户范围、费用、历史迁移、报告和咨询见[天才交易员](guardian.md)；本文不代表部署或测试通过记录。

## 1. 完整性与一次无工具修复

主入口为[`jobs/guardian.py`](../src/ops/application/jobs/guardian.py)。交易日按五分钟槽位研判；09:25、11:30、15:00为仅分析边界，共51个调度时点。交易所日历决定是否开市，模型研究、报价刷新和最终落账分别检查各自条件。

有持仓且处于连续竞价时，先取持仓报价并检查已保存的结构化风险合同。有可执行触发、过期或失效事件时进入风险执行轮，不依赖新的模型回答；仅有缺价事件时保留风险回执，并继续研究其他机会，避免单股缺价使整个模型失去研究能力。旧自然语言计划不会自动变成风险订单。

[`guardian_completion.py`](../src/ops/application/guardian_completion.py)和[`guardian_contract.py`](../src/ops/application/guardian_contract.py)要求本地`stopped_reason=completed`、上游结束原因`stop`或`end_turn`，且正文通过完整决策schema。`length`/`max_tokens`表示截断；缺失结束原因也不能直接成功，半段JSON恰好可解析不构成完整性证明。流已由供应商正常收尾（`[DONE]`/`message_stop`）却不回传结束原因时，直接以不可重放错误说明“供应商未返回结束原因”，不再按瞬时中断重跑两次完整生成；流内`error`事件原样报出真实原因（限流、过载、内容审核、余额等），其中限流/过载/上游超时仍按可恢复中断处理。

首次出现允许修复的完整性或JSON错误时，最多追加一次无工具修复。使用已有输入、消息、工具证据和错误原因，重新输出完整JSON，不拼接残片、不重跑研究或成交。超时、取消、异常结束及轮数耗尽不能借修复绕过；修复后仍须通过同一契约。每次结束原因、输出长度、用量和错误诊断均保留。

买入权限（科创板/北交所等不可买）属于逐笔订单问题，与结构契约分开：决策须先通过完整schema与竞价计划复核，才判权限。修复提示只要求撤回或替换越权买入，其余订单保持原判断。修复后仍越权、或修复输出本身无效时，采用已通过结构校验的决策，越权订单在预检中按`board_not_allowed`拒绝并计入受阻，其余意图（包括止损、减仓卖单）照常核价，不因单笔越权整轮作废。诊断分别记`accepted_with_policy_rejects`或`fallback=policy_rejected_original`。

`thinking_requested`只记录请求的思考档位或`provider_default`，不能证明上游实际采用了相同档位。结束原因、返回的推理字段与请求配置是不同证据，不互相替代。

## 2. 本轮买卖的价格授权

`buy/add/reduce/sell/take_profit/stop_loss`须提供整数`quantity`、理由和`execution`；`hold/watch/unwatch`股数为0，观察只维护观察池。模型不指定实际成交价、费用或盈亏。

| 字段 | 含义 |
|---|---|
| `kind=market` | 市价意图；可给固定 `reference_price`，未给时绑定首次有效执行报价 |
| `kind=limit` | 至少一个原始价格边界，按用户授权允许最多2%执行偏离 |
| `min_price` / `max_price` | 有限正数，拒绝布尔值；同时存在时下限不得超过上限 |
| `reference_price` | 可选有限正数；另与其上下2%范围求交，后续刷新和最终修正不得移动 |
| `valid_until` | ISO时间，到达即失效；应写明时区，漏写时按北京时间（+08:00）解释 |

最高买价、最低卖价、突破或回踩区间必须写入价格字段，只写在`reason`中不构成执行约束。执行容差以原始基准计算一次：上限乘1.02、下限乘0.98，包含边界，使用Decimal比较；9.00上限允许9.01和9.18，不允许9.19。此为用户授权的应用执行容差，不冒称交易所申报价格笼子。实际金额按核验成交价记账，不回写为参考价。等待未来确认的机会使用hold/watch，不能把未满足条件写成当前market意图。

直接买卖授权应不晚于输入的`execution_deadline`；写入更晚时间也不能延长整轮300秒窗口。`execution`只决定是否允许成交，价格仍来自最后核验的报价并按账本规则换算为分。提交前以实际`price_cents / 100`再次核验，价格取整不能绕过授权。

## 3. 共用报价验证与备用源

[`guardian_quotes.py`](../src/ops/application/guardian_quotes.py)统一执行、估值及风险报价校验：对象有效、无源错误，价格为非布尔的有限正数；显式股票代码错配时拒绝。日期和时间合并为北京时间，年龄须在0至180秒内，允许行情时间最多比本机晚60秒（时钟偏差、按结束时刻标注的进行中分钟线）；缺时间、更晚的未来时间或过期报价均无效。

[`guardian_tools.py`](../src/ops/application/guardian_tools.py)在悟道可用时优先取单股`minute_data`，最多四路并行。主源异常、缺报价、价格/代码/时间无效的股票进入系统备用源；主源不可用时直接走系统源。备用结果通过同一验证器，不能以旧价掩盖主源失败。

备用成功保留`primary_error`及实际来源；两源失败保留主源错误和`fallback_error`。无效报价不覆盖估值或参与撮合，旧估值仍带原行情时点作为参考。模型研究后、预检修正后及提交前分别核验所使用的报价。

取价等待检查取消和剩余期限，协作式取消与运维超时不能包装成普通缺价后继续成交。每次并发提交复制租户ContextVar；已启动的同步备用源调用可能运行到自身超时，取消后的迟到结果不得提交。外部HTTP MCP传输期限见第8节。

## 4. 取消、owner和双时钟提交

[`execution_window`](../src/ops/application/guardian_outcome.py)同时要求启动和当前时刻均为连续竞价，墙钟差值与单调耗时均满足`0 <= elapsed < 300`。满300秒或墙钟回拨均不能扩大成交窗口。研究及修复共用最多270秒预算，报价及提交仍受整轮300秒约束。

研判、取价、提交检查取消及当前配置。`OpsStore.guardian_commit_guard`用运维库事务与取消/配置写入串行化；`GuardianStore.finish`验证轮次仍为running及已绑定的`owner_run_id`匹配。失败收口同样拒绝错误owner，旧worker不能覆盖终态。

`before_commit`在账本写入前和提交前各检查一次取消、配置、时段、双时钟、报价及逐笔价格授权/有效期，失败回滚该次提交。账户、fills、轮次和待发通知同事务保存，并核对现金、费用、已实现盈亏与各股数量变化和fills一致。同一槽位不可重复记账。

| 情形 | 结果与通知 |
|---|---|
| 09:25、11:30、15:00启动的正常仅分析意图 | 保存`deferred`，不成交且静默，下一轮重新研究 |
| 连续竞价启动，回答或核价后跨出窗口/超过预算 | 执行受阻、failed，按通知配置提醒，不补造历史成交 |
| 主动无意图或合法hold/watch/unwatch | `no_action`，内部留存 |
| 成交且无受阻意图 | `traded`，按配置通知 |
| 有受阻意图 | 有fills为`partial_execution`，无fills为`rejected`；failed并按配置通知 |

预检撤回、风险受阻和尾盘未收敛都保持可见；可独立核账的合法成交可随失败轮次保存。取消单独记cancelled，不产生新的异常通知；已落账旧通知仍可独立补发。仅分析边界正常静默不等于所有异常都静默。

## 5. 有限预检修正与原拒单

[`simulate`](../src/ops/application/guardian_decision.py)先在账户副本上检查订单和组合，尚未落账。对股数、现金、持仓上限、T+1、收盘留仓等可修正拒单，且有原研究续写上下文、研究预算至少剩20秒时，`guardian_order_repair.py`最多追加一次无工具修正。这与完整性修复是两个步骤。

修正只能降低原股数、撤回意图或调整留仓名单。按原股票和动作匹配，不新增股票、改变方向、重复意图、扩大数量、放宽价限或延长有效期；原limit不得变market。原非交易动作保留，程序不随意取整。收盘自动执行及风险执行轮不走此模型修正。

模型修正时常照抄最初输出，省略程序绑定的`reference_price`和`opening_plan_id`；程序按原股票和动作补回原值后再校验（只会保持或收窄约束），不因此把合法缩量判为“移动参考价”。0股交易视为撤回。竞价计划复核沿用原决策；关联订单被撤回的execute计划记为受阻，不使整轮失败。

修正后从同一未落账账户重新模拟，重新取价并校验窗口；首次取价未能绑定参考价的市价意图按本次首个有效报价绑定。`original_decision`、`initial_rejects`和修正诊断保存；成功修正也不擦除原拒单。被撤回的原交易另记`withdrawn`，即使最终零成交也不能改成主动无动作。

最终`rejects`、`withdrawn`和错过窗口的意图合成`blocked`，决定受阻状态及通知。组合留仓预检失败不能留下半套换仓结果；已可独立核账的实际成交与未执行意图分别保留。

## 6. 结构化风险合同

[`guardian_risk.py`](../src/ops/application/guardian_risk.py)管理合同，[`guardian_risk_execution.py`](../src/ops/application/guardian_risk_execution.py)生成风险执行轮及最终回执。

`risk_plans`可附在hold或买卖动作上，最多16项；省略/`null`保留原合同，`[]`撤回全部，watch/unwatch不能使用此字段。每项包含`action=stop_loss|take_profit`、正整数股数、有限正数`trigger_price`、非空理由和`execution`。

合同按该动作实际完成后的持仓安装。hold验证完整列表后替换；买卖先在副本撮合，再安装完整合同，均成功才接受该笔变化。安装失败不留下交易或半套合同；清仓后不得安装非空合同。安装校验总持仓股数，T+1可卖量在触发后成交时检查。

`basis_quantity`和`basis_opened_at`绑定安装时数量及开仓批次，变化或合同标识错误记invalidated，到期记expired。`plan_id`由股票、开仓批次及结构化授权计算，理由文字不参与；匹配已有ID时保留原基准和终态，不能仅改理由或重复安装来复活已executed的合同。

风险有效期可以跨五分钟轮次，不受本轮直接买卖`execution_deadline`限制；触发出的普通模拟卖单仍受当轮窗口、最终报价、原价限、有效期、股数与T+1限制。

止损在报价`<= trigger_price`触发，止盈在`>= trigger_price`触发；每股每轮最多一笔，止损优先。二次取价时，止损将触发价并入价格上限，止盈并入下限，原有价限继续保留；首次触发仍严格判断，触发后锁定观测报价并以统一2%执行范围复核，范围外才拒单，不因一分钱回弹误拒；触发价不充当成交价。新增可选字段缺省为null不改变旧合同ID，旧合同不会因升级无故失效。

风险执行轮仅止损/止盈减仓，不开仓、加仓或改合同。缺价、过期、失效均有明确风险拒单。已发生的风险成交不因等待模型修正留仓名单而撤销，尾盘未收敛另报失败。

`consume_risk_plans`只消费匹配的实际fills：股票、动作、股数、理由、执行价限、前后数量及发生时间均须一致且未过期，一笔fill只消费一次。清仓后也在`risk_events`保留executed回执。缺价、T+1或最终价格不符不消费有效合同，可后续重试；持仓基准变化和到期则须重新确认。

账本提交成功后，成交和消费状态才成为保存事实。提交失败保存原风险事件，不把未落账触发描述为已执行。旧`holding_plan/take_profit_plan/stop_loss_plan`只用于研究和展示，不从文本猜测自动执行授权。这是五分钟采样的报价模拟，不是券商条件单，不保证实时止损、按触发价成交或捕捉采样间全部变化。

## 7. 逐ID通知目标与重试

[`guardian_notices.py`](../src/ledger/infrastructure/guardian_notices.py)保存租户待发通知，[`guardian_delivery.py`](../src/ops/application/guardian_delivery.py)独立投递。标题正文随轮次/账户事务保存；投递失败不回滚成交、不调用研究或撮合。

首次解析投递目标时保存`channel_targets`：旧通道按kind、ID、type区分，注册通道按注册名区分。快照仅含目标身份，不保存凭据或完整配置；发送时重查该ID和类型，删除或类型变化记`channel_unavailable`，不自动改投其他通道。

`channel_receipts`逐目标保存成功/失败/跳过，同类型多通道分别记账。已成功目标不重试，只处理尚未成功目标。旧类型聚合回执仅在唯一目标时导入成功，多ID歧义标记`ambiguous_legacy_receipt`，不猜送达对象、不自动重投。

事务领取pending或过期sending记录，按`attempts, slot`升序选择：先尝试次数少的，同次数再按轮次排序，避免反复失败的旧消息始终占满领取批次、阻塞新告警。领取后增加attempt并持有300秒租约。每次发送及每个长消息分段前后写进度，续展仍有效的自有租约；写入和收口均匹配slot、attempt、sending与未过期租约；旧投递者失去租约后不能覆盖新回执。失败保持pending，后续`deliver_pending`续传，另一目标失败不使已成功目标重发。

外部接受消息与本地落回执之间没有分布式事务，该间隙断连或进程中断后可能再次投递，不能承诺外部exactly-once。通道静默、限流及休市门禁继续生效，暂缓不伪装送达。交易员执行通知保存完整正文，不只留第一片；`guardian_delivery_parts.py`按UTF-8字节及标题序号分段，逐目标逐段保存回执，只补发未确认的分段。`guardian_delivery`租户任务在工作日08:00—20:55每五分钟检查待发队列，仍遵守静默和用户启停；不重跑模型、不重新成交。状态接口返回pending/sending/oldest_slot，便于看到积压。盘前/复盘报告沿用其报告通知链，见[报告说明](guardian.md)。

## 8. Agent并发、期限与用量

[`agent_execution.py`](../src/ai/application/agent_execution.py)默认顺序，仅并发显式白名单的独立只读请求。交易员使用明确的独立只读工具集合，包含市场工具及账户、报价、预演、计算与证据读取，按服务名前缀后的原名匹配，默认最多四路；并发调度不限制可查询股票或研究方法。连续白名单请求成组，其他工具和`ask_user`形成顺序屏障，结果按模型原请求顺序回填；MCP观察池写工具不自动并发。

研判、咨询与报告研究不再设置固定轮数或单轮工具总次数上限，分别使用真实270秒、300秒、900秒运行期限；模型选择、思考档位和配置容量保留，不通过降级模型或丢弃证据续跑。其他调用方显式设置次数上限时，每个超额tool-call ID仍收到`TOOL_NOT_EXECUTED`、`executed=false`回执，不能静默丢弃请求。取消后不再提交未启动请求，迟到同步只读结果不参与成交。

`McpClient`持有可变初始化状态、session ID、request ID，不可跨线程或租户共享。交易员用thread-local保存客户端，并核对当前租户重建；仅复制ContextVar不构成客户端线程安全。

外部HTTP MCP支持`McpClient.call_tool(..., deadline=...)`，公开`call_mcp_tool`、`guarded_client_call`透传同名参数。值为有限单调时钟绝对时刻，省略保持旧调用方式；不修改共享客户端timeout。嵌套取更早期限，退出恢复ContextVar。

[`mcp_deadline.py`](../src/intel/infrastructure/mcp_deadline.py)用可取消异步HTTP承接同步API，握手、初始化通知和tools/call共用剩余时间，收包也计入。退出时响应体和连接池分别有最多125毫秒的关闭宽限，合计最多250毫秒；清理超时或异常不覆盖原有超时、取消或请求错误，原请求正常时才向外报告清理失败。同步portal保留原取消异常，清理宽限不延长交易意图的有效期。原URL、代理、重定向及响应大小约束保留。

DNS解析在只读线程中执行；超期或取消时可放弃等待，但底层系统解析线程可能稍后才结束，不能宣称线程已被强停。被放弃的解析结果不会继续派发HTTP请求。

配额获取`acquire_quota(pool, deadline=...)`仍为同步API，但有期限时以至多0.1秒小段等待并持续复核剩余时间；超期不占用新名额、不继续HTTP。工具返回后也检查期限。可选HTTP期限不等于所有本地同步工具可强行中断，也不改变所有适配器默认超时。交易员研究工具和悟道执行取价传递本轮期限，系统备用源迟到结果由取消检查及提交闸门排除。

[`agent_budget.py`](../src/ai/application/agent_budget.py)每次请求及流式降级复制供应商配置，将timeout压到剩余预算。文本估算含system、消息、schema、参数、调用ID、原始推理；仅在已知窗口下计算剩余输出，未知窗口不猜默认容量。图像token不按base64长度推算，文本预检不保证多模态实际容量。

已知容量不足明确失败，不删除工具/推理或降低思考档位伪装成功。`agent_usage.py`隔离每次调用已知用量：响应返回先计数，随后取消仍保留增量；未返回的在途用量不猜。研究、完整性修复、预检修正分别记增量后汇总，禁止重复记录整轮累计。

### 8.1 模型研究工作台

`guardian_research_tools.py`合并原行情工具与`system__`前缀的系统只读工具，悟道可用不再隐藏网页、策略和本地研究能力。提供`guardian_account_read`、`guardian_runtime`、`guardian_quotes`、`guardian_preflight`、`guardian_scenario`、`guardian_calculate`及`guardian_decision_history`。每轮复制账户输入，每线程独立工具实例，每次历史读取独立账本连接，租户不串用。

预演在副本上调用同一会计算法，返回费用、资金、T+1、价格范围及拒单；研究中可自主更换股票、方向和股数后重新预演，不受最终一次收缩式修正限制。预演不是成交承诺，最终提交重新核价。情景工具只描述假设涨跌、组合权重和锁仓，不新增止损比例、单股上限或交易战法要求；十进制计算器不执行任意Python代码。

报告和咨询同样保留实际选定的思考档位，并按每次调用增量计费，取消/截断不算完整回答。报告不再限于四个研究工具或最多20只股票评价；失败工具回执不能作为有效经验依据。历史报告仍不能拿未来数据替代历史证据。

## 9. 原文证据与历史归因

[`ResearchContext`](../src/ops/application/guardian_research_context.py)限本租户本轮。大段候选信号、策略说明和历史材料以摘要加`evidence_ref`提供，原字符串或原对象JSON序列化全文保存，引用由UTF-8正文SHA-256生成。摘要没显示的细节不能推断为不存在。

`guardian_context_read(ref, offset, limit)`返回原文片段、相同hash、总字符数及`next_offset`；默认每页12000字符，单页100至24000字符。越租户或未知引用返回错误。长工具正文同样可转原文引用，原始参数、完整回执及文档保存到运行诊断；财务数字和最新持仓行情不因摘要化被截掉。

成功完成和异常终止都通过`evidence_snapshot`在档案锁内深拷贝工具回执和原文文档，冻结到本次结果或异常的用量诊断中。取消后尚在退出的只读工具不能再通过共享对象修改已收口的证据快照。

`guardian_evidence.py`的`guardian_decision_history`检索历史原意图、条件变化、程序拒单和输入来源。研判前保存的`decision_context`在成功和失败收口均保留，当前配置不反推未记录的历史规则；未记录逐股评价时明确未记录，不补写主动放弃。见[决策证据说明](../src/ops/README.md#交易员决策证据与机会复核)。

## 10. 模拟范围与回归入口

本系统是带费用、T+1和账户约束的新鲜报价模拟，没有盘口队列、真实交易所撮合、排队成交、滑点路径或流动性保证，不能称为微观实盘模拟。盈亏来自账本与行情；模型经验仍为`candidate_not_validated`，经后续统计及样本外验证前不能宣传为已验证收益。

以下为对应回归入口，不表示本次文档任务已运行/通过这些测试或已部署：

| 契约 | 回归入口 |
|---|---|
| 完整性及用量 | `tests/ops/test_guardian_agent_repair.py`、`test_guardian_usage.py` |
| 单笔越权不整轮作废、修正沿用绑定 | `tests/test_guardian_repair_resilience.py` |
| 取消、owner、过期与预检撤回 | `tests/ops/test_guardian_execution_safety.py`、`test_guardian_session.py` |
| 主备报价和线程会话 | `tests/ops/test_guardian_quotes.py`、`test_guardian_tool_sessions.py`、`test_guardian_tools.py` |
| 风险合同及账户 | `tests/ops/test_guardian_risk.py`、`tests/ledger/test_guardian_cash_account.py`、`test_guardian_position_limit.py` |
| 通知与租约 | `tests/ops/test_guardian_delivery.py`、`test_guardian_delivery_parts.py`、`test_guardian_reliability.py` |
| Agent并发/容量/用量 | `tests/ai/test_agent_execution.py`、`test_agent_budget.py`、`test_agent_usage.py` |
| 可选HTTP传输期限 | `tests/intel/test_mcp_deadline_transport.py` |
| 2%容差及工具工作台 | `tests/ops/test_guardian_price_tolerance.py`、`test_guardian_workbench.py` |
| 自适应研究及配额期限 | `tests/ai/test_agent_adaptive_capacity.py`、`tests/intel/test_quota_deadline_wait.py` |
| 历史证据与归因 | `tests/ops/test_guardian_evidence.py` |
