"""严格样本外与随机对照验证工具。

这里的函数只消费已经生成的 ``Trade`` 事件，不负责训练策略或选择参数。
这样可以把“参数在训练区间确定、OOS 只验证”写进调用契约；bootstrap/Monte
Carlo 也明确标为不确定性描述，绝不冒充样本外证据。
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date
from math import isfinite
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

from src.backtest.application.engine import BacktestResult, Trade, compute_metrics
from src.shared.jsonify import jsonable as _jsonable


class ValidationError(ValueError):
    """验证输入未满足严格研究契约。"""


def _iso(value: str | date) -> str:
    text = value.isoformat() if isinstance(value, date) else str(value).strip()
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"日期格式无效：{text}") from exc
    return text




def _coerce_trades(value: Iterable[Trade] | BacktestResult) -> list[Trade]:
    if isinstance(value, BacktestResult):
        return list(value.trades)
    return list(value)


@dataclass(frozen=True, slots=True)
class TrainOOSSplit:
    """预声明、不可重叠的训练/样本外日期。

    日期边界按 ``date_field`` 所声明的交易事件字段解释；默认使用
    ``signal_date``，避免用退出日把训练期信号偷偷挪到 OOS。
    """

    train_start: str
    train_end: str
    oos_start: str
    oos_end: str

    def __post_init__(self) -> None:
        values = {name: _iso(getattr(self, name)) for name in asdict(self)}
        if values["train_start"] > values["train_end"]:
            raise ValidationError("train_start 不能晚于 train_end")
        if values["oos_start"] > values["oos_end"]:
            raise ValidationError("oos_start 不能晚于 oos_end")
        if values["train_end"] >= values["oos_start"]:
            raise ValidationError("train/OOS 区间必须严格不重叠且按时间递进")
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def phase_for(self, value: str | date) -> str | None:
        day = _iso(value)
        if self.train_start <= day <= self.train_end:
            return "train"
        if self.oos_start <= day <= self.oos_end:
            return "oos"
        return None

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class TrainOOSResult:
    split: dict[str, str]
    date_field: str
    parameters: dict[str, Any]
    train: dict[str, Any]
    oos: dict[str, Any]
    sample_size: int
    time_range: dict[str, str | None]
    execution_isolated: bool = False
    execution_ranges: dict[str, dict[str, str | None]] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "backtest-train-oos-v1",
            "split": dict(self.split),
            "date_field": self.date_field,
            "parameters": _jsonable(self.parameters),
            "train": _jsonable(self.train),
            "oos": _jsonable(self.oos),
            "sample_size": self.sample_size,
            "time_range": dict(self.time_range),
            "skipped": dict(self.skipped),
            "failures": list(self.failures),
            "oos_is_strict": self.execution_isolated,
            "execution_isolated": self.execution_isolated,
            "execution_ranges": _jsonable(self.execution_ranges),
            "not_strict_reason": (
                "仅对已有交易按日期切窗，未证明 OOS 独立执行"
                if not self.execution_isolated
                else ""
            ),
        }


def evaluate_train_oos(
    trades: Iterable[Trade] | BacktestResult,
    *,
    split: TrainOOSSplit,
    parameters: Mapping[str, Any] | None = None,
    oos_parameters: Mapping[str, Any] | None = None,
    date_field: str = "signal_date",
) -> TrainOOSResult:
    """在预声明切分上计算 train/OOS 指标。

    ``oos_parameters`` 仅用于检测调用方是否偷偷改参；只要它存在且与
    ``parameters`` 不相等就拒绝。没有传 OOS 参数表示直接复用训练期快照。
    """
    if date_field not in {"signal_date", "entry_date", "exit_date"}:
        raise ValidationError("date_field 仅支持 signal_date/entry_date/exit_date")
    train_params = dict(parameters or {})
    if oos_parameters is not None and dict(oos_parameters) != train_params:
        raise ValidationError("OOS 参数必须复用训练期预声明参数，禁止 OOS 漂移")
    all_trades = _coerce_trades(trades)
    phase_trades: dict[str, list[Trade]] = {"train": [], "oos": []}
    skipped: dict[str, int] = {}
    in_range_dates: list[str] = []
    for trade in all_trades:
        try:
            event_date = _iso(getattr(trade, date_field))
        except (AttributeError, ValidationError):
            skipped["事件日期无效"] = skipped.get("事件日期无效", 0) + 1
            continue
        phase = split.phase_for(event_date)
        if phase is None:
            skipped["不在预声明区间"] = skipped.get("不在预声明区间", 0) + 1
            continue
        phase_trades[phase].append(trade)
        in_range_dates.append(event_date)
        if trade.exit_reason == "data_end":
            skipped[f"{phase}:data_end"] = skipped.get(f"{phase}:data_end", 0) + 1

    def phase_metrics(items: list[Trade], phase: str) -> dict[str, Any]:
        metrics = dict(compute_metrics(items))
        phase_dates = [_iso(getattr(item, date_field)) for item in items if _safe_iso(getattr(item, date_field))]
        metrics.update(
            {
                "phase": phase,
                "sample_size": len(items),
                "time_range": {
                    "start": min(phase_dates) if phase_dates else None,
                    "end": max(phase_dates) if phase_dates else None,
                },
                "parameters_from_train": True,
            }
        )
        return metrics

    failures: list[str] = []
    failures.append("仅对已有交易按日期切窗，未证明 OOS 独立执行")
    if not phase_trades["train"]:
        failures.append("train 区间没有有效事件")
    if not phase_trades["oos"]:
        failures.append("OOS 区间没有有效事件")
    return TrainOOSResult(
        split=split.to_dict(),
        date_field=date_field,
        parameters=train_params,
        train=phase_metrics(phase_trades["train"], "train"),
        oos=phase_metrics(phase_trades["oos"], "oos"),
        sample_size=len(phase_trades["train"]) + len(phase_trades["oos"]),
        time_range={
            "start": min(in_range_dates) if in_range_dates else None,
            "end": max(in_range_dates) if in_range_dates else None,
        },
        execution_isolated=False,
        execution_ranges={
            "train": {"start": split.train_start, "end": split.train_end},
            "oos": {"start": split.oos_start, "end": split.oos_end},
        },
        skipped=skipped,
        failures=failures,
    )


@dataclass
class RandomControlResult:
    seed: int
    repeats: int
    date_field: str
    sample_size: int
    time_range: dict[str, str | None]
    coverage_by_date: dict[str, dict[str, Any]]
    observed: dict[str, Any]
    random_summary: dict[str, Any]
    observed_minus_random_mean: dict[str, float | None]
    same_universe: bool
    same_coverage: bool
    oos: bool = False
    skipped: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "backtest-random-control-v1",
            "seed": int(self.seed),
            "repeats": int(self.repeats),
            "date_field": self.date_field,
            "sample_size": int(self.sample_size),
            "time_range": dict(self.time_range),
            "coverage_by_date": _jsonable(self.coverage_by_date),
            "observed": _jsonable(self.observed),
            "random_summary": _jsonable(self.random_summary),
            "observed_minus_random_mean": _jsonable(self.observed_minus_random_mean),
            "same_universe": self.same_universe,
            "same_coverage": self.same_coverage,
            "oos": False,
            "is_oos": False,
            "not_oos_reason": "随机抽样只描述同宇宙基线，不替代独立 OOS",
            "skipped": dict(self.skipped),
            "failures": list(self.failures),
        }


def strict_random_control(
    selected: Sequence[Trade],
    universe: Sequence[Trade],
    *,
    repeats: int = 1000,
    seed: int = 0,
    date_field: str = "signal_date",
    universe_id: str | None = None,
    selected_universe_id: str | None = None,
) -> RandomControlResult:
    """同日、同股票池、同命中覆盖率的随机对照。

    ``universe`` 必须是同一日期下所有可比较候选的事件结果；每次随机抽样
    继承 observed 在当天的命中数，因而不会把“少选股票”误报成策略优势。
    代码集合验证失败、某日候选不足时不降级成不等覆盖率抽样。
    """
    if repeats <= 0:
        raise ValidationError("repeats 必须为正整数")
    if date_field not in {"signal_date", "entry_date", "exit_date"}:
        raise ValidationError("date_field 仅支持 signal_date/entry_date/exit_date")
    selected_items = _dedupe_events(_coerce_trades(selected), date_field=date_field)
    universe_items = _dedupe_events(_coerce_trades(universe), date_field=date_field)
    skipped: dict[str, int] = {}
    failures: list[str] = []
    same_universe = bool(
        universe_id and selected_universe_id and universe_id == selected_universe_id
    )
    if not universe_id or not selected_universe_id:
        failures.append("random control 必须显式提供 selected 与 universe 的 universe_id")
    elif not same_universe:
        failures.append("selected 与 random control 的 universe_id 不一致")

    selected_by_date = _group_events(selected_items, date_field)
    universe_by_date = _group_events(universe_items, date_field)
    coverage: dict[str, dict[str, Any]] = {}
    eligible = same_universe
    all_dates: list[str] = []
    for day in sorted(selected_by_date):
        selected_codes = sorted(selected_by_date[day])
        universe_codes = sorted(universe_by_date.get(day, {}))
        count = len(selected_codes)
        available = len(universe_codes)
        ratio = count / available if available else 0.0
        coverage[day] = {
            "selected": count,
            "universe": available,
            "coverage_ratio": round(ratio, 8),
            "codes": selected_codes,
        }
        all_dates.append(day)
        if not available:
            failures.append(f"{day} 没有同宇宙候选")
            eligible = False
        elif count > available:
            failures.append(f"{day} 随机候选不足以保持覆盖率 {count}/{available}")
            eligible = False
        missing = sorted(set(selected_codes) - set(universe_codes))
        if missing:
            failures.append(f"{day} selected 代码不在 universe：{','.join(missing)}")
            eligible = False
    if not selected_items:
        failures.append("selected 没有有效事件")
        eligible = False
    if not universe_items:
        failures.append("universe 没有有效事件")
        eligible = False
    same_coverage = eligible and all(
        row["selected"] <= row["universe"] for row in coverage.values()
    )
    if not same_coverage and eligible:
        failures.append("无法建立同覆盖率随机抽样")

    observed_metrics = _metrics_with_sample(selected_items)
    distributions: dict[str, list[float]] = {
        key: [] for key in ("avg_net_return", "win_rate", "expectancy", "worst")
    }
    rng = random.Random(int(seed))
    if same_coverage:
        for _ in range(repeats):
            sample: list[Trade] = []
            for day in sorted(selected_by_date):
                universe_events = list(universe_by_date[day].values())
                universe_events.sort(key=_event_sort_key)
                count = len(selected_by_date[day])
                sample.extend(rng.sample(universe_events, count))
            metrics = _metrics_with_sample(sample)
            for key in distributions:
                value = metrics.get(key)
                if isinstance(value, (int, float)) and isfinite(float(value)):
                    distributions[key].append(float(value))
    random_summary = {
        key: _distribution_summary(values) for key, values in distributions.items()
    }
    observed_minus = {
        key: _subtract_observed(observed_metrics.get(key), random_summary[key].get("mean"))
        for key in distributions
    }
    return RandomControlResult(
        seed=int(seed),
        repeats=int(repeats),
        date_field=date_field,
        sample_size=len(selected_items),
        time_range={"start": min(all_dates) if all_dates else None, "end": max(all_dates) if all_dates else None},
        coverage_by_date=coverage,
        observed=observed_metrics,
        random_summary=random_summary,
        observed_minus_random_mean=observed_minus,
        same_universe=same_universe,
        same_coverage=same_coverage,
        skipped=skipped,
        failures=failures,
    )


def _safe_iso(value: Any) -> str | None:
    try:
        return _iso(value)
    except (TypeError, ValidationError):
        return None


def _event_sort_key(trade: Trade) -> tuple[str, str, str, float]:
    return (
        str(trade.code),
        str(trade.entry_date),
        str(trade.exit_date),
        float(trade.net_return_pct),
    )


def _dedupe_events(items: Sequence[Trade], *, date_field: str) -> list[Trade]:
    unique: dict[tuple[str, str], Trade] = {}
    for trade in items:
        day = _safe_iso(getattr(trade, date_field, ""))
        if day is None:
            continue
        key = (day, str(trade.code))
        # Stable replacement by sorted event key protects against input order.
        previous = unique.get(key)
        if previous is None or _event_sort_key(trade) < _event_sort_key(previous):
            unique[key] = trade
    return sorted(
        unique.values(),
        key=lambda item: (
            _safe_iso(getattr(item, date_field, "")) or "",
            _event_sort_key(item),
        ),
    )


def _group_events(items: Sequence[Trade], date_field: str) -> dict[str, dict[str, Trade]]:
    grouped: dict[str, dict[str, Trade]] = {}
    for trade in items:
        day = _safe_iso(getattr(trade, date_field, ""))
        if day is None:
            continue
        grouped.setdefault(day, {})[str(trade.code)] = trade
    return grouped


def _metrics_with_sample(items: Sequence[Trade]) -> dict[str, Any]:
    metrics = dict(compute_metrics(list(items)))
    metrics["sample_size"] = len(items)
    metrics["time_range"] = {
        "start": min((_safe_iso(item.signal_date) for item in items if _safe_iso(item.signal_date)), default=None),
        "end": max((_safe_iso(item.signal_date) for item in items if _safe_iso(item.signal_date)), default=None),
    }
    return metrics


def _distribution_summary(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "p05": None, "p95": None, "min": None, "max": None}
    ordered = sorted(float(value) for value in values)
    return {
        "n": len(ordered),
        "mean": round(mean(ordered), 6),
        "median": round(median(ordered), 6),
        "p05": round(_quantile(ordered, 0.05), 6),
        "p95": round(_quantile(ordered, 0.95), 6),
        "min": round(ordered[0], 6),
        "max": round(ordered[-1], 6),
    }


def _quantile(values: Sequence[float], q: float) -> float:
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return float(values[lower] * (1 - weight) + values[upper] * weight)


def _subtract_observed(observed: Any, baseline: Any) -> float | None:
    if not isinstance(observed, (int, float)) or not isinstance(baseline, (int, float)):
        return None
    if not isfinite(float(observed)) or not isfinite(float(baseline)):
        return None
    return round(float(observed) - float(baseline), 6)


@dataclass
class UncertaintyResult:
    method: str
    statistic: str
    seed: int
    iterations: int
    sample_size: int
    time_range: dict[str, str | None]
    estimate: float | None
    interval: dict[str, float | None]
    distribution: dict[str, float | int | None]
    is_oos: bool = False
    skipped: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "backtest-uncertainty-v1",
            "method": self.method,
            "statistic": self.statistic,
            "seed": int(self.seed),
            "iterations": int(self.iterations),
            "sample_size": int(self.sample_size),
            "time_range": dict(self.time_range),
            "estimate": self.estimate,
            "interval": _jsonable(self.interval),
            "distribution": _jsonable(self.distribution),
            "is_oos": False,
            "not_oos_reason": "对已观察交易重采样，不含参数隔离或新数据，因此不能替代 OOS",
            "skipped": dict(self.skipped),
            "failures": list(self.failures),
        }


def bootstrap_uncertainty(
    trades: Iterable[Trade] | BacktestResult,
    *,
    iterations: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
    statistic: str = "avg_net_return",
) -> UncertaintyResult:
    """对已完成交易做 bootstrap；结果明确不是 OOS。"""
    return _resample_uncertainty(
        trades,
        method="bootstrap",
        iterations=iterations,
        seed=seed,
        confidence=confidence,
        statistic=statistic,
    )


def monte_carlo_uncertainty(
    trades: Iterable[Trade] | BacktestResult,
    *,
    iterations: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
    statistic: str = "compound_return_pct",
) -> UncertaintyResult:
    """用随机重排/有放回抽样描述路径不确定性；不构成 OOS。"""
    return _resample_uncertainty(
        trades,
        method="monte_carlo",
        iterations=iterations,
        seed=seed,
        confidence=confidence,
        statistic=statistic,
    )


def _resample_uncertainty(
    trades: Iterable[Trade] | BacktestResult,
    *,
    method: str,
    iterations: int,
    seed: int,
    confidence: float,
    statistic: str,
) -> UncertaintyResult:
    if iterations <= 0:
        raise ValidationError("iterations 必须为正整数")
    if not 0 < confidence < 1:
        raise ValidationError("confidence 必须在 0 与 1 之间")
    if statistic not in {"avg_net_return", "median_net_return", "compound_return_pct"}:
        raise ValidationError("statistic 不支持")
    items = _coerce_trades(trades)
    skipped: dict[str, int] = {}
    eligible: list[Trade] = []
    for item in items:
        if item.exit_reason == "data_end":
            skipped["data_end不纳入重采样"] = skipped.get("data_end不纳入重采样", 0) + 1
            continue
        if not isfinite(float(item.net_return_pct)):
            skipped["净收益无效"] = skipped.get("净收益无效", 0) + 1
            continue
        eligible.append(item)
    dates = [_safe_iso(item.signal_date) for item in eligible if _safe_iso(item.signal_date)]
    failures: list[str] = []
    if not eligible:
        failures.append("没有可重采样的完整交易")
    if len(eligible) < 2:
        failures.append("样本少于 2 笔，区间只能作为极不稳定的描述")
    estimate = _statistic(eligible, statistic)
    rng = random.Random(int(seed))
    values: list[float] = []
    if eligible:
        for _ in range(iterations):
            sample = [eligible[rng.randrange(len(eligible))] for _ in range(len(eligible))]
            values.append(_statistic(sample, statistic))
    summary = _distribution_summary(values)
    alpha = (1.0 - confidence) / 2.0
    return UncertaintyResult(
        method=method,
        statistic=statistic,
        seed=int(seed),
        iterations=int(iterations),
        sample_size=len(eligible),
        time_range={"start": min(dates) if dates else None, "end": max(dates) if dates else None},
        estimate=estimate,
        interval={
            "confidence": confidence,
            "lower": _quantile(values, alpha) if values else None,
            "upper": _quantile(values, 1.0 - alpha) if values else None,
        },
        distribution=summary,
        skipped=skipped,
        failures=failures,
    )


def _statistic(items: Sequence[Trade], name: str) -> float:
    returns = [float(item.net_return_pct) for item in items]
    if not returns:
        return 0.0
    if name == "avg_net_return":
        return round(mean(returns), 6)
    if name == "median_net_return":
        return round(median(returns), 6)
    factor = 1.0
    for value in returns:
        factor *= 1.0 + value / 100.0
    return round((factor - 1.0) * 100.0, 6)
