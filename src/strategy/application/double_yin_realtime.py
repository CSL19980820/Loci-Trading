"""同档盘后准备完整样本，次交易日竞价后只取样本实时开盘报价。"""
from __future__ import annotations

import math
import inspect
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.market import calendar_trading_day, resolve_universe, scheduled_trading_days
from src.strategy.application.double_yin_pool import (
    load_prepared_pool, save_prepared_pool, selection_key,
)
from src.strategy.application.screener import ScreenResult
from src.strategy.domain.base import StrategyError, merge_params


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _now() -> datetime:
    return datetime.now(SHANGHAI)


def _session(day: str, direction: int) -> str:
    origin = date.fromisoformat(day)
    for offset in range(1, 41):
        target = (origin + timedelta(days=direction * offset)).isoformat()
        if scheduled_trading_days(target, target):
            return target
    raise StrategyError("无法确定相邻交易日，不能使用普通工作日替代")


def _progress(callback, phase: str, percent: int, message: str) -> None:
    if callback is not None:
        callback(phase, percent, message)


def _params(engine, params) -> dict:
    values = merge_params(engine, params)
    engine.history_bars(values)  # 同时执行引擎参数校验。
    return values


def _universe(engine, universe) -> dict:
    effective = dict(universe or engine.default_universe)
    allowed = getattr(engine, "screen_allowed_boards", None)
    if allowed:
        effective["boards"] = list(allowed)
    return effective


def _number(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def prepare_double_yin_pool(engine, *, store=None, as_of: str | None = None,
                            params: dict | None = None, codes: list[str] | None = None,
                            universe: dict | None = None, on_progress=None) -> dict[str, Any]:
    """复用普通盘后行情仓，只保存完整历史形态样本，不写正式精选池。"""
    from src.market.application.double_yin_inputs import RealtimeInputError, fetch_double_yin_industries

    started = time.monotonic()
    clock = _now()
    closed_day = as_of or clock.date().isoformat()
    if closed_day > clock.date().isoformat():
        raise StrategyError("不能准备未来交易日的收盘样本")
    values = _params(engine, params)
    try:
        is_open = calendar_trading_day(closed_day)
    except ValueError as exc:
        raise StrategyError(str(exc)) from exc
    if not is_open:
        return {"status": "skipped_non_trading_day", "as_of": closed_day,
                "candidate_count": 0, "message": "非交易日，不覆盖已准备样本"}
    if closed_day == clock.date().isoformat() and (clock.hour, clock.minute) < (15, 0):
        raise StrategyError("样本准备须等待收盘，不能使用未完成日K")
    if store is None:
        raise StrategyError("盘后样本准备需要普通选股任务提供行情仓")
    days = store.trading_days(end=closed_day)
    if not days or str(days[-1]) != closed_day:
        raise StrategyError(f"{closed_day} 完整日K尚未就绪，不会把旧日数据当成当日样本")
    target = _session(closed_day, 1)
    prior_day = _session(closed_day, -1)
    effective_universe = _universe(engine, universe)
    _progress(on_progress, "prepare", 15, "按常规选股范围准备完整历史样本")
    resolved = resolve_universe(store, effective_universe, codes=codes, as_of=closed_day)
    bars = engine.history_bars(values)
    start = str(days[max(0, len(days) - bars - 4)])
    version = store.market_revision()
    panels = store.load_panel(fields=engine.required_fields(), codes=resolved.codes,
                              start=start, end=closed_day, min_bars=bars - 1, adjust="none")
    reference = panels.get("close")
    if reference is None or reference.empty:
        # 宇宙为空可以是合法空结果；非空宇宙没有面板属于数据失败。
        if resolved.codes:
            raise StrategyError("历史样本面板缺失，未覆盖原有准备结果")
        reference = pd.DataFrame(index=pd.Index(days[-bars:]), columns=[], dtype=float)
        panels = {field: reference.copy() for field in engine.required_fields()}
    names = {str(code): str(resolved.meta.get(str(code), {}).get("name") or "")
             for code in reference.columns}
    for field in engine.required_fields():
        frame = panels[field].reindex(index=reference.index.union([target]), columns=reference.columns).copy()
        frame.loc[target] = float("nan")
        panels[field] = frame
    panels["__instrument_names__"] = names
    panels["__sector_groups__"] = {}
    _progress(on_progress, "prepare", 45, "仅判定历史形态，不提前按评分或名额截断")
    result = engine.compute(panels, values) if len(reference.columns) else None
    mask = result.factors["历史形态候选"].loc[target] if result is not None else pd.Series(dtype=bool)
    candidate_codes = sorted(str(code) for code in mask.index[mask.fillna(False)])
    try:
        metadata, industry_snapshot = fetch_double_yin_industries(candidate_codes) if candidate_codes else ({}, {})
    except RealtimeInputError as exc:
        raise StrategyError(f"盘后板块证据准备失败，原样本保持不变：{exc}") from exc
    candidates = []
    for code in candidate_codes:
        rows = []
        for day in panels["close"].index:
            if str(day) > closed_day:
                continue
            rows.append({"date": str(day), **{
                field: _number(panels[field].at[day, code]) for field in engine.required_fields()
            }})
        # 全市场交易日对齐会产生停牌空格；最近两日必须是真实有效闭市K。
        valid_dates = [row["date"] for row in rows if row["close"] is not None and row["volume"] is not None
                       and row["volume"] > 0]
        if valid_dates[-2:] != [prior_day, closed_day]:
            continue
        candidates.append({"code": code, "name": names[code], "history": rows,
                           "industry": metadata.get(code, {}),
                           "historical_factors": result.explain(target, code)})
    snapshot_options = {"include_source_details": False}
    if "source_evidence_mode" in inspect.signature(store.data_snapshot).parameters:
        snapshot_options["source_evidence_mode"] = "compact"
    elif "source_summary_only" in inspect.signature(store.data_snapshot).parameters:
        snapshot_options["source_summary_only"] = True
    snapshot = store.data_snapshot(codes=list(reference.columns), start=start, end=closed_day,
                                   **snapshot_options)
    if store.market_revision() != version:
        raise StrategyError("行情在样本准备期间变化，未覆盖原有样本，请重试")
    missing_industries = [item["code"] for item in candidates if not item["industry"].get("groups")]
    status = "prepared_empty" if not candidates else ("prepared_with_warnings" if missing_industries else "prepared")
    payload = {
        "strategy_slug": engine.slug, "strategy_revision": engine.strategy_revision,
        "status": status, "as_of": closed_day, "target_trade_date": target,
        "prepared_at": clock.isoformat(), "selection_key": selection_key(engine, values, effective_universe),
        "params": values, "universe": effective_universe,
        "scope_codes": sorted(set(str(code).zfill(6) for code in codes)) if codes else None,
        "universe_size": len(resolved.codes), "history_bars": bars,
        "candidates": candidates, "candidate_count": len(candidates),
        "data_snapshot": {**snapshot, "history_origin": "normal_eod_screen",
                          "history_closed_date": closed_day, "industry": industry_snapshot,
                          "missing_industry_codes": missing_industries,
                          "candidate_scope": "complete_before_open_filter", "pre_ranked": False,
                          "push_wecom": False, "market_revision": version},
    }
    receipt = save_prepared_pool(payload)
    _progress(on_progress, "prepare", 100, f"已保存完整样本 {len(candidates)} 只，供 {target} 竞价筛选")
    return {key: value for key, value in payload.items() if key != "candidates"} | {
        "candidate_codes": [item["code"] for item in candidates], "pool": receipt,
        "elapsed_seconds": round(time.monotonic() - started, 3), "push_wecom": False,
    }


def screen_live_double_yin(engine, *, trade_date: str | None = None,
                           params: dict | None = None, codes: list[str] | None = None,
                           universe: dict | None = None, on_progress=None) -> ScreenResult:
    """早间不打开行情仓，开盘报价必须是该交易日09:25之后的现场数据。"""
    from src.market.application.double_yin_inputs import RealtimeInputError, fetch_double_yin_openings

    started = time.monotonic()
    clock = _now()
    today = clock.date().isoformat()
    day = trade_date or today
    if day != today:
        raise StrategyError("本战法只支持当日竞价实时筛选，不能将历史重放标成实时结果")
    values = _params(engine, params)
    effective_universe = _universe(engine, universe)
    try:
        is_open = calendar_trading_day(day)
    except ValueError as exc:
        raise StrategyError(str(exc)) from exc
    base = dict(strategy_slug=engine.slug, strategy_revision=engine.strategy_revision,
                trade_date=day, params=values, effective_params=values, entry_timing="open",
                universe=effective_universe)
    if not is_open:
        return ScreenResult(**base, data_snapshot={"status": "skipped_non_trading_day",
                            "live_source": "not_requested", "local_market_read": False})
    if not (9 * 60 + 25 <= clock.hour * 60 + clock.minute < 9 * 60 + 30):
        raise StrategyError("实时遴选仅在09:25至09:30竞价开盘确认窗口执行；盘后请运行样本准备")
    prior = _session(day, -1)
    _progress(on_progress, "prepare", 15, "核验次交易日完整样本快照")
    payload, digest = load_prepared_pool(engine, day, expected_as_of=prior,
                                         params=values, universe=effective_universe)
    if payload["history_bars"] < engine.history_bars(values):
        raise StrategyError("评分历史长度超过已准备快照，请按新参数重新准备样本")
    wanted = set(str(code).zfill(6) for code in codes) if codes else None
    prepared_scope = set(payload["scope_codes"]) if payload.get("scope_codes") else None
    if prepared_scope is not None and (wanted is None or not wanted.issubset(prepared_scope)):
        raise StrategyError("股票范围超出盘后准备范围，请重新准备完整样本")
    samples = [item for item in payload["candidates"] if wanted is None or item["code"] in wanted]
    target_codes = [item["code"] for item in samples]
    if not samples:
        return ScreenResult(**base, elapsed_seconds=time.monotonic() - started,
                            data_snapshot={**payload["data_snapshot"], "status": "completed_empty",
                                           "prepared_pool_sha256": digest, "prepared_as_of": prior,
                                           "live_requested_codes": 0, "local_market_read": False,
                                           "full_market_live_scan": False})
    try:
        quotes, quote_snapshot = fetch_double_yin_openings(target_codes, trade_date=day, now=clock,
                                                         on_progress=on_progress)
    except RealtimeInputError as exc:
        raise StrategyError(f"实时开盘数据未就绪：{exc}") from exc
    missing_quotes = sorted(set(target_codes) - set(quotes))
    if missing_quotes:
        rejects = quote_snapshot.get("rejects") or {}
        reasons = "; ".join(f"{code}：{rejects.get(code, '报价缺失')}" for code in missing_quotes[:5])
        raise StrategyError(f"实时开盘样本不完整（缺{len(missing_quotes)}/{len(samples)}只；{reasons}），"
                            "本轮不将剩余样本冒充完整排名")
    finish = _now()
    if finish.date().isoformat() != day or finish.hour * 60 + finish.minute >= 9 * 60 + 30:
        raise StrategyError("现场报价超过竞价确认窗口，本轮不产生迟到精选")
    dates = sorted({row["date"] for item in samples for row in item["history"]} | {day})
    panels = {field: pd.DataFrame(float("nan"), index=dates, columns=target_codes)
              for field in engine.required_fields()}
    names, groups, reference_rejects = {}, {}, {}
    by_code = {item["code"]: item for item in samples}
    for item in samples:
        code = item["code"]
        names[code] = str(quotes[code].get("name") or "").strip()
        groups[code] = tuple(item["industry"].get("groups") or ())
        for row in item["history"]:
            for field in engine.required_fields():
                panels[field].at[row["date"], code] = row[field]
        quote = quotes.get(code)
        if quote is None:
            continue
        prev_close = _number(quote.get("prev_close"))
        history_close = _number(panels["close"].at[prior, code])
        if prev_close is None or history_close is None or abs(prev_close - history_close) > 0.005:
            reference_rejects[code] = "实时前收参考与盘后样本不一致，可能除权或历史修订"
            continue
        panels["open"].at[day, code] = quote["open"]
    if len(reference_rejects) == len(samples):
        raise StrategyError("所有样本的实时前收参考与盘后历史不一致，本轮需要重新准备，不能记成零候选")
    panels["__instrument_names__"], panels["__sector_groups__"] = names, groups
    _progress(on_progress, "compute", 65, f"仅对盘后样本 {len(samples)} 只按实时开盘筛选和评分")
    output = engine.compute(panels, values)
    selected = output.picks_on(day, rank_by="score")
    picks = [{"code": code, "name": names[code], "open": quotes[code]["open"],
              "close": _number(quotes[code].get("price")), "pct_chg": output.explain(day, code)["低开幅度(%)"],
              "industry": by_code[code]["industry"].get("industry_path", ""),
              "factors": output.explain(day, code), "live_quote": quotes[code]}
             for code in selected]
    candidate_mask = output.factors["条件候选"].loc[day]
    reviews = [{"code": code, "name": names[code], "selected": code in selected,
                "industry": by_code[code]["industry"], "factors": output.explain(day, code)}
               for code in target_codes if bool(candidate_mask.get(code, False))]
    snapshot = {**payload["data_snapshot"], "status": "completed", "prepared_pool_sha256": digest,
                "prepared_at": payload["prepared_at"], "prepared_as_of": prior,
                "live_quotes": quote_snapshot, "local_market_read": False,
                "live_requested_codes": len(samples), "full_market_live_scan": False,
                "reference_rejects": reference_rejects, "candidate_reviews": reviews,
                "prepared_instrument_names": {item["code"]: item["name"] for item in samples},
                "selected_quote_evidence": {code: quotes[code] for code in selected},
                "instrument_names": names}
    _progress(on_progress, "done", 100, f"完成实时遴选，板块分散后精选 {len(picks)} 只")
    return ScreenResult(**base, picks=picks, universe_size=len(samples),
                        elapsed_seconds=time.monotonic() - started,
                        universe_funnel={"prepared_candidates": len(samples),
                                         "valid_live_quotes": len(quotes),
                                         "opening_candidates": int(candidate_mask.sum()),
                                         "signals_true": len(picks)}, data_snapshot=snapshot)
