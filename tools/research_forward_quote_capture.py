"""Manual immutable quote evidence for prepared research pools; never ranks or trades.

Only ``capture`` makes public, read-only HTTP requests. It requires a frozen plan
hash and the real target date/window before creating output or contacting Sina.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time as daytime, timedelta
import hashlib
from http.client import HTTPException, IncompleteRead
import json
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".local/forward-quote-evidence"
TZ = ZoneInfo("Asia/Shanghai")
URL = "https://hq.sinajs.cn/list={}"
MAX_BODY = 2 * 1024 * 1024
LINE = re.compile(r'\s*var\s+hq_str_((?:sh|sz)\d{6})\s*=\s*"([^"]*)"\s*', re.S)
FIELDS = {"open": 1, "prev_close": 2, "price": 3, "high": 4, "low": 5, "volume": 8, "amount": 9}


def now():
    return datetime.now(TZ)


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def symbol(code):
    if not re.fullmatch(r"(?:00|30|60)\d{4}", code):
        raise ValueError(f"Unsupported research code: {code}")
    return ("sh" if code.startswith("60") else "sz") + code


def bound_path(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Plan bindings must remain inside this workspace")
    return path


def load_plan(path, expected_sha, phase):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", phase):
        raise ValueError("Invalid capture phase identifier")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha) or sha(path) != expected_sha:
        raise ValueError("Capture plan hash mismatch")
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("format_version") != 1 or plan.get("purpose") != "research_quote_evidence_only":
        raise ValueError("Unsupported research capture contract")
    if plan.get("capture_script_sha256") != sha(Path(__file__)):
        raise ValueError("Capture implementation differs from the frozen plan")
    spec = plan["phases"][phase]
    codes = plan["pools"][spec["pool"]]
    if codes != sorted(set(codes)):
        raise ValueError("Pool must contain every code exactly once in sorted order")
    for code in codes:
        symbol(code)
    for item in plan["bindings"]:
        if sha(bound_path(item["path"])) != item["sha256"]:
            raise ValueError(f"Prepared input changed: {item['path']}")
    pool_source = plan["pool_sources"][spec["pool"]]
    bindings = {item["path"]: item["sha256"] for item in plan["bindings"]}
    if bindings.get(pool_source["manifest_path"]) != pool_source["manifest_sha256"]:
        raise ValueError("Pool manifest must be an immutable input binding")
    manifest = json.loads(bound_path(pool_source["manifest_path"]).read_text(encoding="utf-8"))
    if manifest.get("candidate_codes") != codes:
        raise ValueError("Capture pool differs from the complete prepared candidate set")
    if manifest.get(pool_source["target_date_field"]) != plan["target_trade_date"]:
        raise ValueError("Prepared pool belongs to a different target session")
    start = datetime.fromisoformat(f"{plan['target_trade_date']}T{spec['start']}+08:00")
    end = datetime.fromisoformat(f"{plan['target_trade_date']}T{spec['end']}+08:00")
    if not start < end or (end-start).total_seconds() > 300:
        raise ValueError("Capture phase must be a positive window of at most five minutes")
    if spec["max_quote_age_seconds"] <= 0 or spec["max_quote_age_seconds"] > 300:
        raise ValueError("Invalid source freshness contract")
    return plan, spec, codes, start, end


def require_window(moment, start, end):
    if moment.date() != start.date() or not start <= moment < end:
        raise ValueError(f"No HTTP performed: actual Shanghai time {moment.isoformat()} is outside {start.isoformat()}..{end.isoformat()}")


def parse(text):
    rows, duplicates = {}, set()
    for chunk in text.split(";"):
        match = LINE.fullmatch(chunk)
        if match is None:
            continue
        sym, body = match.groups()
        code = sym[2:]
        if code in rows:
            duplicates.add(code)
        raw = body.split(",") if body else []
        row = {"code": code, "symbol": sym, "raw_fields": raw, "source": "sina",
               "raw_prev_close_preserved": True, "fallback_applied": False}
        if len(raw) < 32:
            row["parse_error"] = "empty_or_short_source_record"
        else:
            row.update(name=raw[0], trade_date=raw[30], trade_time=raw[31])
            for field, index in FIELDS.items():
                try:
                    value = float(raw[index])
                    row[field] = value if math.isfinite(value) else None
                except ValueError:
                    row[field] = None
        rows[code] = row
    for code in duplicates:
        rows[code]["parse_error"] = "duplicate_source_record_in_one_response"
    return rows


def reject_reason(row, received, start, end, spec):
    if row.get("parse_error"):
        return row["parse_error"]
    if not str(row.get("name", "")).strip():
        return "missing_source_name"
    if row.get("trade_date") != start.date().isoformat():
        return "wrong_source_date"
    try:
        if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", str(row.get("trade_time", ""))):
            return "invalid_source_time"
        clock = daytime.fromisoformat(row["trade_time"])
        source = datetime.combine(start.date(), clock, TZ)
    except (KeyError, ValueError, TypeError):
        return "invalid_source_time"
    if not start <= source < end:
        return "source_time_outside_phase"
    if source > received + timedelta(seconds=5):
        return "source_time_ahead_of_receiver"
    if (received-source).total_seconds() > spec["max_quote_age_seconds"]:
        return "stale_source_quote"
    required = ["open", "prev_close", "volume"]
    if spec["require_intraday_ohlcv"]:
        required += ["price", "high", "low", "amount"]
    if any(row.get(k) is None or row[k] <= 0 for k in required):
        return "missing_or_nonpositive_required_raw_field"
    if spec["require_intraday_ohlcv"]:
        if row["high"] < max(row["open"], row["price"]) or row["low"] > min(row["open"], row["price"]):
            return "invalid_running_ohlc"
        center = row["amount"]/row["volume"]
        if not row["low"]-.01 <= center <= row["high"]+.01:
            return "running_amount_volume_outside_price_range"
    return ""


def capture(path, expected_sha, phase):
    plan, spec, codes, start, end = load_plan(path, expected_sha, phase)
    require_window(now(), start, end)  # Before mkdir, network, or output writes.
    folder = OUTPUT / plan["target_trade_date"] / phase / (now().strftime("%H%M%S%f") + "-" + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    started = now()
    deadline = min(started+timedelta(seconds=20), end)
    monotonic_deadline = time.monotonic()+(deadline-started).total_seconds()
    accepted, observed, rejected = {}, {}, {c: "not_received" for c in codes}
    errors, request_count = [], 0
    while rejected and now() < deadline and time.monotonic() < monotonic_deadline:
        pending = sorted(rejected)
        for offset in range(0, len(pending), 400):
            batch = pending[offset:offset+400]
            requested = now()
            remaining_budget = min((deadline-requested).total_seconds(), monotonic_deadline-time.monotonic())
            if remaining_budget <= 0:
                break
            request_count += 1
            prefix = f"request-{request_count:03d}"
            record = {"requested_codes": batch, "requested_at": requested.isoformat(), "attempt": request_count}
            request = Request(URL.format(",".join(symbol(c) for c in batch)),
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
            body = b""
            body_obtained = body_complete = False
            try:
                with urlopen(request, timeout=max(.05, min(6., remaining_budget))) as response:
                    record["http_status"] = response.status
                    body = response.read(MAX_BODY+1)
                    body_obtained = True
                    body_complete = len(body) <= MAX_BODY
                    record["response_headers"] = {k: response.headers.get(k) for k in ("Date", "Content-Type", "Content-Length")}
                received = now()
                record["received_at"] = received.isoformat()
                if len(body) > MAX_BODY:
                    raise ValueError("source_body_exceeded_bound")
                if received >= deadline or time.monotonic() >= monotonic_deadline:
                    raise ValueError("response_received_after_capture_deadline")
                rows = parse(body.decode("gbk", errors="strict"))
                record["unexpected_codes"] = sorted(set(rows)-set(batch))
                record["outcomes"] = {}
                for code in batch:
                    row = rows.get(code)
                    reason = reject_reason(row, received, start, end, spec) if row else "missing_source_record"
                    record["outcomes"][code] = reason or "accepted"
                    if row:
                        observed[code] = {**row, "requested_at": requested.isoformat(), "received_at": received.isoformat(),
                                          "request_file": f"{prefix}.json", "raw_body_file": f"{prefix}.body.bin"}
                    if reason:
                        rejected[code] = reason
                    else:
                        accepted[code] = observed[code]
                        rejected.pop(code, None)
            except (HTTPError, HTTPException, OSError, ValueError) as exc:
                record["received_at"] = now().isoformat()
                record["error"] = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, HTTPError):
                    record["http_status"] = exc.code
                    try:
                        body = exc.read(MAX_BODY+1)
                        body_obtained = True
                        body_complete = len(body) <= MAX_BODY
                    except IncompleteRead as body_error:
                        body = body_error.partial[:MAX_BODY+1]
                        body_obtained, body_complete = True, False
                        record["error_body_read_error"] = type(body_error).__name__
                    except (HTTPException, OSError) as body_error:
                        record["error_body_read_error"] = type(body_error).__name__
                    finally:
                        exc.close()
                elif isinstance(exc, IncompleteRead):
                    body = exc.partial[:MAX_BODY+1]
                    body_obtained, body_complete = True, False
                errors.append(record["error"])
                for code in batch:
                    rejected[code] = record["error"]
            record.update(raw_body_obtained=body_obtained, raw_body_complete=body_complete,
                          raw_body_bytes=len(body), raw_body_exceeded_bound=len(body) > MAX_BODY)
            if body_obtained:
                with (folder / f"{prefix}.body.bin").open("xb") as handle:
                    handle.write(body)
                record.update(raw_body_file=f"{prefix}.body.bin", raw_body_sha256=sha(folder / f"{prefix}.body.bin"), raw_encoding="gbk")
            write(folder / f"{prefix}.json", record)
        remaining = min((deadline-now()).total_seconds(), monotonic_deadline-time.monotonic())
        if rejected and remaining > 0:
            time.sleep(min(1., remaining))
    # Every requested member gets one terminal record, including missing/invalid.
    terminal = [{"code": c, "status": "accepted" if c in accepted else "rejected",
                 "quote": accepted.get(c, observed.get(c)), "reason": rejected.get(c, "")} for c in codes]
    write(folder / "quotes.json", terminal)
    try:
        unchanged = sha(path) == expected_sha and all(sha(bound_path(x["path"])) == x["sha256"] for x in plan["bindings"])
    except OSError as exc:
        unchanged = False
        errors.append(f"Input recheck failed: {type(exc).__name__}")
    complete = unchanged and not rejected and now() <= end
    manifest = dict(format_version=1, purpose="research_quote_evidence_only", phase=phase,
        target_trade_date=plan["target_trade_date"], started_at=started.isoformat(), completed_at=now().isoformat(),
        capture_plan_sha256=expected_sha, capture_script_sha256=sha(Path(__file__)), input_bindings=plan["bindings"],
        requested_codes=codes, requested=len(codes), accepted=len(accepted), rejected=len(rejected),
        complete_input_coverage=bool(complete), source_contract=spec, source="sina", volume_unit="share", amount_unit="yuan",
        original_inputs_unchanged=bool(unchanged), request_count=request_count, errors=errors,
        ranked=False, trading_order_submitted=False, actual_fill_proven=False,
        interpretation="Full input capture only. Accepted quote prints are not order fills; incomplete coverage cannot support full-pool ranking.")
    write(folder / "manifest.json", manifest)
    write(folder / "completion-receipt.json", {"files_sha256": {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
    print(json.dumps({"output": str(folder), "requested": len(codes), "accepted": len(accepted), "complete": bool(complete)}, ensure_ascii=False))


def self_check():
    start = datetime(2026, 10, 8, 14, 45, tzinfo=TZ)
    end = start+timedelta(minutes=1)
    spec = {"require_intraday_ohlcv": True, "max_quote_age_seconds": 10}
    fields = ["测试"] + ["0"]*31
    for key, val in dict(open=10., prev_close=9.9, price=10.2, high=10.3, low=9.8, volume=1000., amount=10100.).items():
        fields[FIELDS[key]] = str(val)
    fields[30], fields[31] = "2026-10-08", "14:45:00"
    line = 'var hq_str_sz300001="'+",".join(fields)+'";'
    row = parse(line)["300001"]
    assert not reject_reason(row, start+timedelta(seconds=1), start, end, spec)
    for patch, expected in [({"prev_close": 0.}, "missing_or_nonpositive_required_raw_field"),
        ({"trade_date": "2026-09-30"}, "wrong_source_date"), ({"trade_time": "14:44:59"}, "source_time_outside_phase"),
        ({"trade_time": "14:46:00"}, "source_time_outside_phase"), ({"trade_time": "14:45:30"}, "source_time_ahead_of_receiver"),
        ({"high": 9.}, "invalid_running_ohlc"), ({"amount": 999999.}, "running_amount_volume_outside_price_range"),
        ({"volume": 0.}, "missing_or_nonpositive_required_raw_field")]:
        assert reject_reason({**row, **patch}, start+timedelta(seconds=1), start, end, spec) == expected
    assert reject_reason(row, start+timedelta(seconds=11), start, end, spec) == "stale_source_quote"
    assert parse(line+line)["300001"]["parse_error"] == "duplicate_source_record_in_one_response"
    assert parse('var hq_str_sz300001="";')["300001"]["parse_error"] == "empty_or_short_source_record"
    bad = fields.copy()
    bad[2] = "nan"
    assert parse('var hq_str_sz300001="'+",".join(bad)+'";')["300001"]["prev_close"] is None
    for moment in (start-timedelta(days=1), end):
        try:
            require_window(moment, start, end)
        except ValueError:
            pass
        else:
            raise AssertionError("Outside-window invocation was accepted")
    assert row["prev_close"] == 9.9 and row["fallback_applied"] is False and symbol("600001") == "sh600001"
    return {"passed": True, "synthetic_only": True, "http_requests": 0,
            "checks": ["raw_source_fields", "no_prev_close_fallback", "date_and_window", "future_and_stale_source_time",
                       "OHLC_and_amount_volume", "no_trade_volume_rejected", "duplicate_and_empty_records", "nan_rejected", "before_HTTP_guard"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["self-check", "validate", "capture"])
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--phase")
    args = parser.parse_args()
    if args.action == "self-check":
        print(json.dumps(self_check(), ensure_ascii=False))
        return
    if not all([args.plan, args.plan_sha256, args.phase]):
        parser.error("--plan, --plan-sha256 and --phase are required")
    if args.action == "validate":
        plan, _, codes, start, end = load_plan(args.plan, args.plan_sha256, args.phase)
        print(json.dumps({"validated": True, "target": plan["target_trade_date"], "phase": args.phase,
                          "codes": len(codes), "start": start.isoformat(), "end": end.isoformat(), "http_requests": 0}))
    else:
        capture(args.plan, args.plan_sha256, args.phase)


if __name__ == "__main__":
    main()
