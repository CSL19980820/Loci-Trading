"""研究冻结上下文保留严格凭证，普通回测报告直接消费 compact。"""
import json

import pandas as pd
import pytest

from src.backtest.application import runner
from src.backtest.application.engine import BacktestConfig
from src.market import MarketStore
from src.research.application.backtest_run_phase import prepare_research_backtest_context
from src.research.application.backtest_support import input_evidence_failures, validation_warnings
from src.research.domain.temporal import MembershipSnapshot
from src.strategy.domain.base import SignalResult


class EvidenceBoundaryStrategy:
    slug = "evidence-boundary"
    name = description = "evidence boundary fixture"
    entry_timing = "next_open"
    adjust = "none"

    def default_params(self):
        return {}

    def required_fields(self):
        return ("close",)

    def min_bars(self):
        return 1

    def compute(self, panels, params=None):
        return SignalResult(panels["close"].gt(1000))


@pytest.fixture
def boundary_store(tmp_path):
    days = pd.bdate_range("2024-01-02", periods=60).strftime("%Y-%m-%d").tolist()
    with MarketStore(tmp_path / "market.db") as store:
        store.upsert_instruments([{"code": "600001", "name": "fixture", "market": "sh",
                                   "board": "main", "list_date": "2010-01-01"}])
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,turnover,"
            "outstanding_share,source,receipt_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(day, "600001", 10., 10.2, 9.8, 10., 100000., 1000000., .01, 10000000.,
              "tdx", "verified", day + "T15:30:00") for day in days],
        )
        store.conn.execute(
            "INSERT INTO source_route_receipts(receipt_id,code,lane,selected_source,state,source_url,"
            "fetched_at,as_of,parser_revision,payload_sha256,publication_status,published_at,"
            "availability_status,available_at,coverage_start,coverage_end,coverage_json,generated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("verified", "600001", "hist_daily", "tdx", "selected", "https://example.invalid/market",
             days[-1] + "T15:30:00", days[-1], "fixture-v1", "a" * 64, "observed",
             days[0] + "T15:00:00", "observed", days[0] + "T15:00:00", days[0], days[-1],
             '{"rejected_ohlc_rows":0}', days[-1] + "T15:30:00"),
        )
        store.conn.executemany(
            "INSERT INTO source_route_attempts(receipt_id,attempt_no,source_id,state,checked_at,rows) "
            "VALUES(?,?,?,?,?,?)",
            [("verified", i, "tdx", "selected", days[-1] + "T15:30:00", len(days)) for i in range(80)],
        )
        store.conn.commit()
        store.rebuild_calendar()
        yield store, days


def _observe_snapshot(monkeypatch, store):
    calls = []
    original = store.data_snapshot

    def snapshot(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(store, "data_snapshot", snapshot)
    return calls


def test_research_full_receipts_pass_strict_gate_and_reports_use_compact(boundary_store, monkeypatch):
    store, days = boundary_store
    calls = _observe_snapshot(monkeypatch, store)
    engine = EvidenceBoundaryStrategy()
    config = BacktestConfig(benchmark=None, hold_days=1)
    membership = MembershipSnapshot(
        universe_id="fixture-pit", as_of=days[0], members=("600001",), available_at=days[0],
        source_id="fixture", source_url="https://example.invalid/universe", snapshot_revision="v1",
        fetched_at=days[0] + "T09:00:00", payload_sha256="b" * 64, parser_revision="fixture-v1",
        pit_membership=True,
    )
    context, summary = prepare_research_backtest_context(
        store, strategy=engine, start=days[40], end=days[45], params=None, config=config, universe=None,
        historical_universe_id=membership.universe_id, membership_rows=[membership],
        historical_codes=["600001"],
    )
    evidence = context["data_snapshot"]["source_evidence"]
    assert evidence["receipts"][0]["state"] == "selected"
    assert len(evidence["attempts"]) == 80
    assert "receipts_source" not in evidence
    assert input_evidence_failures(membership=summary, strict_pit=True,
                                   data_snapshot=context["data_snapshot"]) == []

    monkeypatch.setattr(runner, "fast_backtest_enabled", lambda: False)
    trade = runner.backtest_strategy(store, engine, start=days[40], end=days[45],
                                     config=config, codes=["600001"])
    horizon = runner.backtest_strategy_horizon(store, engine, start=days[40], end=days[45],
                                               codes=["600001"], horizons=[1])
    for report in (trade, horizon):
        compact = report.config["data_snapshot"]["source_evidence"]
        assert compact["receipts"] == [] and compact["receipts_total"] == 1
        assert len(compact["attempts"]) == 50 and compact["attempts_total"] == 80
    assert [call.get("source_evidence_mode", "full") for call in calls] == ["full", "compact", "compact"]

    store.conn.execute("UPDATE source_route_receipts SET parser_revision='',coverage_json=?",
                       (json.dumps({"rejected_ohlc_rows": 4}),))
    store.conn.commit()
    rejected = runner.prepare_backtest_context(store, engine, start=days[40], end=days[45],
                                                config=config, codes=["600001"])["data_snapshot"]
    failures = input_evidence_failures(membership=summary, strict_pit=True, data_snapshot=rejected)
    assert any("parser_revision" in failure for failure in failures)
    assert any("4" in warning for warning in validation_warnings(
        membership=summary, strict_pit=False, data_snapshot=rejected,
    ))


@pytest.mark.parametrize("mode", ["full", "compact"])
def test_explicit_mode_reaches_dataset_snapshot_without_changing_pit_omission(
        boundary_store, monkeypatch, mode):
    from src.backtest.application import asof_signals

    store, days = boundary_store
    calls = _observe_snapshot(monkeypatch, store)

    def dataset_signals(engine, panels, params, **kwargs):
        return engine.compute(panels, params).signals, {"id": kwargs["dataset_id"], "sha256": "c" * 64}

    monkeypatch.setattr(asof_signals, "compute_asof_signals", dataset_signals)
    context = runner.prepare_backtest_context(
        store, EvidenceBoundaryStrategy(), start=days[40], end=days[45], codes=["600001"],
        config=BacktestConfig(benchmark=None, signal_dataset="fixture-dataset"),
        source_evidence_mode=mode,
    )
    assert calls[0]["include_source_details"] is False
    assert calls[0].get("source_evidence_mode", "full") == mode
    assert context["data_snapshot"]["source_evidence"]["receipt_details_omitted"] is True
    assert context["data_snapshot"]["signal_dataset"]["id"] == "fixture-dataset"
