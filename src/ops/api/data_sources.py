"""数据线路运维 HTTP。"""
from __future__ import annotations

from math import isfinite
from statistics import median
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.app.legacy.quant_common import LaneProviderPatch


class _LaneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LaneProbePayload(_LaneRequest):
    lane: str | None = Field(default=None, max_length=64)
    adapter_id: str | None = Field(default=None, max_length=64)
    code: str | None = Field(default=None, max_length=6)
    runs: int = Field(default=1, ge=1, le=3)


class LaneSpeedtestPayload(_LaneRequest):
    lane: str = Field(default="hist_daily", max_length=64)
    code: str | None = Field(default=None, max_length=6)
    runs: int = Field(default=1, ge=1, le=3)


class LanePolicyPayload(_LaneRequest):
    mode: Literal["auto", "manual"] = "auto"
    provider_id: str | None = Field(default=None, max_length=64)
    fallback: bool = False


_LANE_LABELS: dict[str, str] = {
    "hist_daily": "历史日 K",
    "spot_batch": "实时快照",
    "instruments": "证券列表",
    "adjust_factor": "复权因子",
    "minute_bars": "分钟 K",
    "capital_flow": "个股资金流",
    "intel_mcp": "外部情报",
}
_LANE_REQUIRED: dict[str, bool] = {
    "hist_daily": True,
    "spot_batch": True,
    "instruments": True,
    "adjust_factor": True,
    "minute_bars": False,
    "capital_flow": False,
    "intel_mcp": False,
}


def _lane_code(value: str | None) -> str:
    code = (value or "600519").strip()
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=422, detail="code 必须是 6 位数字")
    return code


def _median_value(rows: list[dict[str, Any]], field: str) -> float | None:
    """只统计成功轮的有效耗时，失败不能被伪装成 0ms。"""
    values: list[float] = []
    for row in rows:
        if not row.get("ok"):
            continue
        try:
            value = float(row.get(field))
        except (TypeError, ValueError):
            continue
        if isfinite(value) and value >= 0:
            values.append(value)
    return float(median(values)) if values else None


def build_data_sources_router(*, write_dependency) -> APIRouter:
    """构造数据源线路路由。"""
    router = APIRouter()
    write_guard = Depends(write_dependency)

    @router.get("/api/ops/lanes", tags=["ops"])
    def get_lanes_catalog() -> dict[str, Any]:
        """可接入 API 目录 + 类目清单。转换规则在适配器代码里，这里只列名片。

        ``enabled`` 是源总开关；``disabled_lanes`` 是被单独关掉的工具（lane），
        两者合起来才是「这家在这条线路上到底能不能用」。
        """
        from src.market import (
            ALL_LANES,
            enabled_adapter_ids,
            get_adapter,
            lane_route_policy,
            list_catalog,
            provider_disabled_lanes,
            provider_master_enabled,
        )
        from src.shared.paths import load_config

        config = load_config()
        providers = []
        for entry in list_catalog():
            provider_id = str(entry.get("id") or "")
            providers.append(
                {
                    **entry,
                    "enabled": provider_master_enabled(provider_id, config=config),
                    "disabled_lanes": provider_disabled_lanes(provider_id, config=config),
                }
            )
        lanes = [
            {
                "id": lane_id,
                "label": _LANE_LABELS.get(lane_id, lane_id),
                "required": _LANE_REQUIRED.get(lane_id, False),
                "policy": lane_route_policy(lane_id, config=config),
                "effective_provider_ids": enabled_adapter_ids(lane_id, config=config),
            }
            for lane_id in ALL_LANES
        ]
        policies = [
            {
                "lane": str(item["id"]),
                **dict(item["policy"]),
                "effective_provider_ids": list(item["effective_provider_ids"]),
            }
            for item in lanes
        ]
        return {
            "lanes": lanes,
            "providers": providers,
            "policies": policies,
            "summary": {"ok": 0, "degraded": 0, "down": 0},
        }

    @router.post("/api/ops/lanes/probe", tags=["ops"])
    def post_lanes_probe(
        payload: LaneProbePayload,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """探测连通性。类目内并行；未指定 lane 则逐类目探测。"""
        from src.market import (
            ALL_LANES,
            enabled_adapter_ids,
            get_adapter,
            list_catalog,
            probe_lane,
        )

        label_by_id = {
            str(entry.get("id")): str(entry.get("label") or entry.get("id"))
            for entry in list_catalog()
        }
        only_id = (payload.adapter_id or "").strip() or None
        if only_id:
            try:
                get_adapter(only_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=f"未知接入：{only_id}") from exc

        def ids_for(lane: str) -> list[str]:
            if only_id:
                adapter = get_adapter(only_id)
                return [only_id] if lane in adapter.meta.lanes else []
            return enabled_adapter_ids(lane)

        target = (payload.lane or "").strip() or None
        lane_ids = [target] if target else list(ALL_LANES)
        if target and target not in ALL_LANES:
            raise HTTPException(status_code=400, detail=f"未知类目：{target}")

        code = _lane_code(payload.code)
        rounds_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
        all_rounds: list[dict[str, Any]] = []
        for lane_id in lane_ids:
            ids = ids_for(lane_id)
            if not ids:
                continue
            for run in range(1, payload.runs + 1):
                for item in probe_lane(lane_id, adapter_ids=ids, code=code):
                    row = item.to_dict()
                    row["label"] = label_by_id.get(item.adapter_id, item.adapter_id)
                    row["run"] = run
                    rounds_by_key.setdefault((lane_id, item.adapter_id), []).append(row)
                    all_rounds.append(dict(row))
        results = []
        for adapter_rounds in rounds_by_key.values():
            current = dict(adapter_rounds[-1])
            rtt = _median_value(adapter_rounds, "rtt_ms")
            current.update(
                ok=any(bool(row.get("ok")) for row in adapter_rounds),
                rtt_ms=round(rtt, 2) if rtt is not None else None,
                median_rtt_ms=round(rtt, 2) if rtt is not None else None,
                failed_runs=sum(not bool(row.get("ok")) for row in adapter_rounds),
                rounds=adapter_rounds,
            )
            results.append(current)
        return {
            "code": code,
            "runs": payload.runs,
            "results": results,
            "rounds": all_rounds,
        }

    @router.post("/api/ops/lanes/speedtest", tags=["ops"])
    def post_lanes_speedtest(
        payload: LaneSpeedtestPayload,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """同类下载测速。P0 仅支持历史日 K。"""
        from src.market import (
            LANE_HIST_DAILY,
            enabled_adapter_ids,
            list_catalog,
            speedtest_daily,
        )

        lane = (payload.lane or LANE_HIST_DAILY).strip()
        if lane != LANE_HIST_DAILY:
            raise HTTPException(
                status_code=400,
                detail="下载测速目前仅支持历史日 K（hist_daily）",
            )
        code = _lane_code(payload.code)
        adapter_ids = enabled_adapter_ids(LANE_HIST_DAILY)
        if not adapter_ids:
            return {"lane": lane, "code": code, "runs": payload.runs, "results": []}
        label_by_id = {
            str(entry.get("id")): str(entry.get("label") or entry.get("id"))
            for entry in list_catalog()
        }
        rounds_by_id: dict[str, list[dict[str, Any]]] = {}
        all_rounds: list[dict[str, Any]] = []
        for run in range(1, payload.runs + 1):
            for item in speedtest_daily(code, adapter_ids=adapter_ids):
                row = item.to_dict()
                row["label"] = label_by_id.get(item.adapter_id, item.adapter_id)
                row["run"] = run
                rounds_by_id.setdefault(item.adapter_id, []).append(row)
                all_rounds.append(dict(row))
        rows = []
        for adapter_rounds in rounds_by_id.values():
            current = dict(adapter_rounds[-1])
            elapsed = _median_value(adapter_rounds, "elapsed_ms")
            current.update(
                ok=any(bool(row.get("ok")) for row in adapter_rounds),
                elapsed_ms=round(elapsed, 2) if elapsed is not None else None,
                median_rtt_ms=round(elapsed, 2) if elapsed is not None else None,
                failed_runs=sum(not bool(row.get("ok")) for row in adapter_rounds),
                rounds=adapter_rounds,
            )
            rows.append(current)
        return {
            "lane": lane,
            "code": code,
            "runs": payload.runs,
            "results": rows,
            "rounds": all_rounds,
        }

    @router.put("/api/ops/lanes/{lane}/policy", tags=["ops"])
    def put_lane_policy(
        lane: str,
        payload: LanePolicyPayload,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """保存单 lane 的显式选源策略，并使该 lane 的粘性赢家失效。"""
        from src.market import ALL_LANES, clear_sticky, get_adapter, lane_provider_enabled
        from src.shared.paths import load_config, save_config

        if lane not in ALL_LANES:
            raise HTTPException(status_code=422, detail=f"未知类目：{lane}")
        policy: dict[str, Any] = {"mode": payload.mode, "fallback": payload.fallback}
        if payload.mode == "manual":
            provider_id = (payload.provider_id or "").strip()
            if not provider_id:
                raise HTTPException(status_code=422, detail="manual 模式必须指定 provider_id")
            try:
                adapter = get_adapter(provider_id)
            except KeyError as exc:
                raise HTTPException(status_code=422, detail=f"未知接入：{provider_id}") from exc
            if lane not in adapter.meta.lanes:
                raise HTTPException(status_code=422, detail=f"{provider_id} 不支持类目：{lane}")
            if not lane_provider_enabled(provider_id, lane):
                raise HTTPException(status_code=422, detail=f"{provider_id} 在该线路已停用")
            policy["provider_id"] = provider_id
        config = load_config()
        routes = config.get("lane_routes")
        routes = dict(routes) if isinstance(routes, dict) else {}
        routes[lane] = policy
        save_config({"lane_routes": routes})
        clear_sticky(lane)
        return {"lane": lane, "policy": policy}

    @router.patch("/api/ops/lanes/providers/{provider_id}", tags=["ops"])
    def patch_lane_provider(
        provider_id: str,
        payload: LaneProviderPatch,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        """启用/禁用某家接入。带 ``lane`` 时只动那一个工具，不带则是源总开关。

        只改开关，不改转换规则。必需线路被关空不拦，由目录里的
        ``effective_provider_ids`` 让界面自己红字提醒——单源线路（复权因子、
        证券列表）否则会永远关不掉。
        """
        from src.market import (
            clear_sticky,
            get_adapter,
            provider_disabled_lanes,
            provider_master_enabled,
        )
        from src.shared.paths import load_config, save_config

        try:
            adapter = get_adapter(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"未知接入：{provider_id}") from exc
        target_lane = (payload.lane or "").strip() or None
        if target_lane is not None and target_lane not in adapter.meta.lanes:
            raise HTTPException(
                status_code=422, detail=f"{provider_id} 不支持类目：{target_lane}"
            )
        config = load_config()
        raw_table = config.get("lane_providers")
        table = dict(raw_table) if isinstance(raw_table, dict) else {}
        raw_entry = table.get(provider_id)
        entry = dict(raw_entry) if isinstance(raw_entry, dict) else {}
        if target_lane is None:
            entry["enabled"] = bool(payload.enabled)
        else:
            raw_lanes = entry.get("lanes")
            lanes = dict(raw_lanes) if isinstance(raw_lanes, dict) else {}
            lanes[target_lane] = bool(payload.enabled)
            entry["lanes"] = lanes
        table[provider_id] = entry
        save_config({"lane_providers": table})
        if not payload.enabled:
            # 停用后清粘性，避免下一次还钉着已关的源
            for lane_id in [target_lane] if target_lane else adapter.meta.lanes:
                clear_sticky(lane_id)
        saved = {**config, "lane_providers": table}
        return {
            "id": provider_id,
            "label": adapter.meta.label,
            "enabled": provider_master_enabled(provider_id, config=saved),
            "disabled_lanes": provider_disabled_lanes(provider_id, config=saved),
        }

    return router
