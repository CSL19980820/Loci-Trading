# 悟道 MCP 利用现状与增量价值评估

> 核验日期：2026-08-07  
> 范围：对照 Cursor 侧 `user-wudao-a-stock` 工具面与本仓 `src/intel` / `src/ops/application/skill_watch` / `src/market/.../wudao_adapter` 实际调用。  
> 方法：只读代码与 MCP 工具清单；未新增接入、未改配额配方、未消耗生产 Key。

## 结论（先答「有必要吗」）

**没有必要为「接口好玩」做全面加深利用。**  
短线主链（情绪 / 涨停梯队 / 题材资金 / 竞价 / 炸板 / 截面选股 / 个股资金与 K 线）已经在 `intel_fetch` 配方与战法监测里确定性落地；再铺一层「全工具适配器」会烧配额、膨胀上下文，且与「大批量量价走 market、MCP 只补本地算不出的情报」边界冲突。

值得做的不是「再接 20 个工具」，而是：

1. **把已采的 `intel_snapshots` 吃进 UI / 复盘**（脉冲、盘后复盘、助手引用），减少重复 `call_tool`。  
2. **按场景窄开 0–3 个缺口工具**（见下），写进配方或 Agent allowlist，而不是进 market 权威链路。  
3. **Agent/Skill 继续收窄工具白名单**——63 个 schema 全塞 prompt 成本高、收益低（已见 `docs/quant-toolkit.md`）。

## 现状覆盖（证据）

| 能力带 | 悟道工具示例 | 本仓落点 |
| --- | --- | --- |
| 日 K 备源 | `kline` | `wudao_adapter`（可选「日 K 优先」）；`kline_payload_*` 共享解析 |
| 开盘/盘中/盘后结构化采集 | `short_term_emotion`、`auction_*`、`limit_*`、`theme_*`、`index_market`、`market_overview`、`cls_news`、`smart_hotlist`、`stock_screener`、`dragon_tiger`、`capital_flow`、`intraday_main_flow`、`official_disclosure_evidence` 等 | `daily_recipe` + Job `intel_fetch` → `market.db.intel_snapshots` |
| 战法监测 / 纸面舱 | 同上子集 + `theme_stocks` / `auction_opening_snapshot` / `broken_limit_up` | `skill_watch/*`；不可用时整体降级 |
| Agent 临机 | MCP `collect_tools` 暴露可用工具 | 配额池 `skill`；技能包 `tools:` 收窄 |

架构铁律（本仓已写清）：全市场量价不走 MCP；悟道未配 Key / 过期 / 未同步工具时提前降级。

## 工具面差额（有意思 ≠ 该接）

下列在 Cursor MCP 清单里「好看」，但对 Loci 工作台增量有限或应主动避开：

| 类别 | 代表工具 | 判定 |
| --- | --- | --- |
| 一键工作流 | `market_replay_workflow` / `limitup_review_workflow` / `stock_research_workflow` | Agent 临机可用；**不必**再写确定性 Job——配方已拆原子工具，digest 包会难缓存、难断言 |
| 情绪复盘面板 | `board_break_analysis` | **可选**：盘后复盘补「昨涨停×今日」交叉；未进配方前不阻塞主链 |
| 竞价题材聚合 | `auction_theme_strength` | **可选**：开盘窗与 `theme_intraday_capital` 互补；注意勿与盘中题材榜混比 |
| 催化/解禁日历 | `market_catalyst_calendar` / `stock_event_calendar` / `unlock_events` | **可选·低频**：盘前排雷，适合 close/open 少量调用，勿扫全市场 |
| 基本面包 | `financial_summary` / `valuation_snapshot` / `shareholder_structure` / `research_reports` | 研究/助手按票点查即可；**不要**做成日更权威仓 |
| AI 简报 | `briefings` | **不建议入库当事实**——与「AI 不发明数字、复盘数字走引擎」冲突；可当助手旁注 |
| 自选股写入 | `watchlist_*` | **不要接进账本**；自选真相在本机，不在悟道账号 |
| 美股 SEC / 转债 / ETF | `sec_*` / `convertible_bond_market` / `etf_market` | 非当前 A 股短线主产品边界 |
| 监管异动 | `anomaly_detection` | niche；无明确产品故事前不做 |

## 若只加三刀（优先级）

1. **消费侧（已落地）**：`GET /api/intel/brief` + 盘面 `PulseIntelStrip` 只读当日 `intel_snapshots`（情绪、题材、梯队）；未跑 `intel_fetch` 时空态。Insights/Assistant 可后续同口径复用 brief。  
2. **配方增量（可选，未做）**：`close` 加 `board_break_analysis`；`open` 加 `auction_theme_strength`（limit 收紧）。验收：配额估算不爆、有缓存命中。  
3. **Agent allowlist（未做）**：研究/复盘技能显式加入 `official_announcements` 或 `stock_research_workflow`（digest），禁止默认暴露全部工具 + 禁止 `watchlist_*` 写。

## 明确不做

- 不为「覆盖率」给每个悟道工具写 Python 适配器。  
- 不用悟道结果覆盖 `palace.db` 成交真相或冒充本地复盘权威曲线。  
- 不用 MCP 做全市场日 K / 全池因子扫描（配额与口径都不匹配）。  
- 不把悟道自选与本地候选池双向同步。  
- **不让缺悟道拖垮主体**：统一入口 `wudao_availability` + `call_mcp_tool` 软失败（不抛、不扣配额）；`intel_fetch`/`skill_watch` Job 记 `skipped`；纸面闸门空仓降级；brief API 与盘面空态；行情仍走本地 adapters。

## 决策一句话

悟道接口面宽，本仓已经把**短线决策所需的高价值子集**接进配方与战法；下一步价值在「吃缓存、补 1～2 个复盘缺口、收紧 Agent 白名单」，而不是「全面利用」。
