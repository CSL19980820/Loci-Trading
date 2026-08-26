"""纸面量化：风格记忆、记忆图、五日回看与次日预案落地。

从 `test_paper_quant.py` 拆出（原 955 行）。
"""
from __future__ import annotations

from pathlib import Path

from src.ops.application.nextday_plan import (
    enrich_plan_items,
    evaluate_auction_stance,
    resolve_entry_mode,
)
from src.ops.application.paper_exec import PaperOrder
from src.ops.infrastructure.store import OpsStore


def test_style_memory_extract_and_absorb(tmp_path: Path) -> None:
    from src.ops.application.paper_style_memory import (
        absorb_lessons_into_style,
        ensure_style,
        extract_lessons_from_day,
        run_eod_learning,
        style_prompt_block,
    )

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        style = ensure_style(store, "demo")
        assert "该怎么买" in style["style_md"]
        assert "follow / revise" not in style["style_md"]
        assert "跟随 / 改计划 / 放弃 / 观望" in style["style_md"]
        block = style_prompt_block(style)
        assert "交易风格记忆" in block
        assert "judge_only" not in block
        assert "amount=None" not in block
        assert "{'" not in block and '{"' not in block
        assert "买法摘要：" in block
        assert "竞价=仅纠偏至09:25" in block or "竞价=" in block

        lessons = extract_lessons_from_day(
            slug="demo",
            trade_date="2026-08-07",
            fills=[],
            rejects=[
                {
                    "code": "600519",
                    "action": "open",
                    "reason": "情景门闩拦截：gap_up 情景预案不买",
                }
            ],
            monitor_runs=[
                {
                    "started_at": "2026-08-07T09:20:00+08:00",
                    "snapshot": {
                        "auction_stances": [
                            {"stance": "revise", "code": "600519"},
                            {"stance": "revise", "code": "600519"},
                        ]
                    },
                }
            ],
            style=style,
        )
        assert any(x["kind"] == "mistake" for x in lessons)
        assert any(x["kind"] == "revise" for x in lessons)
        assert all("abandon" not in str(x.get("content") or "") for x in lessons)
        assert all("revise" not in str(x.get("title") or "") for x in lessons)
        for les in lessons:
            store.add_paper_lesson(les)
        absorbed = absorb_lessons_into_style(store, "demo")
        assert absorbed["absorbed"] >= 1
        assert "情景门闩" in absorbed["style"]["style_md"] or "门闩" in absorbed["style"]["style_md"]

        learning_light = run_eod_learning(
            store,
            slug="demo",
            trade_date="2026-08-07",
            positions=[],
            fills_today=[],
            rejects_today=[],
            model="",
            persist_memory=False,
        )
        assert learning_light["critique"] == ""
        assert learning_light["absorbed"] == 0

        learning = run_eod_learning(
            store,
            slug="demo",
            trade_date="2026-08-07",
            positions=[],
            fills_today=[],
            rejects_today=[],
            model="",
            persist_memory=True,
        )
        assert "评头论足" in learning["critique"]
        assert "[mistake]" not in learning["critique"]
        assert "[revise]" not in learning["critique"]
        assert "follow / revise" not in learning["critique"]


def test_paper_memory_graph_explore(tmp_path: Path) -> None:
    from src.ops.application.paper_memory_graph import (
        explore_memory,
        ingest_lesson_to_graph,
        rebuild_graph_from_cabin,
        seed_default_graph,
    )

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        seed_default_graph(store, "demo")
        store.add_paper_lesson(
            {
                "slug": "demo",
                "trade_date": "2026-08-07",
                "kind": "mistake",
                "title": "600519 高开仍开仓",
                "content": "下次高开放弃",
            }
        )
        lessons = store.list_paper_lessons("demo", limit=5)
        ingest_lesson_to_graph(store, lessons[0])
        hit = explore_memory(store, "demo", "高开", max_nodes=20, hops=1)
        assert hit["stats"]["nodes"] >= 1
        assert any(n["kind"] == "lesson" for n in hit["nodes"]) or "高开" in hit["summary"]
        assert "has_rule" not in hit["summary"]
        assert "nodes=" not in hit["summary"]
        assert "query=" not in hit["summary"]
        assert any(e["rel"] == "has_rule" for e in hit["edges"])
        assert "含规则" in hit["summary"] or "规则" in hit["summary"]
        rebuilt = rebuild_graph_from_cabin(store, "demo")
        assert rebuilt["stats"]["nodes"] >= 5
        assert "has_rule" not in rebuilt["summary"]


def test_eod_five_day_lookback_miss_and_environment(tmp_path: Path) -> None:
    import pandas as pd

    from src.ops.application.paper_eod_review import (
        build_eod_lookback_pack,
        extract_miss_lessons_from_pack,
        format_lookback_for_prompt,
        resolve_lookback_days,
    )

    class FakeMarket:
        def trading_days(self, start=None, end=None):
            days = ["2026-08-01", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08"]
            if end:
                days = [d for d in days if d <= end]
            if start:
                days = [d for d in days if d >= start]
            return days

        def history(self, code, *, start=None, end=None, adjust="qfq"):
            rows = []
            for i, d in enumerate(self.trading_days(start=start, end=end)):
                close = 10 + i + (5 if code == "600519" else 0)
                rows.append(
                    {
                        "trade_date": d,
                        "open": close - 0.2,
                        "high": close + 0.3,
                        "low": close - 0.4,
                        "close": close,
                        "volume": 1000 + i,
                        "amount": 10000 + i * 10,
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
        store.ensure_paper_cabin("demo")
        # 今日才进预案 → new_pick，不算错过
        store.upsert_nextday_plan(
            {
                "slug": "demo",
                "plan_date": "2026-08-08",
                "body_text": "x",
                "items": [{"code": "600519", "name": "茅台", "planned_layers": 1}],
                "source": "test",
            }
        )
        market = FakeMarket()
        days = resolve_lookback_days(market, "2026-08-08", n=5)
        assert len(days) == 5
        assert days[-1] == "2026-08-08"
        pack = build_eod_lookback_pack(
            store, market, slug="demo", trade_date="2026-08-08", lookback=5
        )
        assert pack["universe_size"] >= 1
        assert any(m["code"] == "600519" for m in pack["new_picks"])
        assert not any(m["code"] == "600519" for m in pack["missed"])
        text = format_lookback_for_prompt(pack)
        assert "五交易日回看" in text
        assert "今日新入池" in text
        assert "开=" in text and "收=" in text
        assert "amount=None" not in text
        assert "vol=None" not in text
        assert "均涨跌=None" not in text
        assert "['" not in text  # 窗口不 dump Python list
        assert "O=" not in text and "C=" not in text
        empty_env = format_lookback_for_prompt(
            {
                **pack,
                "environment": {
                    "note": "环境统计仅覆盖本战法回看池",
                    "by_day": [
                        {
                            "trade_date": "2026-08-08",
                            "universe_amount": None,
                            "universe_volume": None,
                            "avg_pct": None,
                            "up": 0,
                            "down": 0,
                            "flat": 0,
                            "sample": 0,
                        }
                    ],
                    "boards": [],
                },
            }
        )
        assert "amount=None" not in empty_env
        # 空样本日不占行，避免推送刷「暂无×N」
        assert "2026-08-08 成交额" not in empty_env
        lessons = extract_miss_lessons_from_pack(
            slug="demo", trade_date="2026-08-08", pack=pack
        )
        assert not any(x["kind"] == "miss" for x in lessons)

        # 更早入池且未买 → 才算错过；收益自入池日起算
        store.upsert_nextday_plan(
            {
                "slug": "demo",
                "plan_date": "2026-08-05",
                "body_text": "early",
                "items": [{"code": "600519", "name": "茅台", "planned_layers": 1}],
                "source": "test",
            }
        )
        pack2 = build_eod_lookback_pack(
            store, market, slug="demo", trade_date="2026-08-08", lookback=5
        )
        assert any(m["code"] == "600519" for m in pack2["missed"])
        miss_row = next(r for r in pack2["names"] if r["code"] == "600519")
        assert miss_row["first_attention"] == "2026-08-05"
        assert miss_row["since_attention_return_pct"] is not None
        lessons2 = extract_miss_lessons_from_pack(
            slug="demo", trade_date="2026-08-08", pack=pack2
        )
        assert any(x["kind"] == "miss" for x in lessons2)
        miss_les = next(x for x in lessons2 if x["kind"] == "miss")
        assert miss_les["evidence"]["first_attention"] == "2026-08-05"
        assert "since_attention_return_pct" in miss_les["evidence"]


def test_nextday_picks_carry_unfilled_plan_items(tmp_path: Path) -> None:
    from src.ops.application.jobs.paper_quant_eod import _nextday_picks_after_eod

    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        store.ensure_paper_cabin("demo")
        store.upsert_nextday_plan(
            {
                "slug": "demo",
                "plan_date": "2026-08-06",
                "body_text": "today",
                "items": [{"code": "603713", "name": "密尔克卫", "planned_layers": 1.0, "ref_close": 67.3}],
                "source": "test",
            }
        )
        picks, _changes = _nextday_picks_after_eod(
            store, slug="demo", trade_date="2026-08-06", positions=[]
        )
        assert len(picks) == 1
        assert picks[0]["code"] == "603713"
        assert "尚未成交" in str(picks[0].get("thesis") or "") or "续滚" in str(
            picks[0].get("thesis") or ""
        )


def test_next_open_entry_mode_buys_gap_up() -> None:
    assert resolve_entry_mode("qianlong-close-v3") == "next_open"
    items = enrich_plan_items(
        [{"code": "600976", "name": "健民集团", "layers": 1.0, "ref_close": 29.99}],
        entry_mode="next_open",
    )
    assert items[0]["entry_mode"] == "next_open"
    assert items[0]["scenarios"]["gap_up"]["buy"] is True
    assert items[0]["scenarios"]["flat"]["buy"] is True
    assert items[0]["scenarios"]["gap_down"]["buy"] is True
    assert items[0]["auction"]["follow_requires_band"] is False
    # 普通高开应 follow；近涨停仍 abandon
    follow = evaluate_auction_stance(items[0], {"price": 31.0, "prev_close": 29.99})
    assert follow["stance"] == "follow"
    limitish = evaluate_auction_stance(items[0], {"price": 32.99, "prev_close": 29.99})
    assert limitish["stance"] == "abandon"


def test_dragon_gate_blocks_new_paper_orders_but_keeps_exits() -> None:
    from src.ops.application.jobs.paper_quant_support import _apply_market_gate

    orders, rejects = _apply_market_gate(
        [
            PaperOrder(code="600001", action="open", layers=0.5, mark_price=10),
            PaperOrder(code="600002", action="close", layers=0, mark_price=10),
        ],
        {
            "state": "empty",
            "mode": "空",
            "entry_allowed": False,
            "reason": "退潮",
        },
    )
    assert [order.action for order in orders] == ["close"]
    assert rejects[0]["code"] == "600001"
