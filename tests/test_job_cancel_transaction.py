"""任务取消查询不能泄漏或提前提交 PostgreSQL 事务。"""

import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ops.infrastructure.store_runs import OpsRunsMixin
from src.shared.postgres import CompatConnection


def _postgres_store(*, in_transaction=False, row=None, failure=None):
    raw = Mock()
    raw.info = SimpleNamespace(transaction_status=2 if in_transaction else 0)
    raw.closed = False
    cursor = raw.cursor.return_value

    def execute(_sql, _params):
        raw.info.transaction_status = 2
        if failure:
            raise failure

    cursor.execute.side_effect = execute
    cursor.fetchone.return_value = row
    raw.commit.side_effect = lambda: setattr(raw.info, "transaction_status", 0)
    raw.rollback.side_effect = lambda: setattr(raw.info, "transaction_status", 0)
    conn = object.__new__(CompatConnection)
    conn._raw = raw
    conn._closed = False
    store = OpsRunsMixin()
    store.conn = conn
    store._use_postgres = True
    return store, raw


def test_cancel_poll_finishes_only_its_own_postgres_read():
    store, raw = _postgres_store(row={"cancel_requested": 1})

    assert store.is_cancel_requested("run-1") is True
    assert not store.conn.in_transaction
    raw.commit.assert_called_once_with()
    raw.rollback.assert_not_called()


def test_cancel_poll_preserves_existing_postgres_transaction():
    store, raw = _postgres_store(in_transaction=True, row={"cancel_requested": 0})

    assert store.is_cancel_requested("run-1") is False
    assert store.conn.in_transaction
    raw.commit.assert_not_called()
    raw.rollback.assert_not_called()


def test_cancel_poll_rolls_back_its_own_failed_postgres_read():
    store, raw = _postgres_store(failure=RuntimeError("query failed"))

    with pytest.raises(RuntimeError, match="query failed"):
        store.is_cancel_requested("run-1")
    assert not store.conn.in_transaction
    raw.rollback.assert_called_once_with()
    raw.commit.assert_not_called()


def test_cancel_poll_does_not_commit_sqlite_caller_work():
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE job_runs (id TEXT, cancel_requested INTEGER)")
        conn.execute("INSERT INTO job_runs VALUES ('run-1', 1)")
        store = OpsRunsMixin()
        store.conn = conn
        store._use_postgres = False

        assert store.is_cancel_requested("run-1") is True
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == 0
