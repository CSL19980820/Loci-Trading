"""纸面量化：日终复盘叙事、买入收益口径与 AI 单闸门合并。

从 `test_paper_quant.py` 拆出（原 955 行）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.ops.application.nextday_plan import (
    enrich_plan_items,
    merge_ai_orders_with_gates,
    session_clock,
)
from src.ops.application.paper_exec import PaperOrder
from src.ops.infrastructure.store import OpsStore


def test_eod_summary_tells_the_day_in_chronological_order(tmp_path: Path, monkeypatch) -> None:
    """成交流水按时间正序讲。倒序会让「开仓→止盈→开仓」被读反，成本对不上最后一笔。"""
    from src.ops.application.jobs import paper_quant_eod as eod_mod
    from src.ops.application.jobs import paper_quant_plan as plan_mod
    from src.ops.application.jobs import paper_quant_support as pq_support

    pushed: list[dict[str, str]] = []

    def _fake_dispatch(store, *, title, body, **_k):
        pushed.append({"title": title, "body": body})
        return {"sent": ["wecom"]}

    monkeypatch.setattr(eod_mod, "dispatch_text", _fake_dispatch)
    monkeypatch.setattr(plan_mod, "dispatch_text", _fake_dispatch)
    monkeypatch.setattr(pq_support, "_today", lambda: "2026-08-12")
    monkeypatch.setattr(pq_support, "_next_trade_date", lambda *_a, **_k: "2026-08-13")
    monkeypatch.setattr(
        pq_support,
        "resolve_trading_day_gate",
        lambda *a, **k: {
            "trade_date": "2026-08-12",
            "is_trading_day": True,
            "last_trading_day": "2026-08-12",
            "calendar_source": "test",
            "buy_execution_allowed": True,
            "note": "test",
        },
    )
    monkeypatch.setattr(
        "src.ops.application.paper_style_memory.run_eod_learning",
        lambda *a, **k: {
            "critique": "",
            "lookback_digest": "",
            "lessons": [],
            "absorbed": 0,
            "style": {},
            "lookback": None,
            "persist_memory": False,
        },
    )
    monkeypatch.setattr(eod_mod, "_nextday_picks_after_eod", lambda *a, **k: ([], {}))

    with OpsStore(tmp_path / "ops.db") as store:
        cabin = store.ensure_paper_cabin("dragon-return", config={"follow_wecom": True})
        for created_at, action, price, layers, cost in (
            ("2026-08-12T10:05:00+08:00", "open", 46.77, 1.0, 46.77),
            ("2026-08-12T13:20:00+08:00", "take_profit", 46.79, 0.0, 0.0),
            ("2026-08-12T14:40:00+08:00", "open", 46.7, 1.0, 46.7),
        ):
            store.apply_paper_fill(
                {
                    "cabin_id": cabin["id"],
                    "code": "603171",
                    "action": action,
                    "layers": 1.0,
                    "mark_price": price,
                    "created_at": created_at,
                },
                code="603171",
                name="税友股份",
                layers=layers,
                mark_cost=cost,
            )
        from src.ops.application.jobs.context import JobContext

        eod_mod.execute_paper_eod(
            {"slug": "dragon-return", "push": True}, JobContext(ops_store=store)
        )

    body = pushed[0]["body"]
    fill_lines = [line for line in body.splitlines() if line.startswith("· ")]
    assert fill_lines == [
        "· 10:05 开仓 603171 1.0 @ 46.77",
        "· 13:20 止盈 603171 1.0 @ 46.79",
        "· 14:40 开仓 603171 1.0 @ 46.7",
    ]
    # 最后一笔开仓价就是持仓成本，读起来不能自相矛盾
    assert "成本 46.7" in body


def test_bought_return_is_measured_from_the_entry_not_the_window(tmp_path: Path) -> None:
    """标的整窗跌 ≠ 你这笔亏。买入前的下跌不能算成「买入后走弱」。"""
    import pandas as pd

    from src.ops.application.paper_copy_zh import format_lookback_digest
    from src.ops.application.paper_eod_review import (
        build_eod_lookback_pack,
        extract_miss_lessons_from_pack,
    )

    closes = {
        "2026-08-06": 50.0,
        "2026-08-07": 48.0,
        "2026-08-10": 47.0,
        "2026-08-11": 46.5,
        "2026-08-12": 46.83,
    }

    class FakeMarket:
        def trading_days(self, start=None, end=None):
            days = sorted(closes)
            if end:
                days = [d for d in days if d <= end]
            if start:
                days = [d for d in days if d >= start]
            return days

        def history(self, code, *, start=None, end=None, adjust="qfq"):
            del code, adjust
            return pd.DataFrame(
                [
                    {
                        "trade_date": day,
                        "open": closes[day],
                        "high": closes[day],
                        "low": closes[day],
                        "close": closes[day],
                        "volume": 1000,
                        "amount": 10000,
                        "turnover": 0.01,
                    }
                    for day in self.trading_days(start=start, end=end)
                ]
            )

        @property
        def conn(self):
            class C:
                def execute(self, *_a, **_k):
                    class R:
                        def fetchone(self_inner):
                            return None

                    return R()

            return C()

    with OpsStore(tmp_path / "ops.db") as store:
        cabin = store.ensure_paper_cabin("demo")
        for created_at, action, price, layers, cost in (
            ("2026-08-12T10:05:00+08:00", "open", 46.77, 1.0, 46.77),
            ("2026-08-12T13:20:00+08:00", "take_profit", 46.79, 0.0, 0.0),
            ("2026-08-12T14:40:00+08:00", "open", 46.7, 1.0, 46.7),
        ):
            store.apply_paper_fill(
                {
                    "cabin_id": cabin["id"],
                    "code": "603171",
                    "action": action,
                    "layers": 1.0,
                    "mark_price": price,
                    "created_at": created_at,
                },
                code="603171",
                name="税友股份",
                layers=layers,
                mark_cost=cost,
            )
        pack = build_eod_lookback_pack(
            store, FakeMarket(), slug="demo", trade_date="2026-08-12", lookback=5
        )

    row = next(r for r in pack["names"] if r["code"] == "603171")
    # 标的五日跌 6.34%，但两笔买入均价 46.735，一笔 46.79 止盈、一笔 46.83 盯市
    assert row["window_return_pct"] < -5.0
    assert row["trade_return_pct"] > 0
    lessons = extract_miss_lessons_from_pack(
        slug="demo", trade_date="2026-08-12", pack=pack
    )
    assert not any(x["title"].startswith("买入后走弱") for x in lessons)

    digest = format_lookback_digest(pack)
    assert "买过 税友股份 买入后" in digest
    assert "整窗" not in digest


def test_bought_return_still_flags_a_real_losing_trade(tmp_path: Path) -> None:
    import pandas as pd

    from src.ops.application.paper_eod_review import (
        build_eod_lookback_pack,
        extract_miss_lessons_from_pack,
    )

    closes = {"2026-08-11": 100.0, "2026-08-12": 88.0}

    class FakeMarket:
        def trading_days(self, start=None, end=None):
            days = sorted(closes)
            if end:
                days = [d for d in days if d <= end]
            if start:
                days = [d for d in days if d >= start]
            return days

        def history(self, code, *, start=None, end=None, adjust="qfq"):
            del code, adjust
            return pd.DataFrame(
                [
                    {
                        "trade_date": day,
                        "open": closes[day],
                        "high": closes[day],
                        "low": closes[day],
                        "close": closes[day],
                        "volume": 1000,
                        "amount": 10000,
                        "turnover": 0.01,
                    }
                    for day in self.trading_days(start=start, end=end)
                ]
            )

        @property
        def conn(self):
            class C:
                def execute(self, *_a, **_k):
                    class R:
                        def fetchone(self_inner):
                            return None

                    return R()

            return C()

    with OpsStore(tmp_path / "ops.db") as store:
        cabin = store.ensure_paper_cabin("demo")
        store.apply_paper_fill(
            {
                "cabin_id": cabin["id"],
                "code": "600001",
                "action": "open",
                "layers": 1.0,
                "mark_price": 100.0,
                "created_at": "2026-08-11T10:00:00+08:00",
            },
            code="600001",
            name="测试",
            layers=1.0,
            mark_cost=100.0,
        )
        pack = build_eod_lookback_pack(
            store, FakeMarket(), slug="demo", trade_date="2026-08-12", lookback=5
        )

    lessons = extract_miss_lessons_from_pack(
        slug="demo", trade_date="2026-08-12", pack=pack
    )
    mistake = next(x for x in lessons if x["title"].startswith("买入后走弱"))
    assert mistake["evidence"]["trade_return_pct"] == -12.0
    assert "自买入均价起 -12.0%" in mistake["content"]


def test_plan_scenario_hides_zero_layer_price_band() -> None:
    """不接的情景打「0.5%~0.5%·0层」是噪音，还会被读成「还能接一点」。"""
    from src.ops.application.plan_build import format_plan_body

    items = enrich_plan_items(
        [{"code": "603171", "name": "税友股份", "ref_close": 46.83, "planned_layers": 1.0}],
        entry_mode="scenario",
    )

    text = format_plan_body("dragon-return", "2026-08-13", items)

    assert "📈高开暂缓" in text
    assert "·0层" not in text
    assert "高开接" not in text
    # 真会接的情景照常给价格带与层数
    assert "➡️平开接-0.5%~0.5%·1层" in text


def test_lookback_digest_skips_empty_noise() -> None:
    from src.ops.application.paper_copy_zh import format_lookback_digest

    text = format_lookback_digest(
        {
            "universe_size": 0,
            "bought": [],
            "missed": [],
            "new_picks": [],
            "sold": [],
        }
    )
    assert "【五日回看】" in text
    assert "买过 0" in text
    assert "成交额" not in text


def test_session_clock_blocks_open_until_continuous_auction() -> None:
    """09:25–09:30 仍禁开仓，与扫描竞价窗 09:15–09:30 对齐。"""
    from zoneinfo import ZoneInfo

    from src.ops.application.nextday_plan import session_clock

    tz = ZoneInfo("Asia/Shanghai")
    pre_open = session_clock(datetime(2026, 8, 7, 9, 28, tzinfo=tz))
    assert pre_open.phase == "open"
    assert pre_open.allow_open_fill is False
    regular = session_clock(datetime(2026, 8, 7, 9, 31, tzinfo=tz))
    assert regular.phase == "regular"
    assert regular.allow_open_fill is True


def test_merge_ai_rejects_open_when_allow_open_fill_false() -> None:
    """09:28（phase=open）与 12:00 午休：merge_ai 统一拦截 open/add/buy_dip。"""
    tz = ZoneInfo("Asia/Shanghai")
    items = enrich_plan_items(
        [{"code": "600519", "name": "茅台", "close": 100, "planned_layers": 1.0}],
        entry_mode="scenario",
    )
    follow_quote = {"600519": {"price": 100.0, "prev_close": 100.0}}
    order = PaperOrder(code="600519", action="open", layers=1.0, reason="AI硬开")

    open_phase = session_clock(datetime(2026, 8, 7, 9, 28, tzinfo=tz))
    assert open_phase.phase == "open"
    assert open_phase.allow_open_fill is False
    kept, rejects = merge_ai_orders_with_gates(
        [order], plan_items=items, quotes=follow_quote, clock=open_phase
    )
    assert kept == []
    assert rejects and "非连续竞价" in rejects[0]["reason"]

    lunch = session_clock(datetime(2026, 8, 7, 12, 0, tzinfo=tz))
    assert lunch.phase == "closed"
    kept2, rejects2 = merge_ai_orders_with_gates(
        [order], plan_items=items, quotes=follow_quote, clock=lunch
    )
    assert kept2 == []
    assert rejects2 and "非连续竞价" in rejects2[0]["reason"]


def test_merge_ai_allows_auction_when_auction_allow_open() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    items = enrich_plan_items(
        [{"code": "600519", "name": "茅台", "close": 100, "planned_layers": 1.0}],
        entry_mode="scenario",
    )
    auction = session_clock(
        datetime(2026, 8, 7, 9, 20, tzinfo=tz),
        auction_allow_open=True,
    )
    assert auction.in_auction is True
    assert auction.allow_open_fill is True
    kept, rejects = merge_ai_orders_with_gates(
        [PaperOrder(code="600519", action="open", layers=1.0, reason="AI竞价开")],
        plan_items=items,
        quotes={"600519": {"price": 100.0, "prev_close": 100.0}},
        clock=auction,
    )
    assert rejects == []
    assert len(kept) == 1 and kept[0].action == "open"


def test_generate_nextday_plan_sticky_observe_across_plan_date(tmp_path: Path) -> None:
    """换日写次日预案时，已在上一交易日观察池的票不得误报为新增。"""
    from src.ops.application.jobs import paper_quant_plan as plan_mod

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("dragon-return", config={"follow_wecom": False})
        plan_mod.generate_nextday_plan(
            store,
            slug="dragon-return",
            picks=[
                {
                    "code": "600721",
                    "name": "百花医药",
                    "close": 10.0,
                    "score": 69,
                    "intent": "observe",
                    "role_label": "龙头",
                }
            ],
            plan_date="2026-08-10",
            source="test",
            notify=False,
        )
        plan2 = plan_mod.generate_nextday_plan(
            store,
            slug="dragon-return",
            picks=[
                {
                    "code": "600721",
                    "name": "百花医药",
                    "close": 10.5,
                    "score": 69,
                    "intent": "observe",
                    "role_label": "龙头",
                },
                {
                    "code": "600490",
                    "name": "鹏欣资源",
                    "close": 5.0,
                    "score": 50,
                    "intent": "observe",
                    "role_label": "中军",
                },
            ],
            plan_date="2026-08-11",
            source="test",
            notify=False,
        )
        report = plan2["observe_changes"]
        kept_codes = {str(r.get("code")) for r in report.get("kept") or []}
        added_codes = {str(r.get("code")) for r in report.get("added") or []}
        assert "600721" in kept_codes
        assert "600721" not in added_codes
        assert "600490" in added_codes
        body = plan2["plan_section"]
        assert "续盯" in body and "百花医药" in body
        assert "新进观察 鹏欣资源" in body
        assert "新进观察 百花医药" not in body
        assert "新增 百花医药" not in body


def test_generate_nextday_plan_filters_auction_abandoned(tmp_path: Path) -> None:
    from src.ops.application.jobs.paper_quant import generate_nextday_plan

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        plan = generate_nextday_plan(
            store,
            slug="demo",
            picks=[
                {"code": "600001", "name": "放弃龙", "close": 10, "auction_stance": "abandoned"},
                {"code": "600519", "name": "茅台", "close": 100, "reason": "仍有效"},
            ],
            source="test",
        )
        codes = [item["code"] for item in plan["items"]]
        assert "600001" not in codes
        assert "600519" in codes
        assert plan["config_snapshot"]["auction_excluded"] == ["600001"]
