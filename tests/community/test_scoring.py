"""评分口径单测：公式、时间折扣、榜单门槛与「为什么不用裸收益率」。"""

from __future__ import annotations

import math

import pytest

from src.community.domain.models import StrategyMetrics, ValidationError
from src.community.domain.scoring import (
    BOARD_RULES,
    LIVE_DAYS_FULL_CREDIT,
    SCORE_CLAMP,
    compute_score,
    describe_boards,
    oos_discount,
    rank_entries,
    recompute_scores,
)


def test_score_is_sharpe_times_time_discount() -> None:
    """score = sharpe_1y * min(1, live_days/365)，一个字都不能差。"""
    assert compute_score(2.0, LIVE_DAYS_FULL_CREDIT) == 2.0
    assert compute_score(2.0, 2 * LIVE_DAYS_FULL_CREDIT) == 2.0
    assert compute_score(2.0, 182) == pytest.approx(2.0 * 182 / 365, abs=1e-6)
    assert compute_score(1.5, 0) == 0.0


def test_oos_discount_is_a_ramp_to_one() -> None:
    assert oos_discount(-5) == 0.0
    assert oos_discount(0) == 0.0
    assert oos_discount(LIVE_DAYS_FULL_CREDIT) == 1.0
    assert oos_discount(10 * LIVE_DAYS_FULL_CREDIT) == 1.0
    assert oos_discount(100) < oos_discount(200) < oos_discount(300)


def test_score_survives_dirty_inputs() -> None:
    """脏数据不该让榜单炸，也不该让脏行冲到榜首。"""
    assert compute_score(float("nan"), 365) == 0.0
    assert compute_score(None, 365) == 0.0
    assert compute_score("2.0", 365) == 2.0
    assert compute_score(999.0, 365) == SCORE_CLAMP
    assert compute_score(-999.0, 365) == -SCORE_CLAMP


def test_negative_sharpe_is_also_discounted() -> None:
    """负夏普同样被折扣拉向 0——这不影响榜首，只影响榜尾的相对次序。"""
    assert compute_score(-2.0, 365) == -2.0
    assert compute_score(-2.0, 100) == pytest.approx(-2.0 * 100 / 365, abs=1e-6)


def _metrics(pid: str, **over: object) -> StrategyMetrics:
    base = {
        "publish_id": pid,
        "as_of_date": "2026-08-27",
        "sharpe_1y": 1.0,
        "annual_return": 10.0,
        "trades": 50,
        "live_days": 400,
    }
    base.update(over)
    base["score"] = compute_score(base["sharpe_1y"], base["live_days"])
    return StrategyMetrics.from_row(base)


def test_raw_return_alone_cannot_top_the_main_board() -> None:
    """三天翻倍的「刷榜号」不许压过跑满一年的稳健策略。

    这是不用裸收益率排序的核心理由：``annual_return`` 高但存续 3 天的条目，
    在主榜上要么因门槛被挡在外面，要么被时间折扣压到后面。
    """
    flash = _metrics("PUB-flash", sharpe_1y=6.0, annual_return=400.0, live_days=3, trades=35)
    steady = _metrics("PUB-steady", sharpe_1y=1.8, annual_return=35.0, live_days=400, trades=120)
    ranked = rank_entries([flash, steady], board="overall")
    assert [item["publish_id"] for item in ranked] == ["PUB-steady"]
    # 裸收益率排序会给出完全相反的答案——这正是要避免的
    assert flash.annual_return > steady.annual_return


def test_short_lived_entry_is_discounted_not_deleted_when_eligible() -> None:
    """存续够门槛但不满一年的，只被打折，不被删。"""
    half_year = _metrics("PUB-half", sharpe_1y=4.0, live_days=182, trades=40)
    full_year = _metrics("PUB-full", sharpe_1y=1.6, live_days=400, trades=40)
    ranked = rank_entries([half_year, full_year], board="overall")
    assert [item["publish_id"] for item in ranked] == ["PUB-half", "PUB-full"]
    assert ranked[0]["score"] == pytest.approx(4.0 * 182 / 365, abs=1e-6)


def test_boards_enforce_their_own_gates() -> None:
    thin = _metrics("PUB-thin", trades=5, live_days=400)
    fresh = _metrics("PUB-fresh", trades=50, live_days=30)
    veteran = _metrics("PUB-vet", trades=50, live_days=400)
    pool = [thin, fresh, veteran]
    overall = [i["publish_id"] for i in rank_entries(pool, board="overall")]
    assert overall == ["PUB-vet", "PUB-fresh"]
    # 成交笔数不足的永远进不了任何主榜
    assert "PUB-thin" not in [i["publish_id"] for i in rank_entries(pool, board="sharpe")]
    # 年化榜要求满一年
    assert [i["publish_id"] for i in rank_entries(pool, board="return")] == ["PUB-vet"]
    # 新秀榜只收不满一年的
    assert [i["publish_id"] for i in rank_entries(pool, board="rookie")] == ["PUB-fresh"]


def test_ranking_is_deterministic() -> None:
    """同分时按 live_days、publish_id 稳定排序——榜单要落快照，次序不能随机。"""
    a = _metrics("PUB-aaa", sharpe_1y=1.0, live_days=400, trades=40)
    b = _metrics("PUB-bbb", sharpe_1y=1.0, live_days=400, trades=40)
    c = _metrics("PUB-ccc", sharpe_1y=1.0, live_days=500, trades=40)
    first = [i["publish_id"] for i in rank_entries([a, b, c], board="overall")]
    second = [i["publish_id"] for i in rank_entries([c, b, a], board="overall")]
    assert first == second == ["PUB-ccc", "PUB-aaa", "PUB-bbb"]


def test_rank_entries_limit_and_rank_numbers() -> None:
    pool = [_metrics(f"PUB-{i}", sharpe_1y=float(i), live_days=400, trades=40) for i in range(1, 6)]
    ranked = rank_entries(pool, board="overall", limit=3)
    assert [item["rank"] for item in ranked] == [1, 2, 3]
    assert ranked[0]["publish_id"] == "PUB-5"
    assert ranked[0]["board"] == "overall"


def test_unknown_board_is_rejected() -> None:
    with pytest.raises(ValidationError):
        rank_entries([], board="收益率")


def test_recompute_scores_matches_formula() -> None:
    rows = [{"publish_id": "PUB-1", "sharpe_1y": 2.4, "live_days": 100}]
    out = recompute_scores(rows)
    assert out[0]["score"] == compute_score(2.4, 100)


def test_describe_boards_covers_every_rule() -> None:
    described = {item["board"] for item in describe_boards()}
    assert described == set(BOARD_RULES)
    assert all(item["description"] for item in describe_boards())


def test_score_is_finite_for_all_boards() -> None:
    for name in BOARD_RULES:
        ranked = rank_entries([_metrics("PUB-x", live_days=200, trades=40)], board=name)
        assert all(math.isfinite(item["score"]) for item in ranked)
