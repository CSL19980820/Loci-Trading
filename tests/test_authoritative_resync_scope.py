import sqlite3

from scripts.resync_market_authoritative import stock_codes


def test_recent_repair_excludes_inactive_but_history_keeps_them(tmp_path):
    path = tmp_path / "market.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE instruments(code TEXT, instrument_type TEXT, status TEXT)")
        conn.executemany("INSERT INTO instruments VALUES(?,?,?)", [
            ("600000", "STOCK", "normal"),
            ("000300", "INDEX", "normal"),
            ("000016", "STOCK", "delisted"),
            ("600001", "STOCK", "suspended"),
            ("510300", "FUND", "normal"),
        ])

    assert stock_codes(path, active_only=True) == [("000300", "INDEX"), ("600000", "STOCK")]
    assert stock_codes(path) == [
        ("000016", "STOCK"), ("000300", "INDEX"),
        ("600000", "STOCK"), ("600001", "STOCK"),
    ]
