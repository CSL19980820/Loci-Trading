"""One bounded, read-only native minute capability probe; no strategy returns.

Retained reproduction/evidence script. Exactly four historical TDX query calls
at most and one Sina HTTP call (retries disabled). No persistent adapter edits.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from src.market.infrastructure import http_client, sina, tdx_minute  # noqa: E402

OUT = Path(__file__).resolve().parent
DB = ROOT / ".local/multi-strategy-scoring-20261004/market.db"


def now():
    return datetime.now(timezone.utc).isoformat()


def write(name, value):
    path = OUT / name
    if path.exists():
        raise FileExistsError(f"Preserve existing probe evidence: {path.name}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def daily(conn, code, day):
    row = conn.execute("SELECT trade_date,code,open,high,low,close,volume,amount,source "
                       "FROM quotes_daily WHERE trade_date=? AND code=?", (day, code)).fetchone()
    return dict(row) if row else None


def compare(frame, quote):
    if frame.empty:
        return {"rows": 0}
    result = {"rows": len(frame), "columns": list(frame.columns),
              "first_time_label": str(frame.datetime.iloc[0]), "last_time_label": str(frame.datetime.iloc[-1]),
              "has_source_OHLC": all(x in frame for x in ("open", "high", "low", "close")),
              "has_amount": "amount" in frame, "last_close": float(frame.close.iloc[-1]),
              "sampled_close_min": float(frame.close.min()), "sampled_close_max": float(frame.close.max())}
    if "volume" in frame:
        values = frame.volume.dropna()
        total = float(values.sum())
        result.update(raw_volume_sum=total, last_raw_volume=float(values.iloc[-1]),
                      raw_volume_nondecreasing=bool(values.is_monotonic_increasing))
        if quote and quote["volume"] and math.isfinite(quote["volume"]):
            result.update(raw_volume_sum_to_daily_shares=total/quote["volume"],
                          raw_volume_sum_times100_to_daily_shares=total*100/quote["volume"])
    if "amount" in frame:
        total_amount = float(frame.amount.sum())
        result["source_amount_sum"] = total_amount
        if quote and quote["amount"]:
            result["source_amount_sum_to_daily_amount"] = total_amount/quote["amount"]
    if quote:
        result["daily_quote_for_unit_check_only"] = quote
    return result


def main():
    if (OUT / "probe-plan.json").exists():
        raise FileExistsError("This bounded probe has already been started; do not retry requests implicitly")
    samples = []
    for segment in ("train", "validation_2025h2", "observed_2026"):
        path = ROOT / "docs/research/2026-10-04-multi-strategy-scoring/contraction-rebreakout-v1" / f"{segment}-candidates.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            keys = sorted({(r["signal_date"], r["code"].zfill(6)) for r in csv.DictReader(handle)})
        day, code = keys[0]
        samples.append(dict(segment=segment, code=code, requested_date=day,
                            selection="minimum date/code from preexisting complete shape keys only",
                            key_source=str(path.relative_to(ROOT)), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    conn = sqlite3.connect(DB.as_uri()+"?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    recent_code = samples[0]["code"]
    recent_day = conn.execute("SELECT MAX(trade_date) FROM quotes_daily WHERE code=?", (recent_code,)).fetchone()[0]
    samples.append(dict(segment="recent_reference", code=recent_code, requested_date=recent_day,
                        selection="same earliest-training code at latest frozen daily date; no outcomes"))
    plan = {"created_at": now(), "scope": "native interface capability only; no returns, new universe, installs or production access",
            "tdx_samples": samples, "max_tdx_history_queries": 4, "max_sina_http_queries": 1,
            "tdx_raw_evidence": "library-decoded original binary response fields, not a raw wire packet",
            "tdx_time_labels": "synthesized by project fixed 09:31..11:30 and13:01..15:00; source timestamp absent",
            "source_sha256": {f: hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in
                ("src/market/infrastructure/tdx_minute.py", "src/market/infrastructure/sina.py",
                 "src/market/infrastructure/adapters/tdx_adapter.py", "src/market/infrastructure/adapters/sina_adapter.py")},
            "daily_snapshot": str(DB.relative_to(ROOT)), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write("probe-plan.json", plan)
    receipts, client, connection_error = [], None, None
    try:
        client = tdx_minute._open_client()
    except Exception as error:
        connection_error = {"error_type": type(error).__name__, "error": str(error)}
    for sample in samples:
        started, clock = now(), time.monotonic()
        stem = f"tdx-{sample['requested_date']}-{sample['code']}"
        receipt = {**sample, "provider": "tdx", "started_at": started,
                   "request_method": "get_history_minute_time_data", "history_query_attempted": client is not None,
                   "source_timestamp_present": False, "date_evidence": "request parameter only; decoded records have no date",
                   "source_volume_unit": "not assumed from daily adapter; compare returned sum with same-day raw daily shares"}
        write(stem+"-request.json", receipt)
        if client is None:
            receipt.update(status="connection_failed_before_query", **connection_error)
        else:
            try:
                rows = client.get_history_minute_time_data(1 if sample["code"].startswith("6") else 0,
                                                         sample["code"], int(sample["requested_date"].replace("-", "")))
                receipt["raw_sha256"] = write(stem+"-source-decoded.json", rows)
                receipt["raw_fields"] = sorted({k for row in rows or [] if isinstance(row, dict) for k in row})
                receipt["raw_rows"] = len(rows) if isinstance(rows, list) else None
                frame = tdx_minute._rows_to_frame(rows, sample["requested_date"])
                frame.to_csv(OUT/(stem+"-project-normalized.csv"), index=False)
                receipt.update(status="nonempty" if len(frame) else "empty", comparison=compare(frame, daily(conn, sample["code"], sample["requested_date"])))
            except Exception as error:
                receipt.update(status="error", error_type=type(error).__name__, error=str(error))
        receipt.update(completed_at=now(), elapsed_seconds=time.monotonic()-clock)
        write(stem+"-receipt.json", receipt)
        receipts.append(receipt)
        print(json.dumps({k: receipt.get(k) for k in ("provider", "code", "requested_date", "status", "raw_rows", "error")}), flush=True)
    if client is not None:
        tdx_minute._close_client(client)

    stem, captured, original_get = f"sina-{recent_day}-{recent_code}", {}, http_client.market_get
    receipt = {"provider": "sina", "code": recent_code, "requested_date": recent_day, "started_at": now(),
               "max_http_requests": 1, "trade_date_semantics": "local filter of latest1970 records, not source historical date parameter"}
    write(stem+"-request.json", receipt)

    def capture_get(url, **kwargs):
        if captured.get("attempted"):
            raise AssertionError("Only one Sina HTTP request authorized")
        captured["attempted"] = True
        response = original_get(url, **{**kwargs, "retries": 0})
        body = OUT/(stem+"-source-response.txt")
        body.write_bytes(response.content)
        captured.update(http_status=response.status_code, response_sha256=hashlib.sha256(response.content).hexdigest(),
                        response_bytes=len(response.content), content_type=response.headers.get("Content-Type"))
        try:
            payload = json.loads(response.text.split("=(")[1].split(");")[0])
            if isinstance(payload, list):
                captured.update(raw_rows=len(payload), raw_fields=sorted({k for row in payload for k in row}),
                                source_first_datetime=payload[0].get("day") if payload else None,
                                source_last_datetime=payload[-1].get("day") if payload else None)
                write(stem+"-source-decoded.json", payload)
        except (ValueError, IndexError, TypeError):
            pass
        return response

    http_client.market_get = capture_get
    try:
        frame = sina.fetch_minute("sz"+recent_code, period="1", trade_date=recent_day)
        frame.to_csv(OUT/(stem+"-project-normalized.csv"), index=False)
        receipt.update(status="nonempty" if len(frame) else "empty", comparison=compare(frame, daily(conn, recent_code, recent_day)))
    except Exception as error:
        receipt.update(status="error", error_type=type(error).__name__, error=str(error))
    finally:
        http_client.market_get = original_get
        conn.close()
    receipt.update(captured, completed_at=now())
    write(stem+"-receipt.json", receipt)
    receipts.append(receipt)
    write("probe-summary.json", {"completed_at": now(), "tdx_history_queries": sum(r.get("history_query_attempted", False) for r in receipts),
                                 "sina_http_queries": int(captured.get("attempted", False)), "receipts": receipts})
    print(json.dumps({k: receipt.get(k) for k in ("provider", "code", "requested_date", "status", "raw_rows", "error")}), flush=True)


if __name__ == "__main__":
    main()
