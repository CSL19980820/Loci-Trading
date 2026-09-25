# 助手、交易员对话与侧栏组件优化

本轮对应用户要求：把对话里的 shadcn-vue 组件用到位，并修复左侧一级菜单与「盘面」图标重复、层级不清的问题。

## 实际调整

| 范围 | 调整结果 | 组件落点 |
|---|---|---|
| 左侧导航 | 市场使用地球图标、我的使用公文包，盘面保留仪表盘；一级分组、二级缩进和轨道、选中细边框与图标底明确区分；折叠后图标居中并保留组间分隔 | SidebarGroupLabel、SidebarMenuButton、Collapsible |
| 侧栏品牌 | 修复未定义的 `--primary-foreground`，使用项目的 `--on-primary`；日夜均为白色标志 | 现有主题 token |
| 主助手消息操作 | 复制、重跑统一放入 MessageFooter，使用有中文可访问名称和 Tooltip 的紧凑图标按钮；触摸目标 36px | MessageFooter、Button、Tooltip |
| 思考和工具回执 | CollapsibleTrigger 通过 as-child 组合 Button；完成且收起时弱化外框，展开/运行/错误仍有状态区分；保留键盘展开与自动错误展开 | Collapsible、Button、Spinner |
| 主助手待发送图片 | 使用完整附件分组、媒体、动作结构；修正尺寸变体导致图片只占 28px 的问题，64px 卡片内图片为 56px；移除动作可用 | AttachmentGroup、Attachment、AttachmentMedia、AttachmentActions、AttachmentAction |
| 附件原语 | AttachmentAction 转发已声明的 class/as/asChild，避免调用端样式和组合属性失效 | 现有 shadcn 源码原语 |
| 交易员咨询 | 用户气泡、交易员身份与全宽回答统一使用消息组件；输入区整合为输入组，空态/错误使用对应原语；保护模型缺失、加载中、输入法等状态下的快捷键提交 | Message、MessageHeader、MessageContent、Bubble、Avatar、MessageScroller、InputGroupTextarea、Empty、Alert |
| 多题确认 | 保留同时查看所有问题与一次提交；增加已答数量、必答提示、字段级错误关联、首个缺项焦点；忽略长按/输入法数字键，填写自由回答后清除旧错误 | FieldSet、FieldLegend、FieldLabel、FieldError、RadioGroup |

没有为了组件数量引入不匹配的交互。官方 [Questionnaire](https://shadcn-vue.com/docs/components/questionnaire) 提供逐题导航；当前业务要求全部问题同时可见、统一确认，继续使用 Field/RadioGroup 更适合。单题点击即提交、多题答复格式及宿主 dispatching 防重复机制保持。

## 本地验证与边界

- 前端全量 18 个文件、142 项测试通过；确认卡最后一次清错调整后定向 5/5 通过；最终生产构建包含类型检查。
- 主助手：4 组桌面/移动、日夜组合验证消息页脚、键盘折叠、无嵌套按钮、4 张图片显示与移除；6 组富内容历史/图表/上滑保持回归通过。
- 交易员：7/7 场景通过，覆盖日夜与 1280/390、长文本、失败重试保持 request_id/背景、流式上滑不抢位置、完成态 Markdown 和无模型/IME 保护。
- 侧栏：日夜展开 224px/折叠 60px，8 个入口可达、唯一选中态、折叠记忆、路由切换、390 移动入口通过；品牌对比修正后复核通过。
- 多题确认：1280/390 实际浏览器验证缺项焦点、数字键、自由文本、准确答复格式及无横向溢出。
- 既有助手面板/研究/确认/标签/工坊组合回归 5/5 通过。
- 已查看主助手移动图、咨询移动夜间图、确认移动图、侧栏日夜展开/折叠截图。浏览器夹具使用模拟 API，未调用真实模型、未写业务数据；不能替代生产验收或实体手机验收。

## 证据

- `.local/assistant-nav-refinement-20260922/assistant-composition-results.json` 与截图。
- `.local/assistant-visual-fix-20260922/rich-results.json`。
- `.local/sidebar-20260922-1790088506570/results.json` 与截图。
- `.local/shadcn-foundation-20260922/consult-results.json` 与四组截图。
- `.local/assistant-questionnaire-20260922/receipt.json` 与截图。

## 发布与恢复

- 已部署：`ui-20260922-225007`，2026-09-22 22:52（Asia/Shanghai）。
- 镜像：`sha256:b1859c00fe2cb57ea57fde5c77f2148428db72fa9940f502b608ce251b73dca9`。
- 使用仓库 `deploy.ps1 -FrontendOnly -PrepareOnly` 准备并校验精确候选，10 项隔离接口/恢复检查通过，候选容器已清理；再使用 `server-frontend-deploy.sh ... activate` 切换。
- 当前容器 healthy，276 个前端文件校验一致，容器直连及 nginx 首页均匹配；发布前后后端内容 SHA256 均为 `289ceb5530912bb8a953bd348c1df67cfa871ab159cb61758b8e9d955d1c1b72`，backend_patch 为空。
- 公网首页及 273 个静态资源共 274 项哈希匹配；health/auth options 为 200，未登录管理接口为 401，缺失静态资源为 404 且 no-store。
- 切换后的日志检查：431 行中 ERROR/Traceback 为 0。
- 原生产镜像：`sha256:e73a972ba9d9910c2300252ac9e35aee8f7e32ba4406b9ac4abc63437b3d32ce`。
- 回滚镜像：`loci-qianlong:before-ui-20260922-225007`，另保留 `loci-rollback:navigation-20260922-225007`。
- 回滚备份：`/srv/qianlong-loci/backups/navigation-ui-20260922-225007`；4 个 SQLite 一致性备份 quick_check 均为 ok，环境与编排原件保留。
- 未提交或推送 Git。临时备份执行脚本和上传压缩包已删除；验证回执、可复用测试与回滚材料保留。

## 已登录生产浏览器验收

- 侧栏日/夜展开与折叠已目视：224px/60px、唯一 active，市场 Globe2 与盘面 Gauge 不同，品牌标志白色。
- 主助手恢复现有真实历史：2 个 Message、2 个 MessageFooter、1 个 InputGroup 与 3 个 Collapsible；工具及图表默认收起，工具展开后 aria-expanded=true，再恢复收起；输入为空、无横向溢出。
- 交易员读取现有两轮历史：4 个 Message、4 个 Bubble、1 个 InputGroup；桌面答案 960px 与父栏同宽，390 手机模拟视口答案 328px、输入 342px，无横向溢出，夜间真实页面已目视。
- 未发送模型消息、创建/删除话题或保存业务数据。手机结果为 Chrome 视口模拟，不等于实体手机检查。
- 浏览器 console 警告/错误为 0；检查完成后已恢复原日间主题、侧栏展开和视口，关闭临时标签页。临时 Vite 已停止，5174 无监听。被最终截图取代的早期侧栏截图目录已删除，最终证据保留。

机器回执目录：`.local/assistant-nav-refinement-20260922/`，包括 `DEPLOYMENT.json`、`PUBLIC_VERIFICATION.json`、`runtime-check.json`、候选及备份回执。生产浏览器回执为 `production-browser.json`。
