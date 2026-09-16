"""股票智能体配置、托管日程和读模型。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.ledger import StockAgentStore, mark_guardian_account
from src.ops.application.stock_agent_prompts import CUSTOM_PROMPT, LEADER_PROMPT, PHASE_NAMES
from src.ops.domain.stock_agent import StockAgentConfig


def agent_time() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def workshop_options(store) -> list[dict]:
    from src.strategy import describe_all
    slugs = {str((job.get("config") or {}).get("strategy") or (job.get("config") or {}).get("skill")
                 or (job.get("config") or {}).get("slug") or "") for job in store.list_jobs(enabled_only=True)
             if job["kind"] in {"screen", "skill", "skill_watch", "strategy_monitor"}}
    return [{"slug": row["slug"], "name": row["name"], "description": row.get("description", "")}
            for row in describe_all() if row["slug"] in slugs and row.get("enabled", True)]


def validate_agent_config(store, config: StockAgentConfig) -> dict:
    from src.ai import resolve_config
    data = config.model_dump()
    if config.enabled:
        provider = resolve_config(store, config.provider, model=config.model)
        if provider.model != config.model:
            raise ValueError("所选模型未启用")
        available = {row["slug"] for row in workshop_options(store)}
        if not set(config.strategies) <= available:
            raise ValueError("参考战法中存在已删除或未启用的战法，请重新选择")
    if not data["prompt"]:
        data["prompt"] = LEADER_PROMPT if config.kind == "leader" else CUSTOM_PROMPT
    return data


def schedules(profile: dict) -> list[dict]:
    cfg = profile["config"]
    schedule = cfg["schedule"]
    result = []
    for phase, field in (("premarket", "premarket_time"), ("auction", "auction_time"), ("review", "review_time")):
        hour, minute = schedule[field].split(":")
        result.append({"phase": phase, "label": PHASE_NAMES[phase], "time": schedule[field],
                       "cron": f"{int(minute)} {int(hour)} * * mon-fri", "enabled": True})
    result.append({"phase": "intraday", "label": "盘中管理", "time": f"每{schedule['intraday_minutes']}分钟",
                   "cron": f"*/{schedule['intraday_minutes']} 9-14 * * mon-fri", "enabled": schedule["intraday_enabled"]})
    result.append({"phase": "closeout", "label": "尾盘收敛", "time": "14:50 / 14:55",
                   "cron": "50,55 14 * * mon-fri", "enabled": schedule["intraday_enabled"]})
    return result


def ensure_stock_agent_jobs(store, *, palace_path=None) -> dict:
    store.ensure_job(name="智能体日记维护", kind="stock_agent_maintenance", cron="17 * * * *", enabled=True,
                     config={"managed": True, "timeout_sec": 120})
    with StockAgentStore(palace_path) as ledger:
        profiles = ledger.list_profiles(include_archived=True)
    count = 0
    for profile in profiles:
        cfg = profile["config"]
        for item in schedules(profile):
            # ID只用作不可变内部任务键；任何用户界面采用display_name，而非展示编码。
            name = f"股票智能体:{profile['id']}:{item['phase']}"
            store.ensure_job(name=name, kind="stock_agent", cron=item["cron"],
                enabled=bool(cfg["enabled"] and not profile["archived"] and item["enabled"]),
                config={"agent_id": profile["id"], "phase": item["phase"], "revision": profile["revision"],
                        "display_name": f"{cfg['name']} · {item['label']}", "managed": True,
                        "timezone": "Asia/Shanghai", "timeout_sec": cfg["timeout_seconds"] + 30})
            count += 1
    return {"jobs": count}


def public_profile(profile: dict, *, summary: bool = False) -> dict:
    now = agent_time()
    state = mark_guardian_account(profile["state"], {}, now)
    running = bool(profile["active_run"] and (profile["lease_until"] or "") > now.isoformat())
    status = profile["latest_status"]
    if status == "running" and not running:
        status = "interrupted"
    result = {key: profile[key] for key in (
        "id", "revision", "state_version", "created_at", "updated_at", "archived", "total_runs", "total_actions",
        "total_trades", "cleaned_runs", "history_kept", "latest_at", "latest_phase", "latest_summary", "latest_actions")}
    result.update(running=running, latest_status=status, config=profile["config"], state=state, schedules=schedules(profile))
    if summary:
        result["config"] = {key: profile["config"][key] for key in ("name", "kind", "description", "provider", "model", "enabled")}
        result["state"] = {key: state.get(key) for key in ("equity_cents", "cash_cents", "initial_capital_cents", "total_pnl_cents", "valuation_at", "stale_codes")}
        result["state"]["position_count"] = len(state["positions"])
        result["state"]["watchlist"] = [{"code": item["code"], "name": item.get("name", "")} for item in state.get("watchlist", [])]
    return result
