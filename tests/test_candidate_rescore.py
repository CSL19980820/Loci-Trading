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
    assert slug == SLUG and kwargs == {"health_check": False, "live_overlay": False, "data_snapshot": {}}
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


def test_cli_previews_then_applies_with_backup(tmp_path, monkeypatch, capsys):
    from cli import market as cli_market
    from src.strategy.application import screener

    palace_path = tmp_path / "palace.db"
    with PalaceStore(palace_path) as palace:
        seed(palace)
    monkeypatch.setattr(screener, "screen", fake_screen)
    args = ["--db", str(tmp_path / "market.db"), "rescore", "--strategy", SLUG, "--palace-db", str(palace_path)]
    assert cli_market.main(args) == 0
    preview = capsys.readouterr().out
    assert "300931" in preview and "96.4" in preview and "预览模式" in preview
    assert not list(tmp_path.glob("palace.db.bak-rescore-*"))

    assert cli_market.main([*args, "--apply"]) == 0
    assert "已更新 1 行" in capsys.readouterr().out
    backups = list(tmp_path.glob("palace.db.bak-rescore-*"))
    assert len(backups) == 1
    with PalaceStore(backups[0]) as backup:  # 备份是改写前的原样
        assert {r["code"]: r["score"] for r in backup.candidate_scoring_rows(SLUG)}["300931"] == 2.5
    with PalaceStore(palace_path) as palace:
        assert {r["code"]: r["score"] for r in palace.candidate_scoring_rows(SLUG)}["300931"] == 96.4


def small_market(path, *, codes=80, days=110, seed=4):
    """真实 MarketStore：日 K 每行挂一条来源回执，结构与生产一致（量级缩小）。"""
    import numpy as np
    import pandas as pd

    from src.market import MarketStore

    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-03-02", periods=days).strftime("%Y-%m-%d").tolist()
    symbols = [f"{600000 + i}" for i in range(codes)]
    close = 10 * np.exp(np.cumsum(rng.normal(0.002, 0.03, size=(days, codes)), axis=0))
    open_ = close * (1 + rng.normal(0, 0.01, size=(days, codes)))
    with MarketStore(path) as store:
        store.upsert_instruments({"code": c, "name": f"股{c}", "market": "SH", "board": "main",
                                  "instrument_type": "STOCK", "list_date": "2015-01-05"} for c in symbols)
        quotes, receipts = [], []
        for i, day in enumerate(dates):
            for j, code in enumerate(symbols):
                rid = f"R{day}{code}"
                high, low = max(open_[i, j], close[i, j]) * 1.01, min(open_[i, j], close[i, j]) * 0.99
                volume = float(rng.uniform(1e6, 9e6))
                quotes.append((day, code, open_[i, j], high, low, close[i, j], volume, volume * close[i, j],
                               1.5e8, float(rng.uniform(0.01, 0.15)), "tencent", rid, day + "T15:30:00"))
                receipts.append((rid, code, "hist_daily", "tencent", "ok", day, day, day + "T15:31:00"))
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,outstanding_share,"
            "turnover,source,receipt_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", quotes)
        store.conn.executemany(
            "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,coverage_start,"
            "coverage_end,generated_at) VALUES(?,?,?,?,?,?,?,?)", receipts)
        store.conn.commit()
        store.rebuild_calendar()
    return dates


def test_real_screen_rescore_skips_provenance_snapshot(tmp_path, monkeypatch):
    """用真实选股链路重算：不得装载行情取证快照（生产量级下单日 3.9 GB 的来源）。"""
    from src.market import MarketStore
    from src.strategy import screen
    from src.strategy.application.persist import score_from_factors

    dates = small_market(tmp_path / "market.db")
    with MarketStore(tmp_path / "market.db") as market:
        found = None
        for day in reversed(dates[-30:]):
            direct = screen(market, SLUG, trade_date=day, health_check=False, live_overlay=False,
                            skip_universe_safety=True)
            picks = direct.picks + direct.watch_picks
            if picks:
                found = (day, picks[0])
                break
    assert found, "合成行情应在最近 30 日内出现三源信号"
    day, pick = found

    def forbidden(*_args, **_kwargs):
        raise AssertionError("重算评分不应装载行情取证快照")

    monkeypatch.setattr(MarketStore, "data_snapshot", forbidden)
    with PalaceStore(tmp_path / "palace.db") as palace, MarketStore(tmp_path / "market.db") as market:
        palace.record_candidate(code=pick["code"], name="样本", decision="精选", score=1.3,
                                reason="三源尾盘共振（15:30）选中：A_MA25突破=1.00", occurred_on=day,
                                pool_id=f"{SLUG}@{day}", strategy_slug=SLUG, rule_version=SLUG, source="job:screen")
        plan = plan_rescore(palace, market, SLUG,
                            screen_fn=lambda *a, **k: screen(*a, skip_universe_safety=True, **k))
    assert [row["status"] for row in plan] == ["updated"]
    assert plan[0]["new_score"] == score_from_factors(pick["factors"])
    assert 0 <= plan[0]["new_score"] <= 100
