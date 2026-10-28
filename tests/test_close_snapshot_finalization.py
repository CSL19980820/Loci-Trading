"""通达信整体失败时，收盘快照仍须形成可核验的正式日 K。"""
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from src.market import MarketStore
from src.market.application.screen_spot import ensure_closed_day_finalized
from src.market.infrastructure import sina, sync_close

DAY = "2026-10-20"
CODES = ("002173", "002246")


def hq_line(symbol: str, name: str, previous: float, close: float, volume: float) -> str:
    fields = ["0"] * 32
    fields[:9] = [
        name,
        "0",
        str(previous),
        str(close),
        str(close),
        str(close),
        "0",
        "0",
        str(volume),
    ]
    fields[9] = "0"
    fields[30:] = [DAY, "15:00:00"]
    return f'var hq_str_{symbol}="{",".join(fields)}";'


def test_sina_close_snapshot_keeps_explicit_zero_volume_rows(monkeypatch):
    monkeypatch.setattr(
        sina,
        "_get",
        lambda *_args, **_kwargs: hq_line("sz002246", "北化股份", 24.98, 0, 0),
    )
    assert sina.fetch_spot(["sz002246"]).empty

    frame = sina.fetch_spot(["sz002246"], include_no_trade=True)

    assert frame.to_dict("records") == [
        {
            "symbol": "sz002246",
            "date": pd.Timestamp(DAY).date(),
            "open": 24.98,
            "high": 24.98,
            "low": 24.98,
            "close": 24.98,
            "volume": 0.0,
            "amount": 0.0,
        }
    ]


@pytest.fixture
def market(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        store.upsert_instruments(
            [
                {
                    "code": code,
                    "name": name,
                    "market": "sz",
                    "board": "main",
                    "instrument_type": "STOCK",
                    "list_date": "2000-01-01",
                }
                for code, name in zip(CODES, ("创新医疗", "北化股份"), strict=True)
            ]
        )
        yield store


def test_close_snapshot_writes_formal_hist_daily_receipts(market, monkeypatch):
    frame = pd.DataFrame(
        [
            {
                "code": "002173",
                "date": DAY,
                "open": 16.4,
                "high": 16.6,
                "low": 16.3,
                "close": 16.49,
                "volume": 1_000_000.0,
                "amount": 16_490_000.0,
            },
            {
                "code": "002246",
                "date": DAY,
                "open": 24.98,
                "high": 24.98,
                "low": 24.98,
                "close": 24.98,
                "volume": 0.0,
                "amount": 0.0,
            },
        ]
    )
    adapter = SimpleNamespace(
        meta=SimpleNamespace(base_url="https://finance.sina.com.cn"),
        fetch_spot_close=lambda *_args, **_kwargs: frame,
    )
    monkeypatch.setattr(sync_close, "get_adapter", lambda _adapter_id: adapter)
    monkeypatch.setattr(sync_close, "lane_provider_enabled", lambda *_args, **_kwargs: True)

    result = sync_close.finalize_close_snapshot(
        market,
        CODES,
        trade_date=DAY,
        now=datetime.fromisoformat(f"{DAY}T15:30:00+08:00"),
    )

    assert result["status"] == "ok"
    assert result["succeeded"] == 2
    assert result["no_trade_codes"] == ["002246"]
    assert result["rows_written"] == 2
    finalization = ensure_closed_day_finalized(
        market, DAY, now=datetime.fromisoformat(f"{DAY}T15:30:00+08:00")
    )
    assert finalization["finalized"] == finalization["required"] == 2
    rows = market.conn.execute(
        "SELECT q.code, q.source, q.volume, r.state, r.coverage_json "
        "FROM quotes_daily q JOIN source_route_receipts r ON r.receipt_id=q.receipt_id "
        "WHERE q.trade_date=? ORDER BY q.code",
        (DAY,),
    ).fetchall()
    assert [(row[0], row[1], row[2], row[3]) for row in rows] == [
        ("002173", "sina_close", 1_000_000.0, "selected"),
        ("002246", "sina_close", 0.0, "selected"),
    ]
    assert '"close_snapshot": true' in rows[0][4]
    assert '"no_trade": true' in rows[1][4]


def test_rejects_close_snapshot_before_market_close(market, monkeypatch):
    monkeypatch.setattr(sync_close, "lane_provider_enabled", lambda *_args, **_kwargs: True)
    with pytest.raises(sync_close.CloseSnapshotError, match="尚未收盘"):
        sync_close.finalize_close_snapshot(
            market,
            CODES,
            trade_date=DAY,
            now=datetime.fromisoformat(f"{DAY}T14:59:59+08:00"),
        )


@pytest.mark.parametrize(
    ("finalized_codes", "expected_status", "expected_failed"),
    [(["002173", "002246"], "ok", 0), (["002173"], "failed", 1)],
)
def test_eod_finalize_uses_close_snapshot_only_for_tdx_failures(
    monkeypatch, finalized_codes, expected_status, expected_failed, tmp_path
):
    from src.market.infrastructure.sync import SyncReport
    from src.ops.application.jobs.context import JobContext
    from src.ops.application.jobs.sync import _finalize_today_with_authoritative

    report = SyncReport(
        total=2,
        succeeded=0,
        failed=2,
        unresolved_codes=["002173", "002246"],
    )
    monkeypatch.setattr("src.market.sync_quotes", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(
        sync_close,
        "finalize_close_snapshot",
        lambda *_args, **_kwargs: {
            "status": "ok" if len(finalized_codes) == 2 else "failed",
            "source": "sina_close",
            "succeeded": len(finalized_codes),
            "failed": 2 - len(finalized_codes),
            "rows_written": len(finalized_codes),
            "finalized_codes": finalized_codes,
            "failed_codes": [code for code in CODES if code not in finalized_codes],
        },
    )
    context = JobContext(market_db=str(tmp_path / "market.db"))

    result = _finalize_today_with_authoritative(
        {}, context, codes=list(CODES), types={}, progress=None
    )

    assert result["status"] == expected_status
    assert result["failed"] == expected_failed
    assert result["succeeded"] == len(finalized_codes)
    assert result["fallback"]["source"] == "sina_close"
