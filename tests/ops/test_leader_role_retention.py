"""角色留痕的保留窗与纸面舱闸门调参一致性。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.ops.application.jobs.context import JobContext
from src.ops.application.jobs.prune import execute_prune
from src.ops.application.skill_watch.role_stats import role_transitions
from src.ops.infrastructure.store import OpsStore


def _day(offset: int) -> str:
    return (datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=offset)).isoformat()


def _record(store: OpsStore, *, trade_date: str, role: str) -> None:
    store.record_leader_roles(
        "dragon-return",
        trade_date=trade_date,
        observed_at=f"{trade_date}T09:40:00+08:00",
        gate_state="dragon",
        entries=[{"code": "600001", "name": "测试龙", "role": role}],
    )


def test_prune_drops_role_history_outside_the_keep_window(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        _record(store, trade_date=_day(120), role="leader")
        _record(store, trade_date=_day(1), role="weakened")

        result = execute_prune(
            {"leader_role_keep_days": 60}, JobContext(ops_store=store)
        )
        remaining = store.list_leader_roles("dragon-return")

    assert result["leader_roles_removed"] == 1
    assert [row["trade_date"] for row in remaining] == [_day(1)]


def test_prune_can_keep_full_role_history(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as store:
        _record(store, trade_date=_day(400), role="leader")

        result = execute_prune({"leader_role_keep_days": 0}, JobContext(ops_store=store))

        assert result["leader_roles_removed"] == 0
        assert len(store.list_leader_roles("dragon-return")) == 1


def test_role_history_keeps_every_observation_for_transitions(tmp_path: Path) -> None:
    """同日多次观测必须都留下，否则角色演进会像 intel_snapshots 那样被覆盖掉。"""
    today = _day(0)
    with OpsStore(tmp_path / "ops.db") as store:
        store.record_leader_roles(
            "dragon-return",
            trade_date=today,
            observed_at=f"{today}T09:40:00+08:00",
            gate_state="dragon",
            entries=[{"code": "600001", "name": "测试龙", "role": "leader"}],
        )
        store.record_leader_roles(
            "dragon-return",
            trade_date=today,
            observed_at=f"{today}T14:20:00+08:00",
            gate_state="observe",
            entries=[{"code": "600001", "name": "测试龙", "role": "weakened"}],
        )

        assert len(store.list_leader_roles("dragon-return")) == 2
        transitions = role_transitions(store.list_leader_roles("dragon-return"))

    assert len(transitions) == 1
    assert transitions[0]["from_role"] == "leader"
    assert transitions[0]["to_role"] == "weakened"


def test_paper_cabin_gate_follows_skill_tuning(tmp_path: Path, monkeypatch) -> None:
    """纸面舱闸门必须复用战法调参，不能自成一套阈值。"""
    from src.ops.application.jobs.paper_quant_support import (
        _resolve_market_gate,
        clear_market_gate_cache,
    )
    from src.ops.application.skill_watch import tuning as tuning_mod

    clear_market_gate_cache()
    seen: dict[str, object] = {}

    def fake_scan(_call_tool, *, params=None, **_kwargs):
        seen["params"] = params
        return {"state": "dragon", "entry_allowed": True}

    monkeypatch.setattr(
        "src.ops.application.skill_watch.market_regime.scan_market_gate", fake_scan
    )
    monkeypatch.setattr(
        "src.ops.application.skill_watch.wudao_availability_for_watch",
        lambda: {"available": True},
    )

    with OpsStore(tmp_path / "ops.db") as store:
        tuning_mod.save_tuning(store, "dragon-return", {"gate": {"promotion_attack": 0.55}})
        gate = _resolve_market_gate("dragon-return", {}, store=store)

        assert gate is not None
        assert seen["params"]["promotion_attack"] == 0.55

        # 关掉闸门这一段后 fail-closed：禁开仓，不得静默放行（也不得命中旧缓存）
        tuning_mod.save_tuning(store, "dragon-return", {"stages": {"market_gate": False}})
        disabled = _resolve_market_gate("dragon-return", {}, store=store)
        assert disabled is not None
        assert disabled["entry_allowed"] is False
        assert "market_gate_disabled" in disabled["quality_warnings"]
    clear_market_gate_cache()
