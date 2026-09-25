# 天才交易员三阶段提示词与能力链路审查（2026-09-18）

## 范围与结论

审查工作区：`E:/my_space/stock-analyzer`。对象是 Guardian（现称天才交易员）的盘前、日复盘、周复盘，不是 stock_agent/龙头交易员。首次审查阶段只修改本地源码、增加隔离测试及本文档；当时没有部署、重启服务、调用真实模型生成报告、发送实际通知、改动生产账户或执行真实交易。用户随后授权的线上补丁发布记录见文末。

接手时三阶段提示词已经具有较好的自主性：阶段目标不同，但不强制研究顺序、工坊覆盖、观察数量、每天新增机会、固定条数经验或每周更换策略。保留这些已有设计，不把此前的自主性改动计作本次成果。

本次发现并修复了三个应用层问题：默认身份与实际阶段冲突；历史报告及工具发现失败时连纯计算能力也失去；预载旧报告未校验该版本的实际生成时间。它们分别影响角色一致性、工具可用性和研究记忆的可信度。提示词版本更新为 `2026-09-18-phase-v3`。测试验证的是工程行为，不是收益率、胜率或模型推理能力的提升幅度。

## 三阶段目标与自由度

| 阶段 | 有价值的目标 | 不应变成的机械任务 |
| --- | --- | --- |
| 盘前 | 形成可修订的当前判断、行动条件、失效依据和待核实问题，供盘中继续判断 | 必须看完工坊、必须新增股票、必须交易、逐股重写无变化内容 |
| 日复盘 | 用当时可知证据比较意图、决策与实际结果，区分观点错误、执行问题和不确定性，保留后续研究线索 | 按盈亏倒推对错、替未记录的行为编造理由、每天硬凑经验 |
| 周复盘 | 跨日与相关历史检验假设，识别反例、环境和样本依赖，决定延续、修改或搁置 | 日报拼接、连胜即规律、每周强行换策略或给自己增加永久禁令 |

模型可以选择工坊内外的研究对象，也可以不研究工坊；可以推翻或保留自己已有观点。提出新假设不要求已经有验证样本，但宣称假设获得支持、反证或完成事实纠正时仍需真实证据。研究自由与现金、可卖数量、执行时点、模拟账户规则不是同一个层次。

## 本次改动

### 1. 阶段身份不再继承内置的“当前进行盘中研判”

文件：`src/ops/application/guardian_review_prompts.py`，`review_system`。

此前报告路径用 `DEFAULT_PROMPT` 作为兜底，阶段提示词为空或缺失时可能把内置盘中身份带入盘前或复盘。现在按盘前/复盘选择相应内置默认；只对精确匹配的内置盘中默认进行报告阶段适配。

用户自定义基础提示词、显式阶段提示词、公共身份均保留。公共身份只拼接一次；调用方传入的配置对象不被原地修改，也没有写回用户配置。

同时给三阶段协作提示词补充能力反馈出口：模型可在 `operational_notes` 中提出所需工具、数据或记忆能力，说明输入、用途及对判断的影响。临时能力缺口不应被总结成永久交易禁令；建议也不等于系统已实现或模型已自行修改配置。

### 2. 纯计算能力独立于实时数据工具发现

文件：`src/ops/application/guardian_compute.py`、`guardian_research_tools.py`、`guardian_review_agent.py`。

统一 `guardian_calculate` 工具名称与 schema，在报告执行器本地注册并去重。历史报告和当日外部研究工作台发现失败时，仍能计算已有材料中的数值，得到可回读、可引用、成功/失败明确的工具证据。

历史报告仍不加载不带对应历史时点约束的当前数据工具，避免把今天行情带回过去。这个边界不再连带剥夺纯计算。计算器沿用既有十进制算术实现，不执行任意 Python，不改账户、不下单；它不是通用代码实验沙箱。

### 3. 预载记忆与历史工具使用一致的时间边界

文件：`src/ops/application/guardian_review_data.py`，`_report_available_as_of` 与 `build_review_facts`。

此前 `previous_reviews` 预载主要检查名义交易日期和成功状态，可能把后来更正生成的旧日报当作当时已经存在的材料；`has_premarket_report` 也未检查可用时间。

现在统一以报告创建时点与目标交易日结束时点的较早者为截止时间。优先检查版本 `created_at`，缺失时使用数据库 `started` 的 Unix 时间戳；无时区的日期字符串按 UTC 解释；显式无效时间不被偷偷替换成另一时间。预载正文、对应证据编号及盘前报告存在标记使用同一检查，并提供 `previous_reviews_as_of`。

这不是删除记忆或限制研究数量。当前版本不符合历史时点的报告不会被预载为当时已知；原报告及修订归档没有被修改。本次未实现从修订归档中自动恢复每个历史时点的原版本。

## 已核对、保留的能力链路

报告不仅是通知文字：成功结果保存事实、分析、计划、研究笔记、假设进展和工具证据；后续阶段可回读。`guardian_review_history` 提供日期、类型、关键词、报告编号检索与分页；初始预载五份不是总记忆只能五份。`guardian_context_read` 提供本轮完整原文读取，大材料的预览和分页不等于原文丢弃。

报告 schema 对计划、研究笔记、经验和个股分析没有固定条数上限；`validate_brief` 只做展示测量，不因字数或条数拒绝报告。模型可在修复最终 JSON 时继续回读或补查证据，不被强制重跑全部研究。提示词给阶段目标与结果契约，不规定完整思考步骤。

三个报告入口本身不成交；后续执行依据当时实际行情、资金、可卖量与有效期重新核验。没有为了“自主”删除事实校验、租户隔离或账户执行规则。

## 验证记录

新增 `tests/ops/test_guardian_phase_prompt_audit.py`，共 51 个参数化场景：9 个阶段默认身份、6 个自定义配置保留、6 个独立计算执行与证据引用、30 个预载记忆时间及旧时间格式兼容场景。模型与通知相关测试使用替身，账本使用临时目录。

三阶段专项回归：**143 passed in 25.31s**。

```bash
.venv/Scripts/python.exe -X utf8 -m pytest \
  tests/ops/test_guardian_phase_prompt_audit.py \
  tests/ops/test_guardian_phase_capabilities.py \
  tests/ops/test_guardian_review_repair.py \
  tests/ops/test_guardian_workbench.py \
  tests/ops/test_guardian_reviews.py \
  tests/ops/test_phase_prompts.py::test_stage_selection_and_empty_or_legacy_fallback \
  tests/ops/test_phase_prompts.py::test_guardian_report_selects_stage_and_drops_legacy_preferences \
  tests/ops/test_phase_prompts.py::test_guardian_stage_config_persists_and_legacy_has_empty_overrides \
  tests/ops/test_phase_prompts.py::test_legacy_builtin_split_preserves_custom_and_explicit_fallback \
  tests/ops/test_phase_prompts.py::test_guardian_old_builtin_split_survives_partial_save \
  -q --tb=line --maxfail=5
```

改动文件的 Ruff F 检查通过，定向 `git diff --check` 没有空白错误，仅有已有 CRLF/LF 转换提示。

```bash
.venv/Scripts/python.exe -X utf8 -m ruff check --select F \
  src/ops/application/guardian_compute.py \
  src/ops/application/guardian_research_tools.py \
  src/ops/application/guardian_review_agent.py \
  src/ops/application/guardian_review_prompts.py \
  src/ops/application/guardian_review_data.py \
  tests/ops/test_guardian_phase_prompt_audit.py
```

## 扩展检查未通过项（没有隐藏或改弱校验）

执行整个 `tests/ops/test_guardian*.py` 扩展回归时，达到五项失败后停止，未完成全量验证。其中本次记忆兼容问题已修复并包含在上述 143 项通过结果中；另外两份执行测试单独重跑仍为 **4 failed, 11 passed in 2.09s**：

- `test_guardian_actions.py` 的止盈/止损两个参数场景和持有场景：测试买入输入只有价格和时间，当前实际执行逻辑先以缺少可核验实时盘口拒绝成交，后续持仓/T+1断言不成立。
- `test_guardian_failure_receipts.py::test_bad_rounded_price_does_not_rollback_independent_legal_order`：预期部分成交，但实际结果为 rejected。保留该失败，未修改执行器或账户校验来迎合断言。

```bash
.venv/Scripts/python.exe -X utf8 -m pytest \
  tests/ops/test_guardian_actions.py tests/ops/test_guardian_failure_receipts.py \
  -q --tb=line
```

导入架构检查 `.venv/Scripts/lint-imports.exe`：**12 kept, 2 broken**。检查输出指向两处本次没有修改的跨层导入：

- `src.ops.application.guardian_tools` 直接导入 `src.market.infrastructure.adapters.tencent_adapter`（第80行）。
- `src.app.main` 直接导入 `src.ai.infrastructure.grpc_gateway`（第267行）。

因此只能声称三阶段专项与改动文件静态检查通过，不能声称项目全量回归、全部架构契约或上线验收通过。

## 仍存在的实际边界与建设方向

报告执行器没有另设研究轮数或每轮工具调用数上限，但仍有 900 秒单次执行期限、上游模型上下文/输出容量、取消机制和实际工具可用性。最多三次是最终输出验证/修复尝试，不是最多三轮研究。没有修改模型选择或用户思考档位配置。

中断研究尚不等于可持久化续跑；失败诊断和工具回执不等于能完整恢复模型的中间工作状态。修订归档已存在，但历史工具当前主要读取成功报告的现版本，本次只补预载时间一致性，没有实现原版本自动回放。历史报告的计算能力不等于任意代码实验能力。复盘可形成外部研究记忆，但保存报告不等于更新模型权重。

要继续增强系统，重点应是可恢复的研究工作状态、按时点回读修订版本和可验证的研究工具，而不是增加固定思维模板、强迫活跃或无限延长一次同步调用。以上是审查结论，不代表这些扩展已落地。

## 后续线上补丁发布（用户授权后）

2026-09-18 北京时间 **16:01:31.976717** 完成发布及健康验证，**16:02:06** 再次核对三阶段实际配置拼接。

- 生效镜像：`loci-qianlong:2.0.0-20260918-phase-v3-final`。
- 生效镜像 ID：`sha256:ea8c521474e3b95d5ee225a7261b7dbf22b94323695ac4628477f476f6f8d4b7`。
- 精确基线：`loci-qianlong:2.0.0-20260918-152526`，镜像 ID `sha256:6e07211c972fe67e4d46161ecadac959cfb41219b02e512a361b2dc2b3d97be6`。
- 发布目录：`/srv/qianlong-loci/releases/2.0.0-20260918-phase-v3-final`。
- 回退资料：`/srv/qianlong-loci/backups/guardian-phase-v3-20260918-160100`。

核对时发现线上此前已于15:27独立发布了部分 `phase-v3` 内容，阶段默认身份修复、独立计算工具及相关配置代码均已存在。因此没有重发整个有未提交改动的工作区，只补两个文件：`guardian_review_prompts.py` 中的能力反馈说明，以及 `guardian_review_data.py` 中最终的预载记忆时间校验。

补丁以当时实际运行的镜像为基线构建，只增加一个 COPY 层。核对全部679个 Python 源码文件，只有这两个文件发生变化，其余677个与基线完全一致；镜像运行配置、依赖和前端沿用基线。实际生产服务来自 `/srv/qianlong-loci/docker-compose.yml`，服务名 `qianlong-loci`，调度器与应用在同一容器，本次只重建该服务。

发布前，真实镜像在断网、没有生产数据挂载的独立容器中通过51个场景，覆盖阶段身份、自定义提示保留、预载时点及旧时间格式、实际 Agent 工具调用与证据引用。没有调用真实模型或发送通知。本地专项也重新执行，结果 **143 passed in 25.49s**；发布脚本及修改文件 Ruff F 检查通过。该专项结果不替代上文列出的全项目失败项。

15:45日复盘、15:55周复盘运行时，发布检查返回 busy，没有切换生产。16:01检查任务空闲后才备份并替换 `.env` 的 `LOCI_IMAGE`，没有修改业务配置或运维数据库。发布前后 Guardian 配置及 `guardian_trades` 表哈希一致。未操作资金、持仓或下单接口；没有修改已有报告或强制重新生成今天的报告。

发布后，容器健康状态为 healthy，内网与公网 `/api/health` 均为 HTTP 200。使用只读 SQLite 读取当前实际保存的交易员配置，再通过线上报告代码分别拼接盘前、日复盘、周复盘系统提示词，三者均包含能力反馈说明；未来版本记忆校验和本地计算工具检查通过。提示词版本仍为 `2026-09-18-phase-v3`，本次最终补齐内容由发布镜像和文件哈希区分。

服务器发布目录保存 `manifest.json`、`base-source.json`、`offline-result.json`、`publish_release.py`、`deployment-result.json`；本地 `.local/guardian-phase-deploy-20260918/` 保存对应回执、运行时验证和专项测试记录。回退应先确认当前仍为本次镜像，再恢复上一镜像设置并重建此服务；不要覆盖之后的新发布或恢复整份交易数据库。

此发布完成的是本轮已实现的三阶段修复与能力反馈说明。研究断点续跑和历史修订原版本自动回放仍未实现，不包含在本次上线范围内。
