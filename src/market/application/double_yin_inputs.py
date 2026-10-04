"""倍量阴两阶段选股的外部数据边界；不读行情仓、不复用跨次行情快照。"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date, datetime, time as daytime, timedelta
import math
import re
import time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.http_client import market_get

SHANGHAI = ZoneInfo("Asia/Shanghai")
OPENING_RETRY_SECONDS = 20.0
OPENING_RETRY_INTERVAL = 1.0
CONSUMER_INDUSTRIES = frozenset({
    "食品饮料", "家电", "商贸零售", "纺织服装", "农林牧渔", "轻工制造",
    "休闲服务", "社会服务", "美容护理",
})
INDUSTRY_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
Progress = Callable[[str, float, str], None]


class RealtimeInputError(ValueError):
    """数据不足以完成本次遴选；snapshot 可供任务保留失败覆盖证据。"""

    def __init__(self, message: str, *, snapshot: dict[str, Any] | None = None):
        super().__init__(message)
        self.snapshot = snapshot or {}


@dataclass
class DoubleYinMarketInputs:
    trade_date: str
    panels: dict[str, Any]
    names: dict[str, str]
    data_snapshot: dict[str, Any]
    histories: dict[str, pd.DataFrame] = field(default_factory=dict)


def _stamp() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _progress(callback: Progress | None, phase: str, percent: float, message: str) -> None:
    if callback is not None:
        callback(phase, percent, message)


def _codes(codes: list[str]) -> list[str]:
    wanted = sorted(set(str(code).strip() for code in codes))
    if any(not re.fullmatch(r"\d{6}", code) for code in wanted):
        raise RealtimeInputError("证券代码必须为六位数字")
    return wanted


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _opening_reason(row: dict[str, Any], trade_date: str, now: datetime) -> str:
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        return "源证券名称缺失，不能核验ST或退市状态"
    if str(row.get("trade_date") or "") != trade_date:
        return "源报价日期不是目标交易日"
    try:
        clock = datetime.strptime(str(row.get("trade_time") or ""), "%H:%M:%S").time()
    except ValueError:
        return "源报价时间缺失或无效"
    if clock < daytime(9, 25):
        return "源报价早于09:25，竞价尚未定盘"
    if clock >= daytime(9, 30):
        return "源报价已进入09:30连续竞价，不作为集合竞价定盘事实"
    source_at = datetime.combine(date.fromisoformat(trade_date), clock, tzinfo=SHANGHAI)
    if source_at > now + timedelta(seconds=5):
        return "源报价时间晚于现场请求时间"
    open_price, volume = _number(row.get("open")), _number(row.get("volume"))
    if open_price is None or open_price <= 0:
        return "真实开盘价缺失或为零，不用现价回填"
    if volume is None or volume <= 0:
        return "竞价成交量缺失或为零"
    prev_close = _number(row.get("prev_close"))
    if prev_close is None or prev_close <= 0:
        return "源前收盘价缺失，不能校验除权价格口径"
    return ""


def fetch_double_yin_openings(
    codes: list[str], *, trade_date: str, now: datetime | None = None,
    on_progress: Progress | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """晨间仅拉昨夜候选的真实开盘；失败留明示拒绝证据，不补价格。"""
    wanted = _codes(codes)
    moment = now or datetime.now(SHANGHAI)
    moment = moment.replace(tzinfo=SHANGHAI) if moment.tzinfo is None else moment.astimezone(SHANGHAI)
    if moment.date().isoformat() != trade_date:
        raise RealtimeInputError("实时开盘请求只允许上海时间的当日，不用旧报价重放今日任务")
    quotes: dict[str, dict[str, Any]] = {}
    rejected = {code: "现场报价缺失" for code in wanted}
    errors: list[str] = []
    source_dates_seen: set[str] = set()
    source_times_seen: set[str] = set()
    attempts = 0
    deadline = time.monotonic() + OPENING_RETRY_SECONDS
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="double-yin-open")
    try:
        while rejected and time.monotonic() < deadline:
            pending = sorted(rejected)
            attempts += 1
            _progress(on_progress, "external_opening", 75, f"现场获取{len(pending)}只候选的09:25开盘价")
            future = pool.submit(SinaAdapter().fetch_live_quotes, pending)
            try:
                rows = future.result(timeout=max(0.001, deadline - time.monotonic()))
            except FutureTimeout:
                errors.append("现场新浪开盘请求超过重试时间预算")
                break
            except Exception as exc:
                errors.append(f"新浪现场报价失败：{type(exc).__name__}")
                rows = []
            if not isinstance(rows, list):
                errors.append("新浪现场报价响应不是列表")
                rows = []
            check_at = moment + timedelta(seconds=max(0, OPENING_RETRY_SECONDS - (deadline - time.monotonic())))
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("code") or "")
                if code not in rejected:
                    continue
                source_dates_seen.add(str(row.get("trade_date") or ""))
                source_times_seen.add(str(row.get("trade_time") or ""))
                reason = _opening_reason(row, trade_date, check_at)
                if reason:
                    rejected[code] = reason
                    continue
                quotes[code] = {key: row.get(key) for key in (
                    "code", "name", "open", "prev_close", "price", "volume", "trade_date", "trade_time",
                )}
                quotes[code]["source"] = "sina"
                del rejected[code]
            if rejected:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(OPENING_RETRY_INTERVAL, remaining))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    times = sorted(str(row["trade_time"]) for row in quotes.values())
    return quotes, {
        "mode": "external_auction_opening", "source": "sina", "fetched_at": _stamp(),
        "trade_date": trade_date, "source_date": trade_date if quotes else "",
        "source_time_min": times[0] if times else "", "source_time_max": times[-1] if times else "",
        "source_dates_seen": sorted(source_dates_seen),
        "observed_source_time_min": min(source_times_seen) if source_times_seen else "",
        "observed_source_time_max": max(source_times_seen) if source_times_seen else "",
        "volume_unit": "share", "requested": len(wanted), "returned": len(quotes),
        "rejected": len(rejected), "coverage": len(quotes) / len(wanted) if wanted else 1.0,
        "failed_codes": sorted(rejected), "rejects": rejected, "attempts": attempts,
        "errors": list(dict.fromkeys(errors)), "retry_budget_seconds": OPENING_RETRY_SECONDS,
    }


def fetch_double_yin_industries(
    codes: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """候选级现场行业分类；消费族明确列举，未知行业不按股票名字猜测。"""
    wanted = _codes(codes)
    metadata: dict[str, dict[str, Any]] = {}
    rejects: dict[str, str] = {}
    fetched_at = _stamp()
    for offset in range(0, len(wanted), 100):
        batch = wanted[offset:offset + 100]
        params = {
            "reportName": "RPT_F10_BASIC_ORGINFO",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,EM2016,INDUSTRYCSRC1",
            "filter": '(SECURITY_CODE in ("' + '","'.join(batch) + '"))',
            "pageNumber": 1, "pageSize": 100, "source": "HSF10", "client": "PC",
        }
        try:
            response = market_get(INDUSTRY_URL, params=params, timeout=6, retries=0,
                                  headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"})
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result") or {}
            if payload.get("success") is not True or int(result.get("pages") or 0) > 1:
                raise ValueError("行业查询失败或候选分页不完整")
            rows = result.get("data")
            if not isinstance(rows, list):
                raise ValueError("行业响应缺少数据列表")
        except Exception as exc:
            for code in batch:
                rejects[code] = f"行业现场请求失败：{type(exc).__name__}"
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("SECURITY_CODE") or "")
            if code not in batch:
                continue
            path = str(row.get("EM2016") or "").strip()
            levels = [part.strip() for part in path.split("-")]
            if len(levels) < 2 or any(not part or part in {"-", "未知", "其他", "其他行业"} for part in levels):
                rejects[code] = "行业层级缺失，不能确认板块分散"
                continue
            groups = [f"industry:{levels[0]}"]
            if levels[0] in CONSUMER_INDUSTRIES:
                groups.append("family:consumer")
            metadata[code] = {
                "industry": levels[0], "industry_l1": levels[0], "industry_l2": levels[1],
                "industry_l3": levels[2] if len(levels) > 2 else "", "industry_path": path,
                "groups": groups, "source": "eastmoney_orginfo", "fetched_at": fetched_at,
            }
            rejects.pop(code, None)
        for code in batch:
            if code not in metadata:
                rejects.setdefault(code, "行业现场响应缺少该股票")
    return metadata, {
        "source": "eastmoney_orginfo", "fetched_at": fetched_at, "classification": "EM2016",
        "requested": len(wanted), "returned": len(metadata), "rejected": len(rejects),
        "coverage": len(metadata) / len(wanted) if wanted else 1.0,
        "failed_codes": sorted(rejects), "rejects": rejects,
        "consumer_industries": sorted(CONSUMER_INDUSTRIES),
    }
