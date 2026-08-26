"""decided_by 分组观测：eod pack / 学习回执 / 教训 evidence。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ops.application.paper_decided_by import (
    count_fills_by_decided_by,
    normalize_decided_by,
)
from src.ops.application.paper_eod_review import build_eod_lookback_pack
from src.ops.application.paper_exec import PaperOrder, execute_orders
from src.ops.application.paper_style_memory import (
    extract_lessons_from_day,
    run_eod_learning,
)
from src.ops.infrastructure.store import OpsStore


def test_normalize_empty_decided_by_is_unknown() -> None:
    assert normalize_decided_by("") == "unknown"
    assert normalize_decided_by(None) == "unknown"
    assert normalize_decided_by("  ") == "unknown"
    assert normalize_decided_by("ai") == "ai"


def test_count_fills_by_decided_by_groups() -> None:
    fills = [
        {"decided_by": "ai"},
        {"decided_by": "rules"},
        {"decided_by": ""},
        {"decided_by": "ai"},
    ]
    assert count_fills_by_decided_by(fills) == {"ai": 2, "rules": 1, "unknown": 1}


def test_eod_pack_and_learning_receipt_group_by_decided_by(tmp_path: Path) -> None:
    # fill.created_at 用真实今天；lookback 末日必须覆盖今天，否则 pack 聚不到成交
    from datetime import date, timedelta

    today = date.today().isoformat()
    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]

    class FakeMarket:
        def trading_days(self, start=None, end=None):
            out = list(days)
            if end:
                out = [d for d in out if d <= end]
            if start:
                out = [d for d in out if d >= start]
            return out

        def history(self, code, *, start=None, end=None, adjust="qfq"):
            rows = []
            for i, d in enumerate(self.trading_days(start=start, end=end)):
                close = 100.0 - i
                rows.append(
                    {
                        "trade_date": d,
                        "open": close,
                        "high": close + 1,
                        "low": close - 1,
                        "close": close,
                        "volume": 1000,
                        "amount": 10000,
                        "turnover": 0.01,
                    }
                )
            return pd.DataFrame(rows)

        @property
        def conn(self):
            class C:
                def execute(self, *_a, **_k):
                    class R:
                        def fetchone(self_inner):
                            return None

                    return R()

            return C()

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        cabin = store.ensure_paper_cabin("demo", max_layers=2.0)
        result = execute_orders(
            store,
            slug="demo",
            orders=[
                PaperOrder(
                    code="600519",
                    action="open",
                    layers=0.5,
                    reason="ai open 高开追涨",
                    mark_price=100.0,
                    name="茅台",
                    decided_by="ai",
                ),
                PaperOrder(
                    code="600519",
                    action="take_profit",
                    layers=0.5,
                    reason="rules take",
                    mark_price=105.0,
                    decided_by="rules",
                ),
            ],
            quotes={"600519": {"price": 100.0, "name": "茅台"}},
            source="strategy_monitor",
        )
        assert len(result.fills) == 2
        fills = store.list_paper_fills(cabin["id"], limit=10)

        pack = build_eod_lookback_pack(
            store, FakeMarket(), slug="demo", trade_date=today, lookback=5
        )
        assert pack["fills_by_decided_by"] == {"ai": 1, "rules": 1}

        learning = run_eod_learning(
            store,
            slug="demo",
            trade_date=today,
            positions=[],
            fills_today=fills,
            rejects_today=[],
            model="",
            persist_memory=False,
        )
        assert learning["fills_by_decided_by"] == {"ai": 1, "rules": 1}

        lessons = extract_lessons_from_day(
            slug="demo",
            trade_date=today,
            fills=fills,
            rejects=[],
            monitor_runs=[],
            style={"buy_rules": {"gap_up_default": "no_chase"}},
        )
        fill_lessons = [x for x in lessons if isinstance((x.get("evidence") or {}).get("fill"), dict)]
        assert fill_lessons
        by_decided = {(x["evidence"]["decided_by"]) for x in fill_lessons}
        assert "ai" in by_decided or "rules" in by_decided
        for les in fill_lessons:
            assert "decided_by" in les["evidence"]
            assert les["evidence"]["decided_by"] in {"ai", "rules", "unknown"}
