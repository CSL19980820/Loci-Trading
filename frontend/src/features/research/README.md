# research

量化工坊中的研究证据台：默认只读查看，可由用户显式归档本次输入快照。

- `ResearchPanel.vue`：标的、预算、质量快照、来源回执、21 维状态和显式归档，并编排可审计回测与假设面板。
- `components/ResearchBacktestPanel.vue`：所有研究回测提交前都校验完整 train/OOS 和日期边界；严格 PIT 额外校验历史股票池标识。面板异步轮询 job，读取 run/workflow、查看 artifact manifest 并发起 replay；只有主回测、随机对照、训练和 OOS 全部匹配才显示回放通过。
  **已拆**（607 → 390 行，仓库 600 行硬规则）：job 轮询与 replay 编排抽成
  `components/useResearchBacktestJob.ts`，「主回测 / 随机对照 / train / OOS 四者全匹配才算回放通过」
  的状态判定抽成 `components/researchBacktestStatus.ts`。判定单独成文件是因为它是**纯函数**——
  四项里少判一项就会把没通过的 run 显示成可上线，该有的测试点在它身上，不在轮询逻辑里。
- `components/ResearchPublicationDialog.vue`：仅对 `awaiting_human_review` 且 `validation=passed` 的 run 记录人工签署；原样回传后端给出的 `artifact_manifest_sha256`，不在前端计算 hash，也不改变生产策略默认参数。
- `components/ResearchRejectionDialog.vue`：以同一份服务端 manifest 摘要记录人工否决；否决与签署均不修改生产策略默认参数。
- `components/ResearchTemporalDataPanel.vue`：显式浏览、按截止日解析和导入历史股票池快照与 PIT 事实；选择股票池只回填 `historical_universe_id`，实际日期解析仍由后端完成。
- `components/ResearchFactorPanel.vue`：提交固定 PTH252 因子研究任务，前端只校验日期和已导入的历史股票池标识；轮询 job 并展示后端 run 的指标、验证和 artifact，不改变任何活动策略。
- `components/ResearchHypothesisPanel.vue`：创建假设、生命周期迁移、人工审核及可核验 artifact 证据绑定。
- `components/ResearchDimensionRail.vue`：维度目录与状态选择。
- `components/ResearchDimensionDetail.vue`：单维事实、缺口、技术指标和证据 hash。
- `composables/useResearchProfile.ts`：研究目录、临时剖面与归档 run 请求状态。
- 后端缺失维度直接显示 `missing`，不在前端补综合分或推荐结论。

公开请求统一经 `shared/api/quant.ts` 或研究域模块 `shared/api/quant_research.ts` 发出；不要在组件里拼接 `/api` 或调用外部来源。归档、回测、回放、假设迁移和人工审核均只能通过显式按钮触发，不能在加载 profile 时自动写入。

研究回测使用已有的 `historical_universe_id`。历史股票池和 PIT 事实只能通过研究数据区的显式读取或 JSON 批量导入进入后端；前端不伪造下拉选项、快照或本地 mock。严格 PIT 的最终行情覆盖、来源回执和成分快照校验仍由服务端拒绝或通过。PTH252 job 即使失败也可能返回 `run_id`，面板应继续加载该 run 的诊断 artifact，而不能将失败状态展示为可上线结果。

当前研究回测只消费服务端冻结的行情和历史股票池；PIT 财务/事件事实在本面板可登记和查看，但不会自动参与技术回测或被展示为已验证的因子输入。
