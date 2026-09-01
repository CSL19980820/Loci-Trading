# 回测 / 组合 / 执行引擎架构对比：我们的信号级逐笔回测离主流差在哪（scratch）

> **日期**：2026-08-25 ｜ **检索日期**：2026-08-25
> **用途**：供上层综述引用。回答「Loci 的信号级逐笔回测，相对 zipline-reloaded / backtrader / nautilus_trader / QuantConnect Lean / vectorbt / Backtesting.py / bt 这一批主流引擎，结构性缺什么」。**不是选型建议书**——每条判定都标了「换 / 不换 / 补」。
> **范围**：只读。除本文件外未改任何仓库文件，未 commit / push，未写库。跑过两段一手实测：① 向量化 vs 事件驱动吞吐基准（合成数据，进程内）；② `market.db` 只读查询（`file:...?mode=ro` URI，单次 0.52s）。未落任何临时文件。
> **证据分级**：`P1` 一手源码 / 论文全文已读并逐行核对；`P2` 官方 README / docstring 原文，未读实现；`P3` 本轮本仓实测（输入输出内联在正文，可复跑）；`✗` 未找到一手依据。
> **上游实测**：数据库体积 / 行数 / 依赖清单 / 退市字段等来自**主 agent dbstat 实测 2026-08-25**；本文独立复核了其中三项，见 §0.2。
> **与既有文档的关系**：`2026-08-dragon-survivorship-and-portfolio-fragility.md` 记录了「信号数差 3.4% → 组合全期收益差 187%」这个**现象**但没给机制——本文 §2.4 给机制、§2.5 给修复。`2026-08-tail-1450-next-day-touch-backtest.md` 的「日内截面中性化」在 §6 被定位到国际口径的哪一档。⚠ `2026-08-github-open-source-technology-radar.md` §3 称「`requirements.txt` 已有 DuckDB、vectorbt」——**本轮实测 vectorbt 已不在 `requirements.txt`**（§0.2），该行需订正。

---

## 0. 判定先行

### 0.1 一句话

**不要换引擎。** 向量化选股层是资产不是负债——一手实测：93 组参数 × 5,500 只 × 1,358 天 ≈ **7.0 亿** bar-asset-combo，**9.465 秒**跑完；同样工作量用一个被剥光的事件循环要 **3.8 分钟**，真实事件驱动引擎还要再慢一个量级以上（§1.3）。缺口全部在**信号之后**：

| # | 缺口 | 严重度 | 本文给的东西 |
|---|---|---|---|
| 1 | **组合层没有持仓市值**：`equity = cash + Σ 入场名义额`，未实现盈亏恒为 0 | **致命** | §2.5 对象 / 字段 / 不变式清单 + 伪代码 |
| 2 | **回测结果零持久化**：`strategy_backtests` 0 行，且 schema 只存聚合 JSON | **致命（直接阻断第 4 条）** | §5.6 trial 矩阵表设计 |
| 3 | 绩效只有逐笔统计：无年化 / Sharpe / Sortino / Calmar / Alpha / Beta | 高 | §5.1 口径对照 + 免 scipy 实现 |
| 4 | 参数扫描只有一句「注意过拟合」的文字提示 | 高 | §5.4 DSR、§5.5 PBO：公式 + 门禁 + 伪代码 |
| 5 | 成交量约束完全没有 | **中——比预期低，见 §3.5** | §3.5 实测：当前资金规模下只影响 0.39% 的股票-日 |
| 6 | 截面中性化只有「减当日全池均值」，无行业 / 市值分组 | 中 | §6.3 三行代码级升级路径 |
| 7 | 交易日历自建，无外部对账 | 低 | §4.4 判定：**不换，加只读对账闸** |

**优先级：2 → 1 → 4 → 3 → 6 → 5 → 7。** 第 2 条排第一不是因为最严重，而是因为**它阻断第 4 条**——没有落库的 trial 矩阵，PBO 在数学上就无法计算。

### 0.2 对上游 dbstat 数字的独立复核（`P3`）

| 项 | 主 agent dbstat | 本文独立实测 | 结论 |
|---|---|---|---|
| `market.db` 体积 | 5,740.2 MB | `os.path.getsize()` = **5,474.3 MiB** | **同一文件**：5,474.3 × 1.048576 = 5,740.2。只差 MiB/MB 口径，数字互证 |
| 依赖无 scipy | pandas/numpy/duckdb/polars… | `requirements.txt`：`pandas>=2.0.0`、`numpy>=1.24.0`、`duckdb>=1.0.0`；**无 scipy / statsmodels / scikit-learn / empyrical / quantstats / vectorbt** | 一致。**直接决定 §5 的实现必须免 scipy** |
| `strategy_backtests` 0 行 | 0 行 | schema 实读 `(slug, version, metrics_json, …)`——即使有行也**只存聚合 JSON** | **比「0 行」更糟**：这张表的形状本身装不下 PBO 的输入 |

运行环境：`.venv` = Python 3.12.13 / numpy 2.4.6 / pandas 3.0.5。

---

## 1. 两条技术路线的本质区别

### 1.1 定义（用源码说，不用比喻）

**向量化**＝在 `(T × N)` 矩阵上做**保形变换**。zipline 的 `GroupedRowTransform` 是这个范式最干净的样本，核心变换就六行（`P1`）：

```python
# zipline/pipeline/factors/factor.py:1842-1847 —— 向量化范式的全部内核
def demean(row):
    return row - nanmean(row)

def zscore(row):
    with np.errstate(divide="ignore", invalid="ignore"):
        return (row - nanmean(row)) / nanstd(row)
```

输入一行、输出一行、**行与行之间没有状态**。这既是它能被向量化的全部原因，也是它的全部限制。

**事件驱动**＝按时间推进的状态机 `order → trigger → fill → transaction → ledger`。zipline 的 `SlippageModel.simulate` 是最小完整样本（`src/zipline/finance/slippage.py`，`P1`）：

```python
def simulate(self, data, asset, orders_for_asset):
    self._volume_for_bar = 0
    volume = data.current(asset, "volume")
    if volume == 0:
        return
    price = data.current(asset, "close")
    dt = data.current_dt
    for order in orders_for_asset:
        if order.open_amount == 0:              # <- 跨 bar 残留状态
            continue
        order.check_triggers(price, dt)         # <- 盘中触发
        if not order.triggered:
            continue
        try:
            execution_price, execution_volume = self.process_order(data, order)
            if execution_price is not None:
                txn = create_transaction(order, data.current_dt,
                                         execution_price, execution_volume)
        except LiquidityExceeded:               # <- 本 bar 流动性耗尽，停止撮合
            break
        if txn:
            self._volume_for_bar += abs(txn.amount)   # <- 同 bar 跨订单累积状态
            yield order, txn
```

`self._volume_for_bar` 是**同 bar 内跨订单累积的状态**，`order.open_amount` 是**跨 bar 残留的状态**。这两个状态就是向量化范式在数学上放不进矩阵的东西——不是「难以实现」，是**矩阵的一格只能放一个数**。

### 1.2 事件驱动能做而向量化做不到的六件事

| # | 能力 | 一手源码 | 为什么矩阵做不到 |
|---|---|---|---|
| 1 | **部分成交** | zipline `FixedBasisPointsSlippage.process_order`：`shares_to_fill = min(abs(order.open_amount), max_volume - self.volume_for_bar)`，填不满抛 `LiquidityExceeded`，残量留在 order 里下一 bar 再撮合（`P1`） | 「剩余未成交量」是订单的私有状态，要跨 bar 存活 |
| 2 | **订单簿** | nautilus_trader README：「using historical quote tick, trade tick, bar, **order book**, and custom data with **nanosecond resolution**」（`P2`） | 盘口是每时点一个**深度数组**，等于给每个 (t, asset) 再挂一维 |
| 3 | **资金占用约束** | backtrader `BackBroker` 参数 `('checksubmit', True)`，docstring：「check margin/cash before accepting an order into the system」（`P1`）；Lean `GetMarginRemaining(tpv) = tpv − UnsettledCash − TotalMarginUsed`（`P1`） | 「这笔能不能下」取决于之前**所有**成交的累计，严格顺序依赖 |
| 4 | **动态仓位** | zipline `_calculate_order_percent_amount`：`value = self.portfolio.portfolio_value * percent`（`algorithm.py:1660-1662`，`P1`） | `portfolio_value` 是当下盯市结果；目标手数依赖它，它又依赖之前的成交 |
| 5 | **盘中触发** | zipline `order.check_triggers(price, dt)`；Backtesting.py：「market orders are filled on next bar's open, whereas other order types (limit, stop-limit, stop-market) are filled **when the respective conditions are met**」（`backtesting/backtesting.py:228-231`，`P1`） | 触发是 bar **内部**的时间顺序；日线里 high 和 low 谁先到不可知 |
| 6 | **多资产再平衡** | zipline 把陷阱写进 API 文档（`algorithm.py:1841-1847`，`P1`）：连续两次 `order_target_percent(sid(0), 10)` 得到 **20%** 仓位，「because the first call will not have been filled when the second call is made」 | 再平衡要同时知道所有腿的现值与现金；分腿顺序执行，结果就依赖顺序 |

第 6 条值得单独记：**zipline 自己把「顺序依赖」写成 API 文档里的陷阱警告**。这和我们 §2.4 那个 187% 是同一类病。

### 1.3 速度差多大：一手 benchmark（`P3`）

同机、同数据、同一份 numpy。合成面板刻意取真实工作集形状：**T = 1,358 交易日 × N = 5,500 只**（对应 2021-01 起的 A 股票池；上游 dbstat：`quotes_daily` 2021 起 6,833,221 行、全库 5,547 只）。

```text
B  event-driven  N= 100 x T=1358 ->    0.045s  (3.013 M bar-asset/s) [1 combo]
B  event-driven  N= 300 x T=1358 ->    0.133s  (3.069 M bar-asset/s) [1 combo]
A  vectorised    N=5500 x T=1358 x 93 combos ->    9.465s  (73.4 M bar-asset-combo/s)
per bar-asset-combo: vectorised    13.63 ns  event-driven    325.86 ns  ratio = 24x
extrapolated event-driven cost for same 93-combo x 5500-asset sweep: 0.06 h
numpy 2.4.6  python 3.12.13
```

**三条读法，第三条最重要**：

1. 单位成本：向量化 **13.63 ns / bar-asset-combo**，事件循环 **325.86 ns / bar-asset**，比值 **24×**。
2. 绝对量级：93 组参数的全市场扫描，向量化 **9.5 秒**，事件循环外推 **3.8 分钟**。
3. **24× 是下界，不是实际差距。** 我那个事件循环被刻意剥光了：无 Order 对象、无事件分发、无 commission/slippage 模型调用、无 ledger、无缓存失效，而且槽位一满（`maxpos=20`）就 `break` 掉整个入场扫描——它跳过了绝大多数资产。真实 zipline / backtrader 每根 bar 要为每个未成交订单构造 Transaction、调 commission 模型、更新 `PositionTracker` 并置 `_dirty_stats`。**请把 24× 当「至少 24 倍」用，不要当「大约 24 倍」。**

⚠ 诚实边界：合成面板的数值分布不等于真实 A 股，但本基准量的是**每格固定开销**，与数值分布无关；两侧共用同一份数组，比值可信，绝对秒数只对本机有效。vectorbt 官方 README 只给定性说法（「turning hours of grid search into seconds」，`P2`），**未给可复核的基准数字**，故本文用自测数替代。

### 1.4 对 Loci 的判断：不换，做「向量化选股 + 事件驱动组合层」两段式

三条理由，全部基于本仓事实而非偏好：

1. **向量化层是我们唯一真正产出过结论的地方。** `2026-08-tail-1450-next-day-touch-backtest.md` 那轮跑了 **4,401,129 个股票-交易日 × 4,479 个参数组合**。按 §1.3 实测单位成本，用事件驱动引擎重跑是**数十小时**量级。换引擎＝放弃这一类研究。
2. **缺口不在选股层。** §0.1 七条缺口里 1/2/3/4/6 全部发生在信号生成**之后**。换引擎解决不了「结果不落库」「没有过拟合门禁」。
3. **数据层撑不起全事件驱动。** 上游实测：**分钟线不落库**（`GET /api/market/minute/{code}` 明确不写 `market.db`），live 只有进程内 3–5 秒 TTL 缓存。没有 bar 内数据，事件驱动引擎最值钱的能力（§1.2 第 1/2/5 条）**在本机无数据可喂**——买回来也是空转。

**边界要写死**，否则会退化成两个都不彻底：

```text
┌─ 第一段：向量化选股（保留现状，不动） ───────────────────────┐
│  输入：(T × N) OHLCV 面板      │
│  输出：(T × N) 布尔信号矩阵 + (T × N) 排序分矩阵   │
│  硬约束：只吐信号；不知道钱、不知道仓位、不知道有没有成交  │
│  —— 已写死在 src/backtest/application/engine.py 模块      │
│     docstring：「策略只吐信号，本模块只吃信号吐结果，        │
│     中间不交换任何信息」。继续保持。      │
└──────────────────────────┬───────────────────────────────────┘
                │ 交界面：signals + ranks（纯矩阵，无状态）
┌──────────────────────────┴───────────────────────────────────┐
│─ 第二段：事件驱动组合层（要新建，见 §2.5） ──────────────────│
│  输入：信号矩阵 + 日线 OHLCV + 交易日历         │
│  逐日推进：盯市 → 平仓 → 目标权重 → 开仓 → 记账 → 校验       │
│  输出：日频 equity 曲线 + 成交流水 + 每日持仓快照  │
│  硬约束：日频。不假装能做 bar 内触发（本机无分钟线）         │
└──────────────────────────────────────────────────────────────┘
```

**明确不要做的两件事**：① 不要在第二段回头改信号（会把前视偏差重新引进来）；② 不要让第二段声称能模拟盘中触发——本机日线里 high/low 先后不可知，任何「触价成交」都是假设不是模拟。

---

## 2. 组合账户模型（核心之一）

### 2.1 三家的对象模型对照

| 层 | zipline-reloaded | QuantConnect Lean | backtrader |
|---|---|---|---|
| 账户聚合 | `protocol.Portfolio` | `SecurityPortfolioManager` | `BackBroker` |
| 保证金 / 购买力 | `protocol.Account` | `CashBook` + `UnsettledCashBook` + `MarginCallModel` | `BackBroker` + `CommInfoBase` |
| 单票持仓 | `protocol.Position` / `finance.position.Position` | `SecurityHolding` | `position.Position` |
| 持仓集合与撮合 | `finance.ledger.PositionTracker` | `SecurityPositionGroupModel` | `BackBroker.positions` |
| 「下多少」 | `order_target_percent` 等 API 方法 | `SetHoldings` / `BuyingPowerModel` | **独立可插拔的 `Sizer` 对象** |

**分歧点很有信息量**：backtrader 把「下多少」抽成独立对象，zipline 做成 algorithm 上的方法，Lean 埋进 `BuyingPowerModel`。**但三家都把「下多少」和「能不能下」分成两件事**——这正是我们现在合成一坨的地方（§2.3）。

### 2.2 zipline / Lean 的字段级清单（`P1`）

`src/zipline/protocol.py` 逐字：

```text
Portfolio: cash_flow, starting_cash, portfolio_value, pnl, returns, cash,
           positions, start_date, positions_value, positions_exposure
           + current_portfolio_weights
             (= last_sale_price × amount × price_multiplier / portfolio_value)

Account:   settled_cash, accrued_interest, buying_power, equity_with_loan,
           total_positions_value, total_positions_exposure, regt_equity,
           regt_margin, initial_margin_requirement,
           maintenance_margin_requirement, available_funds, excess_liquidity,
           cushion, day_trades_remaining, leverage, net_leverage, net_liquidation

Position:  asset, amount, cost_basis, last_sale_price, last_sale_date
```

两个设计细节值得直接抄：

- **三个类都重写了 `__setattr__` 抛 `AttributeError("cannot mutate ... objects")`**，内部改动只能经 `MutableView` 走。策略拿到的是**只读视图**——从语言层面杜绝「策略偷偷改自己的现金」。
- `Position.cost_basis` 的口径是「**Average price at which currently-held shares were acquired**」，且 `PositionTracker.handle_commission` 会调 `position.adjust_commission_cost_basis(asset, cost)`——**佣金摊进成本基准**，不单独挂账。这一条决定未实现盈亏的口径，抄的时候别漏。

Lean 的权益恒等式写得最直白（`Common/Securities/SecurityPortfolioManager.cs`，`P1`）：

```text
TotalPortfolioValue = CashBook.TotalValueInAccountCurrency
                    + UnsettledCashBook.TotalValueInAccountCurrency
                    + totalHoldingsValueWithoutForexCryptoFutureCfd
                    + totalFuturesAndCfdHoldingsValue

MarginRemaining     = TotalPortfolioValue − UnsettledCash − TotalMarginUsed
TotalMarginUsed     = Σ group.BuyingPowerModel.GetReservedBuyingPowerForPositionGroup(...)
```

注意 Lean 显式区分 **settled / unsettled 两个 CashBook**，并在 `GetMarginRemaining` 里把 unsettled 部分**扣掉**。A 股是「股票 T+1、资金 T+0」，方向与美股 T+2 相反，但**两个现金池的结构一样需要**（见 §2.5 的 `Account.frozen_cash`）。

backtrader 的 `BackBroker.init()` 则把这套东西摊平成一组标量（`P1`）：`startingcash / cash / _value / _valuemkt / _valuelever / _valuemktlever / _leverage / _unrealized`，外加 `positions = defaultdict(Position)`。它是三家里最轻的，但**`_unrealized` 这个字段是存在的**——这正是我们缺的那一个。

### 2.3 我们的现状：`research_portfolio.py` 逐条解剖（`P1`，本仓源码）

**致命缺陷 ①：`equity` 用入场名义额，不是市值。**

```python
# src/backtest/application/research_portfolio.py:354-367（节选，逐字）
capital_in_use = sum(item.entry_notional for item in occupied.values())
idle_cash = max(0.0, cash)
exits_today = exits_by_date.get(day, [])
realized = 0.0
for allocation in exits_today:
    if occupied.get(allocation.slot) != allocation:
        continue
    cash += allocation.exit_notional
    realized += allocation.pnl
    del occupied[allocation.slot]
equity = cash + sum(item.entry_notional for item in occupied.values())
#                 ^^^^^^^^^^^^^^ 入场名义额，不是当日市值
```

后果不是「略有偏差」，是**三个指标同时失真**：

1. **未实现盈亏恒为 0。** 持仓期间 equity 曲线是**平的**，只在退出日跳变。
2. **最大回撤系统性低估。** `max_drawdown` 就是在这条阶梯曲线上算的（`research_portfolio.py:397-402`）。持仓中途的浮亏**完全看不见**。既有文档里那些「组合回撤 −37.55% / −28.30%」量的是**已实现盈亏的回撤**，不是账户回撤——**这两个不是一回事，此前的表述应当订正**。
3. **任何依赖当前权益的决策都无从谈起**：目标权重、杠杆闸、追保全部做不了。

**致命缺陷 ②：退出用「回填单笔收益率」，不重新撮合。**

```python
# src/backtest/application/research_portfolio.py:317-326（节选，逐字）
quantity = floor(cfg.slot_capital / entry_price / cfg.lot_size) * cfg.lot_size
entry_notional = quantity * entry_price
net_factor = max(0.0, 1.0 + float(trade.net_return_pct) / 100.0)
exit_notional = entry_notional * net_factor  # <- 回填「信号级引擎预先算好的」收益率
pnl = entry_notional * float(trade.net_return_pct) / 100.0
```

`trade.net_return_pct` 是**信号级引擎在组合层之前就算完的**。于是组合层：不能改成本假设、不能加滑点、不能部分成交、不能因资金不足而少买、不能在持仓期间加减仓。**组合层退化成了「按预算收益率分配槽位」的会计程序，不是模拟器。**

**其余缺口**：

| 缺什么 | 现状 | 后果 |
|---|---|---|
| `Position` 对象 | 只有 `PortfolioAllocation`（frozen、一次性、无 qty 变更） | 不能加仓 / 减仓 / 部分成交 |
| 复利 | `slot_capital = initial_capital / max_positions`，**静态 property** | 权益翻倍后每笔仍按初始资金的 1/N 下单，长样本严重低估复利 |
| 杠杆不变式 | 无 | 当前 `cash` 检查恰好隐含 ≤1，但**没有显式断言**，改动时无护栏 |
| settled / unsettled | 无 | 同日退出的现金要**等到下一观察日**才可用（`research_portfolio.py:118-120` 注释自陈）——A 股实际是**卖出资金当日即可买入**，这条过度保守 |
| 盯市新鲜度 | 无 | 持仓票停牌时的估值行为未定义 |
| 默认槽位数 | `max_positions: int = 2` | 见 §2.4：这是 187% 的主要放大器 |

### 2.4 187% 的机制（既有文档只给了现象）

既有实测（`2026-08-dragon-survivorship-and-portfolio-fragility.md`）：信号数 148 → 153（**+3.4%**），逐笔均净 +1.854% → +1.938%（+4.5%），胜率 +0.8%，盈亏比 +0.3%，而**组合全期 34.09% → 97.80%（+187%）**。

机制是三个设计选择叠出来的**路径依赖放大器**：

1. **固定槽位 + 先到先得。** `max_positions` 默认 **2**。入场按 `(entry_date, signal_date, code, index)` 稳定排序后先到先占（`_candidate_sort_key`）。多出来的 5 个信号不是「被平均掉」，而是**改变了此后每一个槽位的占用序列**——一次错位一直传播到样本末尾。
2. **无复利让早期交易权重畸高。** `slot_capital` 静态，但最终 equity 是**乘性**的。早期一次换手改变了后续所有交易的发生时点，而不同时点的行情完全不同。
3. **`exit_notional` 回填 + 槽位互斥。** `allow_same_code_overlap=False`，槽位只在**完全退出后**释放。一笔多持一天就可能挤掉下一个信号。

**这不是收益率差异，是排列差异。** 逐笔口径对排列不敏感（均值就是均值），组合口径对排列极度敏感。所以 **187% 不能读成「组合层更真实所以更敏感」，只能读成「组合层设计得太脆」。**

**修复方向（§2.5 全部覆盖）**：
- 槽位数从 2 提到 ≥10（单槽敏感度大致 ∝ 1/N）；
- 目标权重按**当前 equity** 算而不是静态 slot——同时恢复复利、并让「谁先占到槽」不再决定资金量；
- **报告必须带敏感度带**：同一策略在 `max_positions ∈ {5,10,20}` × 「随机打乱同日候选顺序 ×100」下的 equity 分布，报 **p5 / p50 / p95**。**在这套设计下，单点组合收益没有意义。**

### 2.5 最小可行设计

**四个对象**——多一个都不要，少一个不成立：

```python
# ---- 1) Position：可加仓、可减仓、可部分成交 ----
@dataclass
class Position:
    code: str
    qty: int             # 股数，整手；当前恒 > 0（A 股无融券则不为负）
    cost_basis: float    # 已含买入费用的加权平均成本/股（抄 zipline 口径）
    last_price: float    # 最近一次盯市价（前复权）
    last_date: str       # 盯市日；用来发现「持仓票停牌了」
    opened_on: str       # T+1 判定：opened_on == today 则当日不可卖

    @property
    def market_value(self) -> float:
        return self.qty * self.last_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.last_price - self.cost_basis) * self.qty

# ---- 2) Account：现金与购买力。A 股：股票 T+1，资金 T+0 ----
@dataclass
class Account:
    settled_cash: float
    frozen_cash: float = 0.0   # 已下单未成交冻结（日频撮合下通常为 0）

    @property
    def available(self) -> float:
        return self.settled_cash - self.frozen_cash

# ---- 3) Portfolio：唯一的权益真相来源 ----
@dataclass
class Portfolio:
    account: Account
    positions: dict[str, Position]
    starting_cash: float

    @property
    def positions_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def equity(self) -> float:            # == zipline portfolio_value
        return self.account.settled_cash + self.positions_value

    @property
    def leverage(self) -> float:          # == zipline gross_leverage
        eq = self.equity
        gross = sum(abs(p.market_value) for p in self.positions.values())
        return gross / eq if eq > 0 else 0.0

# ---- 4) Fill：所有现金变动的唯一入口。不许在别处改 cash ----
@dataclass(frozen=True)
class Fill:
    date: str
    code: str
    qty: int              # 买 > 0，卖 < 0
    price: float         # 已含滑点的成交价
    commission: float    # 佣金 + 过户费
    tax: float           # 印花税，仅卖出
    reason: str          # entry / stop_loss / take_profit / hold_expired / rebalance

    @property
    def cash_delta(self) -> float:
        return -(self.qty * self.price) - self.commission - self.tax
```

**八条不变式**——每个交易日收盘后断言一次，失败即抛（不许静默继续）：

```python
def assert_invariants(pf: Portfolio, fills: list[Fill], today: str, tol=1e-6) -> None:
    # I1 现金守恒：现金只能被 Fill 改变。这一条能抓住 90% 的记账 bug
    expected = pf.starting_cash + sum(f.cash_delta for f in fills)
    assert abs(pf.account.settled_cash - expected) < tol, "I1 现金不守恒"

    # I2 可用资金非负：A 股现金账户不许透支
    assert pf.account.available >= -tol, "I2 可用资金为负"

    # I3 持仓整手且为正
    for p in pf.positions.values():
        assert p.qty > 0 and p.qty % 100 == 0, f"I3 {p.code} 持仓 {p.qty} 非法"

    # I4 成本口径：cost_basis 必须已含买入费用，否则未实现盈亏系统性偏高
    for p in pf.positions.values():
        assert p.cost_basis > 0, f"I4 {p.code} 成本基准无效"

    # I5 权益恒等式：equity == 现金 + 盯市市值（不是 + 入场名义额）
    assert abs(pf.equity - (pf.account.settled_cash + pf.positions_value)) < tol, "I5 权益口径错"

    # I6 杠杆闸：A 股现金账户 leverage <= 1
    assert pf.leverage <= 1.0 + tol, f"I6 杠杆 {pf.leverage:.4f} > 1"

    # I7 盯市新鲜度：持仓票当日必须被盯过市；停牌沿用旧价但要计入 stale_marks
    for p in pf.positions.values():
        assert p.last_date == today or p.code in stale_marks, f"I7 {p.code} 未盯市"

    # I8 T+1：当日买入的持仓不得出现在当日卖出 Fill 中
    todays_buys = {f.code for f in fills if f.date == today and f.qty > 0}
    todays_sells = {f.code for f in fills if f.date == today and f.qty < 0}
    assert not (todays_buys & todays_sells), "I8 违反 T+1"
```

**日频事件循环**（顺序本身是契约，不许调换）：

```python
def run(signals, ranks, panels, calendar, cfg) -> PortfolioResult:
    pf = Portfolio(Account(cfg.initial_capital), {}, cfg.initial_capital)
    fills, curve = [], []

    for today in calendar:
        # 1. 盯市：先更新所有持仓 last_price，再算任何依赖 equity 的东西。
        #    停牌（volume == 0）沿用 last_price 并计入 stale_marks 诊断。
        mark_to_market(pf, panels, today)
        equity_open = pf.equity

        # 2. 平仓：止损 / 止盈 / 到期。先释放资金，再谈开仓。
        for p in list(pf.positions.values()):
            if p.opened_on == today:               # T+1
                continue
            reason = exit_reason(p, panels, today, cfg)
            if reason and can_sell(p.code, panels, today):  # 一字跌停卖不出 -> 顺延
                fills.append(execute(pf, p.code, -p.qty, panels, today, reason, cfg))

        # 3. 目标权重：用 equity_open，不用当前 cash。
        #    用 cash 会让「先处理的腿」拿到更多资金 —— 那正是 §2.4 的病根。
        targets = allocate(signals, ranks, today, equity_open, cfg)

        # 4. 开仓：逐笔过 涨停闸 -> 成交量闸 -> 资金闸。
        for code, target_value in targets:
            if code in pf.positions and not cfg.allow_add:
                continue
            if is_one_word_limit_up(code, panels, today):   # 一字板买不进
                continue
            qty = size_order(code, target_value, panels, today,
                             pf.account.available, cfg)      # 见 §3.6
            if qty > 0:
                fills.append(execute(pf, code, qty, panels, today, "entry", cfg))

        # 5. 记账 + 校验
        assert_invariants(pf, fills, today)
        curve.append(DailySnapshot(today, pf.equity, pf.account.settled_cash,
                                   pf.positions_value, pf.leverage,
                                   len(pf.positions)))

    return PortfolioResult(curve=curve, fills=fills, config=cfg)
```

**与既有代码的关系**：这套东西**不替换** `src/backtest/application/engine.py`（信号级逐笔引擎继续回答「这个战法本身有没有 alpha」），而是**替换** `research_portfolio.py` 的 `analyze_portfolio`。交界面从「`list[Trade]`（已含预算收益率）」改成「信号矩阵 + 行情面板」——**这是必须的破坏性改动**，因为缺陷 ② 的根因就长在那个交界面上。

**验收标准**：同一批信号，新旧两套跑出的**已实现盈亏总额**在成本口径一致时应相等（±1e-6）；而 **equity 曲线和 max_drawdown 必然不同**——新的回撤会更深，那才是对的。如果新回撤没有变深，说明盯市没接上。

---

## 3. 成交与滑点模型（核心之二）

### 3.1 zipline：四个滑点模型 + 三个佣金模型（`src/zipline/finance/`，`P1`）

模块头两个常量，逐字：

```python
DEFAULT_EQUITY_VOLUME_SLIPPAGE_BAR_LIMIT = 0.025
DEFAULT_FUTURE_VOLUME_SLIPPAGE_BAR_LIMIT = 0.05
```

| 模型 | 成交价 | 成交量上限 | 默认参数 |
|---|---|---|---|
| `NoSlippage` | close | 无 | —（测试用） |
| `FixedSlippage(spread)` | `close ± spread/2` | **无上限**（docstring 明说「always be filled ... even if the size of the order is greater than the historical volume」） | `spread=0.0` |
| `VolumeShareSlippage` | `price ± price_impact × volume_share²` | `volume_limit × bar volume` | `volume_limit=0.025`、`price_impact=0.1` |
| `FixedBasisPointsSlippage` | `price × (1 ± bps × 1e-4)` | `volume_limit × bar volume` | `basis_points=5.0`、**`volume_limit=0.1`** |
| `VolatilityVolumeShare`（期货） | `price + price × MI / 10000`，`MI = eta × sigma × sqrt(psi)`，`psi = txn_volume / ADV20` | `volume_limit × bar volume` | `eta` 按品种表，无数据时 `7.5/10000` |

`VolumeShareSlippage.process_order` 的关键三行（`P1`）：

```python
volume_share = min(total_volume / volume, self.volume_limit)
simulated_impact = (volume_share ** 2
                    * math.copysign(self.price_impact, order.direction) * price)
impacted_price = price + simulated_impact
```

**`FixedBasisPointsSlippage` 的 docstring 明写它是 zipline 当前 equity 的默认模型**：「This class, default-constructed, is zipline's default slippage model for equities.」

佣金侧（`commission.py`，`P1`）：`DEFAULT_PER_SHARE_COST = 0.001`（每股 0.1 美分，`PerShare` 是 equity 默认）、`DEFAULT_PER_DOLLAR_COST = 0.0015`、`DEFAULT_PER_CONTRACT_COST = 0.85`、`DEFAULT_MINIMUM_COST_PER_EQUITY_TRADE = 0.0`。`calculate_per_unit_commission` 处理「最低佣金 + 多次部分成交」的摊分逻辑——**部分成交存在，佣金就必须能摊**，这是 §3.6 要抄的点。

### 3.2 Lean：`FillModel` / `SlippageModel` / `FeeModel` 三分（`P1`）

Lean 把 zipline 揉在一起的东西拆成三个可插拔接口。`VolumeShareSlippageModel`（`Common/Orders/Slippage/VolumeShareSlippageModel.cs`）逐字：

```csharp
public VolumeShareSlippageModel(decimal volumeLimit = 0.025m, decimal priceImpact = 0.1m)
...
var volumeShare = Math.Min(order.AbsoluteQuantity / barVolume, _volumeLimit);
slippagePercent = volumeShare * volumeShare * _priceImpact;
return slippagePercent * lastData.Value;
```

**与 zipline 逐字相同的 0.025 / 0.1**——这一点在 §3.4 有用。

⚠ **一个反直觉的发现**：**Lean 的 `EquityFillModel` 并不按成交量截断成交数量。** `Common/Orders/Fills/EquityFillModel.cs` 里两处逐字写着：

```csharp
// assume the order completely filled
// TODO: Add separate DepthLimited fill partial order quantities based on tick quantity / bar.Volume available.
fill.FillQuantity = order.Quantity;
fill.Status = OrderStatus.Filled;
```

即：**Lean 的成交量约束只体现在滑点的价格上，不体现在成交数量上**（至少在这条路径上）。zipline 在这一点上比 Lean 严格——它会 `raise LiquidityExceeded()` 并把残量留到下一 bar。**抄的时候要抄 zipline，不要抄 Lean。**

### 3.3 backtrader：`filler` 可插拔（`backtrader/fillers.py`，`P1`）

```python
class FixedBarPerc:
    params = (('perc', 100.0),)
    def __call__(self, order, price, ago):
        maxsize = (order.data.volume[ago] * self.p.perc) // 100
        return min(maxsize, abs(order.executed.remsize))
```

另有 `FixedSize`（绝对股数上限）与 `BarPointPerc`（把 bar 的成交量按 `minmov` 在 high–low 区间**均匀分配**到每个价位，只取该价位那一份）。`BarPointPerc` 这个思路对 A 股涨停板有启发（§3.6 末）。默认 `filler=None` 时**一次全额成交**。

### 3.4 zipline 默认 2.5% 是怎么来的：诚实回答

**一手结论：源码与 docstring 里没有任何推导或文献依据。** 全部可查到的只有：

1. 常量定义 `DEFAULT_EQUITY_VOLUME_SLIPPAGE_BAR_LIMIT = 0.025`（无注释、无引用）；
2. docstring 复述该值：「Maximum percent of historical volume that can fill in each bar. 0.5 means 50% of historical volume. 1.0 means 100%. **Default is 0.025 (i.e., 2.5%)**」。

**没有找到任何一手文献把 2.5% 推导出来**（标 `✗`）。能给的三条旁证如下，它们共同指向「这是 Quantopian 传下来的行业惯例常量，不是从市场微观结构模型算出来的」：

| 旁证 | 内容 | 说明什么 |
|---|---|---|
| Lean 独立实现同一组数字 | `VolumeShareSlippageModel(volumeLimit = 0.025m, priceImpact = 0.1m)` | 两个互不相关的代码库用了逐字相同的 0.025/0.1 —— 典型的**惯例继承**（两者都源自 Quantopian 时代的行业共识），不是各自独立推导 |
| **同一个库内部自相矛盾** | zipline 的 `VolumeShareSlippage` 用 **2.5%**，而它当前的**默认** equity 模型 `FixedBasisPointsSlippage` 用 **10%** | 如果 2.5% 有理论依据，同一个库不会在默认模型里用 4 倍的值。**这条最有力**：它证明该参数是「保守程度旋钮」而非「估计量」 |
| 期货取 5%、`price_impact` 取 0.1 | `DEFAULT_FUTURE_VOLUME_SLIPPAGE_BAR_LIMIT = 0.05` | 都是整齐的圆整数，无小数位——估计量不会长这样 |

**给我们的结论**：不要把 2.5% 当成「正确值」引进来，要把它当成**一个必须做敏感性扫描的旋钮**。真正需要写进文档的是「在 X% 假设下结论成立、在 Y% 下不成立」，而不是「我们用了行业标准的 2.5%」。

### 3.5 对 A 股小盘股的影响：一手实测，结论与直觉相反（`P3`）

只读 `market.db`（`mode=ro`），窗口 **2026-07-29 ~ 2026-08-25 共 20 个交易日**，`instruments.instrument_type='STOCK'` 且 `amount>0 and volume>0`，**110,650 个股票-日**：

```text
  p1   daily amount =        6170622 CNY   2.5% cap =       154266 CNY
  p5   daily amount =       16518288 CNY 2.5% cap =       412957 CNY
  p10  daily amount =       24229568 CNY   2.5% cap =     605739 CNY
  p25  daily amount =    44957727 CNY   2.5% cap =      1123943 CNY
  p50  daily amount =108542160 CNY   2.5% cap =      2713554 CNY
  p75  daily amount =      309888512 CNY   2.5% cap =      7747213 CNY
  p90  daily amount =      862146173 CNY   2.5% cap =     21553654 CNY
  p99  daily amount =     5045260000 CNY   2.5% cap =    126131500 CNY

  slot    100000 CNY ->  0.39% of stock-days cannot absorb it at 2.5% cap ;  0.01% at 10% cap
  slot200000 CNY ->  1.59% of stock-days cannot absorb it at 2.5% cap ;  0.07% at 10% cap
  slot    500000 CNY ->  7.05% of stock-days cannot absorb it at 2.5% cap ;  0.65% at 10% cap
  slot   1000000 CNY -> 21.76% of stock-days cannot absorb it at 2.5% cap ;  2.27% at 10% cap
amount==close*volume (synthetic) share: 85972 / 110650 = 77.70%
```

**这组数字部分证伪了「成交量约束是我们的大缺口」这个预设。** 四条读法：

1. **在当前资金规模下，2.5% 约束几乎不咬人。** `PortfolioResearchConfig` 默认 `initial_capital=200_000`、`max_positions=2` → 单槽 10 万。10 万在 2.5% 上限下只有 **0.39%** 的股票-日装不下。**加上成交量闸，现有回测数字几乎不会变。**
2. **它是「扩容闸」不是「历史订正」。** 到单槽 100 万时跳到 **21.76%**——也就是说，**这道闸的价值在于「有人把资金调大时自动报警」，不在于修正已有结论**。应该按这个定位实现：默认开启、命中即计数并在报告里显式披露 `volume_capped_fills`，而不是当成一项精度改进来宣传。
3. **A 股流动性对散户量级而言很充裕。** 最不活跃的 1% 股票-日也有 617 万成交额；中位数 1.085 亿。这跟美股小盘股的情形完全不同——直接照搬美股的流动性焦虑是错配。
4. ⚠ **但全日成交量对涨停股是错的分母。** 我们的战法主打涨停 / 连板，而涨停价上的**可成交量**跟全日成交额没有稳定关系（一字板全日成交额可能很大，但你在涨停价上排不到队）。**现有引擎里的「一字板买不进」判据（`_one_word_masks`）反而比成交量占比更贴近真实约束。** 结论：成交量闸要加，但**不要指望它能替代涨停可得性建模**——那是另一个缺口，且本机无分钟线/无盘口，暂时无解。

⚠ 另一个必须披露的数据质量事实：该窗口内 **77.70% 的 `amount` 满足 `amount == close × volume`**，即由收盘价乘量合成（腾讯源不返回成交额，`TencentAdapter.meta` 已自报 `amount` 为 `estimated_fields`）。比 `2026-08-tail-1450-next-day-touch-backtest.md` 记录的全窗口 97.82% 有改善，但仍占多数。**对「成交量上限」这个用途影响有限**（`close × volume` 是换手金额的合理代理），但**对任何 VWAP 类计算仍然致命**。

### 3.6 最小可行成交模型

```python
def size_order(code, target_value, panels, today, available_cash, cfg) -> int:
    """返回可成交股数（整手）。三道闸串联，顺序固定：涨停 -> 成交量 -> 资金。"""
    px = fill_price(code, panels, today, side="buy", cfg=cfg)
    if not (px > 0):
        return 0

    # 闸 1：涨停可得性（已有 _one_word_masks，直接复用）
    #       调用方在 run() 里已挡掉一字板；这里只做二次保险
    # 闸 2：成交量上限 —— zipline 口径，但分母用 amount 更稳（volume 单位在本库不统一）
    bar_amount = panels["amount"][today, code]           # 元
    max_notional = cfg.volume_limit * bar_amount         # cfg.volume_limit 默认 0.025
    # 闸 3：可用资金
    notional = min(target_value, max_notional, available_cash / (1 + cfg.buy_fee_rate))
    qty = int(notional // px // cfg.lot_size) * cfg.lot_size
    if notional < target_value - 1e-6:
        cfg.diagnostics["volume_capped_fills"] += 1      # 必须计数并在报告里披露
    return max(qty, 0)


def fill_price(code, panels, today, side, cfg) -> float:
    """A 股日频：固定 bps + 可选成交量平方冲击。两者都要可关。"""
    base = panels[cfg.entry_price_field][today, code]    # open / close，由 entry_timing 决定
    sign = +1.0 if side == "buy" else -1.0
    px = base * (1.0 + sign * cfg.slippage_bps * 1e-4)
    if cfg.price_impact > 0.0:                           # 默认 0.0 = 关闭
        share = min(cfg.pending_notional / max(panels["amount"][today, code], 1.0),
                            cfg.volume_limit)
        px *= 1.0 + sign * cfg.price_impact * share ** 2
    return px


def trade_costs(qty, price, side, cfg) -> tuple[float, float]:
    """A 股真实费用结构。印花税单边，过户费沪深已统一双边计收。"""
    notional = abs(qty) * price
    commission = max(notional * cfg.commission_bps * 1e-4, cfg.min_commission)  # 万三 / 最低 5 元
    transfer   = notional * cfg.transfer_bps * 1e-4                               # 过户费
    tax        = notional * cfg.stamp_duty_bps * 1e-4 if side == "sell" else 0.0  # 千一，仅卖出
    return commission + transfer, tax
```

**相对现状（`BacktestConfig.round_trip_cost_pct()` 返回一个与订单规模、成交量、波动率全部无关的**常数** `(3×2 + 10 + 5×2)/100 = 0.26%`）的三点改进**：

| 改进 | 为什么 |
|---|---|
| **最低佣金** `min_commission`（券商普遍 5 元） | 单槽 10 万时万三 = 30 元，最低佣金不咬；但**小额测试或高 `max_positions` 时会咬**。zipline 的 `calculate_per_unit_commission` 专门处理这件事，说明它在实盘里是真问题 |
| **费用与 qty 挂钩、不是与收益率挂钩** | 现状把成本折成收益率百分点扣掉，等价于假设「成本正比于名义额」。加了最低佣金后这个假设就不成立了，必须按笔算 |
| `volume_capped_fills` **计数并披露** | 见 §3.5 第 2 条：这道闸的价值是扩容报警，不披露就等于没加 |

**不要做的**：不要在日频引擎里实现 `BarPointPerc` 那种「把 bar 成交量按价位均分」的模型。它需要 bar 内价量分布，本机日线只有 OHLCV 五个数——实现出来是**给假设穿一件精确的外衣**。

---

## 4. 公司行为与交易日历

### 4.1 zipline 怎么处理分红送转（`src/zipline/finance/ledger.py`，`P1`）

`PositionTracker` 用**三个方法 + 两个待付队列**处理，关键是**除权日与派发日分离**：

```python
def handle_splits(self, splits):
    """返回碎股产生的剩余现金 —— 拆股不是简单乘一个比例。"""
    total_leftover_cash = 0
    for asset, ratio in splits:
        if asset in self.positions:
            leftover_cash = self.positions[asset].handle_split(asset, ratio)
            total_leftover_cash += leftover_cash
    return total_leftover_cash

def earn_dividends(self, cash_dividends, stock_dividends):
    """在 ex_date 记账「应收」，按 pay_date 入队，此时不动现金。"""
    for cash_dividend in cash_dividends:
        div_owed = self.positions[cash_dividend.asset].earn_dividend(cash_dividend)
        self._unpaid_dividends.setdefault(cash_dividend.pay_date, []).append(div_owed)

def pay_dividends(self, next_trading_day):
    """到 pay_date 才真正加现金 / 加股数。"""
    net_cash_payment = 0.0
    for payment in self._unpaid_dividends.pop(next_trading_day, []):
        net_cash_payment += payment["amount"]
    for sp in self._unpaid_stock_dividends.pop(next_trading_day, []):
        position = self.positions.setdefault(sp["payment_asset"], Position(sp["payment_asset"]))
        position.amount += sp["share_count"]
    return net_cash_payment
```

三条值得抄的口径：

1. **除权日（`ex_date`）与派发日（`pay_date`）分开。** 除权日股价掉下来但现金还没到账，中间这段时间**账户权益是真的少了一块**。用「前复权价直接算收益」的做法会把这段抹平。
2. **拆股会产生碎股剩余现金**（`handle_split` 返回 `leftover_cash`）。A 股送转同样有零碎股折现问题。
3. **股票股利会给一个原本不持有的标的建仓**（`self.positions[payment_asset] = Position(payment_asset)`）——A 股「转送其他证券」少见，但可转债转股是同构问题。

**我们的现状**：`adjust_factors` 表 4.2 MB（上游 dbstat），`kline` 工具支持 `adjust=qfq`，`2026-08-tail-1450-next-day-touch-backtest.md` 记录的口径是「**收益用前复权价，涨停 / 一字 / 价格下限判定用不复权价**」——这个拆分是对的，比很多开源实现都清醒。**但组合层完全没有现金分红入账**：前复权把分红折进价格，所以逐笔收益率是对的；可一旦 §2.5 引入真实 `Position` 与 `cash`，就必须显式决定分红走价格还是走现金——**两者同时做就是重复计数**。

**判定**：§2.5 的组合层**统一用前复权价盯市，不单独记分红现金流**，并在配置里写死这一条。理由：本机 `adjust_factors` 只有因子、没有分红金额与 pay_date 明细，做不了 zipline 那套两阶段派发；混合口径的风险远大于精度收益。

### 4.2 `exchange_calendars`：只有 XSHG，没有 XSHE（`P1`）

实读仓库文件树：`exchange_calendars/` 下有 `exchange_calendar_xshg.py`（14,758 字节），**没有 `exchange_calendar_xshe.py`**。`calendar_utils.py` 的注册表里也只有 `"XSHG": XSHGExchangeCalendar`，别名表只有 `"SSE": "XSHG"`。**深交所（XSHE / SZSE）在这个库里不存在。**

`XSHGExchangeCalendar` 类定义逐字（`P1`）：

```python
class XSHGExchangeCalendar(PrecomputedExchangeCalendar):
    """
    Exchange calendar for the Shanghai Stock Exchange (XSHG, XSSC, SSE).
    Open time: 9:30 Asia/Shanghai
    Lunch break: 11:30 - 13:00 Asia/Shanghai
    Close time: 15:00 Asia/Shanghai

    Due to the complexity around the Shanghai exchange holidays, we are
    hardcoding a list of holidays covering 1999-2026, inclusive. There are
    no known early closes or late opens.
    """
    name = "XSHG"
    tz = ZoneInfo("Asia/Shanghai")
    open_times        = ((None, time(9, 30)),)
    break_start_times = ((None, time(11, 30)),)
    break_end_times   = ((None, time(13, 0)),)
    close_times       = ((None, time(15, 0)),)

    @classmethod
    def bound_min(cls) -> pd.Timestamp:
        return pd.Timestamp("1990-12-03")
```

**对「是否含 A 股半天 / 临时休市」的直接回答**：

| 问题 | 答案 | 依据 |
|---|---|---|
| 含半天（early close）吗？ | **不含。** docstring 逐字：「There are **no known early closes or late opens**」 | `P1` |
| 含临时休市吗？ | **不含机制**。它是 `PrecomputedExchangeCalendar`，只有一张硬编码假日数组；临时停市要等上游发版补进数组 | `P1` |
| 覆盖到哪一年？ | 假日数组最后一条是 **2026-10-07**，注释引用上交所 2026 年安排公告。即**只到 2026 年底，2027 需要升级包** | `P1` |
| 有午休吗？ | 有，11:30–13:00 建模为 break | `P1` |
| 收盘集合竞价（14:57–15:00）？ | **未建模**，`close_times` 只有 15:00 一个点 | `P1` |

`pandas_market_calendars` 侧：`calendar_registry.py` 里有 `from .calendars.sse import SSEExchangeCalendar`，并且 `from .calendars.mirror import *` 会把 `exchange_calendars` 的全部日历再镜像一遍。所以它同样**没有独立的深交所日历**。

### 4.3 我们的 `trading_calendar`（`P1`，本仓源码）

```sql
-- src/market/infrastructure/store_schema.py:74-78
CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date  TEXT PRIMARY KEY,
    updated_at  TEXT NOT NULL
) WITHOUT ROWID;
```

0.4 MB（上游 dbstat）。填充方式有两条路径（`store_rw.py`）：随日 K 写入时 `INSERT ... ON CONFLICT DO NOTHING`，以及重建时 `INSERT ... SELECT DISTINCT trade_date FROM quotes_daily`。**即：我们的交易日定义是「这天有行情数据」。**

### 4.4 判定：不换，加一道只读对账闸

**不换的四条理由**：

1. **我们的定义在「半天 / 临时休市」上反而更强。** 「有行情＝交易日」天然吸收所有临时安排；而 `exchange_calendars` 的 XSHG **明说不含 early close**。在这个具体维度上换过去是**降级**。
2. **没有 XSHE。** 深市要么复用 XSHG（假设两所日历相同，通常成立但无保证），要么自己维护——那就回到了原点。
3. **precomputed 只到 2026 年底**，每年升包。对一个离线桌面应用是新增的年度运维负担与断网风险。
4. **`trading_calendar` 被深度依赖**：`_rows_for_date`（四条 tape lane 的公共取数入口）、`data_quality._check_last_day`、`store_hot` 热库窗口、`sentinel_evidence`、`turnover_repair`、`paper_quant_support` 的交易日判定。替换面太大，收益不成比例。

**但我们的定义有一个方向明确的风险**，而且本仓自己已经写下来了：`sync_spot.py` 注释逐字——「不声明交易日的源（东财现价表没有日期列）只能由本地补今天，落在工作日的法定节假日会把昨天的收盘快照写成当日 K 线，还会往 `trading_calendar` 插一个假交易日（T+N 复盘、回测持有期、会话闸门会跟着整体错位一天）」。

也就是说：**我们的日历可能多出假交易日（同步 bug），也可能漏掉真交易日（同步失败）。两个方向都会静默污染回测。**

**最小闸门**（只读、不改写、不引入运行时依赖）：

```python
def audit_calendar(store, start: str, end: str) -> dict:
    """离线对账。exchange_calendars 只作 dev 依赖，不进运行时。"""
    import exchange_calendars as xcals
    xshg = xcals.get_calendar("XSHG")
    ref = {d.strftime("%Y-%m-%d")
           for d in xshg.sessions_in_range(start, end)}
    ours = {r[0] for r in store.conn.execute(
        "SELECT trade_date FROM trading_calendar WHERE trade_date BETWEEN ? AND ?",
        (start, end))}
    return {
        "phantom": sorted(ours - ref),  # 我们有、交易所没有 -> 假交易日，同步 bug
        "missing": sorted(ref - ours),  # 交易所有、我们没有 -> 同步失败或数据缺口
        "ref_bound_max": "2026-12-31",  # XSHG 预计算上界，越界结果不可信
    }
```

**用法**：放进 `data_quality` 做周期体检，`phantom` 非空 → `block`（假交易日会污染 T+N 口径）；`missing` 非空 → `warn`（可能只是当天数据没同步）。**不要把它接进热路径**，也不要让 `exchange_calendars` 进 `requirements.txt` 主依赖——只做 dev/诊断依赖，且必须处理「超出 2026 上界」的情况。

---

## 5. 绩效与稳健性评估（核心之三）

### 5.1 指标口径：empyrical 是事实标准（`P1`）

`pyfolio-reloaded` 与 `quantstats` 的指标层都建立在 `empyrical`（现维护版 `empyrical-reloaded`）之上。常量逐字（`src/empyrical/periods.py`）：

```python
APPROX_BDAYS_PER_MONTH = 21
APPROX_BDAYS_PER_YEAR  = 252
MONTHS_PER_YEAR = 12; WEEKS_PER_YEAR = 52; QTRS_PER_YEAR = 4
ANNUALIZATION_FACTORS = {DAILY: 252, WEEKLY: 52, MONTHLY: 12, QUARTERLY: 4, YEARLY: 1}
```

| 指标 | empyrical 口径 | 我们有吗 |
|---|---|---|
| 年化收益 | `annual_return`，docstring：「the mean annual growth rate ... **equivalent to the compound annual growth rate**」；`cagr` 是它的别名 | ✗ |
| 年化波动 | `annual_volatility(returns, period=DAILY, alpha=2.0)`，`alpha` 是范数阶 | ✗ |
| Sharpe | `sharpe_ratio(returns, risk_free=0, period=DAILY, annualization=None)`，按 `ANNUALIZATION_FACTORS[period]` 年化 | ✗ |
| Sortino | `sortino_ratio(returns, required_return=0, ...)`，分母是 `downside_risk(returns, required_return, ...)`——**注意阈值是 `required_return` 不是 0**，两者不等价 | ✗ |
| Calmar | `calmar_ratio` = 年化收益 / \|最大回撤\| | ✗ |
| 最大回撤 | `max_drawdown(returns)`，作用在**收益率序列**上 | △ 有，但作用在错误的曲线上（§2.3 缺陷 ①） |
| Omega | `return_threshold = (1 + required_return) ** (1 / annualization) - 1` | ✗ |
| Alpha / Beta | `alpha_beta(returns, factor_returns, risk_free, period)`，OLS 口径 | ✗（见下） |
| 换手率 | empyrical 不提供，`pyfolio` 在 `txn` 层算 | △ 组合层有 `turnover_notional` / `turnover_ratio` |

**我们的 `metrics.py` 现状**：`trades / win_rate / avg_gross_return / avg_net_return / median / std / total / best / worst / expectancy / profit_factor / payoff_ratio / avg_win / avg_loss / avg_mfe / avg_mae / avg_hold_days / 连胜连亏 / exit_reasons / percentiles / 直方图 / by_month / by_year / sample_confidence`，外加 `avg_alpha` 与 `alpha_win_rate`。

**根因只有一条：我们没有周期收益率序列。** Sharpe / Sortino / Calmar / 年化 **全部**定义在等间隔的周期收益序列上，而我们只有「每笔交易的收益率」——**笔与笔之间既不等长也不连续，在它上面算 Sharpe 在数学上没有定义**。所以：

> **§5.1 的缺口不是「少写了几个函数」，而是 §2.5 那条日频 equity 曲线的下游后果。做完 §2.5，这一节大部分是十几行代码；不做 §2.5，这一节根本无法开始。**

⚠ 另需订正一处口径：我们的 `avg_alpha` = `mean(net_return_pct − benchmark_return_pct)`，即「同持有窗口内相对基准买入持有的超额」。**这不是 Jensen's alpha**（没有 β 调整），在报告里应改称「超额收益」或 `excess_vs_benchmark`，避免与 empyrical 的 `alpha` 混淆。

### 5.2 现状：`optimize` 只有一句话（`P1`，本仓源码）

`src/ops/application/jobs/optimize.py` 三重嵌套扫 `holds × targets × stops`，默认 `4 × 4 × 3 = 48` 组，最后返回：

```python
"warning": (
    "这是在同一段历史上反复试参数，天然存在过拟合风险。"
    "换一段区间重跑一次，若最优组合完全不同，说明它只拟合了噪声。"
),
```

**这句话本身是对的，但 PBO 论文恰好证明了它不够。** 论文原文（`P1`）：

> The hold-out method does not take into account the number of trials attempted before selecting a particular strategy configuration, and consequently **holdout cannot correctly assess a backtest's representativeness**. ... If we apply the holdout method enough times (say 20 times for a 95% confidence level), false positives are no longer unlikely: **They are expected**.

更要命的是**每轮扫描的原始数据当场被丢掉**：`optimize` 的 `rows` 只保留 `trades / win_rate / avg_net_return / avg_alpha / exit_reasons` 等**标量**，48 条 trial 各自的**收益率时间序列全部不落库**。而 DSR 需要 `V[{ŜR}]` 与 `N`，PBO 需要完整的 `(T × N)` 矩阵 `M`。**所以现在既算不了 DSR 也算不了 PBO——这是数据问题，不是算法问题。** 这就是 §0.1 把「结果零持久化」排在第一优先级的原因。

### 5.3 记号

| 符号 | 含义 |
|---|---|
| `ŜR` | 选中策略的样本 Sharpe（**非年化**，与 `T` 同频率） |
| `T` | 收益观测数（日频 5 年 = 1250） |
| `γ̂₃`, `γ̂₄` | 选中策略收益的**偏度**与**峰度**（`γ̂₄` 是原始峰度，正态 = 3） |
| `N` | **独立**试验次数 |
| `V[{ŜR}]` | 所有试验 Sharpe 估计值的**方差** |
| `Z[ ]`, `Z⁻¹[ ]` | 标准正态 CDF 与其反函数 |
| `γ` | Euler–Mascheroni 常数 ≈ 0.5772156649 |

### 5.4 Deflated Sharpe Ratio（DSR）

**一手出处**：David H. Bailey & Marcos López de Prado, *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality*, **Journal of Portfolio Management**, Vol. 40, No. 5 (2014), pp. 94–107。First version 2014-04-15，this version 2014-07-31。SSRN: <http://ssrn.com/abstract=2460551>；作者自存 PDF：<https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf>（`P1`，本轮全文读完）。

**第一步 —— 多重检验下 Sharpe 最大值的期望**（论文 Eq. 1 / Appendix A.1 Eq. 6）：

```text
E[max{ŜR_n}] ≈ E[{ŜR}] + √V[{ŜR}]   ( (1 − γ) Z⁻¹(1 − 1/N) + γ Z⁻¹(1 − 1/(N e)) )
                └──────────────────────────────────────┘
               极值理论给出的「纯运气最大值」
```

论文 Appendix A.2 的 Snippet 1 逐字给了实现，可作交叉校验（`P1`）：

```python
def getExpMaxSR(mu, sigma, numTrials):
    # Compute the expected maximum Sharpe ratio (Analytically)
    emc = 0.5772156649  # Euler-Mascheroni constant
    maxZ = (1 - emc) * ss.norm.ppf(1 - 1./numTrials) \
         + emc * ss.norm.ppf(1 - 1./(numTrials * np.e))
    return mu + sigma * maxZ
```

**第二步 —— 用它作为 PSR 的拒绝阈值**（论文 Eq. 2）。零假设 `E[{ŜR}] = 0` 下取 `SR₀ = √V[{ŜR}]   ((1−γ)Z⁻¹(1−1/N) + γZ⁻¹(1−1/(N e)))`，则

```text
    ⎡      (ŜR − SR₀)   √(T − 1)      ⎤
DSR = PSR(SR₀) = Z⎢ ───────────────────────────────── ⎥
         ⎢  √( 1 − γ̂₃ ŜR + (γ̂₄ − 1)/4   ŜR² ) ⎥
           ⎣           ⎦
```

分母就是 Probabilistic Sharpe Ratio 的标准误项（Bailey & López de Prado 2012a）：**左偏（γ̂₃ < 0）会让分母变大 → DSR 变小**；**厚尾（γ̂₄ > 3）同理**。这正是论文强调的「两个膨胀源要一起修正」。

**第三步 —— M 个相关试验折算成 N 个独立试验**（Appendix A.3）。论文原话：「using `M` instead of `N` will overstate `E[max{SR}]`」。给出的路径是先求加权平均相关 `ρ̂`（把相关阵所有非对角元替换成常数 `ρ̂` 而保持二次型不变，即 `ρ̂ = (Σ_{i,j} c_ij − M) / (M² − M)`），再在两个端点之间插值：`ρ̂ → 0` 时 `N̂ → M`，`ρ̂ → 1` 时 `N̂ → 1`。⚠ **PDF 该段的公式表在文本转换中损坏，端点条件可辨、闭式插值式不可辨**；论文同时警告 `M > T` 时相关阵病态、`ρ̂` 本身会过拟合，并建议改用信息论（total correlation / multiinformation）估 `N̂`。**本文只承诺端点条件，不杜撰闭式；见 §5.7 的工程折中。**

**数值验证（`P3`，三处全中）**：论文 §「A NUMERICAL EXAMPLE」给了 `ŜR = 2.5`（年化）、`T = 1250`、每年 250 个观测、`V[{ŜR}] = 0.5`、`γ̂₃ = −3`、`γ̂₄ = 10`。我按上式独立实现（Acklam 逆正态 + Abramowitz–Stegun erf）复算：

| 场景 | 论文原文 | 本文复算 |
|---|---|---|
| `N = 100`, 偏度 −3 / 峰度 10 | 「there is only a **90%** chance that the true SR is greater than zero」 | `SR₀(年化) = 1.7894`，**DSR = 0.9004** ✓ |
| `N = 46`, 同上 | 「DSR would have been **0.9505**, above the 95% confidence level」 | `SR₀(年化) = 1.5869`，**DSR = 0.9505** ✓ |
| `N = 88`, 正态收益（偏度 0 / 峰度 3） | 「DSR ≈ **0.95** after N=88 independent trials」 | `SR₀(年化) = 1.7574`，**DSR = 0.9505** ✓ |

三处独立命中 → **上面写的公式与论文一致，可以直接照抄实现。**

### 5.5 Probability of Backtest Overfitting（PBO / CSCV）

**一手出处**：David H. Bailey, Jonathan M. Borwein, Marcos López de Prado, Qiji Jim Zhu, *The Probability of Backtest Overfitting*, dated **February 27, 2015 (revised February 2015)**；发表于 *Journal of Computational Finance*。SSRN: <http://ssrn.com/abstract=2326253>（补充测试案例：<http://ssrn.com/abstract=2568435>）；作者自存 PDF：<https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf>（`P1`，本轮全文读完）。

**定义**（论文 Definition 2.2，逐字转写）：

```text
PBO = Σ_{n=1}^{N}  Prob[ r̄_n < N/2 | r ∈ Ω_n ]   Prob[ r ∈ Ω_n ]
```

其中 `r` / `r̄` 分别是 N 个配置在 IS / OOS 上的**排名向量**，`Ω_n = { f ∈ Ω | f_n = N }` 即「第 n 个配置在 IS 排第一」的事件。白话：**「IS 最优的那个配置，在 OOS 掉到中位数以下」的概率。**

**CSCV 算法**（论文 Algorithm 2.3，七步）：

```text
1. 构造 M：(T × N) 实值矩阵。列 = 一个参数配置(trial)，行 = 同步的收益观测。
   两条硬条件：(i) 每列行数相同、跨列逐行同步；
      (ii) 绩效指标必须能在每列的子样本上计算。

2. 按行把 M 切成 S 个不相交、等长的子块 M_s（S 取偶数），每块 (T/S × N)。

3. 取所有 C(S, S/2) 种「选一半作训练」的组合。S=16 -> 12,780 种。

4. 对每个组合 c：
   a) J  = 选中的 S/2 块按原顺序拼接        -> 训练集 (T/2 × N)
   b) J̄ = J 在 M 中的补集，同样按原顺序    -> 测试集 (T/2 × N)
   c) R^c  = 各列在 J  上的绩效向量；r^c  = 其排名
   d) R̄^c = 各列在 J̄ 上的绩效向量；r̄^c = 其排名
   e) n* = argmax_n r^c_n      -> IS 最优配置
   f) ω_c = r̄^c_{n*} / (N + 1)  ∈ (0, 1)     -> 该配置的 OOS 相对排名
   g) logit_c = ln( ω_c / (1 − ω_c) )

5. f(λ) = logit 的经验分布；PBO = φ = ∫_{−∞}^{0} f(λ) dλ
        = logit ≤ 0 的比例 = 「IS 最优在 OOS 落到中位数以下」的频率
```

**门禁阈值有论文原文背书**（`P1`）：

> In accordance with standard applications of the Neyman-Pearson framework, **a customary approach would be to reject models for which PBO is estimated to be greater than 0.05**.

**`S` 怎么选**（论文 §4，`P1`）：`S` 太小则 logit 分布左尾表征不足；`S` 太大则时间结构被打碎。论文给的建议与算例：`S = 16` → 12,780 个 logit，`σ[f(λ)] < 0.0045`，95% 置信下估计误差 < 0.01；若 `M` 含 4 年日频数据，`S = 16` 恰好是季度分块，序列相关结构得以保留。**论文结论：「we believe that S = 16 is a reasonable value to use in most cases.」** 另需 `N >> 10`，否则 `ω_c` 取值太离散。

**PBO 之外，同一套 CSCV 免费给三个诊断**（论文 §3）：

| 诊断 | 算法 | 判读 |
|---|---|---|
| **performance degradation** | 对所有 `c` 回归 `R̄^c_{n*} = α + β R^c_{n*} + ε` | `β` 显著为负 = 追求 IS 最优反而有害 |
| **probability of loss** | `Prob[R̄^c_{n*} < 0]` | 论文警告：**即使 `φ ≈ 0`，这一项也可能很高**——那说明策略差，但不是因为过拟合 |
| **stochastic dominance** | 比较 `R̄_{n*}` 与 `Mean(R̄)` 的 CDF | 若不占优 = 「按 IS 挑」还不如随机挑 |

论文自己的两个算例：一个 PBO = 74%（`SR_IS ∈ [1,3]` 但 78% 的 `SR_OOS` 为负），一个 PBO = 0.04%。**「`SR_IS` 高」本身不携带任何信息**——论文原话：「backtests with high Sharpe ratios tell us nothing regarding the representativeness of that result」。

### 5.6 先修数据：trial 矩阵必须落库

现有表（`src/ops/infrastructure/store_schema.py:112-120`，`P1`）：

```sql
CREATE TABLE IF NOT EXISTS strategy_backtests (
    slug          TEXT NOT NULL,
    version       TEXT NOT NULL,
    metrics_json  TEXT NOT NULL DEFAULT '{}',
    ...
);
```

**它只能存一个聚合 JSON，装不下 `(T × N)` 的 `M`。** 且上游 dbstat 实测 **0 行**——连聚合都没在存。最小新增：

```sql
-- 一次参数扫描 = 一个 sweep；trial 的收益序列必须逐行落库，否则 PBO 无解。
CREATE TABLE IF NOT EXISTS backtest_sweeps (
    sweep_id      TEXT PRIMARY KEY,
    slug          TEXT NOT NULL,
    version       TEXT NOT NULL,
    params_space  TEXT NOT NULL,   -- JSON：被扫的参数网格定义
    universe_hash TEXT NOT NULL,   -- 票池 + 区间 + 数据快照的 hash，保证可复现
    start_date    TEXT NOT NULL,
    end_date      TEXT NOT NULL,
    n_trials      INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_trials (
    sweep_id      TEXT NOT NULL,
    trial_idx     INTEGER NOT NULL,   -- 0..N-1，即 M 的列号
    params_json   TEXT NOT NULL,
    sharpe        REAL,                  -- 冗余存一份，省得每次重算 V[{SR}]
    PRIMARY KEY (sweep_id, trial_idx)
);

-- M 本体。行 = 交易日，列 = trial。用长表存，SQLite 上比宽表好维护。
CREATE TABLE IF NOT EXISTS backtest_trial_returns (
    sweep_id      TEXT NOT NULL,
    trial_idx     INTEGER NOT NULL,
    trade_date    TEXT NOT NULL,
    ret           REAL NOT NULL,   -- 该 trial 当日的组合收益率（来自 §2.5 的 equity 曲线）
    PRIMARY KEY (sweep_id, trial_idx, trade_date)
) WITHOUT ROWID;
```

**体量估算**：`optimize` 默认 48 组 × 1,358 个交易日 = **65,184 行**/次扫描，约 2–3 MB。相对 `market.db` 的 5,740 MB（其中溯源审计已占 44.8%）可以忽略。**没有任何理由不存。**

⚠ 一条硬约束：`ret` 必须来自 **§2.5 的日频 equity 曲线**。用现在那条「逐笔收益率拼起来」的序列会同时违反 CSCV 的两个前置条件（跨列逐行同步、子样本上可算指标）——**不同 trial 的成交日期不同，逐笔序列根本对不齐行。**

### 5.7 免 scipy 的最小实现

本仓无 scipy（§0.2 实测），标准正态 CDF 用 `math.erf`（stdlib），逆 CDF 用 Acklam 有理逼近（绝对误差 < 1.15e-9，对门禁足够）：

```python
import math
from itertools import combinations

EMC = 0.5772156649015329  # Euler-Mascheroni

def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

def norm_ppf(p: float) -> float:
    """Acklam 逆正态。scipy.stats.norm.ppf 的替代，无外部依赖。"""
    a = (-3.969683028665376e+01,  2.209460984245205e+02, -2.759285104469687e+02,
          1.383577518672690e+02, -3.066479806614716e+01,  2.506628277459239e+00)
    b = (-5.447609879822406e+01,  1.615858368580409e+02, -1.556989798598866e+02,
          6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00,  4.374664141464968e+00,  2.938163982698783e+00)
    d = ( 7.784695709041462e-03,  3.224671290700398e-01,  2.445134137142996e+00,
          3.754408661907416e+00)
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    if p <= 1.0 - pl:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
             ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)


def expected_max_sr(var_sr: float, n_trials: int, mean_sr: float = 0.0) -> float:
    """Bailey & Lopez de Prado (2014) Eq.(1)/(6)。n_trials 必须是【独立】试验数。"""
    if n_trials < 2:
        return mean_sr
    z = ((1.0 - EMC) * norm_ppf(1.0 - 1.0 / n_trials)
         + EMC * norm_ppf(1.0 - 1.0 / (n_trials * math.e)))
    return mean_sr + math.sqrt(var_sr) * z


def deflated_sharpe(sr_hat, var_sr, n_trials, T, skew, kurt) -> float:
    """DSR。所有 Sharpe 必须同频率（都非年化，或都年化 —— 不能混）。"""
    sr0 = expected_max_sr(var_sr, n_trials, 0.0)           # H0: E[SR] = 0
    denom = math.sqrt(max(1e-12,
              1.0 - skew * sr_hat + (kurt - 1.0) / 4.0 * sr_hat ** 2))
    return norm_cdf((sr_hat - sr0) * math.sqrt(T - 1) / denom)


def pbo_cscv(M, S: int = 16, perf=None) -> dict:
    """Bailey/Borwein/Lopez de Prado/Zhu (2015) Algorithm 2.3。
    M: list[list[float]]，形状 (T, N)，行同步。perf: 作用在收益子序列上的绩效函数。
    返回 pbo / logits / 退化斜率 / OOS 亏损概率。"""
    perf = perf or _sharpe
    T, N = len(M), len(M[0])
    assert S % 2 == 0 and T >= S and N > 10, "S 需偶数；N 需 >> 10（论文 §4）"
    block = T // S
    blocks = [list(range(i * block, (i + 1) * block)) for i in range(S)]

    logits, pairs = [], []
    for combo in combinations(range(S), S // 2):
        tr_rows = [r for b in combo for r in blocks[b]]                      # J
        te_rows = [r for b in range(S) if b not in combo for r in blocks[b]]  # J-bar
        R  = [perf([M[t][n] for t in tr_rows]) for n in range(N)]
        Rb = [perf([M[t][n] for t in te_rows]) for n in range(N)]
        n_star = max(range(N), key=lambda n: R[n])           # 步骤 e
        # r̄ 的排名：1 = 最差，N = 最好
        rank_oos = 1 + sorted(range(N), key=lambda n: Rb[n]).index(n_star)
        w = rank_oos / (N + 1.0)            # 步骤 f，落在 (0,1)
        w = min(max(w, 1e-12), 1 - 1e-12)
        logits.append(math.log(w / (1.0 - w))) # 步骤 g
        pairs.append((R[n_star], Rb[n_star]))

    pbo = sum(1 for x in logits if x <= 0.0) / len(logits)   # 步骤 5
    # performance degradation：OOS 对 IS 的 OLS 斜率，期望为负
    mx = sum(p[0] for p in pairs) / len(pairs)
    my = sum(p[1] for p in pairs) / len(pairs)
    sxx = sum((p[0]-mx)**2 for p in pairs) or 1e-12
    beta = sum((p[0]-mx)*(p[1]-my) for p in pairs) / sxx
    return {
        "pbo": pbo,
        "n_logits": len(logits),
        "degradation_beta": beta,
        "prob_oos_loss": sum(1 for p in pairs if p[1] < 0) / len(pairs),
    }
```

**`N̂`（独立试验数）的工程折中。** §5.4 说了闭式插值式在 PDF 里不可辨、且论文自己警告 `ρ̂` 会过拟合。**不要杜撰公式。** 落地建议按保守度分三档，并**在报告里显式写出用了哪一档**：

| 档 | `N̂` 取值 | 何时用 |
|---|---|---|
| 保守（默认） | `N̂ = M`（全部试验按独立算） | 让 `SR₀` 偏高 → DSR 偏低 → **门禁偏严**。默认选它 |
| 折中 | `N̂ = M   (1 − ρ̂)`，端点满足论文的 `ρ̂→0 ⇒ N̂→M`、`ρ̂→1 ⇒ N̂→1`（近似；`ρ̂` 由 trial 收益序列的相关阵均值估） | 网格维度间明显冗余（如 `stop ∈ {−5,−5.5,−6}`）时 |
| 严格 | 按论文建议改用信息论估计 | 本轮未实现，不建议先做 |

### 5.8 把它变成门禁

```python
GATE = {
    "pbo_max": 0.05,             # 论文原文推荐的拒绝线
    "dsr_min": 0.95,             # = PSR 的 95% 置信
    "degradation_beta_max": 0.0, # 斜率显著为负则拒
    "min_trials": 12,            # N 太小时 DSR/PBO 都不稳；直接标 insufficient
    "min_obs": 512,              # T 太短时 S=16 的每块不足 32 个观测
}

def gate(sweep) -> dict:
    M, sr_list = load_trial_matrix(sweep), load_trial_sharpes(sweep)
    if len(sr_list) < GATE["min_trials"] or len(M) < GATE["min_obs"]:
        return {"verdict": "insufficient", "reason": "试验数或观测数不足，不出结论"}
    best = argmax(sr_list)
    var_sr = variance(sr_list)
    dsr = deflated_sharpe(sr_hat=sr_list[best], var_sr=var_sr,
                         n_trials=len(sr_list),       # 保守档：N̂ = M
                         T=len(M), skew=skew_of(M, best), kurt=kurt_of(M, best))
    res = pbo_cscv(M, S=16)
    passed = (res["pbo"] <= GATE["pbo_max"]
               and dsr >= GATE["dsr_min"]
               and res["degradation_beta"] <= GATE["degradation_beta_max"])
    return {"verdict": "pass" if passed else "reject", "dsr": dsr, **res,
            "n_trials_declared": len(sr_list)}
```

**三条落地纪律**（前两条比代码重要）：

1. **`N` 必须诚实申报。** DSR 论文的核心论点就是这个：「a backtest where the researcher has not controlled for the extent of the search involved in his or her finding is **worthless**, regardless of how excellent the reported performance might be」。如果研究员先手工试了 200 组再跑 `optimize` 的 48 组，`N` 是 248 不是 48。**`backtest_sweeps` 应该按 `(slug, universe_hash)` 累计历史试验数，而不是每次归零。**
2. **门禁只能拒绝，不能替代 OOS。** PBO 论文明说 CSCV「avoid[s] the credibility issue of preserving a truly out-of-sample test-set by not requiring a fixed hold-out」——它是 hold-out 的补充诊断，不是替代品。现有 `evaluate_train_oos` 的 `execution_isolated=False` 与 `not_strict_reason` 自陈机制要保留。
3. **`prob_oos_loss` 要和 `pbo` 一起报。** 论文明确警告：「even if φ ≈ 0, Prob[R̄ < 0] could be high, in which case the strategy's performance OOS is poor **for reasons other than overfitting**」。只报 PBO 会把「没过拟合但就是不赚钱」误判成通过。

### 5.9 walk-forward / purged K-fold / CPCV 的关系

| 方法 | 它防什么 | 它不防什么 | 本轮证据 |
|---|---|---|---|
| hold-out / walk-forward | 时序泄漏 | **多重检验**（PBO 论文用整节论证，见 §5.2 引文） | `P1` |
| K-fold CV | 估计误差方差 | 时序泄漏 + 多重检验。PBO 论文原话：`k` 必须够小才能让每折的 Sharpe 可信，但 `k` 小了「K-FCV will essentially reduce to a hold-out method」 | `P1` |
| **purged K-fold + embargo** | 标签重叠导致的训练/测试泄漏 | 多重检验 | ✗ **本轮未取到 López de Prado, *Advances in Financial Machine Learning* (2018) Ch.7 原文**，不引具体页码与代码清单。`mlfinlab` 的开源实现亦未核验 |
| **CSCV / PBO** | **多重检验下的选择偏差** | 时序泄漏（⚠ 见下） | `P1` |
| **DSR** | 多重检验 + 非正态 + 短样本 | 时序泄漏 | `P1` |

⚠ **一个必须点出的细节：论文里的 CSCV 不含 purging。** Algorithm 2.3 按连续块切分并互换 IS/OOS，但**没有在训练/测试边界剔除标签重叠的样本**。对我们影响多大取决于持有期：`BacktestConfig.hold_days` 默认 3、`optimize` 扫 `{1,2,3,5}`，即标签重叠窗口 ≤ 5 天，而 `S=16` 在 1,358 个交易日上每块约 85 天。**泄漏面 ≤ 6%，且可以用一行 embargo 消掉**：

```python
# 在 pbo_cscv 步骤 4b 之后加一行：把测试集里紧邻训练块的前 h 天剔除
te_rows = [t for t in te_rows if all(abs(t - x) > cfg.hold_days for x in boundary_rows)]
```

**优先级判断**：先做 DSR + PBO（§5.7 的代码今天就能跑，唯一前置是 §5.6 落库），purged K-fold / CPCV 等有真正的 ML 模型（而不是网格扫参）时再说。**我们现在没有需要 purging 的东西——网格扫参不训练模型。**

---

## 6. 多空 / 中性与基准

### 6.1 这些框架怎么做中性化

**zipline 是唯一把它做成一等公民的**（`src/zipline/pipeline/factors/factor.py`，`P1`）。`Factor` 上有一组签名高度一致的方法，全部接受 `mask`（排除哪些样本）与 `groupby`（按什么分组）：

| 方法 | 签名 | 用途 |
|---|---|---|
| `demean` | `demean(mask=NotSpecified, groupby=NotSpecified)` | 减组均值 → **截面 / 行业中性** |
| `zscore` | `zscore(mask=..., groupby=...)` | 组内标准化 |
| `rank` | `rank(method='ordinal', ascending=True, mask=..., groupby=...)` | 组内排名 |
| `winsorize` | `winsorize(min_percentile, max_percentile, mask=..., groupby=...)` | 组内缩尾 |
| `top` / `bottom` | `top(N, mask=..., groupby=...)` | **每组各取 N 只** → 行业均衡选股 |
| `quantiles` / `quintiles` / `deciles` | `quantiles(bins, mask=...)` | 产出 `Classifier`，可再喂给上面任何一个的 `groupby` |

`groupby` 接受的是 `Classifier`。**关键设计：市值中性不是一个单独的 API，而是「先把市值分成十档得到一个 `Classifier`，再把它当 `groupby` 传进去」**——`quantiles()` 的返回类型就是 `Classifier`，这条链是闭合的。所以：

```python
# 行业中性：按行业分组减均值
neutral = my_factor.demean(groupby=Sector())
# 市值中性：先把市值分十档，再按档分组
neutral = my_factor.demean(groupby=MarketCap().deciles())
# 行业 × 市值双中性 + 去极值 + 排除极端样本
clean = (my_factor
         .winsorize(0.01, 0.99, groupby=Sector())
         .zscore(groupby=Sector(), mask=my_factor.percentile_between(1, 99)))
# 行业均衡多空：每个行业各取头尾 5 只
longs  = my_factor.top(5, groupby=Sector())
shorts = my_factor.bottom(5, groupby=Sector())
```

底层实现只有两行（§1.1 已引）：`demean(row) = row - nanmean(row)`；分组由 `GroupedRowTransform` 负责，`groupby is NotSpecified` 时退化成 `Everything(mask=mask)`，即「全市场一个组」。

**其余各家**：`bt` 用 Algo 栈（`SelectAll` → `WeighEqually` / `WeighInvVol` → `Rebalance`）做组合构造，中性化要自己在因子层做；Lean 有 `PortfolioConstructionModel` 但没有截面中性原语；backtrader / Backtesting.py **本质是单标的框架**（Backtesting.py 的 `Backtest.__init__` 只接受一个 OHLC `DataFrame`），做不了截面。vectorbt 的中性化就是 pandas 的 `groupby().transform()`，不是框架能力。

### 6.2 我们的「日内截面中性化」处在什么水平

`2026-08-tail-1450-next-day-touch-backtest.md` §6 的口径逐字：「把每笔收益减去**当日全池均值**，剩下的才是横截面 alpha」。

**准确定位：这正好等于 zipline 的 `demean()` 在 `groupby=NotSpecified`、`mask=NotSpecified` 时的行为**——即 `GroupedRowTransform` 退化成 `Everything()` 的那一档。**方法本身是对的、是国际口径的最低有效档，但只有最低档。**

不过我们**多做了一件 zipline 没有的事**：「波动率匹配对照」——按 ATR% 十分位把池子基准**重新加权**成该臂的波动率结构，只有超过这条线的部分才算 alpha。这在效果上接近「以 ATR 十分位为 `groupby` 的 demean」，**比纯 `demean()` 强**。而且它当场产生了价值：该文 §6 的表里六个原始均净都不错的组合，日中性一分就分出「真选股」（`rsi6≤60` 系，+0.209%）和「只是踩对大盘」（`breadth≥55` 系，−0.354%）两类。

**缺的三样**：

| 缺什么 | 现状 | 代价 |
|---|---|---|
| **行业中性** | 无 | 「选出来的是不是just一个行业 beta」无法回答。而 `instruments.industry` **本地已有**（`instruments` 表 0.5 MB） |
| **市值中性** | 无（只有波动率匹配） | 小盘因子和 alpha 分不开——对 A 股尤其致命，市值是最强的单因子 |
| **`mask`（排除极端样本）** | 无 | 全池均值被 ST、次新、一字板样本污染 |

### 6.3 升级路径：三行

因为已经有了「减当日均值」的框架，加 `groupby` 是**改一个聚合键**，不是重写：

```python
# 现状：日中性 = 减当日全池均值
day_mean = df.groupby("trade_date")["ret"].transform("mean")
df["neutral_ret"] = df["ret"] - day_mean

# 升级 1（行业中性）：instruments.industry 本地已有，改一个 key
grp = df.groupby(["trade_date", "industry"])["ret"].transform("mean")
df["neutral_ret"] = df["ret"] - grp

# 升级 2（行业 × 市值双中性）：先分档，再进 key —— 抄 zipline 的 quantiles() 思路
df["cap_decile"] = (df.groupby("trade_date")["circ_market_cap"]
                      .transform(lambda s: pd.qcut(s, 10, labels=False, duplicates="drop")))
grp = df.groupby(["trade_date", "industry", "cap_decile"])["ret"].transform("mean")
df["neutral_ret"] = df["ret"] - grp
```

⚠ **两条不能省的注意**：

1. **分组细了样本会碎。** 全市场约 5,500 只 × 30+ 个行业 × 10 个市值档 = 每组平均不到 20 只，尾部组只有个位数，组均值噪声会盖过 alpha。**建议：先只做行业中性（组内 ~180 只），双中性只在样本量够时做，并强制 `min_group_size` 门槛（组内 < 20 只则回退到上一级分组）。**
2. **别把中性化当成组合构造。** 「日中性均净为正」只说明**因子有截面信息**，不等于**这个组合能赚钱**——后者要走 §2.5 的组合层。这两件事在本仓过去的文档里偶有混用。

---

## 7. 判定汇总

| 主题 | 主流做法 | 我们 | 判定 | 优先级 |
|---|---|---|---|---|
| 引擎范式 | 事件驱动（zipline/backtrader/nautilus/Lean）vs 向量化（vectorbt） | 向量化 + 逐笔评估 | **不换。** 做「向量化选股 + 事件驱动组合层」两段式（§1.4） | — |
| 组合账户 | `Portfolio`/`Account`/`Position` 三件套 + 盯市 | `equity = cash + Σ 入场名义额`，无 Position、无未实现盈亏 | **重写 `analyze_portfolio`。** 四对象 + 八不变式（§2.5） | **P0** |
| 结果持久化 | —（各家假设你自己存） | `strategy_backtests` 0 行，且 schema 只存聚合 JSON | **新增 `backtest_sweeps` / `backtest_trials` / `backtest_trial_returns`**（§5.6） | **P0（阻断 DSR/PBO）** |
| 成交与滑点 | 滑点 / 佣金 / 成交量上限三分，`volume_limit` 默认 2.5%（zipline & Lean 同值） | 固定 26bps 常数，无成交量约束 | **加成交量闸 + 最低佣金**，但定位为**扩容报警**而非精度修正（§3.5 实测只影响 0.39%） | P2 |
| 过拟合门禁 | DSR（Bailey & LdP 2014）/ PBO（Bailey et al. 2015） | 一句 warning 字符串 | **落地 §5.7 代码 + §5.8 门禁**，`pbo ≤ 0.05`、`dsr ≥ 0.95` | **P0（在 P0 持久化之后）** |
| 绩效口径 | empyrical（252 日年化） | 只有逐笔统计，无年化 / Sharpe / Sortino / Calmar | **§2.5 做完后补**（十几行）；`avg_alpha` 改名为 `excess_vs_benchmark` | P1 |
| 公司行为 | zipline `ex_date` / `pay_date` 两阶段 | 前复权价 + 不复权判涨停（口径已正确） | **不改。** 明确写死「组合层统一用前复权盯市、不单记分红现金流」（§4.1） | P3 |
| 交易日历 | `exchange_calendars` XSHG（**无 XSHE**、**无 early close**、预计算至 2026） | 自建 `trading_calendar`，从行情反推 | **不换。** 加 `audit_calendar` 只读对账闸，`phantom` → block（§4.4） | P3 |
| 截面中性化 | zipline `demean/zscore/rank/winsorize/top(groupby=)` | 减当日全池均值 + 波动率匹配对照 | **加行业中性**（`instruments.industry` 已有），改一个聚合键（§6.3） | P2 |

---

## 8. 诚实边界

1. **§1.3 的 24× 是自测下界，不是文献值。** 事件循环被刻意剥光（无 Order 对象 / 无事件分发 / 无 ledger / 槽位满即 break），合成数据的数值分布也不等于真实 A 股。**vectorbt 官方 README 只给定性说法（「turning hours of grid search into seconds」），未提供可复核基准**，故本文未引用任何第三方性能数字。
2. **§2.5 / §3.6 / §5.7 的代码是设计稿，未在本仓运行过。** 只有 §5.7 的 DSR 部分经过独立数值验证（对论文算例三处全中，用的是等价的 JS 实现而非上面那段 Python）。**`pbo_cscv` 未跑过任何数据**——`C(16,8) = 12,870` 次组合 × N 列的绩效计算在纯 Python 下可能是分钟级，落地时需要向量化，本文未做这一步。
3. **DSR 的 `N̂`（相关试验折算独立试验）没有给闭式。** 论文 Appendix A.3 的公式表在 PDF 文本转换中损坏，**只有端点条件可辨**；本文明确拒绝杜撰插值式，改给 §5.7 的三档工程折中。要精确实现必须回到 SSRN 原始排版或期刊版。
4. **purged K-fold / embargo / CPCV 本轮没有一手来源。** López de Prado, *Advances in Financial Machine Learning* (2018) Ch.7 与 `mlfinlab` 实现**均未取到原文**，§5.9 只写了它与 CSCV 的关系（这部分来自 PBO 论文本身），未给公式与页码。
5. **zipline 默认 2.5% 找不到一手推导依据**（§3.4 标 `✗`）。给出的三条旁证只能支持「这是惯例常量」，不能支持「这个值适合 A 股」。
6. **§3.5 的成交量实测只覆盖 20 个交易日**（2026-07-29 ~ 2026-08-25，110,650 个股票-日），是当前市况的截面，不是全历史。且该窗口 **77.70% 的 `amount` 是 `close × volume` 合成的**。结论「当前资金规模下约束不咬人」对牛市高换手期成立，**熊市缩量期需要重测**。
7. **§3.5 明确指出全日成交量对涨停股是错的分母。** 我们的战法主打涨停 / 连板，涨停价上的可成交量与全日成交额无稳定关系。**这个缺口本文没有解**——本机无分钟线、无盘口，暂时无解。
8. **Lean 的 `EquityFillModel` 不做成交量截断这一条，只核验了 `EquityFillModel.cs` 里两处 `TODO: Add separate DepthLimited fill...`**，未通读 Lean 全部 fill 路径（`FillModel.cs` 基类、期权 / 期货专用模型未读）。结论应限定为「至少在该文件的 tick / quote 分支上如此」。
9. **未评估的东西**：nautilus_trader 只读了 README（`P2`），未读源码；`bt` 的 README.rst 抓取失败（grep 无匹配），§6.1 关于它的描述属**背景知识而非本轮核验**，应视为 `✗`；`quantstats` / `pyfolio-reloaded` 只通过 empyrical 间接核验，未读其自身实现。
10. **存活偏差没有被本文解决，而且比想象的更硬。** 上游 dbstat 实测：`instruments.delist_date` 填充数 **= 0**，`status` 分布 `delisted=1 / normal=5546`。**退市票的行情根本没进库**——本文所有关于「组合层最小设计」的讨论都建立在一个幸存者票池上。§2.5 做完之后，equity 曲线会更准确，但**仍然是幸存者的 equity 曲线**。

---

## 附：一句话给用户

**别换引擎**：7.0 亿 bar-asset-combo 向量化实测 9.5 秒，事件驱动至少慢 24 倍。坑在信号之后，按序补：**① 结果落库**（`strategy_backtests` 0 行且只存聚合 JSON，PBO 算不出）；**② 组合层重写**（`equity = 现金 + 入场名义额`，未实现盈亏恒为 0，旧文「回撤 −37%」量的是已实现盈亏，187% 是 2 槽位的排列敏感）；**③ DSR/PBO 门禁**（已按论文算例验证，`pbo ≤ 0.05` 有原文背书，不需 scipy）。成交量约束可缓：10 万/槽只影响 0.39% 股票-日。
