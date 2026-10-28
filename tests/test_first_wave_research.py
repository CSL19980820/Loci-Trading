from __future__ import annotations

import json
import sqlite3

import pytest

from scripts.first_wave_research import load_minutes, load_panels, metrics


def test_entire_stored_universe_is_retained_without_current_status_filter():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE instruments(code TEXT,name TEXT,instrument_type TEXT,list_date TEXT,status TEXT);
        CREATE TABLE quotes_daily(trade_date TEXT,code TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL);
        CREATE TABLE adjust_factors(code TEXT,trade_date TEXT,hfq_factor REAL);
        INSERT INTO instruments VALUES('600001','old','STOCK','1990-01-01','delisted');
        INSERT INTO instruments VALUES('600002','new','STOCK','2026-01-01','normal');
        INSERT INTO instruments VALUES('000300','index','INDEX','1990-01-01','normal');
        INSERT INTO quotes_daily VALUES('1995-01-03','600001',10,11,9,10,100);
        INSERT INTO quotes_daily VALUES('1995-01-03','600002',10,11,9,10,100);
        INSERT INTO quotes_daily VALUES('1995-01-03','600003',10,9,8,10,100);
        INSERT INTO quotes_daily VALUES('1995-01-03','000300',10,11,9,10,100);
        INSERT INTO adjust_factors VALUES('600001','1900-01-01',1);
    """)
    dates, codes, panels, audit = load_panels(con)
    assert dates == ['1995-01-03']
    assert codes == ['600001', '600002', '600003']
    assert panels['close'][0, 0] == 10
    assert audit['prelisting_rows'] == 1
    assert audit['invalid_rows'] == 1
    assert audit['unknown_instrument_codes'] == ['600003']


def minute_connection():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE intel_snapshots(trade_date TEXT,payload_json TEXT,fetched_at TEXT,tool TEXT)")
    return con


def test_minute_overlay_accepts_only_its_actual_requested_day_and_keeps_failed_probe(tmp_path):
    base = {'tool': 'minute_data', 'trade_date': '2026-10-16', 'fetched_at': '2026-10-26T16:00:00+00:00',
            'arguments': {'code': '002813'}, 'structured': {'stock': {'code': '002813'}, 'points': [
                {'time': '2026-10-16 14:50', 'open': 10, 'high': 11, 'low': 9, 'close': 10, 'volume': 100}]}}
    (tmp_path / 'valid.json').write_text(json.dumps(base), encoding='utf-8')
    (tmp_path / 'failed.json').write_text(json.dumps({**base, 'is_error': True}), encoding='utf-8')
    mismatch = {**base, 'metadata': {'actualTradeDate': '20261026'}}
    (tmp_path / 'mismatch.json').write_text(json.dumps(mismatch), encoding='utf-8')
    minutes, audit = load_minutes(minute_connection(), tmp_path)
    assert list(minutes) == ['002813']
    assert list(minutes['002813']) == ['2026-10-16']
    assert audit['date_mismatch'] == 1
    assert audit['rejected_error_or_truncated'] == 1
    assert len(audit['overlay_hashes']) == 3


def test_missing_or_unfinished_opportunities_are_counted_without_becoming_wins():
    rows = [
        {'status': 'closed', 'signal_date': '2024-01-02', 'net_return_pct': 2, 'exit_reason': 'horizon', 'legs': [{}]},
        {'status': 'closed', 'signal_date': '2024-01-03', 'net_return_pct': -1, 'exit_reason': 'ma5_break', 'legs': [{}]},
        {'status': 'data_end', 'signal_date': '2024-01-03', 'net_return_pct': 99, 'exit_reason': 'data_end'},
        {'status': 'unverifiable', 'signal_date': '2024-01-03', 'net_return_pct': None},
        {'status': 'skipped', 'signal_date': '2024-01-03', 'net_return_pct': 0},
    ]
    result = metrics(rows)
    assert result['opportunities'] == 5
    assert result['realized_trades'] == 2
    assert result['mean_net_pct'] == pytest.approx(0.5)
    assert result['win_rate_pct'] == 50
    assert result['profit_factor'] == 2
    assert result['status_counts']['data_end'] == 1
