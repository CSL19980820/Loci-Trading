"""全局助手的受控运维工具，与账本/行情工具分离以保持主总线紧凑。"""
from __future__ import annotations

from threading import Thread
from typing import Any


_ASSISTANT_JOB_KINDS = {
    "sync",
    "screen",
    "backtest",
    "compare",
    "optimize",
    "prune",
    "outcome",
}

_COMMON_JOB_CONFIG_KEYS = {"push_wecom", "schedule"}
_JOB_CONFIG_KEYS = {
    "sync": {
        "mode", "with_factors", "refresh_instruments", "codes", "limit", "workers", "interval", "force",
    },
    "screen": {
        "strategy", "refresh_spot", "date", "params", "codes", "universe", "record_candidates", "top_n",
        "use_ai_pick", "provider", "model", "thinking", "reserve_n", "pool_id", "decision",
    },
    "backtest": {
        "strategy", "hold_days", "stop_loss_pct", "take_profit_pct", "benchmark", "start", "end", "params",
        "codes", "universe",
    },
    "compare": {"holds", "strategies", "start", "end", "stop_loss_pct", "benchmark", "universe"},
    "optimize": {"strategy", "holds", "targets", "stops", "start", "end", "benchmark", "universe"},
    "prune": {"keep_per_job", "leader_role_keep_days"},
    "outcome": {"limit", "max_age_trading_days", "benchmark"},
}


def _bounded_int(config: dict[str, Any], key: str, *, minimum: int, maximum: int) -> None:
    if key not in config:
        return
    value = config[key]
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        from src.ai.application.system_toolbus import AssistantError

        raise AssistantError(f"任务配置 {key} 必须是 {minimum} 到 {maximum} 的整数")


def _bounded_list(config: dict[str, Any], key: str, *, maximum: int) -> None:
    if key not in config:
        return
    value = config[key]
    if not isinstance(value, list) or len(value) > maximum:
        from src.ai.application.system_toolbus import AssistantError

        raise AssistantError(f"任务配置 {key} 必须是至多 {maximum} 项的列表")


def _validate_job_config(kind: str, config: Any) -> None:
    """助手只能提交已知任务参数，并限制会展开成大量工作量的字段。"""
    from src.ai.application.system_toolbus import AssistantError

    if not isinstance(config, dict):
        raise AssistantError("任务配置必须是对象")
    allowed = _JOB_CONFIG_KEYS.get(kind)
    if allowed is None:
        raise AssistantError("该任务类型不能由全局助手配置")
    unknown = set(config) - allowed - _COMMON_JOB_CONFIG_KEYS
    if unknown:
        raise AssistantError(f"任务配置包含不支持的字段：{sorted(unknown)}")
    if len(config) > len(allowed) + len(_COMMON_JOB_CONFIG_KEYS):
        raise AssistantError("任务配置字段过多")

    for key, maximum in {"codes": 500, "strategies": 20, "holds": 12, "targets": 12, "stops": 12}.items():
        _bounded_list(config, key, maximum=maximum)
    _bounded_int(config, "workers", minimum=1, maximum=8)
    _bounded_int(config, "limit", minimum=1, maximum=2000)
    _bounded_int(config, "top_n", minimum=0, maximum=100)
    _bounded_int(config, "reserve_n", minimum=0, maximum=300)
    _bounded_int(config, "hold_days", minimum=1, maximum=60)
    _bounded_int(config, "keep_per_job", minimum=1, maximum=1000)
    # 0 = 不清理角色留痕；上限压到两年，避免助手写出一个永不生效的保留窗
    _bounded_int(config, "leader_role_keep_days", minimum=0, maximum=730)
    _bounded_int(config, "max_age_trading_days", minimum=1, maximum=250)
    if kind == "optimize":
        combinations = 1
        for key in ("holds", "targets", "stops"):
            combinations *= len(config.get(key) or [None])
        if combinations > 128:
            raise AssistantError("优化任务最多允许 128 组参数组合")


def build_ops_tool_specs(owner: Any) -> dict[str, Any]:
    """延迟导入避免与 ``system_toolbus`` 的 ToolSpec 形成循环。"""
    from src.ai.application.system_toolbus import ToolSpec, _object

    read = False
    write = True
    return {
        "ops_provider_catalog": ToolSpec(
            "ops_provider_catalog",
            "读取脱敏的已配置供应商目录。",
            _object({}),
            read,
            lambda args: _provider_catalog(owner, args),
        ),
        "ops_set_default_provider": ToolSpec(
            "ops_set_default_provider",
            "切换已配置的默认供应商。",
            _object({"name": {"type": "string", "minLength": 1, "maxLength": 80}}, ["name"]),
            write,
            lambda args: _set_default_provider(owner, args),
        ),
        "ops_set_default_model": ToolSpec(
            "ops_set_default_model",
            "切换已配置供应商的默认模型。",
            _object(
                {
                    "name": {"type": "string", "minLength": 1, "maxLength": 80},
                    "model": {"type": "string", "minLength": 1, "maxLength": 160},
                },
                ["name", "model"],
            ),
            write,
            lambda args: _set_default_model(owner, args),
        ),
        "ops_update_provider": ToolSpec(
            "ops_update_provider",
            "修改已有厂商的启停、说明、模型目录或默认模型；密钥不进入对话。",
            _object(
                {
                    "name": {"type": "string", "minLength": 1, "maxLength": 80},
                    "default_model": {"type": "string", "maxLength": 160},
                    "models": {"type": "array", "items": {}},
                    "is_active": {"type": "boolean"},
                    "note": {"type": "string", "maxLength": 500},
                },
                ["name"],
            ),
            write,
            lambda args: _update_provider(owner, args),
        ),
        "ops_delete_provider": ToolSpec(
            "ops_delete_provider",
            "删除一个已配置的厂商。",
            _object({"name": {"type": "string", "minLength": 1, "maxLength": 80}}, ["name"]),
            write,
            lambda args: _delete_provider(owner, args),
        ),
        "ops_jobs_list": ToolSpec(
            "ops_jobs_list", "读取任务列表。", _object({}), read, lambda args: _jobs_list(owner, args)
        ),
        "ops_job_create": ToolSpec(
            "ops_job_create",
            "创建已支持类型的运维任务。",
            _object(
                {
                    "name": {"type": "string", "minLength": 1, "maxLength": 120},
                    "kind": {"type": "string"},
                    "cron": {"type": "string"},
                    "config": {"type": "object"},
                    "enabled": {"type": "boolean"},
                },
                ["name", "kind"],
            ),
            write,
            lambda args: _job_create(owner, args),
        ),
        "ops_job_update": ToolSpec(
            "ops_job_update",
            "更新运维任务。",
            _object(
                {
                    "job_id": {"type": "string", "minLength": 1},
                    "name": {"type": "string"},
                    "cron": {"type": "string"},
                    "config": {"type": "object"},
                    "enabled": {"type": "boolean"},
                },
                ["job_id"],
            ),
            write,
            lambda args: _job_update(owner, args),
        ),
        "ops_job_delete": ToolSpec(
            "ops_job_delete",
            "删除运维任务。",
            _object({"job_id": {"type": "string", "minLength": 1}}, ["job_id"]),
            write,
            lambda args: _job_delete(owner, args),
        ),
        "ops_job_trigger": ToolSpec(
            "ops_job_trigger",
            "在后台立即执行一个已有任务，并持续回传进度。",
            _object({"job_id": {"type": "string", "minLength": 1}}, ["job_id"]),
            write,
            lambda args: _job_trigger(owner, args),
        ),
    }


def _provider_catalog(owner: Any, _: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import _FORBIDDEN, _ok
    from src.ops import OpsStore

    with OpsStore(owner.ops_db) as store:
        rows = store.list_providers()
    return _ok(
        [{key: value for key, value in row.items() if not _FORBIDDEN.search(str(key))} for row in rows]
    )


def _set_default_provider(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import AssistantError, _ok
    from src.ops import OpsStore

    name = str(args["name"]).strip()
    owner._grant("ops.set_default_provider", name, {"name": name})
    with OpsStore(owner.ops_db) as store:
        if not store.set_default_provider(name):
            raise AssistantError("未配置的供应商")
    return _ok({"name": name, "is_default": True})


def _set_default_model(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import AssistantError, _ok
    from src.ops import OpsStore

    name, model = str(args["name"]).strip(), str(args["model"]).strip()
    owner._grant("ops.set_default_model", name, {"name": name, "model": model})
    with OpsStore(owner.ops_db) as store:
        existing = store.get_provider(name)
        if existing is None or model not in existing.get("models", []):
            raise AssistantError("供应商或已配置模型不存在")
        store.upsert_provider(
            {
                "name": existing["name"],
                "protocol": existing["protocol"],
                "base_url": existing["base_url"],
                "default_model": model,
                "models": existing["model_catalog"],
                "is_active": existing["is_active"],
                "is_default": existing["is_default"],
                "note": existing.get("note", ""),
            }
        )
    return _ok({"name": name, "model": model})


def _update_provider(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import AssistantError, _FORBIDDEN, _ok
    from src.ops import OpsStore

    name = str(args["name"]).strip()
    values = {key: args[key] for key in ("default_model", "models", "is_active", "note") if key in args}
    if not values:
        raise AssistantError("必须提供至少一个厂商更新字段")
    grant = owner._grant("ops.update_provider", name, {"name": name, **values})
    with OpsStore(owner.ops_db) as store:
        existing = store.get_provider(name)
        if existing is None:
            raise AssistantError("未配置的供应商")
        store.upsert_provider(
            {
                "id": existing["id"],
                "name": existing["name"],
                "protocol": existing["protocol"],
                "base_url": existing["base_url"],
                "default_model": str(values.get("default_model", existing["default_model"])),
                "models": values.get("models", existing["model_catalog"]),
                "is_active": bool(values.get("is_active", existing["is_active"])),
                "is_default": existing["is_default"],
                "note": str(values.get("note", existing.get("note", ""))),
                "models_synced_at": existing.get("models_synced_at", ""),
                "validated_at": existing.get("validated_at", ""),
                "proxy_url": existing.get("proxy_url", ""),
            }
        )
        updated = store.get_provider(name)
    public = {key: value for key, value in (updated or {}).items() if not _FORBIDDEN.search(key)}
    return _ok({**public, "idempotency_key": grant})


def _delete_provider(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import AssistantError, _ok
    from src.ops import OpsStore

    name = str(args["name"]).strip()
    grant = owner._grant("ops.delete_provider", name, {"name": name})
    with OpsStore(owner.ops_db) as store:
        if not store.delete_provider(name):
            raise AssistantError("未配置的供应商")
    return _ok({"name": name, "removed": True, "idempotency_key": grant})


def _jobs_list(owner: Any, _: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import _ok
    from src.ops import OpsStore

    with OpsStore(owner.ops_db) as store:
        return _ok(store.list_jobs())


def _validate_cron(cron: str) -> None:
    if not cron.strip():
        return
    from src.ai.application.system_toolbus import AssistantError
    from src.ops import SchedulerError, validate_cron

    try:
        validate_cron(cron)
    except SchedulerError as exc:
        raise AssistantError(str(exc)) from exc


def _job_create(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import AssistantError, _ok, _safe
    from src.ops import OpsError, OpsStore

    values = {key: args[key] for key in ("name", "kind")}
    values.update({key: args[key] for key in ("cron", "config", "enabled") if key in args})
    values["kind"] = str(values["kind"]).lower()
    if values["kind"] not in _ASSISTANT_JOB_KINDS:
        raise AssistantError("助手仅可创建受控的行情、选股、回测、比较、优化、清理或复盘任务")
    _safe(values.get("config") or {})
    _validate_job_config(values["kind"], values.get("config") or {})
    _validate_cron(str(values.get("cron") or ""))
    grant = owner._grant("ops.create_job", str(values["name"]), values)
    try:
        with OpsStore(owner.ops_db) as store:
            job_id = store.create_job(
                name=str(values["name"]),
                kind=str(values["kind"]),
                cron=str(values.get("cron") or ""),
                config=values.get("config") or {},
                enabled=bool(values.get("enabled", True)),
            )
            job = store.get_job(job_id)
    except OpsError as exc:
        raise AssistantError(str(exc)) from exc
    owner._reload_scheduler()
    return _ok({**(job or {}), "idempotency_key": grant})


def _job_update(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import AssistantError, _ok, _safe
    from src.ops import OpsError, OpsStore

    job_id = str(args["job_id"])
    values = {key: args[key] for key in ("name", "cron", "config", "enabled") if key in args}
    if not values:
        raise AssistantError("必须提供至少一个任务更新字段")
    _safe(values.get("config") or {})
    if "cron" in values:
        _validate_cron(str(values["cron"]))
    try:
        with OpsStore(owner.ops_db) as store:
            job = store.get_job(job_id)
            if job is None:
                raise AssistantError("未知任务")
            if str(job["kind"]) not in _ASSISTANT_JOB_KINDS:
                raise AssistantError("该任务类型不能由全局助手修改")
            if "config" in values:
                _validate_job_config(str(job["kind"]), values["config"])
            owner._grant("ops.update_job", str(job["name"]), values)
            if not store.update_job(
                job_id,
                expected_name=str(job["name"]),
                allowed_kinds=_ASSISTANT_JOB_KINDS,
                **values,
            ):
                raise AssistantError("任务在授权期间已变化，拒绝更新")
            job = store.get_job(job_id)
    except OpsError as exc:
        raise AssistantError(str(exc)) from exc
    owner._reload_scheduler()
    return _ok(job)


def _job_delete(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import AssistantError, _ok
    from src.ops import OpsStore

    job_id = str(args["job_id"])
    with OpsStore(owner.ops_db) as store:
        job = store.get_job(job_id)
        if job is None:
            raise AssistantError("未知任务")
        if str(job["kind"]) not in _ASSISTANT_JOB_KINDS:
            raise AssistantError("该任务类型不能由全局助手删除")
        owner._grant("ops.delete_job", str(job["name"]), {"name": str(job["name"])})
        if not store.delete_job(
            job_id,
            expected_name=str(job["name"]),
            allowed_kinds=_ASSISTANT_JOB_KINDS,
        ):
            raise AssistantError("任务在授权期间已变化，拒绝删除")
    owner._reload_scheduler()
    return _ok({"removed": True})


def _job_trigger(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import AssistantError, _ok
    from src.ops import JobContext, OpsStore

    job_id = str(args["job_id"])
    with OpsStore(owner.ops_db) as store:
        job = store.get_job(job_id)
    if job is None:
        raise AssistantError("未知任务")
    if str(job["kind"]) not in _ASSISTANT_JOB_KINDS:
        raise AssistantError("该任务类型不能由全局助手触发")
    binding = {
        "job_id": str(job["id"]),
        "name": str(job["name"]),
        "kind": str(job["kind"]),
        "config": job.get("config") if isinstance(job.get("config"), dict) else {},
    }
    grant = owner._grant("ops.trigger_job", str(job["name"]), binding)
    grant_id = owner._last_grant_id

    def run_in_background() -> None:
        agent_id = f"job:{job_id}"
        if owner.on_event:
            owner.on_event(
                {
                    "type": "subagent_start",
                    "id": agent_id,
                    "name": job["name"],
                    "progress": 5,
                    "detail": "后台任务已提交",
                }
            )
            owner.on_event(
                {
                    "type": "subagent_progress",
                    "id": agent_id,
                    "name": job["name"],
                    "progress": 20,
                    "detail": "正在执行任务",
                }
            )
        try:
            from src.ops import run_job

            with OpsStore(owner.ops_db) as store:
                current = store.get_job(job_id)
                if current is None:
                    raise AssistantError("任务已删除")
                current_binding = {
                    "job_id": str(current["id"]),
                    "name": str(current["name"]),
                    "kind": str(current["kind"]),
                    "config": current.get("config") if isinstance(current.get("config"), dict) else {},
                }
                if str(current["kind"]) not in _ASSISTANT_JOB_KINDS or current_binding != binding:
                    raise AssistantError("任务在授权后已变化，拒绝触发")
                outcome = run_job(
                    store,
                    current,
                    context=JobContext(market_db=owner.market_db, palace_db=owner.palace_db),
                    trigger="ai_assistant",
                )
            succeeded = outcome.get("status") in {"success", "skipped"}
            owner._finalize_grant(
                grant_id,
                {"job_id": job_id, "status": outcome.get("status")},
                status="completed" if succeeded else "failed",
            )
            if owner.on_event:
                owner.on_event(
                    {
                        "type": "subagent_end",
                        "id": agent_id,
                        "name": job["name"],
                        "ok": outcome.get("status") in {"success", "skipped"},
                        "progress": 100,
                        "detail": str(outcome.get("status") or "完成"),
                    }
                )
        except Exception as exc:
            owner._finalize_grant(
                grant_id,
                {"job_id": job_id, "error": f"{type(exc).__name__}: {exc}"},
                status="failed",
            )
            if owner.on_event:
                owner.on_event(
                    {
                        "type": "subagent_end",
                        "id": agent_id,
                        "name": job["name"],
                        "ok": False,
                        "progress": 100,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                )

    thread = Thread(target=run_in_background, name=f"ai-job-{job_id}", daemon=True)
    owner._background_threads.append(thread)
    thread.start()
    result = _ok({"job_id": job_id, "name": job["name"], "status": "queued", "idempotency_key": grant})
    result["_grant_deferred"] = True
    return result
