# UZI-Skill 固定版本一手资料审计

> 审计日期：2026-08-04
>
> 对象：[`wbh604/UZI-Skill`](https://github.com/wbh604/UZI-Skill)
>
> 固定 commit：[`fce996c33e70eddce8e375f53cd252b549eb3d7c`](https://github.com/wbh604/UZI-Skill/commit/fce996c33e70eddce8e375f53cd252b549eb3d7c)
>
> commit 时间：2026-07-07 16:47:43 +0800；提交信息：`fix flow and data contract regressions (#85)`

本文是只读研究稿。资料来自固定 commit 的 README、源码、测试/发布说明和依赖的官方文档；没有安装 UZI 依赖，没有运行真实行情采集，没有写入 UZI 的 `.cache`、报告或本仓数据库。因此，文中把“仓库声明”和“本次源码核验”明确分开。

## 结论

UZI-Skill 更适合作为“个股研究工作流插件”参考，而不是可以直接替换本仓策略/回测链的选股引擎。它的工程价值集中在：

1. 把采集、维度评分、Agent 定性分析、合成和报告拆成可恢复阶段；
2. 用 `DimResult` 记录 `quality/source/data_gaps/error`，同时兼容旧 JSON；
3. 在 HTML 组装前运行 self-review，并区分 `critical` 与 `warning`。

本次审计同时确认了四个不能忽略的边界：版本标识未完全同步；来源注册表的 `health` 是静态提示而非本次命中证明；缓存可恢复不等于 point-in-time 历史快照；远程分享、登录 Cookie、安装脚本和 review bypass 都需要额外运维约束。

本仓当前 `src/research` 已经沿着更保守的方向实现了输入快照、`market_revision`、证据 hash、`missing` 语义和只读 ToolBus。建议继续吸收契约和门禁思想，不复制 UZI 的评委分、代理估值或默认外部抓取。

## 1. 版本身份与声明口径

### 1.1 固定版本事实

| 项目 | 固定 commit 中的事实 | 证据 |
|---|---|---|
| 当前引用 | `main`/`origin/main` 指向 `fce996c...`，无对应 `v3.9.2` tag | [commit](https://github.com/wbh604/UZI-Skill/commit/fce996c33e70eddce8e375f53cd252b549eb3d7c)、[tags](https://github.com/wbh604/UZI-Skill/tags) |
| 文档/manifest 版本 | README、`.claude-plugin/plugin.json`、`.cursor-plugin/plugin.json`、`package.json`、`gemini-extension.json` 写 `3.9.2` | [README.md#L10-L15](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/README.md#L10-L15)、[package.json#L1-L5](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/package.json#L1-L5) |
| 根 Skill / bump 配置 | 根 `SKILL.md` 和 `.version-bump.json` 写 `3.9.1` | [SKILL.md#L1-L8](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/SKILL.md#L1-L8)、[.version-bump.json#L1-L8](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/.version-bump.json#L1-L8) |
| 发布说明 | `RELEASE-NOTES.md` 顶部仍是 `v3.9.1`；README 将同一日期 hotfix 写成 `v3.9.2` | [RELEASE-NOTES.md#L1-L8](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/RELEASE-NOTES.md#L1-L8)、[README.md#L786-L787](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/README.md#L786-L787) |

`run.py` 的 `_get_version()` 从 `.claude-plugin/plugin.json` 读取版本，所以运行时 banner 可能显示 `3.9.2`，而根 Skill 的 agent 规则仍显示 `3.9.1`。这不是投资数据问题，但会影响报告、问题单和安装结果的可追溯性。若本仓借鉴其版本同步，应把 commit、tag、manifest、Skill frontmatter 和 release notes 作为同一门禁检查。

### 1.2 “22 维、66 评委、22 方法”应视为项目自述

README 的徽章和简介宣称 `22` 个维度、`66` 位评委和 `22` 种机构方法；pipeline 注释也写“22 BaseFetcher adapter”。固定 commit 的主 registry 按 `dim_key` 去重后是 21 个，`fetch_similar_stocks.py` 是额外流程而不是 registry 维度。这里不把数量差异解释成代码缺陷，但在比较系统能力时应记录统计口径，而不是用 badge 数量证明数据覆盖或质量。

证据：[README.md#L10-L15](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/README.md#L10-L15)、[pipeline/run.py#L20-L28](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/run.py#L20-L28)、[fetchers/registry.py](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/fetchers/registry.py)。

## 2. 运行模型和阶段产物

### 2.1 默认路径

固定版本的默认链路可以概括为：

```text
run.py
  -> pipeline.collect (wave 1 / wave 2 / wave 3)
  -> .cache/<ticker>/raw_data.json
  -> pipeline.score_from_cache
  -> pipeline.synthesize_and_render
  -> HTML / PNG / 摘要
          |
          +-- UZI_LEGACY=1 或 pipeline 异常 --> legacy stage1/stage2
```

`run.py` 明确将 pipeline 作为默认路径，`UZI_LEGACY=1` 强制旧路径，pipeline 异常捕获后回退 legacy。`pipeline/run.py` 读取已有 `raw_data.json` 做 resume；`pipeline/collect.py` 先跑 `0_basic`，再以 `max_workers=6` 并发非依赖 fetcher，最后串行跑依赖 `industry` 的四个维度。并发 future 的单项结果等待上限为 120 秒，失败维度写成 `error`，不会直接把整条采集当作成功。

证据：[run.py#L593-L605](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/run.py#L593-L605)、[pipeline/run.py#L19-L63](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/run.py#L19-L63)、[pipeline/collect.py#L31-L140](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/collect.py#L31-L140)。

### 2.2 产物和 Agent 闭环

仓库的数据契约列出 `.cache/{ticker}/raw_data.json`、`dimensions.json`、`panel.json`、`synthesis.json`，以及 Agent 介入时的 `agent_analysis.json`；报告目录还会产生 standalone HTML、分享图、战报和摘要。深度流程要求 Agent 读取 `panel.json`，覆盖评委判断，写 `agent_analysis.json`，再让 stage2 合并。快速 CLI 可以跳过 Agent，文档明确说此时评委判断只是规则引擎机械输出。

这意味着“报告生成成功”与“完成了真实 Agent 研究”是两个不同状态。下游若消费报告，至少要保留 `agent_reviewed`、缓存阶段和质量状态，而不能只看 HTML 文件是否存在。

证据：[data-contracts.md#L1-L5](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/assets/data-contracts.md#L1-L5)、[data-contracts.md#L281-L292](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/assets/data-contracts.md#L281-L292)、[commands/analyze-stock.md#L44-L118](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/commands/analyze-stock.md#L44-L118)、[deep-analysis/SKILL.md#L478-L573](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/SKILL.md#L478-L573)。

### 2.3 Resume 的边界

`_is_resume_valid()` 主要依据缓存是否存在、`quality` 是否为 `missing/error`、legacy `fallback` 是否为 `True` 以及 `data` 是否非空来决定复用。这个机制适合断点续跑，但固定版本的阶段缓存没有统一的输入 hash、行情 revision、来源 payload hash 或不可变 point-in-time 原始快照。因此，旧 cache 可复用不等于可以重放某个历史时点的研究结论。

证据：[pipeline/collect.py#L157-L177](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/collect.py#L157-L177)、[pipeline/run.py#L94-L119](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/run.py#L94-L119)、[data-contracts.md#L5-L20](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/assets/data-contracts.md#L5-L20)。

## 3. 数据契约、来源和质量门禁

### 3.1 `DimResult` 是值得复用的最小结构

`pipeline/schema.py` 定义四种质量状态：

- `full`：required 字段有实测值；
- `partial`：部分 optional 或 required 字段缺失；
- `missing`：运行完成但没有数据；
- `error`：异常或网络失败。

结果还保留 `source`、`error`、`data_gaps`、`cached`、`latency_ms`。`to_dict()` 把新增元数据放进 `_pipeline`，保留 legacy 顶层 `data/source/fallback`，从而让旧 renderer 可以继续读取。这个兼容层适合迁移期，但也意味着消费者必须主动读取 `_pipeline.quality`，不能只根据 `fallback` 或空值猜质量。

证据：[pipeline/schema.py#L16-L112](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/pipeline/schema.py#L16-L112)。

### 3.2 来源注册表不是实际命中回执

`data_source_registry.py` 自己声明是纯配置、无 I/O；它维护 URL、市场、维度、Tier、访问方式和静态 `health`，并按 `known_good` 等标签排序。文件同时明确写出“registry is a hint, not truth”，实际 fetcher 返回的 `source` 才是事实。

因此，`known_good` 只能帮助选择候选，不足以证明：本次请求成功、字段口径正确、数据可回放、接口授权允许使用，或结果在研究截止日已经公开。本仓若实现来源目录，应额外保存本次 `source_attempts`、最终命中、字段检查和 payload hash。

证据：[data_source_registry.py#L1-L35](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/data_source_registry.py#L1-L35)、[data_source_registry.py#L643-L684](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/data_source_registry.py#L643-L684)。

### 3.3 self-review 的真实语义

`self_review.py` 当前 `CHECKS` 列表注册 16 个检查（README badge/旧说明仍出现 13 条的口径），输出 `critical_count`、`warning_count`、`passed`，并写入 `.cache/{ticker}/_review_issues.json`。`assemble_report.py` 在 HTML 组装前运行它：有 critical 时抛出 `RuntimeError`，warning 继续生成并留下记录。另一方面，CLI 入口设置 `UZI_CLI_ONLY=1`，部分 coverage/Agent 缺失问题在 CLI/lite 场景降级为 warning，允许报告继续生成。

此外，`assemble_report.py` 支持 `UZI_SKIP_REVIEW=1` 完全跳过 review。Skill 文档警告这只应是开发调试用途，但它仍是一个可用的旁路开关；生产封装不能把“调用了 assemble”当作 review 已通过。

证据：[self_review.py#L251-L318](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/self_review.py#L251-L318)、[self_review.py#L603-L665](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/self_review.py#L603-L665)、[assemble_report.py#L340-L370](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/assemble_report.py#L340-L370)、[deep-analysis/SKILL.md#L355-L390](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/SKILL.md#L355-L390)。

## 4. 运行与安全边界

以下不是“代码一定存在漏洞”的结论，而是部署和集成时必须显式建模的边界。

| 边界 | 源码事实 | 影响与建议 |
|---|---|---|
| 本地报告服务 | `http.server` 绑定 `127.0.0.1`；`--remote` 再用 Cloudflare quick tunnel 转发，输出 `trycloudflare.com` bearer URL，未见应用层认证 | 链接持有者可读取该报告目录；只分享给可信对象，报告不得放入敏感信息。见 [run.py#L170-L249](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/run.py#L170-L249) 与 [Python http.server](https://docs.python.org/3/library/http.server.html)、[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)。 |
| 自动安装 cloudflared | Linux `--install-cloudflared` 路径下载 latest 二进制、`chmod` 后 `sudo mv` 到 `/usr/local/bin`；默认缺失时只提示，不自动安装 | 这是用户显式开启的供应链和提权边界。应固定版本、校验 checksum，并让运维预装，不把它放进无人值守默认流程。见 [run.py#L190-L218](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/run.py#L190-L218)。 |
| 雪球登录态 | opt-in 后把 Playwright context cookies 以 JSON 明文写到 `~/.uzi-skill/playwright-xueqiu/cookies.json`，并复用持久化浏览器 profile | 文件权限、备份和恶意读取会影响账户会话；应使用专用账号、最小权限目录和退出/轮换流程。见 [xueqiu_browser.py#L29-L59](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/xueqiu_browser.py#L29-L59)、[xueqiu_browser.py#L78-L119](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/xueqiu_browser.py#L78-L119)。 |
| `--output-dir` | 复制报告时，若目标子目录已存在会先 `shutil.rmtree(target)` 再 `copytree` | 目标路径必须由调用方控制并经过白名单校验；不要把用户任意路径直接传入。见 [run.py#L316-L358](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/run.py#L316-L358)。 |
| review 旁路 | `UZI_SKIP_REVIEW=1` 跳过 critical gate | 生产包装应忽略或拒绝该环境变量，并在 artifact 中记录 gate 是否实际运行。见 [assemble_report.py#L348-L365](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/assemble_report.py#L348-L365)。 |
| 一键安装 | `setup.sh`/`install-hermes.sh` 支持 `curl | bash`、git clone/pull、删除旧 skill symlink/目录和 `pip install -r requirements.txt` | 这是可执行代码和依赖供应链，不应视为无风险安装；部署前应 pin commit、审阅脚本、隔离虚拟环境。见 [setup.sh#L1-L60](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/setup.sh#L1-L60)、[install-hermes.sh#L1-L95](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/install-hermes.sh#L1-L95)。 |
| 外部 API key | `.env` loader 读取任意 `KEY=VALUE` 到进程环境；`MX_APIKEY` 会让客户端向妙想 API 发送查询/新闻请求 | 不把真实 key 写入仓库、提示词或报告；审计日志只记录 source id，不记录 header。见 [run.py#L56-L81](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/run.py#L56-L81)、[mx_api.py#L1-L21](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/mx_api.py#L1-L21)。 |
| 代理凭据缓存 | `_detect_proxy()` 将 `HTTPS_PROXY`/`HTTP_PROXY`/`ALL_PROXY` 的完整值保存到 `NetworkProfile.proxy_url`，`run_preflight()` 再把 `asdict()` 写入 `.cache/_global/network_profile.json` | 含用户名/密码的代理 URL 可能被本地 Agent、报告流程或备份读取；只记录 `has_proxy`、scheme、host、port，并清理旧 cache。见 [network_preflight.py#L73-L99](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/network_preflight.py#L73-L99)、[network_preflight.py#L125-L132](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/network_preflight.py#L125-L132)、[network_preflight.py#L291-L368](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/network_preflight.py#L291-L368)。 |
| 主报告 HTML 注入面 | `_safe()` 只做空值兜底，不做 HTML escaping；主模板替换、`panel_cards.py` 的 name/verdict/reasoning/pass/fail/risks，以及 `special_cards.py` 的 URL/name/reason 均有直接字符串插值；raw JSON 直接放入 `<pre>` | 外部行情、搜索片段或 Agent 字段若含 HTML/属性/`javascript:`，可能形成生成报告中的存储型 HTML/script 注入。仅本地打开时主要是 self-XSS；`--remote` 会扩大阅读者范围。应按上下文分别转义文本、属性和 URL，并覆盖主 assemble/panel/special 渲染测试。见 [assemble_report.py#L23-L25](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/assemble_report.py#L23-L25)、[assemble_report.py#L275-L300](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/assemble_report.py#L275-L300)、[assemble_report.py#L403-L480](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/assemble_report.py#L403-L480)、[panel_cards.py#L33-L117](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/report/panel_cards.py#L33-L117)、[special_cards.py#L73-L85](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/lib/report/special_cards.py#L73-L85)。 |

这项 HTML 风险是源码审计结论，不把单个局部测试当作全链路安全证明。固定 commit 的 `test_v3_7_2_html_escape.py` 主要覆盖 `versus/portfolio` 的转义，`test_v3_9_1_toc_collapse.py` 检查的是 TOC 折叠脚本不使用 `innerHTML`；两者都不能覆盖主报告的模板替换、评委卡片和相似股票链接。若报告通过 `--remote` 分享，应按 P1 处理；仅本地、可信输入场景至少按 P2 修复并加入回归测试。

证据：[test_v3_7_2_html_escape.py](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/tests/test_v3_7_2_html_escape.py)、[test_v3_9_1_toc_collapse.py#L71-L75](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/skills/deep-analysis/scripts/tests/test_v3_9_1_toc_collapse.py#L71-L75)。

## 5. 依赖与官方文档核对

固定 commit 的 `requirements.txt` 只给出最低版本，没有 lockfile 或 hash；同一源码在不同日期安装可能得到不同的 AkShare、yfinance、Playwright 或搜索库行为。本次没有安装这些包，因此不报告“可运行”或“测试通过”。

| 依赖 | 在 UZI 中的用途 | 官方文档 |
|---|---|---|
| `akshare` | A 股/港股数据适配和 fallback | [AkShare 文档](https://akshare.akfamily.xyz/) |
| `yfinance` | 港美股行情/财务 fallback | [yfinance 文档](https://ranaroussi.github.io/yfinance/) |
| `baostock` | A 股 K 线 fallback | [BaoStock 文档](http://baostock.com/baostock/index.php) |
| `pandas` | 表格和指标计算 | [pandas 文档](https://pandas.pydata.org/docs/) |
| `requests` | HTTP 采集 | [Requests 文档](https://requests.readthedocs.io/en/latest/) |
| `ddgs` | 搜索片段和定性维度兜底 | [ddgs 源码/说明](https://github.com/deedy5/ddgs) |
| `playwright` | JS 页面、截图和可选登录态 | [Playwright Python](https://playwright.dev/python/docs/intro) |
| `http.server` | 本地报告服务（Python 标准库） | [Python 文档](https://docs.python.org/3/library/http.server.html) |
| `cloudflared` | `--remote` 临时公网隧道（外部二进制） | [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) |

依赖清单：[requirements.txt](https://github.com/wbh604/UZI-Skill/blob/fce996c33e70eddce8e375f53cd252b549eb3d7c/requirements.txt)。官方文档在这里仅用于确认组件职责和安装边界，不证明 UZI 对各服务的授权、字段口径或稳定性。

## 6. 与本仓 `src/research` 的对照

当前工作树中的研究上下文已经实现了 UZI 适合借鉴的更小闭环：

| UZI 机制 | 本仓当前实现 | 结论 |
|---|---|---|
| `DimResult` 的质量/缺口/来源字段 | `src/research/domain/contract.py` 的 `DimensionResult`、`EvidenceRef`、`SourceAttempt`、`ReviewIssue` | 可继续沿用，但把实际命中和证据 hash 作为硬契约 |
| `.cache` resume | `application/snapshot.py` + `application/run.py` 保存输入 JSON、input hash 和 `market_revision`，版本变化标 `stale` | 本仓的历史安全语义更明确，不应退回只看文件存在 |
| 多来源目录 | `application/catalog.py` 返回候选来源和 guardrails；profile 当前只读本地 `MarketStore` | 外部来源先做 probe/命中回执，再开放给研究工具 |
| self-review | `domain/review.py` 生成质量快照和 issue | critical 只阻止“已核验”标记，不阻止查看带缺口的中间结果 |
| Agent/CLI 消费 | `research_catalog`、`research_profile` 是只读投影，限制代码、预算和 `as_of` | 不允许 AI 写 artifact、写库、生成生产信号 |

对应实现：[研究契约](../../src/research/domain/contract.py)、[输入快照](../../src/research/application/snapshot.py)、[研究运行](../../src/research/application/run.py)、[只读工具](../../src/ai/application/system_toolbus_research.py)、[研究边界说明](../../src/research/README.md)。

## 7. 建议采用和明确拒绝

### 建议采用

1. 研究维度统一输出 `quality/source/data_gaps/error/retrieved_at/as_of`，并保存实际来源尝试与 payload hash。
2. 阶段产物记录契约版本、输入 hash、依赖阶段、输出 hash、耗时和错误；只在输入仍有效时 resume。
3. 终稿前做可注册 review rule；critical 阻止“已验证结论”，warning 必须带缺口展示。
4. 把 Agent 输出作为引用证据上的解释层，保留 `agent_reviewed` 和质量降级标志。

### 明确拒绝直接复制

- 评委数量、角色分数或综合分直接进入本仓策略默认；它们没有本仓定义的入场、退出、成本、容量和组合回撤。
- 代理现金流、目标价和共识值兜底进入生产数字；缺少真实来源时应保持 `missing`。
- 把 registry 的 `known_good`、README 的覆盖数量或 release notes 的测试数字当作当前数据质量/收益证据。
- 通过自动安装、远程 bearer URL 或明文 Cookie 扩大本仓默认权限面。

## 8. 未确认事项和复现边界

以下结论本次没有宣称：

1. README/RELEASE-NOTES 中的 `632 tests`、`649 passed` 是否在固定 commit 的干净环境重新跑通；
2. AkShare、雪球、东财、搜索和官方披露接口在当前网络、当前授权和指定历史截止日下是否能返回完整字段；
3. UZI 的静态评分、DCF 或 Agent 结论是否具有可重复的历史 alpha、预测准确率或真实投资效果；
4. 各第三方站点是否允许当前抓取方式、缓存和报告再分发；
5. `--remote`、Xueqiu 登录和安装脚本在目标部署环境中的权限、审计和清理策略。

因此，本稿只支持“源码结构和边界已核验”的结论，不支持“UZI 已经可作为本仓生产研究/交易来源”的结论。

## 9. 核验记录

- 只读 clone 到临时目录并固定到 `fce996c33e70eddce8e375f53cd252b549eb3d7c`。
- 阅读 README、根 `SKILL.md`、`run.py`、pipeline schema/collector/runner、data source registry、self-review、Agent workflow、报告服务、Xueqiu browser、安装脚本、requirements 和 release notes。
- 对照官方依赖文档入口：AkShare、yfinance、BaoStock、pandas、Requests、ddgs、Playwright Python、Python `http.server`、Cloudflare Tunnel。
- 未运行 UZI CLI、未安装依赖、未触发外部行情请求、未写入真实 `data/` 或数据库。
