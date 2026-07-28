"""腾讯财经直连适配器。

薄包装 ``src.market.infrastructure.tencent``：hist_daily 分页拼全历史；spot_batch 走 qt.gtimg.cn。
"""
from __future__ import annotations

import time

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    DAILY_REQUIRED_COLUMNS,
    LANE_HIST_DAILY,
    LANE_SPOT_BATCH,
    ProbeResult,
)
from src.market.infrastructure.store import normalize_code, to_sina_symbol


class TencentAdapter(MarketAdapter):
    """腾讯财经 —— hist_daily / spot_batch。"""

    meta = AdapterMeta(
        id="tencent",
        label="腾讯财经",
        lanes=(LANE_HIST_DAILY, LANE_SPOT_BATCH),
        description="qt.gtimg 现价 + ifzq 日 K；分页拼全历史，不经 akshare。",
    )

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        from src.market import tencent

        symbol = to_sina_symbol(code, instrument_type=instrument_type)
        try:
            frame = tencent.fetch_daily(symbol)
        except tencent.TencentFetchError as exc:
            raise AdapterError(str(exc)) from exc
        except Exception as exc:
            raise AdapterError(
                f"腾讯日线异常：{type(exc).__name__}: {exc}"
            ) from exc
        return self._normalize_daily(frame)

    def fetch_spot_sample(self, codes: list[str] | None = None) -> pd.DataFrame:
        sample = codes or ["600519", "000001"]
        return self.fetch_spot(sample)

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 80,
    ) -> list[dict]:
        from src.market import tencent

        types = instrument_types or {}
        normalized = [normalize_code(c) for c in codes if str(c).strip()]
        if not normalized:
            return []
        symbol_to_code = {
            to_sina_symbol(code, instrument_type=types.get(code, "STOCK")): code
            for code in normalized
        }
        symbols = list(symbol_to_code)
        _ = batch_size
        try:
            rows = tencent.fetch_live_hq(symbols)
        except Exception as exc:
            raise AdapterError(
                f"腾讯 live 行情异常：{type(exc).__name__}: {exc}"
            ) from exc
        out: list[dict] = []
        for row in rows:
            code = symbol_to_code.get(str(row.get("symbol") or ""))
            if not code:
                continue
            item = dict(row)
            item["code"] = code
            out.append(item)
        if not out:
            raise AdapterError("腾讯 live 行情为空")
        return out

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 80,
    ) -> pd.DataFrame:
        from src.market import tencent

        types = instrument_types or {}
        normalized = [normalize_code(c) for c in codes if str(c).strip()]
        if not normalized:
            return pd.DataFrame(
                columns=[
                    "code",
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                ]
            )

        symbol_to_code = {
            to_sina_symbol(code, instrument_type=types.get(code, "STOCK")): code
            for code in normalized
        }
        symbols = list(symbol_to_code)
        frames: list[pd.DataFrame] = []
        errors: list[str] = []
        size = max(1, batch_size)
        for start in range(0, len(symbols), size):
            batch = symbols[start : start + size]
            try:
                spot = tencent.fetch_spot(batch)
            except tencent.TencentFetchError as exc:
                errors.append(f"{batch[0]}…: {exc}")
                continue
            except Exception as exc:
                errors.append(f"{batch[0]}…: {type(exc).__name__}: {exc}")
                continue
            if spot is None or spot.empty:
                continue
            out = spot.copy()
            out["code"] = out["symbol"].map(symbol_to_code)
            out = out.dropna(subset=["code"])
            if not out.empty:
                frames.append(out)

        if not frames:
            detail = "；".join(errors[-3:]) if errors else "空数据"
            raise AdapterError(f"腾讯现价失败：{detail}")
        merged = pd.concat(frames, ignore_index=True)
        for col in ("open", "high", "low", "close", "volume", "amount"):
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
        return merged[
            ["code", "date", "open", "high", "low", "close", "volume", "amount"]
        ].reset_index(drop=True)

    def probe(self, lane: str) -> ProbeResult:
        """hist_daily 用最近 30 根；spot 走小样本。"""
        if lane == LANE_HIST_DAILY and lane in self.meta.lanes:
            from src.market import tencent

            started = time.perf_counter()
            try:
                symbol = to_sina_symbol("600519")
                frame = tencent.fetch_daily_recent(symbol, count=30)
                normalized = self._normalize_daily(frame)
                self._assert_daily_shape(normalized)
                rtt = (time.perf_counter() - started) * 1000.0
                return ProbeResult(
                    adapter_id=self.meta.id,
                    lane=lane,
                    ok=True,
                    rtt_ms=rtt,
                    rows=len(normalized),
                    extra={"probe_window": "30d"},
                )
            except Exception as exc:
                rtt = (time.perf_counter() - started) * 1000.0
                return ProbeResult(
                    adapter_id=self.meta.id,
                    lane=lane,
                    ok=False,
                    rtt_ms=rtt,
                    error=f"{type(exc).__name__}: {exc}",
                )
        return super().probe(lane)

    @staticmethod
    def _normalize_daily(frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty:
            raise AdapterError("腾讯日线为空")
        out = frame.copy()
        missing = [c for c in DAILY_REQUIRED_COLUMNS if c not in out.columns]
        if missing:
            raise AdapterError(f"腾讯日线缺列：{missing}")
        for col in ("open", "high", "low", "close", "volume", "amount"):
            out[col] = pd.to_numeric(out[col], errors="coerce")
        if "turnover" in out.columns:
            out["turnover"] = pd.to_numeric(out["turnover"], errors="coerce")
        return out.reset_index(drop=True)
