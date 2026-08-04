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
from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.market.infrastructure.store import MarketStore

#: 检查项默认阈值。
DEFAULT_THRESHOLDS: dict[str, float] = {
    # 最新交易日的行情覆盖率下限。低于此值说明同步没跑完或大面积失败。
    "min_coverage_ratio": 0.90,
    # 仓内最新日相对墙钟应覆盖日的最大滞后。历史选股基准日本身不受此限。
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

#: UI 扫描目录（与检查函数一一对应；空仓时只会出现 empty_store）。
CHECK_CATALOG: tuple[dict[str, str], ...] = (
    {"id": "empty_store", "label": "仓内是否有日 K", "group": "仓体"},
    {"id": "staleness", "label": "最新日是否落后", "group": "时效"},
    {"id": "coverage", "label": "当日覆盖率", "group": "覆盖"},
    {"id": "turnover", "label": "换手率完整度", "group": "质量"},
    {"id": "zero_amount", "label": "成交额异常比", "group": "质量"},
    {"id": "factor_age", "label": "复权因子时效", "group": "因子"},
    {"id": "failed_codes", "label": "同步失败标的", "group": "覆盖"},
)

#: 印鉴分扣分（仅展示；门禁仍看 ``blocked``）。
SCORE_BLOCK_PENALTY = 25
SCORE_WARN_PENALTY = 8

#: 一键修复 action 优先级（数字越小越先合并）。
_REPAIR_ACTION_PRIORITY: dict[str, int] = {
    "bootstrap": 0,
    "sync_factors": 1,
    "sync": 2,
    "repair_turnover": 3,
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
            "remediation": remediation_for(self.check),
        }


def remediation_for(check: str) -> dict[str, str] | None:
    """体检项 → 前端可执行的修复动作（无动作返回 None）。"""
    mapping = {
        "empty_store": {
            "action": "bootstrap",
            "label": "初始化行情",
            "hint": "空库需先全量或补齐历史日 K",
        },
        "staleness": {
            "action": "sync",
            "label": "同步行情",
            "hint": "库内最新日落后，增量同步即可",
        },
        "coverage": {
            "action": "sync",
            "label": "补齐当日覆盖",
            "hint": "覆盖率不足通常是同步没跑完，继续同步",
        },
        "turnover": {
            "action": "repair_turnover",
            "label": "回填换手率",
            "hint": "用流通股本回填缺换手，不重拉 OHLC",
        },
        "zero_amount": {
            "action": "sync",
            "label": "重拉成交额",
            "hint": "成交额异常多为源数据未就绪",
        },
        "factor_age": {
            "action": "sync_factors",
            "label": "刷新复权因子",
            "hint": "复权因子过旧会导致前复权价漂移",
        },
        "failed_codes": {
            "action": "sync",
            "label": "重试失败标的",
            "hint": "对失败代码再跑一轮同步",
        },
    }
    return mapping.get(check)


def seal_score(*, block_count: int, warn_count: int) -> int:
    """印鉴分：100 起，block −25 / warn −8，夹到 0–100。"""
    raw = 100 - SCORE_BLOCK_PENALTY * block_count - SCORE_WARN_PENALTY * warn_count
    return max(0, min(100, int(raw)))


def seal_grade(score: int) -> str:
    """印鉴分档：优 / 良 / 中 / 差。"""
    if score >= 90:
        return "优"
    if score >= 70:
        return "良"
    if score >= 50:
        return "中"
    return "差"


def build_repair_plan(findings: list[Finding]) -> dict[str, Any]:
    """把多条 finding 的 remediation 去重合并成一次可执行计划。

    优先级：bootstrap > sync_factors > sync。含因子问题时 ``with_factors=True``。
    """
    by_action: dict[str, dict[str, str]] = {}
    for item in findings:
        if item.severity == "ok":
            continue
        rem = remediation_for(item.check)
        if not rem:
            continue
        action = rem["action"]
        if action not in by_action:
            by_action[action] = rem

    ordered = sorted(
        by_action.values(),
        key=lambda rem: _REPAIR_ACTION_PRIORITY.get(rem["action"], 99),
    )
    actions = [rem["action"] for rem in ordered]
    # 凡要拉行情/因子的动作都带上复权因子；纯换手回填不必
    with_factors = any(a in {"sync_factors", "bootstrap", "sync"} for a in actions)
    primary = actions[0] if actions else None
    return {
        "actions": actions,
        "primary_action": primary,
        "with_factors": with_factors,
        "needs_bootstrap": any(a in {"bootstrap", "sync", "sync_factors"} for a in actions),
        "needs_turnover_repair": "repair_turnover" in actions,
        "labels": [rem["label"] for rem in ordered],
        "check_ids": [
            item.check
            for item in findings
            if item.severity != "ok" and remediation_for(item.check)
        ],
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

    @property
    def score(self) -> int:
        return seal_score(block_count=len(self.blockers), warn_count=len(self.warnings))

    @property
    def grade(self) -> str:
        return seal_grade(self.score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "blocked": self.blocked,
            "reason": self.reason(),
            "checked_at": self.checked_at,
            "findings": [item.to_dict() for item in self.findings],
            "block_count": len(self.blockers),
            "warn_count": len(self.warnings),
            "score": self.score,
            "grade": self.grade,
            "repair_plan": build_repair_plan(self.findings),
            "catalog": [dict(row) for row in CHECK_CATALOG],
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
    include_ok: bool = False,
) -> HealthReport:
    """对行情仓做一次体检。不抛异常，把结论交给调用方决定。

    ``include_ok=True`` 时保留通过项，供体检页扫描回放；选股门禁默认 False。
    """
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
    if not include_ok:
        # 只保留有话说的项；全 ok 的检查不必占版面。
        report.findings = [item for item in report.findings if item.severity != "ok"]
    return report


def _wall_clock_data_lag(last_date: str, days: list[str], *, now: datetime | None = None) -> int:
    """仓内最新日相对「今天应覆盖的交易日」落后多少个交易日。

    日历只含已入库日时，若末日已落后墙钟，用工作日差粗估（不计 A 股节假日）。
    """
    clock = now or datetime.now()
    today = clock.date()
    today_s = today.isoformat()
    try:
        last = date.fromisoformat(last_date)
    except ValueError:
        return 99
    if last >= today:
        return 0

    after_close = (clock.hour * 60 + clock.minute) >= 15 * 60
    if today_s in days and last_date in days:
        expected = today_s
        if not after_close:
            idx = days.index(today_s)
            expected = days[idx - 1] if idx > 0 else today_s
        if last_date >= expected:
            return 0
        return days.index(expected) - days.index(last_date)

    # 日历尚无今日（周末或日历过期）：按 Mon–Fri 粗估
    end = today if after_close or today.weekday() >= 5 else today - timedelta(days=1)
    lag = 0
    cursor = last + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() < 5:
            lag += 1
        cursor += timedelta(days=1)
    return lag


def _check_staleness(
    store: MarketStore,
    coverage: dict[str, Any],
    target: str,
    limits: dict[str, float],
    *,
    now: datetime | None = None,
) -> Finding:
    """行情仓最新日是否过旧，以及是否覆盖选股基准日。

    故意选历史基准日做复盘 ≠ 数据过期。过期只看仓内最新日相对墙钟，
    不是「基准日距日历末日」——后者会误拦选股复盘。
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

    if last_date < target:
        return Finding(
            "staleness",
            "block",
            f"行情最新日 {last_date} 尚未覆盖选股基准日 {target}",
            observed=last_date,
            threshold=target,
        )

    allowed = int(limits["max_stale_days"])
    lag = _wall_clock_data_lag(last_date, days, now=now)
    if lag > allowed:
        return Finding(
            "staleness",
            "block",
            f"行情最新日 {last_date} 落后当前 {lag} 个交易日（上限 {allowed}）",
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
        today = date.today().isoformat()
        spot_hint = (
            "；若目标日是今天，多半是盘中 spot 未写完（历史同步不含当日），请等 spot 刷完或重跑选股前刷新"
            if target == today
            else "，同步很可能没跑完"
        )
        return Finding(
            "coverage",
            "block",
            f"{target} 行情覆盖率仅 {ratio:.1%}（{present}/{listed}，下限 {floor:.0%}）"
            f"{spot_hint}",
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
        fetched = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        if fetched.tzinfo is not None:
            fetched = fetched.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return Finding("factor_age", "warn", f"无法解析复权因子更新时间：{latest!r}")
    # SQLite datetime('now') 写的是 UTC；用 UTC 墙钟比，避免东八区把因子误判旧 8 小时
    age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - fetched).total_seconds() / 86400.0
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
