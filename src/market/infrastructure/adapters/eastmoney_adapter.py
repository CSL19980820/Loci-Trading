"""东财适配器。

包装 ``EastmoneySource``：列校验；换手率百分数→小数已在 Source 完成。
扩展 spot_batch / live / 分钟线 / 个股资金流（akshare 东财口径）。
"""
from __future__ import annotations

from datetime import date, timedelta
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
from src.market.domain.column_glossary import select_columns
from src.market.infrastructure.sources import EastmoneySource, SourceError, _import_akshare
from src.market.infrastructure.store import guess_market, normalize_code


#: 以下四张表只从 ``column_glossary.CN_TO_EN`` 挑子集，中英对照不在此处二次维护。
#: 仅用于「绕过 Source、直接吃 akshare 中文列」的兜底（单测 / 原始表）。
_EASTMONEY_RENAME = select_columns(
    "日期",
    "开盘",
    "最高",
    "最低",
    "收盘",
    "成交量",
    "成交额",
    "换手率",
)

_SPOT_RENAME = select_columns(
    "代码",
    "名称",
    "今开",
    "最高",
    "最低",
    "最新价",
    "成交量",
    "成交额",
    "昨收",
    "涨跌幅",
    "涨跌额",
)

_MINUTE_RENAME = select_columns(
    "时间",
    "开盘",
    "收盘",
    "最高",
    "最低",
    "成交量",
    "成交额",
    "均价",
)

_CAPITAL_FLOW_RENAME = {
    **select_columns(
        "日期",
        "收盘价",
        "主力净流入-净额",
        "主力净流入-净占比",
        "超大单净流入-净额",
        "超大单净流入-净占比",
        "大单净流入-净额",
        "大单净流入-净占比",
        "中单净流入-净额",
        "中单净流入-净占比",
        "小单净流入-净额",
        "小单净流入-净占比",
    ),
    # 资金流表的历史归一名是 pct_chg，与现价表的 pct 撞了同一个中文名，
    # 只能在此单独覆盖；改这里等于改入库列名，勿顺手统一。
    "涨跌幅": "pct_chg",
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
            "日线/现价/资金流经 akshare；分钟线直连 push2his/push2delay；"
            "成交量手→股、换手率百分数→小数在 Source/normalize 完成。"
        ),
        # 东财公开站点，仅供人核对来源：实际请求路径是 akshare，本仓不直连该域名。
        base_url="https://www.eastmoney.com",
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
        self,
        code: str,
        *,
        period: str = "1",
        days: int = 1,
        trade_date: str | None = None,
    ) -> pd.DataFrame:
        """分钟 K（直连东财 push2his / push2delay，不经 akshare）。"""
        from src.market.infrastructure.eastmoney_minute import (
            EastmoneyMinuteError,
            fetch_minute_bars,
        )

        plain = normalize_code(code)
        try:
            return fetch_minute_bars(
                plain,
                period=period,
                days=days,
                trade_date=trade_date,
            )
        except EastmoneyMinuteError as exc:
            raise AdapterError(f"东财分钟线 {plain} 失败：{exc}") from exc
        except Exception as exc:
            raise AdapterError(
                f"东财分钟线 {plain} 失败：{type(exc).__name__}: {exc}"
            ) from exc

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

    def probe(self, lane: str, *, code: str = "600519") -> ProbeResult:
        """hist_daily 用近一年窗口；其余 lane 走小样本。"""
        if lane not in self.meta.lanes:
            return super().probe(lane)

        if lane == LANE_HIST_DAILY:
            return self._probe_hist_daily(code)

        started = time.perf_counter()
        try:
            rows: int | None = None
            extra: dict[str, object] = {}
            if lane == LANE_SPOT_BATCH:
                frame = self.fetch_spot_sample([code])
                rows = int(len(frame))
            elif lane == LANE_MINUTE:
                frame = self.fetch_minute(code, period="1", days=1)
                rows = int(len(frame))
                extra = {"period": "1", "days": 1}
            elif lane == LANE_CAPITAL_FLOW:
                frame = self.fetch_capital_flow(code)
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

    def _probe_hist_daily(self, code: str) -> ProbeResult:
        started = time.perf_counter()
        try:
            end = date.today()
            start = end - timedelta(days=400)
            frame = self._source.fetch_daily(
                code,
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
        """列重命名 + 成交量手→股 + 可选换手率百分数 → 小数。

        ``turnover_as_percent=True``：吃原始/中文列（单测、直接 ak 表）。
        ``False``：Source 已归一（量已是股、换手已是小数），只做列校验与数值化。
        """
        if frame is None or frame.empty:
            raise AdapterError("东财日线为空")
        out = frame.copy()
        from_lots = "成交量" in out.columns
        rename = {src: dst for src, dst in _EASTMONEY_RENAME.items() if src in out.columns}
        if rename:
            out = out.rename(columns=rename)

        missing = [c for c in DAILY_REQUIRED_COLUMNS if c not in out.columns]
        if missing:
            raise AdapterError(f"东财日线缺列：{missing}")

        for col in ("open", "high", "low", "close", "volume", "amount"):
            out[col] = pd.to_numeric(out[col], errors="coerce")

        # 原始东财「成交量」为手；Source 路径已 ×100，勿再乘。
        if from_lots and turnover_as_percent:
            out["volume"] = out["volume"] * 100.0

        if "turnover" in out.columns:
            out["turnover"] = pd.to_numeric(out["turnover"], errors="coerce")
            if turnover_as_percent:
                # 东财原始换手率恒为百分数；低换手日也可能全 <1，不能用启发式。
                out["turnover"] = out["turnover"] / 100.0
        return out.reset_index(drop=True)
