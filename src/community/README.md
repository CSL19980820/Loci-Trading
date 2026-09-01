# 社区（community）

策略广场 / 排行榜 / 跟单订阅 / 点赞收藏评论 / 动态流。

## 职责

把「一个人的策略」变成「可被别人看见、比较、复用的东西」，且**不让广场变成荐股引流场**：

| 能力 | 入口 | 一句话 |
|---|---|---|
| 策略广场 | `list_square` / `GET /api/community/strategies` | 排序（hot/new/score/stars）+ 筛选 + 分页 |
| 发布与版本 | `publish_strategy` / `publish_new_version` | 上架跑清单；**上架即冻结**，改内容只能发新版 |
| 排行榜 | `rebuild_leaderboard` / `read_board` | 风险调整分 x 样本外时间折扣，落快照可回看 |
| 跟单订阅 | `subscribe` / `pull_signals` | **只推信号，不自动下单** |
| 互动 | `star` / `clone` / `add_comment` / `follow` | 计数是缓存，明细才是真相 |
| 我的收藏 | `list_starred` / `GET /api/community/me/stars` | 与广场**同形状**的卡片，前端复用同一个组件 |
| 动态流 | `feed` | 全站 / 关注 / 我的三种范围 |

## 边界

- **只写 `data/community.db`**（路径来自 `src.shared.paths.community_db()`，跨租户全局唯一——
  广场是公共空间，不能跟着租户切换分裂成几份互相看不见的榜单）。
- **不写 `palace.db` / `market.db` / `ops.db`**，一行都不写。克隆只返回 bundle，
  导入由客户端在自己那边完成；社区连对方账本在哪都不知道，也不该知道。
- **不存账号**。`Actor` 只有 `user_id` / `display_name` / `is_admin` 三个字段，来自组合根注入的
  `auth_dependency`（identity 上下文）。库里冗余的 `owner_name` / `actor_name` 是**快照**
  （作者改名不回填历史卡片），不是第二份用户表。
- **不产出行情与盈亏**。`strategy_metrics` 是作者/任务喂进来的绩效切片，社区只负责按统一公式
  换算成 `score` 与名次，不自己算收益。
- **不下单**。见下面的合规红线。

### 合规红线：只推信号，不自动下单

`subscriptions.mode` 只有 `signal_only` 一个取值，DDL 里有 `CHECK` 兜底，API schema 里
**根本没有 `mode` 字段**（想传都传不进来）。代客理财 / 全权委托在境内需牌照；本仓是个人工具，
永远不做「订阅后自动在别人账户成交」这件事。订阅者能拿到的只有作者当日的信号快照
（`signal_broadcasts`），下不下单由他自己对着自己的账本决定。

**这不是没做完的 TODO，是刻意不做。** 要加 `auto_trade` 得先改 DDL、改 schema、改 domain 注释，
三处都拦着你。

### 上架即冻结

`published_versions` 上挂了 `BEFORE UPDATE` / `BEFORE DELETE` 触发器，改写已发布版本一律 `ABORT`。
理由：别人克隆走的那一份必须永远可对账，否则「我抄的时候明明不是这个逻辑」永远说不清。
改内容 → 发新版；不想被人看到 → `delist`（数据仍在，只是不在架上）。

## 关键入口

```python
from src.community import (
    CommunityStore,      # 库门面（mixin 组合，每个实现文件 <= 600 行）
    build_community_router,  # 组合根挂载用的路由工厂
    publish_strategy, publish_new_version,   # 发布
    list_square, detail,    # 广场
    rebuild_leaderboard, read_board,         # 榜单
    publish_signals, pull_signals,           # 跟单（只推信号）
    compute_score, rank_entries,           # 评分口径（纯函数）
 check_publish_ready, checklist,          # 上架清单（纯函数）
  EquityPoint, normalize_equity_curve,  # 净值曲线契约（纯函数）
)
```

HTTP 见 [`api/README.md`](api/README.md)。库表清单见
[`infrastructure/schema.py`](infrastructure/schema.py) 的模块 docstring。

### 评分口径（为什么不用裸收益率排序）

```text
score = sharpe_1y * min(1.0, live_days / 365)
```

国内策略平台普遍拿区间收益率直接排名，榜首长期被三类东西占据：**过拟合刷榜**（参数扫到最优的
那条曲线，样本外立刻失效）、**单押高波动**（满仓一只妖股翻倍就能上榜）、**多开小号只推赢的那个**
（幸存者偏差）。裸收益率对风险和样本长度都不敏感，跑三天 +40% 能压过跑三年 +35%。

所以主榜用风险调整收益（治高波动）乘以样本外时间折扣（治刷榜与新号）：`live_days` 是**上架后**
真实存续的天数，不是回测区间长度，不满一年按比例打折。裸收益率被降级为展示字段与一个带高门槛的
副榜（`return` 榜要求 >= 1 年 + >= 30 笔）。实现与理由：[`domain/scoring.py`](domain/scoring.py)。

### 上架清单（机器可校验）

抄 TradingView *House Rules* 与 QuantConnect 提交规范里**能被程序判定**的条款：必须有回测结果、
成交笔数 >= 30、回测区间 >= 1 年、必须声明 `entry_timing`、佣金/印花税/滑点不得为 0、
标题与摘要非空、不得含外部联系方式（微信 / QQ / 手机号 / 非白名单链接）。
返回 `list[RuleViolation]`，一次给全，别让作者改一条提交一次。
实现：[`domain/publish_rules.py`](domain/publish_rules.py)。

### 净值曲线契约（`metrics_json.equity_curve`）

`strategy_metrics` 的列全是标量，净值曲线过去没有落库位置，于是前端在
`metrics_json` / `manifest.backtest` 里按 `equity` / `equity_curve` / `nav` / `curve`
四个名字挨个猜。现在**只有一个位置、一种形状**：

```json
{ "equity_curve": [{"d": "2024-01-02", "v": 1.0}, {"d": "2024-01-03", "v": 1.0234}] }
```

- `d` 是 `YYYY-MM-DD`；`v` 是**归一化净值（起点 1.0）**，不是金额——金额会泄露本金
  规模，也没法把两条曲线叠在一张图上比。
- 点数建议 <= 750（约三年日频），超过由服务端等距降采样，首尾必留。曲线是给人看
  形状的，不是对账凭据。
- 归一唯一实现：`domain/equity_curve.py::normalize_equity_curve(raw) -> list[EquityPoint]`
  （从 `domain.models` re-export；拆文件只是因为 `models.py` 已贴着 600 行上限）。它认
  上面四个历史别名、`{"date","value"}` 之类的近义键、`[date, value]` 二元组与金额序列，
  **认不出来一律返回空列表，绝不抛异常**：历史数据形状不可控，不该因为某条老记录里
  躺着脏数据就让整个广场列表 500。
- 写入口只有一处：`application/leaderboard.py::record_metrics` 落库前归一一次，
  **库里只写 `equity_curve` 键**，别名一律丢弃（留着别名等于留着四份真相）。

### 广场卡片自带绩效

`GET /api/community/strategies` 的每条都带最近一期绩效：既有的 `latest_score` /
`metrics_date` 原样保留（前端在用，**不许改名**），另加一个可为 `null` 的 `metrics`
对象（`sharpe_1y` / `annual_return` / `max_drawdown` / `win_rate` / `profit_factor` /
`trades` / `live_days` / `score` / `as_of_date`）。没跑过绩效的返回 `null` 而不是一堆 0——
0 分和「还没跑过」是两回事。

绩效由 SQL 的 `LEFT JOIN`（相关子查询取 `MAX(as_of_date)`）一次带回，**不在应用层
逐条 `latest_metrics()`**：一页 20 条就是 20 次额外往返，而且前端为了那四个数字曾被迫
再拉两次 `/leaderboard`（overall + rookie 各 200 条）回来拼，没进榜的只能显示「—」。
`strategy_metrics` 的主键就是 `(publish_id, as_of_date)`，子查询是「主键前缀等值 +
后缀取最大」，索引上一次 seek 就够；**改那段 SQL 前先确认那个 PK 还在**。

## 如何扩展

| 想做的事 | 改哪里 | 注意 |
|---|---|---|
| 加一张榜 | `domain/scoring.py::BOARD_RULES` + `models.BOARDS` | 门槛写进 `BoardRule`，别在 application 里塞 if |
| 改评分公式 | 只改 `compute_score` | 落库的 `score` 由 store 现算，改完重跑 `rebuild_leaderboard` 即可 |
| 加一条上架规则 | `publish_rules._check_*` + `checklist()` | 必须能被程序判定；补一条单测断言它真能触发 |
| 加一张表 | `infrastructure/schema.py::_MIGRATIONS` 尾部追加 | 语句自身幂等；不可重建的表要在 docstring 写清 |
| 给卡片加一个绩效字段 | `store_discovery._METRICS_SELECT` + `_card_metrics` | 从 JOIN 里带回来，别在 application 里逐条查 |
| 加一个端点 | `api/strategies_router.py` 或 `api/social_router.py` | 写操作必须 `write_dependency` + `require_actor`；路由里不写业务 |
| 加一种互动 | `infrastructure/store_social.py` + `application/engagement.py` | 计数列同事务更新，并让 `recount_engagement` 能重算 |
| 加通知渠道 | `application/subscribe.py::NOTIFY_CHANNELS` | 渠道只是「推给谁」，**不许**顺手加下单动作 |

单个实现文件超过 600 行就拆 mixin / 拆 router（本上下文已经这么拆了，见
`infrastructure/store.py` 的 docstring）。

## 给 Agent 的用法

- 只从包根导入：`from src.community import CommunityStore, build_community_router`。
  深引 `src.community.infrastructure.*` 会被 `.importlinter` 的 `protect-community-infra` 拦下。
- 组合根装配：

  ```python
  app.include_router(
      build_community_router(
        write_dependency=require_write,   # 会话 / Bearer
  auth_dependency=current_auth,     # 匿名必须返回 None，不要抛 401
     community_db=None,          # None = data/community.db
      )
  )
  ```

  `auth_dependency` 的返回值形状随意（`Actor` / identity 的 `AuthContext` / 用户对象 / 字典 /
  用户 id 字符串），由 `api/deps.py::coerce_actor` 收敛——社区刻意不与身份实现绑死。
- 写操作一律「只能改自己的东西」，admin 例外；看不见的东西一律 **404 而不是 403**
  （403 会泄露「这个 id 确实存在」）。
- 想给策略打分：`record_metrics(...)` 只喂 `sharpe_1y` / `live_days` / `trades` 等原始指标，
  **不要自己算 `score`**——服务端按统一公式现算，传进来的会被忽略。
- 盘后任务：`rebuild_all(store, as_of=None)`，`as_of` 缺省取库里最新一期绩效日，
  凌晨跑也不会算出空榜把昨天的快照挤掉。
- 别在社区里写别人的库：克隆返回 bundle，导入是调用方的事。

## README 维护

改公开导出、端点、表结构、评分公式、上架清单、订阅模式时，**同批**更新本文与
`api/README.md`，否则 DoD 失败。合规红线（只推信号）与「上架即冻结」两段不得删改口径。

## 相关测试

`tests/community/`：

- `test_scoring.py` — 评分公式、时间折扣、榜单门槛、「裸收益率不能上位」的反例
- `test_publish_rules.py` — 上架清单逐条、引流拦截、`ENTRY_TIMINGS` 与 strategy 域的漂移检查
- `test_publishing.py` — 发布 / 发新版 / 版本冻结（触发器）/ 下架 / 可见性 / 克隆 bundle
- `test_engagement.py` — 收藏、克隆、评论软删与权限、关注、动态流、计数校准
- `test_leaderboard.py` — 重算与快照替换、门槛过滤、排序键值 `sort_value`、迁移幂等、订阅拉信号
- `test_square_metrics.py` — 广场卡片带回的最近一期绩效、净值曲线归一、`GET /me/stars`
- `test_api_router.py` — 路由工厂契约、401/403/422 映射、鸭子类型的 `auth_dependency`

```powershell
    \.venv\Scripts\python.exe -m pytest tests/community -q
```
