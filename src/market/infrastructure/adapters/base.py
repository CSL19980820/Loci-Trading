"""MarketAdapter 抽象基类。

转换逻辑经共享管线；基类定契约、探测模板与 spot/live 共用流程。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import time
from typing import Any

import pandas as pd

from src.market.domain.source_contract import DAILY_CONTRACT, SPOT_CONTRACT
from src.market.infrastructure.adapters.types import (
    AdapterMeta,
    DAILY_REQUIRED_COLUMNS,
    ProbeHint,
    ProbeResult,
)
from src.market.infrastructure.pipeline import NormalizeError, empty_spot_frame, normalize


class AdapterError(RuntimeError):
    """适配器取数失败。router / 调用方据此换路或上报。"""


#: 交易日 → 自然日的换算余量（A 股一年约 243 个交易日）。
_CALENDAR_PER_BAR = 1.6
_WINDOW_SLACK_DAYS = 15


def window_start_date(bars: int, *, today: date | None = None) -> date:
    """按需要的 K 线根数反推起始自然日；宁可多要几天也不要缺档。"""
    anchor = today or date.today()
    span = int(max(1, bars) * _CALENDAR_PER_BAR) + _WINDOW_SLACK_DAYS
    return anchor - timedelta(days=span)


#: spot / live 分批取数的并发路数。
#: 全市场一轮要打 ~5500 个代码：新浪 400/批 ≈ 14 批，腾讯 80/批 ≈ 69 批。
#: 串行时墙钟 = 批数 × 单批往返，而单批往返里真正的网络等待只占 25~35%
#: （其余耗在建连/TLS、GBK 解码与逐行解析上），这部分正好能被少量线程重叠掉。
#: 取 6 而不是「越大越好」：
#:   1. hq.sinajs.cn / qt.gtimg.cn 对同一 IP 的突发并发很敏感，十几路起就
#:      容易被限流成 403 或截断报文，触发重试后反而比串行更慢；
#:   2. market_session() 每次请求新建 Session（连接不跨批复用），并发路数
#:      就是并发 TCP 连接数，6 路与浏览器对单域名的连接上限同量级；
#:   3. 6 路已把新浪 14 批压到 3 轮、腾讯 69 批压到 12 轮，再加路数只剩尾批
#:      对齐的边际收益，抵不过被限流的风险。
_SPOT_FETCH_WORKERS = 6

#: ``batch_size=None``（来源自行分批）时 base 层再切片的最小片长。
#: 比它还少的代码数切片只是白付线程开销，直接整表一次交给 caller。
_SELF_BATCHED_MIN_SHARD = 400


def _batch_span(total: int, batch_size: int | None) -> int:
    """每批的代码数。

    ``batch_size=None`` 表示来源自行分批（腾讯内部 80/批）；这时按并发路数
    把整表均分成至多 ``_SPOT_FETCH_WORKERS`` 片并行喂，片内仍由来源自行分批。
    """
    if batch_size is not None:
        return max(1, batch_size)
    if total <= _SELF_BATCHED_MIN_SHARD:
        return max(1, total)
    return max(_SELF_BATCHED_MIN_SHARD, -(-total // _SPOT_FETCH_WORKERS))


def _split_batches(symbols: list[str], span: int) -> list[list[str]]:
    return [symbols[start : start + span] for start in range(0, len(symbols), span)]


def _map_batches(
    batches: Sequence[list[str]],
    caller: Callable[[list[str]], Any],
    *,
    error_types: tuple[type[BaseException], ...],
) -> tuple[list[Any], list[str]]:
    """有界并发跑各批，**按批次序**返回成功载荷与错误摘要。

    两条不可动的语义：
      * 单批失败只记 errors 并继续跑其余批，整轮不中断；
      * 拼接顺序是批次序而不是完成序——下游 concat 之后按「先出现的行胜出」
        去重，用完成序会让同一代码的重复行随网络抖动改变胜出者。
    """

    def run(index: int) -> tuple[Any, str | None]:
        batch = list(batches[index])
        try:
            return caller(batch), None
        except error_types as exc:
            return None, f"{batch[0]}…: {exc}"
        except Exception as exc:  # 单批异常不得打断整轮
            return None, f"{batch[0]}…: {type(exc).__name__}: {exc}"

    if len(batches) <= 1:
        pairs = [run(index) for index in range(len(batches))]
    else:
        with ThreadPoolExecutor(
            max_workers=min(_SPOT_FETCH_WORKERS, len(batches)),
            thread_name_prefix="spot-batch",
        ) as pool:
            # map 保证按提交顺序回收结果，天然就是批次序。
            pairs = list(pool.map(run, range(len(batches))))

    payloads = [payload for payload, _error in pairs if payload is not None]
    errors = [error for _payload, error in pairs if error is not None]
    return payloads, errors


class MarketAdapter(ABC):
    """一条可接入数据源。

    ``meta.lanes`` 声明自己接哪些 lane；未实现的方法保持 stub，
    ``probe`` 对不支持的 lane 返回 ``unsupported=True``。
    """

    meta: AdapterMeta

    @abstractmethod
    def fetch_daily(
        self, code: str, *, instrument_type: str = "STOCK"
    ) -> pd.DataFrame:
        """返回已归一的不复权日线。

        必选列：date/open/high/low/close/volume/amount。
        可选：turnover（小数）、outstanding_share。
        """

    def fetch_daily_window(
        self, code: str, *, instrument_type: str = "STOCK", bars: int
    ) -> pd.DataFrame:
        """只取最近 ``bars`` 根日线。列契约与 ``fetch_daily`` 相同。

        日常增量同步用它避免每天重拉三十年历史；来源不支持近窗时回落全量，
        调用方拿到的仍是可直接落库的一张表。
        """
        return self.fetch_daily(code, instrument_type=instrument_type)

    def fetch_spot_sample(self, codes: list[str] | None = None) -> pd.DataFrame:
        """批量现价小样本（探测用）。默认走 ``fetch_spot``。"""
        sample = codes or ["600519", "000001"]
        return self.fetch_spot(sample)

    def fetch_spot(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> pd.DataFrame:
        """批量现价。返回列至少含 code/date/open/high/low/close/volume/amount。"""
        raise AdapterError(f"{self.meta.id} 不支持 spot_batch")

    def fetch_live_quotes(
        self,
        codes: list[str],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
    ) -> list[dict]:
        """顶栏/列表富行情。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 spot_batch live")

    def fetch_instruments(self) -> pd.DataFrame:
        """证券列表。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 instruments")

    def fetch_adjust_factors(self, code: str) -> pd.DataFrame:
        """复权因子。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 adjust_factor")

    def fetch_minute(
        self,
        code: str,
        *,
        period: str = "1",
        days: int = 1,
        trade_date: str | None = None,
    ) -> pd.DataFrame:
        """分钟 K 线。默认不支持。

        ``trade_date`` 为 ``YYYY-MM-DD`` 时只取该交易日（实时拉取，不落库）。
        """
        raise AdapterError(f"{self.meta.id} 不支持 minute_bars")

    def fetch_capital_flow(self, code: str) -> pd.DataFrame:
        """个股资金流。默认不支持。"""
        raise AdapterError(f"{self.meta.id} 不支持 capital_flow")

    def _fetch_daily_for_probe(self, code: str) -> pd.DataFrame:
        """探测用日线；默认全量。子类可覆盖为近窗。"""
        return self.fetch_daily(code)

    def probe(self, lane: str, *, code: str = "600519") -> ProbeResult:
        """连通探测：小样本取数 + RTT。

        读 ``meta.probe_hints`` 填充 ``extra.probe_window``；日线近窗由
        ``_fetch_daily_for_probe`` 钩子决定。
        """
        from src.market.infrastructure.adapters.types import (
            LANE_ADJUST_FACTOR,
            LANE_CAPITAL_FLOW,
            LANE_HIST_DAILY,
            LANE_INSTRUMENTS,
            LANE_MINUTE,
            LANE_SPOT_BATCH,
        )

        if lane not in self.meta.lanes:
            return ProbeResult(
                adapter_id=self.meta.id,
                lane=lane,
                ok=False,
                unsupported=True,
                error=f"{self.meta.label} 不支持 lane={lane}",
            )

        hint = self.meta.probe_hints.get(lane) or ProbeHint()
        started = time.perf_counter()
        try:
            rows: int | None = None
            extra: dict[str, Any] = {}
            if hint.note:
                extra["probe_window"] = hint.note
            if lane == LANE_HIST_DAILY:
                frame = self._fetch_daily_for_probe(code)
                self._assert_daily_shape(frame)
                rows = int(len(frame))
            elif lane == LANE_SPOT_BATCH:
                frame = self.fetch_spot_sample([code])
                rows = int(len(frame)) if frame is not None else 0
            elif lane == LANE_INSTRUMENTS:
                frame = self.fetch_instruments()
                rows = int(len(frame)) if frame is not None else 0
                if rows == 0:
                    raise AdapterError("证券列表为空")
            elif lane == LANE_ADJUST_FACTOR:
                frame = self.fetch_adjust_factors(code)
                rows = int(len(frame)) if frame is not None else 0
                if rows == 0:
                    raise AdapterError("复权因子为空")
            elif lane == LANE_MINUTE:
                frame = self.fetch_minute(code, period="1", days=1)
                rows = int(len(frame)) if frame is not None else 0
                if rows == 0:
                    raise AdapterError("分钟线为空")
                extra.setdefault("period", "1")
                extra.setdefault("days", 1)
            elif lane == LANE_CAPITAL_FLOW:
                frame = self.fetch_capital_flow(code)
                rows = int(len(frame)) if frame is not None else 0
                if rows == 0:
                    raise AdapterError("资金流为空")
            else:
                return ProbeResult(
                    adapter_id=self.meta.id,
                    lane=lane,
                    ok=False,
                    unsupported=True,
                    error=f"未知或未实现的 lane={lane}",
                )
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

    def _spot_via_symbols(
        self,
        codes: list[str],
        caller: Callable[[list[str]], pd.DataFrame],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int | None = 400,
        who: str,
        fetch_error_type: type[BaseException] | tuple[type[BaseException], ...] | None = None,
    ) -> pd.DataFrame:
        """sina/tencent 共用：代码→symbol→取现价→回填 code→管线选列。

        各批以 ``_SPOT_FETCH_WORKERS`` 路有界并发发出；单批失败仍只记 errors、
        不打断整轮，拼接顺序仍是批次序（见 ``_map_batches``）。

        ``batch_size=None``：交给 caller 自行分批（对齐 live）；代码数超过
        ``_SELF_BATCHED_MIN_SHARD`` 时先均分成几片并行喂，片内照旧由来源分批。
        这时单片失败同样只记 errors、其余片照常入库——原来是整表一次调用，
        任何一个内部批炸掉都等于整轮无数据。
        """
        from src.market.infrastructure.store import normalize_code, to_sina_symbol

        types = instrument_types or {}
        normalized = [normalize_code(c) for c in codes if str(c).strip()]
        if not normalized:
            return empty_spot_frame()

        symbol_to_code = {
            to_sina_symbol(code, instrument_type=types.get(code, "STOCK")): code
            for code in normalized
        }
        symbols = list(symbol_to_code)
        error_types: tuple[type[BaseException], ...] = (
            (fetch_error_type,)
            if isinstance(fetch_error_type, type)
            else (fetch_error_type or (Exception,))
        )
        spots, errors = _map_batches(
            _split_batches(symbols, _batch_span(len(symbols), batch_size)),
            caller,
            error_types=error_types,
        )

        frames: list[pd.DataFrame] = []
        for spot in spots:
            if spot is None or spot.empty:
                continue
            out = spot.copy()
            out["code"] = out["symbol"].map(symbol_to_code)
            out = out.dropna(subset=["code"])
            if not out.empty:
                frames.append(out)

        if not frames:
            detail = "；".join(errors[-3:]) if errors else "空数据"
            raise AdapterError(f"{who}现价失败：{detail}")
        merged = pd.concat(frames, ignore_index=True)
        try:
            return normalize(
                merged,
                SPOT_CONTRACT,
                who=who,
                empty_label=f"{who}现价",
            )
        except NormalizeError as exc:
            raise AdapterError(str(exc)) from exc

    def _live_via_symbols(
        self,
        codes: list[str],
        caller: Callable[[list[str]], list[dict]],
        *,
        instrument_types: dict[str, str] | None = None,
        batch_size: int = 400,
        who: str,
    ) -> list[dict]:
        """sina/tencent 共用：代码→symbol→live→回填 code。

        底层模块自行分批，这里只把整表均分成几片、以 ``_SPOT_FETCH_WORKERS`` 路
        并发喂进去；单片失败只记错误并保留其余片的报价，全片皆败才抛。
        """
        from src.market.infrastructure.store import normalize_code, to_sina_symbol

        _ = batch_size  # 底层模块自行分批
        types = instrument_types or {}
        normalized = [normalize_code(c) for c in codes if str(c).strip()]
        if not normalized:
            return []
        symbol_to_code = {
            to_sina_symbol(code, instrument_type=types.get(code, "STOCK")): code
            for code in normalized
        }
        symbols = list(symbol_to_code)
        batches = _split_batches(symbols, _batch_span(len(symbols), None))
        payloads, errors = _map_batches(batches, caller, error_types=(Exception,))
        if errors and len(errors) == len(batches):
            raise AdapterError(f"{who} live 行情异常：{errors[-1]}")
        out: list[dict] = []
        for rows in payloads:
            for row in rows or []:
                code = symbol_to_code.get(str(row.get("symbol") or ""))
                if not code:
                    continue
                item = dict(row)
                item["code"] = code
                out.append(item)
        if not out:
            raise AdapterError(f"{who} live 行情为空")
        return out

    @staticmethod
    def _assert_daily_shape(frame: pd.DataFrame) -> None:
        if frame is None or frame.empty:
            raise AdapterError("日线为空")
        missing = [c for c in DAILY_REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            raise AdapterError(f"日线缺列：{missing}")

    @staticmethod
    def _normalize_daily_frame(frame: pd.DataFrame, *, who: str) -> pd.DataFrame:
        try:
            return normalize(
                frame,
                DAILY_CONTRACT,
                who=who,
                empty_label=f"{who}日线",
            )
        except NormalizeError as exc:
            raise AdapterError(str(exc)) from exc

    def catalog_entry(self) -> dict[str, Any]:
        """给 list_catalog / API 用的扁平字典。"""
        return {
            "id": self.meta.id,
            "label": self.meta.label,
            "lanes": list(self.meta.lanes),
            "description": self.meta.description,
            "base_url": self.meta.base_url,
        }
