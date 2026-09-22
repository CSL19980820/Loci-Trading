"""Bounded, read-only, snapshot-consistent financial evidence for holding charts."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from contextlib import closing
from pathlib import Path

from src.shared.paths import palace_db
from src.ledger.domain.guardian_account import new_guardian_account
from src.ledger.domain.guardian_curve import curve_snapshot, TZ


def load_guardian_curve_evidence(*, days: int = 30, now: datetime | None = None,
                                 db_path: str | Path | None = None) -> dict:
    if type(days) is not int or not 1 <= days <= 366:
        raise ValueError('曲线查询范围为1至366天')
    now = now or datetime.now(TZ)
    start = (now - timedelta(days=days)).date().isoformat()
    path = Path(db_path or palace_db()).resolve()
    empty = {'state': new_guardian_account(), 'trades': [], 'snapshots': [],
             'coverage': {'missing_snapshots': 0, 'truncated': False}}
    if not path.is_file():
        return empty
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'guardian_portfolio' not in tables:
            return empty
        record = con.execute('SELECT state_json FROM guardian_portfolio WHERE id=1').fetchone()
        if not record:
            return empty
        state = json.loads(record[0])
        trades = con.execute('SELECT id,detail_json FROM guardian_trades ORDER BY occurred_at,id LIMIT 50001').fetchall()
        if len(trades) > 50000:
            raise ValueError('账本超过单次核对上限，不能截断成交流水计算回撤')
        # Projection avoids reading prompts, tool receipts or model reasoning into Python.
        rows = con.execute("""SELECT slot,
            COALESCE(json_extract(result_json,'$.curve_snapshot'),
                     json_extract(result_json,'$.decision_context.account_before')) AS snapshot,
            COALESCE(json_extract(result_json,'$.curve_account'),
                     json_extract(result_json,'$.account')) AS account
            FROM (SELECT slot,result_json FROM guardian_cycles WHERE slot>=?
                  ORDER BY slot DESC LIMIT 5001) ORDER BY slot""", (start,)).fetchall()
        truncated = len(rows) > 5000
        rows = rows[-5000:]
        snapshots, missing = [], 0
        for row in rows:
            found = False
            for key in ('snapshot', 'account'):
                item = curve_snapshot(json.loads(row[key])) if row[key] else None
                if item and item.get('valuation_at'):
                    snapshots.append({'state': item, 'source': f"{key}:{row['slot']}"})
                    found = True
            if not found:
                missing += 1
        # Completed daily reports may supply genuine recorded closes before the
        # retained intraday window, never reconstructed future prices.
        if 'guardian_reports' in tables:
            for row in con.execute("""SELECT report_key,json_extract(result_json,'$.facts.account') AS account
                  FROM guardian_reports WHERE period='daily' AND status='success'
                  AND trade_date>=? ORDER BY trade_date""", (start,)):
                item = curve_snapshot(json.loads(row['account'])) if row['account'] else None
                if item:
                    snapshots.append({'state': item, 'source': row['report_key']})
        return {'state': state, 'trades': [{**json.loads(r['detail_json']), 'id': r['id']} for r in trades],
                'snapshots': snapshots, 'coverage': {'missing_snapshots': missing, 'truncated': truncated}}
