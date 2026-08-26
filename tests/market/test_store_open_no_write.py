"""MarketStore 打开：schema 已就绪时不得再抢写锁做迁移。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.store_schema import _SCHEMA_READY


def test_open_skips_init_schema_when_version_current(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    first = MarketStore(db)
    first.close()
    key = str(db.resolve())
    _SCHEMA_READY.discard(key)

    with patch.object(MarketStore, "init_schema", autospec=True) as init:
        second = MarketStore(db)
        second.close()
    init.assert_not_called()
