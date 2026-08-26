"""从事件交易明细生成可解释的风险透视（risk xray）。"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from src.backtest.application.engine import BacktestResult, Trade, compute_metrics
from src.shared.jsonify import jsonable as _jsonable


class RiskXrayError(ValueError):
    """风险透视输入不合法。"""


def _iso(value: str | date) -> str:
    text = value.isoformat() if isinstance(value, date) else str(value).strip()
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise RiskXrayError(f"日期格式无效：{text}") from exc
    return text


def _safe_iso(value: Any) -> str | None:
    try:
        return _iso(value)
    except (TypeError, RiskXrayError):
        return None




@dataclass
class RiskXrayResult:
    sample_size: int
    evaluable_sample_size: int
    time_range: dict[str, str | None]
    segment_period: str
    segments: list[dict[str, Any]]
    exit_reasons: list[dict[str, Any]]
    holding_periods: list[dict[str, Any]]
    extreme_losses: list[dict[str, Any]]
    by_board: list[dict[str, Any]] = field(default_factory=list)
    by_industry: list[dict[str, Any]] = field(default_factory=list)
    by_market_regime: list[dict[str, Any]] = field(default_factory=list)
    entry_types: list[dict[str, Any]] = field(default_factory=list)
    entry_gaps: list[dict[str, Any]] = field(default_factory=list)
    availability: dict[str, bool] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "backtest-risk-xray-v1",
            "sample_size": self.sample_size,
            "evaluable_sample_size": self.evaluable_sample_size,
            "time_range": dict(self.time_range),
            "segment_period": self.segment_period,
            "segments": _jsonable(self.segments),
            "exit_reasons": _jsonable(self.exit_reasons),
            "holding_periods": _jsonable(self.holding_periods),
            "extreme_losses": _jsonable(self.extreme_losses),
            "by_board": _jsonable(self.by_board),
            "by_industry": _jsonable(self.by_industry),
            "by_market_regime": _jsonable(self.by_market_regime),
            "entry_types": _jsonable(self.entry_types),
            "entry_gaps": _jsonable(self.entry_gaps),
            "availability": dict(self.availability),
            "skipped": dict(self.skipped),
            "failures": list(self.failures),
        }


def risk_xray(
    trades: Iterable[Trade] | BacktestResult,
    *,
    segment_period: str = "month",
    date_field: str = "signal_date",
    extreme_loss_pct: float = -5.0,
    max_extremes: int = 10,
    metadata_by_code: Mapping[str, Mapping[str, Any]] | None = None,
    market_regime_by_date: Mapping[str, str] | None = None,
    entry_timing: str = "",
    entry_gap_pct_by_trade: Mapping[tuple[str, str], float] | None = None,
) -> RiskXrayResult:
    """按时间、退出原因、持有期和极端亏损拆解交易风险。

    元数据和市场状态都必须由调用方传入；没有可靠来源时，本函数不会根据
    代码前缀猜板块/行业，也不会把 MAE 冒充跳空风险。
    """
    if segment_period not in {"day", "month", "quarter", "year"}:
        raise RiskXrayError("segment_period 仅支持 day/month/quarter/year")
    if date_field not in {"signal_date", "entry_date", "exit_date"}:
        raise RiskXrayError("date_field 仅支持 signal_date/entry_date/exit_date")
    if max_extremes < 0:
        raise RiskXrayError("max_extremes 不能为负数")
    items = list(trades.trades) if isinstance(trades, BacktestResult) else list(trades)
    skipped: dict[str, int] = defaultdict(int)
    valid: list[Trade] = []
    dates: list[str] = []
    for trade in items:
        event_date = _safe_iso(getattr(trade, date_field, ""))
        if event_date is None:
            skipped["事件日期无效"] += 1
            continue
        if trade.exit_reason == "data_end":
            skipped["data_end不纳入风险统计"] += 1
            continue
        if not _finite_trade(trade):
            skipped["交易字段无效"] += 1
            continue
        valid.append(trade)
        dates.append(event_date)

    grouped_segment: dict[str, list[Trade]] = defaultdict(list)
    grouped_reason: dict[str, list[Trade]] = defaultdict(list)
    grouped_hold: dict[str, list[Trade]] = defaultdict(list)
    grouped_board: dict[str, list[Trade]] = defaultdict(list)
    grouped_industry: dict[str, list[Trade]] = defaultdict(list)
    grouped_regime: dict[str, list[Trade]] = defaultdict(list)
    grouped_entry_type: dict[str, list[Trade]] = defaultdict(list)
    gaps: list[dict[str, Any]] = []
    metadata = metadata_by_code or {}
    regimes = market_regime_by_date or {}
    entry_gaps = entry_gap_pct_by_trade or {}
    for trade in valid:
        event_date = _safe_iso(getattr(trade, date_field)) or ""
        grouped_segment[_period_key(event_date, segment_period)].append(trade)
        grouped_reason[str(trade.exit_reason)].append(trade)
        grouped_hold[str(int(trade.hold_days))].append(trade)
        code_meta = metadata.get(str(trade.code), {})
        board = str(
            code_meta.get("board_label") or code_meta.get("board_bucket") or ""
        ).strip()
        if board:
            grouped_board[board].append(trade)
        industry = str(code_meta.get("industry") or "").strip()
        if industry:
            grouped_industry[industry].append(trade)
        regime = str(regimes.get(event_date) or "").strip()
        if regime:
            grouped_regime[regime].append(trade)
        if entry_timing:
            grouped_entry_type[str(entry_timing)].append(trade)
        gap = entry_gaps.get((str(trade.code), str(trade.entry_date)))
        try:
            gap_value = float(gap) if gap is not None else None
        except (TypeError, ValueError):
            gap_value = None
        if gap_value is not None and isfinite(gap_value):
            gaps.append(
                {
                    "code": str(trade.code),
                    "signal_date": str(trade.signal_date),
                    "entry_date": str(trade.entry_date),
                    "entry_gap_pct": round(gap_value, 6),
                    "net_return_pct": round(float(trade.net_return_pct), 6),
                    "exit_reason": str(trade.exit_reason),
                }
            )

    failures: list[str] = []
    if not items:
        failures.append("没有输入交易")
    if not valid and items:
        failures.append("没有可用于风险透视的完整交易")
    availability = {
        "board": bool(grouped_board),
        "industry": bool(grouped_industry),
        "market_regime": bool(grouped_regime),
        "entry_timing": bool(grouped_entry_type),
        "entry_gap": bool(gaps),
    }
    if not metadata:
        failures.append("未提供可审计的板块/行业元数据，相关风险维度未推断")
    elif not grouped_board:
        failures.append("元数据未包含可用板块，相关风险维度未推断")
    if metadata and not grouped_industry:
        failures.append("元数据未包含可用行业，行业风险维度未推断")
    if not regimes:
        failures.append("未提供市场状态序列，市场状态风险维度未推断")
    if not entry_timing:
        failures.append("未提供入场时点，入场类型风险维度未推断")
    if not entry_gaps:
        failures.append("未提供入场跳空序列，跳空失效维度未推断")
    return RiskXrayResult(
        sample_size=len(items),
        evaluable_sample_size=len(valid),
        time_range={"start": min(dates) if dates else None, "end": max(dates) if dates else None},
        segment_period=segment_period,
        segments=_group_rows(grouped_segment, date_field=date_field),
        exit_reasons=_group_rows(
            grouped_reason,
            key_name="exit_reason",
            date_field=date_field,
        ),
        holding_periods=_group_rows(
            grouped_hold,
            key_name="hold_days",
            date_field=date_field,
        ),
        extreme_losses=_extreme_losses(valid, threshold=extreme_loss_pct, limit=max_extremes),
        by_board=_group_rows(grouped_board, key_name="board", date_field=date_field),
        by_industry=_group_rows(
            grouped_industry,
            key_name="industry",
            date_field=date_field,
        ),
        by_market_regime=_group_rows(
            grouped_regime,
            key_name="market_regime",
            date_field=date_field,
        ),
        entry_types=_group_rows(
            grouped_entry_type,
            key_name="entry_timing",
            date_field=date_field,
        ),
        entry_gaps=sorted(
            gaps,
            key=lambda item: (
                float(item["entry_gap_pct"]),
                str(item["entry_date"]),
                str(item["code"]),
            ),
            reverse=True,
        )[:max_extremes],
        availability=availability,
        skipped=dict(skipped),
        failures=failures,
    )


def _finite_trade(trade: Trade) -> bool:
    return all(
        isfinite(float(value))
        for value in (
            trade.gross_return_pct,
            trade.net_return_pct,
            trade.mae_pct,
            trade.mfe_pct,
            trade.hold_days,
        )
    )


def _period_key(value: str, period: str) -> str:
    parsed = date.fromisoformat(value)
    if period == "day":
        return value
    if period == "month":
        return f"{parsed.year:04d}-{parsed.month:02d}"
    if period == "quarter":
        return f"{parsed.year:04d}-Q{(parsed.month - 1) // 3 + 1}"
    return f"{parsed.year:04d}"


def _group_rows(
    groups: dict[str, list[Trade]],
    *,
    key_name: str = "segment",
    date_field: str = "signal_date",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(groups):
        items = groups[key]
        metrics = dict(compute_metrics(items))
        rows.append(
            {
                key_name: key,
                "sample_size": len(items),
                "metrics": _jsonable(metrics),
                "time_range": {
                    "start": min(
                        _safe_iso(getattr(item, date_field))
                        for item in items
                        if _safe_iso(getattr(item, date_field))
                    ),
                    "end": max(
                        _safe_iso(getattr(item, date_field))
                        for item in items
                        if _safe_iso(getattr(item, date_field))
                    ),
                },
            }
        )
    return rows


def _extreme_losses(
    trades: Sequence[Trade], *, threshold: float, limit: int
) -> list[dict[str, Any]]:
    losses = [trade for trade in trades if float(trade.net_return_pct) <= float(threshold)]
    losses.sort(
        key=lambda item: (
            float(item.net_return_pct),
            str(item.exit_date),
            str(item.code),
        )
    )
    rows: list[dict[str, Any]] = []
    for trade in losses[:limit]:
        rows.append(
            {
                "code": str(trade.code),
                "signal_date": str(trade.signal_date),
                "entry_date": str(trade.entry_date),
                "exit_date": str(trade.exit_date),
                "net_return_pct": round(float(trade.net_return_pct), 6),
                "gross_return_pct": round(float(trade.gross_return_pct), 6),
                "mae_pct": round(float(trade.mae_pct), 6),
                "mfe_pct": round(float(trade.mfe_pct), 6),
                "hold_days": int(trade.hold_days),
                "exit_reason": str(trade.exit_reason),
            }
        )
    return rows
