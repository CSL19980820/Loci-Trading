"""选股信号重叠：多战法同日推同一批票 = 假分散。

成交 / 持仓没有战法字段，本模块**不假装**算仓位风险；它回答的是：
「你同时跑的几套选股，信号是不是高度撞车？」

口径：
- 数据源：``candidate_reviews`` 且 ``tier='core'``（真正入选池的票）
- 战法键：``rule_version``（选股落库时的战法标识）
- 日均 Jaccard：同日两边都有票时才比较；平均 ≥0.6 为高重叠
- 附带「常撞代码」：至少同日共现过的票，按共现天数排序，便于人工核对
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.ledger import PalaceStore


@dataclass
class OverlapReport:
    strategy_a: str
    strategy_b: str
    avg_jaccard: float
    days_compared: int
    overlap_level: str  # "low" < 0.3 / "medium" < 0.6 / "high"
    collision_days: int = 0
    shared_code_count: int = 0
    top_shared_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_a": self.strategy_a,
            "strategy_b": self.strategy_b,
            "avg_jaccard": self.avg_jaccard,
            "days_compared": self.days_compared,
            "overlap_level": self.overlap_level,
            "collision_days": self.collision_days,
            "shared_code_count": self.shared_code_count,
            "top_shared_codes": list(self.top_shared_codes),
        }


def compute_overlap(
    palace: PalaceStore,
    days: int = 60,
    *,
    top_n: int = 8,
) -> list[OverlapReport]:
    """计算最近 N 个自然日内各战法两两信号重叠。"""
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    rows = palace.conn.execute(
        """
        SELECT occurred_on, rule_version, code
        FROM candidate_reviews
        WHERE tier = 'core' AND occurred_on >= ?
          AND IFNULL(source, '') NOT LIKE '%backfill%'
          AND IFNULL(source, '') NOT LIKE '%:history'
        ORDER BY occurred_on, rule_version, code
        """,
        (cutoff,),
    ).fetchall()

    day_strategy: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        day = str(row["occurred_on"])
        strat = str(row["rule_version"])
        code = str(row["code"])
        day_strategy.setdefault(day, {}).setdefault(strat, set()).add(code)

    all_strategies: set[str] = set()
    for strats in day_strategy.values():
        all_strategies.update(strats.keys())

    strategies = sorted(all_strategies)
    if len(strategies) < 2:
        return []

    pair_sum: dict[tuple[str, str], float] = {}
    pair_count: dict[tuple[str, str], int] = {}
    pair_collision_days: dict[tuple[str, str], int] = {}
    pair_shared: dict[tuple[str, str], Counter[str]] = {}

    for strats in day_strategy.values():
        for i in range(len(strategies)):
            for j in range(i + 1, len(strategies)):
                a, b = strategies[i], strategies[j]
                set_a = strats.get(a)
                set_b = strats.get(b)
                if not set_a or not set_b:
                    continue
                intersection = set_a & set_b
                union = set_a | set_b
                jaccard = (len(intersection) / len(union)) if union else 0.0
                key = (a, b)
                pair_sum[key] = pair_sum.get(key, 0.0) + jaccard
                pair_count[key] = pair_count.get(key, 0) + 1
                if intersection:
                    pair_collision_days[key] = pair_collision_days.get(key, 0) + 1
                    shared = pair_shared.setdefault(key, Counter())
                    for code in intersection:
                        shared[code] += 1

    results: list[OverlapReport] = []
    for (a, b), total in pair_sum.items():
        n = pair_count[(a, b)]
        avg = round(total / n, 4)
        if avg >= 0.6:
            level = "high"
        elif avg >= 0.3:
            level = "medium"
        else:
            level = "low"
        shared_counter = pair_shared.get((a, b), Counter())
        top_codes = [code for code, _ in shared_counter.most_common(top_n)]
        results.append(
            OverlapReport(
                strategy_a=a,
                strategy_b=b,
                avg_jaccard=avg,
                days_compared=n,
                overlap_level=level,
                collision_days=pair_collision_days.get((a, b), 0),
                shared_code_count=len(shared_counter),
                top_shared_codes=top_codes,
            )
        )

    results.sort(key=lambda r: (r.avg_jaccard, r.collision_days), reverse=True)
    return results
