from src.shared.postgres import translate_sql


def test_julianday_translation_preserves_nested_expressions() -> None:
    sql = (
        "SELECT julianday(COALESCE(NULLIF(heartbeat_at, ''), started_at)) "
        "IS NULL, julianday('now', ?)"
    )

    translated = translate_sql(sql)

    assert "julianday" not in translated.lower()
    assert (
        "EXTRACT(EPOCH FROM (COALESCE(NULLIF(heartbeat_at, ''), "
        "started_at))::timestamptz)"
    ) in translated
    assert "EXTRACT(EPOCH FROM CURRENT_TIMESTAMP + (%s)::interval)" in translated


def test_sqlite_index_hint_is_removed_for_postgres() -> None:
    sql = (
        "SELECT 1 FROM quotes_daily "
        "INDEXED BY sqlite_autoindex_quotes_daily_1 WHERE FALSE"
    )

    translated = translate_sql(sql)

    assert translated == "SELECT 1 FROM quotes_daily WHERE FALSE"
