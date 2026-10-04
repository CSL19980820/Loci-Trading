"""One frozen sampled-entry experiment; isolated, finite and train-first.

prepare/self-check are offline. freeze binds the reviewable contracts. run may
collect training only, then opens later phases solely after strict train success.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.engine import _resolve_exit  # noqa: E402
from src.market import is_st_name  # noqa: E402
from src.strategy.application.catalog import get  # noqa: E402
from tools.research_chinext_payoff_exits import BASELINE, CutoffMarketStore, common_maturity_mask  # noqa: E402
from tools.research_contraction_learned_rank import corrected_shape, original_rank, metrics_bundle  # noqa: E402
from tools.research_contraction_structure import Executor  # noqa: E402
from tools.research_double_yin_regime import normalized_economic, snapshot_factors  # noqa: E402
from tools.research_impulse_scoring import now, paired_bootstrap  # noqa: E402
from tools.strategy_chinext_review import write_json  # noqa: E402

OUTPUT = ROOT/"docs/research/2026-10-04-contraction-sampled-entry"
PREPOOL = ROOT/"docs/research/2026-10-04-contraction-intraday-feasibility/prepool"
PROBES = ROOT/"docs/research/2026-10-04-contraction-intraday-feasibility/minute-probes"
DB = ROOT/".local/chinext-payoff-20261004/market.db"
SPLITS = {"train": ("2024-01-01", "2025-06-30"), "validation_2025h2": ("2025-07-01", "2025-12-31"),
          "observed_2026": ("2026-01-01", "2026-09-30")}
ARMS = ("sampled_early", "sampled_next_open", "original_eod")
EPS = 1e-8
DECISION, ENTRY = 224, 234
REQUEST_INTERVAL = .125
MAX_CONNECT_ROUNDS = 4


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_once(path, value, *, raw=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Preserve evidence: {path}")
    if raw:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=True), encoding="utf-8")
    else:
        write_json(path, value)


def precise(value):
    if not np.isfinite(value) or value == 0:
        return float(value)
    scale = 10.**(9-np.floor(np.log10(abs(value))))
    return float(np.round(value*scale)/scale)


def positive(value):
    return value is not None and np.isfinite(value) and value > 0


def cents(value):
    return int(np.floor(float(value)*100+.5+1e-9))


def upper_cents(event):
    reference = event["raw_previous_close"]*event["factor_asof"]/event["factor_T"]
    return cents(reference*1.20)


def sdk_evidence():
    from tdxpy import hq
    paths = {"hq": Path(inspect.getfile(hq.TdxHq_API)),
             "history_parser": Path(inspect.getfile(hq.GetHistoryMinuteTimeData))}
    return dict(version=importlib.metadata.version("tdxpy"), files={k: dict(path=str(p), sha256=sha(p)) for k, p in paths.items()})


def sources():
    paths = ["tools/research_contraction_sampled_entry.py", "src/strategy/application/contraction_rebreakout.py",
        "src/backtest/application/engine.py", "src/backtest/application/execution_contract.py",
        "src/market/infrastructure/tdx_minute.py", "src/formula/domain/board.py",
        "tools/research_contraction_learned_rank.py", "tools/research_contraction_structure.py",
        "tools/research_double_yin_regime.py", "tools/research_chinext_payoff_exits.py",
        "tools/research_impulse_scoring.py", "tools/strategy_chinext_review.py"]
    return {p: sha(ROOT/p) for p in paths}


def halt_keys(output):
    receipt = read(output/"data-evidence/official-halt-receipt.json")
    keys = set()
    for item in receipt["records"]:
        assert item["content_checked"] and item["session"] == "whole_day_from_open"
        assert item["status"] == "officially_suspended"
        assert sha(output/"data-evidence"/item["file"]) == item["sha256"]
        keys.add((item["trade_date"], item["code"]))
    if keys != {("2025-05-19", "300506"), ("2025-06-20", "300959")}:
        raise AssertionError("Only the two predeclared training halt dates are authorized")
    return keys


def prepare_inputs(output):
    """Only offline collection bounds; never reads final C or return labels."""
    path = output/"inputs"
    if path.exists():
        raise FileExistsError("Input ledgers already prepared")
    path.mkdir()
    pool = pd.read_csv(PREPOOL/"potential-code-days.csv", dtype={"code": str}, float_precision="round_trip")
    halts = halt_keys(output)
    store = CutoffMarketStore(DB, "2026-09-30")
    try:
        factors = {}
        for code, date, factor in store.conn.execute("SELECT code,trade_date,hfq_factor FROM adjust_factors WHERE trade_date<=? ORDER BY code,trade_date", ("2026-09-30",)):
            if code not in factors:
                factors[code] = ([], [])
            factors[code][0].append(date)
            factors[code][1].append(factor)
        rows = []
        for item in pool.to_dict("records"):
            day, code = item["target_date"], item["code"]
            quote = store.conn.execute("SELECT high,source FROM quotes_daily WHERE trade_date=? AND code=?", (day, code)).fetchone()
            high, source = quote if quote is not None else (None, None)
            factor = np.nan
            if code in factors:
                days, values = factors[code]
                i = bisect_right(days, day)-1
                if i >= 0:
                    factor = values[i]
            threshold = max(item["prior_high5_economic"], 1.03*item["previous_close_economic"])
            bound = precise((high+.01+EPS)*factor) if positive(high) and positive(factor) else np.nan
            impossible = bool(source == "tdx" and np.isfinite(bound) and bound < threshold)
            disposition = ("current_static_ineligible" if not item["current_static_clean"] else
                           "official_full_day_halt" if (day, code) in halts else
                           "conditional_high_impossible" if impossible else "awaiting_minute")
            rows.append({**item, "factor_T": factor, "daily_high_for_bound": high, "daily_source_for_bound": source,
                "expanded_high_bound_economic": bound, "required_price_floor_economic": threshold,
                "expanded_H_impossible": impossible, "disposition": disposition})
    finally:
        store.close()
    frame = pd.DataFrame(rows)
    summaries = {}
    for segment, (start, end) in SPLITS.items():
        subset = frame[frame.target_date.between(start, end)].copy()
        subset.to_csv(path/f"{segment}-full-prepool-ledger.csv", index=False)
        summaries[segment] = dict(prepool_code_days=len(subset),
            expanded_H_only_possible_before_identity=int((~subset.expanded_H_impossible).sum()),
            actual_minute_targets=int(subset.disposition.eq("awaiting_minute").sum()),
            disposition=subset.disposition.value_counts().to_dict(),
            target_dates=int(subset.loc[subset.disposition.eq("awaiting_minute"), "target_date"].nunique()))
    write_once(path/"summary.json", dict(created_at=now(), expanded_high="precision10((rawH+.01+1e-8)*factorT)",
        quote_fields_read=["high", "source"], no_returns=True, no_network=True, segments=summaries))
    print(json.dumps(summaries, ensure_ascii=False), flush=True)


def protected_files(output):
    files = [output/"PLAN.md", output/"INPUT-QC.md", PREPOOL/"potential-code-days.csv", PREPOOL/"PLAN.json",
        output/"data-evidence/official-halt-receipt.json", *sorted((output/"data-evidence").glob("*.pdf")),
        *sorted((output/"inputs").glob("*")),
        PROBES/"tdx-2024-01-05-300707-source-decoded.json", PROBES/"tdx-2024-01-05-300707-request.json",
        PROBES/"tdx-2024-01-05-300707-receipt.json"]
    return {str(p.relative_to(ROOT)): sha(p) for p in files if p.is_file()}


def freeze(output):
    checks = self_check()
    if not (output/"inputs/summary.json").exists():
        raise ValueError("Review offline input/request counts before freeze")
    plan = dict(created_at=now(), sources=sources(), protected_files=protected_files(output),
        snapshot_sha256=sha(DB), sdk=sdk_evidence(), arms=ARMS, splits=SPLITS,
        decision_point_1based=225, entry_point_1based=235, price_QA_tolerance=.01+EPS,
        volume_QA="max(100 shares,dailyV*.001)", synthetic_checks=checks)
    write_once(output/"PLAN.json", plan)
    write_once(output/"freeze-receipt.json", dict(created_at=now(), plan_sha256=sha(output/"PLAN.json")))
    print(json.dumps(dict(frozen=True, plan_sha256=sha(output/"PLAN.json"))))


def verify_frozen(output, *, full=False):
    plan = read(output/"PLAN.json")
    assert sources() == plan["sources"]
    assert protected_files(output) == plan["protected_files"]
    assert sdk_evidence() == plan["sdk"]
    assert sha(output/"PLAN.json") == read(output/"freeze-receipt.json")["plan_sha256"]
    if full:
        assert sha(DB) == plan["snapshot_sha256"]
    return plan


def require_phase(output, phase):
    if phase not in SPLITS:
        raise ValueError(phase)
    if phase != "train":
        gate = read(output/"training-gate.json")
        assert gate["passed"] and gate["plan_sha256"] == sha(output/"PLAN.json")


def arrays(rows):
    if not isinstance(rows, list) or len(rows) != 240 or not all(isinstance(r, dict) for r in rows):
        raise ValueError("Expected240 ordered price/vol records")
    values = []
    for row in rows:
        if isinstance(row.get("price"), bool) or isinstance(row.get("vol"), bool):
            raise ValueError("Boolean is not a numeric quote")
        values.append((float(row["price"]), float(row["vol"])))
    return np.asarray(values, dtype=float).T


def quality(rows, quote):
    result = dict(passed=False, reason="invalid_structure", source_timestamp_present=False,
        date_evidence="request-date binding plus QA; source dates absent; not a date proof")
    try:
        p, v = arrays(rows)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {**result, "detail": str(exc)}
    if not np.isfinite(p).all() or not np.isfinite(v).all() or (p < 0).any() or (v < 0).any() or ((v > 0) & (p <= 0)).any():
        return {**result, "reason": "nonfinite_negative_or_positive_volume_without_price"}
    if quote is None or quote.get("source") != "tdx":
        return {**result, "reason": "missing_same_source_daily_reference"}
    o, h, low, c, volume = (quote.get(k) for k in ("open", "high", "low", "close", "volume"))
    if not all(positive(x) for x in (o, h, low, c, volume)) or h < max(o, c) or low > min(o, c):
        return {**result, "reason": "invalid_daily_reference"}
    if p[-1] <= 0:
        return {**result, "reason": "nonpositive_final_price_without_date_evidence"}
    share_sum = float(v.sum()*100)
    delta = share_sum-volume
    price_delta = float(p[-1]-c)
    positive_prices = p[p > 0]
    outside = int(((positive_prices < low-.01-EPS) | (positive_prices > h+.01+EPS)).sum())
    result.update(raw_volume_sum=float(v.sum()), sampled_share_sum=share_sum, daily_volume=float(volume),
        volume_signed_diff=float(delta), volume_abs_diff=abs(float(delta)), volume_relative_diff=float(delta/volume),
        volume_tolerance=float(max(100., volume*.001)), final_price_signed_diff=price_delta,
        final_price_abs_diff=abs(price_delta), outside_expanded_daily_range_points=outside,
        zero_volume_points=int((v == 0).sum()), price_exact_at_raw_cent=bool(cents(p[-1]) == cents(c)),
        volume_exact=bool(abs(delta) <= 1e-7), raw_positive_min=float(positive_prices.min()), raw_positive_max=float(positive_prices.max()))
    passed = abs(price_delta) <= .01+EPS and outside == 0 and abs(delta) <= max(100., volume*.001)+EPS
    result.update(passed=bool(passed), reason="QA_pass" if passed else "daily_joint_QA_mismatch",
        match_class="exact" if passed and abs(price_delta) <= EPS and abs(delta) <= 1e-7 else "within_frozen_tolerance" if passed else "failed")
    return result


def decision(event, rows, raw_open):
    """Only prefix225 and predeclared historical/opening fields enter this function."""
    result = {**event, "decision_status": "unknown", "decision_reason": "invalid_prefix", "score": np.nan}
    try:
        if not isinstance(rows, list) or len(rows) < DECISION+1:
            return result
        price = float(rows[DECISION]["price"])
        vols = np.array([float(r["vol"]) for r in rows[:DECISION+1]])
    except (KeyError, ValueError, TypeError):
        return result
    if not positive(price) or not np.isfinite(vols).all() or (vols < 0).any():
        return result
    if not all(positive(event.get(k)) for k in ("factor_T", "factor_asof", "raw_previous_close",
            "previous_close_economic", "prior_high5_economic", "previous_volume", "momentum_denominator_Tminus10")) or not positive(raw_open):
        return {**result, "decision_reason": "unknown_open_or_factor_or_past_reference"}
    economic_price = precise(price*event["factor_T"])
    economic_open = precise(raw_open*event["factor_T"])
    shares = float(vols.sum()*100)
    ratio = shares/event["previous_volume"]
    momentum = economic_price/event["momentum_denominator_Tminus10"]-1
    score80 = (40*np.clip(momentum/.20, 0, 1)+event["contraction_score15"]+event["pullback_depth_score15"]
               +10*np.clip((ratio-1)/2, 0, 1))
    passes = (economic_price > event["prior_high5_economic"] and economic_price >= 1.03*event["previous_close_economic"]
        and economic_price > economic_open and shares >= 1.5*event["previous_volume"] and cents(price) < upper_cents(event))
    result.update(decision_status="candidate" if passes else "known_not_candidate", decision_reason="prefix225_conditions",
        decision_price_raw=price, decision_price_economic=economic_price, cumulative_shares225=shares,
        breakout_volume_ratio225=float(ratio), momentum225_pct=float(momentum*100),
        score=float(np.round(score80*100/80, 4)), upper_limit_raw=upper_cents(event)/100, opening_raw=float(raw_open))
    return result


def raw_quote(store, day, code):
    row = store.conn.execute("SELECT trade_date,code,open,high,low,close,volume,source FROM quotes_daily WHERE trade_date=? AND code=?", (day, code)).fetchone()
    return dict(row) if row is not None else None


class Collector:
    """One connection, two attempts/key, four bounded connection rounds/phase."""
    def __init__(self, path):
        self.path, self.client, self.host, self.last_request = path, None, None, 0.
        self.rounds = len(list(path.glob("connection-round-*.json")))

    def close(self):
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
        self.client = None

    def connect(self):
        if self.client is not None:
            return True
        if self.rounds >= MAX_CONNECT_ROUNDS:
            return False
        from tdxpy.hq import TdxHq_API
        from src.market.infrastructure.tdx_minute import _SERVERS
        self.rounds += 1
        record = dict(started_at=now(), attempts=[])
        for host, port in _SERVERS[:4]:
            client = TdxHq_API(auto_retry=False, raise_exception=True)
            try:
                if not client.connect(host, port, time_out=4):
                    raise ConnectionError("connection returned false")
                self.client, self.host = client, f"{host}:{port}"
                record["connected"] = self.host
                break
            except Exception as exc:
                record["attempts"].append(dict(host=f"{host}:{port}", error_type=type(exc).__name__, error=str(exc)[:500]))
                try:
                    client.disconnect()
                except Exception:
                    pass
        record["completed_at"] = now()
        write_once(self.path/f"connection-round-{self.rounds}.json", record)
        return self.client is not None

    def fetch(self, day, code):
        if not self.connect():
            raise ConnectionError("bounded connection budget unavailable")
        gap = REQUEST_INTERVAL-(time.monotonic()-self.last_request)
        if gap > 0:
            time.sleep(gap)
        self.last_request = time.monotonic()
        return self.client.get_history_minute_time_data(0, code, int(day.replace("-", "")))


def transport_error(exc):
    from tdxpy.exceptions import TdxConnectionError
    seen = set()
    pending = [exc]
    while pending:
        item = pending.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, (OSError, TimeoutError, ConnectionError, TdxConnectionError)):
            return True
        pending.extend([getattr(item, "original_exception", None), getattr(item, "__cause__", None), getattr(item, "__context__", None)])
    return False


def collect(output, phase):
    verify_frozen(output, full=True)
    require_phase(output, phase)
    path = output/"cache"/phase
    path.mkdir(parents=True, exist_ok=True)
    if (path/"collection-summary.json").exists():
        existing = read(path/"collection-summary.json")
        for key, expected in existing["keys_sha256"].items():
            assert sha(path/f"{key}.json") == expected
        return existing
    ledger = pd.read_csv(output/"inputs"/f"{phase}-full-prepool-ledger.csv", dtype={"code": str})
    wanted = ledger[ledger.disposition.eq("awaiting_minute")].sort_values(["target_date", "code"])
    collector = Collector(path)
    store = CutoffMarketStore(DB, SPLITS[phase][1])
    try:
        for ordinal, row in enumerate(wanted.itertuples(), start=1):
            stem = f"{row.target_date}-{row.code}"
            final = path/f"{stem}.json"
            if final.exists():
                continue
            quote = raw_quote(store, row.target_date, row.code)
            attempts = []
            accepted = None
            for number in (1, 2):
                request_file = path/f"{stem}.attempt{number}.request.json"
                raw_file = path/f"{stem}.attempt{number}.raw.json"
                receipt_file = path/f"{stem}.attempt{number}.receipt.json"
                if receipt_file.exists():
                    receipt = read(receipt_file)
                    attempts.append(receipt)
                    if receipt.get("quality", {}).get("passed"):
                        assert sha(raw_file) == receipt["raw_sha256"]
                        accepted = receipt
                        break
                    if not receipt.get("retryable_transport_failure"):
                        break
                    continue
                if request_file.exists():
                    attempts.append(dict(attempt=number, status="interrupted_attempt_unknown", request_sha256=sha(request_file)))
                    break  # Neither a successful response nor transport failure is proven.
                reused = phase == "train" and row.code == "300707" and row.target_date == "2024-01-05" and number == 1
                request = dict(code=row.code, requested_date=row.target_date, provider="tdx", attempt=number,
                    started_at=now(), method="get_history_minute_time_data", reused_existing_probe=reused,
                    source_timestamp_present=False, sdk_auto_retry=False)
                write_once(request_file, request)
                receipt = {**request, "status": "unknown", "response_received": False, "retryable_transport_failure": False}
                try:
                    if reused:
                        old = PROBES/"tdx-2024-01-05-300707-source-decoded.json"
                        original_receipt = read(PROBES/"tdx-2024-01-05-300707-receipt.json")
                        assert sha(old) == original_receipt["raw_sha256"]
                        rows = read(old)
                        receipt.update(endpoint="not_logged_by_original_probe", original_raw_sha256=sha(old),
                            original_request_sha256=sha(PROBES/"tdx-2024-01-05-300707-request.json"))
                    else:
                        rows = collector.fetch(row.target_date, row.code)
                        receipt["endpoint"] = collector.host
                    receipt["response_received"] = True
                    write_once(raw_file, rows, raw=True)
                    q = quality(rows, quote)
                    receipt.update(status="valid" if q["passed"] else "QA_unknown", quality=q,
                        raw_file=str(raw_file.relative_to(ROOT)), raw_sha256=sha(raw_file))
                except Exception as exc:
                    receipt.update(status="request_unknown", error_type=type(exc).__name__, error=str(exc)[:600],
                        retryable_transport_failure=bool(not receipt["response_received"] and transport_error(exc)))
                    collector.close()
                receipt["completed_at"] = now()
                write_once(receipt_file, receipt)
                attempts.append(receipt)
                if receipt.get("quality", {}).get("passed"):
                    accepted = receipt
                    break
                if not receipt["retryable_transport_failure"]:
                    break
            write_once(final, dict(code=row.code, requested_date=row.target_date, status="valid" if accepted else "unknown",
                accepted_attempt=accepted["attempt"] if accepted else None,
                raw_file=accepted.get("raw_file") if accepted else None, raw_sha256=accepted.get("raw_sha256") if accepted else None,
                attempts=attempts, completed_at=now()))
            if ordinal % 100 == 0 or ordinal == len(wanted):
                print(f"{phase}: collected/resolved {ordinal}/{len(wanted)} keys", flush=True)
    finally:
        collector.close()
        store.close()
    verify_frozen(output)
    states = [read(path/f"{r.target_date}-{r.code}.json") for r in wanted.itertuples()]
    result = dict(completed_at=now(), targets=len(wanted), statuses=dict(Counter(s["status"] for s in states)),
        keys_sha256={f"{r.target_date}-{r.code}": sha(path/f"{r.target_date}-{r.code}.json") for r in wanted.itertuples()},
        plan_sha256=sha(output/"PLAN.json"))
    write_once(path/"collection-summary.json", result)
    return result


def phase_context(phase, output):
    """Daily data are for the stated opening, EOD control, QA and exits only."""
    start, end = SPLITS[phase]
    store = CutoffMarketStore(DB, end)
    try:
        metadata = {str(r["code"]): dict(r) for r in store.conn.execute("SELECT * FROM instruments WHERE instrument_type='STOCK'")
            if len(str(r["code"])) == 6 and str(r["code"]).isascii() and str(r["code"]).isdigit()
            and str(r["code"]).startswith(("300", "301"))}
        codes = sorted(metadata)
        dates = pd.Index(store.trading_days(start="2023-01-03", end=end), name="trade_date")
        raw = store.load_panel(fields=("open", "high", "low", "close", "volume"), codes=codes,
            start="2023-01-03", end=end, adjust="none", min_bars=0)
        raw = {k: f.reindex(index=dates, columns=codes) for k, f in raw.items()}
        # The same two exact official all-day halts also govern holding/selling.
        # This is an in-memory status overlay; original quote NULLs stay intact.
        overlay = []
        raw["volume"] = raw["volume"].copy()
        for day, code in sorted(halt_keys(output)):
            if day in raw["volume"].index and code in raw["volume"].columns:
                before = raw["volume"].at[day, code]
                raw["volume"].at[day, code] = 0.
                overlay.append(dict(trade_date=day, code=code, source_volume_before=before, execution_volume=0.,
                    evidence="official whole-day halt on this exact date only"))
        factor = snapshot_factors(store, raw["close"])
        raw["__adjust_factor"] = factor
        economic = normalized_economic(raw, factor)
        names = {c: str(m.get("name") or "") for c, m in metadata.items()}
        clean = pd.Series({c: bool(names[c].strip() and not is_st_name(names[c]) and "退" not in names[c]
            and str(m.get("status") or "") not in ("delisted", "suspended")) for c, m in metadata.items()})
        ctx = dict(engine=get("contraction-rebreakout-v1"), execution_panels=raw,
            panels={"__instrument_names__": names}, resolved_params={})
        eod = corrected_shape(ctx, economic, factor)
        candidate = eod["candidates"] & clean
        selected = original_rank(candidate, eod["original_score"])
        mature = common_maturity_mask(dates, start, end, max_hold=4)
        allowed = list(map(str, dates[mature]))
        return dict(ctx=ctx, executor=Executor(ctx, end), allowed=allowed,
            eod_selected=selected.where(mature, False, axis=0), eod_score=eod["original_score"],
            row_lookup={str(d): i for i, d in enumerate(dates)}, col_lookup={c: j for j, c in enumerate(codes)},
            official_halt_overlay=overlay)
    finally:
        store.close()


def cached_rows(output, phase, day, code):
    value = read(output/"cache"/phase/f"{day}-{code}.json")
    if value["status"] != "valid":
        return None, value
    path = ROOT/value["raw_file"]
    assert sha(path) == value["raw_sha256"]
    return read(path), value


def selection_records(output, phase, prepared):
    ledger = pd.read_csv(output/"inputs"/f"{phase}-full-prepool-ledger.csv", dtype={"code": str}, float_precision="round_trip")
    ledger = ledger[ledger.target_date.isin(prepared["allowed"])]
    byday = {day: group.to_dict("records") for day, group in ledger.groupby("target_date", sort=False)}
    selected, decisions, day_states = [], [], []
    executor = prepared["executor"]
    for day in prepared["allowed"]:
        items, known, unknown = byday.get(day, []), [], []
        for item in items:
            record = {**item, "signal_date": day, "decision_date": day,
                "row": prepared["row_lookup"][day], "col": prepared["col_lookup"][item["code"]]}
            if item["disposition"] != "awaiting_minute":
                decisions.append({**record, "decision_status": "known_not_candidate", "decision_reason": item["disposition"]})
                continue
            rows, cache = cached_rows(output, phase, day, item["code"])
            if rows is None:
                value = {**record, "decision_status": "unknown", "decision_reason": "minute_QA_or_request_unknown"}
            else:
                value = decision(record, rows, float(executor.values["open"][record["row"], record["col"]]))
                value["raw_minute_sha256"] = cache["raw_sha256"]
            decisions.append(value)
            if value["decision_status"] == "unknown":
                unknown.append(value)
            elif value["decision_status"] == "candidate":
                known.append(value)
        chosen = [] if unknown else sorted(known, key=lambda r: (-r["score"], r["code"]))[:2]
        selected.extend(chosen)
        day_states.append(dict(signal_date=day, total_prepool=len(items),
            static_ineligible=sum(r["disposition"] == "current_static_ineligible" for r in items),
            official_halt=sum(r["disposition"] == "official_full_day_halt" for r in items),
            conditional_high_impossible=sum(r["disposition"] == "conditional_high_impossible" for r in items),
            known_candidates=len(known), unknown_records=len(unknown), selected=len(chosen), rank_complete=not unknown))
    eod = []
    mask = prepared["eod_selected"]
    for row, col in zip(*np.nonzero(mask.to_numpy())):
        day, code = str(mask.index[row]), str(mask.columns[col])
        eod.append(dict(signal_date=day, decision_date=day, code=code, row=int(row), col=int(col),
            score=float(prepared["eod_score"].iat[row, col])))
    columns = ["signal_date", "decision_date", "code", "row", "col", "score"]
    sampled = pd.DataFrame(selected) if selected else pd.DataFrame(columns=columns)
    return {"sampled_early": sampled, "sampled_next_open": sampled.copy(), "original_eod": pd.DataFrame(eod, columns=columns)}, pd.DataFrame(decisions), pd.DataFrame(day_states)


def entry_fill(executor, event, arm, rows=None):
    row, col = int(event["row"]), int(event["col"])
    entry = row if arm == "sampled_early" else row+1
    if entry >= len(executor.dates):
        return entry, None, "unknown", "entry_beyond_phase"
    if arm == "sampled_early":
        try:
            p, v = float(rows[ENTRY]["price"]), float(rows[ENTRY]["vol"])
        except (IndexError, KeyError, TypeError, ValueError):
            return entry, None, "unknown", "missing_point235"
        if np.isfinite(v) and v == 0:
            return entry, None, "cancelled", "zero_volume_point235"
        if not positive(v) or not positive(p):
            return entry, None, "unknown", "invalid_point235"
        if cents(p) >= upper_cents(event):
            return entry, None, "cancelled", "limit_up_point235"
        return entry, p, "filled", "point235_price_proxy"
    volume, opening = float(executor.values["volume"][entry, col]), float(executor.values["open"][entry, col])
    if np.isfinite(volume) and volume <= 0:
        return entry, None, "cancelled", "known_nonpositive_volume"
    if not positive(volume) or not positive(opening) or not executor.known[entry, col]:
        return entry, None, "unknown", "unknown_open_volume_or_limit_reference"
    if executor.blocked[entry, col]:
        return entry, None, "cancelled", "known_limit_up_open"
    return entry, opening, "filled", "next_open"


def label_order(executor, event, arm, rows=None):
    entry, fill, state, reason = entry_fill(executor, event, arm, rows)
    record = {**event, "label_status": "unresolved", "label_reason": reason,
        "entry_date": str(executor.dates[entry]) if entry < len(executor.dates) else None,
        "entry_price": fill, "entry_factor": None, "exit_date": None, "exit_price": None,
        "exit_factor": None, "exit_reason": None, "hold_days": None,
        "gross_return_pct": np.nan, "net_return_pct": np.nan, "label_available_date": None}
    if state == "cancelled":
        record.update(label_status="cancelled", net_return_pct=0., label_available_date=record["entry_date"])
        return record
    if state != "filled":
        return record
    col = int(event["col"])
    factor = float(executor.factor[entry, col])
    basis = fill*factor
    record["entry_factor"] = factor
    exit_row, price, exit_reason = _resolve_exit(col=col, entry_idx=entry, entry_price=basis,
        planned_exit=entry+3, cfg=BASELINE.config(executor.end), high_a=executor.ec["high"], low_a=executor.ec["low"],
        close_a=executor.ec["close"], open_a=executor.ec["open"], one_word_down=executor.down,
        volume_a=executor.values["volume"], last_index=len(executor.dates)-1)
    if exit_row is None or exit_reason == "data_end" or not positive(price):
        record["label_reason"] = "unresolved_exit_not_zero"
        return record
    for day in range(entry, exit_row+1):
        v = float(executor.values["volume"][day, col])
        o, h, low, c = [float(executor.values[k][day, col]) for k in ("open", "high", "low", "close")]
        if not np.isfinite(v) or (v > 0 and (not all(positive(x) for x in (o, h, low, c))
                or h < max(o, c) or low > min(o, c) or not executor.known[day, col])):
            record["label_reason"] = "unknown_or_invalid_holding_quote"
            return record
    assert exit_row > entry and str(executor.dates[exit_row]) <= executor.end
    exit_factor = float(executor.factor[exit_row, col])
    raw_exit = float(price/exit_factor)
    for key in ("open", "close"):
        if price == executor.ec[key][exit_row, col]:
            raw_exit = float(executor.values[key][exit_row, col])
            break
    gross = float((price/basis-1)*100)
    record.update(label_status="closed", label_reason="closed", gross_return_pct=gross, net_return_pct=gross-.21,
        exit_date=str(executor.dates[exit_row]), exit_price=raw_exit, exit_factor=exit_factor,
        exit_reason=exit_reason, hold_days=exit_row-entry, label_available_date=str(executor.dates[exit_row]))
    return record


def result_bundle(orders, daily, rank_unknown_days):
    bundle = metrics_bundle(orders, int(daily.opportunities.sum()))
    complete = not rank_unknown_days and not orders.label_status.eq("unresolved").any()
    if not complete:
        for key in ("base", "double_cost", "winner_removed", "double_cost_winner_removed"):
            bundle[key]["net_sum"] = None
            bundle[key]["common_slot_mean"] = None
    closed = orders[orders.label_status.eq("closed")]
    return dict(metrics=bundle, complete_opportunity_statistics=bool(complete), rank_unknown_days=rank_unknown_days,
        selected_order_unknown=int(orders.label_status.eq("unresolved").sum()),
        active_entry_months=int(closed.entry_date.str[:7].nunique()) if len(closed) else 0,
        label_reasons=orders.label_reason.value_counts().to_dict())


def evaluate(output, phase):
    verify_frozen(output, full=True)
    require_phase(output, phase)
    collection = read(output/"cache"/phase/"collection-summary.json")
    for key, expected in collection["keys_sha256"].items():
        assert sha(output/"cache"/phase/f"{key}.json") == expected
    path = output/phase
    if (path/"summary.json").exists():
        completion = read(path/"completion-receipt.json")
        assert completion["plan_sha256"] == sha(output/"PLAN.json")
        for name, expected in completion["artifacts_sha256"].items():
            assert sha(path/name) == expected
        return read(path/"summary.json"), {a: pd.read_csv(path/f"{a}-orders.csv", dtype={"code": str}) for a in ARMS}, pd.read_csv(path/"daily-budget.csv")
    if path.exists():
        raise FileExistsError("Preserve interrupted evaluation artifacts")
    path.mkdir()
    prepared = phase_context(phase, output)
    selections, decisions, day_states = selection_records(output, phase, prepared)
    decisions.to_csv(path/"prepool-decision-records.csv", index=False)
    day_states.to_csv(path/"day-rank-completeness.csv", index=False)
    for arm, frame in selections.items():
        frame.to_csv(path/f"{arm}-preselected.csv", index=False)
    pd.testing.assert_frame_equal(selections["sampled_early"], selections["sampled_next_open"])
    write_once(path/"selection-receipt.json", dict(created_at=now(), return_labels_not_yet_computed=True,
        preselected_sha256={a: sha(path/f"{a}-preselected.csv") for a in ARMS},
        rank_completeness_sha256=sha(path/"day-rank-completeness.csv"), plan_sha256=sha(output/"PLAN.json")))
    runs, allorders, dailies = {}, {}, []
    bad_days = set(day_states.loc[~day_states.rank_complete, "signal_date"])
    for arm, selected in selections.items():
        labels = []
        for event in selected.to_dict("records"):
            rows = cached_rows(output, phase, event["signal_date"], event["code"])[0] if arm == "sampled_early" else None
            labels.append(label_order(prepared["executor"], event, arm, rows))
        order_columns = [*selected.columns, "label_status", "label_reason", "entry_date", "entry_price", "exit_date", "gross_return_pct", "net_return_pct"]
        orders = pd.DataFrame(labels) if labels else pd.DataFrame(columns=order_columns)
        orders.to_csv(path/f"{arm}-orders.csv", index=False)
        closed = orders[orders.label_status.eq("closed")]
        closed.to_csv(path/f"{arm}-trades.csv", index=False)
        unknown = set(orders.loc[orders.label_status.eq("unresolved"), "signal_date"])
        rank_unknown = bad_days if arm != "original_eod" else set()
        totals = closed.groupby("signal_date").net_return_pct.sum()
        daily = pd.DataFrame([dict(segment=phase, variant=arm, signal_date=day, opportunities=2,
            rank_unknown=day in rank_unknown, selected_unknown=day in unknown,
            net_sum=np.nan if day in unknown or day in rank_unknown else float(totals.get(day, 0.))) for day in prepared["allowed"]])
        result = result_bundle(orders, daily, len(rank_unknown))
        runs[arm], allorders[arm] = result, orders
        dailies.append(daily)
        print(phase, arm, json.dumps(dict(base=result["metrics"]["base"], rank_unknown_days=len(rank_unknown))), flush=True)
    for daily in dailies:
        arm = daily.variant.iloc[0]
        runs[arm]["paired_month_bootstrap"] = {}
        for control in ("sampled_next_open", "original_eod"):
            base = next(d for d in dailies if d.variant.iloc[0] == control).set_index("signal_date").net_sum
            paired = daily.assign(base_net_sum=daily.signal_date.map(base))
            paired["delta_net_sum"] = paired.net_sum-paired.base_net_sum
            runs[arm]["paired_month_bootstrap"][control] = paired_bootstrap(paired) if np.isfinite(paired.delta_net_sum).all() else None
    joined = pd.concat(dailies, ignore_index=True)
    joined.to_csv(path/"daily-budget.csv", index=False)
    result = dict(segment=phase, common_market_days=len(prepared["allowed"]), common_slots=len(prepared["allowed"])*2,
        first_signal=prepared["allowed"][0], last_signal=prepared["allowed"][-1], runs=runs,
        collection_statuses=collection["statuses"], plan_sha256=sha(output/"PLAN.json"),
        exact_clock_not_proven=True, high_envelope_assumption_required=True,
        exact_official_halt_execution_overlay=prepared["official_halt_overlay"])
    verify_frozen(output)
    write_once(path/"summary.json", result)
    write_once(path/"completion-receipt.json", dict(created_at=now(), plan_sha256=sha(output/"PLAN.json"),
        artifacts_sha256={p.name: sha(p) for p in sorted(path.iterdir()) if p.is_file()}))
    return result, allorders, joined


def positive_quality(run):
    m = run["metrics"]["base"]
    stress = run["metrics"]["double_cost_winner_removed"]["avg_net_return"]
    pf = (m["profit_factor"] is not None and m["profit_factor"] > 1) or (m["positive_net_sum"] > 0 and m["negative_net_sum"] == 0)
    return bool(run["complete_opportunity_statistics"] and m["avg_net_return"] is not None and m["avg_net_return"] > 0
        and pf and stress is not None and stress > 0)


def beats_controls(runs):
    m = runs["sampled_early"]["metrics"]["base"]
    return bool(runs["sampled_early"]["complete_opportunity_statistics"] and m["common_slot_mean"] is not None
        and all(runs[a]["complete_opportunity_statistics"] and runs[a]["metrics"]["base"]["common_slot_mean"] is not None
            and m["common_slot_mean"] > runs[a]["metrics"]["base"]["common_slot_mean"] for a in ("sampled_next_open", "original_eod")))


def run(output):
    verify_frozen(output, full=True)
    collect(output, "train")
    train, _, _ = evaluate(output, "train")
    candidate = train["runs"]["sampled_early"]
    criteria = dict(at_least20_closed=candidate["metrics"]["base"]["trades"] >= 20,
        at_least6_entry_months=candidate["active_entry_months"] >= 6,
        complete_positive_base_and_combined_stress=positive_quality(candidate),
        common_slot_beats_both_controls=beats_controls(train["runs"]))
    passed = all(criteria.values())
    gate = dict(created_at=now(), passed=passed, criteria=criteria, nominee="sampled_early" if passed else None,
        no_fallback=True, later_new_minutes_not_yet_read=True, plan_sha256=sha(output/"PLAN.json"))
    if not (output/"training-gate.json").exists():
        write_once(output/"training-gate.json", gate)
    else:
        assert read(output/"training-gate.json")["passed"] == passed
    result = dict(train=train, training_gate=gate, later_not_evaluated=not passed, no_2023h2_returns=True)
    if passed:
        stages, pooled_orders, dailies = {}, {a: [] for a in ARMS}, []
        for phase in ("validation_2025h2", "observed_2026"):
            collect(output, phase)
            stages[phase], orders, daily = evaluate(output, phase)
            for arm in ARMS:
                pooled_orders[arm].append(orders[arm])
            dailies.append(daily)
        merged = pd.concat(dailies, ignore_index=True)
        merged.to_csv(output/"pooled-later-daily-budget.csv", index=False)
        pooled = {}
        for arm in ARMS:
            daily = merged[merged.variant.eq(arm)]
            pooled[arm] = result_bundle(pd.concat(pooled_orders[arm], ignore_index=True), daily,
                sum(s["runs"][arm]["rank_unknown_days"] for s in stages.values()))
        result.update(later=stages, pooled_later=pooled,
            statistical_pass=bool(all(positive_quality(s["runs"]["sampled_early"]) for s in stages.values()) and beats_controls(pooled)))
    verify_frozen(output, full=True)
    result.update(completed_at=now(), plan_sha256=sha(output/"PLAN.json"), frozen_inputs_unchanged=True,
        conditional_sampled_proxy_only=True, shared_capital_not_evaluated=True)
    write_once(output/"summary.json", result)
    print(json.dumps(dict(training_passed=passed, later_not_evaluated=not passed, statistical_pass=result.get("statistical_pass"))), flush=True)


def self_check():
    rows = [dict(price=10.4, vol=10.) for _ in range(240)]
    quote = dict(source="tdx", open=10.2, high=10.5, low=10., close=10.4, volume=240000.)
    assert quality(rows, quote)["passed"]
    assert quality(rows, {**quote, "volume": 240100.})["passed"]
    assert not quality(rows, {**quote, "volume": 242000.})["passed"]
    assert not quality(rows[:-1], quote)["passed"]
    bad = [dict(r) for r in rows]
    bad[4]["price"] = 10.52
    assert not quality(bad, quote)["passed"]
    near = [dict(r) for r in rows]
    near[4]["price"] = 10.51
    assert quality(near, quote)["passed"]
    event = dict(signal_date="2024-01-04", decision_date="2024-01-04", code="300001", row=2, col=0,
        factor_T=1., factor_asof=1., raw_previous_close=10., previous_close_economic=10.,
        prior_high5_economic=10.3, previous_volume=100000., momentum_denominator_Tminus10=9.8,
        contraction_score15=12., pullback_depth_score15=11.)
    selected = decision(event, rows, 10.2)
    assert selected["decision_status"] == "candidate" and selected["cumulative_shares225"] == 225000.
    future = [dict(r) for r in rows]
    for i in range(DECISION+1, len(future)):
        future[i] = dict(price=999., vol=999.)
    assert decision(event, future, 10.2) == selected
    assert decision(event, rows[:225], 10.2) == selected
    assert decision(event, rows[:224], 10.2)["decision_status"] == "unknown"
    assert precise((10.29+.01+EPS)) >= 10.3  # QA price allowance cannot be pruned.
    dates = pd.Index([f"2024-01-{d:02d}" for d in range(2, 12)])
    raw = {k: pd.DataFrame(10.4, index=dates, columns=["300001"]) for k in ("open", "high", "low", "close")}
    raw.update(volume=pd.DataFrame(100., index=dates, columns=["300001"]),
        __adjust_factor=pd.DataFrame(1., index=dates, columns=["300001"]))
    executor = Executor(dict(execution_panels=raw), str(dates[-1]))
    early = label_order(executor, selected, "sampled_early", rows)
    later = label_order(executor, selected, "sampled_next_open")
    assert early["label_status"] == later["label_status"] == "closed"
    assert early["entry_date"] == dates[2] and later["entry_date"] == dates[3]
    assert early["exit_date"] == dates[5] and later["exit_date"] == dates[6]
    assert early["net_return_pct"] == later["net_return_pct"] == -.21
    zero = [dict(r) for r in rows]
    zero[ENTRY]["vol"] = 0.
    assert decision(event, zero, 10.2) == selected
    assert entry_fill(executor, event, "sampled_early", zero)[2:] == ("cancelled", "zero_volume_point235")
    high = [dict(r) for r in rows]
    high[ENTRY]["price"] = 12.
    assert entry_fill(executor, event, "sampled_early", high)[2:] == ("cancelled", "limit_up_point235")
    executor.values = {k: a.copy() for k, a in executor.values.items()}
    executor.values["volume"][4, 0] = np.nan
    unknown = label_order(executor, selected, "sampled_early", rows)
    assert unknown["label_status"] == "unresolved" and np.isnan(unknown["net_return_pct"])
    daily = pd.DataFrame([dict(signal_date=str(d), opportunities=2, net_sum=0.) for d in dates])
    bundle = result_bundle(pd.DataFrame([early]), daily, 1)
    assert not bundle["complete_opportunity_statistics"] and bundle["metrics"]["base"]["common_slot_mean"] is None
    tied = sorted([dict(code="300002", score=80.), dict(code="300001", score=80.)], key=lambda r: (-r["score"], r["code"]))
    assert tied[0]["code"] == "300001"
    assert transport_error(TimeoutError()) and not transport_error(ValueError("bad QA"))
    # Exercise the actual full-day selection path, not merely metric nulling.
    with tempfile.TemporaryDirectory(prefix="sampled-rank-check-") as directory:
        tmp = Path(directory)
        (tmp/"inputs").mkdir()
        (tmp/"cache/train").mkdir(parents=True)
        fixture = []
        for i, code in enumerate(("300001", "300002", "300003")):
            fixture.append({**event, "code": code, "target_date": event["signal_date"], "disposition": "awaiting_minute"})
            raw_path = tmp/f"{code}.raw.json"
            write_once(raw_path, rows, raw=True)
            write_once(tmp/"cache/train"/f"{event['signal_date']}-{code}.json", dict(status="valid" if i < 2 else "unknown",
                raw_file=str(raw_path), raw_sha256=sha(raw_path)))
        pd.DataFrame(fixture).to_csv(tmp/"inputs/train-full-prepool-ledger.csv", index=False)
        index = pd.Index([event["signal_date"]])
        fake = dict(allowed=list(index), executor=SimpleNamespace(values={"open": np.full((1, 3), 10.2)}),
            row_lookup={event["signal_date"]: 0}, col_lookup={f"30000{i+1}": i for i in range(3)},
            eod_selected=pd.DataFrame(False, index=index, columns=["300001", "300002", "300003"]),
            eod_score=pd.DataFrame(50., index=index, columns=["300001", "300002", "300003"]))
        choices, _, states = selection_records(tmp, "train", fake)
        assert choices["sampled_early"].empty and choices["sampled_next_open"].empty
        assert not states.rank_complete.iloc[0] and states.unknown_records.iloc[0] == 1
        fixture[2]["disposition"] = "current_static_ineligible"
        pd.DataFrame(fixture).to_csv(tmp/"inputs/train-full-prepool-ledger.csv", index=False)
        choices, _, states = selection_records(tmp, "train", fake)
        assert choices["sampled_early"].code.tolist() == ["300001", "300002"] and states.rank_complete.iloc[0]
    return dict(passed=True, synthetic_only=True, no_requests_or_returns_from_real_data=True,
        checks=["240-row QA", "frozen price/volume tolerances", "expanded high includes QA boundary",
            "point225/235 one-based indexing", "80point score solely from prefix225", "future-tail mutation invariance",
            "same-list different four-session expiry", "T+1/no-entry-day sell", "zero-volume235 cancellation after ranking",
            "235limit cancellation", "holding unknown not zero", "rank-unknown preserves budget", "lexical tie",
            "transport-only retry classification", "actual incomplete-pool path selects no residual Top2"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("self-check", "prepare", "freeze", "collect", "evaluate", "run"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--phase", choices=tuple(SPLITS), default="train")
    args = parser.parse_args()
    output = args.output.resolve(strict=True)
    if args.action == "self-check":
        print(json.dumps(self_check()))
    elif args.action == "prepare":
        prepare_inputs(output)
    elif args.action == "freeze":
        freeze(output)
    elif args.action == "collect":
        collect(output, args.phase)
    elif args.action == "evaluate":
        evaluate(output, args.phase)
    else:
        run(output)


if __name__ == "__main__":
    main()
