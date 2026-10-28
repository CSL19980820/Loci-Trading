"""潜龙记忆宫殿的本地候选池与复盘账本。

这个模块只记录候选裁决、预案与复盘结果，不记录持仓/成交，也不生成自动交易指令。
核心原则是：任何结论都带有日期、来源和可选的证据字段，便于日后追溯与量化复盘。

实现按职责拆到同目录 mixin 模块；本文件组合为 ``PalaceStore`` 并 re-export 公开符号。
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from src.ledger.infrastructure.ai_judgments import AiJudgmentMixin
from src.ledger.infrastructure.candidates import CandidateMixin
from src.ledger.infrastructure.candidates_query import CandidateQueryMixin
from src.ledger.infrastructure.plans_reviews import PlanReviewMixin
from src.ledger.infrastructure.queries import QueryMixin
from src.ledger.infrastructure.schema import SchemaMixin
from src.ledger.infrastructure.store_types import (
    SCHEMA_VERSION,
    PalaceError,
    _dumps,
    _loads,
    _normalize_decision,
    _normalize_rule_version,
    _now,
    normalize_code,
    normalize_date,
)
from src.shared.paths import palace_db as _default_palace_db
from src.shared.postgres import CompatConnection, explicit_postgres_required, uses_primary_path

__all__ = [
    "SCHEMA_VERSION",
    "PalaceError",
    "PalaceStore",
    "normalize_code",
    "normalize_date",
    "_dumps",
    "_loads",
    "_normalize_decision",
    "_normalize_rule_version",
    "_now",
]


class PalaceStore(
    SchemaMixin,
    CandidateMixin,
    CandidateQueryMixin,
    PlanReviewMixin,
    QueryMixin,
    AiJudgmentMixin,
):
    """SQLite 账本：候选池、预案、复盘与 AI 判定的可审计事实源。"""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._use_postgres = (
            explicit_postgres_required()
            and uses_primary_path(db_path, _default_palace_db())
        )
        if self._use_postgres:
            self.conn = CompatConnection()
            self.conn.raw.execute("SET search_path TO ledger, public")
            self.conn.raw.commit()
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        journal = self.conn.execute("PRAGMA journal_mode").fetchone()
        if journal is None or str(journal[0]).lower() != "wal":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> PalaceStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.conn.cursor()
        nested = self.conn.in_transaction
        savepoint = f"palace_tx_{id(cursor)}"
        started = False
        try:
            cursor.execute(
                f"SAVEPOINT {savepoint}"
                if nested
                else ("BEGIN" if self._use_postgres else "BEGIN IMMEDIATE")
            )
            started = True
            yield cursor
        except BaseException:
            if started and nested:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
            elif started:
                self.conn.rollback()
            raise
        else:
            if nested:
                cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                self.conn.commit()
        finally:
            cursor.close()
