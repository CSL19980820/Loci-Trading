from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3

import pytest

from scripts.first_wave_data import TABLES, merge


def make_archive(path):
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE instruments(code TEXT,name TEXT);
            CREATE TABLE quotes_daily(trade_date TEXT,code TEXT,close REAL);
            CREATE TABLE adjust_factors(code TEXT,trade_date TEXT,hfq_factor REAL);
            CREATE TABLE trading_calendar(trade_date TEXT);
            CREATE TABLE intel_snapshots(trade_date TEXT,tool TEXT,args_hash TEXT);
            CREATE TABLE meta(key TEXT,value TEXT);
            INSERT INTO instruments VALUES('000001','old');
            INSERT INTO quotes_daily VALUES('1990-12-19','000001',10);
            INSERT INTO quotes_daily VALUES('2026-09-11','000001',11);
            INSERT INTO adjust_factors VALUES('000001','1900-01-01',1);
            INSERT INTO trading_calendar VALUES('1990-12-19');
            INSERT INTO meta VALUES('revision','old');
        """)


def test_snapshot_unions_earliest_history_and_production_without_mutating_archive(tmp_path):
    archive = tmp_path / "archive.db"
    make_archive(archive)
    original_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    exported = tmp_path / "production.gz"
    replacements = {
        "instruments": [["000001", "new"]],
        "quotes_daily": [["2026-09-11", "000001", 12], ["2026-10-26", "000001", 13]],
        "meta": [["revision", "new"]],
    }
    with sqlite3.connect(archive) as con, gzip.open(exported, "wt", encoding="utf-8") as out:
        for table in TABLES:
            columns = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
            out.write(json.dumps({"table": table, "columns": columns}) + "\n")
            out.write(json.dumps({"table": table, "rows": replacements.get(table, [])}) + "\n")
        out.write(json.dumps({"manifest": {"source": "fixture"}}) + "\n")
    target = tmp_path / "frozen.db"
    merge(archive, exported, target)
    with sqlite3.connect(target) as con:
        assert con.execute("SELECT trade_date,close FROM quotes_daily ORDER BY trade_date").fetchall() == [
            ("1990-12-19", 10), ("2026-09-11", 12), ("2026-10-26", 13)]
        assert con.execute("SELECT name FROM instruments").fetchone()[0] == "new"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == original_hash
    manifest = json.loads(target.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert manifest["quotes_range"][:3] == ["1990-12-19", "2026-10-26", 3]
    assert manifest["integrity_check"] == "ok"
    with pytest.raises(FileExistsError):
        merge(archive, exported, target)


def test_export_without_terminal_manifest_cannot_be_accepted(tmp_path):
    archive = tmp_path / "archive.db"
    make_archive(archive)
    exported = tmp_path / "truncated.gz"
    with gzip.open(exported, "wt", encoding="utf-8") as out:
        out.write(json.dumps({"table": "instruments", "columns": ["code", "name"]}) + "\n")
    with pytest.raises(ValueError, match="Missing production export manifest"):
        merge(archive, exported, tmp_path / "incomplete.db")
