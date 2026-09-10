"""行情数据源适配器。

多源的意义不是"更全"，而是**活着**：akshare 底层是对东财/新浪网页接口的
爬取封装，上游随时可能改版或限流封 IP，个人服务器通常只有一个公网出口，
一被封就是系统性瘫痪。所以取数必须能在源之间热切换。

实测（2026-07-26）：
- 新浪 `stock_zh_a_daily` 一次返回**全部历史**（贵州茅台 5968 根，0.44s），
  且自带 turnover 与 outstanding_share——通达信的换手率、量比、COST 筹码
  分布公式都依赖这两个字段。作为主源。
- akshare 的 `stock_zh_a_hist` 走 `82.push2.eastmoney.com` 这类编号子域名，
  在部分网络下不可达，而基础域名 `push2.eastmoney.com` 是通的。作为备源，
  且要能在主源失败时顶上。
"""
from __future__ import annotations

from src.shared.clock import utc_now

from abc import ABC, abstractmethod
import logging
import threading
import time
from typing import Any

import pandas as pd

from src.market.infrastructure.em_industry import fetch_em_industry_map
from src.market.infrastructure.store import normalize_code, to_sina_symbol

logger = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """取数失败。调用方据此决定降级到下一个源还是记 watermark 失败。"""


def _import_akshare() -> Any:
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover - 依赖缺失路径
        raise SourceError(
            "未安装 akshare，无法取行情。安装方式：pip install akshare"
        ) from exc
    return ak


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


class BaostockSource(QuoteSource):
    """证券宝（baostock）日线：独立免费源，登录后拉不复权 K 线。

    对齐 Vibe-Trading A 股 fallback 链中的 ``baostock`` 位；不经 akshare。
    SDK 会话全局共享，并发取数串行化 login/query/logout。
    """

    name = "baostock"
    source_url = "http://baostock.com"

    _lock = threading.Lock()

    def fetch_daily(
        self,
        code: str,
        *,
        instrument_type: str = "STOCK",
        start_date: str = "1990-01-01",
        end_date: str = "2099-12-31",
    ) -> pd.DataFrame:
        try:
            import baostock as bs
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise SourceError(
                "未安装 baostock，无法取证券宝行情。安装方式：pip install baostock"
            ) from exc

        from src.market.infrastructure.store import guess_market

        plain = normalize_code(code)
        symbol = f"{guess_market(plain, instrument_type=instrument_type)}.{plain}"
        fields = "date,open,high,low,close,volume,amount,turn"
        with self._lock:
            login = bs.login()
            if getattr(login, "error_code", "0") not in ("0", 0, None, ""):
                raise SourceError(
                    f"baostock 登录失败：{getattr(login, 'error_msg', login)}"
                )
            try:
                result = bs.query_history_k_data_plus(
                    symbol,
                    fields,
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="3",  # 不复权
                )
                if getattr(result, "error_code", "0") not in ("0", 0, None, ""):
                    raise SourceError(
                        f"baostock 取 {symbol} 失败："
                        f"{getattr(result, 'error_msg', result)}"
                    )
                rows: list[list[str]] = []
                while result.error_code == "0" and result.next():
                    rows.append(result.get_row_data())
            finally:
                bs.logout()

        if not rows:
            raise SourceError(f"baostock 返回 {symbol} 空数据")
        # 保留原始 turn（百分数）；换算交给管线 FieldSpec(unit_by_source)。
        return pd.DataFrame(rows, columns=fields.split(","))


class EastmoneySource(QuoteSource):
    """东财源（akshare ``stock_zh_a_hist``）。备源；覆盖 Vibe 链上的 eastmoney/akshare-hist。"""

    name = "eastmoney"
    source_url = "https://quote.eastmoney.com"

    def fetch_daily(
        self,
        code: str,
        *,
        instrument_type: str = "STOCK",
        start_date: str = "19900101",
        end_date: str = "20991231",
    ) -> pd.DataFrame:
        ak = _import_akshare()
        plain = normalize_code(code)
        try:
            if instrument_type == "INDEX":
                frame = ak.index_zh_a_hist(
                    symbol=plain,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                )
            else:
                frame = ak.stock_zh_a_hist(
                    symbol=plain,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="",
                )
        except Exception as exc:
            raise SourceError(f"东财取 {plain} 日线失败：{type(exc).__name__}: {exc}") from exc
        if frame is None or frame.empty:
            raise SourceError(f"东财返回 {plain} 空数据")
        # 原始中文表；列映射与单位换算由 Adapter / fetch_with_fallback 走管线。
        return frame


def fetch_instrument_list() -> pd.DataFrame:
    """按交易所分别取上市证券列表，合并成 code/name/board/list_date/industry。

    刻意**不用** ``ak.stock_info_a_code_name()``：它内部依赖 py_mini_racer
    执行 JS，在本项目的多线程同步场景下会触发原生崩溃（不是 Python 异常，
    整个进程直接挂掉，连 traceback 都拿不到）。交易所各自的列表接口是
    纯表格下载，更快也更稳，还额外带板块与上市日期。
    """
    ak = _import_akshare()
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    complete_markets: set[str] = set()

    def collect(
        label: str, loader: Any, contract: Any, board: str, market: str
    ) -> None:
        from src.market.infrastructure.pipeline import NormalizeError, normalize

        try:
            raw = loader()
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            return
        if raw is None or raw.empty:
            errors.append(f"{label}: 空表")
            return
        try:
            frame = normalize(raw, contract, who=label, empty_label=f"{label}列表")
        except NormalizeError as exc:
            errors.append(f"{label}: {exc}")
            return
        if "code" not in frame.columns:
            errors.append(f"{label}: 缺代码列（实际列 {list(raw.columns)[:6]}）")
            return
        frame = frame.copy()
        if "board" not in frame.columns or frame["board"].isna().all():
            frame["board"] = board
        else:
            frame["board"] = frame["board"].fillna(board)
        if "industry" not in frame.columns:
            frame["industry"] = ""
        frame["market"] = market
        frames.append(frame)
        complete_markets.add(market.lower())

    from src.market.domain.source_contract import (
        INSTRUMENTS_BJ_CONTRACT,
        INSTRUMENTS_SH_CONTRACT,
        INSTRUMENTS_SZ_CONTRACT,
    )

    collect(
        "上交所",
        ak.stock_info_sh_name_code,
        INSTRUMENTS_SH_CONTRACT,
        "上交所",
        "SH",
    )
    collect(
        "深交所",
        lambda: ak.stock_info_sz_name_code(symbol="A股列表"),
        INSTRUMENTS_SZ_CONTRACT,
        "深交所",
        "SZ",
    )
    collect(
        "北交所",
        getattr(ak, "stock_info_bj_name_code", lambda: pd.DataFrame()),
        INSTRUMENTS_BJ_CONTRACT,
        "北交所",
        "BJ",
    )

    if not frames:
        raise SourceError("取不到任何交易所的证券列表 -> " + " | ".join(errors))
    if errors:
        logger.warning("部分交易所列表取失败：%s", " | ".join(errors))

    merged = pd.concat(frames, ignore_index=True)
    merged["code"] = merged["code"].astype(str).str.strip().str.zfill(6)
    merged = merged[merged["code"].str.fullmatch(r"\d{6}")]
    if "industry" not in merged.columns:
        merged["industry"] = ""
    merged["industry"] = merged["industry"].fillna("").map(_normalize_industry)
    # 东财行业板块成分覆盖沪深（半导体/电力设备等），补全上交所等缺行业行
    # 走 7 天磁盘缓存（em_industry_map.json）：这张图 ~90 次 akshare，不能每次同步都拉
    em_map = fetch_em_industry_map()
    if em_map:
        mapped = merged["code"].map(em_map)
        merged["industry"] = mapped.where(mapped.notna() & (mapped != ""), merged["industry"])
    merged = merged.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)
    merged.attrs["complete_markets"] = tuple(sorted(complete_markets))
    return merged


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
    return [SinaSource(), EastmoneySource(), BaostockSource()]


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
        "eastmoney": "东财",
        "baostock": "证券宝",
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
