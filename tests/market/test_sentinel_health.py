"""行情仓体检：印鉴分、修复计划、include_ok、时效语义。"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.market.infrastructure.sentinel import (
    Finding,
    HealthReport,
    _check_staleness,
    _wall_clock_data_lag,
    build_repair_plan,
    remediation_for,
    seal_grade,
    seal_score,
)
from src.market.infrastructure.store import MarketStore


def test_seal_score_penalties() -> None:
    assert seal_score(block_count=0, warn_count=0) == 100
    assert seal_score(block_count=2, warn_count=1) == 42
    assert seal_score(block_count=5, warn_count=0) == 0
    assert seal_grade(96) == "优"
    assert seal_grade(72) == "良"
    assert seal_grade(55) == "中"
    assert seal_grade(42) == "差"


def test_seal_grade_never_reads_good_while_blocked() -> None:
    """单条 block 只扣 25 分 → 75 →「良」。体检拦下选股却显示「良」= 虚假安心。"""
    blocked_score = seal_score(block_count=1, warn_count=0)
    assert blocked_score == 75
    assert seal_grade(blocked_score) == "良"
    assert seal_grade(blocked_score, blocked=True) == "中"
    assert seal_grade(100, blocked=True) == "中"
    assert seal_grade(40, blocked=True) == "差"

    report = HealthReport(
        trade_date="2026-07-29",
        findings=[Finding("coverage", "block", "覆盖率仅 12%")],
    )
    assert report.blocked is True
    assert report.score == 75
    assert report.grade == "中"


def test_health_report_to_dict_includes_score_and_plan() -> None:
    report = HealthReport(
        trade_date="2026-07-29",
        findings=[
            Finding("staleness", "block", "落后 3 日", observed=3, threshold=3),
            Finding("factor_age", "warn", "因子过旧", observed=42, threshold=30),
            Finding("turnover", "ok", "换手正常"),
        ],
        checked_at="2026-07-30T10:00:00",
    )
    data = report.to_dict()
    assert data["blocked"] is True
    assert data["block_count"] == 1
    assert data["warn_count"] == 1
    assert data["score"] == 67
    assert data["grade"] == "中"
    assert data["repair_plan"]["needs_bootstrap"] is True
    assert data["repair_plan"]["with_factors"] is True
    assert "sync" in data["repair_plan"]["actions"]
    assert "sync_factors" in data["repair_plan"]["actions"]
    catalog_ids = {item["id"] for item in data["catalog"]}
    assert {
        "empty_store",
        "staleness",
        "coverage",
        "turnover",
        "zero_amount",
        "factor_age",
        "failed_codes",
    } <= catalog_ids
    assert "capabilities_runtime" in catalog_ids


def test_repair_plan_dedupes_and_orders() -> None:
    findings = [
        Finding("coverage", "block", "覆盖不足"),
        Finding("staleness", "block", "落后"),
        Finding("factor_age", "warn", "因子旧"),
        Finding("turnover", "warn", "缺换手"),
    ]
    plan = build_repair_plan(findings)
    assert plan["actions"] == ["sync_factors", "sync", "repair_turnover"]
    assert plan["primary_action"] == "sync_factors"
    assert plan["needs_bootstrap"] is True
    assert plan["needs_turnover_repair"] is True
    assert plan["with_factors"] is True


def test_repair_plan_turnover_only() -> None:
    plan = build_repair_plan([Finding("turnover", "warn", "缺换手")])
    assert plan["actions"] == ["repair_turnover"]
    assert plan["needs_bootstrap"] is False
    assert plan["needs_turnover_repair"] is True
    assert plan["with_factors"] is False


def test_remediation_turnover_is_dedicated() -> None:
    rem = remediation_for("turnover")
    assert rem is not None
    assert rem["action"] == "repair_turnover"


def test_job_sync_stale_is_manual_not_bootstrap() -> None:
    """Job 时效提示不得一键走 sync/bootstrap，否则会卡在刷新证券列表。"""
    from src.market.infrastructure.sentinel_evidence import evidence_remediation

    rem = evidence_remediation("job_sync_stale")
    assert rem is not None
    assert rem["action"] == "open_jobs"
    assert remediation_for("job_sync_stale") == rem
    plan = build_repair_plan(
        [
            Finding("turnover", "warn", "缺换手"),
            Finding("job_sync_stale", "warn", "同步过久未跑"),
        ]
    )
    assert plan["actions"] == ["repair_turnover"]
    assert plan["needs_bootstrap"] is False
    assert plan["needs_turnover_repair"] is True


def test_empty_findings_plan() -> None:
    plan = build_repair_plan([])
    assert plan["actions"] == []
    assert plan["primary_action"] is None
    assert plan["needs_bootstrap"] is False


def test_wall_clock_lag_zero_when_tip_is_today() -> None:
    days = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"]
    assert (
        _wall_clock_data_lag(
            "2026-07-30", days, now=datetime(2026, 7, 30, 16, 0)
        )
        == 0
    )


def test_wall_clock_lag_counts_behind_tip() -> None:
    days = ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23"]
    lag = _wall_clock_data_lag(
        "2026-07-23", days, now=datetime(2026, 7, 30, 16, 0)
    )
    assert lag > 3


def test_historical_screen_date_is_not_blocked_as_stale() -> None:
    """选股复盘选更早基准日 ≠ 行情过期；仓新鲜时必须放行。"""
    dates = [
        "2026-07-23",
        "2026-07-24",
        "2026-07-27",
        "2026-07-28",
        "2026-07-29",
        "2026-07-30",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        store = MarketStore(Path(tmp) / "market.db")
        try:
            n = len(dates)
            frame = pd.DataFrame(
                {
                    "date": dates,
                    "open": np.full(n, 10.0),
                    "high": np.full(n, 11.0),
                    "low": np.full(n, 9.0),
                    "close": np.full(n, 10.5),
                    "volume": np.full(n, 1e6),
                    "amount": np.full(n, 1e7),
                    "outstanding_share": np.full(n, 1e9),
                    "turnover": np.full(n, 0.01),
                }
            )
            store.upsert_quotes("600519", frame, source="test")
            coverage = store.coverage()
            finding = _check_staleness(
                store,
                coverage,
                "2026-07-23",
                {"max_stale_days": 3},
                now=datetime(2026, 7, 30, 16, 0),
            )
            # 仓末日是 07-30；若误用「基准日距末日」会算 lag=5 并 block。
            assert finding.severity == "ok", finding.message
        finally:
            store.close()


def test_future_screen_date_beyond_data_is_blocked() -> None:
    dates = ["2026-07-27", "2026-07-28"]
    with tempfile.TemporaryDirectory() as tmp:
        store = MarketStore(Path(tmp) / "market.db")
        try:
            n = len(dates)
            frame = pd.DataFrame(
                {
                    "date": dates,
                    "open": np.full(n, 10.0),
                    "high": np.full(n, 11.0),
                    "low": np.full(n, 9.0),
                    "close": np.full(n, 10.5),
                    "volume": np.full(n, 1e6),
                    "amount": np.full(n, 1e7),
                    "outstanding_share": np.full(n, 1e9),
                    "turnover": np.full(n, 0.01),
                }
            )
            store.upsert_quotes("600519", frame, source="test")
            # 手工把日历扩到尚无行情的未来日，模拟「基准日超前于仓」
            store.conn.execute(
                "INSERT INTO trading_calendar(trade_date, updated_at)"
                " VALUES('2026-07-29', datetime('now'))"
            )
            store.conn.commit()
            finding = _check_staleness(
                store,
                {"last_date": "2026-07-28"},
                "2026-07-29",
                {"max_stale_days": 3},
            )
            assert finding.severity == "block"
            assert "尚未覆盖" in finding.message
        finally:
            store.close()


def _seed_month(store: MarketStore, dates: list[str]) -> None:
    n = len(dates)
    store.upsert_quotes(
        "600519",
        pd.DataFrame(
            {
                "date": dates,
                "open": np.full(n, 10.0),
                "high": np.full(n, 11.0),
                "low": np.full(n, 9.0),
                "close": np.full(n, 10.5),
                "volume": np.full(n, 1e6),
                "amount": np.full(n, 1e7),
                "outstanding_share": np.full(n, 1e9),
                "turnover": np.full(n, 0.01),
            }
        ),
        source="test",
    )


def _attach_receipt(store: MarketStore, *, since: str) -> None:
    store.conn.execute(
        "UPDATE quotes_daily SET receipt_id = 'r-recent' WHERE trade_date >= ?",
        (since,),
    )
    store.conn.execute(
        "INSERT INTO source_route_receipts("
        "receipt_id, code, lane, requested_sources_json, selected_source,"
        "fallback_used, state, coverage_json, generated_at"
        ") VALUES("
        "'r-recent', '600519', 'hist_daily', '[]', 'test',"
        "0, 'ok', '{}', datetime('now'))"
    )
    store.conn.execute(
        "INSERT INTO source_route_attempts("
        "receipt_id, attempt_no, source_id, state, checked_at, rows,"
        "fields_json, error"
        ") VALUES("
        "'r-recent', 1, 'test', 'ok', datetime('now'), 1, '[]', '')"
    )
    store.conn.commit()


def test_source_evidence_gap_still_scans_only_sampled_days() -> None:
    """不做全表 COUNT：只查近窗逐日 + 少量历史抽样日，覆盖率全绿时仍报 ok。"""
    from src.market.infrastructure.sentinel_evidence import check_source_evidence_gap

    dates = [f"2026-07-{day:02d}" for day in range(1, 31)]
    with tempfile.TemporaryDirectory() as tmp:
        store = MarketStore(Path(tmp) / "market.db")
        try:
            _seed_month(store, dates)
            _attach_receipt(store, since="2026-07-01")
            finding = check_source_evidence_gap(
                store, max_ratio=0.5, lookback_days=5, history_samples=5
            )
            assert finding.severity == "ok", finding.message
            assert finding.observed["lookback_days"] == 5
            assert finding.observed["total_rows"] == 5
            assert finding.observed["legacy_rows"] == 0
            # 历史抽样也只碰有限几天，不是全表
            assert len(finding.observed["history_sample_days"]) == 5
            assert finding.observed["history_legacy_rows"] == 0
        finally:
            store.close()


def test_source_evidence_gap_flags_history_when_only_recent_window_has_receipts() -> None:
    """增量同步只重写近 20 交易日：只看近窗会永远绿，历史缺回执必须报出来。"""
    from src.market.infrastructure.sentinel_evidence import check_source_evidence_gap

    dates = [f"2026-07-{day:02d}" for day in range(1, 31)]
    with tempfile.TemporaryDirectory() as tmp:
        store = MarketStore(Path(tmp) / "market.db")
        try:
            _seed_month(store, dates)
            _attach_receipt(store, since="2026-07-26")
            finding = check_source_evidence_gap(
                store, max_ratio=0.5, lookback_days=5, history_samples=5
            )
            assert finding.observed["legacy_rows"] == 0, "近窗本身是干净的"
            assert finding.severity == "warn", finding.message
            assert "历史抽样" in finding.message
            assert finding.observed["history_ratio"] == 1.0
        finally:
            store.close()


def test_factor_coverage_sees_codes_that_max_fetched_at_hides() -> None:
    """factor_age 看 MAX(fetched_at)：一只票今天刷过就报「新鲜」，其余全被掩盖。"""
    from src.market.infrastructure.sentinel import _check_factor_age
    from src.market.infrastructure.sentinel_extended import check_factor_coverage

    with tempfile.TemporaryDirectory() as tmp:
        store = MarketStore(Path(tmp) / "market.db")
        try:
            fresh = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(" ")
            store.conn.executemany(
                "INSERT INTO adjust_factors(code, trade_date, hfq_factor, fetched_at)"
                " VALUES(?, ?, ?, ?)",
                [
                    ("600519", "2020-06-01", 1.0, "2020-06-02 00:00:00"),
                    ("000001", "2020-06-01", 1.0, "2020-06-02 00:00:00"),
                    ("000002", "2026-07-30", 1.0, fresh),
                ],
            )
            store.conn.commit()

            age = _check_factor_age(store, {"max_factor_age_days": 30.0})
            assert age.severity == "ok", "MAX(fetched_at) 只看最新的那只，报健康"

            coverage = check_factor_coverage(store, max_age_days=30.0)
            assert coverage.severity == "warn", coverage.message
            assert coverage.observed == {
                "codes": 3,
                "stale_codes": 2,
                "ratio": round(2 / 3, 6),
            }
        finally:
            store.close()


def test_source_evidence_gap_warns_when_recent_window_mostly_legacy() -> None:
    from src.market.infrastructure.sentinel_evidence import check_source_evidence_gap

    dates = ["2026-07-28", "2026-07-29", "2026-07-30"]
    with tempfile.TemporaryDirectory() as tmp:
        store = MarketStore(Path(tmp) / "market.db")
        try:
            n = len(dates)
            frame = pd.DataFrame(
                {
                    "date": dates,
                    "open": np.full(n, 10.0),
                    "high": np.full(n, 11.0),
                    "low": np.full(n, 9.0),
                    "close": np.full(n, 10.5),
                    "volume": np.full(n, 1e6),
                    "amount": np.full(n, 1e7),
                    "outstanding_share": np.full(n, 1e9),
                    "turnover": np.full(n, 0.01),
                }
            )
            store.upsert_quotes("600519", frame, source="test")
            finding = check_source_evidence_gap(
                store, max_ratio=0.5, lookback_days=10
            )
            assert finding.severity == "warn"
            assert "近窗无回执" in finding.message
            assert finding.observed["legacy_rows"] == 3
        finally:
            store.close()
