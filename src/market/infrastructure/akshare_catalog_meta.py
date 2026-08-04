"""只看函数名与 docstring 就能得出的目录元数据。

与签名/试跑无关的推断都放这里，``akshare_catalog`` 专心做发现与受控执行。
"""
from __future__ import annotations

import re

from src.market.infrastructure.akshare_probe_result import JsonValue


#: 单个 :param/:return 描述的展示上限；上游偶有整段说明书塞在一个字段里。
MAX_DOC_SECTION_LENGTH = 160
_DOC_PARAM_PATTERN = re.compile(r"^:param\s+([^:]+):\s*(.*)$")
_DOC_RETURN_PATTERN = re.compile(r"^:returns?:\s*(.*)$")


def parse_doc_sections(doc: str) -> tuple[dict[str, JsonValue], str]:
    """从完整 docstring 抽 ``:param``/``:return``（akshare 用中文写）。

    240 字的 ``doc`` 摘要会把这两段截掉，而它们正是「入参含义」与「返回数据」
    的唯一来源。上游写法并不统一，解析失败一律降级成空值，不猜。
    """
    params: dict[str, list[str]] = {}
    returns: list[str] = []
    current: list[str] | None = None
    for line in doc.splitlines():
        stripped = line.strip()
        param_match = _DOC_PARAM_PATTERN.match(stripped)
        if param_match is not None:
            current = params.setdefault(param_match.group(1).strip(), [])
            current.append(param_match.group(2))
            continue
        return_match = _DOC_RETURN_PATTERN.match(stripped)
        if return_match is not None:
            current = returns
            current.append(return_match.group(1))
            continue
        if stripped.startswith(":"):
            # :type / :rtype 等其它字段不是描述正文，就此结束上一段。
            current = None
            continue
        if current is not None:
            current.append(stripped)
    param_docs: dict[str, JsonValue] = {
        name: _collapse_doc_section(parts) for name, parts in params.items()
    }
    return param_docs, _collapse_doc_section(returns)


def execution_mode(name: str) -> str:
    if "hist" in name or "minute" in name:
        return "batch_cache_only"
    if any(token in name for token in ("spot", "individual", "notice", "fund_flow", "hot_")):
        return "on_demand"
    # 当前 market 同步链未注册 AkShare 适配器；未知能力不能冒充同步可用。
    return "disabled"


def capability_status(parameters: list[dict[str, JsonValue]]) -> str:
    """目录试跑就绪度，不与同步/缓存编排状态混为一谈。"""
    if any(item["required"] is True for item in parameters):
        return "needs_parameters"
    return "available"


def infer_source(name: str, module: str) -> str:
    text = f"{name} {module}".lower()
    for token, source in (
        ("_em", "eastmoney"),
        ("_sina", "sina"),
        ("_tx", "tencent"),
        ("_ths", "tonghuashun"),
        ("_xq", "xueqiu"),
        ("_baidu", "baidu"),
    ):
        if token in text:
            return source
    return "akshare"


SOURCE_LABELS: dict[str, str] = {
    "eastmoney": "东方财富",
    "sina": "新浪",
    "tencent": "腾讯",
    "tonghuashun": "同花顺",
    "xueqiu": "雪球",
    "baidu": "百度",
    "akshare": "AkShare",
}

CATEGORY_LABELS: dict[str, str] = {
    "history": "历史行情",
    "minute_bars": "分钟线",
    "spot_quotes": "实时行情",
    "capital_flow": "资金流",
    "financials": "财务报表",
    "corporate_actions": "公司行为",
    "reference": "参考数据",
}


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source or "未知")


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category or "其他")


def infer_category(name: str) -> str:
    if "hist" in name:
        return "history"
    if "minute" in name:
        return "minute_bars"
    if "spot" in name:
        return "spot_quotes"
    if "fund_flow" in name:
        return "capital_flow"
    if any(token in name for token in ("financial", "profit", "balance", "cash_flow")):
        return "financials"
    if any(token in name for token in ("holder", "share", "dividend")):
        return "corporate_actions"
    return "reference"


def _collapse_doc_section(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())[:MAX_DOC_SECTION_LENGTH]
