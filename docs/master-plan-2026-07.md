# 潜龙记忆宫殿 · 系统重构总纲

> 立项日期：2026-07-26
> 状态：**已定稿**（三个关键决策见 §9，已确认）
> 本文是路线图，不是实现文档。每个阶段落地时另开 ADR。
>
> **2026-07-28 更新**：公网服务器部署已废弃下线（域名返回 410）。文中 `deploy/`、
> `sync-to-server.ps1`、线上 Docker 相关条目仅作历史记录，不再执行。

---

## 0. 现状诊断：先把话说清楚

以下全部是代码级核实的事实，不是印象。

| 你的判断 | 实际情况 | 严重度 |
|---|---|---|
| 没有复盘功能 | `reviews` 表 0 行、`plans` 表 0 行。`analytics_payload()` 的 `equity_curve` 是**已实现盈亏累加**（[src/palace.py:1184](../src/palace.py)），持仓期间曲线是平的，无法算回撤 | blocker |
| 信息不到位 | 后端已算出但前端**从未渲染**：`Candidate.evidence`、`Plan.stop_price/target_price/layers/scenario`、`Scorecard.review_groups`、`daily_pnl` | high |
| 前端不好看不好用 | 5 个写接口（候选/预案/复盘/快照/现金流）后端存在、前端**一个按钮都没有**，只能回本地 CLI 或 curl。无搜索、无筛选、无分页、无快捷键、无 K 线 | blocker |
| 线上想直接用 | [deploy/requirements-runtime.txt](../deploy/requirements-runtime.txt) 只装 `fastapi/uvicorn/itsdangerous`。**线上 import `src/fetcher.py` 会直接 ImportError**。线上是个哑账本 | blocker |
| AI 要用得更好 | 线上 LLM 相关代码 **0 行**。全仓库 grep `api_key/anthropic/openai/encrypt` 无命中 | blocker |

另外三条你没提但更要命的：

1. **仓库一个 commit 都没有。** `git log` → `does not have any commits yet`。40+ 文件全 untracked，没有任何回滚基线。
2. **`src/qianlong.py` 的辰星线算错了。** 原公式是"当天权重 20、越往回越小"的近期加权 WMA，代码里 `np.arange(20,0,-1)` 与 rolling 窗口点积，把权重 20 给了 20 天前那根、权重 1 给了当天，**权重方向整体倒挂**。所有基于它的信号和打分都建立在错误数值上。
3. **`requirements.txt` 缺 `yfinance`**（历史：旧报告链 `src/fetcher`）。**2026-07-28 已删除整条旧报告/discover 工具链。**

还有一份被低估的资产：[docs/stock-pick-backtest-2026-07.md](stock-pick-backtest-2026-07.md)。你手工做的那次回测（MFE/MAE、Hold-N 退出曲线、市场调整 alpha、评分单调性检验、前视偏差告警、拒绝集验证）**就是自动化复盘引擎的需求文档**，§7.5 那张表直接是待办清单。这份方法论应该被代码化，而不是每次手算。

---

## 1. 目标形态

> 一个自己会拉行情、自己会算复盘、自己会跑回测的单机金融工作台；AI 是坐在旁边的分析师，不是数据的来源。

---

## 2. 产品定位裁决：AI 和量化的分工

这是必须先定死的，否则后面所有功能都会打架：

- **所有数字由量化引擎产出**，AI 不生产任何一个数字。资金曲线、胜率、MAE/MFE、回测结果，全部来自行情仓 + 账本的确定性计算，可复现、可审计。
- **AI 只做三件事**：解释数字（"为什么这个月回撤大"）、提问和挑刺（"你这三笔都是追高，注意到了吗"）、把自然语言变成结构化操作（"帮我记一笔"→ 确认卡片 → 落库）。
- **两者结论冲突时，以量化引擎为准**，AI 的说法只是待验证的假设。

这条定位直接决定了：AI 不可用（没配 key / 余额不足 / 出网挂了）时，系统的核心价值**完全不受影响**。这正是你说的"脱离 AI 的复盘"。

---

## 3. 目标架构

```
┌─ 浏览器 (Vue3 SPA, 暗色金融终端) ────────────────────────────┐
│  今日 / 持仓·档案 / 候选池 / 交割单 / 复盘中心 /              │
│  K线工作台 / AI对话 / 策略中心 / 设置                          │
└───────────────┬──────────────────────────────────────────────┘
                │ REST + SSE (session cookie / Bearer)
┌───────────────▼──────────────────────────────────────────────┐
│  FastAPI  src/palace_api.py                                   │
│  /api/*(现有)  /api/quotes/*  /api/review/*                   │
│  /api/strategies/*  /api/backtest/*  /api/ai/*                │
├───────────────────────────────────────────────────────────────┤
│  ledger        review          quotes         ai              │
│  palace.py     replay.py       fetcher.py     gateway.py       │
│  (账本,不动)   equity.py       store.py       agent.py         │
│                attribution.py  sync.py        tools.py         │
│                candidate_bt.py                keyvault.py      │
│                plan_bt.py                                      │
│                metrics.py                                      │
│  strategies/   base.py  qianlong.py  discovery.py  ...         │
│  backtest/     engine.py (自写 pandas 事件驱动, T+1/涨跌停)     │
├───────────────────────────────────────────────────────────────┤
│  APScheduler(进程内, 单 worker): 15:35 行情增量 / 16:00 复盘   │
│                                  重算 / 盘后 AI 简报            │
└───────┬───────────────┬────────────────┬─────────────────────┘
        │               │                │
   palace.db      market.db          ai.db
   (账本,不可变)    (行情,可重建)      (对话/密钥,可清理)
```

**三库物理隔离**是核心决策。SQLite/WAL 只有一个写者：行情批量写入、AI 流式对话写入，都不能和交互式记账抢同一把写锁。三者语义也完全不同——账本是不可变审计源，行情是可从外部重建的缓存，对话是可清理的日志。

---

## 4. 数据模型总账（已消除方案冲突，此为定稿）

### 4.1 账本 `palace.db` —— 现有 9 表原则上不动

只做两处加法：
- `candidate_reviews` / `plans` / `reviews` 各加 `strategy_id TEXT`，与现有 `rule_version` / `strategy_tag` 自由文本过渡期并存。
- 新增 `strategies` 表：`id / slug / name / engine_type / config_json / status`。

**`holdings` 和 `position_events` 不加 `strategy_id`**（决策 D1 已确认）。多套战法共享同一份真实持仓，各自维护候选池、各自打分、各自统计胜率；持仓只有一份真实的。这避免了把 `holdings` 主键从 `(code)` 改成 `(strategy_id, code)` 这种破坏性变更，也避免实盘账本被模拟数据污染。

一个必须提前想清楚的推论：**同一笔真实成交要归给哪个策略做绩效？** 方案是在 `position_events.metadata_json` 里记 `strategy_id`（可空、可事后补），复盘按此归因；未标注的成交归入"未归属"分组单独统计，不硬塞给某个策略。这条不需要改表结构。

**现有 9 表不加 `user_id`**——你说了单用户就行，改动面是全部查询语句，收益为零。这条作为显式技术债写进后续 ADR-004，并写明触发条件（"出现第二个真实使用者"时启动迁移），迁移步骤逐条列好。

### 4.2 行情仓 `market.db`（独立 SQLite 文件）

```sql
instruments(code PK, name, market, board, list_date, delist_date, status)
quotes_daily(code, trade_date, open, high, low, close, volume, amount,
             turnover_rate, adj_factor, is_limit_up, is_limit_down,
             is_suspended, source, fetched_at, PRIMARY KEY(code, trade_date))
index_daily(...)              -- 同构，存 000300/000905/000852 做基准
corporate_actions(code, ex_date, adj_factor_cum, event_type)
ingest_watermark(code, last_trade_date, last_synced_at, status)
```

两条硬约束：
- **存原始价 + 复权因子，不存固化复权价**。否则将来除权除息一发生，历史缓存就出现"应该变但没变"的静默错误。
- **同步范围从第一天起就包含"账本里出现过的全部代码"**，含被剔除、被否决的候选。否则做候选池复盘时"剔除组"没数据，得回头重新回填。

**不上 DuckDB。** 三份设计里有两份分歧，这里拍板：MVP 到中期都用独立 SQLite 文件，量级真到全市场 5000 票 × 10 年（约 1250 万行）再平迁 DuckDB+Parquet。现在上 DuckDB 是白背一层技术栈。

### 4.3 复盘缓存（与 market.db 同库，可整表重建）

```sql
equity_daily(trade_date PK, holding_value, cash_est, floating_pnl,
             realized_pnl_cum, total_equity, drawdown_pct,
             bench_000300, bench_000905, bench_000852,
             confidence, computed_at)
position_rounds(id PK, code, opened_on, closed_on, shares_peak, avg_cost,
                avg_exit, realized_pnl, hold_days, mae_pct, mfe_pct, status)
candidate_outcomes(candidate_review_id PK, code, base_date, base_close,
                   ret_t5, ret_t10, ret_t20, ret_t60, mfe_in_window,
                   bench_ret_t20, alpha_t20, computed_at)
plan_outcomes(plan_id PK, entered_on, stop_hit_on, target_hit_on,
              status_final, fulfillment_days, computed_at)
signal_defs / signal_backtest_runs / signal_backtest_trades
```

`equity_daily` 此前被两份设计各写了一版、字段不同，这里定稿为上面这一版。

**归因单位用"持仓周期"（round-trip，从 0 仓建仓到清仓算一段），不建 FIFO 影子 lot 表。** 现有 `record_trade` 是移动加权成本、且卖出时把已实现盈亏摊回余票成本（你的长期规则，不当 bug 改）——这口径下批次身份已被抹平，硬做 FIFO 要维护第二套并行账本口径，心智负担不值。按持仓周期算 MAE/MFE 和持有天数，语义直观、够用，且和你手工回测里的口径一致。真需要更细再说。

### 4.4 AI 库 `ai.db`（独立文件）

```sql
-- 通用供应商条目：url + key + 拉模型（决策 D3）。不硬编码任何厂商。
llm_providers(id PK, name, protocol, base_url, encrypted_key BLOB, key_last4,
              default_model, models_json, models_fetched_at,
              is_active, validated_at, created_at, updated_at)
              -- protocol ∈ {openai_compatible, anthropic}
conversations(id PK, title, kind, provider_id, model, status, ...)
messages(id PK, conversation_id, role, content_text, content_json,
         input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
tool_calls(id PK, message_id, tool_name, arguments_json,
           requires_confirmation, status, result_json, error_text,
           confirmed_at, ledger_ref_id)
ai_usage_daily(trade_date, provider, model, ..., estimated_cost_cents)
```

`tool_calls.status ∈ {pending_confirmation, confirmed, rejected, executed, failed}` 是两段式写入的状态机核心，不能省。

---

## 5. 分阶段路线图

每个阶段都能独立发布验证，不要求一次性重构到位。

### P0 · 地基与止血 —— ✅ 已完成（2026-07-26）

| # | 事项 | 状态 |
|---|---|---|
| 1 | 基线提交 + 补全 `.gitignore` / 新增 `.gitattributes` | ✅ `a143d15` |
| 2 | 修辰星线 WMA 权重方向倒挂 + 单测 | ✅ `6b45728` |
| 3 | 补 `yfinance` 依赖 + scipy 缺失改显式告警 | ✅ `db37dd4` |
| 4 | 会话 Cookie 默认带 `Secure` + 登录失败限流 | ✅ `0abbda5` |
| 5 | 发布前强制 pytest + HTTP 模式一致性校验 | ✅ `8340bf7` |
| 6 | 验证服务器出网 | ✅ 见下表 |
| 7 | 验证 `.env` 新增密钥不被同步覆盖 | ✅ 见 P4 |

辰星线的实测影响：模拟 120 根真实走势，修复前后 **99 个交易日里有 36 天「辰星升」布尔信号完全相反**。所有基于它的信号与 `score_signals` 打分此前都建立在错误数值上。

#### P0 实测结论（2026-07-26，容器内直连，无代理变量）

| 目标 | 结果 | 对计划的影响 |
|---|---|---|
| 东财 `push2.eastmoney.com`（带 UA） | **200 / 0.14s** | P2 行情仓零障碍，不需要代理 |
| 新浪 `hq.sinajs.cn`（带 Referer） | **200 / 0.10s** | 同上 |
| `pypi.org` | **200 / 0.61s** | 扩容 requirements-runtime 可行 |
| DeepSeek | **401 / 0.12s**（可达） | P4 直连可用，零代理 |
| OpenRouter | **200 / 0.99s** | P4 直连可用，零代理 |
| Anthropic | 403（地域封锁） | 必须走代理 |
| OpenAI | Network unreachable | 必须走代理 |
| 宿主代理 `172.17.0.1:7890` | **可达**（mihomo 监听 `*:7890`） | 容器可用它访问境外 API |

推论，直接改写了 P4 的默认路径：

- **OpenRouter 直连可达是最优解**。一个 key 接 100+ 模型（含 Claude、GPT），协议是 OpenAI 兼容，`GET /api/v1/models` 能自动拉模型列表——正好落在 D3 的通用供应商模型里，**零代理即可用上 Claude**。DeepSeek 同理，成本更低。
- 直连 Anthropic / OpenAI 官方 API 才需要 `172.17.0.1:7890`，且已验证该代理从容器可达。所以"每个供应商可单独配代理"不只是设计上合理，是已验证可行。
- 之前从宿主机 shell 测出的"东财失败"是我漏带 UA 造成的假阴性；宿主机测 pypi 超时而容器内 200，说明两者出口路由不同。**结论必须以容器内为准**，这是应用真正跑的地方。

另外两条实测事实：

- **uvicorn 确认单 worker**（容器 CMD 无 `--workers`），APScheduler 进程内单例安全，不会重复触发抓取或烧 token。这条是 P2 定时任务的前提，现在被证实了。
- **服务器 4 核 / 3786MB 内存，当前仅 1150MB 可用；磁盘 40G 用了 49%，剩 21G。** 磁盘对行情仓绰绰有余，**内存是真瓶颈**：pandas+numpy+scipy 装上再跑回测，1.1G 可用内存会很紧。P2 必须给 docker-compose 加内存 limit，回测要控制批量大小，全市场扫描大概率需要分片跑。

---

### P2′ · 量化底座 —— ✅ 已完成（2026-07-26），顺序前置

原计划是 P1 前端优先。但新增了两条诉求——「支持安装 skill 包并按配置的 API 定时跑」
和「通达信代码转成量化工具、要解决选股慢的问题」——它们的地基都是本地行情仓
与向量化引擎。没有它，这两条都做不成，而前端有了真数据才有东西可展示。
所以把量化底座提到了前端之前。使用文档见 [quant-toolkit.md](quant-toolkit.md)。

| 模块 | 内容 | 提交 |
|---|---|---|
| `src/market` | 行情仓、多源降级、增量同步、交易日历、面板加载 | `9777a9a` |
| `src/formula` | 通达信内建函数向量化实现（23 个） | `9777a9a` |
| `src/strategies` | 策略接口 + 潜龙出海两个变体 | `9777a9a` |
| `src/backtest` | 信号级回测，含 A 股规则与成本 | `671ec0e` |
| `src/ops` | 技能包安装、任务调度、执行留痕 | `e582e47` |
| `src/ai` | 通用 LLM 网关、密钥加密 | `e582e47` |
| `src/routers` | 全部能力接入 HTTP + 部署侧调整 | `7d89dea` |

**核心洞察**：性能差距不在语言，在**形状**。通达信是 C 引擎逐票循环，
而把全市场组织成 `DataFrame(index=交易日, columns=股票代码)` 的面板后，
`REF` 就是 `shift`、`MA` 就是 `rolling.mean`，一次调用覆盖几千只票，
走 pandas 的 C 路径——反而比逐票循环更快。

实测：

| 指标 | 数值 |
|---|---|
| 同步吞吐 | 0.5–0.76 s/票；全市场约 43 分钟串行 / 11 分钟 4 并发 |
| 存储 | 400 只 = 271 万行 = 401 MB；外推全市场约 5.4 GB |
| 选股 | 400 只 × 60 日，加载 219 ms + 计算 109 ms = **328 ms** |
| 外推全市场 | **约 4.4 秒**（通达信全市场选股约 10 秒） |
| 交易日历优化 | `trading_days()` 648 ms → **4 ms** |

**DuckDB 的推迟决策依然成立**：瓶颈从来不在计算（109 ms 算完 60 天全市场），
而在 SQLite 的一次全表扫描——加一张几千行的日历小表就解决了。当前量级
上 DuckDB 仍是白背技术栈。

回测给出的第一个真实结论也值得记一笔：潜龙出海竞价版在 400 只样本上
**MFE 均值 +3.3% 而净收益 −1.8%，浮盈全部回吐**，与你手工回测 §7.6 发现的
是同一个病。样本仅 27 笔，不足以定论，引擎已自动附上小样本警告。

### P1 · 前端可用性（M）—— 投入产出比最高的一步

**不依赖任何新后端能力**，纯前端对接已有 API。做完这一步，线上就不用再回本地 CLI 了。

- 补齐 5 个缺失写表单：候选裁决、预案、复盘、资产快照、现金流。
- 把后端已算但前端没渲染的字段接上：`evidence`、`stop_price/target_price/layers/scenario`、`review_groups`、`daily_pnl`。
- 交割单加搜索/筛选/分页（替换硬编码 `limit=200`）、候选池去掉 `.slice(0,10)` 硬截断。
- 全局股票搜索 + `Ctrl+K` 命令面板（`buy 600519 100 16.8` 一行记成交、`goto 代码` 跳档案）。
- 视觉重做：暗色优先金融终端。设计 token 落地（`--bg-canvas #0a0e14` / 红涨 `#f5222d` 绿跌 `#00b578` / 金色强调 `#d4a017` / `tabular-nums` 等宽数字 / 表格行高 28-32px）。真正启用 Tailwind（现在是"声明了没用"的负资产）或彻底删掉它，二选一，不留中间态。删除死代码 `BarChart.vue`。
- 拆掉 `stores/palace.ts` 里那个 `switch(route.name)` 大分支，改成按页 composable。
- 补最小化 vitest 组件测试——前端现在零测试，大改期间没有任何回归兜底。

**不引入 shadcn-vue / Naive UI / Element Plus。** 命令面板本质是 input + keydown + 数组过滤，几十行原生代码；为 3-5 个组件引一整条 Reka UI 依赖链、还要专门验 CSP 兼容性，个人项目性价比不成立。

### P2 · 行情仓与真实资金曲线（L）—— "脱离 AI 的复盘"第一次落地

- `market.db` 建库 + 抓取层：akshare 主源、mootdx（通达信本地）应急降级、baostock 做 T+1 对账。
- APScheduler 每交易日 15:35 增量、次日 9:00 回补。**必须确认 uvicorn 单 worker**，否则多 worker 下同一个 cron 会被每个 worker 各触发一次，重复抓取、重复烧 token。
- **`positions_as_of(date)` 持仓回放函数**——从 `position_events` 按 `occurred_on <= date` 重放。这是市值曲线、逐笔归因、候选池回测三个功能**共同的地基**，必须最先实现，且要有覆盖"部分减仓 + 盈亏摊回余票成本"这条非常规规则的完整单测。这里出 bug，三个功能一起推倒重来。
- `equity_daily` 计算：每日总市值、浮动盈亏、已实现盈亏、总资产、回撤；对沪深300/中证500/中证1000 算超额；年化、最大回撤、夏普、卡玛、胜率、盈亏比、期望值。
- 现金流记录不全时，总资产曲线降级为"持仓市值 + 已实现盈亏"并在前端标注置信度——**不伪造现金数字**。
- 扩容 `deploy/requirements-runtime.txt`：`akshare/pandas/numpy/scipy/apscheduler`。镜像会从几十 MB 涨到 1GB+，**同步调整 `sync-to-server.ps1` 的健康检查超时阈值**，否则部署超时会误判失败、触发不必要的自动回滚。
- 给 docker-compose 加 CPU/内存 limit 和日志轮转（现在都没有）。

**验收：打开复盘中心，看到自己真实的资金曲线和回撤，与三大指数对比，全程不碰 AI。**

### P3 · 复盘中心与 K 线工作台（L）—— 差异化核心

- **逐笔归因**：按持仓周期算 MAE/MFE、持有天数、按标的/策略/月份/决策类型分组。写复盘表单时**自动预填程序算好的 MFE/MAE**，人工只做确认修改，不再手填。
- **候选池复盘**（这是你相对通用复盘工具的真正差异化）：当初判"买入/观察/剔除/不纳入"的票，事后 T+5/10/20/60 实际涨了多少。**包括"剔除的票后来涨了"这种反向证据**——你手工回测里的"硬剔验证"那张表，就是这个功能的手工版。
- **预案兑现率**：`entry_zone` 有没有被触达、`stop_price/target_price` 有没有被打到、兑现率多少。
- **K 线工作台**：klinecharts 9.x（锁大版本，10.0 还在 beta）画蜡烛 + 成交量 + 指标，叠加自己的买卖点、当时的候选评分与理由；逐帧回放，可隐藏未来 K 线做盲测训练。ECharts 做资金曲线/回撤/MAE-MFE 散点/分数直方图。
- 顺带解决"信息不到位"的另一半：研报摘要、龙虎榜、资金流、财务在档案页有专门呈现，不只是塞进 AI 工具清单。

### P4 · 线上 AI（L）—— 让线上真正能用

- **通用供应商配置（决策 D3）**：不做"Anthropic/OpenAI/DeepSeek"这种硬编码枚举，改成一个通用条目 —— **名称 + Base URL + API Key + 协议类型**，加一个"拉取模型列表"按钮。
  - `protocol = openai_compatible`：走 `openai` SDK 改 `base_url`。覆盖 DeepSeek、OpenRouter、OpenAI、Kimi、通义、硅基流动、以及任何自建/中转网关。模型列表调 `GET {base_url}/models` 自动拉取。
  - `protocol = anthropic`：走 `anthropic` SDK（`base_url` 可覆盖，便于走中转）。Anthropic 无公开模型列表接口，退化为内置候选 + 手填。
  - 拉不到模型列表一律降级为手填 model id，不阻断保存。
  - 只有这两种协议实现，**新增供应商 = 加一条配置记录，不需要改代码**。
- **Key 安全**：AES-256-GCM 加密（AAD 绑定 `provider_id`），主密钥 `PALACE_AI_MASTER_KEY` 只存服务器 `.env`。
  - P0 已验证 `.env` 的隔离是可靠的：发布脚本的上传白名单是**显式枚举**（只有 `requirements.txt` / `src/` / `frontend/dist/` / 四个 `deploy/` 文件），无通配；远端脚本对 `.env` **只有读操作**（`test -f` / `grep` / `sed -n` / `--env-file`），全脚本没有任何一处写入它；`.gitignore` 也覆盖了 `.env` 与 `deploy/.env`。所以新增主密钥不会被同步覆盖，也不会进仓库。
  - **但有个坑**：`deploy/docker-compose.yml` 用的是显式 `environment:` 白名单，**没有 `env_file:` 段**。往 `.env` 里加变量，容器默认看不到。P4 必须同步在 compose 的 `environment` 块加一行 `PALACE_AI_MASTER_KEY: ${PALACE_AI_MASTER_KEY:?...}`，否则症状是"我明明配了密钥，应用却说没配"。保存时先发一次 `max_tokens=1` 的最小请求校验有效性，失败不落库。GET 只返回末 4 位，**永不回显明文或密文**；解密只发生在调用 SDK 前一行，是局部变量；日志中间件对 `Authorization/api_key` 正则脱敏。
- **运行时出网代理**：`docker-compose.yml` 现在的 `HTTP_PROXY/HTTPS_PROXY` 只在构建阶段生效，运行容器没有任何出网通路。P4 要在 `environment` 块补上**可选的**运行时代理变量——境内直连的供应商（DeepSeek 等）不受影响，境外的（Anthropic/OpenAI/OpenRouter）走代理。代理地址每个供应商可单独覆盖，避免"为了一家境外模型把所有出网都绕道"。
- **服务端 Agent 循环**（手写，不上 LangGraph）：约 20 个只读工具自动执行（取行情、算指标、查账本、跑筛选、跑回测、在线检索），6 个账本写工具走**两段式**——模型只能"提议"，落 `pending_confirmation`，前端弹确认卡片，你点确认后端才真调 `PalaceStore` 落库，再把**真实**结果喂回模型继续。
- **SSE 流式**：`token_delta / tool_call_start / tool_call_result / tool_call_awaiting_confirmation / usage`。前端渲染成可展开的工具调用卡片。**Nginx 要为 SSE 单开 location**（`proxy_buffering off` + 长超时），现在两份模板都是笼统 60s，会直接掐断。
- **反幻觉双重护栏**：铁律进 system prompt 是第一层；第二层是代码/前端层规则检测——若某轮回复里出现价格/均线/MACD 等关键词、但本轮**没有任何成功的行情类工具调用**，前端追加警告横幅。"拿不到真实 K 线就必须失败"这条不能只靠模型自觉。
- **成本硬顶**：单轮工具调用次数上限、单月 token 预算硬顶写在 Agent 循环入口，不只是 UI 上显示花费。
- **定时 AI 任务**：盘后简报、早盘提示。这类会话的工具注册表里**物理上没有写工具**（不是靠 prompt 约束），从代码结构上杜绝无人值守写入。

### P5 · 多策略系统（XL）

- `StrategyEngine` Protocol：`default_params / score / signals / backtest` 四个方法。现有 `discovery.py`（四维打分）和 `qianlong.py`（潜龙出海状态机）各包一层适配器注册为前两个成员。
- **把通达信公式真正复刻成 Python 信号函数**。潜龙出海选股条件（T5 突破、L4 量能换手、抗织布、9:25 竞价过滤）与主图状态机应落在 `src/strategies/qianlong.py` / `src/qianlong.py`；卢高文六个涨停战法及 `COST()` 换手率衰减筹码分布见 `src/strategies/lugaowen.py`（`COST()` 语义与等宽分箱直方图仍有差距）。
- **回测引擎自写 pandas 事件驱动**，精确还原 A 股 T+1 不可当日卖出、涨跌停不可成交、停牌跳过。不上 qlib/zipline/backtrader——它们默认面向美股 T+0，适配成本比自写高。
- **防前视偏差是架构级约束**：每个信号函数配一条"信号截断一致性"单测（只喂到 T 日的数据 vs 喂全部历史，同一个 T 日信号值必须完全一致），作为 CI 强制门禁。你手工回测里踩过的那个坑（用 D 日盘中数据做 D 日决策）不能再踩。
- 前端策略中心：各策略独立候选池、独立复盘、独立绩效，并排对比。

### P6 · 收尾（M）

移动端 PWA（收窄为盯盘提示 / 记成交 / 看复盘三个场景）、可观测性（结构化日志 + 请求追踪 + 容器 unhealthy 告警）、releases 目录保留策略、备份体系纳入 `market.db` 和 `ai.db`。

---

## 6. 明确砍掉 / 推迟的

| 项 | 处置 | 理由 |
|---|---|---|
| DuckDB + Parquet | 推迟到全市场量级 | 当前量级纯属白背技术栈 |
| FIFO 影子 lot 表 | 砍掉，用持仓周期替代 | 为精确归因维护第二套并行账本口径，不值 |
| shadcn-vue / Reka UI | 砍掉 | 为 3-5 个组件引依赖链 + 验 CSP，个人项目性价比不成立 |
| 工具集 MCP 化 | 无限期推迟 | 服务"避免逻辑漂移"的工程洁癖，不服务任何用户可感知功能 |
| LiteLLM 网关 | 不用 | 4 家 provider 不足以摊平中间层复杂度；且 2026-03 有过 PyPI 供应链投毒 |
| Celery + Redis | 不用 | 单机单用户，APScheduler 进程内足够 |
| 全部新表统一加 `user_id` | 按需判断 | `ai_usage_daily` 这种系统级表加了没意义 |
| 现有 9 张账本表加 `user_id` | 不做，记 ADR | 改动面是全部查询语句，单用户收益为零 |

---

## 7. 已知风险（不粉饰）

- **akshare 被封 IP**。个人服务器通常单公网 IP，被封即系统性瘫痪。多源热切换（mootdx / baostock）不是可选项是必需项，且全市场首次回填最容易触发限流——必须限速 + 断点续传（`ingest_watermark` 为此设计）。
- **首次回填耗时未知**。akshare 请求间隔通常要 200ms-1s 防封，5000 票 × 历史区间，保守估计几十小时到数天。这个数字直接决定 P5 全市场扩展能不能兑现，需要在 P2 用小样本实测外推。
- **镜像体积暴涨**导致发布/回滚超时误判（见 P2）。
- **SQLite 写锁在行情仓内部依然存在**——物理隔离只解决了"行情 vs 账本"，定时批量抓取和手动补数之间仍然只有一个写者。
- **前端包体积**：klinecharts + ECharts 在 CSP 禁 CDN、必须全打包进 dist 的约束下，需要按需引入 + 首屏性能预算。
- **`PALACE_AI_MASTER_KEY` 没有轮换流程**。一旦怀疑泄露，需要旧主密钥解密全部 key、新主密钥重加密——这个应急流程要在 P4 一并设计。
- **审计元数据**：账本记录要能区分"手动录入"还是"AI 对话确认落地"（`tool_calls.ledger_ref_id` + 前端可视化）。这是未来复盘"AI 建议准确率"的唯一依据，漏了就永久丢失。
- **"不做自动交易"要成为对新功能的强制设计约束**：策略中心和信号回测的前端**禁止出现任何"一键跟单/一键下单"式引导 UI**。这条要写进新 ADR，不能只停留在旧文档共识。

---

## 8. 期望管理：线上能做到本地的几成

诚实回答：**六到七成，而且这个差距不会随迭代自然消失**，因为它是结构性的。

**能对齐的**：看数据、跑基础分析、把简单决策落进账本。这部分线上会做得比本地更顺（本地还要人工产出 `online_evidence.json` 再合并，线上一步到位）。

**做不到的**：

1. 本地对话背后是通用智能——能临时上网查任意资料、读写文件系统、跑任意脚本、随时换分析角度。线上 Agent 的能力边界被锁死在预注册的工具 Schema 里，**工具集永远滞后于临场创造力**。这不是多加几个工具能解决的。
2. "人工上网核验"依赖你对信息权威性的主观判断。工具化成 `web_search/web_fetch` 后，要么退化成更弱的规则校验，要么完全依赖模型自评可信度，有实质折扣。
3. 算力不对等。本地用最强模型；线上 BYO key，你很可能为省钱选便宜模型。
4. **两段式确认改变了交互节奏**。本地能"查完直接给完整建议"一气呵成，线上每次写操作都要停下来等你点确认。这是**故意的安全取舍，不是技术债**——不会"以后就一样了"。

要真正逼近十成，唯一的路是给线上 Agent 一个真正的代码执行沙箱，但那会撞上"不引入过重基础设施"和 CSP 约束。这是两个目标之间的根本张力，先说清楚，好过让你带着"应该完全一样"的预期去用。

---

## 9. 已确认的决策

| 编号 | 决策 | 结论 | 影响 |
|---|---|---|---|
| **D1** | 多套系统的语义 | **共享实盘仓位，多战法分别打分对比**。`holdings` / `position_events` 不动，只给 `candidate_reviews` / `plans` / `reviews` 加 `strategy_id`；成交归因走 `metadata_json.strategy_id`，未标注的进"未归属"分组 | 避免破坏性变更，P5 可增量上线；代价是不支持"几个战法各跑模拟盘 PK"，将来真要再开 ADR |
| **D2** | 落地顺序 | **P0 → P1 前端 → P2 行情 → P3 复盘 → P4 AI → P5 多策略 → P6 收尾** | 每步独立可发布；P1 不依赖任何新后端能力，最快见效 |
| **D3** | LLM 接入方式 | **通用供应商模型：名称 + Base URL + Key + 协议（openai_compatible / anthropic）+ 拉模型列表**。不硬编码厂商枚举 | 新增供应商不用改代码；运行时出网代理做成可选、按供应商覆盖 |
| **D4** | 技能包（新增诉求） | zip 上传 → 安全校验 → 解到数据卷 → 注册为可定时运行的模式。铁律由系统提示强制前置，技能包无权覆盖 | 已落地，见 §P2′ |
| **D5** | 量化底座顺序 | 提到 P1 前端之前 | 两条新诉求的共同地基；且前端有真数据才有东西可展示 |

### D2 的一个后果，先记下来

P4 排在 P2/P3 之后是对的——AI 的工具集要靠行情和复盘能力撑起来，没有 P2/P3，线上 AI 能做的事非常有限（只能查账本和聊天）。但这意味着**"线上能跟 AI 对话"这件事要等到相当靠后**。如果中途你想提前尝一口，可以从 P4 里切出一个最小子集插到 P1 之后：只做供应商配置 + 纯对话（无工具）+ 账本只读工具三样，工作量 M，能先让线上有个能问话的入口。这个提前量是可选的，不影响主线顺序。

---

> 本文与既有铁律并行有效：[docs/operating-rules.md](operating-rules.md) 的"失败优先于造假""不伪造行情""不输出确定性买卖建议"在重构后继续成立，且需要被吸收进新增功能的设计约束，而非仅作为历史文档保留。
