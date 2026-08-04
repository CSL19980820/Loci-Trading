"""通达信历史分时读取。

TDX 的历史分时接口返回每分钟的成交价和成交量，但不返回时间戳及
OHLC/成交额；这里保留源数据能证明的字段，用固定的 A 股交易时段补时间轴。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.market.infrastructure.store_codes import normalize_code


class TdxMinuteError(RuntimeError):
    """通达信历史分时读取失败。"""


# These are public TDX quote servers. Keep the pool small so a failed source
# does not turn a minute request into a long serial scan.
_SERVERS: tuple[tuple[str, int], ...] = (
    ("110.41.147.114", 7709),
    ("119.97.185.59", 7709),
    ("124.70.176.52", 7709),
    ("121.36.54.217", 7709),
)
_PERIODS = frozenset({"1"})
_MINUTES_PER_DAY = 240


def _trading_time_labels() -> tuple[str, ...]:
    morning = pd.date_range("09:31", periods=120, freq="min").strftime("%H:%M")
    afternoon = pd.date_range("13:01", periods=120, freq="min").strftime("%H:%M")
    return tuple(morning) + tuple(afternoon)


_TIME_LABELS = _trading_time_labels()


def _open_client() -> Any:
    """连接一个 TDX 行情服务器；tdxpy 只在实际请求时导入。"""
    try:
        from tdxpy.hq import TdxHq_API
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise TdxMinuteError("缺少通达信分钟依赖：tdxpy") from exc

    errors: list[str] = []
    for host, port in _SERVERS:
        client = TdxHq_API(auto_retry=False, raise_exception=True)
        try:
            client.connect(host, port, time_out=8)
            return client
        except Exception as exc:
            errors.append(f"{host}:{port} {type(exc).__name__}: {exc}")
            _close_client(client)
    raise TdxMinuteError("通达信服务器全部连接失败 -> " + " | ".join(errors[-4:]))


def _close_client(client: Any) -> None:
    for name in ("disconnect", "close"):
        close = getattr(client, name, None)
        if not callable(close):
            continue
        try:
            close()
        except Exception:
            pass
        return


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["datetime", "close", "volume"])


def _rows_to_frame(rows: Any, day: str) -> pd.DataFrame:
    if not isinstance(rows, list) or not rows:
        return _empty_frame()
    if len(rows) != _MINUTES_PER_DAY:
        raise TdxMinuteError(
            f"{day} 历史分时行数异常：通达信返回 {len(rows)}，预期 {_MINUTES_PER_DAY}"
        )

    prices = pd.to_numeric(
        pd.Series([item.get("price") if isinstance(item, dict) else None for item in rows]),
        errors="coerce",
    )
    volumes = pd.to_numeric(
        pd.Series([item.get("vol") if isinstance(item, dict) else None for item in rows]),
        errors="coerce",
    )
    if prices.isna().any() or volumes.isna().any():
        raise TdxMinuteError(f"{day} 历史分时含无法解析的价格或成交量")

    return pd.DataFrame(
        {
            "datetime": [f"{day} {label}" for label in _TIME_LABELS],
            "close": prices.astype(float).tolist(),
            "volume": volumes.astype(float).tolist(),
        }
    )


def _fetch_day(client: Any, code: str, day: str) -> pd.DataFrame:
    market = 1 if code.startswith("6") else 0
    rows = client.get_history_minute_time_data(market, code, int(day.replace("-", "")))
    return _rows_to_frame(rows, day)


def _normalize_day(value: str) -> str:
    parsed = pd.to_datetime(str(value).strip()[:10], errors="coerce")
    if pd.isna(parsed):
        raise TdxMinuteError(f"交易日无效：{value}")
    return parsed.date().isoformat()


def fetch_minute_bars(
    code: str,
    *,
    period: str = "1",
    days: int = 1,
    trade_date: str | None = None,
) -> pd.DataFrame:
    """读取 1 分钟历史分时，不写行情库。"""
    plain = normalize_code(code)
    scale = str(period).strip()
    if scale not in _PERIODS:
        raise TdxMinuteError(f"通达信暂不支持的分钟周期：{period}")

    requested_days = max(1, int(days))
    if trade_date:
        target_days = [_normalize_day(trade_date)]
    else:
        # days 表示交易日数量；周末/节假日需要向前多探几天。
        span = min(90, max(7, requested_days * 3 + 3))
        today = date.today()
        target_days = [
            (today - timedelta(days=offset)).isoformat() for offset in range(span)
        ]

    client = _open_client()
    frames: list[pd.DataFrame] = []
    try:
        for day in target_days:
            frame = _fetch_day(client, plain, day)
            if frame.empty:
                if trade_date:
                    raise TdxMinuteError(f"{plain} 在 {day} 无历史分时")
                continue
            frames.append(frame)
            if trade_date or len(frames) >= requested_days:
                break
    finally:
        _close_client(client)

    if not frames:
        raise TdxMinuteError(f"{plain} 最近 {requested_days} 个交易日无历史分时")
    return pd.concat(reversed(frames), ignore_index=True)
