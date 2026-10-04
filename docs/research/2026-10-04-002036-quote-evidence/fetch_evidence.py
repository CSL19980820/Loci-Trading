"""Single-symbol read-only evidence request through two existing native sources.

Run under tools/isolated_check.py so adapter caches cannot touch application data.
No source router, synchronization, quote writes, account access or return labels.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from zoneinfo import ZoneInfo

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
CODE, START, END = "002036", "2026-07-22", "2026-07-29"
DBS = [ROOT/".local/chinext-payoff-20261004/market.db", ROOT/".local/multi-strategy-scoring-20261004/market.db"]


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def run(source):
    target = HERE/f"{source}-receipt.json"
    if target.exists():
        raise FileExistsError("Preserve first source attempt; do not issue repeated requests")
    before = {str(p.relative_to(ROOT)): sha(p) for p in DBS}
    if not (HERE/"original-frozen-quotes.json").exists():
        original = {}
        for db in DBS:
            with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT trade_date,code,open,high,low,close,volume,amount,source,fetched_at FROM quotes_daily WHERE code=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date", (CODE, START, END)).fetchall()
                original[str(db.relative_to(ROOT))] = [dict(row) for row in rows]
        write(HERE/"original-frozen-quotes.json", dict(captured_at=now(), snapshot_sha256=before, rows=original))
    receipt = dict(source=source, code=CODE, requested_window=[START, END], started_at=now(),
        prices="unadjusted yuan/share", volume="shares", amount="yuan", trade_status_field=None,
        mutable_adapter_paths="isolated_check temporary directory", no_database_writes=True,
        no_candidate_or_return_calculation=True, snapshots_before_sha256=before)
    try:
        if source == "tdx":
            from src.market.infrastructure.adapters.tdx_adapter import TdxAdapter
            from src.market.infrastructure.tdx_daily import current_server
            frame = TdxAdapter().fetch_daily_window(CODE, instrument_type="STOCK", bars=90)
            receipt.update(native_call="TdxAdapter.fetch_daily_window(code, instrument_type=STOCK, bars=90)",
                endpoint=f"tdx://{current_server()}", unit_basis="tdx_daily._rows_to_frame: vol in lots times100; amount unchanged yuan",
                source_code_sha256={p: sha(ROOT/p) for p in ("src/market/infrastructure/adapters/tdx_adapter.py", "src/market/infrastructure/tdx_daily.py")})
        else:
            from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
            frame = SinaAdapter().fetch_daily(CODE, instrument_type="STOCK")
            receipt.update(native_call="SinaAdapter.fetch_daily(code, instrument_type=STOCK)",
                endpoint="https://finance.sina.com.cn/realstock/company/sz002036/hisdata_klc2/klc_kl.js",
                unit_basis="Sina native English volume/amount columns use DAILY_CONTRACT without multiplier; source returns shares/yuan",
                source_code_sha256={p: sha(ROOT/p) for p in ("src/market/infrastructure/adapters/sina_adapter.py", "src/market/infrastructure/sina.py", "src/market/domain/source_contract.py")})
        receipt.update(returned_rows=int(len(frame)), returned_columns=list(frame.columns),
            returned_first_date=str(frame.date.min()) if len(frame) else None,
            returned_last_date=str(frame.date.max()) if len(frame) else None)
        dates = frame.date.astype(str).str[:10]
        selected = frame.loc[dates.ge(START) & dates.le(END)].copy()
        selected["date"] = selected.date.astype(str).str[:10]
        columns = [c for c in ("date", "open", "high", "low", "close", "volume", "amount", "tradestatus", "trade_status", "status") if c in selected.columns]
        selected = selected[columns].sort_values("date")
        selected.to_csv(HERE/f"{source}-window.csv", index=False, encoding="utf-8")
        receipt.update(ok=True, selected_rows=json.loads(selected.to_json(orient="records")),
            all_dates_in_requested_window=True, csv_sha256=sha(HERE/f"{source}-window.csv"),
            missing_requested_weekdays=sorted(set(pd.bdate_range(START, END).strftime("%Y-%m-%d"))-set(selected.date)))
    except Exception as exc:
        # Public adapters need no credentials. Still redact any URI userinfo in
        # inherited-network errors and preserve only the bounded failure text.
        message = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1<redacted>@", str(exc))
        receipt.update(ok=False, error_type=type(exc).__name__, error=message[:1400])
    after = {str(p.relative_to(ROOT)): sha(p) for p in DBS}
    receipt.update(completed_at=now(), snapshots_after_sha256=after, snapshots_unchanged=before == after)
    assert before == after
    write(target, receipt)
    print(json.dumps(receipt, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("tdx", "sina"))
    run(parser.parse_args().source)
