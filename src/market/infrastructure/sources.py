"""新浪日线源与通用测试注入契约。常规取数统一经过受控适配器路由。"""
from __future__ import annotations

from src.shared.clock import utc_now

from abc import ABC, abstractmethod
import logging
import time
from typing import Any

import pandas as pd

from src.market.infrastructure.store import to_sina_symbol

logger = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """取数失败。调用方据此决定降级到下一个源还是记 watermark 失败。"""




class QuoteSource(ABC):
    """一个数据源要能回答三个问题：有哪些票、某票的历史、某票的复权因子。"""

    name: str = "base"

    @abstractmethod
    def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
        """返回**不复权**日线。列至少含 date/open/high/low/close/volume。"""

    def fetch_adjust_factors(self, code: str) -> pd.DataFrame:
        """返回稀疏后复权因子（date, hfq_factor）。不支持则返回空表。"""
        return pd.DataFrame(columns=["date", "hfq_factor"])

    def fetch_instruments(self) -> pd.DataFrame:
        """返回证券列表（code, name）。不支持则返回空表。"""
        return pd.DataFrame(columns=["code", "name"])


class SinaSource(QuoteSource):
    """新浪源：一次拿全历史，自带换手率与流通股本。主源。

    走 ``src/market/sina.py`` 的直连实现，**不经 akshare**。原因是
    ``ak.stock_zh_a_daily`` 每次都新建 V8 isolate 跑解密 JS，多线程并发下
    会触发 V8 地址空间初始化竞态，把整个进程原生打死（不是 Python 异常，
    没有 traceback，正在跑的回填全部丢失）。直连版把 HTTP 与 JS 解码拆开，
    只给解码加锁，实测 6 并发 48/48 成功、0.10s/次，比走 akshare 快 4.7 倍。
    """

    name = "sina"
    source_url = "https://finance.sina.com.cn"

    def fetch_daily(self, code: str, *, instrument_type: str = "STOCK") -> pd.DataFrame:
        from src.market import sina

        symbol = to_sina_symbol(code, instrument_type=instrument_type)
        try:
            frame = sina.fetch_daily(symbol)
        except sina.SinaFetchError as exc:
            raise SourceError(f"新浪取 {symbol} 日线失败：{exc}") from exc
        except Exception as exc:
            raise SourceError(f"新浪取 {symbol} 日线异常：{type(exc).__name__}: {exc}") from exc
        if frame is None or frame.empty:
            raise SourceError(f"新浪返回 {symbol} 空数据")
        return frame

    def fetch_adjust_factors(self, code: str) -> pd.DataFrame:
        from src.market import sina

        symbol = to_sina_symbol(code)
        try:
            return sina.fetch_hfq_factors(symbol)
        except sina.SinaFetchError as exc:
            # 取数失败要往上抛（换源 / 记回执），不能吞成「这只票没有除权事件」。
            raise SourceError(f"新浪取 {symbol} 复权因子失败：{exc}") from exc

    def fetch_instruments(self) -> pd.DataFrame:
        return fetch_instrument_list()








def _normalize_industry(value: object) -> str:
    """深交所「J 金融业」→「金融业」；空值保底。"""
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    # 证监会门类前缀：单字母 + 空格
    if len(text) >= 3 and text[0].isalpha() and text[1] == " ":
        return text[2:].strip()
    return text




def default_sources() -> list[QuoteSource]:
    """遗留顺序降级链（sync 在未走 adapter 路由时用）。

    日常同步优先 ``fetch_daily_routed``；此处保留字段更全的新浪优先语义。
    """
    return [SinaSource()]


def fetch_with_fallback(
    sources: list[QuoteSource],
    code: str,
    *,
    instrument_type: str = "STOCK",
    retries: int = 2,
    backoff: float = 1.5,
    receipt: list[dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, str]:
    """依次尝试每个源，每个源内部重试。返回 (日线, 命中的源名)。

    重试用退避而不是固定间隔：被限流时立刻重试只会加深限流。
    Source 只出原始表；此处统一过管线，与 Adapter 出口一致。
    """
    from src.market.domain.source_contract import DAILY_CONTRACT
    from src.market.infrastructure.pipeline import NormalizeError, normalize

    labels = {
        "sina": "新浪",
    }
    errors: list[str] = []
    for source in sources:
        who = labels.get(source.name, source.name)
        for attempt in range(retries + 1):
            try:
                raw = source.fetch_daily(code, instrument_type=instrument_type)
                try:
                    frame = normalize(
                        raw, DAILY_CONTRACT, who=who, empty_label=f"{who}日线"
                    )
                except NormalizeError as exc:
                    raise SourceError(str(exc)) from exc
                if receipt is not None:
                    receipt.append(
                        {
                            "source_id": source.name,
                            "state": "selected",
                            "attempt": attempt + 1,
                            "checked_at": utc_now(),
                            "rows": int(len(frame)) if frame is not None else 0,
                            "fields": [str(field) for field in frame.columns]
                            if frame is not None
                            else [],
                        }
                    )
                return frame, source.name
            except Exception as exc:
                errors.append(f"{source.name}#{attempt + 1}: {exc}")
                if receipt is not None:
                    receipt.append(
                        {
                            "source_id": source.name,
                            "state": "failed",
                            "attempt": attempt + 1,
                            "checked_at": utc_now(),
                            "error": str(exc)[:500],
                        }
                    )
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
    raise SourceError(f"{code} 全部数据源失败 -> " + " | ".join(errors[-4:]))


def fetch_instrument_list() -> pd.DataFrame:
    """直接读取交易所名录，不扩散到其他数据提供方。"""
    from src.market.infrastructure.exchange_instruments import InstrumentListError, fetch_exchange_instruments
    try:
        return fetch_exchange_instruments()
    except InstrumentListError as exc:
        raise SourceError(str(exc)) from exc
