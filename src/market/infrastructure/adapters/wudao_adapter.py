"""悟道 MCP 日 K 适配器 — 配置生效且可用时作为 hist_daily 高优先级备源。"""
from __future__ import annotations

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    LANE_HIST_DAILY,
    ProbeHint,
    ProbeResult,
)


def wudao_adapter_enabled() -> bool:
    # 延迟导入：src.intel 会反向依赖 src.market，模块级导入会成环
    try:
        from src.intel import (
            wudao_availability,
            wudao_hist_daily_primary,
        )

        if not wudao_hist_daily_primary():
            return False
        return bool(wudao_availability().get("available"))
    except Exception:
        return False


class WudaoAdapter(MarketAdapter):
    meta = AdapterMeta(
        id="wudao",
        label="悟道",
        lanes=(LANE_HIST_DAILY,),
        description="悟道 MCP 的 kline 日 K 旁路；需 Key 且开启「日 K 优先」。不单独出现在数据源目录。",
        base_url="https://stock.quicktiny.cn",
        probe_hints={LANE_HIST_DAILY: ProbeHint(note="320d")},
    )

    #: 悟道 kline 单次根数上限。**权威来源是服务端 schema**（`maxRows ≤ 150`，
    #: 与 `intel/application/arg_clamp._MCP_ROWS_MAX` 同源）。这里曾写 320，
    #: 于是 `fetch_daily()` 每次都带 `maxRows=320` 被服务端整条拒——一个
    #: 「永远失败但照扣配额」的调用。参数上限只能对齐服务端，不能自己拍。
    MAX_BARS = 150

    #: 单次可以问几只。悟道 `kline` 的 `codes` 是数组，上限 20；过去固定塞
    #: 单元素列表，等于把配额白扔 20 倍。全市场 5500 只逐票调用会直接打穿
    #: 日总 5000 的配额，这条源根本不可能当主源用——它只适合小批量旁路核对。
    MAX_CODES_PER_CALL = 20

    #: 缓存窗。**盘中绝不能用长 TTL**：缓存键按交易日走，10:00 抓到的半截
    #: 当日 bar 会在 15:40 被当成权威收盘日 K 复用，收盘价直接是错的。
    #: 收盘后当日 K 已定稿，才允许长 TTL。判据统一走 `intel` 侧的收盘判定，
    #: 这里只给两个候选值。
    _CACHE_MINUTES_SETTLED = 360
    _CACHE_MINUTES_INTRADAY = 5

    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        _ = instrument_type
        return self._fetch_bars(code, self.MAX_BARS)

    def fetch_daily_window(
        self, code: str, *, instrument_type: str = "STOCK", bars: int
    ) -> pd.DataFrame:
        _ = instrument_type
        return self._fetch_bars(code, min(max(1, bars), self.MAX_BARS))

    def fetch_daily_many(
        self,
        codes: list[str],
        *,
        bars: int | None = None,
        workers: int = 1,
    ) -> dict[str, pd.DataFrame]:
        """批量日 K：一次问 ≤20 只，这是本源唯一划算的用法。

        ``workers`` 忽略：悟道是有配额、有每分钟上限的付费 MCP，并发扇出只会
        更快打穿限流。省调用靠的是每次多问几只，不是同时问几次。
        """
        _ = workers
        from src.intel import kline_payload_frames

        want = min(max(1, int(bars or self.MAX_BARS)), self.MAX_BARS)
        wanted = [str(c).strip().zfill(6) for c in codes if str(c).strip()]
        out: dict[str, pd.DataFrame] = {}
        for start in range(0, len(wanted), self.MAX_CODES_PER_CALL):
            chunk = wanted[start : start + self.MAX_CODES_PER_CALL]
            try:
                payload = self._call_kline(chunk, want)
            except AdapterError:
                # 单批失败不拖垮其余批；缺的票不出现在返回值里，调用方自行回退。
                continue
            for code, frame in kline_payload_frames(payload).items():
                if frame is None or frame.empty:
                    continue
                try:
                    out[code] = self._normalize_daily_frame(frame, who="悟道")
                except Exception:
                    continue
        return out

    def _cache_minutes(self) -> int:
        """收盘后才允许长缓存；盘中复用会把半截 bar 当收盘价。"""
        try:
            from src.ops.application.session_clock import session_clock

            settled = session_clock().phase == "closed"
            return self._CACHE_MINUTES_SETTLED if settled else self._CACHE_MINUTES_INTRADAY
        except Exception:
            # 判不出来就按盘中处理：宁可多打几次，也不能发错收盘价。
            return self._CACHE_MINUTES_INTRADAY

    def _call_kline(self, codes: list[str], bars: int) -> dict:
        from src.intel import BUILTIN_WUDAO_NAME, call_mcp_tool

        try:
            payload = call_mcp_tool(
                "kline",
                {"codes": codes, "days": bars, "maxRows": bars},
                server=BUILTIN_WUDAO_NAME,
                pool="structured",
                cache=True,
                cache_max_age_minutes=self._cache_minutes(),
            )
        except Exception as exc:
            raise AdapterError(f"悟道 kline 失败：{exc}") from exc
        if payload.get("is_error"):
            raise AdapterError(str(payload.get("text") or "悟道 kline 返回错误"))
        return payload

    def _fetch_bars(self, code: str, bars: int) -> pd.DataFrame:
        from src.intel import kline_payload_to_frame

        payload = self._call_kline([str(code).zfill(6)], bars)
        frame = kline_payload_to_frame(payload)
        return self._normalize_daily_frame(frame, who="悟道")

    def probe(self, lane: str, *, code: str = "600519") -> ProbeResult:
        if lane != LANE_HIST_DAILY:
            return ProbeResult(adapter_id=self.meta.id, lane=lane, unsupported=True)
        if not wudao_adapter_enabled():
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=lane,
                ok=False,
                error="未配置 Key 或未开启日 K 优先",
            )
        return super().probe(lane, code=code)
