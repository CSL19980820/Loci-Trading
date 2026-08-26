"""新浪个股资金流：``capital_flow`` lane 的回退源。

从 ``sina.py`` 拆出来是体量原因。只取原始报文转 DataFrame，**不做任何 rename
与乘除**——列映射与单位换算全部由 ``domain/source_contract.CAPITAL_FLOW_CONTRACT``
+ ``infrastructure/pipeline.normalize`` 负责。

注意新浪与东财对「主力」的定义不同（东财 = 超大单 + 大单，新浪用自有 r0–r3
分档），两家的 ``main_net_inflow`` 不可当同一条序列拼接；跨源分析必须看
routed 回的 adapter_id。
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
import requests

CAPITAL_FLOW_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "MoneyFlow.ssl_qsfx_zjlrqs?page=1&num={num}&sort=opendate&asc=0&daima={daima}"
)
#: 单次条数上限。接口按 page/num 分页，这里只取第一页；超过千日的资金流
#: 历史没有分析价值，也不值得为它加一层翻页。
CAPITAL_FLOW_MAX_NUM = 1000
#: 契约要用到的原始键，空表也按这个骨架返回，免得调用方对空表做列判断时崩。
CAPITAL_FLOW_FIELDS = (
    "opendate",
    "trade",
    "changeratio",
    "turnover",
    "netamount",
    "ratioamount",
    "r0_net",
    "r0_ratio",
)


def fetch_capital_flow(
    symbol_or_code: str, *, days: int = 60, session: requests.Session | None = None
) -> pd.DataFrame:
    """取个股资金流历史的**原始表**（不 rename、不做任何单位换算）。

    ``symbol_or_code`` 接受 ``600519`` / ``sh600519`` / ``600519.SH``，一律经
    ``to_sina_symbol`` 归成 ``daima`` 要的 ``sh``/``sz``/``bj`` 前缀写法。
    返回列即新浪原始键：``opendate`` / ``trade`` / ``changeratio`` /
    ``netamount`` / ``ratioamount`` / ``r0_net`` / ``r0_ratio`` 等；口径（小数
    还是百分数）由 ``CAPITAL_FLOW_CONTRACT`` 声明、``pipeline.normalize`` 执行。

    ``keep_unmapped=True`` 会让契约没认领的原始键原样留在归一结果里。注意新浪
    这张表的 ``turnover`` 是**成交额（亿元）**，与日 K lane 里表示换手率（小数）
    的同名列不是一回事；``r0x_ratio`` / ``cate_ra`` / ``cate_na`` 同样是新浪自有
    口径，仓内没有任何一列依赖它们。

    错误语义照 ``fetch_hfq_factors``：**请求失败 / 404 / 超时 / 报文变形一律抛
    ``SinaFetchError``**，只有新浪明确回了一个空数组才返回空表。吞成空表会让
    上游把「这条线路拿不到数据」误读成「这只票今天没有资金流」，回退链也就不
    会再往下试。
    """
    from src.market.infrastructure.sina import SinaFetchError, _get
    from src.market.infrastructure.store_codes import to_sina_symbol

    text = str(symbol_or_code).strip()
    if not text:
        raise SinaFetchError("资金流缺少证券代码")
    try:
        symbol = to_sina_symbol(text)
    except Exception as exc:
        raise SinaFetchError(f"资金流代码非法：{symbol_or_code!r}") from exc
    num = max(1, min(int(days), CAPITAL_FLOW_MAX_NUM))

    payload = _get(CAPITAL_FLOW_URL.format(num=num, daima=symbol), session)
    start, end = payload.find("["), payload.rfind("]")
    if start < 0 or end < 0:
        raise SinaFetchError(
            f"{symbol} 资金流报文无 JSON 数组段（{len(payload)} 字节）"
        )
    try:
        records = json.loads(payload[start : end + 1])
    except ValueError as exc:
        raise SinaFetchError(f"{symbol} 资金流 JSON 解析失败：{exc}") from exc

    if not isinstance(records, list):
        raise SinaFetchError(f"{symbol} 资金流不是数组：{type(records).__name__}")
    if not records:
        # 新浪明确回了空数组：票存在但这段窗口没有资金流数据。这才是合法空表。
        return pd.DataFrame(columns=list(CAPITAL_FLOW_FIELDS))
    if not all(isinstance(row, dict) for row in records):
        raise SinaFetchError(f"{symbol} 资金流数组元素不是对象")

    frame = pd.DataFrame(records)
    if "opendate" not in frame.columns:
        raise SinaFetchError(
            f"{symbol} 资金流缺 opendate 列：{list(frame.columns)[:6]}"
        )
    # 接口按 opendate 倒序返回；东财那一路是升序，调用方（MCP / 日终复盘）
    # 一律 ``frame.tail(n)`` 取最近几天。这里只翻行序，不动值也不动列名。
    return frame.sort_values("opendate", kind="stable").reset_index(drop=True)
