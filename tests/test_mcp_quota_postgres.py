"""Quota accounting works with PostgreSQL mapping rows and no SQLite file."""
from types import SimpleNamespace

from src.intel.infrastructure import quota
from src.ops.infrastructure.store_quota import OpsQuotaMixin
from src.shared.postgres import _CompatRow


def test_postgres_mapping_rows_use_values_for_quota_counts():
    rows = [_CompatRow(("structured", 788), ("pool", "call_count"))]
    store = OpsQuotaMixin()
    store.conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: rows))

    assert store.read_mcp_quota_counts("2026-10-27") == {"structured": 788, "skill": 0}


def test_postgres_quota_does_not_depend_on_sqlite_file(tmp_path, monkeypatch):
    class Store:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read_mcp_quota_counts(self, trade_date):
            assert trade_date == "2026-10-27"
            return {"structured": 788, "skill": 0}

    monkeypatch.setattr(quota, "ops_db", lambda: tmp_path / "missing.db")
    monkeypatch.setattr(quota, "explicit_postgres_required", lambda: True)
    monkeypatch.setattr(quota, "OpsStore", Store)

    assert quota._read_counts("2026-10-27") == {"structured": 788, "skill": 0}
