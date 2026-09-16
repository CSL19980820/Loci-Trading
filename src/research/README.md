# 研究（research）

## 职责

把个股研究组织成可回溯的维度剖面：维度目录、来源名片、证据引用、质量状态、self-review 和本地技术指标。目录兼容 UZI-Skill 固定版本的 21 个 unique `dim_key`，但不复制其静态评委分或代理估值。

## 边界

研究上下文当前只读 `market` 的公开 API，不直接访问 `market.infrastructure`，不写 `palace.db`、`market.db` 或 `ops.db`，也不默认发起外部网络请求。普通 profile 是临时只读响应；用户显式创建 run 时仅写入 `data/research_runs/<run_id>/` 的 JSON 输入/阶段产物。PIT 事实与历史股票池也只以该目录下追加式 JSON 注册表保存，不能覆盖既有事实，也不能把今天的值或名单回填历史。

缺少可信来源的维度必须保持 `missing`；字段不完整使用 `partial`；计算异常使用 `error`。`market_revision`、`as_of`、来源和证据 hash 是研究结果的最低追溯字段。

## 关键入口

- `build_research_catalog()`：返回 21 维目录、预算档位、来源注册表和安全边界。
- `build_research_profile()`：从 `MarketStore` 构造不触网的临时个股研究剖面，支持 `as_of` 截止交易日。
- 研究快照直接使用 `MarketStore.history` 的 pandas 输入，已移除没有计算收益的 Polars 往返转换。`application/readonly_engine.py` 仅保留旧导入兼容，`readonly_frame` 原样返回输入；旧 `LOCI_RESEARCH_POLARS` 不再生效，`polars_research_enabled()` 如实返回 false。不改变研究 DTO 和快照指纹。
- `create_research_run()` / `resume_research_run()`：保存输入快照、profile、review 三阶段；相同输入 hash 可复用，行情版本变化只标记旧 run 为 `stale`，不覆盖旧输入。
- `run_research_backtest()`：请求必须预先声明完整且不重叠的 train/OOS 区间；严格 PIT 还必须给出 `historical_universe_id`。它先保存 `frozen_input.json`（signals、执行 OHLCV、entry-price、benchmark、PIT mask、随机配置），主 run、control、train/OOS 都只使用该冻结切片。**产物契约 `research-frozen-input-v2`**：紧凑分隔符（不再 indent，行情价格本身很短、空白会占掉近一半体积），且 `execution_panels` 与 `panels` 同源时写 `null` 由解码侧回落——全市场 370 日 × 5000 只、6 字段的产物从约 376 MB 降到约 71 MB。序列化只做一次，`payload_bytes` 的返回值既用于算 hash 也原样落盘，不要把 dict 交给 `write_artifact` 让它再 dump 一遍。v1 产物会被 `context_from_payload` 明确拒绝（版本不符），不会静默走到 hash 不一致；validation 通过后只会进入 `awaiting_human_review`，必须由受权限保护的人工签署才能完成。replay 校验冻结和执行 artifact hash、策略 revision，并逐项比较主结果、控制组与 train/OOS；终态 run 只允许 `workflow-final.json`、`run_card.md`、`replay-comparison.json` 三类审计收尾 artifact，既有相同 hash 写入可幂等重放，其余新增或 hash 不同的写入一律拒绝。
- 当前技术回测的 PIT 输入范围仅为行情证据和历史股票池。PIT 财务/事件事实可追加登记、按截止日查询并为后续因子研究保留来源与 `available_at`，但尚未被技术回测选择、冻结或消费；任何引入这类事实的未来回测都必须先冻结被选 observation、revision 和 hash，再进入严格门禁。
- 时点数据集的来源快照保留全部实际报价关联回执，额外历史失败记录仅汇总，并以 `receipt_details_omitted=true` 标识。严格 PIT 拒绝此模式；非严格研究保留缺口警告，不能把减少来源详情解释为证据补齐。
- 冻结JSON通过标准库文本流分块编码UTF-8，避免整份含中文Unicode文本及换行副本同时占用内存；排序、紧凑分隔符、末尾换行和v2字节/hash契约不变。回归既比较旧版精确字节，也约束大载荷编码的额外内存峰值。
- 完整研究在冻结后释放原始面板，在解码后释放列表载荷，冻结字节写盘并校验后释放；分析完成后不把无后续读者的行情、对照组和分期大对象留在workflow state。重放同样在解析/校验后释放原始字节与临时载荷，避免完整历史规模下同时保留多份输入；计算仍只使用冻结数据。
- `ResearchRunCardStore` 的run card和映射型artifact直接流式编码UTF-8到临时文件，分块读取文件计算hash，不在`BytesIO`中累积整份工件。保留原有两空格缩进、排序、末尾换行、非有限数转null及各入口的未知类型处理差异。映射工件先写同run目录临时文件，再在原锁内重读并校验路径、终态与不可变hash，通过后才原子改名和记录manifest；失败清理临时文件。byte/string入口保持既有契约。
- JSON规范化仅复制确需转换的分支，已合法的dict/list直接复用且不原地改动，避免对已规范化的大批交易明细和来源记录再次深复制。后台研究任务完成时只提取run_id，完整run card继续由详情/列表接口按既有契约读取，不在仅需编号的后台路径调用完整`to_dict()`。
- 同一JSON锁内登记工件时，保存路径复用刚读并验证的旧card，仍执行输入hash和状态约束；独立保存仍读盘校验，没有跨请求缓存。
- 大执行工件重放使用 `infrastructure/json_artifacts.py` 和固定依赖 `ijson==3.5.1` 从文件分块解析，避免原始文件字节与解析对象同时驻留。解析前后均检查文件SHA，严格读至EOF；Decimal数值事件转为Python float，整数保留原精度，键名仅在本次读取中复用。完整字典仍用于全部字段比较，不裁减交易。冻结输入使用已安装的 `pydantic_core.from_json` 直接解析字节。接口依据：[ijson官方用法](https://github.com/ICRAR/ijson)、[Pydantic Core JSON API](https://docs.pydantic.dev/latest/api/pydantic_core/#pydantic_core.from_json)。
- `build_quantile_signals()` / `analyze_cross_section()` 的等量分组是整块向量化的：按 (分数, 代码) 升序用 `np.lexsort` 一次算完整块面板的名次，再 `np.put_along_axis` 反解组号，全程不碰标签索引。口径与逐日 `sorted()` 完全一致——同分仍按 `str(code)` 升序，非正/非有限分数仍判无效且不占名额，非调仓日仍不产生任何选择。唯一可观察的差异是元数据：旧实现用 `.loc` 标签散写会把 `groups/top/bottom` 的 `columns.name` 抹成 `None`（且只在当天真被选中时发生），现在原样保留。250 天 × 5500 只、每日调仓实测 8.92 s → 0.13 s。
- `run_pth252_factor_experiment()`：固定研究候选 `close / rolling_max(high, 252)`；盘后信号、T+1 开盘执行、每 20 个交易日调仓并持有 20 日。仅从最高十分位按分数保留至多 20 只，成交失败位置保持空缺。它复用研究回测、冻结重放和因子敏感性产物，但不会注册进 `src.strategy` 的四个活动战法。
- HTTP：`GET /api/research/catalog`、`GET /api/research/profile/{code}?budget=lite|standard|deep&as_of=YYYY-MM-DD`、`POST /api/research/runs`；历史股票池和 PIT 事实通过独立 temporal API 查询或追加导入；研究回测在人工审核后只能发布或否决，两个结论都绑定 artifact manifest。
- PTH252 HTTP：`POST /api/research/factor-jobs` 只接受固定参数和已有 `historical_universe_id`，异步任务通过 `GET /api/research/factor-jobs/{job_id}` 查询。严格 PIT 任一证据缺失都会标记任务失败；若已生成 run，失败响应仍保留 `run_id` 以读取诊断 artifact。
- HTTP 分文件与端点归属见 [`api/README.md`](api/README.md#文件清单)。回测端点组 2026-08 拆到 `api/backtest_router.py`（它持有进程级线程池 `_BACKTEST_EXECUTOR`，已登记进 `tests/ai/test_tenant_threads.py::_GUARDED_FILES`；再拆时清单要跟着走）；`build_research_router` 仍 `include_router` 它，URL 集合与挂载方式不变。
- 技术指标：`application/technical.py`，只对行情仓历史日 K 计算 MA、MACD、RSI、KDJ、OBV、Williams %R、Stage 和 VCP 代理。

## 如何扩展

### 历史时点与逐日账户

研究请求的 `backtest_config` 可携带 `signal_dataset`、`strict_limit_prices`、`economic_returns`、`valuation_end`；顶层 `account_model="daily_close"` 开启逐日估值和当前权益仓位。快照战法缺省执行配置、仓位数和账户模式来自其模板，显式值优先。冻结输入保存时点数据SHA、实际信号、原始执行价格、经济因子及账户配置；train/OOS各自截止，账户日历排除指标预热。

`analysis.json` 的 `portfolio` 保存每日权益、闭合交易和未平仓；`conclusion.portfolio_summary` 只投影它供界面查看。新模式重放另重新计算整份portfolio并比较每日记录与未平仓，旧模式重放不变。时点数据完整不等于已解决历史ST/成分身份，探索性标记与人工签署规则仍保留，不能把数值一致伪造成审核通过。

1. 先在 `domain/dimensions.py` 明确字段、依赖、历史安全性和候选来源。
2. 在 `intel` 或 `market` 的公开适配器契约中接入来源；注册表中的 `health` 不代表实际请求成功。每次 run 还要保存 `source_attempts`，区分登记、探针、实际命中和失败。
3. 保存实际命中 `selected_source/source_url/published_at/publication_status/fetched_at/as_of/payload_sha256/parser_revision/available_at/availability_status`，并为失败返回 `partial/missing/error`；输入快照必须包含实际消费的原始行和 input hash。严格 PIT 的已选成功 receipt 必须字段完整，且 `publication_status`、`availability_status` 都为 `observed`；自动同步无法观察到的历史发布时间或可见时间必须明确标为 `not_observed`，不能由抓取时间替代。财务/事件事实写为 `PointInTimeObservation`，历史成分写为 `MembershipSnapshot`，两者必须带来源、版本和可见日期。
4. 新增 review rule 时注册到 `domain/review.py`；critical 阻止标记为已核验，warning 只允许带缺口展示。
5. 只有通过质量门禁和前视审计的数据，才可进入 `strategy` 的研究验证；研究定性标签不能直接变成生产信号。
6. `strict_pit=true` 是严格证据门禁：PIT/生存者偏差、OHLC 覆盖或结构坏值、来源 attempt 缺失，或已选 receipt 的来源、载荷 hash、解析版本、发布时间/可见时间证据不完整任一项都会拒绝。非严格运行会标为 `degraded`，不得作为 hypothesis 通过依据；PIT 注册表本身不代表供应商数据已验证，只有被 run card 选中并冻结的事实才是本次运行证据。

## 给 Agent 的用法

```python
from src.research import build_research_profile, list_dimension_specs
from src.market import MarketStore

with MarketStore() as market:
    profile = build_research_profile(market, "600519", budget="standard")
```

不要从 `src.research.infrastructure` 的私有文件路径或 `src.market.infrastructure` 深路径取数据；不要将 UZI 的综合分、目标价代理或搜索片段补进历史回测。AI 只能通过 `research_catalog` / `research_profile` 只读工具消费投影，不能创建 run 或写入策略。

`research.infrastructure` 已由 import-linter `protect-research-infra` 契约保护；域内仅 `api` / `application` / `domain` 可导入。

## README 维护

新增维度、来源、质量枚举、公开接口或持久化语义时必须同步本文和 `api/README.md`，并更新 `docs/architecture/bounded-contexts.md`。固定研究候选还必须记录公式、执行时点、选股容量、PIT 前提和是否注册为活动策略。

## 相关测试

`tests/research/`：

- `test_temporal_lookahead.py`：防前视不变量。可见性只认 `available_at`——财报期已过但未披露、成分已生效但未公告，都不能被当日的回测看见；`assert_strict_membership` 对降级/生存者偏差/证据不全一律拒绝。
- `test_run_card_state_machine.py`：人工签署不可跳过（`running` 不能直达 `completed`）、否决不可翻案、终态只能降级为 `stale`；输入指纹两道锁（领域层不接受手填的不一致 hash，存储层拒绝同 `run_id` 换输入）。
- `test_frozen_artifact.py`：冻结产物的体积契约与确定性——序列化必须逐字节可重现（否则 hash 自校验会随机失败）、同源执行面板不重复落盘、NaN 在编码阶段就收敛成 `null`、浮点快路径与逐格兜底逐值一致。
- `test_readonly_engine.py`：pandas / 可选 Polars 等价性。
- `test_factor_quantile_parity.py`：等量分组向量化前后的等价性。文件里留了一份逐字照抄的旧实现当 oracle，对含并列分数、非正值、±inf、整天/整列缺失的合成面板逐元素比对 `groups/top/bottom/status`（NaN 位置与 dtype 一并比），并覆盖全 NaN 列、样本不足、单行、空行、空列；`analyze_cross_section` 用 mock 换回旧分组函数做整体回归。

上面三个新文件都做过变异验证：把可见性判据换成 `observed_on`、或短路状态机白名单，或把分组的次关键字从 `str(code)` 去掉，测试都会红。

`test_daily_close_replay.py` 已覆盖临时数据/产物目录中的时点输入、完整研究、每日估值账户冻结与重放，以及被篡改账户明细的拒绝；不替代真实行情规模的内存和线上运行验收。**仍未完整覆盖**：artifact manifest 各类幂等与拒写边界、PTH252 因子实验、`api/router.py` 全部 HTTP 契约。跨上下文导入由 `tests/app/test_import_boundaries.py` 和全仓 `lint-imports` 约束。
