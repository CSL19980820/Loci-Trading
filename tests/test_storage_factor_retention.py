"""行情截断后，稀疏累计复权因子必须保留每股最后已知的历史锚点。"""
from __future__ import annotations

import pandas as pd
import pytest

from src.market import MarketStore
from src.market.application.storage_governance import StoragePolicy, run_storage_maintenance


@pytest.fixture
def factor_store(tmp_path):
    path = tmp_path / "market.db"
    with MarketStore(path) as store:
        store.upsert_adjust_factors(
            "000001", pd.DataFrame({"date": ["1900-01-01", "2020-01-01", "2022-12-01",
                                              "2023-01-01", "2023-06-01", "2026-09-30"],
                                   "hfq_factor": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]}), source="fixture",
        )
        store.upsert_adjust_factors(
            "000002", pd.DataFrame({"date": ["2010-01-01"], "hfq_factor": [6.0]}), source="fixture",
        )
        store.upsert_adjust_factors(
            "000003", pd.DataFrame({"date": ["2024-01-01"], "hfq_factor": [5.0]}), source="fixture",
        )
        store.upsert_adjust_factors(
            "000004", pd.DataFrame({"date": ["2020-01-01", "2022-01-01"], "hfq_factor": [10.0, 11.0]}),
            source="fixture",
        )
    return path


def _rows(path):
    with MarketStore(path) as store:
        return [tuple(row) for row in store.conn.execute(
            "SELECT code, trade_date, hfq_factor FROM adjust_factors ORDER BY code, trade_date",
        )]


def test_dry_run_counts_only_expired_factors_without_changing_any_rows(factor_store):
    before = _rows(factor_store)
    report = run_storage_maintenance(factor_store, policy=StoragePolicy(batch_size=1),
                                     vacuum=False, dry_run=True)
    assert report["errors"] == []
    assert report["deleted"]["adjust_factors"] == 3
    assert _rows(factor_store) == before


def test_apply_preserves_each_pre_floor_anchor_and_all_factors_from_floor_onward(factor_store):
    report = run_storage_maintenance(factor_store, policy=StoragePolicy(batch_size=1), vacuum=False)
    assert report["errors"] == []
    assert report["integrity"] == "ok"
    assert report["deleted"]["adjust_factors"] == 3
    assert _rows(factor_store) == [
        ("000001", "2022-12-01", 2.0), ("000001", "2023-01-01", 2.5),
        ("000001", "2023-06-01", 3.0), ("000001", "2026-09-30", 4.0),
        ("000002", "2010-01-01", 6.0), ("000003", "2024-01-01", 5.0),
        ("000004", "2022-01-01", 11.0),
    ]
    second = run_storage_maintenance(factor_store, policy=StoragePolicy(batch_size=1), vacuum=False)
    assert second["errors"] == []
    assert second["deleted"]["adjust_factors"] == 0


def test_maintenance_preserves_generic_hfq_and_qfq_panel_adjustment(factor_store):
    reference = pd.DataFrame(10.0, index=["2023-01-03", "2023-06-02", "2024-01-02"],
                             columns=["000001", "000002", "000003", "000004", "000005"])
    with MarketStore(factor_store) as store:
        before = {adjust: store._factor_panel(reference, adjust) for adjust in ("hfq", "qfq")}
    run_storage_maintenance(factor_store, policy=StoragePolicy(batch_size=1), vacuum=False)
    with MarketStore(factor_store) as store:
        after = {adjust: store._factor_panel(reference, adjust) for adjust in ("hfq", "qfq")}
    for adjust in before:
        pd.testing.assert_frame_equal(after[adjust], before[adjust], check_exact=True)
    assert after["hfq"].loc["2023-01-03", "000001"] == 2.5
    assert after["hfq"].loc["2023-01-03", "000002"] == 6.0
    assert after["hfq"].loc["2023-01-03", "000004"] == 11.0
    assert after["qfq"].loc["2023-01-03", "000001"] == 2.5 / 3.0
    assert (after["hfq"]["000005"] == 1.0).all()


def test_empty_factor_table_is_a_safe_idempotent_noop(tmp_path):
    path = tmp_path / "market.db"
    with MarketStore(path):
        pass
    report = run_storage_maintenance(path, vacuum=False)
    assert report["errors"] == []
    assert report["deleted"]["adjust_factors"] == 0


LEGACY_FACTOR_TRIGGER = (
    "CREATE TRIGGER adjust_factors_floor BEFORE INSERT ON adjust_factors "
    "WHEN NEW.trade_date < '2023-01-01' BEGIN SELECT RAISE(IGNORE); END"
)
QUOTE_FLOOR_TRIGGER = (
    "CREATE TRIGGER quotes_daily_floor BEFORE INSERT ON quotes_daily "
    "WHEN NEW.trade_date < '2023-01-01' BEGIN SELECT RAISE(IGNORE); END"
)


def _triggers(path):
    with MarketStore(path) as store:
        return {row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}


def test_dry_run_reports_known_legacy_factor_trigger_without_removing_it(factor_store):
    with MarketStore(factor_store) as store:
        store.conn.execute(LEGACY_FACTOR_TRIGGER)
        store.conn.execute(QUOTE_FLOOR_TRIGGER)
    report = run_storage_maintenance(factor_store, vacuum=False, dry_run=True)
    assert report["errors"] == []
    assert report["factor_floor_trigger"] == {
        "name": "adjust_factors_floor", "present": True, "recognized": True, "removed": False,
    }
    assert _triggers(factor_store) == {"adjust_factors_floor", "quotes_daily_floor"}


def test_apply_removes_only_known_legacy_factor_trigger_and_allows_true_past_anchor(factor_store):
    frame = pd.DataFrame({"date": ["2022-12-30"], "hfq_factor": [7.0]})
    with MarketStore(factor_store) as store:
        store.conn.execute(LEGACY_FACTOR_TRIGGER)
        store.conn.execute(QUOTE_FLOOR_TRIGGER)
        store.upsert_adjust_factors("000005", frame, source="fixture")
        assert store.conn.execute("SELECT COUNT(*) FROM adjust_factors WHERE code='000005'").fetchone()[0] == 0
    report = run_storage_maintenance(factor_store, policy=StoragePolicy(batch_size=1), vacuum=False)
    assert report["errors"] == []
    assert report["factor_floor_trigger"]["removed"] is True
    assert _triggers(factor_store) == {"quotes_daily_floor"}
    with MarketStore(factor_store) as store:
        store.upsert_adjust_factors("000005", frame, source="fixture")
        assert store.conn.execute("SELECT hfq_factor FROM adjust_factors WHERE code='000005'").fetchone()[0] == 7.0
        store.conn.execute(
            "INSERT INTO quotes_daily(trade_date,code,close,source,fetched_at) "
            "VALUES ('2022-12-30','000005',10,'fixture','2026-09-30')",
        )
        store.conn.commit()
        assert store.conn.execute("SELECT COUNT(*) FROM quotes_daily WHERE code='000005'").fetchone()[0] == 0
    second = run_storage_maintenance(factor_store, vacuum=False)
    assert second["errors"] == []
    assert second["factor_floor_trigger"]["present"] is False


@pytest.mark.parametrize("different_definition", [
    LEGACY_FACTOR_TRIGGER.replace("2023-01-01", "2024-01-01"),
    LEGACY_FACTOR_TRIGGER.replace("RAISE(IGNORE)", "RAISE(ABORT, 'user protection')"),
])
def test_unknown_same_named_trigger_is_preserved_and_maintenance_stops(factor_store, different_definition):
    before = _rows(factor_store)
    with MarketStore(factor_store) as store:
        store.conn.execute(different_definition)
        store.conn.execute(QUOTE_FLOOR_TRIGGER)
    report = run_storage_maintenance(factor_store, vacuum=False)
    assert report["errors"] and "与已知旧定义不同" in report["errors"][0]
    assert report["factor_floor_trigger"]["present"] is True
    assert report["factor_floor_trigger"]["recognized"] is False
    assert report["factor_floor_trigger"]["removed"] is False
    assert _triggers(factor_store) == {"adjust_factors_floor", "quotes_daily_floor"}
    assert _rows(factor_store) == before
