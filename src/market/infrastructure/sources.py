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

from abc import ABC, abstractmethod
import logging
import time
from typing import Any

import pandas as pd

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

        return sina.fetch_hfq_factors(to_sina_symbol(code))

    def fetch_instruments(self) -> pd.DataFrame:
        return fetch_instrument_list()


class EastmoneySource(QuoteSource):
    """东财源。备源：主源失败时顶上，也用于交叉校验。"""

    name = "eastmoney"

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
        out = frame.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover",
            }
        )
        # 东财「成交量」为手，行情仓与新浪/腾讯统一为股。
        if "volume" in out.columns:
            out["volume"] = pd.to_numeric(out["volume"], errors="coerce") * 100.0
        # 东财「换手率」为百分数（5.0=5%）；行情仓 / COST 要小数（0.05）。
        # 转换写在 Source，sync 降级链与 Adapter 共用同一口径。
        if "turnover" in out.columns:
            out["turnover"] = pd.to_numeric(out["turnover"], errors="coerce") / 100.0
        return out


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

    def collect(label: str, loader: Any, mapping: dict[str, str], board: str) -> None:
        try:
            raw = loader()
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            return
        if raw is None or raw.empty:
            errors.append(f"{label}: 空表")
            return
        available = {src: dst for src, dst in mapping.items() if src in raw.columns}
        if "code" not in available.values():
            errors.append(f"{label}: 缺代码列（实际列 {list(raw.columns)[:6]}）")
            return
        frame = raw.rename(columns=available)[list(available.values())].copy()
        frame["board"] = frame.get("board", board)
        if "industry" not in frame.columns:
            frame["industry"] = ""
        frames.append(frame)

    collect(
        "上交所",
        ak.stock_info_sh_name_code,
        {"证券代码": "code", "证券简称": "name", "上市日期": "list_date"},
        "上交所",
    )
    collect(
        "深交所",
        lambda: ak.stock_info_sz_name_code(symbol="A股列表"),
        {
            "A股代码": "code",
            "A股简称": "name",
            "A股上市日期": "list_date",
            "板块": "board",
            "所属行业": "industry",
        },
        "深交所",
    )
    collect(
        "北交所",
        getattr(ak, "stock_info_bj_name_code", lambda: pd.DataFrame()),
        {"证券代码": "code", "证券简称": "name", "上市日期": "list_date"},
        "北交所",
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
    em_map = fetch_em_industry_map()
    if em_map:
        mapped = merged["code"].map(em_map)
        merged["industry"] = mapped.where(mapped.notna() & (mapped != ""), merged["industry"])
    return merged.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)


def _normalize_industry(value: object) -> str:
    """深交所「J 金融业」→「金融业」；空值保底。"""
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    # 证监会门类前缀：单字母 + 空格
    if len(text) >= 3 and text[0].isalpha() and text[1] == " ":
        return text[2:].strip()
    return text


def fetch_em_industry_map() -> dict[str, str]:
    """东财行业板块成分 → code→行业名（如半导体、电力设备）。失败返回空字典。"""
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if os.environ.get("LOCI_SKIP_EM_INDUSTRY", "").strip() in {"1", "true", "yes"}:
        return {}
    try:
        ak = _import_akshare()
        boards = ak.stock_board_industry_name_em()
    except Exception as exc:
        logger.warning("取东财行业板块列表失败：%s", exc)
        return {}
    if boards is None or boards.empty:
        return {}
    name_col = "板块名称" if "板块名称" in boards.columns else boards.columns[1]
    names = [str(n).strip() for n in boards[name_col].tolist() if str(n).strip()]
    out: dict[str, str] = {}

    def one(name: str) -> dict[str, str]:
        try:
            cons = ak.stock_board_industry_cons_em(symbol=name)
        except Exception:
            return {}
        if cons is None or cons.empty:
            return {}
        code_col = "代码" if "代码" in cons.columns else None
        if not code_col:
            return {}
        local: dict[str, str] = {}
        for raw in cons[code_col].tolist():
            code = str(raw).strip().zfill(6)
            if code.isdigit() and len(code) == 6:
                local[code] = name
        return local

    workers = min(8, max(2, len(names) // 10 or 2))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, name) for name in names]
        for fut in as_completed(futures):
            try:
                out.update(fut.result())
            except Exception as exc:  # pragma: no cover
                logger.debug("行业成分合并失败：%s", exc)
    logger.info("东财行业映射 %s 只", len(out))
    return out


def default_sources() -> list[QuoteSource]:
    """默认降级链：新浪优先（一次拿全历史且字段全），东财兜底。"""
    return [SinaSource(), EastmoneySource()]


def fetch_with_fallback(
    sources: list[QuoteSource],
    code: str,
    *,
    instrument_type: str = "STOCK",
    retries: int = 2,
    backoff: float = 1.5,
) -> tuple[pd.DataFrame, str]:
    """依次尝试每个源，每个源内部重试。返回 (日线, 命中的源名)。

    重试用退避而不是固定间隔：被限流时立刻重试只会加深限流。
    """
    errors: list[str] = []
    for source in sources:
        for attempt in range(retries + 1):
            try:
                frame = source.fetch_daily(code, instrument_type=instrument_type)
                return frame, source.name
            except SourceError as exc:
                errors.append(f"{source.name}#{attempt + 1}: {exc}")
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
    raise SourceError(f"{code} 全部数据源失败 -> " + " | ".join(errors[-4:]))
