"""当日 spot 日 K 的单飞刷新与逐代码来源回执。"""
from __future__ import annotations

from src.shared.clock import utc_now

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
import hashlib
import logging
import sqlite3
import threading
import time
from typing import Any, Mapping, Sequence, TypeVar

import pandas as pd

from src.market.infrastructure.store import MarketStore, normalize_code
from src.market.infrastructure.store_quote_payload import partition_valid_ohlc_rows
from src.market.infrastructure.turnover_math import (
    compute_turnover,
    normalize_trade_volume,
)
from src.market.infrastructure.turnover_repair import load_shares_asof
from src.market.infrastructure.write_lock import MarketWriteBusy, market_write_lock

logger = logging.getLogger(__name__)

from src.market.infrastructure.sync_spot_receipts import (
    _persist_spot_failure_receipts,
    _spot_receipts,
)

T = TypeVar("T")

#: spot 写库遇 locked/busy 时的退避（秒）；总等待远短于 busy_timeout，避免选股干等。
_SPOT_WRITE_RETRY_DELAYS = (0.05, 0.15, 0.4, 1.0, 2.0, 4.0)
_SPOT_DB_BUSY_MSG = "行情库正忙（写入被占用），稍后重试仍失败；请稍后再试或先停掉同步任务"


def fallback_used(attempts: Sequence[Mapping[str, Any]], selected_source: str) -> bool:
    """仅在最终命中另一来源时标记 fallback；全失败不伪装成已降级成功。"""
    return bool(selected_source) and any(
        str(item.get("source_id") or "") != selected_source
        and str(item.get("state") or "") in {"failed", "empty", "skipped"}
        for item in attempts
    )


def dated_spot_adapter_ids() -> list[str] | None:
    """写当日 K 线时只用「自报交易日」的现价源。

    不声明交易日的源（东财现价表没有日期列）只能由本地补今天，落在工作日的
    法定节假日会把昨天的收盘快照写成当日 K 线，还会往 ``trading_calendar``
    插一个假交易日——T+N 复盘、回测持有期、会话闸门会跟着整体错位一天。
    返回 ``None`` 表示不加限制（无法读取注册表时不拦，保持可用）。
    """
    try:
        from src.market.infrastructure.adapters import (
            LANE_SPOT_BATCH,
            enabled_adapter_ids,
            get_adapter,
        )

        ids = [
            adapter_id
            for adapter_id in enabled_adapter_ids(LANE_SPOT_BATCH)
            if get_adapter(adapter_id).meta.spot_declares_trade_date
        ]
    except Exception:  # pragma: no cover - 注册表不可读时不改变原行为
        return None
    return ids or None


def _source_url(adapter_id: str) -> str:
    """读取适配器声明的站点地址；不能从运行时请求参数反推就保持空。"""
    if not adapter_id or adapter_id == "live":
        return ""
    try:
        from src.market.infrastructure.adapters import get_adapter

        return str(get_adapter(adapter_id).meta.base_url or "")
    except Exception:
        return ""


@dataclass
class _SpotRefreshFlight:
    event: threading.Event = field(default_factory=threading.Event)
    result: int = 0
    error: Exception | None = None
    receipts: list[dict[str, Any]] = field(default_factory=list)
    completed_at: float = 0.0


_SPOT_REFRESH_TTL_SECONDS = 30.0
#: 失败结果的重放窗口。成功的一轮可以放心复用 30 秒，失败的不行：源抽一次
#: 风就会被原样重放给之后 30 秒内的每一个调用方，行情台与选股集体空窗，且
#: 没有任何人去重试。留 3 秒只为挡住同一瞬间涌进来的重试风暴。
_SPOT_REFRESH_FAILURE_TTL_SECONDS = 3.0
_SPOT_REFRESH_CONDITION = threading.Condition()
#: (库路径, 交易日, batch_size, 代码集合指纹)
_SpotRefreshKey = tuple[str, str, int, str]
_SPOT_REFRESH_FLIGHTS: dict[_SpotRefreshKey, _SpotRefreshFlight] = {}


def _quote_number(source: Mapping[str, Any], name: str, fallback: float) -> float:
    """取一个数值字段；缺失 / 非数 / NaN 一律回落。

    提到模块级而不是留在循环体里：全市场 spot 一次 5500 行，循环内 ``def`` 每行
    造一个只用六次的函数对象；而且闭包捕获 ``quote`` 会让静态检查无法判断它是
    否延迟调用（ruff B023），把一个真 bug 的形状留在了没有 bug 的地方。
    """
    try:
        value = float(source.get(name, fallback))
    except (TypeError, ValueError):
        return fallback
    return value if pd.notna(value) else fallback


def _live_quotes_to_spot_frame(quotes: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """把富行情转换为 spot 入库所需的最小 OHLCV 字段。

    未声明交易日的报价会被丢弃：替源补一个 ``date.today()`` 会让节假日的
    陈旧快照被盖上今天的日期落库，还会顺带往 ``trading_calendar`` 插一个
    假交易日（T+N 复盘、回测、会话闸门全跟着错位）。
    """
    rows: list[dict[str, Any]] = []
    for quote in quotes:
        try:
            close = float(quote["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if close <= 0:
            continue
        trade_date = str(quote.get("trade_date") or quote.get("date") or "").strip()[:10]
        if not trade_date:
            continue
        rows.append(
            {
                "code": str(quote.get("code") or ""),
                "date": trade_date,
                "open": _quote_number(quote, "open", close),
                "high": _quote_number(quote, "high", close),
                "low": _quote_number(quote, "low", close),
                "close": close,
                "volume": _quote_number(quote, "volume", 0.0),
                "amount": _quote_number(quote, "amount", 0.0),
            }
        )
    return pd.DataFrame(
        rows,
        columns=["code", "date", "open", "high", "low", "close", "volume", "amount"],
    )


def apply_today_spot(
    store: MarketStore,
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str] | None = None,
    batch_size: int = 400,
    live_quotes: Sequence[Mapping[str, Any]] | None = None,
    raise_on_failure: bool = False,
    source_receipts: list[dict[str, Any]] | None = None,
) -> int:
    """用 spot_batch 线路将当日 OHLC 写入行情仓并可返回逐代码回执。"""
    from src.market.infrastructure.adapters import AdapterError

    types = instrument_types or {}
    normalized = [normalize_code(code) for code in codes]
    if not normalized or not _is_current_trading_day(store):
        return 0

    def _run_once(
        *,
        live: Sequence[Mapping[str, Any]] | None,
        receipts: list[dict[str, Any]],
    ) -> int:
        try:
            with market_write_lock(store.db_path, label="spot"):
                return _apply_today_spot_once(
                    store,
                    normalized,
                    types,
                    batch_size=batch_size,
                    live_quotes=live,
                    source_receipts=receipts,
                )
        except MarketWriteBusy as exc:
            raise AdapterError(str(exc)) from exc

    if live_quotes is not None:
        receipts: list[dict[str, Any]] = []
        try:
            return _run_once(live=live_quotes, receipts=receipts)
        except AdapterError as exc:
            logger.warning("实时行情失败：%s", exc)
            if raise_on_failure:
                raise
            return 0
        finally:
            _extend_receipts(source_receipts, receipts)

    key = _spot_refresh_key(store, normalized, types, batch_size)
    flight, owner = _claim_spot_refresh(key)
    if not owner:
        _extend_receipts(source_receipts, flight.receipts)
        if flight.error is not None and raise_on_failure:
            raise flight.error
        return flight.result
    receipts: list[dict[str, Any]] = []
    try:
        try:
            written = _run_once(live=None, receipts=receipts)
        except Exception as exc:
            _complete_spot_refresh(flight, result=0, error=exc, receipts=receipts)
            _extend_receipts(source_receipts, receipts)
            if isinstance(exc, AdapterError):
                logger.warning("实时行情失败：%s", exc)
                if not raise_on_failure:
                    return 0
            raise
        _complete_spot_refresh(flight, result=written, error=None, receipts=receipts)
    finally:
        # owner 被 BaseException（关站 / Ctrl-C / 线程被杀）打断时也要放行：
        # follower 挂在无超时的 event.wait() 上，少设一次就是永久占住线程。
        if not flight.event.is_set():
            _complete_spot_refresh(
                flight,
                result=0,
                error=RuntimeError("当日现价刷新被中断"),
                receipts=receipts,
            )
    _extend_receipts(source_receipts, receipts)
    return written


def _is_current_trading_day(store: MarketStore) -> bool:
    """今天是否开市：行情库日历里有今天，或交易所公告日程判定开市（节假日不再按工作日刷现价）。"""
    from src.market.infrastructure.exchange_calendar import exchange_is_open

    today = date.today().isoformat()
    days = store.trading_days()
    if today in days:
        return True
    if days and today <= max(days):
        return False
    return exchange_is_open(today)


def _spot_refresh_key(
    store: MarketStore,
    codes: Sequence[str],
    instrument_types: Mapping[str, str],
    batch_size: int,
) -> _SpotRefreshKey:
    """单飞 key：库路径 + 交易日 + batch_size + **代码集合的稳定指纹**。

    原来把全部 ``(code, type)`` 元组直接塞进 key，两个后果：一是每次调用都要
    排序并哈希一条 5500 元素的元组；二是 board / screen / sync / ops 几条调用
    方只要类型映射写法有一点差别（``None`` 与「全 STOCK 字典」是同一个意思，
    却是不同的 key），刷同一批全市场代码时也永远合不了流，单飞形同虚设。

    改成 sha1 指纹，并先把类型归一（空 → STOCK）：等价于「解析出来的 symbol
    集合相同就合流」，语义不变（真正的 STOCK/INDEX 差异仍是不同 key），而 key
    退化成一个定长字符串。
    """
    digest = hashlib.sha1(usedforsecurity=False)
    for code in sorted(set(codes)):
        kind = str(instrument_types.get(code, "") or "STOCK").upper()
        digest.update(f"{code}:{kind}\n".encode())
    return (
        str(store.db_path.resolve()),
        date.today().isoformat(),
        batch_size,
        digest.hexdigest(),
    )


def _claim_spot_refresh(key: _SpotRefreshKey) -> tuple[_SpotRefreshFlight, bool]:
    with _SPOT_REFRESH_CONDITION:
        current = _SPOT_REFRESH_FLIGHTS.get(key)
        if current is not None and current.event.is_set():
            # 失败只做极短负缓存：整整 30 秒重放同一个异常，等于把一次抖动
            # 放大成半分钟的集体停摆，且期间没有任何人真的去重试。
            ttl = (
                _SPOT_REFRESH_FAILURE_TTL_SECONDS
                if current.error is not None
                else _SPOT_REFRESH_TTL_SECONDS
            )
            if time.monotonic() - current.completed_at > ttl:
                _SPOT_REFRESH_FLIGHTS.pop(key, None)
                current = None
        if current is None:
            current = _SpotRefreshFlight()
            _SPOT_REFRESH_FLIGHTS[key] = current
            return current, True
    current.event.wait()
    return current, False


def _complete_spot_refresh(
    flight: _SpotRefreshFlight,
    *,
    result: int,
    error: Exception | None,
    receipts: Sequence[Mapping[str, Any]],
) -> None:
    with _SPOT_REFRESH_CONDITION:
        flight.result = result
        flight.error = error
        flight.receipts = [dict(receipt) for receipt in receipts]
        flight.completed_at = time.monotonic()
        flight.event.set()
        _SPOT_REFRESH_CONDITION.notify_all()


def _extend_receipts(
    target: list[dict[str, Any]] | None, receipts: Sequence[Mapping[str, Any]]
) -> None:
    if target is not None:
        target.extend(dict(receipt) for receipt in receipts)


def _is_db_locked(exc: BaseException) -> bool:
    """识别 SQLite locked/busy（含异常链）。"""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, sqlite3.OperationalError):
            text = str(current).lower()
            if "locked" in text or "busy" in text:
                return True
        current = current.__cause__ or current.__context__
    return False


def _retry_db_write(op: Callable[[], T], *, what: str) -> T:
    """对 persist/watermark 等写库做有限次退避；非锁错误立即抛出。"""
    delays = _SPOT_WRITE_RETRY_DELAYS
    last: BaseException | None = None
    for attempt, delay in enumerate((*delays, None)):
        try:
            return op()
        except Exception as exc:
            last = exc
            if not _is_db_locked(exc) or delay is None:
                raise
            logger.warning(
                "%s 遇库忙，%.2fs 后重试（%d/%d）：%s",
                what,
                delay,
                attempt + 1,
                len(delays),
                exc,
            )
            time.sleep(delay)
    assert last is not None  # pragma: no cover — loop always assigns
    raise last


def _humanize_spot_write_error(exc: BaseException) -> str:
    """用户可见文案：锁争用人话，禁止 OperationalError 原文。"""
    if _is_db_locked(exc):
        return _SPOT_DB_BUSY_MSG
    text = str(exc).strip()
    if text.startswith("spot 入库失败："):
        return text
    # 剥掉 sqlite3.OperationalError: 等类型前缀，避免刷进企微/任务历史
    if ": " in text and text.split(": ", 1)[0].endswith("Error"):
        text = text.split(": ", 1)[1].strip() or text
    return f"spot 入库失败：{text}"


def _safe_normalize_code(value: str) -> str | None:
    """归一失败返回 None（老逻辑是逐行 try/except 跳过），供整列 map 复用。"""
    try:
        return normalize_code(value)
    except Exception:
        return None


def _rows_by_code(frame: pd.DataFrame) -> dict[str, int]:
    """按归一代码统计行数；未解析代码（NaN）不计，与逐行 try 的老口径一致。"""
    if frame is None or frame.empty or "norm_code" not in frame.columns:
        return {}
    return {
        str(code): int(number)
        for code, number in frame["norm_code"].value_counts().items()
    }


def _apply_today_spot_once(
    store: MarketStore,
    normalized: Sequence[str],
    instrument_types: Mapping[str, str],
    *,
    batch_size: int,
    live_quotes: Sequence[Mapping[str, Any]] | None,
    source_receipts: list[dict[str, Any]] | None = None,
) -> int:
    """执行一轮真实 spot 拉取；所有不可入库终态均写逐代码失败回执。"""
    from src.market.infrastructure.adapters import AdapterError, fetch_spot_routed
    from src.market.infrastructure.turnover_repair import backfill_missing_turnover

    route_attempts: list[dict[str, Any]] = []
    adapter_id = ""
    today = date.today().isoformat()
    try:
        if live_quotes is None:
            spot, adapter_id = fetch_spot_routed(
                normalized,
                instrument_types=dict(instrument_types) or None,
                batch_size=batch_size,
                adapter_ids=dated_spot_adapter_ids(),
                receipt=route_attempts,
            )
        else:
            spot = _live_quotes_to_spot_frame(live_quotes)
            adapter_id = "live"
            route_attempts.append(
                {
                    "source_id": adapter_id,
                    "state": "selected" if not spot.empty else "empty",
                    "checked_at": utc_now(),
                    "rows": int(len(spot)),
                    "fields": [str(column) for column in spot.columns],
                }
            )
        if spot is None or spot.empty:
            raise AdapterError("实时行情返回空数据")

        # 归一化只跑一轮：先按「原始代码去重」建缓存，再整列 map；日期也整列
        # 向量化。老逻辑是「统计源行数」「统计拒绝行」「建 bar」各扫一遍 5500 行，
        # normalize_code 被调用约 1.1 万次，pd.Timestamp 另有 1.1 万次逐行构造。
        raw_codes = spot["code"].astype(str)
        code_lookup = {raw: _safe_normalize_code(raw) for raw in raw_codes.unique()}
        spot = spot.assign(
            norm_code=raw_codes.map(code_lookup),
            trade_day=pd.to_datetime(spot["date"], format="ISO8601").dt.strftime(
                "%Y-%m-%d"
            ),
        )

        trade_dates = sorted(set(spot["trade_day"].tolist()))
        if today not in trade_dates:
            raise AdapterError(f"实时行情日期落后，未返回 {today}")

        source_rows_by_code = _rows_by_code(spot)
        spot, rejected = partition_valid_ohlc_rows(spot)
        rejected_ohlc_by_code = _rows_by_code(rejected)

        # 与下面的 backfill_missing_turnover 共用这一份 as-of 股本：
        # load_shares_asof 固定倒扫 60 个交易日（约 33 万行），一轮只该算一次。
        shares_map = load_shares_asof(store, today)
        bars: list[dict[str, Any]] = []
        latest_by_code: dict[str, str] = {}
        requested_codes = set(normalized)
        wanted = spot["norm_code"].isin(requested_codes)
        fresh = wanted & (spot["trade_day"] == today)
        # 落后日只留每个代码首次出现的那天（老逻辑的 setdefault）。
        stale_frame = spot.loc[wanted & ~fresh, ["norm_code", "trade_day"]].drop_duplicates(
            subset=["norm_code"], keep="first"
        )
        stale_dates: dict[str, str] = {
            str(row.norm_code): str(row.trade_day)
            for row in stale_frame.itertuples(index=False)
        }
        for row in spot.loc[fresh].itertuples(index=False):
            code = str(row.norm_code)
            shares = shares_map.get(code)
            amount = float(row.amount)
            close = float(row.close)
            volume = normalize_trade_volume(
                float(row.volume), amount=amount, close=close
            )
            turnover = compute_turnover(
                volume=volume, amount=amount, close=close, shares=shares
            )
            if turnover is None:
                shares = None
            bars.append(
                {
                    "code": code,
                    "date": today,
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                    "outstanding_share": shares,
                    "turnover": turnover,
                }
            )
            latest_by_code[code] = today

        receipts = _spot_receipts(
            normalized,
            latest_by_code,
            route_attempts,
            adapter_id=adapter_id,
            trade_date=today,
            stale_dates=stale_dates,
            source_rows_by_code=source_rows_by_code,
            rejected_ohlc_by_code=rejected_ohlc_by_code,
        )
        source_tag = f"{adapter_id}_spot"
        written = _retry_db_write(
            lambda: store.persist_quote_bar_receipts(
                receipts, bars, source=source_tag
            ),
            what="spot 日K入库",
        )
        _extend_receipts(source_receipts, receipts)
        if latest_by_code:
            items = list(latest_by_code.items())
            _retry_db_write(
                lambda: store.set_watermarks(items, status="ok", source=source_tag),
                what="spot 水位",
            )
        if bars:
            _retry_db_write(
                lambda: backfill_missing_turnover(
                    store, trade_dates=[today], shares_asof={today: shares_map}
                ),
                what="spot 换手回填",
            )
        return written
    except Exception as exc:
        # 整批挂掉用人话摘要，避免 OperationalError/技术栈刷进企微/回执
        human = (
            "当日现价暂时拉不到（源忙或断网），已跳过，不影响已有历史日K"
            if isinstance(exc, AdapterError)
            else _humanize_spot_write_error(exc)
        )
        receipts = _persist_spot_failure_receipts(
            store,
            normalized,
            route_attempts,
            adapter_id=adapter_id,
            error=human,
        )
        _extend_receipts(source_receipts, receipts)
        if isinstance(exc, AdapterError):
            raise
        raise AdapterError(human) from exc
