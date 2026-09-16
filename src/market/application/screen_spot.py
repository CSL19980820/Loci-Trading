"""收盘后选股前「当日行情就绪」：覆盖够就跳过 spot，根治与同步抢写。

盘中选今天走 ``screen_live``：自己拉实时、只叠内存，不进本模块。

旧逻辑：每次选股都全市场 apply_today_spot，raise_on_failure=True。
盘后同步/日终重刷已写好今日日 K 时，选股再硬写一遍 → SQLite locked → 选股失败。

正确语义（收盘后）：选股要的是「今天有可用日 K」，不是「此刻必须再写一遍 spot」。

**盘中的覆盖率不足多半不是故障**。收盘门槛（min_coverage_ratio，默认 90%）是按
「今天已经走完」定的；在 10:30 拿这条线去卡选股，缺的那几个点其实是「今天还没
走完 / 个别票尚未成交」。此前三处覆盖不足一律 raise，等于每个盘中选股都可能被
自己的门槛打死。现在改成：**盘中软放行 + 降级标记**（``status="degraded_intraday"``、
``degraded=True``），让调用方知道这批结果是盘中口径。

但**不是一刀切放行**。软放行同时要求两件事：

1. 现在确实是盘中——今天是交易日，且时间落在 [09:15, 15:00)。历史日回补、收盘后、
   非交易日一律不吃这条路径。
2. 覆盖率已经过得去（≥ ``INTRADAY_SOFT_PASS_FLOOR``）。覆盖低到这条线以下就不是
   「今天还没走完」，而是真的没数据——那种情况仍旧阻断，绝不能拿降级当遮羞布。
"""
from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.market.infrastructure.sentinel import DEFAULT_THRESHOLDS
from src.market.infrastructure.store import MarketStore

logger = logging.getLogger(__name__)

#: 与健康门禁当日覆盖率下限对齐
DEFAULT_SCREEN_COVERAGE_FLOOR = float(DEFAULT_THRESHOLDS["min_coverage_ratio"])

_TZ = ZoneInfo("Asia/Shanghai")
#: 盘中时段 [09:15, 15:00)，与 application/session.py 的 ``in_live_clock`` 同口径。
_OPEN_MIN = 9 * 60 + 15
_CLOSE_MIN = 15 * 60

#: 盘中软放行的覆盖率下限。这是「今日未完结」与「真的缺数据」的分界线：
#: 盘中缺几个点很正常，缺一半就不是时钟问题了，别拿降级标记去盖真故障。
INTRADAY_SOFT_PASS_FLOOR = 0.5


class ScreenSpotError(RuntimeError):
    """选股前当日行情无法就绪（用户可见中文）。"""


def measure_day_coverage(store: MarketStore, trade_date: str) -> dict[str, Any]:
    """目标日有行情票数 / 在册正常标的。"""
    listed = int(
        store.conn.execute(
            "SELECT COUNT(*) FROM instruments WHERE status = 'normal'"
        ).fetchone()[0]
    )
    present = int(
        store.conn.execute(
            "SELECT COUNT(DISTINCT code) FROM quotes_daily WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()[0]
    )
    ratio = (present / listed) if listed else 0.0
    return {
        "trade_date": trade_date,
        "listed": listed,
        "present": present,
        "ratio": ratio,
    }


def coverage_ready(
    cov: Mapping[str, Any], *, floor: float = DEFAULT_SCREEN_COVERAGE_FLOOR
) -> bool:
    listed = int(cov.get("listed") or 0)
    if listed <= 0:
        return False
    return float(cov.get("ratio") or 0.0) >= float(floor)


def _is_trading_day(store: MarketStore, day: date) -> bool:
    """今天是不是交易日。

    交易日历优先；日历缺失或已过期（最大日早于今天）时退回工作日粗判——与
    ``application/session.py`` 同一策略，避免「日历没更新」被误读成「今天休市」。
    """
    today = day.isoformat()
    try:
        days = store.trading_days()
    except Exception:  # noqa: BLE001 — 日历读不到不该连累选股，退回粗判
        days = []
    if days and isinstance(days, Sequence) and len(days) > 0:
        if today in set(days):
            return True
        try:
            if today <= max(days):
                # 日历已经覆盖到今天及之后却没有今天 → 真节假日
                return False
        except Exception:
            pass
    return day.weekday() < 5

def in_open_session(store: MarketStore, *, now: datetime | None = None) -> bool:
    """是否「盘中」：今天是交易日，且还没收盘（[09:15, 15:00)）。"""
    if now is None:
        current = datetime.now(_TZ)
    elif now.tzinfo is None:
        current = now.replace(tzinfo=_TZ)
    else:
        current = now.astimezone(_TZ)
    minutes = current.hour * 60 + current.minute
    if not (_OPEN_MIN <= minutes < _CLOSE_MIN):
        return False
    return _is_trading_day(store, current.date())


def _intraday_soft_pass(
    store: MarketStore,
    cov: Mapping[str, Any],
    *,
    floor: float,
    requested: int,
    reason: str,
    written: int = 0,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """盘中且缺口确实只是「今日未完结」时，放行选股并打降级标记；否则返回 None。

    返回 None 的三种情况都必须继续阻断：库里连在册标的都没有、覆盖低于盘中下限
    （真缺数据）、以及当前根本不在盘中（历史日 / 收盘后 / 非交易日）。
    """
    listed = int(cov.get("listed") or 0)
    if listed <= 0:
        # 在册标的都是 0 = 库是空的，跟「今天走没走完」无关。
        return None
    ratio = float(cov.get("ratio") or 0.0)
    if ratio < min(float(floor), INTRADAY_SOFT_PASS_FLOOR):
        # 缺得太多，不是时钟问题，是真没数据。
        return None
    if not in_open_session(store, now=now):
        # 历史日回补、收盘后、非交易日：这时候还不够就是真不足。
        return None
    msg = (
        f"盘中降级放行：当日覆盖 {int(cov.get('present') or 0)}/{listed}="
        f"{ratio:.1%}，未达收盘门槛 {float(floor):.0%}，但此刻尚未收盘，"
        f"缺口应为今日未完结（{reason}）；已按现有数据继续选股，"
        "结果请按盘中口径解读"
    )
    logger.warning(msg)
    return {
        "status": "degraded_intraday",
        "written": int(written),
        "requested": int(requested),
        "coverage": dict(cov),
        "degraded": True,
        "degrade_reason": reason,
        "message": msg,
    }


def resolve_screen_trade_date(
    store: MarketStore, trade_date: str | None = None, *, now: datetime | None = None
) -> str:
    """显式日期优先；默认按上海交易时段选今日或上一已收盘日。"""
    from src.market.application.session import build_session_status

    current = now or datetime.now(_TZ)
    current = current.replace(tzinfo=_TZ) if current.tzinfo is None else current.astimezone(_TZ)
    if trade_date:
        target = date.fromisoformat(trade_date).isoformat()
        if target > current.date().isoformat():
            raise ScreenSpotError(f"选股目标日 {target} 尚未到来")
        return target
    session = build_session_status(
        coverage={}, trading_days=store.trading_days(), now=current
    )
    target = (
        current.date().isoformat()
        if in_open_session(store, now=current)
        else session["expected_last_date"]
    )
    if not target:
        raise ScreenSpotError("无法确定选股目标交易日，请先同步交易日历")
    return str(target)


def ensure_today_quotes_for_screen(
    store: MarketStore,
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str] | None = None,
    min_coverage_ratio: float = DEFAULT_SCREEN_COVERAGE_FLOOR,
    force_refresh: bool = False,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """保证选股可读到目标日日 K；历史日只检查，今日才允许刷新 spot。

    返回字段：
    - status: skipped | refreshed | reused_after_busy | degraded_intraday
    - written: spot 写入行数
    - coverage: 度量快照
    - degraded: 是否降级放行（盘中软放行为 True）
    - degrade_reason: 降级原因（仅降级时有）
    - message: 中文说明
    """
    from src.market.infrastructure.sync_spot import apply_today_spot

    today = datetime.now(_TZ).date().isoformat()
    target = resolve_screen_trade_date(store, trade_date)
    floor = float(min_coverage_ratio)
    before = measure_day_coverage(store, target)

    # 现价只能补今天；历史/休市选股不能拿今天的 spot 修补目标日或污染日期。
    if target != today:
        if not coverage_ready(before, floor=floor):
            raise ScreenSpotError(
                f"选股目标日 {target} 行情不足（覆盖 {before['present']}/{before['listed']}="
                f"{before['ratio']:.1%}，需要 ≥{floor:.0%}），请先补齐该日历史行情"
            )
        return {
            "status": "skipped", "written": 0, "requested": len(codes),
            "coverage": before, "degraded": False,
            "message": f"选股目标日 {target} 行情已就绪（覆盖 {before['ratio']:.1%}），跳过现价重刷",
        }

    if not force_refresh and coverage_ready(before, floor=floor):
        msg = (
            f"当日行情已就绪（覆盖 {before['present']}/{before['listed']}="
            f"{before['ratio']:.1%}），跳过现价重刷"
        )
        logger.info(msg)
        return {
            "status": "skipped",
            "written": 0,
            "requested": len(codes),
            "coverage": before,
            "degraded": False,
            "message": msg,
        }

    if not codes:
        if coverage_ready(before, floor=floor):
            return {
                "status": "skipped",
                "written": 0,
                "requested": 0,
                "coverage": before,
                "degraded": False,
                "message": "无标的需刷新，且当日覆盖已达标",
            }
        soft = _intraday_soft_pass(
            store, before, floor=floor, requested=0, reason="no_refresh_targets"
        )
        if soft is not None:
            return soft
        raise ScreenSpotError(
            f"选股前当日行情不足（覆盖 {before['present']}/{before['listed']}="
            f"{before['ratio']:.1%}，需要 ≥{floor:.0%}），且没有可刷新标的；"
            f"当前不在盘中或覆盖低于 {INTRADAY_SOFT_PASS_FLOOR:.0%}，"
            "不能按「今日未完结」放行"
        )

    try:
        written = apply_today_spot(
            store,
            codes,
            instrument_types=instrument_types,
            raise_on_failure=True,
        )
    except Exception as exc:
        after = measure_day_coverage(store, today)
        if coverage_ready(after, floor=floor):
            # 写锁争用时别人（盘后同步）可能已经把今日写好了——选股放行
            msg = (
                f"现价重刷未写入，但当日行情已可用（覆盖 "
                f"{after['present']}/{after['listed']}={after['ratio']:.1%}），继续选股"
            )
            logger.warning("%s；原错误：%s", msg, exc)
            return {
                "status": "reused_after_busy",
                "written": 0,
                "requested": len(codes),
                "coverage": after,
                "degraded": False,
                "message": msg,
            }
        soft = _intraday_soft_pass(
            store, after, floor=floor, requested=len(codes), reason="spot_failed_intraday"
        )
        if soft is not None:
            logger.warning("%s；原错误：%s", soft["message"], exc)
            return soft
        detail = _humanize_ensure_error(exc, after, floor=floor)
        raise ScreenSpotError(detail) from exc

    after = measure_day_coverage(store, today)
    if not coverage_ready(after, floor=floor):
        soft = _intraday_soft_pass(
            store,
            after,
            floor=floor,
            requested=len(codes),
            written=int(written),
            reason="coverage_incomplete_intraday",
        )
        if soft is not None:
            return soft
        raise ScreenSpotError(
            f"选股前刷新后当日行情仍不足（覆盖 {after['present']}/{after['listed']}="
            f"{after['ratio']:.1%}，需要 ≥{floor:.0%}），已阻断选股；"
            f"当前不在盘中或覆盖低于 {INTRADAY_SOFT_PASS_FLOOR:.0%}，"
            "按真实数据缺失处理"
        )
    msg = f"当日现价已刷新，写入 {int(written)} 行（覆盖 {after['ratio']:.1%}）"
    return {
        "status": "refreshed",
        "written": int(written),
        "requested": len(codes),
        "coverage": after,
        "degraded": False,
        "message": msg,
    }


def _humanize_ensure_error(
    exc: BaseException, cov: Mapping[str, Any], *, floor: float
) -> str:
    text = str(exc).strip() or "未知错误"
    lower = text.lower()
    busy = (
        "locked" in lower
        or "busy" in lower
        or "行情库正忙" in text
        or "正被占用" in text
    )
    cov_txt = (
        f"当前覆盖 {cov.get('present', 0)}/{cov.get('listed', 0)}="
        f"{float(cov.get('ratio') or 0):.1%}（需要 ≥{floor:.0%}）"
    )
    if busy:
        return (
            f"选股前刷新当日行情失败：行情库正被同步占用，且{cov_txt}；"
            "当前不在盘中或覆盖过低，无法按「今日未完结」降级放行，"
            "请等盘后同步/日终重刷完成后再选股"
        )
    if ": " in text and text.split(": ", 1)[0].endswith("Error"):
        text = text.split(": ", 1)[1].strip() or text
    return f"选股前刷新当日行情失败，已阻断选股：{text}（{cov_txt}）"
