"""组合风控：在选股结果被写入候选池前，检查是否违反集中度约束。

总额度与单战法槽位超限只记警告，不丢弃标的（满仓不丢弃）。
行业集中度超限同样只警告。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PortfolioLimits:
    max_total_positions: int = 20       # 所有战法合计最大持仓数
    max_positions_per_strategy: int = 5  # 单战法最大持仓
    max_per_industry: float = 0.40      # 单行业占比上限（相对所有活跃候选）
    max_single_stock: float = 0.20      # 单票占比上限


@dataclass
class GuardResult:
    allowed: bool
    violations: list[str]
    allowed_codes: list[str]  # 全部候选代码（超限仅警告，不丢弃）


def check_portfolio_limits(
    new_picks: list[dict],
    existing_core: list[dict],
    limits: PortfolioLimits | None = None,
) -> GuardResult:
    """检查新选股是否违反集中度约束，返回允许写入的代码列表。

    1. existing_core 占用的位置数已计入总额度。
    2. 总额度 / 单战法额度超限只追加警告，仍写入 allowed_codes。
    3. 行业超限仅警告。
    """
    if limits is None:
        limits = PortfolioLimits()

    violations: list[str] = []
    allowed_codes: list[str] = []

    existing_count = len(existing_core)
    remaining_total = limits.max_total_positions - existing_count

    # 统计当前策略已有的持仓数（按 rule_version 字段）
    strategy_counts: dict[str, int] = {}
    for item in existing_core:
        tag = str(item.get("rule_version", item.get("strategy_tag", "unknown")))
        strategy_counts[tag] = strategy_counts.get(tag, 0) + 1

    # 统计行业分布（基础：existing_core 全部 + new_picks 已过关的）
    all_codes_for_industry: list[str] = [
        str(d.get("code", "")) for d in existing_core if d.get("code")
    ]

    for pick in new_picks:
        code = str(pick.get("code", ""))
        strategy = str(pick.get("rule_version", pick.get("strategy_tag", "unknown")))

        # 1. 总额度检查（警告，不丢弃）
        if remaining_total <= 0:
            violations.append(
                f"{code}: 超出总持仓上限 {limits.max_total_positions}（警告，未丢弃）"
            )

        # 2. 单战法额度检查（警告，不丢弃）
        strat_used = strategy_counts.get(strategy, 0)
        if strat_used >= limits.max_positions_per_strategy:
            violations.append(
                f"{code}: 战法 {strategy} 已用 {strat_used}/{limits.max_positions_per_strategy} 个槽位"
                "（警告，未丢弃）"
            )

        allowed_codes.append(code)
        if remaining_total > 0:
            remaining_total -= 1
        strategy_counts[strategy] = strat_used + 1
        all_codes_for_industry.append(code)

    # 3. 行业集中度警告（不丢弃，只 flag）
    # 计算全部候选（existing + allowed new）的行业分布
    all_picks_map: dict[str, dict] = {
        str(d.get("code", "")): d for d in existing_core if d.get("code")
    }
    for pick in new_picks:
        code = str(pick.get("code", ""))
        if code in allowed_codes:
            all_picks_map[code] = pick

    total_with_industry = sum(
        1 for d in all_picks_map.values() if d.get("industry")
    )
    if total_with_industry > 0:
        industry_counts: dict[str, int] = {}
        for d in all_picks_map.values():
            ind = d.get("industry")
            if ind:
                industry_counts[str(ind)] = industry_counts.get(str(ind), 0) + 1
        for ind, cnt in industry_counts.items():
            pct = cnt / total_with_industry
            if pct > limits.max_per_industry:
                violations.append(
                    f"行业 {ind} 占比 {pct:.0%} 超过上限 {limits.max_per_industry:.0%}（警告，未丢弃）"
                )

    return GuardResult(
        allowed=len(violations) == 0,
        violations=violations,
        allowed_codes=allowed_codes,
    )
