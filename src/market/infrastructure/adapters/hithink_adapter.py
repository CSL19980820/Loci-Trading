"""同花顺扶摇 REST 行情：通达信失败时的可选日 K / 快照来源。"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
import hashlib
import threading
import time
from zoneinfo import ZoneInfo

import pandas as pd

from src.market.domain.source_contract import SPOT_CONTRACT
from src.market.infrastructure.adapters.base import (
    AdapterError,
    MarketAdapter,
    window_start_date,
)
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_HIST_DAILY,
    LANE_SPOT_BATCH,
    ProbeHint,
)
from src.market.infrastructure.history_floor import clamp_start
from src.market.infrastructure.http_client import market_get
from src.market.infrastructure.pipeline import (
    NormalizeError,
    empty_spot_frame,
    normalize,
)
from src.market.infrastructure.store import guess_market, normalize_code
from src.market.infrastructure.store_quote_payload import partition_valid_ohlc_rows


_BASE_URL = "https://fuyao.aicubes.cn"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MIN_INTERVAL_SEC = 0.5
_RATE_LIMIT_COOLDOWN_SEC = 60.0
_AUTH_COOLDOWN_SEC = 900.0
_MAX_SNAPSHOT_CODES = 80
# 历史接口单次最多 10 年；每段留足余量，避免闰年边界触发 1003。
_WINDOW_DAYS = 365 * 9


def hithink_adapter_enabled() -> bool:
    """MCP 与 REST 共用租户凭据；没配 Key 就不进入行情路由。"""
    try:
        from src.intel import hithink_api_key

        return bool(hithink_api_key())
    except Exception:
        return False


def _api_key() -> str:
    from src.intel import hithink_api_key

    key = hithink_api_key()
    if not key:
        raise AdapterError("同花顺扶摇 API Key 未配置或不可用")
    return key


def _timestamp_ms(value: date) -> int:
    return int(datetime.combine(value, dtime.min, tzinfo=_SHANGHAI).timestamp() * 1000)


def _trade_date(value: object) -> str:
    try:
        return (
            datetime.fromtimestamp(float(value) / 1000, tz=_SHANGHAI).date().isoformat()
        )
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise AdapterError("同花顺扶摇日 K 日期无效") from exc


def _thscode(code: str, *, instrument_type: str) -> str:
    plain = normalize_code(code)
    market = guess_market(plain, instrument_type=instrument_type).upper()
    return f"{plain}.{market}"


class HithinkAdapter(MarketAdapter):
    meta = AdapterMeta(
        id="hithink",
        label="同花顺扶摇",
        lanes=(LANE_HIST_DAILY, LANE_SPOT_BATCH),
        description=(
            "官方 REST 未复权日 K 与行情快照；共用同花顺 MCP 的 API Key。"
            "快照无逐票交易日，只用于展示，不写当日 K。"
        ),
        base_url=_BASE_URL,
        probe_hints={
            LANE_HIST_DAILY: ProbeHint(note="最近 60 根日线", recent_count=60)
        },
        spot_declares_trade_date=False,
    )

    def __init__(self) -> None:
        self._pace_lock = threading.Lock()
        self._next_request_at = 0.0
        self._cooldown_until = 0.0
        self._cooldown_reason = ""
        self._key_digest = ""

    def _request(self, path: str, *, params: dict[str, object]) -> dict:
        key = _api_key()
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with self._pace_lock:
            if digest != self._key_digest:
                # 前端更换 Key 后立即解除旧 Key 的鉴权/限流冷却。
                self._key_digest = digest
                self._cooldown_until = 0.0
                self._cooldown_reason = ""
            now = time.monotonic()
            if now < self._cooldown_until:
                raise AdapterError(self._cooldown_reason)
            wait = max(0.0, self._next_request_at - now)
            self._next_request_at = max(now, self._next_request_at) + _MIN_INTERVAL_SEC
        if wait:
            time.sleep(wait)
        with self._pace_lock:
            if time.monotonic() < self._cooldown_until:
                raise AdapterError(self._cooldown_reason)

        try:
            response = market_get(
                _BASE_URL + path,
                params=params,
                headers={"X-api-key": key},
                timeout=8,
                retries=1,
            )
        except Exception as exc:
            raise AdapterError(f"同花顺扶摇请求失败：{type(exc).__name__}") from exc
        if response.status_code == 429:
            self._cooldown(_RATE_LIMIT_COOLDOWN_SEC, "同花顺扶摇限流，稍后重试")
            raise AdapterError("同花顺扶摇限流，稍后重试")
        if response.status_code != 200:
            raise AdapterError(f"同花顺扶摇 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterError("同花顺扶摇响应不是 JSON") from exc
        if not isinstance(payload, dict):
            raise AdapterError("同花顺扶摇响应格式无效")
        code = payload.get("code")
        if code != 0:
            if code in (3001, 3002, 3004):
                # 个别标的不存在/数据未就绪，不等于整个来源失联；交给路由继续换源。
                return {"item": []}
            if code == 4001:
                self._cooldown(_RATE_LIMIT_COOLDOWN_SEC, "同花顺扶摇限流，稍后重试")
                raise AdapterError("同花顺扶摇限流，稍后重试")
            elif code in (2001, 2003):
                self._cooldown(
                    _AUTH_COOLDOWN_SEC, "同花顺扶摇 API Key 无效或无权访问行情"
                )
                raise AdapterError("同花顺扶摇 API Key 无效或无权访问行情")
            raise AdapterError(
                f"同花顺扶摇业务错误 {code}：{str(payload.get('message') or '')[:120]}"
            )
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            raise AdapterError("同花顺扶摇行情数据格式无效")
        return data

    def _cooldown(self, seconds: float, reason: str) -> None:
        with self._pace_lock:
            self._cooldown_until = time.monotonic() + seconds
            self._cooldown_reason = reason

    def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
        return self._fetch_daily(code, instrument_type=instrument_type, bars=None)

    def fetch_daily_window(
        self, code: str, *, instrument_type: str = "STOCK", bars: int
    ) -> pd.DataFrame:
        return self._fetch_daily(
            code, instrument_type=instrument_type, bars=max(1, int(bars))
        )

    def _fetch_daily(
        self, code: str, *, instrument_type: str, bars: int | None
    ) -> pd.DataFrame:
        kind = str(instrument_type or "STOCK").upper()
        if kind not in {"STOCK", "INDEX"}:
            raise AdapterError(f"同花顺扶摇日 K 不支持标的类型 {kind}")
        today = datetime.now(_SHANGHAI).date()
        start = (
            window_start_date(bars, today=today)
            if bars
            else date.fromisoformat(clamp_start(None))
        )
        end = today + timedelta(days=1)
        path = (
            "/api/a-share-index/prices/historical"
            if kind == "INDEX"
            else "/api/a-share/prices/historical"
        )
        rows: list[dict[str, object]] = []
        while start < end:
            stop = min(end, start + timedelta(days=_WINDOW_DAYS))
            params: dict[str, object] = {
                "thscode": _thscode(code, instrument_type=kind),
                "interval": "1d",
                "start": _timestamp_ms(start),
                "end": _timestamp_ms(stop),
            }
            if kind == "STOCK":
                params["adjust"] = "none"
            data = self._request(path, params=params)
            for item in data["item"]:
                if not isinstance(item, dict):
                    continue
                trade_date = _trade_date(item.get("date_ms"))
                if not (start.isoformat() <= trade_date < stop.isoformat()):
                    continue
                rows.append(
                    {
                        "date": trade_date,
                        "open": item.get("open_price"),
                        "high": item.get("high_price"),
                        "low": item.get("low_price"),
                        "close": item.get("close_price"),
                        "volume": item.get("volume"),
                        "amount": item.get("turnover"),
                    }
                )
            start = stop
        if not rows:
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume", "amount"]
            )
        frame = self._normalize_daily_frame(pd.DataFrame(rows), who="同花顺扶摇")
        frame, _rejected = partition_valid_ohlc_rows(frame)
        frame = frame.sort_values("date").drop_duplicates("date", keep="last")
        return (
            frame.tail(bars).reset_index(drop=True)
            if bars
            else frame.reset_index(drop=True)
        )

    def _fetch_daily_for_probe(self, code: str) -> pd.DataFrame:
        return self.fetch_daily_window(code, bars=60)

    def _snapshot_rows(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None,
        batch_size: int,
    ) -> list[dict[str, object]]:
        types = instrument_types or {}
        groups: dict[str, dict[str, str]] = {"STOCK": {}, "INDEX": {}}
        for raw_code in codes:
            code = normalize_code(raw_code)
            kind = str(types.get(code, types.get(raw_code, "STOCK"))).upper()
            if kind in groups:
                groups[kind][_thscode(code, instrument_type=kind)] = code
        span = min(max(1, int(batch_size)), _MAX_SNAPSHOT_CODES)
        out: list[dict[str, object]] = []
        for kind, requested in groups.items():
            symbols = list(requested)
            path = (
                "/api/a-share-index/prices/snapshot"
                if kind == "INDEX"
                else "/api/a-share/prices/snapshot"
            )
            for offset in range(0, len(symbols), span):
                selected = symbols[offset : offset + span]
                data = self._request(path, params={"thscodes": ",".join(selected)})
                for item in data["item"]:
                    if not isinstance(item, dict):
                        continue
                    code = requested.get(str(item.get("thscode") or "").upper())
                    if code:
                        out.append({**item, "code": code})
        if not out:
            raise AdapterError("同花顺扶摇快照返回空数据")
        return out

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> pd.DataFrame:
        if not codes:
            return empty_spot_frame()
        rows = self._snapshot_rows(
            codes, instrument_types=instrument_types, batch_size=batch_size
        )
        frame = pd.DataFrame(
            {
                "code": item["code"],
                "open": item.get("open_price"),
                "high": item.get("high_price"),
                "low": item.get("low_price"),
                "close": item.get("last_price"),
                "volume": item.get("volume"),
                "amount": item.get("turnover"),
            }
            for item in rows
        )
        try:
            return normalize(frame, SPOT_CONTRACT, who="同花顺扶摇")
        except NormalizeError as exc:
            raise AdapterError(str(exc)) from exc

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        if not codes:
            return []
        rows = self._snapshot_rows(
            codes, instrument_types=instrument_types, batch_size=batch_size
        )
        return [
            {
                "code": item["code"],
                "price": item.get("last_price"),
                "open": item.get("open_price"),
                "high": item.get("high_price"),
                "low": item.get("low_price"),
                "prev_close": item.get("prev_price"),
                "volume": item.get("volume"),
                "amount": item.get("turnover"),
                "pct": item.get("price_change_ratio_pct"),
                "change": item.get("price_change"),
            }
            for item in rows
        ]
