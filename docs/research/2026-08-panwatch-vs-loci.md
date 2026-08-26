# PanWatch vs Loci 对照研究

> 审计日期：2026-08-06  
> 外部对象：`[TNT-Likely/PanWatch](https://github.com/TNT-Likely/PanWatch)`  
> 固定 commit：`[c1b064fee9f0cae60731a6e19def2817f06cec09](https://github.com/TNT-Likely/PanWatch/commit/c1b064fee9f0cae60731a6e19def2817f06cec09)`（2026-08-02，`feat(dashboard): 首页视觉改版 + 指数/美股K线数据源修复 + 首屏提速`）  
> 本地镜像：`%TEMP%/PanWatch-research`（`git clone --depth 1`）  
> 本仓对照：当前工作树 `E:\my_space\stock-analyzer`（Loci / stock-analyzer）

本文是只读对比研究：未安装/运行 PanWatch Docker，未改本仓业务代码。外部结论以固定 commit 的源码与 README 为准；README 营销句仅在能被源码路径佐证时采用。本仓侧以 `README.md`、`AGENTS.md`、`docs/architecture/bounded-contexts.md` 及各上下文 `README.md` 为权威。

相关既有调研：[Vibe-Trading 对比](2026-08-vibe-trading-comparison.md)（研究证据链取向；与本文正交）。

---

## 摘要

**Verdict：PanWatch 是「自托管 AI 盯盘 + 多渠道推送 + TradingAgents 深度分析」产品；Loci 是「A 股账本权威 + 行情仓 + 确定性策略/复盘」工作台。二者重叠在「本机持仓/行情/AI/通知」，但数据权威性与 AI 权限模型几乎相反。** 五轮深挖见下文「深度调研五轮」；建议动作表已按否决清单修订。

**是否值得借鉴：值得部分借鉴（通知渠道/价格提醒引擎/月度 AI 成本闸门/`packages/marketdata` 的端口化思路）；不值得整体照抄（TradingAgents 多 Agent 决策、可变持仓快照、Docker+React 技术栈、跨市场实时抓取当权威）。**

---

## PanWatch 是什么

### 定位

自托管 AI 盯盘助手：持仓监控、定时 Agent（盘前/盘中/盘后/新闻）、条件价格提醒、模拟盘、TradingAgents 多 Agent「深度分析」，结论推到 IM。

证据：根 `[README.md](https://github.com/TNT-Likely/PanWatch/blob/c1b064fee9f0cae60731a6e19def2817f06cec09/README.md)` 标题与「核心功能」；`[CLAUDE.md](https://github.com/TNT-Likely/PanWatch/blob/c1b064fee9f0cae60731a6e19def2817f06cec09/CLAUDE.md)`「What is PanWatch」。

### 技术栈


| 层     | 选择                                                 | 证据                                                                                                                        |
| ----- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 后端    | FastAPI + SQLAlchemy + APScheduler + OpenAI SDK    | README「技术栈」；`requirements.txt`                                                                                            |
| 入口    | 单体 `server.py`（约 1572 行）注册 Agent/调度/DB             | `server.py`；`[AGENTS.md](https://github.com/TNT-Likely/PanWatch/blob/c1b064fee9f0cae60731a6e19def2817f06cec09/AGENTS.md)` |
| ORM/库 | 单 SQLite（`DATA_DIR`）                               | `src/web/database.py`、`src/web/models.py`（约 1083 行）                                                                       |
| 行情包   | 仓内 `packages/marketdata`（可插拔 vendor + 主备）          | `packages/marketdata/README.md`；`requirements.txt` `-e ./packages/marketdata`                                             |
| 深度分析  | `tradingagents @ git+...@v0.3.0`（可选重依赖）            | `requirements.txt` L24–33                                                                                                 |
| 前端    | React 18 + Vite + Tailwind + shadcn/Radix；pnpm；PWA | `frontend/package.json`；README                                                                                            |
| 通知    | Apprise + 自研渠道表单（Telegram/企微/钉钉/飞书/Bark/…）         | `src/core/notifier.py` `CHANNEL_TYPES`；`apprise>=1.6.0`                                                                   |


### 核心能力（源码核实）

1. **Agent 注册表**：`premarket_outlook` / `intraday_monitor` / `daily_report` / `news_digest` / `chart_analyst` / `tradingagents`，经 `AGENT_REGISTRY` + `seed_agents()` 落库。
  证据：`server.py` import 与 `AGENT_REGISTRY`；`src/agents/*.py`；`prompts/*.txt`。
2. **持仓 = 可改快照**：`Account` + `Position(cost_price, quantity, invested_amount, trading_style)`，无成交事件账本。
  证据：`src/web/models.py` `Account`/`Position`；`src/agents/base.py` `PositionInfo`。
3. **行情 = 实时抓取 + 内存 TTL**，无本仓式 `quotes_daily` 权威落盘。`marketdata.Engine` 主备链；`TTLCache` 默认秒级。
  证据：`packages/marketdata/src/marketdata/engine.py`；`cache.py`；`models.py` 中无 `quotes_daily` 表。
4. **价格提醒引擎**：条件组 AND/OR、交易时段、冷却、日触发上限、命中落库、按规则选渠道。
  证据：`PriceAlertRule`/`PriceAlertHit`（`models.py` ~L910）；`src/core/price_alert_engine.py`。
5. **通知策略**：安静时段、重试、按 agent 去重 TTL。
  证据：`src/core/notify_policy.py`；`src/core/notify_dedupe.py`。
6. **TradingAgents 适配**：`monkeypatch route_to_vendor`，A 股走 PanWatch 数据；月度美元预算；可选把 BUY 写入模拟盘信号。
  证据：`src/agents/tradingagents/toolkit_adapter.py` 模块 docstring；`cost_tracker.py`；`agent.py` `emit_paper_trading_signal`。
7. **模拟盘**：信号驱动建仓/平仓，A 股一手与成本模型；非实盘账本。
  证据：`src/core/paper_trading_engine.py`；`PaperTrading*` models。
8. **回测**：轻量事件内核（次日开盘入场、涨跌停未建模 TODO）。
  证据：`src/core/backtest/engine.py` docstring L1–14。

### 部署形态

- **主推**：Docker Hub `sunxiao0721/panwatch`，卷挂 `/app/data`，端口 8000；首次可设 `AUTH_*`。  
证据：README「快速开始」；`Dockerfile` 多阶段（Node 构建前端 + Python 3.11，含 Playwright/中文字体/git 拉 TradingAgents）。
- **开发**：`make dev-api` / `make dev-web`（前端 :5183）。  
证据：README；`AGENTS.md`。
- **VERSION 文件内容为 `dev`**（本 clone）；镜像 tag 由 CI 发布流程管理。

---

## Loci 是什么

### 定位

单机 A 股工作台：**账本 + 行情仓 + 策略/复盘/运维/AI**。数字由量化引擎产出；AI 只解释、提问、结构化录入。

证据：根 `[README.md](../../README.md)`；`[AGENTS.md](../../AGENTS.md)` §1；`[docs/architecture/bounded-contexts.md](../architecture/bounded-contexts.md)`。

### 技术栈


| 层   | 选择                                                          | 证据                                                   |
| --- | ----------------------------------------------------------- | ---------------------------------------------------- |
| 后端  | FastAPI 模块化单体；DDD 四层；无跨库 FK                                 | `src/AGENTS.md`；bounded-contexts                     |
| 库   | `palace.db` / `market.db`(+`market_hot.db`) / `ops.db` 物理隔离 | bounded-contexts 表；各域 README                         |
| 前端  | Vue 3.5 + Element Plus + Pinia + bun                        | `frontend/AGENTS.md`；`frontend/package.json`         |
| 桌面  | PyInstaller onedir `Loci.exe` + 可选加密分享包                     | `[docs/portable-desktop.md](../portable-desktop.md)` |
| AI  | toolbus + HITL + 月度 Token 硬顶；禁止造权威数字                        | `src/ai/README.md`                                   |


### 核心能力（与本文相关的）

- **Ledger**：成交事件驱动现金/持仓投影；候选/预案/复盘记录。  
证据：`src/ledger/README.md`。
- **Market**：日 K + 复权因子落盘、多 adapter 协作合并、来源回执、热读库。  
证据：`src/market/README.md`。
- **Strategy/Backtest/Review**：声明 `entry_timing` 的战法选股、成交/Horizon 回测、资金曲线与候选 T+N；AI 不得替代出数。  
证据：`src/strategy|backtest|review/README.md`。
- **Ops**：Job 调度、企微 text 推送、选股模板与防连推；触价 `notify` 绑预案。  
证据：`src/ops/README.md`；`src/review/application/alerts.py`。
- **AI**：受控工具面、ExecutionGrant、SSE 富状态；默认月 Token 预算 1e6。  
证据：`src/ai/README.md`；`assistant_manager.py` `DEFAULT_MONTHLY_TOKEN_BUDGET`。

---

## 对照表


| 维度        | PanWatch（c1b064f）                                     | Loci（本仓）                                                                   |
| --------- | ----------------------------------------------------- | -------------------------------------------------------------------------- |
| **产品定位**  | AI 盯盘助手：监控 + 推送 + 多 Agent 分析                          | A 股单机工作台：账本事实 + 量化决策链 + 辅助 AI                                              |
| **数据权威性** | 持仓可手改；行情内存 TTL，重启/失效即丢；分析结论可驱动模拟盘                     | `palace.db` 成交不可被 market/AI 冒充；`market.db` 可重建但有 revision/回执；复盘只读真账本       |
| **AI 角色** | 定时 Agent + TradingAgents 辩论出「操作/决策」；盘中 AI 判断是否提醒      | 解释/录入/调度受控任务；禁止发明行情与盈亏数字；HITL 确认写操作                                        |
| **持仓与账本** | `Position` 成本/数量快照；多账户汇总；无交割事件链                       | 事件账本（买/卖/出入金）→ 现金与持仓投影；候选/预案                                               |
| **行情**    | `packages/marketdata`：CN/HK/US 实时 vendor 主备；不落权威日 K 表 | A 股适配器注册表 + 全量/热库双库；provenance；分钟线不写库                                      |
| **策略回测**  | 轻量信号回测 + 模拟盘自动交易；涨跌停 TODO                             | 战法 Protocol + `entry_timing`；经典/加速成交回测 + Horizon；研究 run card 路径（见 vibe 调研） |
| **通知推送**  | 多渠道（Telegram/企微/钉钉/飞书/Bark/…）+ 去重/安静时段/按规则选渠          | 主路径企微 webhook text；选股/触价/sync 失败模板；无 Apprise 多渠                            |
| **多市场**   | 一等公民 CN/HK/US（代码归一 + 分市场交易时段）                         | 刻意单市场 A 股；明确不引入美股/加密等跨市场源（market README）                                   |
| **前端**    | React + Tailwind + shadcn；PWA 移动向                     | Vue + Element Plus；桌面壳 + 工作台页；禁止第二套 UI 库                                   |
| **自托管方式** | Docker 一键为主；JWT 登录；单数据卷                               | `setup.ps1` / `loci.py` / `cli.serve`；便携 exe 分享包；本机三库                      |


---

## 差异根因

1. **信任边界不同**
  Loci 的产品承诺是「数字可审计」：成交、选股、回测、复盘必须可复现，AI 是旁路。PanWatch 的承诺是「盯住并告诉你」：AI 输出与推送是主路径，持仓是配置型快照，行情是即时拉取。  
   → 同一功能名（持仓/提醒/回测）在两边语义不同。
2. **时效 vs 证据**
  PanWatch 优化盘中秒级 quote + Agent 调度；不建千万行日 K 仓与回执链。Loci 优化全市场历史同步、协作合并、热库与研究 PIT——这是为选股/回测服务的，不是为 IM 推送延迟服务的。
3. **架构演进路径**
  PanWatch：`server.py` 巨石 + 单 `models.py` + Agent 插件，利于 Docker 开箱与功能堆叠。Loci：限界上下文 + 600 行拆分硬约束，利于账本/行情长期正确性，不利于「五分钟装完再加九个 Agent」。
4. **市场范围**
  PanWatch 靠 yfinance/腾讯/东财等拼 CN/HK/US；Loci 明确收窄到 A 股并拒绝把跨市场和进权威数字（与 Vibe 调研结论一致方向）。
5. **前端与分发**
  PanWatch 面向浏览器/PWA + 容器；Loci 面向 Windows 桌面工作台 + Element Plus 既有体系。照抄 React/shadcn 会直接违反本仓前端手册。

---

## 值得借鉴

按「Loci 缺什么 → 迁什么 → 风险」写，不写空泛架构赞美。

### 1. 多渠道通知抽象（高价值，局部）

**现状缺口**：ops 推送几乎只有企微 webhook（`src/ops/application/notify.py` / `api/notifications.py`）；无 Telegram/钉钉/Bark 等统一渠道路由表。

**可借鉴**：`CHANNEL_TYPES` 表单契约 + Apprise URI（或薄封装）+ `NotifyChannel` 启用/默认；`notify_dedupe` / `NotifyPolicy`（安静时段、TTL 去重）。  
证据：`PanWatch src/core/notifier.py`；`notify_policy.py`；`notify_dedupe.py`。

**怎么迁**：在 `ops` 扩 `notify_channels` 设置（ops.db），保留现有企微 text 为默认实现；新渠道只发**已由 review/strategy/ledger 算好的文本**，禁止 Agent 自由文案当权威。

**风险**：Apprise 依赖与密钥面扩大；须继续「出站只发受控模板」，不要引入「AI 原文直推」。

### 2. 通用价格提醒规则引擎（中高，补齐产品缺口）

**现状缺口**：Loci 触价是「活跃预案 × 昨收/近价」MVP（`review/application/alerts.py`），无用户自定义条件组、冷却、日上限、命中审计表。

**可借鉴**：`PriceAlertRule.condition_group` + cooldown / max_triggers_per_day / repeat_mode / hit 去重 bucket。  
证据：`models.py` PriceAlert*；`price_alert_engine.py` `_op_eval`。

**怎么迁**：新表落 `ops.db` 或 ledger 旁路「提醒订阅」（提醒≠成交事实）；评估只读 `market_hot`/live-tape，命中写 hit 日志再走 notify。不要把提醒状态写进 `palace` 成交。

**风险**：盘中轮询打爆外部源；须复用本仓 live 路由与节流，禁止另起一套 efinance 直连。

### 3. AI 成本/预算闸门的「美元或次数」层（中，增强已有 Token 顶）

**现状**：Loci 已有自然月 **Token** 硬顶（`LOCI_AI_MONTHLY_TOKEN_BUDGET`）。  
**可借鉴**：按「功能/Agent」聚合成本、超预算 reject/warn（`cost_tracker.check_budget`）。对昂贵可选能力（若未来接重型分析）比纯 Token 更可运营。

**怎么迁**：在 ops/ai 已有用量统计上加「能力级配额」配置；不必抄美元估算公式。

**风险**：美元估算依赖模型价目表，易过时；优先次数/Token，美元仅展示。

### 4. `packages/marketdata` 的端口化（中低，模式而非搬包）

**可借鉴**：`ConfigProvider` / `MetricsSink` Protocol，vendor 无 DB 依赖；`Symbol` 归一。  
证据：`packages/marketdata/README.md`「两个端口」。

**怎么迁**：本仓已有 adapter 注册表与 lane 策略——保持；若抽「只读探测/榜单」可学其 ports，**不要**把东财/腾讯/yfinance 整包替换 `MarketStore` 权威路径。

**风险**：双管道（实时包 vs 落盘仓）→ 双真相；与 vibe 调研「run card 绑本仓 revision」冲突。

### 5. Agent 调度目录与运行审计（低中，对齐 ops Job）

**可借鉴**：`AgentRun`（status/trace/notify_sent/duration）+ 股票×Agent 绑定。  
Loci 已有更强的 Job 互斥/补跑/企微防连推；若做「盘前简报」类能力，应落为 `ops` Job kind + 模板，而不是再引入 `server.py` 式 AGENT_REGISTRY。

---

## 不要照抄


| 项                               | 为何冲突 / 稀释定位                                   | 证据                                                                       |
| ------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------ |
| **TradingAgents 多 Agent「投资决策」** | AI 产出买卖结论当主路径，直接违反「AI 不发明权威数字 / 不冒充复盘」        | PanWatch `TradingAgentsAgent`；Loci `src/ai/README.md`、`src/AGENTS.md` §5 |
| **monkeypatch 上游库路由**           | 对 TradingAgents API 强耦合，升级脆弱；本仓禁止依赖不可审计的外部决策图 | `toolkit_adapter.py` docstring「没有公开 toolkit 注入入口」                        |
| **可变 Position 快照当账本**           | 抹掉成交审计；无法支撑资金曲线/往返/胜率                         | PanWatch `Position`；Loci `ledger/README.md`                              |
| **实时抓取当研究/回测唯一行情**              | 无 revision/回执/PIT；与 market 热库+provenance 目标相反 | marketdata `TTLCache`；Loci `market/README.md` data_snapshot              |
| **CN/HK/US 一锅烩进权威指标**           | 本仓刻意单市场；混合结算会制造假精确                            | PanWatch README 多市场；Loci market README「不引入美股…」                           |
| **React/shadcn/PWA 换前端**        | 违反 Element Plus 强制与 features 目录               | 双方 package.json / frontend AGENTS                                        |
| **Docker 为主分发、放弃便携 exe**        | 用户场景是 Windows 工作台分享包                          | `docs/portable-desktop.md` vs PanWatch Dockerfile                        |
| `**server.py` / 单文件 ORM 巨石**    | 违反 ≤600 行与 DDD 分包                             | PanWatch `server.py` 1572 行、`models.py` 1083 行；`AGENTS.md` 体量规则          |
| **模拟盘自动跟 AI/信号下单当「验证」**         | 易与真实账本混淆；Loci 应用确定性 backtest/research         | `paper_trading_engine.py`；`emit_paper_trading_signal`                    |
| **盘中 AI 自由裁量提醒**                | 不可复现；应规则引擎 + 可选 LLM 润色文案                      | `intraday_monitor.py` 职责                                                 |


---

## 建议动作（按优先级）

> 经「深度调研五轮」修订（2026-08-06）。否决 ID 见轮次5。


| 优先级 | 动作                                                                                                                  | 类型           | 说明                              |
| --- | ------------------------------------------------------------------------------------------------------------------- | ------------ | ------------------------------- |
| P0  | **忽略/否决** V1–V8：TradingAgents、monkeypatch、Position 快照账本、TTL 行情当研究证据、AI 驱动模拟盘、盘中 LLM 自由裁量买卖推送、换前端栈、AGENT_REGISTRY 巨石 | 忽略           | 与账本/AI/单市场红线冲突；见轮次5否决表          |
| P1  | **小实验**：ops 通知渠道（企微默认 + Bark/Telegram 其一）+ 全局 quiet hours；**保留** `wecom_push_marks` 交易日幂等，另可选 TTL scope             | 小实验          | 轮次1；正文仍只走确定性模板                  |
| P1  | **部分移植**：ops.db `alert_rules`/`alert_hits`（条件组、冷却、日上限、命中审计）；可引用 `plan_id` 但**不改写** plans；报价绑 live-tape/热库 spot      | 部分移植         | 轮次2；与日终预案触价并存                   |
| P2  | **小实验**：能力级 AI 次数配额叠 Token 月顶；查询失败**硬拒绝**（勿学美元预算默认放行）                                                               | 小实验          | 轮次3                             |
| P2  | **小增强**：job/AI run 展示 notify_attempted/sent、duration（学 AgentRun 字段，不学调度模型）                                          | 部分移植         | 轮次3                             |
| P2  | **忽略** paper trading 自动交易 UI                                                                                        | 忽略           | 已有 backtest/research；影子账户须另 ADR |
| P3  | **模式借鉴**：新只读采集用 Protocol 端口；**禁止** Engine「首个非空」替换 hist 协作合并                                                         | 部分移植         | 轮次4                             |
| —   | Docker 镜像发布                                                                                                         | 忽略（除非另有运维需求） | 与便携桌面主路径无关                      |


---

## 深度调研五轮

> 追加日期：2026-08-06。在上文对照基础上按主题深挖源码契约；固定 PanWatch `c1b064f`；不改业务代码。

### 轮次1 · 通知 / 去重 / 安静时段

**主题**：PanWatch 多渠道通知栈 vs Loci 企微单通道，抽出可迁移契约。

#### 论断（≥3，带路径）

1. **PanWatch 渠道是「表单契约 + Apprise URI + 自定义 HTTP」三层**
  `CHANNEL_TYPES` 定义 telegram/bark/dingtalk/wecom/lark/serverchan/pushplus/discord/pushover 的字段；Apprise 覆盖多数，企微/Server酱/PushPlus 走 `_CUSTOM_IMPL_TYPES`。  
   证据：`PanWatch src/core/notifier.py`（`CHANNEL_TYPES` ~L69–111，`_APPRISE_TYPES`/`_CUSTOM_IMPL_TYPES` ~L113–117，`build_apprise_url` ~L126）。
2. **发送路径内建 quiet hours + retry，测试可 bypass**
  `notify_with_result` 在无渠道时直接失败；否则若 `policy.is_quiet_now()` 且未 `bypass_quiet_hours` 则 `skipped: quiet_hours`；其后按 `retry_attempts` / 指数 backoff 重试 Apprise。渠道自检 API 显式 `bypass_quiet_hours=True`。  
   证据：`notifier.py` ~L241–310；`src/web/api/channels.py` 测试发送；`src/core/notify_policy.py` `NotifyPolicy.is_quiet_now`（跨午夜区间）。
3. **去重是「agent × scope」TTL 表，不是「任务 × 交易日」**
  `NotifyThrottle` 唯一键 `(agent_name, stock_symbol)`，`check_and_mark_notify` 用 `ttl_minutes` 窗口；另有按 agent 的 `dedupe_ttl_overrides` JSON 设置。内容指纹 `build_notify_dedupe_key` 用 title+content SHA1，但主节流表按 scope。  
   证据：`src/web/models.py` `NotifyThrottle` ~L270–282；`src/core/notify_dedupe.py`；`src/web/api/settings.py` 键 `notify_quiet_hours` / `notify_dedupe_ttl_overrides`。
4. **Loci 出站刻意单通道：企微 webhook text-only + 选股日标记**
  唯一发送函数 `send_wecom_text`；`send_wecom_markdown` 仅为兼容壳。设置 API 只有 `/api/ops/settings/wecom`。选股防连推用 `wecom_push_marks` 键 `job_id:trade_date`（保留 45 天），同日再跑记 `already_pushed`——这是**业务日幂等**，不是分钟级 TTL。  
   证据：`src/ops/application/notify.py` L1–7、L79–91；`src/ops/api/notifications.py`；`src/ops/application/wecom_push_mark.py`；`src/ops/README.md` 推送段落。
5. **两边都有「模板化正文」意识，但粒度不同**
  Loci：`format_alerts` / `format_screen_picks_text` / `format_digest` / `format_job_status` 由确定性数据拼 text，再出站。PanWatch：Agent/提醒自带 title+content（常含 AI 文案），再按渠道 sanitize（Telegram 去 MD）。  
   证据：Loci `notify.py` `format_`*；PanWatch `sanitize_for_telegram` ~L30–65。

#### 可迁移契约（给未来 ops 实验，非本轮实现）

```text
NotifyChannel { id, type, config, enabled, is_default }
NotifyPolicy  { timezone, quiet_hours, retry_attempts, retry_backoff_seconds }
SendRequest   { title, body_text, template_id?, bypass_quiet?: bool, dedupe_scope?: str }
Dedupe        { kind: job_day | ttl_scope, key, ttl_or_day }
约束          body_text 必须来自 review/strategy/ledger/ops 模板；禁止 AI 原文直推当权威
```

**相对上文「建议动作」的修正**：P1 通知渠道实验应**保留** `wecom_push_marks` 的交易日幂等，另加可选 TTL scope；安静时段可先做全局设置，不必一次引入 Apprise 全表——先企微默认 + 一个 plain-text 渠道（Bark/Telegram）即可验证密钥 UI。

### 轮次2 · 价格提醒规则引擎 vs 预案触价 MVP

**主题**：字段级对照——什么是「交易意图事实」，什么是「订阅式提醒」。

#### 字段对照


| 概念   | PanWatch `PriceAlertRule`                                                                      | Loci 触价路径                                              |
| ---- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| 主体   | 独立提醒规则，挂 `stock_id`                                                                            | 活跃 `plans` 行（账本意图）                                     |
| 条件   | `condition_group.{op,items[]}`：type∈price/change_pct/turnover/volume/volume_ratio；op 含 between | 固定：`stop_price` / `target_price` vs `last_close`；近距 2% |
| 时段   | `market_hours_mode` trading_only/always                                                        | 无；`notify` Job cron 决定何时算                              |
| 冷却   | `cooldown_minutes`（默认 30）                                                                      | 无规则冷却；选股有日标记，触价无                                       |
| 日上限  | `max_triggers_per_day`（默认 3）                                                                   | 无                                                      |
| 重复   | `repeat_mode` once/repeat                                                                      | 每次拉取都可显示同一状态                                           |
| 到期   | `expire_at`                                                                                    | `plans.status` 人工关闭                                    |
| 渠道   | `notify_channel_ids[]` 或默认渠                                                                    | 全局 `wecom_webhook`                                     |
| 命中审计 | `PriceAlertHit` + `trigger_bucket` 去重                                                          | 无 hit 表；API 即时计算列表                                     |
| 报价源  | 实时 `md_quote_rows`（TTL 缓存 5s）                                                                  | 热库日 K 最新收盘（非盘中现价）                                      |


#### 论断（≥3，带路径）

1. **PanWatch 提醒是通用条件 DSL + 扫描器；Loci 是预案投影**
  `_eval_condition` 按 type 取 quote 字段，量比优先报价再回退 K 线摘要；`eval_rule` 对 items 做 AND/OR。Loci `_classify` 只比较止损/目标与昨收，近距 `NEAR_PCT=0.02`。  
   证据：`PanWatch price_alert_engine.py` `_eval_condition`/`eval_rule` ~L146–222；`price_alerts.py` `AlertCondition`*；Loci `review/application/alerts.py` L9–34、L59–96。
2. **触发门闩（冷却/日上限/once/交易时段）是 PanWatch 的产品内核，Loci 完全缺失**
  `_can_trigger` 串行检查 enabled → expire → trading_only → 日计数重置 → daily_limit → once → cooldown。这决定「可推送」而不只是「可展示」。  
   证据：`price_alert_engine.py` `_can_trigger` ~L224–262；`models.py` `PriceAlertRule` 字段 ~L910–937。
3. **命中落库 + 分钟 bucket 防抖，与 Loci 无状态 API 不同类**
  `PriceAlertHit` 对 `(rule_id, trigger_bucket)` 唯一；扫描写 hit 再通知。Loci `GET /api/alerts/today` 每次现算，不记历史命中。  
   证据：`models.py` `PriceAlertHit` UniqueConstraint；Loci `ledger/api/router.py` `/api/alerts/today`；`alerts.py` `today_alerts_payload`。
4. **语义冲突：Loci 的 stop/target 属于账本预案，不应被「提醒规则表」吞掉**
  `plans` 写入含 scenario/entry_zone/layers/invalidation/rule_version（`plans_reviews.py`），是交易意图审计。提醒引擎应订阅「代码+条件」，可**引用** plan_id，但命中日志必须落 ops（或独立提醒库），禁止改写 palace 成交/预案事实。  
   证据：`ledger/infrastructure/plans_reviews.py` `add_plan`/`plans_payload`；bounded-contexts「ledger 不可被 market 写入」。
5. **报价时效差距大于功能差距**
  PanWatch 盘中现价扫描；Loci 触价用热库最新日 K 收盘——适合日终 `notify` 模板，不适合「量比>2 立刻推」。若移植规则引擎，数据源必须绑本仓 live-tape / hot spot，并复用 lane 节流，禁止直连 efinance。  
   证据：`price_alert_engine.py` `_fetch_quotes_map`；Loci `alerts.py` `latest_closes`；`market/README.md` 热库与 live 边界。

#### 可迁移最小 schema（ops.db，示意）

```text
alert_rules(id, code, name, enabled, condition_group_json, market_hours_mode,
            cooldown_minutes, max_triggers_per_day, repeat_mode, expire_at,
            plan_id_optional, channel_ids_json, last_trigger_at, trigger_count_today, trigger_date)
alert_hits(id, rule_id, trigger_bucket, trigger_time, snapshot_json, notify_ok)
```

**对建议动作的影响**：P1「价格提醒」应明确两阶段——(A) 保留预案触价日终展示；(B) 新增独立规则扫描；不要把 (B) 的字段塞进 `plans`。

### 轮次3 · Agent 调度 / 运行审计 / 成本闸门 vs ops Job + AI Token 顶

**主题**：谁在调度、记什么审计、钱/Token 怎么闸。

#### 论断（≥3，带路径）

1. **PanWatch 调度对象是「命名 Agent」；Loci 是「Job kind + config」**
  `AgentScheduler.register(agent, schedule, execution_mode)` 把 `premarket_outlook` 等注册进 APScheduler；`single` 模式按 watchlist 逐票并跳过非交易时段。Loci Job 注册表按 kind 执行（sync/screen/notify/…），助手只能管受控子集，禁止经助手创建 skill/notify 扩展面。  
   证据：`PanWatch src/core/scheduler.py` L17–60、L64–100；Loci `ops/README.md` 助手任务边界；`ops/application/jobs/registry.py`。
2. **两边都有运行审计，但字段重心不同**
  PanWatch `AgentRun`：status、trace_id、trigger_source、notify_attempted/sent、context_chars、model_label、duration_ms、截断 result/error（`record_agent_run`）。Loci ops 有 job runs（状态/结果/推送元数据）+ AI run/events SSE；另有 `eod_catchup` 对定点 cron 补跑。  
   证据：`agent_runs.py`；`models.py` `AgentRun` ~L182；`src/app/main.py` `_spawn_eod_catchup`；`ops/application/eod_catchup.py`。
3. **成本闸门：PanWatch 美元/能力级；Loci Token/自然月硬顶**
  TradingAgents `check_budget` 聚合本月 `AnalysisHistory.raw_data.cost_usd`，`exceeded` 时可由 `over_budget_action` reject/warn；`estimate_cost` 用粗算价目表。Loci `AssistantManager` 默认 `DEFAULT_MONTHLY_TOKEN_BUDGET=1_000_000`，环境变量 `LOCI_AI_MONTHLY_TOKEN_BUDGET`，超限直接拒绝新 run。  
   证据：`cost_tracker.py` L18–68、L86–116；`assistant_manager.py` L26–49、L150–153；`src/ai/README.md`。
4. **股票×Agent 绑定是 PanWatch 产品轴；Loci 无对等物**
  `StockAgent` / `AgentConfig` 允许按标的启停盘中监测等。Loci 提醒/选股绑定在 plans 与 screen Job，不按「每票挂一个 LLM Agent」。移植「盘前简报」应落为 ops Job + 模板 + 可选 LLM 润色，而非复制 StockAgent 矩阵。  
   证据：`models.py` `StockAgent`/`AgentConfig` ~L134–180；对照表 AI 角色行。
5. **查询失败默认放行是 PanWatch 预算的弱点；Loci Token 顶是硬失败**
  `check_budget` except 时 `exceeded: False`「默认放行」。Loci 预算解析失败抛 `ValueError`；用量达标拒绝消息。若借鉴能力级配额，应学 Loci 的硬失败语义，美元估算仅展示。  
   证据：`cost_tracker.py` L60–68；`assistant_manager.py` `_resolve_monthly_token_budget`。

#### 可迁移点（不迁调度巨石）


| 借                                           | 落到                                               |
| ------------------------------------------- | ------------------------------------------------ |
| AgentRun 的 notify_attempted/sent + duration | 扩展现有 job run / AI run 元数据展示                      |
| 能力级次数配额（非美元）                                | ops/ai 配置：如「重型分析 N 次/月」                          |
| 交易时段门闩（single 模式）                           | 未来 live 提醒扫描复用 market session，而非新 AgentScheduler |


**明确不迁**：`AGENT_REGISTRY` + `server.py` 生命周期；TradingAgents 预算美元公式当权威闸门。

### 轮次4 · packages/marketdata 端口化 vs market adapter / lane / 热库

**主题**：可借鉴的是端口解耦；不可借鉴的是「实时包 = 权威行情」。

#### 论断（≥3，带路径）

1. **PanWatch marketdata 的真正亮点是 Protocol 端口，不是 vendor 清单**
  `ConfigProvider.sources_for` + `MetricsSink.record` 让包零依赖 web/DB；`Engine.fetch` 按 priority 主备、`TTLCache`、首个非空返回。宿主单一路径接入，旧 collector 已删。  
   证据：`packages/marketdata/README.md` L1–20、L82+；`ports.py`；`engine.py` L23–60。
2. **Loci 已有更重的「落盘权威」管线，目标不同**
  adapter 注册表（tencent/eastmoney/baostock/sina/tdx…）→ lane 路由 / hist_daily **协作合并** → `sync_quotes` 写 `market.db` → provenance/`data_snapshot`/`market_revision` → `market_hot.db` 近窗只读镜像。热库声明「可重建、零双真相」。  
   证据：`src/market/infrastructure/adapters/registry.py`；`src/market/README.md` 热读库、线路、data_snapshot 段。
3. **双真相风险矩阵（若整包迁入）**


| 场景                                     | 风险                   |
| -------------------------------------- | -------------------- |
| UI 现价走 marketdata TTL，选股/回测走 market.db | 同一代码两套价，AI/用户误信      |
| 回测直接调 `md.klines` 不经 sync              | 无 revision/回执，研究不可复现 |
| CN/HK/US 混用 quote API 聚合资产             | 与「不引入美股…」及混合结算红线冲突   |
| Engine「首个非空即返回」替换 hist 协作合并            | 丢失冲突校验与字段互补语义        |


1. **故障转移语义相反方向值得注意**
  marketdata：priority 链上谁先返回非空谁赢（低延迟盯盘）。Loci hist_daily：多源取完再合并（正确性优先）。live 顶栏才用竞速。把 Engine 默认语义套到 hist 会 silently 降质。  
   证据：`engine.py` docstring「首个非空」；`market/README.md` hist_daily 协作 vs live 竞速。
2. **可安全借鉴的落地方式**
  - 新「只读探测/榜单/快讯」用 Protocol，不 import ops ORM。  
  - 盘中提醒扫描只允许调用本仓 `fetch_live_quotes_routed`（或明确标注 ephemeral 的旁路），**禁止**写入研究 run card 当行情证据。  
  - 不要把 `packages/marketdata` 整包 vendoring 进权威路径。

**结论**：端口化 = 模式借鉴（P3）；整包替换 MarketStore = P0 忽略。

### 轮次5 · TradingAgents / 模拟盘 / 盘中 AI 否决清单 + 修订建议动作

**主题**：可执行否决（带触发条件），并回写「建议动作」表。

#### 论断（≥3，带路径）

1. **TradingAgents 输出的权威是「PM 决策书 / BUY|SELL」——与 Loci AI 红线正面冲突**
  `result_mapper` 明确以 `final_trade_decision` 正文为评级权威，并映射 `decision` 动作档；上游无公开 toolkit 注入，PanWatch 用 **monkeypatch `route_to_vendor`**，文档自称强耦合。  
   证据：`result_mapper.py` L5–9、L58–80；`toolkit_adapter.py` 模块 docstring L1–19。
2. **模拟盘可被 AI 决策驱动，形成「非账本假权威」**
  `TradingAgentsAgent.emit_paper_trading_signal` 可将 BUY 写入 `StrategySignalRun`；`paper_trading_engine` 按信号自动建平仓。轻量回测引擎涨跌停 **TODO 未建模**。这与 Loci「数字由量化引擎产出、entry_timing、研究 run card」路径竞争心智。  
   证据：`tradingagents/agent.py` 构造参数；`paper_trading_engine.py`；`backtest/engine.py` L1–14。
3. **盘中监测 Agent 以 LLM 裁量输出建仓/加仓/清仓建议**
  `intraday_monitor` 定义 `SUGGESTION_TYPES`（建仓/加仓/减仓/清仓/持有/观望），属不可复现的操作建议主路径。Loci 若要盘中能力，应规则引擎命中 → 可选 LLM **润色文案**，建议不得写 palace、不得冒充复盘。  
   证据：`agents/intraday_monitor.py` `SUGGESTION_TYPES`；Loci `src/ai/README.md`「不发明数字」。
4. **否决清单（可执行）**


| ID  | 禁止动作                                     | 触发条件（看到即停）                  | 替代                               |
| --- | ---------------------------------------- | --------------------------- | -------------------------------- |
| V1  | 引入 `tradingagents` git 依赖或 LangGraph 决策环 | 任何 PR 把 BUY/SELL 当产品结论      | 助手只解释 strategy/review 已有输出       |
| V2  | monkeypatch 第三方 `route_to_vendor`        | 为接外部框架改全局函数                 | 公开端口 / 不接                        |
| V3  | Position 成本×数量快照替换 ledger                | 新表充当持仓真相                    | 继续事件账本                           |
| V4  | marketdata TTL 写入回测/选股证据                 | run card 引用无 revision 的实时包  | 只允许 live 提醒 ephemeral            |
| V5  | 模拟盘自动跟 AI 信号                             | UI 把 paper PnL 当验证          | backtest/research + 可选只读影子账户 ADR |
| V6  | 盘中 LLM 自由裁量推送买卖                          | notify 正文含「建议建仓」且无规则 id     | 规则命中模板 ± LLM 润色                  |
| V7  | React/shadcn/Docker 替换本仓壳                | 新前端栈或弃便携 exe                | 保持 Vue+EP+桌面包                    |
| V8  | `server.py` 式 Agent 巨石注册                 | 新 AGENT_REGISTRY 绕开 ops Job | Job kind + 模板                    |


#### 修订后的建议动作（五轮综合）

见上文「建议动作」表（已按五轮结论更新）。要点：

- **P0 否决**：V1–V8 整包。  
- **P1 做**：通知渠道（保留 wecom 日标记 + 可选第二渠 + quiet hours）；独立价格提醒规则（非塞入 plans）。  
- **P2 做**：能力级次数配额（硬失败，美元仅展示）；notify/job run 补 notify_sent 类元数据。  
- **P3 模式**：ConfigProvider 式端口；不迁 Engine 默认语义到 hist。

---

## 调研局限

1. 固定 **depth-1** clone 的 `c1b064f`；未遍历完整 git 历史与未合并 PR。
2. **未实际 `docker run` / 跑前端**，UI 行为以源码与 README 截图说明为准。
3. TradingAgents 上游 `v0.3.0` 本身未再展开审计（仅看适配层）。
4. 本仓工作树含大量未提交 AI/research 改动；对照以已文档化的模块 README/红线为准，不把未合并实验写成已发布基线。
5. PanWatch `VERSION` 文件为 `dev`；对外版本以 Docker Hub tag/GitHub Release 为准，本文不依赖星标或营销数字。
6. **五轮深挖**未重新 clone；沿用 `%TEMP%/PanWatch-research@c1b064f`。

---

## 源码索引（快速跳转）


| 主题    | PanWatch                        | Loci                                    |
| ----- | ------------------------------- | --------------------------------------- |
| 定位    | `README.md`, `CLAUDE.md`        | `README.md`, `AGENTS.md`                |
| 上下文/库 | 单 SQLite `src/web/models.py`    | `docs/architecture/bounded-contexts.md` |
| 行情    | `packages/marketdata/`          | `src/market/README.md`                  |
| 账本/持仓 | `Position`/`Account`            | `src/ledger/README.md`                  |
| AI    | `src/agents/`, `tradingagents/` | `src/ai/README.md`                      |
| 通知    | `src/core/notifier.py`          | `src/ops/application/notify.py`         |
| 提醒    | `price_alert_engine.py`         | `src/review/application/alerts.py`      |
| 分发    | `Dockerfile`                    | `docs/portable-desktop.md`              |


