from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

import pandas as pd

from src.ai.application.system_toolbus import build_system_toolbus
from src.ledger import PalaceStore
from src.market import MarketStore
from src.ops import OpsStore


def _bus(root: Path, *, grants: bool = True, scheduler_reloader=None):
    def issuer(action: str, target: str, parameters: dict):
        return {"id": "grant-1"} if grants else None

    return build_system_toolbus(
        palace_db=str(root / "palace.db"), market_db=str(root / "market.db"), ops_db=str(root / "ops.db"),
        grant_issuer=issuer, grant_consumer=lambda *_: "idem-1",
        scheduler_reloader=scheduler_reloader,
    )


def _qianlong_decisions() -> list[dict[str, str]]:
    return [
        {
            "code": f"60000{index}",
            "name": f"标的{index}",
            "decision": "精选" if index < 2 else "观察",
            "reason": "结构完整",
            "timing": "次日回踩" if index < 2 else "",
            "invalidation": "跌破前低" if index < 2 else "",
        }
        for index in range(6)
    ]


def _seed_qianlong_pool(root: Path, *, day: str, pool_id: str) -> None:
    with PalaceStore(root / "palace.db") as palace:
        for row in _qianlong_decisions():
            palace.record_candidate(
                code=row["code"],
                name=row["name"],
                decision="观察",
                reason="等待潜龙精选",
                occurred_on=day,
                pool_id=pool_id,
            )


def test_static_catalog_excludes_dynamic_execution_surfaces(tmp_path: Path) -> None:
    bus = _bus(tmp_path)
    names = {item["name"] for item in bus.catalog()}
    assert "ledger_dashboard" in names
    assert "market_kline" in names
    assert "qianlong_commit" in names
    assert not any("sql" in name or "shell" in name or "mcp" in name or "cli" in name for name in names)
    assert not any(name.startswith("ops_setting") for name in names)
    assert bus.executor("unknown_tool", {})["is_error"]
    assert bus.executor("market_search", {"query": "https://bad.example"})["is_error"]


def test_qianlong_commit_writes_entire_constrained_pool_with_audit_source(tmp_path: Path) -> None:
    day, pool_id = "2026-08-01", "POOL-1"
    _seed_qianlong_pool(tmp_path, day=day, pool_id=pool_id)
    bus = _bus(tmp_path)
    decisions = _qianlong_decisions()

    missing_snapshot = bus.executor(
        "qianlong_commit", {"occurred_on": day, "pool_id": pool_id, "decisions": decisions}
    )
    assert missing_snapshot["is_error"]
    assert "先读取" in missing_snapshot["text"]
    assert not bus.executor("qianlong_candidate_pool", {"occurred_on": day, "pool_id": pool_id})["is_error"]
    assert not bus.executor("qianlong_pool_evidence", {"occurred_on": day, "pool_id": pool_id})["is_error"]

    mismatched = [*decisions]
    mismatched[-1] = {**mismatched[-1], "code": "600099"}
    assert bus.executor(
        "qianlong_commit", {"occurred_on": day, "pool_id": pool_id, "decisions": mismatched}
    )["is_error"]

    result = bus.executor(
        "qianlong_commit", {"occurred_on": day, "pool_id": pool_id, "decisions": decisions}
    )
    assert not result["is_error"]
    with PalaceStore(tmp_path / "palace.db") as palace:
        rows = palace.candidates_payload(day)
    assert len(rows) == 6
    assert sum(row["decision"] == "精选" for row in rows) == 2
    assert all(row["source"] == "ai_assistant" for row in rows)
    assert rows[0]["evidence"]["source"] == "ai_assistant"


def test_qianlong_commit_rolls_back_the_entire_pool_when_a_late_write_fails(tmp_path: Path) -> None:
    day, pool_id = "2026-08-01", "POOL-ROLLBACK"
    _seed_qianlong_pool(tmp_path, day=day, pool_id=pool_id)
    bus = _bus(tmp_path)
    decisions = _qianlong_decisions()
    bus.executor("qianlong_candidate_pool", {"occurred_on": day, "pool_id": pool_id})
    bus.executor("qianlong_pool_evidence", {"occurred_on": day, "pool_id": pool_id})
    original = PalaceStore.record_candidate

    def fail_on_last(store, **values):
        if values["code"] == decisions[-1]["code"]:
            raise RuntimeError("late candidate failure")
        return original(store, **values)

    with patch.object(PalaceStore, "record_candidate", new=fail_on_last):
        result = bus.executor(
            "qianlong_commit", {"occurred_on": day, "pool_id": pool_id, "decisions": decisions}
        )
    assert result["is_error"]
    with PalaceStore(tmp_path / "palace.db") as palace:
        assert {row["decision"] for row in palace.candidates_payload(day)} == {"观察"}


def test_qianlong_evidence_includes_price_ma_and_volume_context(tmp_path: Path) -> None:
    day, pool_id = "2026-08-01", "POOL-K"
    with PalaceStore(tmp_path / "palace.db") as palace:
        palace.record_candidate(
            code="600000", name="浦发银行", decision="观察", reason="等待确认", occurred_on=day, pool_id=pool_id,
        )
    dates = pd.date_range(end=day, periods=20, freq="D").strftime("%Y-%m-%d")
    closes = [10 + index for index in range(20)]
    with MarketStore(tmp_path / "market.db") as market:
        market.upsert_quotes(
            "600000",
            pd.DataFrame(
                {
                    "date": dates,
                    "open": closes,
                    "high": [value + 1 for value in closes],
                    "low": [value - 1 for value in closes],
                    "close": closes,
                    "volume": [100] * 19 + [200],
                    "amount": [value * 100 for value in closes],
                    "outstanding_share": [1_000_000] * 20,
                    "turnover": [0.01] * 20,
                }
            ),
        )
    evidence = _bus(tmp_path).executor(
        "qianlong_pool_evidence", {"occurred_on": day, "pool_id": pool_id}
    )["structured"]["candidates"][0]
    assert evidence["pct_chg"] == 3.57
    assert evidence["ma5_gap_pct"] == 7.41
    assert evidence["ma20_gap_pct"] == 48.72
    assert evidence["volume_ratio"] == 2


def test_write_tool_refuses_without_server_grant(tmp_path: Path) -> None:
    result = _bus(tmp_path, grants=False).executor("ledger_record_trade", {"action": "BUY", "code": "600000", "shares": 100, "price": 10})
    assert result["is_error"]
    assert "凭据" in result["text"]


def test_owner_tools_adjust_positions_and_cover_mutable_ledgers(tmp_path: Path) -> None:
    bus = _bus(tmp_path)
    adjusted = bus.executor(
        "ledger_adjust_positions",
        {
            "trades": [
                {"action": "BUY", "code": "600000", "shares": 200, "price": 10, "name": "浦发银行"},
                {"action": "SELL", "code": "600000", "shares": 100, "price": 12, "name": "浦发银行"},
            ]
        },
    )
    assert not adjusted["is_error"]
    assert adjusted["structured"]["records"][-1]["cost_after"] == 8
    with PalaceStore(tmp_path / "palace.db") as palace:
        position = palace.positions_payload()[0]
        assert position["shares"] == 100
        assert position["cost"] == 8

    assert not bus.executor("ledger_record_cashflow", {"amount": 5000, "note": "入金"})["is_error"]
    assert not bus.executor("ledger_record_daily_pnl", {"broker_pnl": 120})["is_error"]
    assert not bus.executor("ledger_record_snapshot", {"total_assets": 30000, "cash": 18000})["is_error"]
    candidate = bus.executor(
        "ledger_upsert_candidate",
        {"code": "600001", "name": "样本", "decision": "观察", "reason": "等待确认"},
    )
    assert not candidate["is_error"]
    candidate_id = candidate["structured"]["id"]
    assert not bus.executor("ledger_delete_candidate", {"candidate_id": candidate_id})["is_error"]
    assert not bus.executor(
        "ledger_record_plan",
        {"code": "600000", "title": "回踩预案", "scenario": "回踩承接", "layers": 1},
    )["is_error"]


def test_owner_tools_update_provider_without_exposing_system_settings(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as ops:
        ops.upsert_provider(
            {
                "name": "test-provider",
                "protocol": "openai_compatible",
                "base_url": "https://example.invalid/v1",
                "default_model": "m1",
                "models": ["m1"],
                "is_active": True,
            }
        )
    bus = _bus(tmp_path)
    updated = bus.executor(
        "ops_update_provider",
        {
            "name": "test-provider",
            "default_model": "m1",
            "models": [{"id": "m1", "max_output_tokens": 4096}],
            "note": "助手管理",
        },
    )
    assert not updated["is_error"]
    assert updated["structured"]["note"] == "助手管理"
    assert updated["structured"]["model_catalog"][0]["max_output_tokens"] == 4096


def test_assistant_jobs_are_whitelisted_and_reload_scheduler(tmp_path: Path) -> None:
    reloads: list[bool] = []
    bus = _bus(tmp_path, scheduler_reloader=lambda: reloads.append(True))
    for kind in ("skill", "notify"):
        result = bus.executor("ops_job_create", {"name": f"blocked-{kind}", "kind": kind})
        assert result["is_error"]

    with OpsStore(tmp_path / "ops.db") as ops:
        skill_id = ops.create_job(name="private-skill", kind="skill")
    assert bus.executor("ops_job_update", {"job_id": skill_id, "enabled": False})["is_error"]
    assert bus.executor("ops_job_delete", {"job_id": skill_id})["is_error"]
    assert bus.executor("ops_job_trigger", {"job_id": skill_id})["is_error"]

    created = bus.executor("ops_job_create", {"name": "允许同步", "kind": "sync"})
    assert not created["is_error"]
    job_id = created["structured"]["id"]
    assert not bus.executor("ops_job_update", {"job_id": job_id, "enabled": False})["is_error"]
    assert not bus.executor("ops_job_delete", {"job_id": job_id})["is_error"]
    assert len(reloads) == 3


def test_assistant_job_mutations_bind_checked_name_and_kind(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as ops:
        job_id = ops.create_job(name="受控任务", kind="sync")
    bus = _bus(tmp_path)

    with patch.object(OpsStore, "update_job", return_value=False) as update:
        rejected_update = bus.executor("ops_job_update", {"job_id": job_id, "enabled": False})
    assert rejected_update["is_error"]
    update.assert_called_once_with(
        job_id,
        expected_name="受控任务",
        allowed_kinds={"sync", "screen", "backtest", "compare", "optimize", "prune", "outcome"},
        enabled=False,
    )

    with patch.object(OpsStore, "delete_job", return_value=False) as delete:
        rejected_delete = bus.executor("ops_job_delete", {"job_id": job_id})
    assert rejected_delete["is_error"]
    delete.assert_called_once_with(
        job_id,
        expected_name="受控任务",
        allowed_kinds={"sync", "screen", "backtest", "compare", "optimize", "prune", "outcome"},
    )


def test_assistant_job_configs_reject_unbounded_sync_work(tmp_path: Path) -> None:
    bus = _bus(tmp_path)
    workers = bus.executor(
        "ops_job_create",
        {"name": "too-many-workers", "kind": "sync", "config": {"workers": 9}},
    )
    assert workers["is_error"]
    assert "workers" in workers["text"]

    codes = bus.executor(
        "ops_job_create",
        {
            "name": "too-many-codes",
            "kind": "sync",
            "config": {"codes": [f"{index:06d}" for index in range(501)]},
        },
    )
    assert codes["is_error"]
    assert "codes" in codes["text"]


def test_assistant_job_trigger_uses_its_own_databases(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as ops:
        job_id = ops.create_job(name="立即同步", kind="sync")
    captured: dict[str, object] = {}

    def run_job(_store, job, *, context, trigger):
        captured.update({"job": job, "context": context, "trigger": trigger})
        return {"status": "success"}

    bus = _bus(tmp_path)
    with patch("src.ops.application.jobs.run_job", side_effect=run_job):
        queued = bus.executor("ops_job_trigger", {"job_id": job_id})
        bus.wait_for_background_tasks()
    assert not queued["is_error"]
    assert captured["job"]["id"] == job_id
    assert captured["trigger"] == "ai_assistant"
    assert captured["context"].market_db == str(tmp_path / "market.db")
    assert captured["context"].palace_db == str(tmp_path / "palace.db")


def test_assistant_job_trigger_rejects_config_changed_after_grant(tmp_path: Path) -> None:
    with OpsStore(tmp_path / "ops.db") as ops:
        job_id = ops.create_job(name="受控同步", kind="sync", config={"workers": 1})
    created_threads: list[object] = []

    class DeferredThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target
            created_threads.append(self)

        def start(self) -> None:
            return None

    bus = _bus(tmp_path)
    events: list[dict] = []
    bus.on_event = events.append
    with patch("src.ai.application.system_toolbus_ops.Thread", DeferredThread), patch(
        "src.ops.application.jobs.run_job"
    ) as run_job:
        queued = bus.executor("ops_job_trigger", {"job_id": job_id})
        with OpsStore(tmp_path / "ops.db") as ops:
            assert ops.update_job(job_id, config={"workers": 2})
        created_threads[0].target()
    assert not queued["is_error"]
    run_job.assert_not_called()
    assert any(event["type"] == "subagent_end" and not event["ok"] for event in events)


def test_background_wait_detaches_after_cancellation(tmp_path: Path) -> None:
    events: list[dict] = []
    bus = _bus(tmp_path)
    bus.on_event = events.append
    release = Event()
    thread = Thread(target=release.wait, daemon=True)
    bus._background_threads.append(thread)
    thread.start()

    assert not bus.wait_for_background_tasks(is_cancelled=lambda: True, timeout=0.1)
    assert thread.is_alive()
    assert any(event["type"] == "warning" and "后台任务" in event["message"] for event in events)

    release.set()
    thread.join(timeout=1)
