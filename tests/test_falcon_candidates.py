"""候选边界使用真实隔离SQLite；工具网络使用替身，仅验证访问/成交范围。"""
from datetime import datetime
import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.ai.application.tool_schema import tool_schema
from src.ledger import PalaceStore, StockAgentStore, new_guardian_account, settle_guardian_order
from src.ops.application.falcon_candidates import (
    falcon_research_codes, falcon_research_scope, load_falcon_candidates, project_falcon_candidate_scope,
)
from src.ops.application.stock_agent_decision import StockAgentDecision
from src.ops.application.stock_agent_policy import simulate_stock_agent
from src.ops.application.stock_agent_tools import stock_agent_tools
from src.ops.domain.stock_agent import StockAgentConfig

NOW = datetime.fromisoformat("2026-09-30T10:00:00+08:00")


class Ops:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE meta(key TEXT, value TEXT)")
        self.values = {}
        self.jobs = [{"id": "screen-fixture", "kind": "screen", "name": "screen:test-strategy", "enabled": True,
                      "config": {"strategy": "test-strategy", "schedule": {"mode": "once"}}}]

    def save(self, slug, value):
        key = "unified_monitor_pool:" + slug
        self.conn.execute("INSERT INTO meta VALUES (?, '')", (key,))
        self.values[key] = value
        self.jobs.append({"id": "watch-" + slug, "kind": "skill_watch", "name": "监测·" + slug, "enabled": True,
                          "config": {"skill": slug, "schedule": {"mode": "interval"}}})

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def list_jobs(self):
        return self.jobs

    def is_screen_job_opted_out(self, slug):
        return bool(self.get_setting("screen_job_opt_out:" + slug, False))


@pytest.fixture(autouse=True)
def isolated_candidate_definitions(monkeypatch):
    from src.ops.application import falcon_candidates as module
    monkeypatch.setattr(module, "get_screen_package", lambda _slug: None)
    monkeypatch.setattr(module, "is_builtin_registered", lambda slug: slug == "test-strategy")
    monkeypatch.setattr(module, "resolve_skill", lambda slug: {"slug": slug, "enabled": True})


def record(ledger, code, *, day="2026-09-29", created="2026-09-29T16:00:00+08:00", source="job:screen", decision="精选", pool="quant", strategy="test-strategy"):
    candidate_id = ledger.record_candidate(code=code, name=code, occurred_on=day, pool_id=pool,
        strategy_slug=strategy, decision=decision, source=source, reason="真实判分理由", score=80,
        effective_params={"threshold": 30}, evidence={"factor": 50})
    ledger.conn.execute("UPDATE candidate_reviews SET created_at=? WHERE id=?", (created, candidate_id))
    ledger.conn.commit()
    return candidate_id


def test_full_five_day_system_outputs_keep_rejected_evidence_without_buy_permission(tmp_path):
    path = str(tmp_path / "palace.db")
    with PalaceStore(path) as ledger:
        for index in range(16):
            record(ledger, f"6000{index:02d}", decision="落选" if index == 15 else "精选")
        record(ledger, "600100", day="2026-09-28", created="2026-09-28T16:00:00+08:00")
        record(ledger, "600101", source="manual")
        record(ledger, "600102", source="api:screen_backfill")
        record(ledger, "600103", source="api:screen:history")
        record(ledger, "600104", source="api:screen", created="2026-09-30T09:00:00+08:00")
        record(ledger, "600105", day="2026-09-30", created="2026-09-30T10:01:00+08:00")
    scope = load_falcon_candidates(path, Ops(), as_of=NOW)
    assert len(scope["candidates"]) == 17
    assert len(scope["candidate_codes"]) == 16 and len(scope["research_codes"]) == 17
    assert "600100" in scope["auto_observe_codes"]
    assert scope["window"]["dates"] == ["2026-09-23", "2026-09-24", "2026-09-28", "2026-09-29", "2026-09-30"]
    rejected = next(row for row in scope["candidates"] if row["code"] == "600015")
    assert not rejected["entry_eligible"]
    assert rejected["score"] == 80 and rejected["evidence"] == {"factor": 50}
    assert rejected["effective_params"] == {"threshold": 30}
    assert rejected["evidence_id"].startswith("candidate:CA-")


def test_quant_candidate_removes_nested_full_pool_snapshot_but_keeps_own_signal_and_score(tmp_path):
    path = str(tmp_path / "palace.db")
    target, outside = "301180", "600099"
    snapshot = {"source_evidence": {"requested_codes": [target, outside],
        "attempts": [{"code": outside, "name": "来源外股票", "receipt_id": "not-for-candidate"}],
        "attempts_not_observed_receipt_ids": [f"outside-receipt-{index:08d}" for index in range(40000)]}}
    evidence = {"score": 0.8, "signal": {"passed": True, "low_turnover": 2.5}, "流通股本": 1.64,
        "_data_snapshot": snapshot,
        "target_rows": [{"code": target, "signal": "缩量", "score": 0.8}, {"code": outside, "score": 99}],
        "upper_rows": [{"CODE": 301180, "factor": 77}, {"STOCK_CODE": 600099, "factor": 88}],
        "nested": {"more": [{"_data_snapshot": snapshot, "factor": 50}],
                   "codes": [target, outside], "requested_codes": [301180, 600099],
                   "by_stock": {target: {"volume_ratio": 0.5}, outside: {"volume_ratio": 99}},
                   "encoded": json.dumps({"rows": [{"stock_code": target, "signal": "通过"},
                                                    {"symbol": "sh600099", "name": "外部机会"}], "_data_snapshot": snapshot})}}
    assert len(json.dumps(evidence)) > 1_000_000
    with PalaceStore(path) as ledger:
        candidate_id = record(ledger, target)
        ledger.conn.execute("UPDATE candidate_reviews SET evidence_json=?,effective_params_json=? WHERE id=?",
            (json.dumps(evidence, ensure_ascii=False), json.dumps({"threshold": 30, "universe_codes": [target, outside]}), candidate_id))
        ledger.conn.commit()
    scope = load_falcon_candidates(path, Ops(), as_of=NOW)
    candidate = scope["candidates"][0]
    serialized = json.dumps(candidate, ensure_ascii=False)
    assert len(serialized) < 4000
    assert outside not in serialized and "outside-receipt" not in serialized and "_data_snapshot" not in serialized
    assert candidate["score"] == 80 and candidate["decision"] == "精选" and candidate["reason"] == "真实判分理由"
    assert candidate["evidence"]["score"] == 0.8 and candidate["evidence"]["signal"] == {"passed": True, "low_turnover": 2.5}
    assert candidate["evidence"]["流通股本"] == 1.64
    assert candidate["evidence"]["target_rows"] == [{"code": target, "signal": "缩量", "score": 0.8}]
    assert candidate["evidence"]["upper_rows"] == [{"CODE": 301180, "factor": 77}]
    assert candidate["evidence"]["nested"]["by_stock"] == {target: {"volume_ratio": 0.5}}
    assert candidate["evidence"]["nested"]["requested_codes"] == [301180]
    assert candidate["effective_params"] == {"threshold": 30, "universe_codes": [target]}
    assert candidate["evidence_scope"]["internal_snapshots_omitted"] == 3
    assert candidate["evidence_scope"]["foreign_stock_entries_omitted"] >= 5
    assert "未另存可回读" in candidate["evidence_scope"]["note"]


def test_skill_and_previously_saved_review_candidates_apply_same_evidence_scope_filter(tmp_path):
    path = str(tmp_path / "palace.db")
    with PalaceStore(path):
        pass
    original = {"code": "301180", "score": 0.9, "_data_snapshot": {"codes": ["301180", "600099"]},
                "diagnostic": [{"code": "301180", "signal": True}, {"ts_code": "600099.SH", "name": "外部机会"}]}
    ops = Ops()
    ops.save("sample", {"slug": "sample", "trade_date": "2026-09-30", "updated_at": "2026-09-30T09:59:00+08:00", "items": [original]})
    scope = load_falcon_candidates(path, ops, as_of=NOW)
    assert "600099" not in json.dumps(scope) and "_data_snapshot" not in json.dumps(scope)
    assert scope["candidates"][0]["diagnostic"] == [{"code": "301180", "signal": True}]
    assert scope["candidates"][0]["evidence"]["score"] == 0.9
    saved = {"as_of": NOW.replace(day=29).isoformat(), "research_codes": ["301180"], "strategy_slugs": ["sample"],
             "candidates": [{**original, "evidence_id": "candidate:saved", "strategy_slug": "sample"}]}
    merged = falcon_research_scope({"candidate_scope": {"candidate_codes": [], "candidates": []}, "analysis_only": True,
        "as_of": NOW.isoformat(), "review_evidence": {"runs": [{"candidate_scope": saved}]}})
    assert "600099" not in json.dumps(merged) and "_data_snapshot" not in json.dumps(merged)
    assert merged["candidates"][0]["score"] == 0.9 and merged["candidate_codes"] == []
    direct = project_falcon_candidate_scope({**saved, "raw_pool": {"code": "600099"}, "_data_snapshot": {"codes": ["600099"]}})
    assert direct["as_of"] == saved["as_of"] and len(direct["candidates"]) == 1
    assert "600099" not in json.dumps(direct) and "_data_snapshot" not in json.dumps(direct)
    assert project_falcon_candidate_scope(None) == {}


def test_snapshot_time_and_history_are_fail_closed(tmp_path):
    path = str(tmp_path / "palace.db")
    with PalaceStore(path) as ledger:
        record(ledger, "600001", day="2026-09-25", created="2026-09-25T16:00:00+08:00")
        record(ledger, "600002", day="2026-09-25", created="2026-09-30T09:00:00+08:00")
    ops = Ops()
    ops.save("yesterday", {"slug": "yesterday", "trade_date": "2026-09-29", "updated_at": "2026-09-29T14:00:00+08:00",
                           "items": [{"code": "600020", "score": 99}]})
    ops.save("future", {"slug": "future", "trade_date": "2026-09-25", "updated_at": "2026-09-30T09:00:00+08:00",
                        "items": [{"code": "600021"}]})
    scope = load_falcon_candidates(path, ops, as_of=NOW, research_date="2026-09-25", historical_review=True)
    assert scope["research_codes"] == []
    assert any("不读取原表分数" in warning for warning in scope["warnings"])
    assert any("无法重建" in warning for warning in scope["warnings"])
    assert any("future" in warning for warning in scope["warnings"])
    with pytest.raises(ValueError, match="不能晚于"):
        load_falcon_candidates(path, ops, as_of=NOW, research_date="2026-10-01")


def test_historical_quant_does_not_leak_later_overwritten_score_and_uses_saved_account_snapshot(tmp_path):
    path = str(tmp_path / "palace.db")
    original_time = datetime.fromisoformat("2026-09-24T16:01:00+08:00")
    with PalaceStore(path) as ledger:
        candidate_id = record(ledger, "600001", day="2026-09-24", created="2026-09-24T16:00:00+08:00")
    saved = load_falcon_candidates(path, Ops(), as_of=original_time)
    with PalaceStore(path) as ledger:
        ledger.conn.execute("UPDATE candidate_reviews SET score=999,decision='落选',reason='未来修订',evidence_json='{}',effective_params_json='{}' WHERE id=?", (candidate_id,))
        ledger.conn.commit()
    current = load_falcon_candidates(path, Ops(), as_of=NOW, research_date="2026-09-25", historical_review=True)
    assert current["candidates"] == [] and current["candidate_codes"] == []
    payload = {"candidate_scope": current, "analysis_only": True, "historical_review": True,
        "as_of": NOW.isoformat(), "research_date": "2026-09-25", "research_cutoff": "2026-09-25T23:59:59+08:00",
        "review_evidence": {"runs": [{"candidate_scope": saved}]}}
    scope = falcon_research_scope(payload)
    assert scope["research_codes"] == ["600001"] and scope["candidate_codes"] == []
    assert scope["candidates"][0]["score"] == 80
    assert scope["candidates"][0]["decision"] == "精选"
    assert scope["candidates"][0]["reason"] == "真实判分理由"
    assert scope["candidates"][0]["evidence"] == {"factor": 50}
    assert scope["candidates"][0]["effective_params"] == {"threshold": 30}


def test_all_window_outputs_remain_and_new_rejection_does_not_withdraw_old_eligible_signal(tmp_path):
    path = str(tmp_path / "palace.db")
    with PalaceStore(path) as ledger:
        record(ledger, "600001", day="2026-09-30", created="2026-09-30T09:00:00+08:00", pool="A@2026-09-30")
        record(ledger, "600002", pool="B@2026-09-29", decision="落选")
        record(ledger, "600002", day="2026-09-28", created="2026-09-28T16:00:00+08:00", pool="B@2026-09-28")
        record(ledger, "600003", day="2026-09-28", created="2026-09-28T16:00:00+08:00", pool="B@2026-09-28")
    scope = load_falcon_candidates(path, Ops(), as_of=NOW)
    assert scope["research_codes"] == ["600001", "600002", "600003"]
    assert scope["candidate_codes"] == ["600001", "600002", "600003"]
    assert [row["date"] for row in scope["candidates"]] == ["2026-09-28", "2026-09-28", "2026-09-29", "2026-09-30"]
    assert next(row for row in scope["candidates"] if row["date"] == "2026-09-29")["entry_eligible"] is False
    assert "较新落选只供判分研究" in scope["note"]


def test_five_exchange_days_include_all_outputs_exclude_expired_and_do_not_age_during_holiday(tmp_path):
    path = str(tmp_path / "palace.db")
    with PalaceStore(path) as ledger:
        for day, code in (("2026-09-22", "600022"), ("2026-09-23", "600023"), ("2026-09-24", "600024"),
                          ("2026-09-25", "600025"), ("2026-09-28", "600028"), ("2026-09-29", "600029"),
                          ("2026-09-30", "600030")):
            record(ledger, code, day=day, created=day + "T09:00:00+08:00", pool="quant@" + day)
    current = load_falcon_candidates(path, Ops(), as_of=NOW)
    holiday = load_falcon_candidates(path, Ops(), as_of=NOW.replace(month=10, day=7))
    assert current["candidate_codes"] == holiday["candidate_codes"] == ["600023", "600024", "600028", "600029", "600030"]
    assert current["window"] == holiday["window"]
    earliest = next(row for row in current["candidates"] if row["code"] == "600023")
    assert earliest["signal_date"] == "2026-09-23" and earliest["age_trading_days"] == 5
    assert earliest["expires_on"] == "2026-09-30"
    september24 = next(row for row in current["candidates"] if row["code"] == "600024")
    assert september24["age_trading_days"] == 4 and september24["expires_on"] == "2026-10-08"
    reopened = load_falcon_candidates(path, Ops(), as_of=NOW.replace(month=10, day=8))
    assert reopened["candidate_codes"] == ["600024", "600028", "600029", "600030"]
    assert reopened["window"]["start"] == "2026-09-24"
    assert reopened["lifecycle_ready"] and reopened["source_completeness"]["quant_window"]


def test_active_formula_requires_real_screen_switch_and_available_enabled_definition(tmp_path, monkeypatch):
    from src.ops import OpsStore
    from src.ops.application import falcon_candidates as module
    path = str(tmp_path / "palace.db")
    slugs = ["test-strategy", "package-on", "package-off", "job-disabled", "schedule-off", "opted-out", "unbound", "missing-definition"]
    monkeypatch.setattr(module, "get_screen_package", lambda slug: SimpleNamespace(enabled=slug != "package-off")
                        if slug in {"package-on", "package-off", "job-disabled", "schedule-off", "opted-out", "unbound"} else None)
    with PalaceStore(path) as ledger:
        for index, slug in enumerate(slugs):
            record(ledger, f"6001{index:02d}", strategy=slug, decision="观察" if slug == "package-on" else "精选")
    with OpsStore(str(tmp_path / "ops.db")) as ops:
        for slug in slugs:
            if slug == "unbound":
                continue
            ops.create_job(name="custom formula schedule" if slug == "package-on" else "screen:" + slug,
                kind="screen", cron="30 15 * * 1-5", enabled=slug != "job-disabled",
                config={"strategy": slug, "schedule": {"mode": "off" if slug == "schedule-off" else "once"}})
        ops.set_screen_job_opt_out("opted-out", True)
        scope = load_falcon_candidates(path, ops, as_of=NOW)
        assert scope["active_strategy_slugs"] == ["package-on", "test-strategy"]
        assert scope["candidate_codes"] == scope["auto_observe_codes"] == ["600100", "600101"]
        assert all(source["enabled"] for source in scope["active_sources"])
        assert scope["lifecycle_ready"] and scope["complete"]
        # 删除/明确关闭最后的公式是可核实空池，允许生命周期清理但不碰持仓。
        for job in ops.list_jobs():
            ops.update_job(job["id"], enabled=False)
        closed = load_falcon_candidates(path, ops, as_of=NOW)
        assert closed["active_sources"] == [] and closed["auto_observe_codes"] == [] and closed["lifecycle_ready"]


def test_unknown_announcement_year_or_switch_failure_never_guesses_or_authorizes_cleanup(tmp_path, monkeypatch):
    from src.ops.application import falcon_candidates as module
    path = str(tmp_path / "palace.db")
    with PalaceStore(path) as ledger:
        record(ledger, "600001")
    with monkeypatch.context() as calendar_patch:
        calendar_patch.setattr(module, "scheduled_trading_days", lambda *_args: (_ for _ in ()).throw(ValueError("未知年度")))
        scope = load_falcon_candidates(path, Ops(), as_of=NOW)
        assert not scope["complete"] and not scope["lifecycle_ready"] and scope["candidate_codes"] == []
        assert scope["window"]["dates"] == [] and any("权威交易日历" in warning for warning in scope["warnings"])
    broken = Ops()
    broken.list_jobs = lambda: (_ for _ in ()).throw(sqlite3.OperationalError("配置不可读"))
    scope = load_falcon_candidates(path, broken, as_of=NOW)
    assert not scope["complete"] and not scope["lifecycle_ready"] and not scope["source_completeness"]["active_formula_config"]


def test_skill_window_and_enabled_producer_do_not_expand_formula_auto_observe_scope(tmp_path, monkeypatch):
    from src.ops.application import falcon_candidates as module
    path = str(tmp_path / "palace.db")
    with PalaceStore(path) as ledger:
        record(ledger, "600001")
    ops = Ops()
    for slug, day, code in (("active", "2026-09-24", "600010"), ("expired", "2026-09-22", "600011"),
                            ("paused", "2026-09-29", "600012"), ("disabled", "2026-09-29", "600013")):
        ops.save(slug, {"slug": slug, "trade_date": day, "updated_at": day + "T16:00:00+08:00", "items": [{"code": code}]})
    next(job for job in ops.jobs if job.get("config", {}).get("skill") == "paused")["enabled"] = False
    monkeypatch.setattr(module, "resolve_skill", lambda slug: {"slug": slug, "enabled": slug != "disabled"})
    scope = load_falcon_candidates(path, ops, as_of=NOW)
    assert scope["candidate_codes"] == ["600001", "600010"]
    assert scope["auto_observe_codes"] == ["600001"]
    assert scope["source_completeness"]["skill_current_snapshot"] and not scope["source_completeness"]["skill_window_history"]
    # 历史证据不可用今天的开关重建过去：已截止快照只供研究，不能驱动自动池。
    ops.list_jobs = lambda: (_ for _ in ()).throw(AssertionError("不得读取当前历史开关"))
    past = load_falcon_candidates(path, ops, as_of=NOW, research_date="2026-09-29", historical_review=True)
    assert past["active_sources"] == [] and not past["lifecycle_ready"] and past["auto_observe_codes"] == []
    assert past["research_codes"] == ["600010", "600011", "600012", "600013"]


def test_unannounced_future_expiry_is_not_guessed_and_unknown_source_time_blocks_cleanup(tmp_path, monkeypatch):
    from src.market.domain.exchange_schedule import scheduled_trading_days as announced_days
    from src.ops.application import falcon_candidates as module
    monkeypatch.setattr(module, "scheduled_trading_days", announced_days)
    path = str(tmp_path / "palace.db")
    with PalaceStore(path) as ledger:
        candidate_id = record(ledger, "600001", day="2026-12-30", created="2026-12-30T16:00:00+08:00")
    year_end = datetime.fromisoformat("2026-12-31T10:00:00+08:00")
    scope = load_falcon_candidates(path, Ops(), as_of=year_end)
    assert scope["candidate_codes"] == ["600001"] and scope["lifecycle_ready"]
    assert scope["candidates"][0]["expires_on"] is None  # 没有2027公告，不按工作日猜未来失效日。
    with PalaceStore(path) as ledger:
        ledger.conn.execute("UPDATE candidate_reviews SET created_at='' WHERE id=?", (candidate_id,))
        ledger.conn.commit()
    unknown = load_falcon_candidates(path, Ops(), as_of=year_end)
    assert unknown["candidates"] == [] and not unknown["complete"] and not unknown["lifecycle_ready"]
    assert any("量化候选读取失败" in warning for warning in unknown["warnings"])


def test_skill_pool_is_read_in_full_and_position_projection_does_not_authorize_entry(tmp_path):
    path = str(tmp_path / "palace.db")
    with PalaceStore(path):
        pass
    ops = Ops()
    items = [{"code": f"6000{i:02d}", "score": i, "candidate_feed": "skill_watch:sample"} for i in range(12)]
    items.extend([{"code": "600099", "bucket": "position"}, {"code": "600098", "action": "sell"}])
    ops.save("sample", {"slug": "sample", "trade_date": "2026-09-30", "updated_at": "2026-09-30T09:59:00+08:00", "items": items})
    scope = load_falcon_candidates(path, ops, as_of=NOW)
    assert len(scope["candidates"]) == 13
    assert "600099" not in scope["research_codes"]
    assert "600098" in scope["research_codes"] and "600098" not in scope["candidate_codes"]
    assert scope["candidates"][0]["evidence_id"].startswith("skill:2026-09-30:sample:")


def test_missing_source_schema_does_not_stop_position_management(tmp_path):
    scope = load_falcon_candidates(str(tmp_path / "missing.db"), Ops(), as_of=NOW)
    assert not scope["complete"] and scope["candidate_codes"] == []
    assert any("已有持仓仍可管理退出" in warning for warning in scope["warnings"])
    assert not (tmp_path / "missing.db").exists()


def test_final_store_check_requires_evidenced_scope_and_rolls_back_failed_new_entry(tmp_path):
    cfg = StockAgentConfig(name="猎隼存储边界", kind="falcon", enabled=True, provider="fixture", model="fixture").model_dump()
    with StockAgentStore(tmp_path / "isolated.db") as store:
        profile = store.create(cfg, now=NOW)
        claimed = store.claim_run(profile["id"], "2026-09-30:intraday:10:00", "intraday", now=NOW)
        projected = dict(claimed["state"])
        projected["watchlist"] = [{"code": "600001", "name": "系统候选"}]
        # 模型在账户里伪造候选集合不能授权成交/新增观察。
        projected["candidate_scope"] = {"candidate_codes": ["600001"]}
        with pytest.raises(ValueError, match="缺少完整"):
            store.finish_run(profile["id"], claimed["run_id"], projected, {"summary": "缺失独立快照", "fills": []}, now=NOW)
        assert store.get(profile["id"])["state"]["watchlist"] == []
        scope = {"complete": True, "as_of": NOW.isoformat(), "candidate_codes": ["600001"], "candidates": []}
        with pytest.raises(ValueError, match="具有入选/观察证据"):
            store.finish_run(profile["id"], claimed["run_id"], projected, {"summary": "只有伪造名单", "fills": [], "candidate_scope": scope}, now=NOW)
        scope["candidates"] = [{"code": "600001", "entry_eligible": True, "evidence_id": "candidate:CA-fixture"}]
        store.finish_run(profile["id"], claimed["run_id"], projected, {"summary": "已核实候选", "fills": [], "candidate_scope": scope}, now=NOW)
        assert store.get(profile["id"])["state"]["watchlist"][0]["code"] == "600001"


def test_store_guard_keeps_exits_without_scope_and_rejects_existing_position_add():
    from src.ledger.domain.stock_agent_account import validate_falcon_candidate_transition
    previous = {"positions": [{"code": "600001", "quantity": 100}], "watchlist": []}
    validate_falcon_candidate_transition(previous, {"positions": [], "watchlist": []}, [{"code": "600001", "side": "sell"}], None, NOW)
    with pytest.raises(ValueError, match="缺少完整"):
        validate_falcon_candidate_transition(previous, {"positions": [{"code": "600001", "quantity": 200}], "watchlist": []},
                                              [{"code": "600001", "side": "buy"}], None, NOW)


def test_historical_saved_runs_expand_research_only_before_research_cutoff():
    payload = {"portfolio": {"positions": [{"code": "600001", "quantity": 100}]}, "analysis_only": True,
               "as_of": NOW.isoformat(), "research_date": "2026-09-29", "research_cutoff": "2026-09-29T23:59:59+08:00",
               "market_history_cutoff": "2026-09-28", "candidate_scope": {"research_codes": ["600002"]},
               "review_evidence": {"runs": [
                   {"candidate_scope": {"as_of": "2026-09-29T14:00:00+08:00", "research_codes": ["600003"]}},
                   {"candidate_scope": {"as_of": "2026-09-30T09:00:00+08:00", "research_codes": ["600004"]}}]}}
    assert falcon_research_codes(payload) == {"600001", "600002", "600003"}
    assert falcon_research_codes({**payload, "analysis_only": False}) == {"600001", "600002"}


def test_saved_review_scope_merges_old_sources_without_expanding_entry_and_preserves_original_score():
    original = {"code": "600001", "evidence_id": "candidate:first", "score": 50, "strategy_slug": "older"}
    payload = {"analysis_only": True, "as_of": NOW.isoformat(), "research_date": "2026-09-30",
        "candidate_scope": {"candidate_codes": ["600002"], "research_codes": ["600002"], "strategy_slugs": ["current"],
                            "candidates": [{**original, "score": 99}]},
        "review_evidence": {"runs": [{"candidate_scope": {"as_of": "2026-09-29T16:00:00+08:00",
            "candidate_codes": ["600001"], "research_codes": ["600001"], "strategy_slugs": ["older"], "candidates": [original]}}]}}
    scope = falcon_research_scope(payload)
    assert scope["candidate_codes"] == ["600002"]
    assert scope["research_codes"] == ["600001", "600002"]
    assert scope["strategy_slugs"] == ["current", "older"]
    assert scope["candidates"][0]["score"] == 50


def test_order_scope_rejects_new_and_add_outsiders_but_keeps_exit_and_cleanup():
    state = new_guardian_account()
    settle_guardian_order(state, {"code": "600001", "action": "buy", "quantity": 100, "reason": "昨日买入"},
                          {"price": 10}, NOW.replace(day=29), {}, guardian_policy=False)
    state["watchlist"] = [{"code": "600099", "name": "旧观察"}]
    decision = StockAgentDecision(summary="范围边界", orders=[
        {"code": "600001", "action": "add", "quantity": 100, "reason": "不能以持仓绕过候选"},
        {"code": "600088", "action": "watch", "reason": "不是系统候选"},
        {"code": "600099", "action": "unwatch", "reason": "清理过期观察"},
        {"code": "600001", "action": "sell", "quantity": 100, "reason": "已有持仓退出",
         "execution": {"kind": "market", "valid_until": "2026-09-30T10:02:00+08:00"}},
        {"code": "600002", "action": "watch", "reason": "真实候选等待进场"}])
    quotes = {"600001": {"code": "600001", "price": 10, "source": "tencent", "trade_date": "2026-09-30", "trade_time": "10:00:00",
        "order_book": {"code": "600001", "price": 10, "source": "tencent", "trade_date": "2026-09-30", "trade_time": "10:00:00",
                       "limit_up": 11, "limit_down": 9, "bid_price": 10, "bid_quantity": 100000,
                       "ask_price": 10, "ask_quantity": 100000}}}
    projected, fills, rejects = simulate_stock_agent(state, decision, quotes, NOW,
        StockAgentConfig(name="猎隼", kind="falcon").model_dump(), candidate_codes=["600002"])
    assert [(fill["code"], fill["side"]) for fill in fills] == [("600001", "sell")]
    assert [row["code"] for row in rejects] == ["600001", "600088"]
    assert all(row["reject_code"] == "falcon_candidate_scope" for row in rejects)
    assert [row["code"] for row in projected["watchlist"]] == ["600002"]


def test_missing_candidate_scope_is_fail_closed_only_for_falcon():
    decision = StockAgentDecision(summary="空范围", orders=[{"code": "600001", "action": "watch", "reason": "test"}])
    for kind, rejected in (("falcon", True), ("custom", False), ("leader", False)):
        _, _, rejects = simulate_stock_agent(new_guardian_account(), decision, {}, NOW,
            StockAgentConfig(name="test", kind=kind).model_dump(), phase="review", analysis_only=True)
        assert bool(rejects) is rejected


@pytest.mark.parametrize("protocol", ["anthropic", "openai_compatible"])
def test_tools_hide_discovery_and_block_implicit_outside_symbols(monkeypatch, protocol):
    from src.ops.application import stock_agent_tools as module
    schemas = [tool_schema(protocol, name, name, {"type": "object", "properties": properties}) for name, properties in (
        ("guardian_quotes", {"codes": {"type": "array"}}), ("guardian_account_read", {}),
        ("guardian_preflight", {}), ("system__market_quote", {"codes": {"type": "array"}}),
        ("system__market_status", {}), ("system__web_search", {"query": {"type": "string"}}))]
    calls = []
    monkeypatch.setattr(module, "GuardianResearchTools", lambda *args, **kwargs: SimpleNamespace(
        schemas=schemas, names=set(), execute=lambda name, arguments: calls.append((name, arguments)) or {"structured": arguments}))
    primary = [tool_schema(protocol, name, name, {"type": "object", "properties": {"symbol": {"type": "string"}}})
               for name in ("source__kline", "source__stock_screen", "source__stock_search", "source__market_overview")]
    monkeypatch.setattr(module, "agent_tools", lambda *args, **kwargs: (primary,
        lambda name, arguments: calls.append((name, arguments)) or {"structured": arguments}, {"wudao": True}))
    payload = {"portfolio": {"positions": [{"code": "600001", "quantity": 100}]},
        "candidate_scope": {"candidate_codes": ["600002"], "research_codes": ["600002", "600003"],
                            "candidates": [{"code": f"6000{i:02d}"} for i in range(12)], "strategy_slugs": ["allowed"]},
        "as_of": NOW.isoformat(), "analysis_only": False, "phase": "intraday"}
    available, execute, info = stock_agent_tools(protocol, profile={"id": "falcon", "config": {"kind": "falcon"}},
        payload=payload, palace_path="unused", deadline=999999999, checkpoint=lambda: None)
    names = {(schema.get("function") or schema)["name"] for schema in available}
    assert "agent_market_query" not in names and "system__web_search" not in names
    assert "source__stock_screen" not in names and "source__stock_search" not in names
    assert "source__market_overview" not in names
    assert "system__market_status" in names and "falcon_strategy_read" in names
    assert execute("source__kline", {"symbol": "600088"})["is_error"]
    assert execute("source__kline", {"symbol": "600002", "code": "600088"})["is_error"]
    assert execute("source__kline", {})["is_error"]
    assert calls == []
    assert "structured" in execute("source__kline", {"symbol": "600001"})
    assert execute("falcon_strategy_read", {"slug": "outsider"})["is_error"]
    first = execute("falcon_candidates_read", {"limit": 5})["structured"]
    second = execute("falcon_candidates_read", {"offset": first["next_offset"], "limit": 10})["structured"]
    assert len(first["items"]) + len(second["items"]) == 12
    assert second["next_offset"] is None and info["system_candidates_only"]


def test_historical_tools_do_not_offer_current_accounts_and_paginate_before_cutoff(monkeypatch, tmp_path):
    from src.ops.application import stock_agent_tools as module
    protocol = "openai_compatible"
    schemas = [tool_schema(protocol, name, name, {"type": "object", "properties": {}}) for name in (
        "guardian_account_read", "guardian_runtime", "guardian_preflight", "guardian_scenario",
        "guardian_calculate", "guardian_decision_history", "guardian_quotes")]
    monkeypatch.setattr(module, "GuardianResearchTools", lambda *args, **kwargs: SimpleNamespace(schemas=schemas, names=set()))
    monkeypatch.setattr(module, "agent_tools", lambda *args, **kwargs: ([], None, {"wudao": False}))
    path = str(tmp_path / "history.db")
    cfg = StockAgentConfig(name="历史范围", kind="falcon", enabled=True, provider="fixture", model="fixture").model_dump()
    with StockAgentStore(path) as store:
        profile = store.create(cfg, now=NOW.replace(day=29, hour=8))
        for day, hour in ((29, 10), (29, 11), (29, 19), (30, 9), (30, 10)):
            at = NOW.replace(day=day, hour=hour)
            claim = store.claim_run(profile["id"], f"{at.date().isoformat()}:review:{hour}", "review", now=at)
            store.finish_run(profile["id"], claim["run_id"], claim["state"], {"summary": f"{day}-{hour}", "fills": []}, now=at)
    original = {"code": "600001", "name": "old", "strategy_slug": "older", "evidence_id": "candidate:past", "score": 80}
    payload = {"portfolio": {"positions": [], "watchlist": []}, "candidate_scope": {"candidate_codes": [], "research_codes": [], "strategy_slugs": [], "candidates": []},
        "analysis_only": True, "historical_review": True, "as_of": NOW.isoformat(), "research_date": "2026-09-29",
        "research_cutoff": "2026-09-29T17:00:00+08:00", "market_history_cutoff": "2026-09-29",
        "review_evidence": {"runs": [{"candidate_scope": {"as_of": "2026-09-29T11:00:00+08:00",
            "candidate_codes": ["600001"], "research_codes": ["600001"], "strategy_slugs": ["older"], "candidates": [original]}}]}}
    available, execute, _ = stock_agent_tools(protocol, profile=profile, payload=payload, palace_path=path,
        deadline=999999999, checkpoint=lambda: None)
    names = {(schema.get("function") or schema)["name"] for schema in available}
    assert not names & {"guardian_account_read", "guardian_runtime", "guardian_preflight", "guardian_scenario", "guardian_quotes"}
    assert {"guardian_calculate", "guardian_decision_history", "falcon_strategy_read", "falcon_market_context"} <= names
    page = execute("guardian_decision_history", {"limit": 1})["structured"]
    assert page["total"] == 2 and page["items"][0]["summary"] == "29-11"
    page2 = execute("guardian_decision_history", {"limit": 1, "offset": 1})["structured"]
    assert page2["items"][0]["summary"] == "29-10"
    future_request = execute("guardian_decision_history", {"date": "2026-09-30", "limit": 10})["structured"]
    assert [row["summary"] for row in future_request["items"]] == ["29-11", "29-10"]
    snapshot = execute("falcon_strategy_read", {"slug": "older"})["structured"]
    assert not snapshot["definition_available"] and snapshot["candidate_evidence"] == [original]
    assert execute("falcon_candidates_read", {})["structured"]["candidate_codes"] == []
    assert execute("guardian_quotes", {"codes": ["600001"]})["is_error"]
    assert execute("falcon_market_context", {"sql": "SELECT code FROM securities"})["is_error"]
