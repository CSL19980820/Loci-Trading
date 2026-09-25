# 天才交易员报告：交易手记阅读稿与企微短讯

## 最终交付及并行改动

最终独立预览目录：`.local/guardian-report-redesign-20260918/editorial-preview/`。

- `daily-editorial.html`：日复盘。
- `weekly-editorial.html`：周复盘。
- `wechat-preview.html`：两条短讯，可点击进入对应本地全文。

验收中发现默认 `guardian_report_share.render_report_share` 被另一处并行修改接到 `guardian_report_dashboard`。本轮保留该入口，不覆盖并行代码；独立 `build_previews.py` 直接调用本轮阅读器。原 `.local/guardian-loop-audit-20260918/daily-after.html` 和 `weekly-after.html` 不作为本轮最终验收稿。

本轮没有部署、公开发布报告、实际发送企微、调用模型重写报告或修改账户。不改变 Guardian 的研究、仓位、策略和成交授权。当前阅读稿未重新接管默认报告入口。

## 阅读与视觉

只保留账户结果、持仓与计划、完整复盘三个主入口。首屏呈现真实盈亏、期间收益、成交概况和资金；日复盘为逐股期间盈亏贡献，周复盘为实际收盘净值采样，均不生成虚构盘中行情。

纸色底、深色文字、朱红强调、大数字与细分隔线替代侧栏章节清单、渐变卡片与重复框架。持仓集中成可比较的行；点击展开判断、成本、触发与失效条件。其他关注与已退出持仓集中折叠，完整正文默认收起，保留全部判断、后续安排、研究与验证状态。

采用原生 details 与内部锚点；键盘可操作，点击全文入口由浏览器展开祖先折叠。没有脚本、外部字体或图片请求。共享页面的 CSP、令牌及不可变快照规则未放宽。适配窄屏、深色和减少动态效果偏好。

参考 Stripe 官方年度更新页的结果前置与完整内容入口层级，不照搬渐变和营销卡片。参考地址：`https://stripe.com/annual-updates/2024`。浏览器截图保存在验证目录 `stripe-reference.jpg`。Wealthsimple 访问遇到站点验证，未宣称完成其视觉检查。

## 企微短讯

发送端 `DIGEST_MAX_BYTES=560` 仅约束通知展示，不限制模型研究、决策或存储内容。正文为盈亏、仓位／持仓、单句摘要或真实成交概况，再加全文入口。

独立 notification_summary 只有单行且适合短讯时整句使用，否则从实际成交流水生成短讯。绝不退回完整 summary、next_steps 或条件计划计数，不截断条件句。历史折算与新增成交分开。超长链接不截断，提供工作台阅读路径。通知格式标记 digest_v2，保持原有去重与重试。

最终离线预演：日短讯 211 UTF-8 字节、144 字符；周短讯 217 字节、146 字符，包含示例分享链接。实际域名和独立摘要会影响大小，发送端仍核验上限。这不是实际送达回执。

## 实现

新增 `guardian_report_reader.py`、`guardian_report_reader_style.py`；共享 report_sections 仅作为可读内容源。完整段落和交易条件不删减，未知的新类型章节也保留。研究发现仅在完整验证段落包含同文时去重，验证状态不会消失。仅转义并呈现可读字段，不向页面序列化原始工具、配置或完整账户 JSON。

`build_previews.py` 直接使用阅读器生成上述独立文件，避免默认入口并行变化导致验收稿被替换。通用 render_shared_document 保留供其他 Agent 使用。

## 验证与边界

目标报告、通知、分享与其他 Agent 兼容回归：67 通过、1 跳过。跳过项需要 Linux root 的文件权限验证，本机 Windows。相关 Ruff F 检查通过。

最终独立日／周稿在 1440、820、390、320 像素宽度及深色主题完成 10 组 Chromium 检查：没有横向溢出、重复 ID、失效锚点或页面错误；验证默认折叠、键盘展开、其他计划、直接进入全文、收起和返回顶部。外部 HTTP 请求为零。不是企微客户端真机验证。

扩大到所有 guardian 测试时有周复盘提示词文案断言失败。独立改前副本仍复现 `test_report_contract_has_no_presentation_or_learning_quota[weekly]`，缺失测试期待的 CUSTOM 继承文案；其他五个文案断言在副本复查时通过。该路径未因本次设计修改，不宣称全量全绿。

新增超长摘要测试最初因 pytest 将整个参数写入 Windows 环境变量导致设置错误，改为显式短测试 ID 后通过；未缩短测试数据或业务输出。

证据目录：`.local/guardian-report-redesign-20260918/`。主要为 `target-final.log`、`visual-final.log`、`visual-results.json`、`ruff-final.log`、`preview-results.json`、`prompt-baseline.log` 和各尺寸截图。默认入口的旧失败日志保留；最终通过记录明确对应独立 editorial-preview。
