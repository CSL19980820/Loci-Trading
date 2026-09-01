"""榜单评分口径。

**为什么不用裸收益率排序。**
国内策略平台（含各家「策略广场」「模拟大赛」）普遍拿区间收益率直接排名，结果是可预测的：
榜首长期被三类东西占据——

1. **过拟合刷榜**：参数在历史上扫到最优的一条曲线，样本外立刻失效。收益率不区分
   「赚到的」和「拟合出来的」，而榜单本身给了刷榜的收益（曝光、跟单）。
2. **单押高波动**：满仓一只妖股翻倍就能上榜，风险调整后其实很差。夏普能把这种
   「一次性运气」压回去，裸收益率不能。
3. **新号刷榜**：开一堆号各押不同方向，只把赢的那个推上榜（幸存者偏差）。裸收益率
   对样本长度完全不敏感，跑三天 +40% 就能压过跑三年 +35% 的。

所以本仓的主榜分数是 **风险调整收益 x 样本外时间折扣**：

    score = sharpe_1y * min(1.0, live_days / 365)

- ``sharpe_1y`` 治「单押高波动」：分母是波动，运气型净值曲线拿不到高分。
- ``min(1, live_days/365)`` 治「刷榜」与「新号」：**上架后真实存续的天数**才算数，
  不满一年按比例打折，满一年才拿满分。回测跑得再漂亮，live_days=0 时分数就是 0。

裸收益率没有被删除，只是被降级为**展示字段**（``annual_return``）与一个带门槛的副榜
（``return`` 榜要求 >= 1 年存续、>= 30 笔），主榜永远不看它。

本模块是纯函数：没有 IO、没有随机、不依赖当前时间。同样的输入必须给出同样的排名，
否则榜单快照没法复现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.community.domain.models import (
    BOARDS,
    StrategyMetrics,
    ValidationError,
    as_float,
    as_int,
)

#: 拿满时间折扣所需的存续天数（一年）。
LIVE_DAYS_FULL_CREDIT = 365

#: 分数上下限。夏普再离谱也不让它撑爆榜（多半是净值曲线算错了）。
SCORE_CLAMP = 10.0


def oos_discount(live_days: int | float) -> float:
    """样本外时间折扣 ∈ [0, 1]。

    ``live_days`` 是**上架之后**真实走过的天数，不是回测区间长度——回测区间由
    ``publish_rules`` 卡门槛（≥1 年），折扣卡的是「这套东西公开挂出来之后活了多久」。
    两者混用会让「回测十年、昨天才发」的策略直接拿满分，那正是要防的事。
    """
    days = as_float(live_days)
    if days <= 0:
        return 0.0
    return min(1.0, days / LIVE_DAYS_FULL_CREDIT)


def compute_score(sharpe_1y: float, live_days: int | float) -> float:
    """主榜分数：``sharpe_1y * min(1, live_days/365)``。

    约定：
    - 非数值 / NaN 按 0 处理（宁可不上榜，不可用脏数据排名）。
    - 结果裁剪到 ``±SCORE_CLAMP``，防止异常夏普霸榜。
    - 保留 6 位小数：SQLite 存 REAL，落库与重算必须能对上。
    - 负夏普同样被折扣拉向 0，看起来「新号亏得少」，但它们在榜尾的相对次序不影响
      榜首，而放大新号的亏损也没有意义。
    """
    raw = as_float(sharpe_1y) * oos_discount(live_days)
    clamped = max(-SCORE_CLAMP, min(SCORE_CLAMP, raw))
    return round(clamped, 6)


@dataclass(frozen=True, slots=True)
class BoardRule:
    """一个榜单分区的口径：主排序键 + 参赛门槛。"""

    key: Callable[[StrategyMetrics], float]
    min_trades: int = 0
    min_live_days: int = 0
    max_live_days: int | None = None
    description: str = ""


#: 各榜口径。``overall`` 是主榜，其余是带门槛的副榜。
BOARD_RULES: dict[str, BoardRule] = {
    "overall": BoardRule(
        key=lambda m: m.score,
        min_trades=30,
        min_live_days=7,
        description="风险调整收益 x 样本外时间折扣；主榜",
    ),
    "sharpe": BoardRule(
        key=lambda m: m.sharpe_1y,
        min_trades=30,
        min_live_days=90,
        description="近一年夏普；要求满 90 天存续，防止三天神话",
    ),
    "return": BoardRule(
        key=lambda m: m.annual_return,
        min_trades=30,
        min_live_days=LIVE_DAYS_FULL_CREDIT,
        description="年化收益；**唯一**看裸收益的榜，门槛最高（≥1 年 + ≥30 笔）",
    ),
    "rookie": BoardRule(
        key=lambda m: m.score,
        min_trades=10,
        min_live_days=7,
        max_live_days=LIVE_DAYS_FULL_CREDIT,
        description="新秀榜：存续不足一年的，单独一张榜，不与老策略抢主榜",
    ),
}


def _as_metrics(item: StrategyMetrics | Mapping[str, Any]) -> StrategyMetrics:
    if isinstance(item, StrategyMetrics):
        return item
    if isinstance(item, Mapping):
        return StrategyMetrics.from_row(item)
    raise ValidationError("排名条目必须是 StrategyMetrics 或字典")


def is_eligible(metrics: StrategyMetrics, rule: BoardRule) -> bool:
    """是否够格进这张榜。门槛不满足的直接不出现，而不是排在后面。"""
    if as_int(metrics.trades) < rule.min_trades:
        return False
    days = as_int(metrics.live_days)
    if days < rule.min_live_days:
        return False
    if rule.max_live_days is not None and days >= rule.max_live_days:
        return False
    return True


def rank_entries(
    entries: Iterable[StrategyMetrics | Mapping[str, Any]],
    *,
    board: str = "overall",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """把绩效切片排成一张榜。

    返回 ``[{"rank": 1, "publish_id": ..., "score": ..., "value": ..., "metrics": {...}}]``。

    - ``score`` 一律是**主榜分数**（便于跨榜比较），``value`` 才是本榜的排序键值。
    - 排序键相同时依次比 ``live_days``（活得久的在前）与 ``publish_id``（字典序），
      保证同样输入永远得到同样的榜——榜单要落快照，随机次序等于没法复盘。
    - 不满足门槛的条目直接被过滤掉。
    """
    if board not in BOARD_RULES:
        raise ValidationError(f"未知榜单：{board}（可选 {', '.join(sorted(BOARD_RULES))}）")
    rule = BOARD_RULES[board]
    pool: list[StrategyMetrics] = []
    for item in entries:
        metrics = _as_metrics(item)
        if metrics.publish_id and is_eligible(metrics, rule):
            pool.append(metrics)
    pool.sort(key=lambda m: (-as_float(rule.key(m)), -as_int(m.live_days), m.publish_id))
    if limit is not None and limit >= 0:
        pool = pool[:limit]
    ranked: list[dict[str, Any]] = []
    for index, metrics in enumerate(pool, start=1):
        ranked.append(
            {
                "rank": index,
                "publish_id": metrics.publish_id,
                "board": board,
                "as_of_date": metrics.as_of_date,
                "score": round(as_float(metrics.score), 6),
                "value": round(as_float(rule.key(metrics)), 6),
                "metrics": metrics.to_dict(),
            }
        )
    return ranked


def describe_boards() -> list[dict[str, Any]]:
    """给前端/Agent 看的榜单口径说明。"""
    rows: list[dict[str, Any]] = []
    for name in BOARDS:
        rule = BOARD_RULES[name]
        rows.append(
            {
                "board": name,
                "description": rule.description,
                "min_trades": rule.min_trades,
                "min_live_days": rule.min_live_days,
                "max_live_days": rule.max_live_days,
            }
        )
    return rows


def recompute_scores(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """按当前口径重算一批 metrics 行的 ``score``（落库前统一走这里）。"""
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["score"] = compute_score(data.get("sharpe_1y"), data.get("live_days"))
        out.append(data)
    return out
