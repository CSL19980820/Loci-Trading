"""显式尾盘快照任务的时点与交易日门禁，不改变普通选股任务。"""
from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from src.ops.application.jobs.context import JobContext, JobError, JobSkipped

_TZ = ZoneInfo("Asia/Shanghai")


def guard_screen_schedule(
    config: dict[str, Any], context: JobContext, *, now: datetime | None = None
) -> dict[str, Any]:
    """只放行指定实时窗口及明确有日历证据的交易日；跳过原因带实际时刻。"""
    snapshot_time = config.get("snapshot_time")
    trading_only = config.get("trading_days_only") is True
    if snapshot_time is None and not trading_only:
        return {}
    stamp = now or datetime.now(_TZ)
    stamp = stamp.replace(tzinfo=_TZ) if stamp.tzinfo is None else stamp.astimezone(_TZ)
    actual = stamp.isoformat(timespec="seconds")
    day = stamp.date().isoformat()

    def skip(reason: str) -> None:
        raise JobSkipped(f"{reason}；实际检查时间 {actual}")

    metadata: dict[str, Any] = {"checked_at": actual, "timezone": "Asia/Shanghai"}
    if snapshot_time is not None:
        if not isinstance(snapshot_time, str) or not re.fullmatch(r"\d{2}:\d{2}", snapshot_time):
            raise JobError("snapshot_time 必须是 HH:MM")
        try:
            hour, minute = map(int, snapshot_time.split(":"))
            target = stamp.replace(hour=hour, minute=minute, second=0, microsecond=0)
            grace = float(config.get("snapshot_grace_minutes", 2))
            if not 0 < grace <= 10:
                raise ValueError("grace")
        except (TypeError, ValueError, OverflowError) as exc:
            raise JobError("尾盘快照时点非法，宽限分钟必须大于 0 且不超过 10") from exc
        deadline = target + timedelta(minutes=grace)
        if target.hour < 9 or target.hour >= 15 or deadline > target.replace(hour=15, minute=0):
            raise JobError("尾盘快照窗口必须位于盘中且在 15:00 前结束")
        metadata.update({"snapshot_time": snapshot_time, "window_end": deadline.isoformat()})
        if config.get("date") and str(config["date"])[:10] != day:
            skip("定时快照不允许使用历史日期替代今天")
        # 截止时刻不包含：14:50 + 2 分钟允许 [14:50:00, 14:52:00)。
        if not target <= stamp < deadline:
            skip(f"已在快照窗口 {snapshot_time}～{deadline:%H:%M} 之外，禁止用盘后日 K 补跑")

    if trading_only:
        if stamp.weekday() >= 5:
            skip(f"{day} 非交易日（周末）")
        try:
            with context.market() as market:
                days = sorted(str(value) for value in market.trading_days())
        except Exception as exc:
            skip(f"交易日历读取失败，禁止筛选（{type(exc).__name__}）")
        # trading_days 是 MarketStore 的公开日历接口；区间外不能靠工作日猜测。
        if not days or day < days[0] or day > days[-1]:
            skip(f"交易日历未明确覆盖 {day}，禁止筛选")
        if day not in days:
            skip(f"{day} 非交易日（交易日历休市）")
        metadata["calendar_source"] = "market_db"
    return metadata
