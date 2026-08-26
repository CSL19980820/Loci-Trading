"""预案兑现：止损/止盈事后是否触发。"""
from __future__ import annotations

from typing import Any

from src.market import MarketStore
from src.ledger import PalaceStore


def evaluate_plans(palace: PalaceStore, market: MarketStore) -> list[dict[str, Any]]:
    """预案兑现：止损/止盈事后有没有被触发。

    口径约束：
    - 预案是盘后（或休市日）制定的，信号日当天尚未开盘 → 从下一交易日开始扫描，
      不能用当天的盘中价「提前」标记触发。
    - 观察窗口上限 60 个交易日：长尾预案不无限扫描。
    """
    calendar = market.trading_days()
    position_of = {day: index for index, day in enumerate(calendar)}
    #: 预案观察窗口上限（交易日）。超过仍未触发视为「未兑现」，不再追溯。
    PLAN_WINDOW_TRADING_DAYS = 60

    rows = [
        {
            "id": plan["id"],
            "occurred_on": plan["date"],
            "code": plan["code"],
            "title": plan["title"],
            "stop_price": plan["stop_price"],
            "target_price": plan["target_price"],
            "status": plan["status"],
        }
        for plan in palace.plans_payload(status="active")
    ]
    results: list[dict[str, Any]] = []
    evaluations: list[tuple[dict[str, Any], list[str] | None, int | None]] = []
    codes: set[str] = set()
    window_start: str | None = None
    window_end: str | None = None
    for row in rows:
        code = str(row["code"])
        base_date = str(row["occurred_on"])
        stop = row["stop_price"]
        target = row["target_price"]

        record: dict[str, Any] = {
            "plan_id": str(row["id"]),
            "code": code,
            "title": str(row["title"]),
            "occurred_on": base_date,
            "stop_price": stop,
            "target_price": target,
            "stop_hit_on": None,
            "target_hit_on": None,
            "status_final": "observing",
        }

        base_index = position_of.get(base_date)
        if base_index is None:
            following = [day for day in calendar if day >= base_date]
            if not following:
                record["status_final"] = "no_data"
                record["note"] = "预案日之后还没有交易日数据"
                evaluations.append((record, None, None))
                continue
            base_index = position_of[following[0]]
        start_index = base_index + 1  # 盘后预案：次日才可能触发
        if start_index >= len(calendar):
            # 预案日之后还没有交易日，保持 observing
            evaluations.append((record, None, None))
            continue
        end_index = min(start_index + PLAN_WINDOW_TRADING_DAYS, len(calendar))
        window = calendar[start_index:end_index]
        evaluations.append((record, window, start_index))
        codes.add(code)
        window_start = min(window_start, window[0]) if window_start else window[0]
        window_end = max(window_end, window[-1]) if window_end else window[-1]

    panels = (
        market.load_panel(
            fields=("low", "high"),
            codes=sorted(codes),
            start=window_start,
            end=window_end,
            adjust="qfq",
        )
        if codes
        else {}
    )
    low_panel = panels.get("low")
    high_panel = panels.get("high")

    for record, window, start_index in evaluations:
        if window is None:
            results.append(record)
            continue

        code = str(record["code"])
        low_series = low_panel[code] if low_panel is not None and code in low_panel else None
        high_series = high_panel[code] if high_panel is not None and code in high_panel else None
        observed_days = set()
        if low_series is not None:
            observed_days.update(str(day) for day in low_series.dropna().index)
        if high_series is not None:
            observed_days.update(str(day) for day in high_series.dropna().index)
        if not any(day in observed_days for day in window):
            record["status_final"] = "no_data"
            record["note"] = "未取得真实行情"
            results.append(record)
            continue

        if start_index is not None and len(calendar) - start_index > PLAN_WINDOW_TRADING_DAYS:
            record["window_expired"] = True

        # 必须从本条 record 取价位；勿复用外层 for-row 循环变量。
        stop = record["stop_price"]
        target = record["target_price"]
        for trade_date in window:
            low = low_series.get(trade_date) if low_series is not None else None
            high = high_series.get(trade_date) if high_series is not None else None
            if stop is not None and low is not None and low <= float(stop) and not record["stop_hit_on"]:
                record["stop_hit_on"] = trade_date
            if (
                target is not None
                and high is not None
                and high >= float(target)
                and not record["target_hit_on"]
            ):
                record["target_hit_on"] = trade_date

        if record["target_hit_on"] and record["stop_hit_on"]:
            record["status_final"] = (
                "target_first" if record["target_hit_on"] <= record["stop_hit_on"] else "stop_first"
            )
        elif record["target_hit_on"]:
            record["status_final"] = "target_hit"
        elif record["stop_hit_on"]:
            record["status_final"] = "stop_hit"
        elif record.get("window_expired"):
            # 观察窗口完整走完仍未触发 → 未兑现；否则保持 observing 等行情补齐
            record["status_final"] = "expired"
            record["note"] = "观察窗口内未触发"
        results.append(record)
    return results
