from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.ops.application.skill_watch.dragon_return import (
    _suite_checks,
    _suite_passed,
    scan_dragon_return,
)
from src.ops.application.skill_watch.leader_map import LEADER_ROLES, scan_leader_map
from src.ops.application.skill_watch.market_regime import evaluate_market_gate
from src.ops.infrastructure.store import OpsStore


def _payload(data: dict) -> dict:
    return {"structured": data, "is_error": False}


class _MemoryMarketStore:
    """只读日 K 夹具，保证战法测试不回退到网络或 MCP。"""

    def __init__(self, rows: list[dict]) -> None:
        self.frame = pd.DataFrame(rows)

    def history(self, _code: str, **_kwargs: object) -> pd.DataFrame:
        return self.frame.copy()


def test_market_gate_soft_warning_caps_at_observe_not_empty() -> None:
    """tape degraded 等软警告：最多观察，不再一刀切空仓。"""
    emotion = {
        **_payload(
            {
                "promotion_rate": 0.46,
                "broken_rate": 0.12,
                "breadth": 0.62,
                "temperature": 72,
                "limit_up_count": 58,
                "limit_down_count": 2,
            }
        ),
        "degraded": True,
        "provenance": {"degraded": True, "warnings": ["degraded"]},
    }
    result = evaluate_market_gate(
        emotion,
        _payload({"rows": [{"code": "600001", "level": 4}]}),
        _payload({"rows": [{"themeCode": "801843k", "strength": 82}]}),
        trade_date="2026-08-07",
    )
    assert result["state"] == "observe"
    assert result["entry_allowed"] is False
    assert result["data_status"] == "degraded"
    assert result["soft_warnings"]
    assert "关键数据不完整" not in result["reason"]
    assert "软降级" in result["reason"]


def test_market_gate_allows_attack_when_emotion_ladder_and_theme_align() -> None:
    result = evaluate_market_gate(
        _payload(
            {
                "promotion_rate": 0.46,
                "broken_rate": 0.12,
                "breadth": 0.62,
                "temperature": 72,
                "limit_up_count": 58,
                "limit_down_count": 2,
            }
        ),
        _payload({"rows": [{"code": "600001", "level": 4}]}),
        _payload({"rows": [{"themeCode": "801843k", "strength": 82}]}),
        trade_date="2026-08-07",
    )

    assert result["state"] == "dragon"
    assert result["entry_allowed"] is True
    assert result["data_status"] == "ok"
    assert result["metrics"]["height"] == 4


def test_market_gate_fails_closed_in_a_clear_retreat() -> None:
    result = evaluate_market_gate(
        _payload(
            {
                "promotion_rate": 0.12,
                "broken_rate": 0.58,
                "breadth": 0.28,
                "temperature": 22,
                "limit_up_count": 20,
                "limit_down_count": 50,
            }
        ),
        _payload({"rows": [{"code": "600001", "level": 1}]}),
        _payload({"rows": [{"themeCode": "801843k", "strength": 20}]}),
    )

    assert result["state"] == "empty"
    assert result["mode"] == "空"
    assert result["entry_allowed"] is False


def test_market_gate_treats_missing_required_data_as_empty() -> None:
    result = evaluate_market_gate(
        _payload({"temperature": 50}),
        _payload({"rows": []}),
        _payload({"rows": []}),
    )

    assert result["state"] == "empty"
    assert result["data_status"] == "degraded"
    assert result["entry_allowed"] is False
    assert "promotion_rate" in result["missing"]


def test_stale_actual_trade_date_forces_empty() -> None:
    result = evaluate_market_gate(
        _payload(
            {
                "tradeDate": "20260806",
                "actualTradeDate": "20260806",
                "dateStatus": "mismatch",
                "promotionRates": {"streakPromotion": 50},
                "brokenBoardRate": 10,
                "highestBoard": 5,
            }
        ),
        _payload({"boardSummary": [{"level": 5, "count": 1}]}),
        _payload({"rows": [{"themeName": "主线", "strength": 90}]}),
        trade_date="2026-08-07",
    )
    assert result["state"] == "empty"
    assert result["freshness"]["stale"] is True
    assert "非当日" in result["reason"] or "实时" in result["reason"]


def test_boom_date_nested_does_not_poison_freshness() -> None:
    """官方 boomDate/催化叙事可跨日，不能当成 actualTradeDate。"""
    from src.ops.application.skill_watch.payload import extract_freshness

    fresh = extract_freshness(
        {
            "actualTradeDate": "20260807",
            "tradeDate": "20260807",
            "dateStatus": "exact",
            "snapshotTime": "2026-08-07T06:30:00Z",
            "rows": [
                {
                    "themeName": "医药",
                    "strength": 100,
                    "boomDate": "20260806",
                    "date": "2026-08-06",
                    "prevDate": "20260806",
                    "boomReason": "8月6日某某催化",
                }
            ],
        },
        requested="2026-08-07",
    )
    assert fresh["actual_trade_date"] == "2026-08-07"
    assert fresh["stale"] is False


def test_ladder_height_prefers_board_summary_and_continue_num() -> None:
    result = evaluate_market_gate(
        _payload(
            {
                "promotionRates": {"streakPromotion": 40},
                "brokenBoardRate": 10,
            }
        ),
        _payload(
            {
                "boardSummary": [{"level": 4, "count": 2}, {"level": 1, "count": 10}],
                "rows": [
                    {"code": "600001", "name": "测试", "continueNum": 4},
                    {"code": "600002", "name": "跟风", "continueNum": 1},
                ],
            }
        ),
        _payload({"rows": [{"themeName": "主线", "strength": 80}]}),
    )
    assert result["metrics"]["height"] == 4
    assert "height" not in result["missing"]


def test_market_gate_reads_wudao_nested_emotion_and_kpl_strength() -> None:
    """悟道 short_term_emotion / 开盘啦 strength 嵌套字段要对得上闸门。"""
    result = evaluate_market_gate(
        _payload(
            {
                "promotionRates": {
                    "streakPromotion": 46.2,
                    "firstToSecond": 40.0,
                },
                "brokenBoardRate": 12.5,
                "sealedLimitUp": 58,
                "sealedLimitDown": 2,
                "temperature": 72,
            }
        ),
        _payload(
            {
                "highestBoard": 5,
                "rows": [{"code": "600001", "level": 4}],
            }
        ),
        _payload(
            {
                "rows": [
                    {"themeCode": "801843k", "themeName": "机器人", "strength": 9800},
                    {"themeCode": "801001k", "themeName": "弱题材", "strength": 200},
                ]
            }
        ),
        trade_date="2026-08-07",
    )

    assert result["metrics"]["promotion_rate"] is not None
    assert abs(float(result["metrics"]["promotion_rate"]) - 0.462) < 1e-6
    assert abs(float(result["metrics"]["broken_rate"]) - 0.125) < 1e-6
    assert result["metrics"]["height"] == 5
    assert result["metrics"]["theme_strength"] is not None
    assert result["metrics"]["theme_strength"] >= 60
    assert result["missing"] == []
    assert result["data_status"] == "ok"


def test_dragon_return_empty_still_scans_roles_but_no_picks() -> None:
    """空仓一段式仍要角色（龙头/走弱）；可出观察票，绝无 intent=buy。"""
    calls: list[tuple[str, dict]] = []

    def call_tool(name: str, arguments: dict) -> dict:
        calls.append((name, arguments))
        if name == "short_term_emotion":
            return _payload({"promotion_rate": 0.1, "broken_rate": 0.6})
        if name == "limit_up_ladder":
            return _payload(
                {"rows": [{"code": "600001", "name": "测试龙", "level": 3}]}
            )
        if name == "theme_intraday_capital":
            return _payload(
                {"rows": [{"themeCode": "801843k", "themeName": "机器人", "strength": 15}]}
            )
        if name == "theme_stocks":
            return _payload({"rows": [{"code": "600001", "name": "测试龙"}]})
        if name == "kline":
            # 高位回撤走弱形态，便于空仓日仍出角色条
            close = [10.0] * 10 + [20.0] * 5 + [14.0] * 10
            volume = [1_000_000.0] * len(close)
            rows = _kline_rows(close, volume)
            return _payload({"batch": {"items": [{"code": "600001", "rows": rows}]}})
        if name == "auction_opening_snapshot":
            return _payload({"active": False, "stances": []})
        return _payload({})

    result = scan_dragon_return(
        call_tool,
        market_store=_MemoryMarketStore(_kline_rows([10.0] * 25, [1_000_000.0] * 25)),
    )

    assert result["market_gate"]["state"] == "empty"
    assert not any(str(p.get("intent") or "") == "buy" for p in result["picks"])
    assert result["signals"][0]["type"] == "gate_empty"
    names = [name for name, _ in calls]
    assert names[:3] == [
        "short_term_emotion",
        "limit_up_ladder",
        "theme_intraday_capital",
    ]
    assert "theme_stocks" in names
    assert "kline" not in names
    role_types = {str(s.get("type")) for s in result["signals"] if isinstance(s, dict)}
    assert role_types & {"leader_watch", "leader_weak"}


def _kline_rows(close: list[float], volume: list[float]) -> list[dict]:
    rows = []
    for index, (price, vol) in enumerate(zip(close, volume, strict=True)):
        rows.append(
            {
                "trade_date": (date.today() - timedelta(days=len(close) - index)).isoformat(),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": vol,
                "amount": vol * price,
            }
        )
    return rows


#: 前高 13 后缩量回踩到 11、今日放量拉到 12.5 —— 典型龙回头形态。
_PULLBACK_CLOSE = [10.0] * 20 + [11.0, 12.0, 13.0] + [11.0] * 5 + [12.5]
_PULLBACK_VOLUME = [1_000_000.0] * 23 + [200_000.0] * 5 + [1_500_000.0]


def _strong_market_call_tool(kline_rows: list[dict]):
    def call_tool(name: str, arguments: dict) -> dict:
        if name == "short_term_emotion":
            return _payload(
                {
                    "promotion_rate": 0.46,
                    "broken_rate": 0.12,
                    "breadth": 0.62,
                    "temperature": 72,
                }
            )
        if name == "limit_up_ladder":
            return _payload({"rows": [{"code": "600001", "name": "测试龙", "level": 3}]})
        if name == "theme_intraday_capital":
            return _payload(
                {"rows": [{"themeCode": "801843k", "themeName": "机器人", "strength": 82}]}
            )
        if name == "theme_stocks":
            return _payload({"rows": [{"code": "600001", "name": "测试龙"}]})
        if name == "kline":
            return _payload(
                {"batch": {"items": [{"code": "600001", "rows": kline_rows}]}}
            )
        if name == "auction_opening_snapshot":
            return _payload({"rows": []})
        raise AssertionError(name)

    return call_tool


def test_dragon_return_emits_unverified_paper_candidate() -> None:
    trade_day = date.today().isoformat()
    call_tool = _strong_market_call_tool(_kline_rows(_PULLBACK_CLOSE, _PULLBACK_VOLUME))

    result = scan_dragon_return(
        call_tool,
        market_store=_MemoryMarketStore(
            _kline_rows(_PULLBACK_CLOSE, _PULLBACK_VOLUME)
        ),
    )

    assert result["trade_date"] == trade_day
    assert result["market_gate"]["state"] == "dragon"
    assert result["picks"]
    buy = [p for p in result["picks"] if p.get("intent") == "buy"]
    assert buy
    assert buy[0]["validation"] == "unverified"
    assert result["signals"][0]["type"] == "paper_candidate"
    # 组合链：候选必须来自龙头战法角色，而不是自己再猜一遍
    assert result["ranked"][0]["role"] in {"leader", "secondary"}
    assert result["leader_map"]["leaders"]
    assert result.get("suite") == "dragon-king"
    checks = buy[0]["suite_checks"]
    assert _suite_passed(checks) is True
    assert all(checks[layer]["passed"] for layer in checks)
    assert buy[0]["suite_layer"] == "dragon-king"
    assert "龙头身份" in buy[0]["decision_reason"]
    assert "龙空龙进攻窗" in buy[0]["decision_reason"]
    assert "龙回头买点通过" in buy[0]["decision_reason"]


def test_dragon_return_does_not_buy_leader_before_any_pullback() -> None:
    """高涨幅/高连板只能进入观察；没有回撤过程时不得被总分直接放成可买。"""
    close = [10.0] * 20 + [11.0, 12.1, 13.31, 14.64, 16.1]
    volume = [1_000_000.0] * len(close)
    rows = _kline_rows(close, volume)

    result = scan_dragon_return(
        _strong_market_call_tool(rows),
        market_store=_MemoryMarketStore(rows),
    )

    assert result["market_gate"]["state"] == "dragon"
    assert result["ranked"][0]["score"] >= 65
    assert result["ranked"][0]["pullback_depth_pct"] == 0
    assert result["ranked"][0]["buy_zone_ready"] is False
    assert not any(row.get("intent") == "buy" for row in result["picks"])
    observes = [row for row in result["picks"] if row.get("intent") == "observe"]
    assert observes and "尚未回撤" in str(observes[0].get("observe_reason"))
    checks = observes[0]["suite_checks"]
    assert checks["leader_playbook"]["passed"] is True
    assert checks["market_gate"]["passed"] is True
    assert checks["dragon_return"]["passed"] is False
    assert "龙空龙进攻窗" in observes[0]["decision_reason"]
    assert "龙回头尚未回撤" in observes[0]["decision_reason"]


def test_dragon_king_suite_truth_table_requires_all_three_layers() -> None:
    gate_open = {"state": "dragon", "entry_allowed": True, "reason": "进攻窗口"}
    gate_empty = {"state": "empty", "entry_allowed": False, "reason": "空仓窗口"}
    ready_leader = {
        "role": "leader",
        "role_label": "龙头",
        "score": 70,
        "buy_zone_ready": True,
        "buy_zone_reason": "进入回头买点区",
    }

    role_failed = _suite_checks(
        {**ready_leader, "role": "follower", "role_label": "跟风"},
        gate=gate_open,
        candidate_score=65,
    )
    assert role_failed["leader_playbook"]["passed"] is False
    assert _suite_passed(role_failed) is False

    gate_failed = _suite_checks(ready_leader, gate=gate_empty, candidate_score=65)
    assert gate_failed["market_gate"]["passed"] is False
    assert _suite_passed(gate_failed) is False

    shape_failed = _suite_checks(
        {
            **ready_leader,
            "buy_zone_ready": False,
            "buy_zone_reason": "尚未回撤",
        },
        gate=gate_open,
        candidate_score=65,
    )
    assert shape_failed["dragon_return"]["passed"] is False
    assert _suite_passed(shape_failed) is False

    all_passed = _suite_checks(ready_leader, gate=gate_open, candidate_score=65)
    assert _suite_passed(all_passed) is True


def test_leader_map_labels_roles_and_keeps_signals_unverified() -> None:
    call_tool = _strong_market_call_tool(_kline_rows(_PULLBACK_CLOSE, _PULLBACK_VOLUME))

    result = scan_leader_map(
        call_tool,
        market_store=_MemoryMarketStore(
            _kline_rows(_PULLBACK_CLOSE, _PULLBACK_VOLUME)
        ),
    )

    assert result["themes"][0]["theme_name"] == "机器人"
    entry = result["entries"][0]
    assert entry["code"] == "600001"
    assert entry["role"] in LEADER_ROLES
    assert entry["role_basis"]
    assert result["validation"] == "unverified"
    assert all(signal["validation"] == "unverified" for signal in result["signals"])


def test_leader_map_marks_broken_structure_as_failed() -> None:
    """放量跌破 MA20 必须判成结构破坏，而不是继续当龙头。"""
    close = [10.0] * 20 + [14.0, 15.0, 16.0] + [12.0, 11.0, 10.0, 9.0] + [7.0]
    volume = [1_000_000.0] * 23 + [900_000.0] * 4 + [3_000_000.0]
    call_tool = _strong_market_call_tool(_kline_rows(close, volume))

    result = scan_leader_map(
        call_tool,
        market_store=_MemoryMarketStore(_kline_rows(close, volume)),
    )

    assert result["entries"][0]["role"] == "failed"
    assert result["leaders"] == []
    assert any(signal["type"] == "leader_weak" for signal in result["signals"])


def test_stage_toggles_change_what_the_scan_actually_does() -> None:
    """关掉的段必须真的不跑，而不是跑完再丢结果。"""
    from src.ops.application.skill_watch.tuning import normalize_tuning

    calls: list[str] = []

    def call_tool(name: str, arguments: dict) -> dict:
        calls.append(name)
        return _strong_market_call_tool(_kline_rows(_PULLBACK_CLOSE, _PULLBACK_VOLUME))(
            name, arguments
        )

    tuning = normalize_tuning(
        {
            "stages": {"market_gate": False, "auction_confirm": False, "paper_candidates": False},
        }
    )
    result = scan_dragon_return(
        call_tool,
        tuning=tuning,
        market_store=_MemoryMarketStore(
            _kline_rows(_PULLBACK_CLOSE, _PULLBACK_VOLUME)
        ),
    )

    assert result["market_gate"]["data_status"] == "disabled"
    assert result["market_gate"]["entry_allowed"] is False
    assert "market_gate_disabled" in result["market_gate"]["quality_warnings"]
    assert "auction_opening_snapshot" not in calls
    assert result["picks"] == []
    # 关闸门 fail-closed → 空仓早退；不再继续产出纸面候选观察句
    assert any(
        "禁开仓" in str(s.get("reason")) or "空仓" in str(s.get("reason"))
        for s in result["signals"]
    )


def test_candidate_score_line_is_configurable() -> None:
    from src.ops.application.skill_watch.tuning import normalize_tuning

    call_tool = _strong_market_call_tool(_kline_rows(_PULLBACK_CLOSE, _PULLBACK_VOLUME))
    strict = scan_dragon_return(
        call_tool,
        tuning=normalize_tuning({"scan": {"candidate_score": 100}}),
        market_store=_MemoryMarketStore(
            _kline_rows(_PULLBACK_CLOSE, _PULLBACK_VOLUME)
        ),
    )

    assert not any(str(p.get("intent") or "") == "buy" for p in strict["picks"])
    assert any(str(p.get("intent") or "") == "observe" for p in strict["picks"])
    assert strict["ranked"]


def test_leader_map_still_scans_in_empty_window_but_dragon_stops() -> None:
    """退潮日的龙头健康最有价值，所以地图继续扫；开仓型战法则提前止损配额。"""
    calls: list[str] = []

    def call_tool(name: str, arguments: dict) -> dict:
        calls.append(name)
        if name == "short_term_emotion":
            return _payload({"promotion_rate": 0.1, "broken_rate": 0.6, "temperature": 20})
        if name == "limit_up_ladder":
            return _payload({"rows": [{"code": "600001", "level": 1}]})
        if name == "theme_intraday_capital":
            return _payload({"rows": [{"themeCode": "801843k", "strength": 15}]})
        if name == "theme_stocks":
            return _payload({"rows": [{"code": "600001", "name": "测试龙"}]})
        return _payload({"batch": {"items": [{"code": "600001", "rows": []}]}})

    scan_leader_map(
        call_tool,
        market_store=_MemoryMarketStore(
            _kline_rows(_PULLBACK_CLOSE, _PULLBACK_VOLUME)
        ),
    )

    assert "theme_stocks" in calls


def test_skill_watch_does_not_seed_nextday_plan_midday(tmp_path: Path, monkeypatch) -> None:
    """盘中 skill_watch 不得种子次日预案；收盘选股/日终才写。"""
    from src.ops.application.jobs import registry
    from src.ops.application.jobs import paper_quant_support as pq_support

    monkeypatch.setattr(pq_support, "_next_trade_date", lambda *_args: "2026-08-08")
    result = {
        "slug": "dragon-return",
        "picks": [
            {
                "code": "600001",
                "name": "测试龙",
                "close": 10.0,
                "planned_layers": 0.5,
                "validation": "unverified",
            }
        ],
    }
    job = {
        "kind": "skill_watch",
        "name": "监测·dragon-return",
        "config": {"skill": "dragon-return"},
    }
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin(
            "dragon-return",
            config={"paper_quant": {"enabled": True}},
        )
        registry._maybe_seed_nextday_plan(store=store, job=job, result=result)
        plan = store.get_nextday_plan("dragon-return", "2026-08-08")

    assert plan is None
    assert "nextday_plan" not in result


def test_screen_result_seeds_enabled_paper_cabin(tmp_path: Path, monkeypatch) -> None:
    from src.ops.application.jobs import registry
    from src.ops.application.jobs import paper_quant_support as pq_support

    monkeypatch.setattr(pq_support, "_next_trade_date", lambda *_args: "2026-08-08")
    result = {
        "slug": "custom-test-slug",
        "picks": [
            {
                "code": "600001",
                "name": "测试龙",
                "close": 10.0,
                "planned_layers": 0.5,
                "validation": "unverified",
            }
        ],
    }
    job = {
        "kind": "screen",
        "name": "选股·custom-test-slug",
        "config": {"skill": "custom-test-slug"},
    }
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_paper_cabin(
            "custom-test-slug",
            config={"paper_quant": {"enabled": True}},
        )
        registry._maybe_seed_nextday_plan(store=store, job=job, result=result)
        plan = store.get_nextday_plan("custom-test-slug", "2026-08-08")

    assert plan is not None
    assert result["nextday_plan"]["slug"] == "custom-test-slug"
    assert plan["items"][0]["code"] == "600001"
