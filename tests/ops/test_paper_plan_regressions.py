"""纸面预案/交易日闸回归（原 r2/r3/r5 审计散文件合并）。"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.ops.api.paper_quant import _allow_bypass_gates
from src.ops.application.jobs.paper_quant_eod import _nextday_picks_after_eod
from src.ops.application.jobs.paper_quant_support import (
    _next_trade_date,
    _weekend_next,
    resolve_trading_day_gate,
)
from src.ops.application.nextday_plan import (
    enrich_plan_items,
    evaluate_auction_stance,
    merge_ai_orders_with_gates,
    session_clock,
)
from src.ops.application.paper_exec import PaperOrder


def test_ai_layers_clamped_to_scenario_decision() -> None:
    items = enrich_plan_items(
        [{"code": "600519", "name": "茅台", "close": 100, "planned_layers": 0.5}],
        entry_mode="scenario",
    )
    clock = session_clock(
        now=datetime(2026, 8, 7, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    kept, rejects = merge_ai_orders_with_gates(
        [PaperOrder(code="600519", action="open", layers=4.0, reason="AI加仓")],
        plan_items=items,
        quotes={"600519": {"price": 100.0, "prev_close": 100.0}},
        clock=clock,
    )
    assert rejects == []
    assert len(kept) == 1
    assert kept[0].layers == float(items[0]["scenarios"]["flat"]["layers"])
    assert "层数钳制" in kept[0].reason


def test_next_open_stretched_gap_reduces_layers() -> None:
    items = enrich_plan_items(
        [{"code": "600976", "name": "健民", "layers": 1.0, "ref_close": 30.0}],
        entry_mode="next_open",
    )
    # +5% 超舒适带 3% → follow 但减层
    decision = evaluate_auction_stance(
        items[0], {"price": 31.5, "prev_close": 30.0}
    )
    assert decision["stance"] == "follow"
    assert decision["layers"] == float(items[0]["scenarios"]["gap_up"]["layers_if_stretched"])


def test_deep_gap_down_abandons_aligned_with_scan() -> None:
    items = enrich_plan_items(
        [{"code": "600001", "name": "测", "layers": 1.0, "ref_close": 10.0}],
        entry_mode="next_open",
    )
    decision = evaluate_auction_stance(
        items[0], {"price": 9.4, "prev_close": 10.0}  # -6%
    )
    assert decision["stance"] == "abandon"
    assert "放弃线" in decision["reason"]


def test_auction_stance_keeps_opening_gap_after_market_opens() -> None:
    """十点后的现价变化不能改写已经发生的高开/平开/低开情景。"""
    item = {
        "code": "603228",
        "ref_close": 100.0,
        "scenarios": {"flat": {"buy": False}},
    }

    at_ten = evaluate_auction_stance(
        item,
        {"open": 100.2, "price": 99.66, "prev_close": 100.0},
    )
    ten_minutes_later = evaluate_auction_stance(
        item,
        {"open": 100.2, "price": 101.16, "prev_close": 100.0},
    )

    assert at_ten["scenario"] == "flat"
    assert ten_minutes_later["scenario"] == "flat"
    assert round(float(at_ten["gap_pct"]), 2) == 0.2
    assert round(float(ten_minutes_later["gap_pct"]), 2) == 0.2


class FakeCalendarMarket:
    def __init__(self, days: list[str]) -> None:
        self._days = days

    def trading_days(self, start: str | None = None, end: str | None = None) -> list[str]:
        out = list(self._days)
        if start:
            out = [d for d in out if d >= start]
        if end:
            out = [d for d in out if d <= end]
        return out

    def shift_trading_days(self, trade_date: str, offset: int) -> str | None:
        try:
            i = self._days.index(trade_date)
        except ValueError:
            return None
        j = i + offset
        if 0 <= j < len(self._days):
            return self._days[j]
        return None

    def close(self) -> None:
        return None


def test_next_trade_date_skips_national_holiday_via_calendar() -> None:
    # 2026-10-01 国庆：日历直跳到 10-09，而不是周末算法的 10-02
    cal = FakeCalendarMarket(
        ["2026-09-30", "2026-10-09", "2026-10-12"]
    )
    assert _next_trade_date("2026-09-30", market=cal) == "2026-10-09"


def test_next_trade_date_from_holiday_picks_next_listed_day() -> None:
    cal = FakeCalendarMarket(["2026-09-30", "2026-10-09"])
    assert _next_trade_date("2026-10-01", market=cal) == "2026-10-09"


def test_weekend_next_fallback() -> None:
    assert _weekend_next(date(2026, 8, 7)) == "2026-08-10"  # Fri → Mon


def test_allow_bypass_gates_blocked_in_production(monkeypatch) -> None:
    monkeypatch.setenv("PALACE_ENV", "production")
    monkeypatch.delenv("LOCI_PAPER_ALLOW_BYPASS_GATES", raising=False)
    assert _allow_bypass_gates() is False
    monkeypatch.setenv("LOCI_PAPER_ALLOW_BYPASS_GATES", "1")
    assert _allow_bypass_gates() is True


def test_allow_bypass_gates_open_locally(monkeypatch) -> None:
    monkeypatch.setenv("PALACE_ENV", "local")
    assert _allow_bypass_gates() is True

class _FakeMarket:
    def latest_bars(self, codes: list[str]) -> dict[str, dict[str, float | str]]:
        return {
            "600001": {"code": "600001", "trade_date": "2026-08-07", "close": 12.5},
        }


def test_eod_roll_uses_bar_close_not_mark_cost() -> None:
    picks, _ = _nextday_picks_after_eod(
        store=type("S", (), {"get_nextday_plan": staticmethod(lambda *_a, **_k: {})})(),
        slug="demo",
        trade_date="2026-08-07",
        positions=[
            {
                "code": "600001",
                "name": "测",
                "layers": 1.0,
                "mark_cost": 99.0,
            }
        ],
        market=_FakeMarket(),
    )
    assert len(picks) == 1
    assert picks[0]["ref_close"] == 12.5
    assert picks[0]["ref_close"] != 99.0


def test_eod_roll_ref_close_none_without_market() -> None:
    picks, _ = _nextday_picks_after_eod(
        store=type("S", (), {"get_nextday_plan": staticmethod(lambda *_a, **_k: {})})(),
        slug="demo",
        trade_date="2026-08-07",
        positions=[{"code": "600001", "name": "测", "layers": 1.0, "mark_cost": 99.0}],
        market=None,
    )
    assert picks[0]["ref_close"] is None


def test_eod_roll_reads_planned_layers_max_and_refreshes_ref_close() -> None:
    """预案权威层数键是 planned_layers_max；未成交项昨收用日 K 覆盖种子脏价。"""

    class Store:
        @staticmethod
        def get_nextday_plan(*_a, **_k):
            return {
                "items": [
                    {
                        "code": "600001",
                        "name": "测",
                        "planned_layers_max": 2.5,
                        "ref_close": 1.0,  # 脏种子价
                    }
                ]
            }

    picks, _ = _nextday_picks_after_eod(
        store=Store(),
        slug="demo",
        trade_date="2026-08-07",
        positions=[],
        market=_FakeMarket(),
    )
    assert len(picks) == 1
    assert picks[0]["planned_layers"] == 2.5
    assert picks[0]["ref_close"] == 12.5


def test_downgrade_gap_forces_half_layer() -> None:
    items = enrich_plan_items(
        [
            {
                "code": "600001",
                "name": "测",
                "layers": 1.5,
                "ref_close": 10.0,
                "auction": {"abandon_gap_pct": -5.0, "downgrade_gap_pct": -2.0},
            }
        ],
        entry_mode="next_open",
    )
    # -3%：过降级线、未到放弃线 → follow 半层
    decision = evaluate_auction_stance(
        items[0], {"price": 9.7, "prev_close": 10.0}
    )
    assert decision["stance"] == "follow"
    assert decision["layers"] == 0.5
    assert "降级带" in decision["reason"]


def test_plan_item_carries_tuning_abandon_gap() -> None:
    items = enrich_plan_items(
        [
            {
                "code": "600001",
                "layers": 1.0,
                "ref_close": 10.0,
                "auction": {"abandon_gap_pct": -6.0, "downgrade_gap_pct": -3.0},
            }
        ],
        entry_mode="next_open",
    )
    assert items[0]["auction"]["abandon_gap_pct"] == -6.0
    assert items[0]["auction"]["downgrade_gap_pct"] == -3.0
    decision = evaluate_auction_stance(
        items[0], {"price": 9.45, "prev_close": 10.0}  # -5.5%
    )
    assert decision["stance"] == "follow"  # 放弃线 -6，尚未触发
    deep = evaluate_auction_stance(
        items[0], {"price": 9.3, "prev_close": 10.0}  # -7%
    )
    assert deep["stance"] == "abandon"


def test_trading_day_gate_weekend_is_non_trading() -> None:
    gate = resolve_trading_day_gate(
        "2026-08-08",
        market=FakeCalendarMarket(["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]),
    )
    assert gate["is_trading_day"] is False
    assert gate["buy_execution_allowed"] is False
    assert gate["calendar_source"] == "market_db"
    assert "非交易日" in str(gate["note"])


def test_trading_day_gate_holiday_in_calendar() -> None:
    gate = resolve_trading_day_gate(
        "2026-10-01",
        market=FakeCalendarMarket(["2026-09-30", "2026-10-08"]),
    )
    assert gate["is_trading_day"] is False
    assert gate["buy_execution_allowed"] is False


def test_trading_day_gate_weekday_with_calendar_allows_buy() -> None:
    gate = resolve_trading_day_gate(
        "2026-08-07",
        market=FakeCalendarMarket(["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]),
    )
    assert gate["is_trading_day"] is True
    assert gate["buy_execution_allowed"] is True
    assert gate["calendar_source"] == "market_db"


def test_trading_day_gate_missing_calendar_fail_closed_on_weekday() -> None:
    gate = resolve_trading_day_gate("2026-08-07", market=FakeCalendarMarket([]))
    assert gate["is_trading_day"] is True
    assert gate["buy_execution_allowed"] is False
    assert gate["calendar_source"] == "weekday_fallback"
    assert "fail-closed" in str(gate["note"])


def test_merge_ai_orders_blocks_buy_before_continuous_auction() -> None:
    items = enrich_plan_items(
        [{"code": "600519", "name": "茅台", "ref_close": 100.0, "planned_layers_max": 1.0}],
        entry_mode="next_open",
    )
    clock = session_clock(datetime(2026, 8, 7, 9, 28, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert clock.allow_open_fill is False
    kept, rejects = merge_ai_orders_with_gates(
        [PaperOrder(code="600519", action="open", layers=0.5, reason="AI")],
        plan_items=items,
        quotes={"600519": {"price": 100.0, "prev_close": 100.0}},
        clock=clock,
    )
    assert kept == []
    assert rejects and "非连续竞价" in str(rejects[0]["reason"])


def test_build_plan_item_prefers_planned_layers_max() -> None:
    items = enrich_plan_items(
        [
            {
                "code": "600519",
                "name": "茅台",
                "layers": 0.5,
                "planned_layers": 1.0,
                "planned_layers_max": 2.0,
                "ref_close": 100.0,
            }
        ]
    )
    assert items[0]["planned_layers_max"] == 2.0


