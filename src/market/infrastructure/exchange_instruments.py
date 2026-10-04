"""交易所证券名录直连，不依赖聚合数据 SDK。

只有完整拉取的交易所才进入 complete_markets，部分失败不能把存量证券误停用。
名录是低频主数据；与盘中行情读取、行业专题取数隔离。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import logging
import re
import time
from typing import Any

import pandas as pd

from src.market.infrastructure.http_client import market_get, market_session

logger = logging.getLogger(__name__)
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"}
_MAX_PAGES = 100


class InstrumentListError(RuntimeError):
    """名录不可用或分页/字段不满足完整性契约。"""


def _date(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "nat", "none", "null", "-"}:
        return ""
    parsed = pd.to_datetime(text, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def _code(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise InstrumentListError("证券名录缺少代码")
    text = re.sub(r"\.0$", "", raw).zfill(6)
    if not re.fullmatch(r"\d{6}", text):
        raise InstrumentListError("证券名录含非法代码")
    return text


def _rows(frame: pd.DataFrame, market: str) -> pd.DataFrame:
    if frame.empty or not {"code", "name", "list_date"}.issubset(frame.columns):
        raise InstrumentListError(f"{market} 名录为空或缺少代码、名称、上市日期列")
    out = frame.copy()
    out["code"] = out["code"].map(_code)
    out["name"] = out["name"].fillna("").astype(str).str.strip()
    if (out["name"] == "").any():
        raise InstrumentListError(f"{market} 名录含空证券名称")
    out["list_date"] = out["list_date"].map(_date)
    for key in ("industry", "board"):
        if key not in out:
            out[key] = ""
        out[key] = out[key].fillna("").astype(str).str.strip()
    out["industry"] = out["industry"].str.replace(r"^[A-Za-z]\s+", "", regex=True)
    out["market"] = market
    return out[["code", "name", "market", "board", "list_date", "industry"]].drop_duplicates("code")


def fetch_shanghai() -> pd.DataFrame:
    """上交所主板 A 股及科创板；任一板块分页不完整则整所不标记完成。"""
    url = "https://query.sse.com.cn/sseQuery/commonQuery.do"
    headers = {**_HEADERS, "Referer": "https://www.sse.com.cn/assortment/stock/list/share/"}
    result: list[dict[str, Any]] = []
    started = time.monotonic()
    for stock_type, board in (("1", "主板"), ("8", "科创板")):
        collected: list[dict[str, Any]] = []
        total: int | None = None
        for page in range(1, _MAX_PAGES + 1):
            if time.monotonic() - started > 45:
                raise InstrumentListError("上交所名录超过总耗时预算")
            response = market_get(url, headers=headers, timeout=12, retries=0, params={
                "STOCK_TYPE": stock_type, "REG_PROVINCE": "", "CSRC_CODE": "", "STOCK_CODE": "",
                "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L", "COMPANY_STATUS": "2,4,5,7,8",
                "type": "inParams", "isPagination": "true", "pageHelp.cacheSize": "1",
                "pageHelp.beginPage": str(page), "pageHelp.pageSize": "10000",
                "pageHelp.pageNo": str(page), "pageHelp.endPage": str(page),
            })
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("result")
            if not isinstance(batch, list) or not batch:
                raise InstrumentListError(f"上交所 {board} 第 {page} 页无有效名录")
            page_help = payload.get("pageHelp") or {}
            reported = page_help.get("total")
            if reported not in (None, ""):
                total = int(reported)
            collected.extend(batch)
            if total is not None and len(collected) >= total:
                break
            if total is None and len(batch) < 10000:
                break
        else:
            raise InstrumentListError(f"上交所 {board} 超出分页上限")
        codes = {str(row.get("A_STOCK_CODE") or "") for row in collected}
        if total is not None and len(codes) < total:
            raise InstrumentListError(f"上交所 {board} 分页重复或返回不足")
        for row in collected:
            result.append({"code": row.get("A_STOCK_CODE"), "name": row.get("SEC_NAME_CN"),
                           "list_date": row.get("LIST_DATE"), "board": board,
                           "industry": row.get("CSRC_CODE_NAME") or ""})
    return _rows(pd.DataFrame(result), "SH")


def fetch_shenzhen() -> pd.DataFrame:
    """深交所 A 股名录下载：读取原始字段，不通过行情聚合 SDK。"""
    response = market_get("https://www.szse.cn/api/report/ShowReport", timeout=15, retries=0,
                          headers={**_HEADERS, "Referer": "https://www.szse.cn/market/product/stock/list/index.html"},
                          params={"SHOWTYPE": "xlsx", "CATALOGID": "1110", "TABKEY": "tab1"})
    response.raise_for_status()
    if len(response.content) > 16 * 1024 * 1024:
        raise InstrumentListError("深交所名录超过大小上限")
    raw = pd.read_excel(BytesIO(response.content), dtype=str, engine="openpyxl")
    return _rows(raw.rename(columns={"A股代码": "code", "A股简称": "name", "A股上市日期": "list_date",
                                     "板块": "board", "所属行业": "industry"}), "SZ")


def _beijing_page(text: str) -> dict[str, Any]:
    """交易所 JSONP 只解析 JSON 数组，绝不执行响应中的脚本。"""
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise InstrumentListError("北交所响应无名录数组")
    payload = json.loads(text[start:end + 1])
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise InstrumentListError("北交所名录响应格式变化")
    return payload[0]


def fetch_beijing() -> pd.DataFrame:
    """北交所固定查询接口；有界分页、完整才返回，失败不影响沪深结果。"""
    url = "https://www.bse.cn/nqxxController/nqxxCnzq.do"
    result: list[dict[str, Any]] = []
    started = time.monotonic()
    expected: int | None = None
    with market_session() as session:
        pages = 1
        page = 0
        while page < pages:
            if time.monotonic() - started > 45:
                raise InstrumentListError("北交所名录超过总耗时预算")
            response = session.post(url, data={"page": str(page), "typejb": "T", "xxfcbj[]": "2",
                                              "xxzqdm": "", "sortfield": "xxzqdm", "sorttype": "asc"},
                                    headers={**_HEADERS, "Referer": "https://www.bse.cn/nq/listedcompany.html"},
                                    timeout=(4, 10))
            response.raise_for_status()
            payload = _beijing_page(response.text)
            pages = int(payload.get("totalPages") or 0)
            if not 1 <= pages <= _MAX_PAGES:
                raise InstrumentListError("北交所分页数无效")
            if payload.get("totalElements") is not None:
                expected = int(payload["totalElements"])
            batch = payload.get("content")
            if not isinstance(batch, list) or not batch:
                raise InstrumentListError("北交所存在空分页")
            for row in batch:
                if not isinstance(row, dict):
                    raise InstrumentListError("北交所证券条目格式变化")
                # 只认具名字段，不能依赖字典列的偶然位置去猜证券代码或日期。
                result.append({"code": row.get("xxzqdm"), "name": row.get("xxzqjc"),
                               "list_date": row.get("ssrq") or row.get("xxgprq"),
                               "industry": row.get("sshy") or row.get("xxhyname") or "", "board": "北交所"})
            page += 1
    frame = _rows(pd.DataFrame(result), "BJ")
    if expected is not None and len(frame) != expected:
        raise InstrumentListError("北交所分页重复或返回不足")
    return frame


def fetch_exchange_instruments() -> pd.DataFrame:
    """独立拉取三个交易所；完整市场集合随表返回，调用方不得猜测。"""
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    complete: list[str] = []
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="exchange-list") as pool:
        futures = [(market, pool.submit(loader)) for market, loader in
                   (("sh", fetch_shanghai), ("sz", fetch_shenzhen), ("bj", fetch_beijing))]
        for market, future in futures:
            try:
                frame = future.result()
                if frame.empty:
                    raise InstrumentListError("空名录")
                frames.append(frame)
                complete.append(market)
            except Exception as exc:
                errors.append(f"{market}: {type(exc).__name__}: {str(exc)[:160]}")
    if not frames:
        raise InstrumentListError("交易所名录均不可用：" + " | ".join(errors))
    if errors:
        logger.warning("部分交易所名录未更新：%s", " | ".join(errors))
    result = pd.concat(frames, ignore_index=True).drop_duplicates("code").reset_index(drop=True)
    result.attrs["complete_markets"] = tuple(sorted(complete))
    result.attrs["errors"] = errors
    return result
