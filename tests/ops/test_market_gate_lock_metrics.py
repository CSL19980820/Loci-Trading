"""market_gate / write_lock 锁等待观测（opt-in）。"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.market.infrastructure.write_lock import MarketWriteBusy, market_write_lock
from src.ops.application.jobs.context import JobError
from src.ops.application.jobs import market_gate as gate
from src.shared import observability


def test_market_gate_records_timeout_lock_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCI_OBSERVABILITY", "1")
    observability.reset_metrics()
    entered = threading.Event()
    release = threading.Event()

    def hold_sync() -> None:
        with gate.market_heavy_slot("sync", "holder"):
            entered.set()
            release.wait(timeout=5)

    worker = threading.Thread(target=hold_sync, daemon=True)
    worker.start()
    assert entered.wait(timeout=2)

    old_sync = gate.MARKET_LOCK_WAIT_SEC
    old_screen = gate.MARKET_SCREEN_LOCK_WAIT_SEC
    gate.MARKET_LOCK_WAIT_SEC = 0.2
    gate.MARKET_SCREEN_LOCK_WAIT_SEC = 0.2
    try:
        with pytest.raises(JobError):
            with gate.market_heavy_slot("screen", "waiter"):
                pass
    finally:
        gate.MARKET_LOCK_WAIT_SEC = old_sync
        gate.MARKET_SCREEN_LOCK_WAIT_SEC = old_screen
        release.set()
        worker.join(timeout=2)

    rows = observability.metrics_snapshot()
    wait_rows = [
        row
        for row in rows
        if row["name"] == "loci.lock.wait_ms"
        and row["labels"].get("component") == "market_gate"
        and row["labels"].get("outcome") == "timeout"
    ]
    assert wait_rows
    assert wait_rows[0]["value"] >= 150


def test_write_lock_records_busy_and_reentrant(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCI_OBSERVABILITY", "1")
    observability.reset_metrics()
    db_path = tmp_path / "market.db"
    db_path.write_bytes(b"")

    with market_write_lock(db_path, label="outer"):
        with market_write_lock(db_path, label="inner"):
            pass
    reentrant = [
        row
        for row in observability.metrics_snapshot()
        if row["name"] == "loci.lock.acquire"
        and row["labels"].get("reason") == "reentrant"
    ]
    assert reentrant

    lock_path = db_path.with_name(f".{db_path.name}.write.lock")
    lock_path.write_text("99999:foreign", encoding="ascii")
    monkeypatch.setattr(
        "src.market.infrastructure.write_lock._LOCK_WAIT_SEC",
        0.2,
    )
    with pytest.raises(MarketWriteBusy):
        with market_write_lock(db_path, label="waiter"):
            pass
    busy = [
        row
        for row in observability.metrics_snapshot()
        if row["name"] == "loci.lock.wait_ms"
        and row["labels"].get("outcome") == "busy"
    ]
    assert busy
    assert busy[0]["value"] >= 150
