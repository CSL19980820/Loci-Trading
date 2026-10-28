"""把首波回调 D2 信号回填到候选池。

该脚本读取一个冻结的只读行情源，使用注册后的系统战法计算窗口内全部日期，
再通过统一的 ``persist_screen_candidates`` 写入指定租户的 palace.db。回填源
使用系统已有的历史标记，不会覆盖盘后真选结果。
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.market import MarketStore, resolve_universe
from src.market.infrastructure.store_schema import _INTEL_SNAPSHOTS_DDL, _SCHEMA
from src.shared.paths import palace_db as default_palace_db
from src.strategy import get
from src.strategy.application.persist import BACKFILL_SOURCE, persist_screen_candidates
from src.strategy.application.screener import ScreenResult


SLUG = "first-wave-pullback-v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _six_months_before(day: str) -> str:
    value = date.fromisoformat(day)
    month = value.month - 6
    year = value.year
    if month <= 0:
        year -= 1
        month += 12
    # Calendar subtraction keeps the requested window understandable; the
    # market calendar below chooses the first actual session on or after it.
    try:
        return date(year, month, value.day).isoformat()
    except ValueError:
        return date(year, month + 1, 1).isoformat()


def _ensure_research_schema(store: MarketStore) -> None:
    """Repair schema tables omitted by the compact frozen-market export."""
    store.conn.executescript(_SCHEMA)
    for ddl in _INTEL_SNAPSHOTS_DDL:
        store.conn.execute(ddl)
    store.conn.commit()


def _pick_payload(result: Any, day: str, panels: dict[str, Any]) -> list[dict[str, Any]]:
    selected = result.picks_on(day, rank_by="score")
    picks = []
    for code in selected:
        close = panels.get("close")
        open_ = panels.get("open")
        picks.append({
            "code": code,
            "close": None if close is None or code not in close.columns else float(close.at[day, code]),
            "open": None if open_ is None or code not in open_.columns else float(open_.at[day, code]),
            "factors": result.explain(day, code),
        })
    return picks


def run_backfill(
    *,
    market_db: Path,
    palace_path: Path,
    start: str | None,
    end: str | None,
    mainline_mode: str,
    output: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    engine = get(SLUG)
    params = {"mainline_mode": mainline_mode}
    with MarketStore(market_db) as store:
        _ensure_research_schema(store)
        all_days = store.trading_days()
        if not all_days:
            raise RuntimeError("行情源没有交易日")
        target_end = end or all_days[-1]
        if target_end not in all_days:
            prior = [day for day in all_days if day <= target_end]
            if not prior:
                raise RuntimeError(f"行情源没有目标日之前的交易日：{target_end}")
            target_end = prior[-1]
        requested_start = start or _six_months_before(target_end)
        target_days = store.trading_days(start=requested_start, end=target_end)
        if not target_days:
            raise RuntimeError(f"行情源没有回填交易日：{requested_start} → {target_end}")
        warmup_calendar = store.trading_days(end=target_days[0])
        warmup = engine.history_bars(params)
        load_start = warmup_calendar[max(0, len(warmup_calendar) - warmup)]

        resolved = resolve_universe(
            store,
            getattr(engine, "default_universe", None),
            as_of=target_end,
        )
        codes = list(resolved.codes)
        panels = store.load_panel(
            fields=engine.required_fields(),
            codes=codes,
            start=load_start,
            end=target_end,
            adjust=getattr(engine, "adjust", "hfq"),
            min_bars=engine.min_bars(),
        )
        result = engine.compute(panels, params)
        names = {
            item["code"]: item["name"]
            for item in store.list_instruments(status="")
        }
        source_sha256 = _sha256_file(market_db)
        pool_id = f"{SLUG}@{target_days[0]}-{target_days[-1]}"
        day_rows: list[dict[str, Any]] = []
        written_total = 0
        selected_total = 0
        for index, day in enumerate(target_days, start=1):
            picks = _pick_payload(result, day, panels)
            selected_total += len(picks)
            screen_result = ScreenResult(
                strategy_slug=SLUG,
                trade_date=day,
                strategy_revision=str(engine.strategy_revision),
                picks=picks,
                universe_size=len(codes),
                params=params,
                effective_params=params,
                entry_timing=engine.entry_timing,
                universe=resolved.spec,
                universe_funnel=resolved.funnel.to_dict(),
                # Backfill provenance is compact and points to the frozen source;
                # the full source is retained as a separate research artifact.
                data_snapshot={
                    "source_kind": "frozen_read_only_research_snapshot",
                    "source_db": str(market_db.resolve()),
                    "source_sha256": source_sha256,
                    "source_range": [str(all_days[0]), str(all_days[-1])],
                    "selection_range": [str(target_days[0]), str(target_days[-1])],
                    "selection_mode": "daily_d2_close_proxy",
                },
            )
            recorded = persist_screen_candidates(
                screen_result,
                palace_db=str(palace_path),
                names=names,
                pool_id=pool_id,
                source=BACKFILL_SOURCE,
                top_n=0,
            )
            written = int(recorded.get("written") or 0)
            written_total += written
            day_rows.append({
                "date": day,
                "selected": len(picks),
                "written": written,
                "removed": int(recorded.get("removed") or 0),
                "failed": recorded.get("failed") or [],
            })
            if index == 1 or index == len(target_days) or index % 10 == 0:
                print(f"backfill {index}/{len(target_days)} {day} selected={len(picks)} written={written}", flush=True)

    result_payload = {
        "strategy": SLUG,
        "strategy_revision": str(engine.strategy_revision),
        "params": params,
        "source_db": str(market_db.resolve()),
        "source_sha256": source_sha256,
        "palace_db": str(palace_path.resolve()),
        "pool_id": pool_id,
        "source": BACKFILL_SOURCE,
        "requested_start": start or _six_months_before(target_end),
        "requested_end": end or target_end,
        "actual_start": target_days[0],
        "actual_end": target_days[-1],
        "trading_days": len(target_days),
        "universe_size": len(codes),
        "selected_total": selected_total,
        "written_total": written_total,
        "days": day_rows,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--palace-db", type=Path, default=default_palace_db())
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--mainline-mode", choices=("price_resonance_proxy", "none"), default="price_resonance_proxy")
    parser.add_argument("--output", type=Path, default=Path("docs/research/2026-10-27-first-wave/system-backfill.json"))
    args = parser.parse_args()
    result = run_backfill(
        market_db=args.market_db,
        palace_path=args.palace_db,
        start=args.start,
        end=args.end,
        mainline_mode=args.mainline_mode,
        output=args.output,
    )
    print(json.dumps({k: result[k] for k in (
        "strategy", "actual_start", "actual_end", "trading_days", "universe_size", "selected_total", "written_total", "elapsed_seconds"
    )}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
