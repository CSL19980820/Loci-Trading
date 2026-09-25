# 交易员咨询复用助手三栏工作台

对应用户截图中的 Guardian「对话」区域（现称天才交易员），按助手布局改为左侧话题、中间消息与思考、右侧详情。采用实际组件复用，不复制一份助手 Dialog 或业务会话状态机。

## 布局与复用

- 左侧直接使用 `AssistantSessionRail`：搜索、话题列表、新话题、删除确认、折叠。该场景不开放助手专属的归档、批量管理和全局助手设置；主助手原默认能力保持。
- 中间直接使用 `AssistantConversation` / `AssistantTurnTimeline`：用户气泡、交易员身份、模型/时间、思考、工具调用、回答及复制使用相同组件。通过 `assistantLabel` 与 `allowRerun` 适配角色，失败消息通过 `after-message` 插槽保留逐条重新编辑入口。
- 右侧直接使用 `AssistantTaskSidebar`：只展示真实存在的「来源」与「上下文」；通过 `cabin` 插槽放置本话题的实际持仓/执行偏差说明，仍在发送咨询时保存，不改变模拟账户。
- 桌面左右栏分别约 240/260px，可折叠。按咨询容器实际宽度响应：小于 1100px 将右侧收进 Sheet，700px 及以下左侧也用 Sheet，不依赖整个浏览器的宽度。
- 保留流式回复、上滑阅读位置、原有话题 ID/request_id、错误重试、背景恢复、输入法和模型未配置时的提交保护。

## 思考与真实进度

以前公开咨询结果只记录正文和最终工具摘要，本轮补上可供页面读取的过程字段：

```ts
thinking?: string
tool_receipts?: { call_id: string; name: string; status: 'running' | 'done' | 'error'; elapsed_ms?: number; summary?: string }[]
phase?: 'preparing' | 'thinking' | 'tools' | 'answering' | 'done' | 'error'
```

`thinking` 来自模型协议真实 `think.delta`，多轮以空行分隔；工具起止在实际执行边界计时。阶段切换与工具边界立即落盘，文本增量按 0.2 秒节流。成功、失败与断线重连都保留过程，既有终态迟到更新守卫继续生效。显示思考沿用脱敏并限制 8000 字符，回执最多 100 条，不保存工具原始参数/结果到公开进度中。

旧历史缺少的思考不补造；已有旧格式工具记录可转换为已完成/失败的回执，未知耗时留空。模型未给出思考文本时仅显示真实运行阶段。运行错误显示「思考已中断」，不会把中断过程标成完成。

后端变更限于 `src/ops/application/guardian_consult.py`、新增 `guardian_consult_progress.py`、以及 `src/ai/__init__.py` 对既有脱敏函数的公共导出，无 DDL、策略、订单或工具权限调整。

## 验证

- 前端：19 个文件、145 项测试通过；类型检查与最终生产构建通过。
- 后端：临时数据/config、禁止外网环境中 180 项通过；717 模块导入、0 失败。导入边界检查没有本次新增违规，仍有 3 条既有违规：guardian_tools→tencent_adapter、app.main→grpc_gateway、app.main→backtest_jobs，未为本轮修改规则或扩大修复。
- Guardian 真实 Chromium：9/9，覆盖日夜/桌面/390、思考与工具展开、容器响应、话题搜索/切换、删除取消与确认、新话题、request_id 重试、背景恢复、流式阅读位置、完成态 Markdown、无模型/IME。
- 特别验证：全局侧栏占 224px、咨询容器仅 900px 时，右侧自动变抽屉，中间宽度 660px。
- 共用左右栏的主助手默认与 Guardian 精简配置均验收；主助手 4 组组合检查覆盖阶段等待→原生思考→中断、附件与键盘；既有功能组合 5/5。
- 精确候选镜像：通用 10 项与本次思考/工具/SSE 8 组通过。后者 network none、tmpfs、无宿主数据挂载、384MiB/1CPU、调度关闭；未调用真实模型，候选均已清理。

## 发布与证据

已部署版本 `2.0.0-20260922-232513`，镜像 `sha256:7a0acba243609c0c4971f1effc4028ceaaef6da9549ff296cec2add5bcfcf12f`。切换前只读确认 active_consultations=0。

- 生产容器 healthy，UID 10001；1,027 个运行文件与发布包哈希一致，环境配置与原 JSON 保持，nginx 首页匹配。
- 公网首页及 266 个静态资源共 267 项哈希匹配；health/auth options 为 200，未登录管理接口为 401，缺失资源为 404 且 no-store。
- 切换后的日志检查：415 行中 ERROR/Traceback 为 0，候选容器残留为 0。

- 上一版 `ui-20260922-225007`，镜像 `sha256:b1859c00fe2cb57ea57fde5c77f2148428db72fa9940f502b608ce251b73dca9`。
- 回滚镜像 `loci-rollback:consult-workspace-20260922-232513`。
- 一致性备份 `/srv/qianlong-loci/backups/consult-workspace-2.0.0-20260922-232513`，4 个业务 SQLite quick_check 均为 ok，环境/编排及相关 JSON 保留。
- 回执 `.local/guardian-assistant-workspace-20260922/deploy/`；后端本地测试 `.local/guardian-consult-progress-20260922/`；浏览器模拟场景 `.local/shadcn-foundation-20260922/consult-results.json` 与截图。

本次临时打包/备份脚本和上传压缩包已清理；保留测试脚本、验收回执和回滚材料。未提交或推送 Git。

## 已登录生产浏览器

1680px 大屏中实际查看三栏：左 SessionRail 240px，右 TaskSidebar 260px，中间共享 Conversation/MessageFooter。读取既有 2 个话题，搜索筛到 1 项、切换历史后恢复原话题；旧历史的 2 条工具记录正常映射到来源，无新增虚构思考块，背景仅查看未编辑。1280px 时右侧转为 480px Sheet，来源可读且无横向溢出。

390 手机模拟视口下左右 Sheet 均为 366px，显示与 Escape 关闭正常，无横向溢出。主助手原有 3 条历史、新建/归档/多选/设置入口及 5 个任务分区完整，左右栏展开收起正常。浏览器 console 警告/错误为 0。

此次生产检查未发模型消息、创建/删除话题或改动背景。保持原夜间主题，恢复原话题、搜索、折叠及视口，关闭临时标签页。Vite 已停止，5174 无监听。最终回执见 `.local/guardian-assistant-workspace-20260922/deploy/production-browser.json`。

生产页面只读检查、模拟接口与离线候选结果分别记录，没有把它们冒充真实模型调用或实体手机验收。
