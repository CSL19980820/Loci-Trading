"""Freeze public market inputs from production SQLite, without writing the source."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def freeze(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target.resolve().as_uri(), uri=True)
    db.execute("ATTACH DATABASE ? AS live", (source.resolve().as_uri() + "?mode=ro",))
    db.execute("BEGIN")
    for table in ("instruments", "adjust_factors", "meta"):
        db.execute(f"CREATE TABLE {table} AS SELECT * FROM live.{table}")
    db.execute("CREATE TABLE trading_calendar AS SELECT * FROM live.trading_calendar "
               "WHERE trade_date BETWEEN '2024-07-01' AND '2026-08-31'")
    db.execute("CREATE TABLE quotes_daily AS SELECT * FROM live.quotes_daily "
               "WHERE trade_date BETWEEN '2024-07-01' AND '2026-08-31'")
    db.execute("CREATE UNIQUE INDEX quote_key ON quotes_daily(code,trade_date)")
    db.execute("CREATE UNIQUE INDEX factor_key ON adjust_factors(code,trade_date)")
    db.commit()
    db.execute("DETACH DATABASE live")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source), "snapshot": str(target),
        "window": ["2024-07-01", "2026-08-31"],
        "rows": db.execute("SELECT count(*) FROM quotes_daily").fetchone()[0],
        "source_counts": db.execute("SELECT source,count(*) FROM quotes_daily GROUP BY source").fetchall(),
        "meta": db.execute("SELECT * FROM meta").fetchall(),
        "integrity_check": db.execute("PRAGMA main.integrity_check").fetchone()[0],
    }
    db.close()
    manifest["sha256"] = hashlib.file_digest(target.open("rb"), "sha256").hexdigest()
    target.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("target", type=Path)
    a = p.parse_args()
    freeze(a.source, a.target)
