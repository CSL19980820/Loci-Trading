"""战法重叠度：发现多个战法天天选同一批票。

如果战法A和战法B的日均Jaccard相似度>60%，
你认为自己在分散，实际上是隐性加杠杆。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.palace import PalaceStore


@dataclass
class OverlapReport:
    strategy_a: str
    strategy_b: str
    avg_jaccard: float
    days_compared: int
    overlap_level: str  # "low" < 0.3 / "medium" < 0.6 / "high"


def compute_overlap(palace: PalaceStore, days: int = 60) -> list[OverlapReport]:
    """计算最近 N 天各战法两两 Jaccard 重叠度。"""
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    rows = palace.conn.execute(
        """
        SELECT occurred_on, rule_version, code
        FROM candidate_reviews
        WHERE tier = 'core' AND occurred_on >= ?
        ORDER BY occurred_on, rule_version, code
        """,
        (cutoff,),
    ).fetchall()

    # day -> strategy -> set of codes
    day_strategy: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        day = str(row["occurred_on"])
        strat = str(row["rule_version"])
        code = str(row["code"])
        day_strategy.setdefault(day, {}).setdefault(strat, set()).add(code)

    # collect all strategies
    all_strategies: set[str] = set()
    for strats in day_strategy.values():
        all_strategies.update(strats.keys())

    strategies = sorted(all_strategies)
    if len(strategies) < 2:
        return []

    # accumulate per-pair jaccard sums
    pair_sum: dict[tuple[str, str], float] = {}
    pair_count: dict[tuple[str, str], int] = {}

    for strats in day_strategy.values():
        for i in range(len(strategies)):
            for j in range(i + 1, len(strategies)):
                a, b = strategies[i], strategies[j]
                set_a = strats.get(a)
                set_b = strats.get(b)
                if not set_a or not set_b:
                    continue
                intersection = len(set_a & set_b)
                union = len(set_a | set_b)
                jaccard = intersection / union if union else 0.0
                key = (a, b)
                pair_sum[key] = pair_sum.get(key, 0.0) + jaccard
                pair_count[key] = pair_count.get(key, 0) + 1

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
        results.append(OverlapReport(
            strategy_a=a,
            strategy_b=b,
            avg_jaccard=avg,
            days_compared=n,
            overlap_level=level,
        ))

    results.sort(key=lambda r: r.avg_jaccard, reverse=True)
    return results
