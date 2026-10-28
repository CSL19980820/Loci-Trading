"""Exercise the reviewed repair and rollback with synthetic, isolated data."""
from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

import pandas as pd
import pytest

from src.market.infrastructure.store import MarketStore
from tools import repair_market_20261027 as repair


class Cursor:
    def __init__(self, conn: sqlite3.Connection):
        self.raw = conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.raw.close()

    def execute(self, sql, params=()):
        sql = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        if sql == repair.BUMP_REVISION.replace("%s", "?"):
            sql = ("UPDATE market.meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT), "
                   "updated_at=CURRENT_TIMESTAMP WHERE key=?")
        self.raw.execute(sql, params)
        self.rowcount = self.raw.rowcount
        return self

    def fetchone(self):
        return self.raw.fetchone()

    def fetchall(self):
        return self.raw.fetchall()


class IsolatedDB:
    def __init__(self, plan):
        self.raw = sqlite3.connect(":memory:", isolation_level=None)
        self.raw.row_factory = sqlite3.Row
        self.raw.execute("ATTACH DATABASE ':memory:' AS market")
        self.raw.executescript("""
            CREATE TABLE market.quotes_daily(
              trade_date TEXT, code TEXT, open REAL, high REAL, low REAL, close REAL,
              volume REAL, amount REAL, outstanding_share REAL, turnover REAL,
              source TEXT, receipt_id TEXT, fetched_at TEXT,
              PRIMARY KEY(trade_date,code));
            CREATE TABLE market.adjust_factors(
              code TEXT, trade_date TEXT, hfq_factor REAL, source TEXT, fetched_at TEXT,
              PRIMARY KEY(code,trade_date));
            CREATE TABLE market.meta(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
        """)
        for item in plan["quotes"]:
            self.raw.execute(
                "INSERT INTO market.quotes_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(item["before"][key] for key in repair.QUOTE_COLUMNS),
            )
        self.raw.executemany("INSERT INTO market.meta VALUES (?, '1', '')", [
            ("market_revision",), ("quotes_revision",), ("adjust_factors_revision",),
        ])

    @contextmanager
    def transaction(self):
        self.raw.execute("BEGIN")
        try:
            yield
        except Exception:
            self.raw.rollback()
            raise
        else:
            self.raw.commit()

    def cursor(self, **_kwargs):
        return Cursor(self.raw)

    def state(self, plan):
        with self.cursor() as cur:
            rows, factors = repair.read_state(cur, plan)
        return repair.state_label(rows, factors, plan)


@pytest.fixture
def plan():
    sentinel = 2.0 ** -127
    codes = ["688496", *(f"600{i:03d}" for i in range(343))]
    quotes = []
    for code in codes:
        before = {
            "trade_date": "2026-10-27", "code": code,
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0,
            "volume": sentinel * 100, "amount": sentinel, "outstanding_share": None,
            "turnover": None, "source": "tdx", "receipt_id": "fixture",
            "fetched_at": "2026-10-27T15:00:00Z",
        }
        quotes.append({"before": before, "after": {"volume": 0.0, "amount": 0.0, "turnover": 0.0}})
    for trade_date, turnover in (("2026-10-26", 0.0158), ("2026-10-27", 0.0344)):
        before = {
            **quotes[0]["before"], "trade_date": trade_date, "code": "689009",
            "volume": 1000.0, "amount": 10000.0,
        }
        quotes.append({"before": before, "after": {"volume": 1000.0, "amount": 10000.0, "turnover": turnover}})
    values = (
        ("2023-10-27", 1.0),
        ("2024-05-24", 1.0070440251572328),
        ("2025-06-13", 1.0260224755724456),
        ("2025-10-31", 1.0332516223555428),
        ("2026-08-07", 1.063714816634754),
    )
    factors = [
        {"code": "689009", "trade_date": day, "hfq_factor": value,
         "source": "exchange_reference_derived", "fetched_at": "fixture"}
        for day, value in values
    ]
    events = [
        {"ex_date": current[0], "prior_close": 10.0, "reference": 10.0 * previous[1] / current[1]}
        for previous, current in zip(values, values[1:])
    ]
    return {"version": "market-repair-20261027-v2", "quotes": quotes,
            "factors": factors, "factor_events": events}


def test_apply_then_rollback_restores_original_values_and_bumps_revisions(plan, tmp_path):
    db = IsolatedDB(plan)
    backup = tmp_path / "before.json"
    assert db.state(plan) == "before"
    repair.change(db, plan, apply=True, backup_path=backup, plan_sha256="test-digest")
    assert db.state(plan) == "after"
    saved = json.loads(backup.read_text(encoding="utf-8"))
    assert saved["plan"] == plan
    assert saved["plan_sha256"] == "test-digest"
    repair.change(db, saved["plan"], apply=False)
    assert db.state(plan) == "before"
    assert [row[0] for row in db.raw.execute("SELECT value FROM market.meta ORDER BY key")] == ["3"] * 3


def test_quote_only_repair_preserves_factors_and_their_revision(plan, tmp_path):
    plan["factors"] = []
    db = IsolatedDB(plan)
    db.raw.execute("INSERT INTO market.adjust_factors VALUES ('689009','2026-08-07',1.2,'existing','now')")
    repair.change(db, plan, apply=True, backup_path=tmp_path / "before.json")
    assert db.state(plan) == "after"
    repair.change(db, plan, apply=False)
    assert db.state(plan) == "before"
    assert db.raw.execute("SELECT hfq_factor,source FROM market.adjust_factors").fetchone()[:] == (1.2, "existing")
    assert db.raw.execute("SELECT value FROM market.meta WHERE key='adjust_factors_revision'").fetchone()[0] == "1"


def test_changed_before_image_aborts_without_backup_or_other_changes(plan, tmp_path):
    db = IsolatedDB(plan)
    db.raw.execute("UPDATE market.quotes_daily SET turnover=0.02 WHERE code='689009' AND trade_date='2026-10-27'")
    with pytest.raises(RuntimeError, match="found conflict"):
        repair.change(db, plan, apply=True, backup_path=tmp_path / "before.json")
    assert not (tmp_path / "before.json").exists()
    assert db.raw.execute("SELECT count(*) FROM market.adjust_factors").fetchone()[0] == 0


def test_failure_rolls_back_all_rows_and_keeps_backup(plan, tmp_path):
    db = IsolatedDB(plan)
    db.raw.execute("DELETE FROM market.meta WHERE key='quotes_revision'")
    backup = tmp_path / "before.json"
    with pytest.raises(RuntimeError, match="missing market revision"):
        repair.change(db, plan, apply=True, backup_path=backup)
    assert backup.exists()
    assert db.state(plan) == "before"
    with pytest.raises(FileExistsError):
        repair.change(db, plan, apply=True, backup_path=backup)
    assert db.state(plan) == "before"


def test_rollback_refuses_to_overwrite_later_updates(plan, tmp_path):
    db = IsolatedDB(plan)
    repair.change(db, plan, apply=True, backup_path=tmp_path / "before.json")
    db.raw.execute("UPDATE market.quotes_daily SET volume=100 WHERE code='688496' AND trade_date='2026-10-27'")
    with pytest.raises(RuntimeError, match="found conflict"):
        repair.change(db, plan, apply=False)
    assert db.raw.execute("SELECT count(*) FROM market.adjust_factors").fetchone()[0] == 5
    assert db.raw.execute("SELECT volume FROM market.quotes_daily WHERE code='688496' AND trade_date='2026-10-27'").fetchone()[0] == 100


def test_unreviewed_factor_is_rejected(plan):
    invalid = copy.deepcopy(plan)
    invalid["factors"][-1]["hfq_factor"] = 1.0
    with pytest.raises(ValueError, match="invalid factor row"):
        repair.validate_plan(invalid)


def test_prepared_factors_produce_reported_ex_right_reference_prices(plan, tmp_path):
    events = plan["factor_events"]
    days = sorted({day for event in events for day in (
        event["ex_date"],
        (date.fromisoformat(event["ex_date"]) - timedelta(days=1)).isoformat(),
    )})
    with MarketStore(tmp_path / "market.db") as store:
        store.upsert_adjust_factors("689009", pd.DataFrame(plan["factors"]), source="test")
        ratio = store._factor_panel(pd.DataFrame(1.0, index=days, columns=["689009"]), "qfq")
        for event in events:
            previous = (date.fromisoformat(event["ex_date"]) - timedelta(days=1)).isoformat()
            adjusted_previous = event["prior_close"] * ratio.loc[previous, "689009"]
            ex_day_reference = event["reference"] * ratio.loc[event["ex_date"], "689009"]
            assert adjusted_previous == pytest.approx(ex_day_reference, abs=1e-10)
