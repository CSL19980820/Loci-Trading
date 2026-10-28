"""回退源的真实性与通达信覆盖告警必须分别判断。"""
from datetime import datetime

import pytest

from src.market import MarketStore
from src.market.application.data_quality import (
    QualityThresholds,
    _check_authoritative,
    _check_fabricated,
    _check_last_day_authoritative,
    _check_watermarks,
    inspect_market_data,
)
from src.shared.postgres import _CompatRow


DAY = "2026-10-26"
AFTER_SETTLE = datetime.fromisoformat(f"{DAY}T16:30:00")


@pytest.fixture
def market(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        yield store


def add_bars(store, source, count=1, *, day=DAY, **values):
    offset = store.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0]
    codes = [f"{600000 + offset + i:06d}" for i in range(count)]
    bar = dict(high=11.0, low=9.0, close=10.0, volume=1000.0, amount=9800.0)
    bar.update(values)
    store.conn.executemany(
        "INSERT INTO quotes_daily(trade_date,code,high,low,close,volume,amount,"
        "source,receipt_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        [(day, code, *(bar[k] for k in ("high", "low", "close", "volume", "amount")),
          source, f"receipt-{code}", f"{day} 07:30:00") for code in codes],
    )
    store.conn.executemany(
        "INSERT INTO instruments(code,status,instrument_type,updated_at)"
        " VALUES(?,'normal','STOCK',?)",
        [(code, day) for code in codes],
    )
    store.conn.execute(
        "INSERT OR IGNORE INTO trading_calendar(trade_date,updated_at) VALUES(?,?)",
        (day, day),
    )
    return codes


def test_sina_close_keeps_global_authoritative_block_without_false_amount_claim():
    finding = _check_authoritative([("sina_close", 5578)], QualityThresholds())

    assert finding.level == "block"
    assert finding.observed["authoritative_rows"] == 0
    assert "sina_close" in finding.message
    assert "收盘快照" in finding.message
    assert "真实成交额" in finding.message
    assert "合成的假值" not in finding.message
    assert "scripts/resync_market_authoritative.py --no-force" in finding.remediation


def test_full_market_close_fallback_reports_source_failure_not_fabrication(market):
    codes = add_bars(market, "sina_close", 5578)
    market.conn.executemany(
        "INSERT INTO ingest_watermark(code,source,last_trade_date) VALUES(?,?,?)",
        [(code, "sina_close", DAY) for code in codes]
        + [(code, "tdx", DAY) for code in ("000300", "000905", "000852")],
    )
    market.conn.commit()
    market.conn.execute("PRAGMA query_only=ON")

    report = inspect_market_data(market, now=AFTER_SETTLE)
    findings = {item["key"]: item for item in report["findings"]}

    assert report["blocked"] is True
    assert findings["last_day_rows"]["level"] == "ok"
    last = findings["last_day_authoritative"]
    assert last["level"] == "warn"
    assert last["observed"]["settled_rows"] == 5578
    assert last["observed"]["authoritative_rows"] == 0
    assert last["observed"]["provisional_rows"] == 0
    assert "sina_close 5578 行" in last["message"]
    assert "真实成交额" in last["message"]
    assert "未定稿" not in last["message"]
    assert findings["fabricated_amount"]["observed"]["rows"] == 0
    watermark = findings["watermark_source"]
    assert watermark["level"] == "warn"
    assert watermark["observed"]["non_authoritative"] == 5578
    assert watermark["observed"]["unexplained_count"] == 5578
    assert watermark["observed"]["sources"] == [("sina_close", 5578)]
    assert len(watermark["observed"]["unexplained"]) == 10
    assert "--lanes hist_daily" in watermark["remediation"]
    assert "scripts/resync_market_authoritative.py --no-force" in watermark["remediation"]
    assert "逐票" not in watermark["remediation"]
    assert "合成的假值" not in report["alert"]


def test_health_report_reads_postgres_mapping_rows_as_values(market):
    code = add_bars(market, "tencent", amount=10_000.0)[0]
    market.conn.execute(
        "INSERT INTO ingest_watermark(code,source,last_trade_date) VALUES(?,?,?)",
        (code, "sina_close", DAY),
    )
    market.conn.commit()
    sqlite_conn = market.conn

    class PostgresRows:
        def execute(self, sql, params=()):
            cursor = sqlite_conn.execute(sql, params)
            names = tuple(column[0] for column in cursor.description)
            rows = [_CompatRow(tuple(row), names) for row in cursor.fetchall()]
            return type("Cursor", (), {"fetchone": lambda self: rows[0] if rows else None,
                                      "fetchall": lambda self: rows})()

    market.conn = PostgresRows()
    try:
        report = inspect_market_data(market, now=AFTER_SETTLE)
    finally:
        market.conn = sqlite_conn

    findings = {item["key"]: item for item in report["findings"]}
    assert findings["authoritative_ratio"]["observed"]["top_sources"] == [("tencent", 1)]
    assert findings["fabricated_amount"]["observed"]["sources"] == [("tencent", 1)]
    assert findings["watermark_source"]["observed"]["unexplained"][0][0] == code


def test_mixed_fallbacks_report_actual_sources_and_synthesis_evidence(market):
    add_bars(market, "sina_close", 3)
    add_bars(market, "tencent", 2, amount=10_000.0)
    add_bars(market, "other_feed", amount=10_000.0)

    last = _check_last_day_authoritative(market, QualityThresholds(), AFTER_SETTLE)
    fabricated = _check_fabricated(market, QualityThresholds(max_fabricated_rows=1))

    assert last.level == "warn"
    for source in ("sina_close", "tencent", "other_feed"):
        assert source in last.message
    assert "合成的假值" not in last.message
    assert fabricated.level == "warn"
    assert fabricated.observed["rows"] == 2
    assert fabricated.observed["sources"] == [("tencent", 2)]
    assert "tencent 2 行" in fabricated.message
    assert "sina_close" not in fabricated.message


@pytest.mark.parametrize("source,expected", [
    ("sina_close", 0), ("sina", 0), ("tdx", 0), ("baostock", 0),
    ("other_feed", 0), ("tencent", 1), ("tencent_spot", 1),
])
def test_amount_equality_requires_known_fabricating_source(market, source, expected):
    add_bars(market, source, amount=10_000.0)

    finding = _check_fabricated(market, QualityThresholds(max_fabricated_rows=0))

    assert finding.observed["rows"] == expected
    assert finding.level == ("warn" if expected else "ok")


@pytest.mark.parametrize("values", [
    dict(high=10.0, low=10.0, amount=10_000.0),
    dict(volume=0.0, amount=0.0),
    dict(close=0.0, amount=0.0),
    dict(amount=None),
    dict(amount=9800.0),
])
def test_tencent_synthesis_still_requires_row_evidence(market, values):
    add_bars(market, "tencent", **values)

    finding = _check_fabricated(market, QualityThresholds(max_fabricated_rows=0))

    assert finding.level == "ok"
    assert finding.observed["rows"] == 0


@pytest.mark.parametrize("source", ["tdx_spot", "tencent_spot", "sina_spot"])
@pytest.mark.parametrize("stamp,level", [
    (f"{DAY}T11:00:00", "ok"),
    (f"{DAY}T16:00:00", "warn"),
    ("2026-10-27T09:00:00", "warn"),
])
def test_spot_exclusion_and_settle_deadline_are_preserved(market, source, stamp, level):
    add_bars(market, source, 2)

    finding = _check_last_day_authoritative(
        market, QualityThresholds(), datetime.fromisoformat(stamp),
    )

    assert finding.level == level
    assert finding.observed["settled_rows"] == 0
    assert finding.observed["authoritative_rows"] == 0
    assert finding.observed["provisional_rows"] == 2
    assert finding.observed["ratio"] is None
    assert "合成的假值" not in finding.message
    if level == "warn":
        assert source in finding.message
        assert "hist_daily" in finding.remediation


def test_tdx_spot_cannot_raise_settled_authoritative_ratio(market):
    add_bars(market, "tdx_spot", 4)
    add_bars(market, "sina_close", 6)

    finding = _check_last_day_authoritative(market, QualityThresholds(), AFTER_SETTLE)

    assert finding.level == "warn"
    assert finding.observed["settled_rows"] == 6
    assert finding.observed["provisional_authoritative_rows"] == 4
    assert finding.observed["ratio"] == 0.0


@pytest.mark.parametrize("tdx_rows,level", [(9, "ok"), (8, "warn")])
def test_last_day_authoritative_threshold_stays_at_ninety_percent(market, tdx_rows, level):
    add_bars(market, "tdx", tdx_rows)
    add_bars(market, "sina_close", 10 - tdx_rows)

    finding = _check_last_day_authoritative(market, QualityThresholds(), AFTER_SETTLE)

    assert finding.level == level
    assert finding.observed["limit"] == 0.90


@pytest.mark.parametrize("tdx_rows,level", [(95, "ok"), (94, "block")])
def test_global_authoritative_threshold_stays_at_ninety_five_percent(tdx_rows, level):
    finding = _check_authoritative(
        [("tdx", tdx_rows), ("sina_close", 100 - tdx_rows)], QualityThresholds(),
    )

    assert finding.level == level


def test_delisted_and_suspended_watermarks_keep_existing_exemption(market):
    codes = add_bars(market, "sina_close", 2)
    market.conn.executemany(
        "UPDATE instruments SET status=? WHERE code=?",
        [("delisted", codes[0]), ("suspended", codes[1])],
    )
    market.conn.executemany(
        "INSERT INTO ingest_watermark(code,source) VALUES(?,'sina_close')",
        [(code,) for code in codes],
    )

    finding = _check_watermarks(market)

    assert finding.level == "ok"
    assert finding.observed["non_authoritative"] == 2
