"""Freeze read-only market inputs for the first-wave study; never open a ledger.

The local archive contains the early history; production wins duplicate keys.
Run capture and merge as separate commands so a completed export is reusable.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from datetime import datetime, timezone


TABLES = ("instruments", "quotes_daily", "adjust_factors", "trading_calendar", "intel_snapshots", "meta")

REMOTE_EXPORT = r'''
import gzip, json, sqlite3, sys
from datetime import datetime, timezone
c = sqlite3.connect('file:/srv/qianlong-loci/data/market.db?mode=ro', uri=True)
c.execute('PRAGMA query_only=ON')
c.execute('BEGIN')
tables = ('instruments','quotes_daily','adjust_factors','trading_calendar','intel_snapshots','meta')
manifest = {'source':'my-debian:/srv/qianlong-loci/data/market.db',
            'captured_at':datetime.now(timezone.utc).isoformat(), 'tables':{}}
with gzip.open(sys.stdout.buffer, 'wt', encoding='utf-8', compresslevel=1) as out:
    for table in tables:
        cursor = c.execute('SELECT * FROM '+table)
        columns = [r[0] for r in cursor.description]
        out.write(json.dumps({'table':table,'columns':columns},separators=(',',':'))+chr(10))
        count = 0
        while True:
            rows = cursor.fetchmany(50 if table == 'intel_snapshots' else 10000)
            if not rows: break
            out.write(json.dumps({'table':table,'rows':rows},ensure_ascii=False,separators=(',',':'))+chr(10))
            count += len(rows)
        manifest['tables'][table] = count
        print(table, count, file=sys.stderr, flush=True)
    manifest['quotes_range'] = c.execute('SELECT MIN(trade_date),MAX(trade_date) FROM quotes_daily').fetchone()
    out.write(json.dumps({'manifest':manifest},ensure_ascii=False,separators=(',',':'))+chr(10))
c.close()
'''


def ro_connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def capture(target: Path, host: str = "my-debian") -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves an earlier capture, including an incomplete one.
    with target.open("xb") as output:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, "python3 -"],
            input=REMOTE_EXPORT.encode("utf-8"), stdout=output, check=False,
        )
    if result.returncode:
        raise RuntimeError(f"Production export failed ({result.returncode}); retained {target}")
    with gzip.open(target, "rt", encoding="utf-8") as source:
        last = {}
        for line in source:
            last = json.loads(line)
    if "manifest" not in last:
        raise ValueError("Production export has no terminal manifest")
    manifest = last["manifest"]
    with target.open("rb") as source:
        manifest["sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    manifest["bytes"] = target.stat().st_size
    target.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


def merge(local: Path, production: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target.resolve().as_uri(), uri=True)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("ATTACH DATABASE ? AS archive", (local.resolve().as_uri() + "?mode=ro",))
    con.execute("BEGIN")
    for table in TABLES:
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM archive.{table}")
        print("copied_archive", table, flush=True)
    keys = {
        "instruments": "code", "quotes_daily": "trade_date,code",
        "adjust_factors": "code,trade_date", "trading_calendar": "trade_date",
        "intel_snapshots": "trade_date,tool,args_hash", "meta": "key",
    }
    for table, columns in keys.items():
        con.execute(f"CREATE UNIQUE INDEX key_{table} ON {table}({columns})")
    inserts: dict[str, str] = {}
    exported_manifest = None
    with gzip.open(production, "rt", encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if "manifest" in record:
                exported_manifest = record["manifest"]
                continue
            table = record["table"]
            if table not in TABLES:
                raise ValueError(f"Unexpected input table: {table}")
            if "columns" in record:
                expected = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
                columns = record["columns"]
                if columns != expected:
                    raise ValueError(f"Schema mismatch for {table}: {columns} != {expected}")
                inserts[table] = f"INSERT OR REPLACE INTO {table} VALUES ({','.join('?' for _ in columns)})"
            else:
                con.executemany(inserts[table], record["rows"])
    if exported_manifest is None:
        raise ValueError("Missing production export manifest")
    con.execute("CREATE INDEX quotes_by_code ON quotes_daily(code,trade_date)")
    con.commit()
    con.execute("DETACH DATABASE archive")
    print("merged; auditing", flush=True)
    audit = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "archive": str(local.resolve()), "production_export": str(production.resolve()),
        "production": exported_manifest, "duplicate_policy": "production wins identical primary key",
        "quotes_range": con.execute("SELECT MIN(trade_date),MAX(trade_date),COUNT(*),COUNT(DISTINCT code),COUNT(DISTINCT trade_date) FROM quotes_daily").fetchone(),
        "by_year": con.execute("SELECT substr(trade_date,1,4),COUNT(*),COUNT(DISTINCT code),COUNT(DISTINCT trade_date) FROM quotes_daily GROUP BY substr(trade_date,1,4)").fetchall(),
        "intel_coverage": con.execute("SELECT tool,MIN(trade_date),MAX(trade_date),COUNT(*) FROM intel_snapshots GROUP BY tool").fetchall(),
        "integrity_check": con.execute("PRAGMA quick_check").fetchone()[0],
    }
    con.close()
    with target.open("rb") as source:
        audit["sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    target.with_suffix(".manifest.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    cap = subs.add_parser("capture")
    cap.add_argument("target", type=Path)
    cap.add_argument("--host", default="my-debian")
    mer = subs.add_parser("merge")
    mer.add_argument("local", type=Path)
    mer.add_argument("production", type=Path)
    mer.add_argument("target", type=Path)
    args = parser.parse_args()
    if args.command == "capture":
        capture(args.target, args.host)
    else:
        merge(args.local, args.production, args.target)


if __name__ == "__main__":
    main()
