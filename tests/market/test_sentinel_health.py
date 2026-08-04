"""行情仓体检：印鉴分、修复计划、include_ok、时效语义。"""
from __future__ import annotations

import tempfile
from datetime import datetime
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
    assert len(data["catalog"]) == 7


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
