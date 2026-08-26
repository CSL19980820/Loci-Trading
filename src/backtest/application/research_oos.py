"""真正隔离执行的 train/OOS 研究验证。

``research_validation.evaluate_train_oos`` 保留为旧结果的切窗诊断；本模块只
接受已经分别执行的训练和样本外结果，并核验二者的区间与参数承诺，才会把
``oos_is_strict`` 标为真。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

from src.backtest.application.engine import BacktestResult, Trade, compute_metrics
from src.backtest.application.research_validation import (
    TrainOOSResult,
    TrainOOSSplit,
    ValidationError,
)


def evaluate_isolated_train_oos(
    train: BacktestResult | Iterable[Trade],
    oos: BacktestResult | Iterable[Trade],
    *,
    split: TrainOOSSplit,
    parameters: Mapping[str, Any],
    oos_parameters: Mapping[str, Any] | None = None,
    date_field: str = "signal_date",
    train_execution_range: Mapping[str, str] | None = None,
    oos_execution_range: Mapping[str, str] | None = None,
) -> TrainOOSResult:
    """核验两段独立回测结果，而不是在一段结果上事后切窗。

    ``parameters`` 必须是创建研究 run 时冻结的完整参数快照；OOS 结果不能
    使用另一组参数。结果配置若可用，也必须与预声明区间完全一致。
    """
    if date_field not in {"signal_date", "entry_date", "exit_date"}:
        raise ValidationError("date_field 仅支持 signal_date/entry_date/exit_date")
    locked = dict(parameters)
    if oos_parameters is not None and dict(oos_parameters) != locked:
        raise ValidationError("OOS 参数必须复用训练期冻结快照，禁止 OOS 漂移")

    train_range = _execution_range(train, train_execution_range)
    oos_range = _execution_range(oos, oos_execution_range)
    _require_exact_range(
        train_range,
        expected={"start": split.train_start, "end": split.train_end},
        phase="train",
    )
    _require_exact_range(
        oos_range,
        expected={"start": split.oos_start, "end": split.oos_end},
        phase="OOS",
    )
    _require_result_parameters(train, locked, phase="train")
    _require_result_parameters(oos, locked, phase="OOS")

    train_items, train_skipped = _phase_items(
        _trades(train),
        start=split.train_start,
        end=split.train_end,
        date_field=date_field,
        phase="train",
    )
    oos_items, oos_skipped = _phase_items(
        _trades(oos),
        start=split.oos_start,
        end=split.oos_end,
        date_field=date_field,
        phase="OOS",
    )
    skipped = {**train_skipped}
    for key, value in oos_skipped.items():
        skipped[key] = skipped.get(key, 0) + value
    failures: list[str] = []
    if not train_items:
        failures.append("train 区间没有有效事件")
    if not oos_items:
        failures.append("OOS 区间没有有效事件")
    if any(key.endswith("事件不在独立执行区间") for key in skipped):
        failures.append("独立执行结果包含区间外事件")

    return TrainOOSResult(
        split=split.to_dict(),
        date_field=date_field,
        parameters=locked,
        train=_phase_metrics(train_items, phase="train", date_field=date_field),
        oos=_phase_metrics(oos_items, phase="oos", date_field=date_field),
        sample_size=len(train_items) + len(oos_items),
        time_range={
            "start": min(
                [_event_date(item, date_field) for item in [*train_items, *oos_items]],
                default=None,
            ),
            "end": max(
                [_event_date(item, date_field) for item in [*train_items, *oos_items]],
                default=None,
            ),
        },
        execution_isolated=True,
        execution_ranges={"train": train_range, "oos": oos_range},
        skipped=skipped,
        failures=failures,
    )


def _trades(value: BacktestResult | Iterable[Trade]) -> list[Trade]:
    return list(value.trades) if isinstance(value, BacktestResult) else list(value)


def _execution_range(
    value: BacktestResult | Iterable[Trade],
    explicit: Mapping[str, str] | None,
) -> dict[str, str | None]:
    raw = explicit
    if raw is None and isinstance(value, BacktestResult):
        candidate = value.config.get("range")
        raw = candidate if isinstance(candidate, Mapping) else None
    if raw is None:
        raise ValidationError("严格 OOS 需要每段独立执行范围回执")
    return {
        "start": _iso_or_none(raw.get("start")),
        "end": _iso_or_none(raw.get("end")),
    }


def _require_exact_range(
    actual: Mapping[str, str | None],
    *,
    expected: Mapping[str, str],
    phase: str,
) -> None:
    if actual.get("start") != expected["start"] or actual.get("end") != expected["end"]:
        raise ValidationError(
            f"{phase} 独立执行范围与预声明切分不一致：{actual.get('start')}"
            f"~{actual.get('end')}"
        )


def _require_result_parameters(
    value: BacktestResult | Iterable[Trade],
    locked: Mapping[str, Any],
    *,
    phase: str,
) -> None:
    if not isinstance(value, BacktestResult):
        return
    actual = value.config.get("params")
    if isinstance(actual, Mapping) and dict(actual) != dict(locked):
        raise ValidationError(f"{phase} 独立执行参数与预声明快照不一致")


def _phase_items(
    trades: Iterable[Trade],
    *,
    start: str,
    end: str,
    date_field: str,
    phase: str,
) -> tuple[list[Trade], dict[str, int]]:
    kept: list[Trade] = []
    skipped: dict[str, int] = {}
    for trade in trades:
        try:
            event = _event_date(trade, date_field)
        except ValidationError:
            key = f"{phase}:事件日期无效"
            skipped[key] = skipped.get(key, 0) + 1
            continue
        if not start <= event <= end:
            key = f"{phase}:事件不在独立执行区间"
            skipped[key] = skipped.get(key, 0) + 1
            continue
        kept.append(trade)
    return kept, skipped


def _phase_metrics(
    trades: list[Trade],
    *,
    phase: str,
    date_field: str,
) -> dict[str, Any]:
    dates = [_event_date(item, date_field) for item in trades]
    metrics = dict(compute_metrics(trades))
    metrics.update(
        {
            "phase": phase,
            "sample_size": len(trades),
            "time_range": {
                "start": min(dates) if dates else None,
                "end": max(dates) if dates else None,
            },
            "parameters_from_train": True,
            "parameters_locked_before_oos_execution": True,
        }
    )
    return metrics


def _event_date(trade: Trade, date_field: str) -> str:
    return _iso_or_none(getattr(trade, date_field, None)) or _raise_date_error()


def _iso_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValidationError(f"日期格式无效：{text}") from exc


def _raise_date_error() -> str:
    raise ValidationError("事件日期为空")


__all__ = ["evaluate_isolated_train_oos"]
