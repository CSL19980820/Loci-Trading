"""decided_by 落库 + leader_roles 索引。"""
from __future__ import annotations

from pathlib import Path

from src.ops.application.paper_exec import PaperOrder, execute_orders
from src.ops.infrastructure.store import OpsStore
from src.ops.infrastructure.store_schema import _MIGRATIONS


def test_paper_fill_decided_by_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        cabin = store.ensure_paper_cabin("demo", max_layers=2.0)
        result = execute_orders(
            store,
            slug="demo",
            orders=[
                PaperOrder(
                    code="600519",
                    action="open",
                    layers=0.5,
                    reason="ai open",
                    mark_price=100.0,
                    name="茅台",
                    decided_by="ai",
                ),
                PaperOrder(
                    code="600519",
                    action="stop_cut",
                    layers=0.5,
                    reason="rules stop",
                    mark_price=90.0,
                    decided_by="rules",
                ),
            ],
            quotes={"600519": {"price": 100.0, "name": "茅台"}},
            source="strategy_monitor",
        )
        assert len(result.fills) == 2
        fills = store.list_paper_fills(cabin["id"], limit=10)
    by_action = {f["action"]: f for f in fills}
    assert by_action["open"]["decided_by"] == "ai"
    assert by_action["stop_cut"]["decided_by"] == "rules"
    # eod/style 可按 decided_by 分组
    grouped: dict[str, int] = {}
    for fill in fills:
        key = str(fill.get("decided_by") or "unknown")
        grouped[key] = grouped.get(key, 0) + 1
    assert grouped == {"ai": 1, "rules": 1}


def test_leader_roles_slug_observed_index_is_idempotent(tmp_path: Path) -> None:
    assert any(
        "idx_leader_roles_slug_observed" in sql for sql in _MIGRATIONS
    )
    db = tmp_path / "ops.db"
    with OpsStore(db) as store:
        # 迁移已在连接时跑过；再执行一次应幂等
        store.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_leader_roles_slug_observed "
            "ON leader_role_snapshots(slug, observed_at DESC)"
        )
        store.conn.commit()
        rows = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_leader_roles_slug_observed'"
        ).fetchall()
    assert len(rows) == 1
