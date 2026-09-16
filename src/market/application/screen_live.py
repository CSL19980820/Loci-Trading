"""盘中选股：自己拉实时日 K，只叠内存面板，不写 market.db。

14:50 尾盘选股如果去 ``apply_today_spot`` / 镜像热库，就会跟盘中增量抢同一把
写锁、同一份 WAL。选股要的是「此刻的价」，不是「库里那根可能还是早上的
spot」。历史 K 线继续只读热库；今日这一根走 ``spot_batch``，叠到面板上就散。

铁律：本模块不调 ``apply_today_spot``、不拿 ``market_write_lock``。
"""
from __future__ import annotations

from datetime import date, datetime
import logging
import math
import threading
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from src.market.infrastructure.store_codes import normalize_code
from src.market.infrastructure.store_panel import _consolidate
from src.market.infrastructure.turnover_math import compute_turnover, normalize_trade_volume

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")
_OPEN_MIN = 9 * 60 + 15
_CLOSE_MIN = 15 * 60
_CACHE_TTL_SEC = 20.0

_CACHE_LOCK = threading.Lock()
_CACHE_KEY = ""
_CACHE_AT = 0.0
_CACHE_BARS: dict[str, dict[str, float]] = {}
_CACHE_ERROR: BaseException | None = None
_INFLIGHT: threading.Event | None = None
_INFLIGHT_KEY = ""


class ScreenLiveError(RuntimeError):
    """盘中选股拉不到实时行情（用户可见中文）。"""


def in_live_screen_clock(now: datetime | None = None) -> bool:
    """工作日 [09:15, 15:00)。节假日粗判：周末必否，交易日交给调用方。"""
    if now is None:
        current = datetime.now(_TZ)
    elif now.tzinfo is None:
        current = now.replace(tzinfo=_TZ)
    else:
        current = now.astimezone(_TZ)
    if current.weekday() >= 5:
        return False
    minutes = current.hour * 60 + current.minute
    return _OPEN_MIN <= minutes < _CLOSE_MIN


def should_overlay_live(
    trade_date: str | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    """目标日是「今天」且仍在盘中：必须叠实时，禁止回退昨日本地日 K。"""
    if not in_live_screen_clock(now):
        return False
    if now is None:
        today = date.today().isoformat()
    else:
        stamp = now if now.tzinfo else now.replace(tzinfo=_TZ)
        today = stamp.astimezone(_TZ).date().isoformat()
    requested = str(trade_date or "").strip()[:10]
    return not requested or requested == today


def reset_live_spot_cache() -> None:
    """测试用：清掉进程内实时快照。"""
    global _CACHE_KEY, _CACHE_AT, _CACHE_BARS, _CACHE_ERROR, _INFLIGHT, _INFLIGHT_KEY
    with _CACHE_LOCK:
        _CACHE_KEY = ""
        _CACHE_AT = 0.0
        _CACHE_BARS = {}
        _CACHE_ERROR = None
        _INFLIGHT = None
        _INFLIGHT_KEY = ""


def _remember_live_spot(
    key: str, bars: dict[str, dict[str, float]], error: BaseException | None
) -> None:
    global _CACHE_KEY, _CACHE_AT, _CACHE_BARS, _CACHE_ERROR
    import time

    _CACHE_KEY = key
    _CACHE_AT = time.monotonic()
    _CACHE_BARS = bars
    _CACHE_ERROR = error


def fetch_live_spot_bars(
    codes: Sequence[str],
    *,
    instrument_types: Mapping[str, str] | None = None,
    strict: bool = False,
) -> dict[str, dict[str, float]]:
    """拉今日 spot；strict绕过已完成缓存并要求全部代码真实OHLCV齐全。"""
    import time

    from src.market.infrastructure.adapters import AdapterError, fetch_spot_routed
    from src.market.infrastructure.sync_spot import dated_spot_adapter_ids

    global _INFLIGHT, _INFLIGHT_KEY

    normalized = [normalize_code(code) for code in codes]
    if not normalized:
        return {}
    today = date.today().isoformat()
    key = f"{today}:{int(strict)}:{','.join(sorted(set(normalized)))}"

    with _CACHE_LOCK:
        if (
            not strict
            and _CACHE_KEY == key
            and _CACHE_BARS
            and time.monotonic() - _CACHE_AT < _CACHE_TTL_SEC
        ):
            return {code: dict(bar) for code, bar in _CACHE_BARS.items()}
        if not strict and _CACHE_KEY == key and _CACHE_ERROR is not None:
            if time.monotonic() - _CACHE_AT < _CACHE_TTL_SEC:
                raise ScreenLiveError(str(_CACHE_ERROR)) from _CACHE_ERROR
        if _INFLIGHT is None:
            _INFLIGHT = threading.Event()
            _INFLIGHT_KEY = key
            owner = True
        else:
            owner = False
            waiter = _INFLIGHT
            waiter_key = _INFLIGHT_KEY

    if not owner:
        if not waiter.wait(timeout=90):
            raise ScreenLiveError("盘中选股等待实时行情超时")
        if waiter_key != key:
            return fetch_live_spot_bars(codes, instrument_types=instrument_types, strict=strict)
        with _CACHE_LOCK:
            if _CACHE_KEY == key and _CACHE_BARS:
                return {code: dict(bar) for code, bar in _CACHE_BARS.items()}
            if _CACHE_KEY == key and _CACHE_ERROR is not None:
                raise ScreenLiveError(str(_CACHE_ERROR)) from _CACHE_ERROR
        raise ScreenLiveError("盘中选股实时行情未返回")

    try:
        spot, _aid = fetch_spot_routed(
            normalized,
            instrument_types=dict(instrument_types) if instrument_types else None,
            adapter_ids=dated_spot_adapter_ids(),
        )
        bars = _spot_frame_to_bars(spot, today, strict=strict)
        if strict:
            missing = sorted(set(normalized) - set(bars))
            if missing:
                examples = ", ".join(missing[:5])
                raise ScreenLiveError(
                    f"严格盘中行情缺少{len(missing)}/{len(set(normalized))}只合格当日OHLCV"
                    f"（示例：{examples}），已中止，不使用旧日K或回填价格"
                )
            bars = {code: bars[code] for code in sorted(set(normalized))}
        if not bars:
            raise ScreenLiveError("盘中选股实时行情为空或日期不是今天")
        with _CACHE_LOCK:
            _remember_live_spot(key, bars, None)
        return {code: dict(bar) for code, bar in bars.items()}
    except ScreenLiveError as exc:
        with _CACHE_LOCK:
            _remember_live_spot(key, {}, exc)
        raise
    except AdapterError as exc:
        err = ScreenLiveError(f"盘中选股拉不到实时行情：{exc}")
        with _CACHE_LOCK:
            _remember_live_spot(key, {}, err)
        raise err from exc
    except Exception as exc:
        err = ScreenLiveError(f"盘中选股拉不到实时行情：{exc}")
        with _CACHE_LOCK:
            _remember_live_spot(key, {}, err)
        raise err from exc
    finally:
        with _CACHE_LOCK:
            done = _INFLIGHT
            _INFLIGHT = None
            _INFLIGHT_KEY = ""
        if done is not None:
            done.set()


def overlay_live_day(
    panels: dict[str, Any],
    bars: Mapping[str, Mapping[str, float]],
    trade_date: str,
) -> dict[str, Any]:
    """把今日实时 OHLCV 叠进已加载的历史面板；缺今日就追加一行。"""
    if not bars:
        return panels
    out: dict[str, Any] = {}
    for field, panel in panels.items():
        if not isinstance(panel, pd.DataFrame):
            out[field] = panel
            continue
        work = panel.copy()
        if trade_date not in work.index:
            extra = pd.DataFrame(
                index=pd.Index([trade_date], name="trade_date"),
                columns=work.columns,
                dtype=float,
            )
            work = pd.concat([work, extra])
            work.index.name = "trade_date"
        for code, bar in bars.items():
            if code not in work.columns:
                continue
            value = _field_value(field, bar, work, code)
            if value is not None:
                work.loc[trade_date, code] = value
        out[field] = _consolidate(work)
    _fill_turnover(out, bars, trade_date)
    return out


def _field_value(
    field: str,
    bar: Mapping[str, float],
    work: pd.DataFrame,
    code: str,
) -> float | None:
    if field == "__raw_close":
        raw = bar.get("close")
        return float(raw) if raw is not None else None
    if field == "outstanding_share":
        shares = bar.get("outstanding_share")
        if shares is not None:
            return float(shares)
        if len(work.index) >= 2:
            prev = work[code].iloc[-2]
            return float(prev) if pd.notna(prev) else None
        return None
    raw = bar.get(field)
    return float(raw) if raw is not None else None


def _fill_turnover(
    panels: dict[str, Any],
    bars: Mapping[str, Mapping[str, float]],
    trade_date: str,
) -> None:
    turnover = panels.get("turnover")
    close = panels.get("close")
    if not isinstance(turnover, pd.DataFrame) or not isinstance(close, pd.DataFrame):
        return
    if trade_date not in turnover.index or trade_date not in close.index:
        return
    volume = panels.get("volume")
    amount = panels.get("amount")
    shares_panel = panels.get("outstanding_share")
    for code in bars:
        if code not in turnover.columns:
            continue
        stored = bars[code].get("turnover")
        vol = (
            float(volume.loc[trade_date, code])
            if isinstance(volume, pd.DataFrame) and code in volume.columns
            else None
        )
        amt = (
            float(amount.loc[trade_date, code])
            if isinstance(amount, pd.DataFrame) and code in amount.columns
            else None
        )
        close_v = float(close.loc[trade_date, code]) if code in close.columns else None
        shares = (
            float(shares_panel.loc[trade_date, code])
            if isinstance(shares_panel, pd.DataFrame) and code in shares_panel.columns
            else None
        )
        if shares is not None and pd.isna(shares):
            shares = None
        value = compute_turnover(
            volume=vol, amount=amt, close=close_v, shares=shares, stored=stored
        )
        if value is not None:
            turnover.loc[trade_date, code] = value
    panels["turnover"] = _consolidate(turnover)


def _row_number(row: Any, name: str, fallback: float) -> float:
    """从 itertuples 行里取一个数；缺失 / 非数 / NaN / 0 一律回落。

    注意 ``or fallback``——0 也回落：spot 截面里 0 开盘价意味着「源没给」而不是
    「开在 0 元」。这是原实现的语义，搬到模块级时逐字保留。

    提到模块级而不是留在循环体里：全市场截面一次 5000+ 行，循环内 ``def`` 每行
    造一个只用六次的函数对象，而闭包捕获 ``row`` 让静态检查无法判断它是否延迟
    调用（ruff B023）——把一个真 bug 的形状留在了没有 bug 的地方。
    """
    try:
        value = float(getattr(row, name, fallback) or fallback)
    except (TypeError, ValueError):
        return fallback
    return value if pd.notna(value) else fallback


def _spot_frame_to_bars(
    spot: pd.DataFrame | None, today: str, *, strict: bool = False,
) -> dict[str, dict[str, float]]:
    if spot is None or spot.empty:
        return {}
    frame = spot.copy()
    if "code" not in frame.columns:
        return {}
    date_col = "date" if "date" in frame.columns else "trade_date"
    if date_col not in frame.columns:
        return {}
    bars: dict[str, dict[str, float]] = {}
    for row in frame.itertuples(index=False):
        try:
            code = normalize_code(str(getattr(row, "code", "") or ""))
            close = float(getattr(row, "close", 0) or 0)
            day = str(getattr(row, date_col, "") or "")[:10]
        except Exception:
            continue
        if not code or close <= 0 or day != today:
            continue

        if strict:
            try:
                bar = {name: float(getattr(row, name))
                       for name in ("open", "high", "low", "close", "volume")}
            except (AttributeError, TypeError, ValueError):
                continue
            if not all(math.isfinite(value) for value in bar.values()):
                continue
            if any(bar[name] < 0 for name in ("open", "high", "low")) or bar["volume"] < 0:
                continue
            # 完整、明确的零量报价可以表示停牌；有成交时OHLC仍必须为正。
            if bar["volume"] > 0 and any(bar[name] <= 0 for name in ("open", "high", "low")):
                continue
            # Routed行情已归一为股；严格路径不得再根据amount猜测并改写成交量。
            bar["amount"] = _row_number(row, "amount", 0.0)
            bars[code] = bar
            continue

        amount = _row_number(row, "amount", 0.0)
        volume = normalize_trade_volume(
            _row_number(row, "volume", 0.0), amount=amount, close=close
        )
        bars[code] = {
            "open": _row_number(row, "open", close),
            "high": _row_number(row, "high", close),
            "low": _row_number(row, "low", close),
            "close": close,
            "volume": volume,
            "amount": amount,
        }
    return bars


__all__ = [
    "ScreenLiveError",
    "fetch_live_spot_bars",
    "in_live_screen_clock",
    "overlay_live_day",
    "reset_live_spot_cache",
    "should_overlay_live",
]
