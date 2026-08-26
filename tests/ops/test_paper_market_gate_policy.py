"""候选已用本战法自己的宽度确认时，不被龙空龙全局闸门重复否决。"""
from __future__ import annotations

from src.ops.application.jobs.paper_quant_support import _apply_market_gate
from src.ops.application.paper_exec import PaperOrder


def test_strategy_specific_entry_bypasses_global_gate_only_for_declared_code() -> None:
    orders, rejects = _apply_market_gate(
        [
            PaperOrder(code="600001", action="open", layers=0.5),
            PaperOrder(code="600002", action="open", layers=0.5),
            PaperOrder(code="600003", action="close", layers=0.5),
        ],
        {"entry_allowed": False, "reason": "退潮"},
        entry_exempt_codes={"600001"},
    )

    assert [(order.code, order.action) for order in orders] == [
        ("600001", "open"),
        ("600003", "close"),
    ]
    assert [(row["code"], row["action"]) for row in rejects] == [
        ("600002", "open")
    ]
