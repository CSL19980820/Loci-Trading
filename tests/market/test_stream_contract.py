"""SSE \u5bf9\u5916\u5951\u7ea6\u56de\u5f52\uff1a\u884c\u91cc\u5fc5\u987b\u6709 ``code``\u3002

\u8e29\u8fc7\u7684\u5751\uff1a\u9002\u914d\u5668\u5185\u90e8\u628a\u6807\u7684\u6807\u8bc6\u53eb ``symbol``\uff0c\u800c\u5bf9\u5916\u5951\u7ea6\uff08\u524d\u7aef\u4e0e\u6587\u6863\uff09\u7528
``code``\u3002\u4e24\u8fb9\u5bf9\u4e0d\u4e0a\u65f6\u7684\u8868\u73b0\u662f**\u6d41\u662f\u901a\u7684\u3001\u5e27\u4e5f\u5728\u53d1\u3001\u5c4f\u4e0a\u5168\u662f\u7a7a\u884c**\uff1b
\u66f4\u9690\u853d\u7684\u662f\u4fe1\u53f7\u5f15\u64ce\u6309 ``code`` \u8fc7\u6ee4\u8f93\u5165\u884c\uff0c\u5b57\u6bb5\u540d\u4e0d\u5bf9\u5c31\u6c38\u8fdc\u8bc4\u4f30\u51fa\u7a7a\u5217\u8868\uff0c
\u65e2\u4e0d\u62a5\u9519\u4e5f\u4e0d\u544a\u8b66\u3002
"""
from __future__ import annotations

from typing import Any

from src.market.api.stream_router import _contract_row


def test_contract_row_backfills_code_from_symbol() -> None:
    row: dict[str, Any] = {"symbol": "sh000001", "name": "\u4e0a\u8bc1\u6307\u6570", "price": 3900.0}
    out = _contract_row(row)
    assert out["code"] == "sh000001"
    # symbol \u4e0d\u80fd\u88ab\u62ff\u6389\uff1a\u884c\u60c5\u57df\u5185\u90e8\u4e0a\u767e\u5904\u5728\u7528\u5b83\u3002
    assert out["symbol"] == "sh000001"
    assert out["name"] == "\u4e0a\u8bc1\u6307\u6570"


def test_contract_row_is_a_noop_when_code_already_present() -> None:
    row = {"code": "300358", "symbol": "sz300358"}
    assert _contract_row(row) is row


def test_contract_row_tolerates_rows_without_symbol() -> None:
    """\u9002\u914d\u5668\u8fd4\u56de\u7684\u5f62\u72b6\u4e0d\u53ef\u63a7\uff0c\u7f3a\u952e\u65f6\u4e0d\u80fd\u629b\u3002"""
    row = {"name": "\u672a\u77e5"}
    assert _contract_row(row) is row
