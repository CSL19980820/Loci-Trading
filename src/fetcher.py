"""A 股数据采集模块

容错原则: 每个数据源独立 try/except, 单个失败不影响其他数据, 最终返回聚合字典.
数据源: AkShare 聚合 (东方财富/新浪/同花顺口径).
可靠性: 关键接口(K线/实时行情)支持重试.
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Callable

import akshare as ak
import pandas as pd
import yfinance as yf


def _with_retry(fn: Callable, *args, retries: int = 3, delay: float = 1.5, **kwargs):
    """通用重试装饰器: 对网络类错误重试 retries 次"""
    last_exc: Exception | None = None
    for i in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if i < retries - 1:
                time.sleep(delay * (i + 1))
    if last_exc:
        raise last_exc


def detect_market(code: str) -> str:
    """根据股票代码判断交易所: sh/sz/bj"""
    code = str(code).zfill(6)
    prefix = code[0]
    if prefix in ("6",) or code.startswith("68"):
        return "sh"
    if prefix in ("0", "3"):
        return "sz"
    if prefix in ("8", "4"):
        return "bj"
    return "sz"


class StockFetcher:
    """单个股票数据采集器.

    用法:
        fetcher = StockFetcher("002460")
        data = fetcher.fetch_all()
    """

    def __init__(self, code: str, name: str | None = None):
        self.code = str(code).zfill(6)
        self.market = detect_market(self.code)
        self.name = name
        self._data: dict[str, Any] = {}

    def _warn(self, section: str, exc: Exception) -> None:
        print(f"  [警告] {section} 获取失败: {type(exc).__name__}: {exc}")

    def fetch_realtime(self) -> dict | None:
        """实时行情快照 (依赖东方财富A股总榜, 失败自动重试 3 次)"""
        try:
            df = _with_retry(ak.stock_zh_a_spot_em)
            row = df[df["代码"] == self.code]
            if row.empty:
                return None
            r = row.iloc[0].to_dict()
            if not self.name:
                self.name = r.get("名称")
            return r
        except Exception as e:
            self._warn("实时行情", e)
            return None

    def fetch_kline(self, days: int = 90, adjust: str = "qfq") -> pd.DataFrame | None:
        """日 K 线 (默认前复权, 取最近 days 根, 失败自动重试 3 次)"""
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=days * 2 + 30)).strftime("%Y%m%d")
            df = _with_retry(
                ak.stock_zh_a_hist, retries=3, delay=2.0,
                symbol=self.code, period="daily",
                start_date=start, end_date=end, adjust=adjust,
            )
            if df is None or df.empty:
                return self.fetch_kline_yfinance(days=days)
            return df.tail(days).reset_index(drop=True)
        except Exception as e:
            self._warn("K线", e)
            return self.fetch_kline_yfinance(days=days)

    def fetch_kline_yfinance(self, days: int = 90) -> pd.DataFrame | None:
        """备用 K 线源：Yahoo Finance。"""
        suffix = ".SZ" if self.market == "sz" else ".SS" if self.market == "sh" else ""
        if not suffix:
            return None
        ticker = f"{self.code}{suffix}"
        try:
            start = (datetime.now() - timedelta(days=days * 3 + 30)).strftime("%Y-%m-%d")
            end = datetime.now().strftime("%Y-%m-%d")
            df = yf.download(ticker, start=start, end=end, interval="1d", auto_adjust=False, progress=False)
            if df is None or df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            out = pd.DataFrame({
                "日期": pd.to_datetime(df.index).strftime("%Y-%m-%d"),
                "开盘": df["Open"].astype(float).round(2),
                "收盘": df["Close"].astype(float).round(2),
                "最高": df["High"].astype(float).round(2),
                "最低": df["Low"].astype(float).round(2),
                "成交量": df["Volume"].fillna(0).astype(float),
            }).reset_index(drop=True)
            out["成交额"] = (out["收盘"] * out["成交量"]).round(2)
            out["涨跌额"] = out["收盘"].diff().fillna(0).round(2)
            prev_close = out["收盘"].shift(1)
            out["涨跌幅"] = ((out["收盘"] / prev_close - 1) * 100).fillna(0).round(2)
            out["振幅"] = ((out["最高"] / out["最低"] - 1) * 100).replace([float("inf")], 0).fillna(0).round(2)
            out["换手率"] = 0.0
            print(f"  [回退] K线使用 Yahoo Finance: {ticker}")
            return out.tail(days).reset_index(drop=True)
        except Exception as e:
            self._warn("K线(Yahoo)", e)
            return None

    @staticmethod
    def load_kline_from_csv(path: str) -> pd.DataFrame | None:
        """离线模式: 从本地 CSV 读取 K 线 (列名需与 akshare stock_zh_a_hist 一致)"""
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
            required = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "涨跌幅"}
            if not required.issubset(set(df.columns)):
                print(f"  [警告] CSV 列名缺失, 需包含: {required}")
                return None
            return df.reset_index(drop=True)
        except Exception as e:
            print(f"  [错误] 离线 CSV 读取失败: {e}")
            return None

    def fetch_fund_flow(self, days: int = 60) -> pd.DataFrame | None:
        """个股资金流 (主力/超大单/大单/中单/小单 净额)"""
        try:
            df = ak.stock_individual_fund_flow(stock=self.code, market=self.market)
            return df.tail(days).reset_index(drop=True)
        except Exception as e:
            self._warn("资金流", e)
            return None

    def fetch_financial_abstract(self) -> pd.DataFrame | None:
        """主要财务指标 (新浪口径, 季度/年度累计)"""
        try:
            df = ak.stock_financial_abstract(symbol=self.code)
            return df
        except Exception as e:
            self._warn("财务指标", e)
            return None

    def fetch_research_reports(self) -> pd.DataFrame | None:
        """个股研报 (近期机构评级和盈利预测)"""
        try:
            df = ak.stock_research_report_em(symbol=self.code)
            return df.head(15)
        except Exception as e:
            self._warn("机构研报", e)
            return None

    def fetch_top_holders(self, date: str | None = None) -> pd.DataFrame | None:
        """十大流通股东 (最新一期年报/季报)"""
        try:
            if date is None:
                today = datetime.now()
                q_dates = [
                    f"{today.year}0331", f"{today.year - 1}1231",
                    f"{today.year - 1}0930", f"{today.year - 1}0630",
                ]
            else:
                q_dates = [date]
            for d in q_dates:
                try:
                    df = ak.stock_gdfx_free_top_10_em(
                        symbol=f"{self.market}{self.code}", date=d)
                    if df is not None and not df.empty:
                        return df
                except Exception:
                    continue
            return None
        except Exception as e:
            self._warn("十大股东", e)
            return None

    def fetch_dragon_tiger(self, days: int = 90) -> pd.DataFrame | None:
        """龙虎榜 (最近 days 天是否上榜)"""
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
            if df is None or "代码" not in df.columns:
                return None
            row = df[df["代码"] == self.code]
            return row if not row.empty else None
        except Exception as e:
            self._warn("龙虎榜", e)
            return None

    def fetch_all(self, kline_days: int = 90, fund_days: int = 60) -> dict[str, Any]:
        """一次性拉取全部数据, 失败项返回 None"""
        print(f"=== 数据采集 {self.code} {self.name or ''} ===")
        result: dict[str, Any] = {
            "code": self.code, "market": self.market,
            "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        print("  -> 实时行情 ...")
        result["realtime"] = self.fetch_realtime()
        result["name"] = self.name
        print("  -> K线(前复权) ...")
        result["kline"] = self.fetch_kline(days=kline_days, adjust="qfq")
        print("  -> 资金流 ...")
        result["fund_flow"] = self.fetch_fund_flow(days=fund_days)
        print("  -> 财务指标 ...")
        result["financial"] = self.fetch_financial_abstract()
        print("  -> 机构研报 ...")
        result["reports"] = self.fetch_research_reports()
        print("  -> 十大流通股东 ...")
        result["top_holders"] = self.fetch_top_holders()
        print("  -> 龙虎榜 ...")
        result["lhb"] = self.fetch_dragon_tiger()
        print("=== 采集完成 ===\n")
        self._data = result
        return result
