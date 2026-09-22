"""Trade search uses a shared literal filter for counts and pages; SQLite is in memory."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.ledger.infrastructure.guardian_queries import GuardianQueriesMixin


@pytest.fixture
def ledger():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE guardian_trades (id TEXT, slot TEXT, code TEXT, occurred_at TEXT, detail_json TEXT)")
    rows = [
        ("1", "000980", "模拟汽车", "2026-09-21T10:00:00"),
        ("2", "000981", "模拟Beta", "2026-09-21T11:00:00"),
        ("3", "000980", "模拟汽车", "2026-09-21T12:00:00"),
        ("4", "000982", "百分%_测试", "2026-09-21T13:00:00"),
        ("5", "000980", "模拟汽车", "2026-09-22T00:00:00"),
    ]
    conn.executemany("INSERT INTO guardian_trades VALUES (?, 'fixture', ?, ?, ?)", [
        (row_id, code, at, json.dumps({"code": code, "name": name})) for row_id, code, name, at in rows
    ])
    try:
        yield SimpleNamespace(conn=conn)
    finally:
        conn.close()


def page(ledger, keyword="", offset=0, limit=1):
    return GuardianQueriesMixin.trade_page(
        ledger, start="2026-09-21", end="2026-09-21", limit=limit, offset=offset, keyword=keyword,
    )


def test_name_filter_count_and_pagination_share_the_same_predicate(ledger):
    first = page(ledger, "汽车")
    second = page(ledger, "汽车", offset=1)
    assert first["total"] == second["total"] == 2
    assert [item["id"] for item in first["items"]] == ["3"]
    assert [item["id"] for item in second["items"]] == ["1"]


@pytest.mark.parametrize("keyword,expected", [("980", 2), ("  BETA  ", 1), ("%_", 1)])
def test_code_case_and_literal_characters(ledger, keyword, expected):
    assert page(ledger, keyword)["total"] == expected


def test_query_cannot_change_sql_and_reset_restores_date_range(ledger):
    assert page(ledger, "' OR 1=1 --")["total"] == 0
    reset = page(ledger, limit=20)
    assert reset["total"] == 4
    assert all(item["id"] != "5" for item in reset["items"])
