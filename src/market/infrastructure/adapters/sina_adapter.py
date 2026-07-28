"""新浪直连适配器。

薄包装 ``SinaSource`` / ``src.market.infrastructure.sina``：日线与换手率已在 sina 模块
归一成小数；现价批量也经本适配器，业务层不再直调 sina。
"""
from __future__ import annotations

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    DAILY_REQUIRED_COLUMNS,
    LANE_ADJUST_FACTOR,
    LANE_HIST_DAILY,
    LANE_SPOT_BATCH,
    ProbeResult,
)
from src.market.infrastructure.sources import SinaSource, SourceError
from src.market.infrastructure.store import normalize_code, to_sina_symbol


class SinaAdapter(MarketAdapter):
    """新浪直连 —— hist_daily / spot_batch / adjust_factor。"""

    meta = AdapterMeta(
        id="sina",
        label="新浪直连",
        lanes=(LANE_HIST_DAILY, LANE_SPOT_BATCH, LANE_ADJUST_FACTOR),
        description="一次拉全历史，自带流通股本与换手率（小数）；不经 akshare。",
    )

    def __init__(self, source: SinaSource | None = None) -> None:
        self._source = source or SinaSource()

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        try:
            frame = self._source.fetch_daily(code, instrument_type=instrument_type)
        except SourceError as exc:
            raise AdapterError(str(exc)) from exc
        return self._normalize_daily(frame)

    def fetch_spot_sample(self, codes: list[str] | None = None) -> pd.DataFrame:
        sample = codes or ["600519", "000001"]
        return self.fetch_spot(sample)

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        """顶栏/列表富行情：含 name、prev_close、pct；每条带 code。"""
        from src.market import sina

        types = instrument_types or {}
        normalized = [normalize_code(c) for c in codes if str(c).strip()]
        if not normalized:
            return []
        symbol_to_code = {
            to_sina_symbol(code, instrument_type=types.get(code, "STOCK")): code
            for code in normalized
        }
        symbols = list(symbol_to_code)
        # sina.fetch_live_hq 内部已按 SPOT_BATCH_SIZE 分批
        _ = batch_size
        try:
            rows = sina.fetch_live_hq(symbols)
        except Exception as exc:
            raise AdapterError(
                f"新浪 live 行情异常：{type(exc).__name__}: {exc}"
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
            raise AdapterError("新浪 live 行情为空")
        return out

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> pd.DataFrame:
        """批量现价 → 归一列 code/date/open/high/low/close/volume/amount。"""
        from src.market import sina

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
                spot = sina.fetch_spot(batch)
            except sina.SinaFetchError as exc:
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
            raise AdapterError(f"新浪现价失败：{detail}")
        merged = pd.concat(frames, ignore_index=True)
        for col in ("open", "high", "low", "close", "volume", "amount"):
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
        return merged[
            ["code", "date", "open", "high", "low", "close", "volume", "amount"]
        ].reset_index(drop=True)

    def probe(self, lane: str) -> ProbeResult:
        """hist_daily：新浪接口一次就是全历史，探测仍走全量但只校验形状。"""
        if lane != LANE_HIST_DAILY:
            return super().probe(lane)
        result = super().probe(lane)
        if result.ok:
            result.extra = {**(result.extra or {}), "probe_window": "full"}
        return result

    def fetch_adjust_factors(self, code: str) -> pd.DataFrame:
        try:
            return self._source.fetch_adjust_factors(code)
        except Exception as exc:
            raise AdapterError(
                f"新浪复权因子失败：{type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _normalize_daily(frame: pd.DataFrame) -> pd.DataFrame:
        """新浪直连已产出标准列名；turnover 已是小数，勿再 /100。"""
        if frame is None or frame.empty:
            raise AdapterError("新浪日线为空")
        out = frame.copy()
        missing = [c for c in DAILY_REQUIRED_COLUMNS if c not in out.columns]
        if missing:
            raise AdapterError(f"新浪日线缺列：{missing}")
        for col in ("open", "high", "low", "close", "volume", "amount"):
            out[col] = pd.to_numeric(out[col], errors="coerce")
        if "turnover" in out.columns:
            out["turnover"] = pd.to_numeric(out["turnover"], errors="coerce")
        if "outstanding_share" in out.columns:
            out["outstanding_share"] = pd.to_numeric(
                out["outstanding_share"], errors="coerce"
            )
        return out.reset_index(drop=True)
