"""证券代码归一与交易所前缀推断。"""
from __future__ import annotations


class MarketError(RuntimeError):
    """行情仓自身的可预期错误，调用方应转成 4xx 而不是 500。"""


def normalize_code(value: str) -> str:
    """统一成 6 位数字代码。接受 '600519' / 'sh600519' / '600519.SH'。"""
    text = str(value).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    text = text.split(".")[0]
    if not (len(text) == 6 and text.isdigit()):
        raise MarketError(f"非法证券代码：{value}")
    return text


#: 指数代码无法只靠前缀判断（000300 在上交所，而 000001 既是上证指数
#: 也是平安银行的代码）。把要用的基准指数显式列出来，避免猜错。
INDEX_MARKETS = {
    "000001": "sh",  # 上证指数
    "000300": "sh",  # 沪深300
    "000905": "sh",  # 中证500
    "000852": "sh",  # 中证1000
    "000016": "sh",  # 上证50
    "399001": "sz",  # 深证成指
    "399006": "sz",  # 创业板指
    "399005": "sz",  # 中小板指
}


def guess_market(code: str, *, instrument_type: str = "STOCK") -> str:
    """由代码前缀推断交易所，仅用于拼接数据源需要的带前缀符号。"""
    code = normalize_code(code)
    if instrument_type == "INDEX":
        if code in INDEX_MARKETS:
            return INDEX_MARKETS[code]
        return "sz" if code.startswith("39") else "sh"
    if code.startswith(("60", "68", "90")):  # 主板 / 科创板 / B股
        return "sh"
    if code.startswith(("4", "8", "92")):  # 北交所
        return "bj"
    return "sz"  # 00 主板 / 30 创业板 / 20 B股


def to_sina_symbol(code: str, *, instrument_type: str = "STOCK") -> str:
    """'600519' -> 'sh600519'。新浪与通达信都用这种带前缀的写法。"""
    code = normalize_code(code)
    return f"{guess_market(code, instrument_type=instrument_type)}{code}"
