"""历史候选按新口径重算评分：只改分数/理由/证据，不动真选身份；未重现的行保持原样。"""
import json
from types import SimpleNamespace

from src.ledger import PalaceStore
from src.strategy.application.rescore import apply_rescore, plan_rescore
from src.strategy.application.score_percentile import SCORE_PERCENTILE

SLUG = "sanyuan-tail-v1"


def seed(palace):
    common = {"pool_id": f"{SLUG}@2026-09-23", "occurred_on": "2026-09-23", "strategy_slug": SLUG,
              "rule_version": SLUG, "source": "job:screen", "timing": "next_open"}
    palace.record_candidate(code="300931", name="通用电梯", decision="观察", score=2.5,
                            reason="三源尾盘共振（15:30）弱市低吸观察：A_MA25突破=1.00", tier="watch",
                            evidence={"横截面评分": 2.5, "_data_snapshot": {"end": "2026-09-23"}}, **common)
    palace.record_candidate(code="002937", name="兴瑞科技", decision="观察", score=1.4,
                            reason="三源尾盘共振（15:30）弱市低吸观察：A_MA25突破=1.00", tier="watch",
                            evidence={"横截面评分": 1.4}, **common)
    palace.record_candidate(code="600000", name="浦发银行", decision="精选", score=1.1,
                            reason="三源尾盘共振（15:30）选中：A_MA25突破=1.00",
                            **{**common, "pool_id": f"{SLUG}@2026-09-24", "occurred_on": "2026-09-24"})


def fake_screen(market, slug, *, trade_date, **kwargs):
    assert slug == SLUG and kwargs == {"health_check": False, "live_overlay": False}
    if trade_date == "2026-09-24":
        return SimpleNamespace(trade_date="2026-09-23", picks=[], watch_picks=[])
    factors = {SCORE_PERCENTILE: 96.4, "横截面评分": 2.5, "1日涨幅%": 6.1, "5日涨幅%": 9.8,
               "20日涨幅%": 15.0, "收盘位置CLV": 0.7, "A_MA25突破": 1.0}
    return SimpleNamespace(trade_date=trade_date, picks=[], watch_picks=[{"code": "300931", "factors": factors}])


def test_plan_then_apply_updates_only_rescored_rows(tmp_path):
    with PalaceStore(tmp_path / "palace.db") as palace:
        seed(palace)
        before = {row["code"]: row for row in palace.candidate_scoring_rows(SLUG)}
        created = {r["code"]: r["created_at"] for r in map(dict, palace.conn.execute(
            "SELECT code, created_at FROM candidate_reviews"))}
        plan = plan_rescore(palace, None, SLUG, screen_fn=fake_screen)
        by_code = {row["code"]: row for row in plan}
        assert by_code["300931"]["status"] == "updated" and by_code["300931"]["new_score"] == 96.4
        assert by_code["002937"]["status"] == "not_repicked"
        assert by_code["600000"]["status"] == "no_data"
        assert palace.candidate_scoring_rows(SLUG)[0]["score"] == before["002937"]["score"]  # 预览不写库

        assert apply_rescore(palace, plan) == 1
        after = {row["code"]: row for row in palace.candidate_scoring_rows(SLUG)}
        updated = after["300931"]
        assert updated["score"] == 96.4
        assert updated["reason"].startswith("三源尾盘共振（15:30）弱市低吸观察：评分百分位=96.40")
        evidence = json.loads(updated["evidence_json"])
        assert evidence[SCORE_PERCENTILE] == 96.4 and evidence["_data_snapshot"] == {"end": "2026-09-23"}
        assert updated["source"] == "job:screen" and updated["decision"] == "观察"
        assert after["002937"]["score"] == 1.4 and after["600000"]["score"] == 1.1
        assert {r["code"]: r["created_at"] for r in map(dict, palace.conn.execute(
            "SELECT code, created_at FROM candidate_reviews"))} == created


def test_since_until_filters_dates(tmp_path):
    with PalaceStore(tmp_path / "palace.db") as palace:
        seed(palace)
        assert [r["code"] for r in palace.candidate_scoring_rows(SLUG, since="2026-09-24")] == ["600000"]
        assert len(palace.candidate_scoring_rows(SLUG, until="2026-09-23")) == 2
