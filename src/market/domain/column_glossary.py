"""行情列名中英对照表（唯一真相）。

上游（akshare / 交易所）返回的多为中文列名，仓内归一列名为英文。两套名字
在适配器、探测结果、前端「出参」展示里都要用，因此对照表只在这里维护一份，
适配器按需从中挑子集，不再各自抄一遍。

纯标准库：领域层不依赖 pandas / fastapi / sqlite。
"""
from __future__ import annotations


#: 中文列名 → 仓内英文列名。键唯一，因此同一中文名只能有一个英文归一名；
#: 少数历史列名冲突（如资金流的 ``pct_chg``）由使用方在本表之外显式覆盖。
CN_TO_EN: dict[str, str] = {
    # 日线（含 types.py 的 DAILY_REQUIRED_COLUMNS / DAILY_OPTIONAL_COLUMNS）
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
    "流通股本": "outstanding_share",
    # 现价快照
    "代码": "code",
    "名称": "name",
    "今开": "open",
    "最新价": "close",
    "昨收": "prev_close",
    "涨跌幅": "pct",
    "涨跌额": "change",
    # 分钟线
    "时间": "datetime",
    "均价": "avg_price",
    # 个股资金流
    "收盘价": "close",
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

def _build_reverse(mapping: dict[str, str]) -> dict[str, str]:
    reverse: dict[str, str] = {}
    for chinese, english in mapping.items():
        reverse.setdefault(english, chinese)
    return reverse


#: 英文 → 中文的反查。多个中文名映射到同一英文名时（收盘/最新价/收盘价 → close），
#: 取 ``CN_TO_EN`` 中最先出现的那个，保证反查结果稳定。
EN_TO_CN: dict[str, str] = _build_reverse(CN_TO_EN)


def gloss_column(raw: str) -> dict[str, str]:
    """把一个列名标注成 ``{"raw", "cn", "en"}``，认不出就留空，不猜译。"""
    text = str(raw)
    mapped_en = CN_TO_EN.get(text)
    if mapped_en is not None:
        return {"raw": text, "cn": text, "en": mapped_en}
    mapped_cn = EN_TO_CN.get(text)
    if mapped_cn is not None:
        return {"raw": text, "cn": mapped_cn, "en": text}
    if _has_chinese(text):
        return {"raw": text, "cn": text, "en": ""}
    return {"raw": text, "cn": "", "en": text}


def select_columns(*chinese_names: str) -> dict[str, str]:
    """按中文列名从 ``CN_TO_EN`` 取子集，供适配器拼自己的 rename 表。"""
    missing = [name for name in chinese_names if name not in CN_TO_EN]
    if missing:
        raise KeyError(f"列名未登记在 CN_TO_EN：{missing}")
    return {name: CN_TO_EN[name] for name in chinese_names}


def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)
