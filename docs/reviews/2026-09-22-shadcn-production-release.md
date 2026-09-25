# shadcn 基础能力优化生产发布回执

发布日期：2026-09-22。用户授权：部署本次审查后完成的前后端改动。

## 发布版本与范围

- 站点：<https://qianlong.chenkit.cloud/>
- 版本：`2.0.0-20260922-200909`
- 镜像：`loci-qianlong:2.0.0-20260922-200909`
- 镜像 ID：`sha256:eb50e6b911acc227ed299f654c9b2481abefe9359b0272de095eb873736c3df0`
- 生产容器启动：`2026-09-22T12:13:52.783212544Z`，北京时间 20:13:52。
- 源码基线：`2cabf932adb90c89f898eadc116b796a2dfee79c` 加已验证工作区改动；本次未创建 commit 或执行 push。

打包前实际读取生产容器代码指纹：线上原有 Guardian/MCP 改动与工作区一致，后端仅有本次审查涉及的 13 个文件不同。保留现有生产修复，发布新的前端构建与这 13 个后端文件；本地辅助文件、测试夹具、凭据和数据库未进入镜像。

发布沿用 `deploy/deploy.ps1` 的打包内容、Dockerfile 和 `deploy/server/server-deploy.sh`。为在切换前验收候选，本轮将打包/上传与激活分开执行；激活前再次确认生产仍为所核对的旧镜像。前端复用本轮最后一次 typecheck/生产构建成功的产物。

## 实际验证

| 层次 | 结果 |
|---|---|
| 开发验收 | 前端 133 项、后端隔离 163 项、前端类型检查/构建、716 模块导入通过；详见实施回执 |
| 精确候选镜像 | 10 项通过；真实 HTTP 登录、角色分页/total、用量缓存、技能事件 cursor，以及主/子租户研究任务恢复、JSON 保留/回退、有界 executor |
| 候选隔离 | `/app/data` 仅 tmpfs，无生产数据或生产环境文件挂载；768 MiB/单 CPU，scheduler 禁用；临时容器和认证数据已删除 |
| 生产容器 | healthy，非 root UID 10001；运行时 1,030 个源码、模板、前端文件与发布包逐项 SHA-256 一致 |
| 生产配置 | 除发布镜像/端口字段外，环境与切换前备份一致 |
| 实际迁移 | 3 条既有 failed 研究任务完整迁入 ops.db；记录内容与原 JSON 相同；原 JSON 字节不变；迁移标记存在 |
| 公网 | health/auth options 为 200、匿名管理接口 401；首页加 270 个 `/assets/*` 资源共 271 项内容指纹一致；不存在的静态资源为 404 且 no-store |
| 已登录真实浏览器 | Chrome 1440/390 双视口：实际盘面、Quant 研究分区、Admin 角色筛选、助手、个股档案通过；admin/visitor 筛选分别返回 1/2 条实际记录；手机助手 390×844 全屏、关闭重开保留草稿，测试草稿已清空；档案子弹窗退出后 Escape 返回盘面；console warn/error 为 0，无文档横溢 |
| 运行日志 | 新容器检查窗口内 ERROR/CRITICAL/Traceback 为 0，重启计数 0 |

真实已登录浏览器的最终结果另存同一证据目录的 `BROWSER_VERIFICATION.json`。上线前的 32 场景模拟接口验收与上线后的真实浏览器验收分别记录，不混用证据。

## 回滚与数据保护

旧镜像：`loci-qianlong:2.0.0-20260922-182052`，固定回滚标签为 `loci-rollback:shadcn-20260922-200909`。

切换前备份：`/srv/qianlong-loci/backups/shadcn-2.0.0-20260922-200909/`。其中 ops.db、palace.db、identity.db、community.db 均使用 SQLite backup API 生成一致性副本，quick_check 均为 ok；保留环境、compose、JSON 配置与原研究任务文件。未复制开发机业务数据库到生产。

研究迁移为新增表，旧 JSON 保留。如果上线后产生新研究任务，回滚旧镜像前应先停止接收/执行新研究任务，并从新表导出最新任务状态；不得直接把部署前旧 JSON 当作最新任务状态覆盖回去。本次未触发模型调用、策略运行或交易。

## 证据与清理

本地证据目录：`.local/shadcn-deploy-20260922/`。核心文件为 `release-receipt.json`、`DEPLOYMENT.json`、`ROLLBACK.json`、`PUBLIC_VERIFICATION.json`、`candidate-receipt-2.0.0-20260922-200909.json`、`BROWSER_VERIFICATION.json`。正式机器回执同步到服务器该版本的 releases 目录。

候选容器和临时数据已清理。删除本次 `prepare-release.ps1`、`backup.py` 和已上传 tar.gz 时，自动审批审查拒绝执行，理由为 `blocked by policy`；未绕过，以上三项仍在本地。发布 staging 保留作版本追溯材料，不作为当前源码入口。回滚镜像、数据库备份和正式回执按交付证据保留。
