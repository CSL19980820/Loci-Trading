"""数据质量哨兵：在选股之前拦下"看着正常的错数字"。

## 为什么要有阻断式检查

这个项目已经栽过两次同类的跟头，两次都不是崩溃，而是**静默产出错结果**：

1. 每日增量同步的 ``stale_after_days`` 默认 1，意思是"跳过最近 1 天内同步过
   的票"——昨天同步过的今天也被跳过。任务每天照常报 success，实际一行没取。
2. 缺换手率的票，衰减率被 ``nan_to_num`` 当成 0，筹码分布永远停在第一天，
   ``COST`` 返回上市首日附近的价格。合法浮点数，一路流进选股结果。

崩溃你会立刻知道；错数字你可能永远不知道。所以本模块的默认行为是
**阻断**而不是告警：检查不过就拒绝选股，让人当场发现，而不是拿一份
静默错掉的候选池去下单。

## 检查项与阈值

阈值都可覆盖，但默认值刻意偏严：宁可多挡一次让人来看，也不要放过一次。
``severity`` 分 ``block``（阻断选股）与 ``warn``（记录但放行）——只有
真正会让结果错掉的才是 block，比如"今天根本没有数据"；覆盖率略低这种
可能只是停牌，记 warn。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from src.market.store import MarketStore

#: 检查项默认阈值。
DEFAULT_THRESHOLDS: dict[str, float] = {
    # 最新交易日的行情覆盖率下限。低于此值说明同步没跑完或大面积失败。
    "min_coverage_ratio": 0.90,
    # 允许的最大数据滞后交易日数。0 = 必须有当天数据（盘后场景）。
    "max_stale_days": 3,
    # 换手率缺失比例上限。筹码类指标（COST/WINNER）完全依赖它。
    "max_turnover_missing_ratio": 0.05,
    # 复权因子最后更新距今的日历天数上限。超了说明因子表没跟上除权。
    "max_factor_age_days": 30.0,
    # 同步失败的标的数上限。
    "max_failed_codes": 50,
    # 单日成交额为 0 的比例上限（长期停牌之外不该有这么多）。
    "max_zero_amount_ratio": 0.10,
}


@dataclass
class Finding:
    """一条检查结果。"""

    check: str
    severity: str          # "block" | "warn" | "ok"
    message: str
    observed: Any = None
    threshold: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "observed": self.observed,
            "threshold": self.threshold,
        }


@dataclass
class HealthReport:
    """一次完整体检。``blocked`` 为真时调用方必须拒绝选股。"""

    trade_date: str
    findings: list[Finding] = field(default_factory=list)
    checked_at: str = ""

    @property
    def blocked(self) -> bool:
        return any(item.severity == "block" for item in self.findings)

    @property
    def blockers(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "block"]

    @property
    def warnings(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "warn"]

    def reason(self) -> str:
        """给人看的一句话结论，用于任务失败原因与接口 detail。"""
        if not self.blocked:
            count = len(self.warnings)
            return f"数据体检通过（{count} 项提示）" if count else "数据体检通过"
        return "；".join(item.message for item in self.blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "blocked": self.blocked,
            "reason": self.reason(),
            "checked_at": self.checked_at,
            "findings": [item.to_dict() for item in self.findings],
            "block_count": len(self.blockers),
            "warn_count": len(self.warnings),
        }


class DataQualityError(RuntimeError):
    """体检未通过。带上完整报告，便于接口原样透出而不是只给一句话。"""

    def __init__(self, report: HealthReport) -> None:
        super().__init__(report.reason())
        self.report = report


def check_market_health(
    store: MarketStore,
    *,
    trade_date: str | None = None,
    thresholds: dict[str, float] | None = None,
) -> HealthReport:
    """对行情仓做一次体检。不抛异常，把结论交给调用方决定。"""
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    coverage = store.coverage()
    target = trade_date or str(coverage.get("last_date") or "")
    report = HealthReport(
        trade_date=target,
        checked_at=datetime.now().isoformat(timespec="seconds"),
    )

    if not target:
        report.findings.append(
            Finding(
                check="empty_store",
                severity="block",
                message="行情仓是空的，没有任何可用于选股的数据",
            )
        )
        return report

    report.findings.append(_check_staleness(store, coverage, target, limits))
    report.findings.append(_check_coverage(store, target, limits))
    report.findings.append(_check_turnover(store, target, limits))
    report.findings.append(_check_zero_amount(store, target, limits))
    report.findings.append(_check_factor_age(store, limits))
    report.findings.append(_check_failed_codes(coverage, limits))
    # 只保留有话说的项；全 ok 的检查不必占版面。
    report.findings = [item for item in report.findings if item.severity != "ok"]
    return report


def _check_staleness(
    store: MarketStore, coverage: dict[str, Any], target: str, limits: dict[str, float]
) -> Finding:
    """最新数据落后了多少个交易日。

    这是第一个要查的：数据本身是旧的，后面所有覆盖率都好看也没意义。
    """
    last_date = str(coverage.get("last_date") or "")
    if not last_date:
        return Finding("staleness", "block", "行情仓没有任何交易日数据")

    days = store.trading_days()
    if target not in days:
        return Finding(
            "staleness",
            "block",
            f"{target} 不在交易日历中，无法作为选股基准日",
            observed=target,
        )

    lag = len(days) - 1 - days.index(target)
    allowed = int(limits["max_stale_days"])
    if lag > allowed:
        return Finding(
            "staleness",
            "block",
            f"选股基准日 {target} 落后最新交易日 {lag} 个交易日（上限 {allowed}）",
            observed=lag,
            threshold=allowed,
        )
    return Finding("staleness", "ok", f"数据新鲜度正常（落后 {lag} 个交易日）", lag, allowed)


def _check_coverage(store: MarketStore, target: str, limits: dict[str, float]) -> Finding:
    """当日有行情的票 / 在册正常状态的票。

    大面积缺失最常见的成因就是同步任务静默跳过——本项目真实发生过。
    """
    listed = store.conn.execute(
        "SELECT COUNT(*) FROM instruments WHERE status = 'normal'"
    ).fetchone()[0]
    if not listed:
        return Finding(
            "coverage", "warn", "instruments 表没有正常状态的标的，无法计算覆盖率"
        )
    present = store.conn.execute(
        "SELECT COUNT(DISTINCT code) FROM quotes_daily WHERE trade_date = ?", (target,)
    ).fetchone()[0]
    ratio = present / listed
    floor = float(limits["min_coverage_ratio"])
    if ratio < floor:
        return Finding(
            "coverage",
            "block",
            f"{target} 行情覆盖率仅 {ratio:.1%}（{present}/{listed}，下限 {floor:.0%}）"
            "，同步很可能没跑完",
            observed=round(ratio, 4),
            threshold=floor,
        )
    return Finding("coverage", "ok", f"覆盖率 {ratio:.1%}", round(ratio, 4), floor)


def _check_turnover(store: MarketStore, target: str, limits: dict[str, float]) -> Finding:
    """换手率缺失比例。

    筹码分布（COST/WINNER）完全靠换手率做衰减，缺了就只能整列作废。
    缺得多说明数据源那边出了问题，此时筹码类战法的结果不可用。
    """
    row = store.conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN turnover IS NULL OR turnover <= 0 THEN 1 ELSE 0 END) AS missing"
        " FROM quotes_daily WHERE trade_date = ?",
        (target,),
    ).fetchone()
    total = int(row["total"] or 0)
    if not total:
        return Finding("turnover", "block", f"{target} 没有任何行情记录")
    missing = int(row["missing"] or 0)
    ratio = missing / total
    ceiling = float(limits["max_turnover_missing_ratio"])
    if ratio > ceiling:
        return Finding(
            "turnover",
            "warn",
            f"{target} 有 {missing}/{total}（{ratio:.1%}）标的缺换手率，"
            f"超过上限 {ceiling:.0%}；筹码类战法（COST/WINNER）结果不可信",
            observed=round(ratio, 4),
            threshold=ceiling,
        )
    return Finding("turnover", "ok", f"换手率缺失 {ratio:.1%}", round(ratio, 4), ceiling)


def _check_zero_amount(store: MarketStore, target: str, limits: dict[str, float]) -> Finding:
    """成交额为 0 的比例。正常市况下只有停牌股才会是 0。"""
    row = store.conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN amount IS NULL OR amount <= 0 THEN 1 ELSE 0 END) AS zeros"
        " FROM quotes_daily WHERE trade_date = ?",
        (target,),
    ).fetchone()
    total = int(row["total"] or 0)
    if not total:
        return Finding("zero_amount", "ok", "无记录可查")
    zeros = int(row["zeros"] or 0)
    ratio = zeros / total
    ceiling = float(limits["max_zero_amount_ratio"])
    if ratio > ceiling:
        return Finding(
            "zero_amount",
            "warn",
            f"{target} 有 {ratio:.1%} 的标的成交额为 0（上限 {ceiling:.0%}），"
            "可能是数据源缺列而不是真停牌",
            observed=round(ratio, 4),
            threshold=ceiling,
        )
    return Finding("zero_amount", "ok", f"零成交额 {ratio:.1%}", round(ratio, 4), ceiling)


def _check_factor_age(store: MarketStore, limits: dict[str, float]) -> Finding:
    """复权因子的时效。

    因子表是同步时一次性拉的。若某只票在同步之后除权，历史价格会全部错位，
    而且同样不报错——前复权面板整列失真，回测与选股一起废掉。
    """
    row = store.conn.execute(
        "SELECT MAX(fetched_at) AS latest, COUNT(*) AS rows FROM adjust_factors"
    ).fetchone()
    if not row or not row["rows"]:
        return Finding(
            "factor_age",
            "warn",
            "adjust_factors 表是空的：前复权等同于不复权，除权票的历史价格会错位",
            observed=0,
        )
    latest = str(row["latest"] or "")
    try:
        fetched = datetime.fromisoformat(latest.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return Finding("factor_age", "warn", f"无法解析复权因子更新时间：{latest!r}")
    age_days = (datetime.now() - fetched).total_seconds() / 86400.0
    ceiling = float(limits["max_factor_age_days"])
    if age_days > ceiling:
        return Finding(
            "factor_age",
            "warn",
            f"复权因子已 {age_days:.0f} 天未更新（上限 {ceiling:.0f} 天）；"
            "期间发生除权的标的价格序列会失真",
            observed=round(age_days, 1),
            threshold=ceiling,
        )
    return Finding("factor_age", "ok", f"复权因子 {age_days:.1f} 天前更新",
                   round(age_days, 1), ceiling)


def _check_failed_codes(coverage: dict[str, Any], limits: dict[str, float]) -> Finding:
    failed = int(coverage.get("failed_codes") or 0)
    ceiling = int(limits["max_failed_codes"])
    if failed > ceiling:
        return Finding(
            "failed_codes",
            "warn",
            f"有 {failed} 只标的最近一次同步失败（上限 {ceiling}）",
            observed=failed,
            threshold=ceiling,
        )
    return Finding("failed_codes", "ok", f"同步失败 {failed} 只", failed, ceiling)


def guard_market_health(
    store: MarketStore,
    *,
    trade_date: str | None = None,
    thresholds: dict[str, float] | None = None,
    enabled: bool = True,
) -> HealthReport:
    """体检并在不合格时抛 ``DataQualityError``。

    ``enabled=False`` 时仍然跑检查并返回报告，只是不抛——用于"我知道数据
    有问题，就是要看看它会选出什么"这种显式绕过。绕过必须是显式的，
    不能是默认行为。
    """
    report = check_market_health(store, trade_date=trade_date, thresholds=thresholds)
    if enabled and report.blocked:
        raise DataQualityError(report)
    return report
