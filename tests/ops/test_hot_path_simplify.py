"""竞价低开带纯函数与市场快照短缓存。"""
from __future__ import annotations

from src.ops.application.skill_watch.auction_gap import classify_low_open_band
from src.ops.application.skill_watch.market_regime import (
    clear_market_snapshot_cache,
    fetch_market_snapshot,
)
from src.ops.application.skill_watch.roles import ROLE_LABEL


def test_classify_low_open_band_thresholds() -> None:
    assert classify_low_open_band(-5.0) == "abandon"
    assert classify_low_open_band(-2.0) == "downgrade"
    assert classify_low_open_band(-1.0) == "ok"
    assert (
        classify_low_open_band(-6.0, abandon_gap_pct=-6.0, downgrade_gap_pct=-3.0)
        == "abandon"
    )


def test_role_label_single_source() -> None:
    assert ROLE_LABEL["failed"] == "结构破坏"
    from src.ops.application.skill_watch.leader_map import ROLE_LABEL as map_labels
    from src.ops.application.skill_watch.role_stats import ROLE_LABEL as stats_labels

    assert map_labels is ROLE_LABEL
    assert stats_labels is ROLE_LABEL


def test_fetch_market_snapshot_reuses_short_ttl_cache() -> None:
    clear_market_snapshot_cache()
    calls = {"n": 0}

    def fake_tool(name: str, _args: dict) -> dict:
        calls["n"] += 1
        return {"tool": name, "ok": True}

    first = fetch_market_snapshot(fake_tool, trade_date="2026-08-09")
    second = fetch_market_snapshot(fake_tool, trade_date="2026-08-09")
    assert first[0]["tool"] == "short_term_emotion"
    assert second[0]["tool"] == "short_term_emotion"
    assert calls["n"] == 3  # emotion + ladder + themes once

    forced = fetch_market_snapshot(
        fake_tool, trade_date="2026-08-09", force_refresh=True
    )
    assert forced[1]["tool"] == "limit_up_ladder"
    assert calls["n"] == 6
    clear_market_snapshot_cache()
