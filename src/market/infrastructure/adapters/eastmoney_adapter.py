"""东财适配器。

包装 ``EastmoneySource``：列校验；换手率百分数→小数已在 Source 完成。
扩展 spot_batch / live / 分钟线 / 个股资金流（akshare 东财口径）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import time

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    DAILY_REQUIRED_COLUMNS,
    LANE_CAPITAL_FLOW,
    LANE_HIST_DAILY,
    LANE_MINUTE,
    LANE_SPOT_BATCH,
    ProbeResult,
)
from src.market.infrastructure.sources import EastmoneySource, SourceError, _import_akshare
from src.market.infrastructure.store import guess_market, normalize_code


#: 仅用于「绕过 Source、直接吃 akshare 中文列」的兜底（单测 / 原始表）。
_EASTMONEY_RENAME = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
}

_SPOT_RENAME = {
    "代码": "code",
    "名称": "name",
    "今开": "open",
    "最高": "high",
    "最低": "low",
    "最新价": "close",
    "成交量": "volume",
    "成交额": "amount",
    "昨收": "prev_close",
    "涨跌幅": "pct",
    "涨跌额": "change",
}

_MINUTE_RENAME = {
    "时间": "datetime",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "均价": "avg_price",
}

_CAPITAL_FLOW_RENAME = {
    "日期": "date",
    "收盘价": "close",
    "涨跌幅": "pct_chg",
    "主力净流入-净额": "main_net_inflow",
    "主力净流入-净占比": "main_net_pct",
    "超大单净流入-净额": "super_large_net_inflow",
    "超大单净流入-净占比": "super_large_net_pct",
    "大单净流入-净额": "large_net_inflow",
    "大单净流入-净占比": "large_net_pct",
    "中单净流入-净额": "medium_net_inflow",
    "中单净流入-净占比": "medium_net_pct",
    "小单净流入-净额": "small_net_inflow",
    "小单净流入-净占比": "small_net_pct",
}


class EastmoneyAdapter(MarketAdapter):
    """东财 —— hist_daily / spot_batch / minute / capital_flow。"""

    meta = AdapterMeta(
        id="eastmoney",
        label="东财",
        lanes=(
            LANE_HIST_DAILY,
            LANE_SPOT_BATCH,
            LANE_MINUTE,
            LANE_CAPITAL_FLOW,
        ),
        description=(
            "akshare 东财接口；换手率在 Source 层从百分数归一为小数；"
            "现价走全市场表后按代码过滤。"
        ),
    )

    def __init__(self, source: EastmoneySource | None = None) -> None:
        self._source = source or EastmoneySource()

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        try:
            frame = self._source.fetch_daily(code, instrument_type=instrument_type)
        except SourceError as exc:
            raise AdapterError(str(exc)) from exc
        # Source 已把 turnover 收成小数，勿再 /100。
        return self._normalize_daily(frame, turnover_as_percent=False)

    def fetch_spot_sample(self, codes: list[str] | None = None) -> pd.DataFrame:
        sample = codes or ["600519", "000001"]
        return self.fetch_spot(sample)

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> pd.DataFrame:
        """全市场现价表按 ``codes`` 过滤；仅 A 股现货（指数不在东财 spot 表）。"""
        _ = batch_size
        types = instrument_types or {}
        normalized = [normalize_code(c) for c in codes if str(c).strip()]
        stock_codes = [
            c for c in normalized if types.get(c, "STOCK") != "INDEX"
        ]
        if not stock_codes:
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
        try:
            raw = self._fetch_spot_em()
        except Exception as exc:
            raise AdapterError(
                f"东财现价失败：{type(exc).__name__}: {exc}"
            ) from exc
        if raw is None or raw.empty:
            raise AdapterError("东财现价为空")
        out = self._normalize_spot(raw)
        want = set(stock_codes)
        out = out[out["code"].isin(want)]
        if out.empty:
            raise AdapterError(f"东财现价未命中：{stock_codes[:5]}")
        return out.reset_index(drop=True)

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        """顶栏富行情：name / prev_close / pct / price 等。"""
        _ = batch_size
        types = instrument_types or {}
        normalized = [normalize_code(c) for c in codes if str(c).strip()]
        stock_codes = [
            c for c in normalized if types.get(c, "STOCK") != "INDEX"
        ]
        if not stock_codes:
            return []
        try:
            raw = self._fetch_spot_em()
        except Exception as exc:
            raise AdapterError(
                f"东财 live 行情异常：{type(exc).__name__}: {exc}"
            ) from exc
        if raw is None or raw.empty:
            raise AdapterError("东财 live 行情为空")
        spot = self._normalize_spot(raw, include_rich=True)
        want = set(stock_codes)
        spot = spot[spot["code"].isin(want)]
        if spot.empty:
            raise AdapterError("东财 live 行情未命中")
        out: list[dict] = []
        for item in spot.to_dict(orient="records"):
            out.append(
                {
                    "code": item["code"],
                    "name": item.get("name") or "",
                    "price": float(item["close"]),
                    "prev_close": float(item.get("prev_close", item["close"])),
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "change": float(item.get("change") or 0.0),
                    "pct": float(item.get("pct") or 0.0),
                    "volume": float(item["volume"]),
                    "amount": float(item["amount"]),
                    "trade_time": "",
                    "source": "eastmoney",
                }
            )
        return out

    def fetch_minute(
        self, code: str, *, period: str = "1", days: int = 1
    ) -> pd.DataFrame:
        """分钟 K（东财 akshare ``stock_zh_a_hist_min_em``）。"""
        plain = normalize_code(code)
        ak = _import_akshare()
        end = datetime.now()
        start = end - timedelta(days=max(1, days))
        start_s = start.strftime("%Y-%m-%d %H:%M:%S")
        end_s = end.strftime("%Y-%m-%d %H:%M:%S")
        try:
            frame = ak.stock_zh_a_hist_min_em(
                symbol=plain,
                start_date=start_s,
                end_date=end_s,
                period=str(period),
                adjust="",
            )
        except Exception as exc:
            raise AdapterError(
                f"东财分钟线 {plain} 失败：{type(exc).__name__}: {exc}"
            ) from exc
        return self._normalize_minute(frame)

    def fetch_capital_flow(self, code: str) -> pd.DataFrame:
        """个股资金流（主力/超大/大/中/小单净额）。"""
        plain = normalize_code(code)
        market = guess_market(plain)
        ak = _import_akshare()
        try:
            frame = ak.stock_individual_fund_flow(stock=plain, market=market)
        except Exception as exc:
            raise AdapterError(
                f"东财资金流 {plain} 失败：{type(exc).__name__}: {exc}"
            ) from exc
        return self._normalize_capital_flow(frame)

    def probe(self, lane: str) -> ProbeResult:
        """hist_daily 用近一年窗口；其余 lane 走小样本。"""
        if lane not in self.meta.lanes:
            return super().probe(lane)

        if lane == LANE_HIST_DAILY:
            return self._probe_hist_daily()

        started = time.perf_counter()
        try:
            rows: int | None = None
            extra: dict[str, object] = {}
            if lane == LANE_SPOT_BATCH:
                frame = self.fetch_spot_sample(["600519"])
                rows = int(len(frame))
            elif lane == LANE_MINUTE:
                frame = self.fetch_minute("600519", period="1", days=1)
                rows = int(len(frame))
                extra = {"period": "1", "days": 1}
            elif lane == LANE_CAPITAL_FLOW:
                frame = self.fetch_capital_flow("600519")
                rows = int(len(frame))
                if rows == 0:
                    raise AdapterError("资金流为空")
            else:
                return super().probe(lane)
            rtt = (time.perf_counter() - started) * 1000.0
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=lane,
                ok=True,
                rtt_ms=rtt,
                rows=rows,
                extra=extra,
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

    def _probe_hist_daily(self) -> ProbeResult:
        started = time.perf_counter()
        try:
            end = date.today()
            start = end - timedelta(days=400)
            frame = self._source.fetch_daily(
                "600519",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            normalized = self._normalize_daily(frame, turnover_as_percent=False)
            self._assert_daily_shape(normalized)
            rtt = (time.perf_counter() - started) * 1000.0
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=LANE_HIST_DAILY,
                ok=True,
                rtt_ms=rtt,
                rows=int(len(normalized)),
                extra={"probe_window": "≈400d"},
            )
        except Exception as exc:
            rtt = (time.perf_counter() - started) * 1000.0
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=LANE_HIST_DAILY,
                ok=False,
                rtt_ms=rtt,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _fetch_spot_em() -> pd.DataFrame:
        ak = _import_akshare()
        return ak.stock_zh_a_spot_em()

    @classmethod
    def _normalize_spot(
        cls, frame: pd.DataFrame, *, include_rich: bool = False
    ) -> pd.DataFrame:
        if frame is None or frame.empty:
            raise AdapterError("东财现价为空")
        out = frame.copy()
        rename = {src: dst for src, dst in _SPOT_RENAME.items() if src in out.columns}
        if rename:
            out = out.rename(columns=rename)
        if "code" not in out.columns:
            raise AdapterError("东财现价缺 code 列")
        out["code"] = out["code"].astype(str).str.strip().str.zfill(6)
        trade_date = date.today()
        out["date"] = trade_date
        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        if include_rich:
            for col in ("prev_close", "pct", "change", "name"):
                if col in out.columns and col != "name":
                    out[col] = pd.to_numeric(out[col], errors="coerce")
            return out
        return out[
            ["code", "date", "open", "high", "low", "close", "volume", "amount"]
        ].reset_index(drop=True)

    @classmethod
    def _normalize_minute(cls, frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty:
            raise AdapterError("东财分钟线为空")
        out = frame.copy()
        rename = {src: dst for src, dst in _MINUTE_RENAME.items() if src in out.columns}
        if rename:
            out = out.rename(columns=rename)
        if "datetime" not in out.columns:
            raise AdapterError("东财分钟线缺 datetime 列")
        for col in ("open", "high", "low", "close", "volume", "amount", "avg_price"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        return out.reset_index(drop=True)

    @classmethod
    def _normalize_capital_flow(cls, frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty:
            raise AdapterError("东财资金流为空")
        out = frame.copy()
        rename = {
            src: dst for src, dst in _CAPITAL_FLOW_RENAME.items() if src in out.columns
        }
        if rename:
            out = out.rename(columns=rename)
        if "date" not in out.columns:
            raise AdapterError("东财资金流缺 date 列")
        for col in out.columns:
            if col == "date":
                continue
            out[col] = pd.to_numeric(out[col], errors="coerce")
        return out.reset_index(drop=True)

    @classmethod
    def _normalize_daily(
        cls, frame: pd.DataFrame, *, turnover_as_percent: bool = True
    ) -> pd.DataFrame:
        """列重命名 + 可选换手率百分数 → 小数。

        ``turnover_as_percent=True``：吃原始/中文列（单测、直接 ak 表）。
        ``False``：Source 已归一，只做列校验与数值化。
        """
        if frame is None or frame.empty:
            raise AdapterError("东财日线为空")
        out = frame.copy()
        rename = {src: dst for src, dst in _EASTMONEY_RENAME.items() if src in out.columns}
        if rename:
            out = out.rename(columns=rename)

        missing = [c for c in DAILY_REQUIRED_COLUMNS if c not in out.columns]
        if missing:
            raise AdapterError(f"东财日线缺列：{missing}")

        for col in ("open", "high", "low", "close", "volume", "amount"):
            out[col] = pd.to_numeric(out[col], errors="coerce")

        if "turnover" in out.columns:
            out["turnover"] = pd.to_numeric(out["turnover"], errors="coerce")
            if turnover_as_percent:
                # 东财原始换手率恒为百分数；低换手日也可能全 <1，不能用启发式。
                out["turnover"] = out["turnover"] / 100.0
        return out.reset_index(drop=True)
