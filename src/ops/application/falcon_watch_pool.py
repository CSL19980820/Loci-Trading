"""公式观察池无模型同步；来源生命周期与自主择时计划分别保存。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import time
from typing import Any
from zoneinfo import ZoneInfo

from src.ledger import StockAgentStore
from src.ops.application.falcon_candidates import load_falcon_candidates
from src.ops.application.stock_agent_workbench import capture_observation_prices, quote_values, research_quotes
from src.shared.paths import palace_db
from src.shared.tenancy import current_tenant

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _sources(scope: dict) -> dict[str, list[dict]]:
    eligible = set(scope.get("candidate_codes") or [])
    latest: dict[tuple[str, str, str, str], dict] = {}
    for row in scope.get("candidates") or []:
        code = row.get("code")
        if code not in eligible or row.get("entry_eligible") is not True or not row.get("evidence_id"):
            continue
        key = (code, str(row.get("origin") or ""), str(row.get("strategy_slug") or ""),
               str(row.get("source") or ""))
        rank = (str(row.get("signal_date") or row.get("date") or ""),
                str(row.get("produced_at") or ""), str(row["evidence_id"]))
        prior = latest.get(key)
        if prior is None or rank > prior["rank"]:
            latest[key] = {"rank": rank, "row": row}
    result: dict[str, list[dict]] = {}
    for key, selected in sorted(latest.items()):
        row = selected["row"]
        result.setdefault(key[0], []).append({
            "origin": key[1], "strategy_slug": key[2], "source": key[3],
            "evidence_id": row["evidence_id"], "signal_date": selected["rank"][0],
            "produced_at": row.get("produced_at"), "expires_on": row.get("expires_on"),
            "score": row.get("score"), "reason": str(row.get("reason") or ""),
            "name": str(row.get("name") or key[0]),
        })
    return result


def reconcile_falcon_watch_pool(state: dict, scope: dict, *, as_of: datetime,
                                 agent_id: str) -> tuple[dict, dict]:
    """完整有效来源决定自动池；当前持仓不进入观察，不修改任何金融状态。"""
    result = deepcopy(state)
    changes: dict[str, Any] = {"changed": False, "added": [], "removed": [], "updated": []}
    if not scope.get("lifecycle_ready") or scope.get("historical_review"):
        changes["deferred"] = "缺少完整的实时来源/交易日生命周期证据，保留现有观察；不据缺失重建或清空。"
        return result, changes
    previous_pool = state.get("falcon_watch_pool") or {}
    if previous_pool and (previous_pool.get("agent_id") != agent_id or previous_pool.get("tenant_id") != current_tenant()):
        raise ValueError("猎隼观察池归属不匹配")
    sources = _sources(scope)
    auto_codes = set(scope.get("auto_observe_codes") or []) & set(sources)
    held = {row["code"] for row in state.get("positions") or [] if row.get("quantity", 0) > 0}
    previous_watch = {row["code"]: row for row in state.get("watchlist") or []}
    watch_codes = (auto_codes | (set(previous_watch) & set(sources))) - held
    watchlist = []
    entries = []
    for code in sorted(auto_codes | watch_codes | (held & set(sources))):
        refs = sources[code]
        newest = max(refs, key=lambda ref: (ref["signal_date"], str(ref.get("produced_at") or "")))
        expiry = max(ref["expires_on"] for ref in refs) if all(ref.get("expires_on") for ref in refs) else None
        labels = "、".join(dict.fromkeys(ref["strategy_slug"] or ref["source"] for ref in refs))
        reason = f"已开启来源 {labels} 的有效产出；最新合格信号 {newest['signal_date']}，按近5个公告交易日滚动保留。"
        entry = {"code": code, "name": newest["name"], "automatic": code in auto_codes,
                 "held": code in held, "last_signal_date": newest["signal_date"],
                 "expires_on": expiry, "sources": deepcopy(refs), "reason": reason}
        entries.append(entry)
        if code not in watch_codes:
            continue
        watch = deepcopy(previous_watch.get(code) or {})
        watch.update(code=code, name=newest["name"], source_managed=code in auto_codes,
                     source_reason=reason, source_signal_date=newest["signal_date"],
                     source_expires_on=expiry, source_refs=deepcopy(refs))
        watch.setdefault("added_at", as_of.isoformat())
        if not watch.get("reason"):
            watch["reason"] = reason
        watchlist.append(watch)
    pool = {"version": 1, "agent_id": agent_id, "tenant_id": current_tenant(),
            "policy": "enabled_formula_last_5_trading_days", "window": deepcopy(scope.get("window") or {}),
            "auto_observe_codes": sorted(auto_codes), "watch_codes": sorted(watch_codes), "entries": entries}
    comparable = {key: value for key, value in previous_pool.items() if key != "synced_at"}
    if comparable == pool and state.get("watchlist", []) == watchlist:
        return result, changes
    pool["synced_at"] = as_of.isoformat()
    result.update(watchlist=watchlist, falcon_watch_pool=pool)
    changes["changed"] = True
    changes["added"] = sorted(watch_codes - set(previous_watch))
    changes["removed"] = [{"code": code, "reason": "已持仓，转入持仓管理" if code in held else
                            "已无开启且在近5个交易日内的合格来源"}
                           for code in sorted(set(previous_watch) - watch_codes)]
    changes["updated"] = [code for code in sorted(watch_codes & set(previous_watch))
                          if next(row for row in watchlist if row["code"] == code) != previous_watch[code]]
    return result, changes


def sync_falcon_watch_pools(ops, palace_path, *, as_of: datetime | None = None,
                           agent_id: str | None = None) -> dict:
    """来源变更、维护与运行入口共用；paused/休市也同步，不调用模型。"""
    now = as_of or datetime.now(SHANGHAI)
    palace_path = palace_path or palace_db()
    if now.tzinfo is None:
        now = now.replace(tzinfo=SHANGHAI)
    # 网络取价只针对本次预览会新入池的代码，且不持有ops/ledger写事务。
    preview_scope = load_falcon_candidates(str(palace_path), ops, as_of=now)
    new_codes = set()
    with StockAgentStore(palace_path) as ledger:
        profiles = [ledger.get(agent_id)] if agent_id else ledger.list_profiles(include_archived=True)
        for profile in profiles:
            if profile["config"].get("kind") == "falcon" and not profile["archived"]:
                _, delta = reconcile_falcon_watch_pool(profile["state"], preview_scope, as_of=now, agent_id=profile["id"])
                new_codes.update(delta["added"])
    quotes = {}
    capture_time = now
    if new_codes:
        quote_started = time.monotonic()
        try:
            quotes = research_quotes(sorted(new_codes), now=now, deadline=quote_started + 6)
        except Exception:
            # 观察来源的入池/清理不能依赖行情服务成功，缺失价格保持未知。
            quotes = {}
        finally:
            capture_time = now + timedelta(seconds=max(0, time.monotonic() - quote_started))
    with ops.guardian_commit_guard(""):
        # 取价期间公式或账户可能变化，提交时重新核实资格及“首次入池”。
        scope = load_falcon_candidates(str(palace_path), ops, as_of=now)
        items = []
        with StockAgentStore(palace_path) as ledger:
            profiles = [ledger.get(agent_id)] if agent_id else ledger.list_profiles(include_archived=True)
            for profile in profiles:
                if profile["config"].get("kind") != "falcon" or profile["archived"]:
                    continue
                changes = {}

                def project(state):
                    updated, delta = reconcile_falcon_watch_pool(state, scope, as_of=now, agent_id=profile["id"])
                    new_quotes = {code: quotes[code] for code in delta["added"] if code in quotes}
                    if delta["added"]:
                        # helper会记录首次尝试，输入也只包含真正新增行，旧unknown完全不回填。
                        captured = capture_observation_prices({"watchlist": [row for row in updated.get("watchlist", [])
                            if row["code"] in delta["added"]]}, quotes=new_quotes, now=capture_time)
                        new_rows = {row["code"]: row for row in captured["watchlist"]}
                        updated["watchlist"] = [new_rows.get(row["code"], row) for row in updated["watchlist"]]
                    for row in updated.get("watchlist", []):
                        if row["code"] not in delta["added"]:
                            continue
                        row["observed_at"] = row["added_at"]
                        row.setdefault("observation_price_attempted_at", capture_time.isoformat())
                        price, stamp = quote_values(new_quotes.get(row["code"], {}), capture_time)
                        if price is not None:
                            row.update(current_price_cents=price, current_price_at=stamp)
                    changes.update(delta)
                    return updated

                ledger.update_falcon_watch_pool(profile["id"], project, now=now)
                items.append({"agent_id": profile["id"], **changes})
    return {"as_of": now.isoformat(), "lifecycle_ready": bool(scope.get("lifecycle_ready")),
            "warnings": scope.get("warnings") or [], "items": items}
