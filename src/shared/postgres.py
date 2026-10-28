"""PostgreSQL connection and SQLite-compatible query adapter.

The application historically uses SQLite's ``?`` placeholders and a few SQL
helpers.  The adapter keeps those call sites stable while PostgreSQL owns the
transactional database.  It is intentionally small and synchronous: stores are
opened per request/job, matching the existing lifecycle.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
from typing import Any, Iterable, Iterator

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row, tuple_row
from psycopg_pool import ConnectionPool


DEFAULT_DSN = "postgresql://loci@127.0.0.1:5432/loci"

PG_PRIMARY_KEYS = {
    "meta": "key",
    "instruments": "code",
    "quotes_daily": "(trade_date, code)",
    "adjust_factors": "(code, trade_date)",
    "trading_calendar": "trade_date",
    "ingest_watermark": "code",
    "source_route_receipts": "receipt_id",
    "source_route_attempts": "(receipt_id, attempt_no)",
    "intel_snapshots": "(trade_date, tool, args_hash)",
    "stocks": "code",
    "candidate_reviews": "id",
    "plans": "id",
    "reviews": "id",
    "ai_judgments": "id",
    "guardian_portfolio": "id",
    "guardian_cycles": "slot",
    "guardian_trades": "id",
    "guardian_reports": "report_key",
    "guardian_report_revisions": "(report_key, revision)",
    "guardian_consultations": "id",
    "guardian_consult_turns": "id",
    "guardian_notices": "slot",
    "guardian_experience_versions": "revision",
    "guardian_diary_preferences": "id",
    "guardian_diary_compactions": "slot",
    "stock_agent_profiles": "id",
    "stock_agent_runs": "id",
    "stock_agent_trades": "id",
    "stock_agent_funding": "(agent_id, request_id)",
    "stock_agent_equity": "(agent_id, day)",
    "jobs": "id",
    "job_runs": "id",
    "llm_providers": "id",
    "alert_rules": "id",
    "alert_hits": "id",
    "signal_journal": "id",
    "users": "id",
    "identities": "id",
    "sessions": "id",
    "email_verifications": "id",
    "oauth_states": "state",
    "user_quotas": "user_id",
    "usage_counters": "(user_id, period, metric)",
    "audit_log": "id",
    "notifications": "id",
}


def database_url() -> str:
    """Return the configured PostgreSQL URL.

    ``PALACE_POSTGRES_URL`` is the explicit production switch.  There is no
    credential-bearing fallback in source: leaked defaults outlive the machine
    they were written for and turn every clone into a password disclosure.
    """
    return (
        os.environ.get("PALACE_POSTGRES_URL")
        or os.environ.get("LOCI_POSTGRES_URL")
        or DEFAULT_DSN
    ).strip()


def postgres_enabled() -> bool:
    return (os.environ.get("LOCI_DATABASE_BACKEND") or "").strip().lower() == "postgres"


def explicit_postgres_required() -> bool:
    backend = (os.environ.get("LOCI_DATABASE_BACKEND") or "").strip().lower()
    if backend and backend not in {"postgres", "sqlite"}:
        raise RuntimeError(f"未知 LOCI_DATABASE_BACKEND：{backend}")
    return backend == "postgres"


def uses_primary_path(
    explicit: Path | str | None,
    default: Path | str,
) -> bool:
    """Whether a store argument addresses the deployment's primary database.

    Production wiring often passes the default path explicitly.  Merely keying
    the backend switch on ``None`` sends those call sites back to SQLite.
    Tests and alternate tenants keep custom paths and therefore stay isolated.
    """
    if explicit is None:
        return True
    try:
        return Path(explicit).expanduser().resolve() == Path(default).expanduser().resolve()
    except OSError:
        return str(explicit) == str(default)


def _json_path(expr: str, path: str) -> str:
    """Translate SQLite ``json_extract(doc, '$.a.b')`` to jsonb traversal."""
    parts = [part for part in str(path).lstrip("$").lstrip(".").split(".") if part]
    result = f"({expr}::jsonb)"
    for index, part in enumerate(parts):
        operator = "->>" if index == len(parts) - 1 else "->"
        if part.isdigit():
            result += f"{operator}{int(part)}"
        else:
            result += f"{operator}'{part.replace(chr(39), chr(39) * 2)}'"
    return result


def _rewrite_json_functions(sql: str) -> str:
    # JSON paths in this repository are literals.  Nested calls are deliberately
    # handled from the inside out by repeatedly rewriting simple expressions.
    pattern = re.compile(
        r"json_extract\(\s*([A-Za-z_][A-Za-z0-9_\.]*)\s*,\s*'\$([^']*)'\s*\)",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: _json_path(m.group(1), "$" + m.group(2)), sql)


def _rewrite_julianday_functions(sql: str) -> str:
    """Translate SQLite ``julianday(expr)`` while preserving nested calls.

    A regular expression that stops at the first ``)`` rejects ordinary
    expressions such as ``COALESCE(NULLIF(heartbeat_at, ''), started_at)`` and
    leaves PostgreSQL parsing the latter half as a RECORD.
    """
    text = sql
    start = 0
    marker = re.compile(r"\bjulianday\s*\(", re.I)
    while match := marker.search(text, start):
        open_at = text.find("(", match.start())
        depth = 0
        quote = ""
        close_at = -1
        for position in range(open_at, len(text)):
            char = text[position]
            if quote:
                if char == quote:
                    if position + 1 < len(text) and text[position + 1] == quote:
                        continue
                    quote = ""
                continue
            if char in {"'", '"'}:
                quote = char
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    close_at = position
                    break
        if close_at < 0:
            break
        expression = text[open_at + 1 : close_at]
        replacement = f"EXTRACT(EPOCH FROM ({expression})::timestamptz)"
        text = text[: match.start()] + replacement + text[close_at + 1 :]
        start = match.start() + len(replacement)
    return text


class _CompatRow(dict[str, Any]):
    """Mapping row that also preserves sqlite3.Row's positional indexing."""

    __slots__ = ("_values",)

    def __init__(self, values: tuple[Any, ...], fields: tuple[str, ...]) -> None:
        super().__init__(zip(fields, values, strict=True))
        self._values = values

    def __getitem__(self, key: int | slice | str) -> Any:
        if isinstance(key, (int, slice)):
            return self._values[key]
        return super().__getitem__(key)


def _compat_row(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    return _CompatRow(tuple(row.values()), tuple(row.keys()))


def translate_sql(sql: str) -> str:
    """Translate the SQLite subset used by this repository to PostgreSQL."""
    text = str(sql)
    # SQLite models BEGIN IMMEDIATE as a write-intent transaction. PostgreSQL
    # uses ordinary BEGIN; retaining IMMEDIATE is a syntax error.
    text = re.sub(
        r"\bBEGIN\s+IMMEDIATE\b",
        "BEGIN",
        text,
        flags=re.I,
    )
    text = _rewrite_json_functions(text)
    def json_array_path(match: re.Match[str]) -> str:
        expression = match.group(1)
        path = str(match.group(2)).lstrip(".").split(".")
        array_path = "{" + ",".join(path) + "}" if path else "{}"
        return f"jsonb_array_elements(({expression}::jsonb)#>'{array_path}')"

    text = re.sub(
        r"\bjson_each\(\s*([^,()]+)\s*,\s*'\$([^']*)'\s*\)",
        json_array_path,
        text,
        flags=re.I,
    )
    text = re.sub(r"\bjson_each\(\s*([^,()]+)\s*\)", r"jsonb_array_elements((\1::jsonb))", text, flags=re.I)
    def json_type_path(match: re.Match[str]) -> str:
        expression = match.group(1)
        parts = [part for part in str(match.group(2)).lstrip(".").split(".") if part]
        path = "{" + ",".join(parts) + "}" if parts else "{}"
        return f"jsonb_typeof(({expression}::jsonb)#>'{path}')"

    text = re.sub(
        r"\bjson_type\(\s*([^,()]+)\s*,\s*'\$([^']*)'\s*\)",
        json_type_path,
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bjson_valid\(\s*([^,()]+)\s*\)",
        r"COALESCE(pg_input_is_valid((\1)::text, 'json'), false)",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bIFNULL\(", "COALESCE(", text, flags=re.I)
    text = re.sub(r"\bTOTAL\(", "COALESCE(SUM(", text, flags=re.I)
    text = re.sub(
        r"\bGROUP_CONCAT\(\s*(.+?)\s*,\s*'\|\|'\s*\)",
        r"STRING_AGG(\1, '||')",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(r"\bGROUP_CONCAT\(", "STRING_AGG(", text, flags=re.I)
    text = re.sub(r"\bNULLIF\(", "NULLIF(", text, flags=re.I)
    text = re.sub(r"\bdatetime\(\s*'now'\s*,\s*'localtime'\s*\)", "CURRENT_TIMESTAMP", text, flags=re.I)
    text = re.sub(r"\bdatetime\(\s*'now'\s*\)", "CURRENT_TIMESTAMP", text, flags=re.I)
    text = re.sub(r"\bstrftime\(\s*'%Y-%m'\s*,\s*([^)]+)\)", r"to_char(\1, 'YYYY-MM')", text, flags=re.I)
    text = re.sub(
        r"\bjulianday\(\s*'now'\s*,\s*(\?|%s)\s*\)",
        r"EXTRACT(EPOCH FROM CURRENT_TIMESTAMP + (\1)::interval)",
        text,
        flags=re.I,
    )
    text = _rewrite_julianday_functions(text)
    text = re.sub(
        r"\bjson_extract\(\s*([^,()]+)\s*,\s*'\$([^']*)'\s*\)",
        lambda m: _json_path(m.group(1), "$" + m.group(2)),
        text,
        flags=re.I,
    )
    # PostgreSQL has no implicit row identifier.  Queries selecting physical
    # ids are SQLite-specific; leave the token unchanged so they fail loudly and
    # are migrated to a declared key instead of silently using an unstable ctid.
    text = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", text, flags=re.I)
    text = re.sub(
        r"\bINSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_\.]*)\s+VALUES\s*\(",
        r"INSERT INTO \1 VALUES(",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "INSERT INTO", text, flags=re.I)
    # SQLite accepts ``ON CONFLICT(table) DO NOTHING`` just like PostgreSQL.
    # ``INDEXED BY`` is a SQLite planner hint, not part of the query contract.
    # The same predicates still use PostgreSQL's equivalent indexes.
    text = re.sub(
        r"\s+INDEXED\s+BY\s+[A-Za-z_][A-Za-z0-9_]*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bAUTOINCREMENT\b", "GENERATED BY DEFAULT AS IDENTITY", text, flags=re.I)
    text = re.sub(r"\bWITHOUT\s+ROWID\b", "", text, flags=re.I)
    text = text.replace("?", "%s")
    return text


class CompatCursor:
    """Cursor facade with ``fetchone/fetchall/rowcount`` and mapping rows."""

    def __init__(self, raw: Any) -> None:
        self.raw = raw

    def execute(self, sql: str, params: Any = None) -> CompatCursor:
        original = str(sql)
        statement = translate_sql(original)
        if re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", original, re.I):
            statement += " ON CONFLICT DO NOTHING"
        if re.search(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", original, re.I):
            raise NotImplementedError(
                "INSERT OR REPLACE must be migrated to an explicit upsert; "
                "silently replacing would hide a data-loss bug"
            )
        self.raw.execute(statement, params)
        return self

    def executemany(self, sql: str, params: Iterable[Any]) -> CompatCursor:
        rows = list(params)
        statement = translate_sql(sql)
        # ``INSERT OR IGNORE`` has no direct placeholder rewrite: add the
        # equivalent conflict clause for the repository's common inserts.
        if re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", str(sql), re.I):
            statement += " ON CONFLICT DO NOTHING"
        if re.search(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", str(sql), re.I):
            # The stores using REPLACE provide a complete primary-key row.
            raise NotImplementedError(
                "INSERT OR REPLACE must be migrated to an explicit upsert; "
                "silently replacing would hide a data-loss bug"
            )
        self.raw.executemany(statement, rows)
        return self

    def fetchone(self) -> Any:
        return _compat_row(self.raw.fetchone())

    def fetchall(self) -> list[Any]:
        return [_compat_row(row) for row in self.raw.fetchall()]

    def fetchmany(self, size: int | None = None) -> list[Any]:
        rows = self.raw.fetchmany(size) if size is not None else self.raw.fetchmany()
        return [_compat_row(row) for row in rows]

    @property
    def rowcount(self) -> int:
        return int(self.raw.rowcount if self.raw.rowcount is not None else -1)

    @property
    def lastrowid(self) -> Any:
        return None

    @property
    def description(self) -> Any:
        return self.raw.description

    def close(self) -> None:
        self.raw.close()

    def __iter__(self) -> Iterator[Any]:
        return (_compat_row(row) for row in self.raw)


class CompatConnection:
    """Small psycopg connection wrapper used by the existing stores."""

    def __init__(
        self, url: str | None = None, *, autocommit: bool = False,
        pool: ConnectionPool | None = None,
    ) -> None:
        if pool is not None and (url is not None or autocommit):
            raise ValueError("pooled connections use the pool URL and transaction mode")
        self.url = url or database_url()
        self._pool = pool
        self._closed = False
        self._raw = (
            pool.getconn() if pool is not None
            else psycopg.connect(self.url, row_factory=dict_row, autocommit=autocommit)
        )

    @property
    def raw(self) -> Any:
        if self._closed:
            raise psycopg.OperationalError("the connection is closed")
        return self._raw

    @property
    def total_changes(self) -> int:
        return 0

    @property
    def in_transaction(self) -> bool:
        return bool(getattr(self.raw, "info", None) and self.raw.info.transaction_status)

    @property
    def closed(self) -> bool:
        return self._closed or self._raw.closed

    def execute(self, sql: str, params: Any = None) -> CompatCursor:
        cur = self.raw.cursor()
        return CompatCursor(cur).execute(sql, params)

    def executemany(self, sql: str, params: Iterable[Any]) -> CompatCursor:
        cur = self.raw.cursor()
        return CompatCursor(cur).executemany(sql, params)

    def executescript(self, sql: str) -> CompatCursor:
        cur = self.raw.cursor()
        cur.execute(translate_sql(sql))
        return CompatCursor(cur)

    def cursor(self) -> CompatCursor:
        return CompatCursor(self.raw.cursor())

    def tuple_cursor(self, sql: str, params: Any = None) -> Any:
        """Return a native tuple cursor for bulk numeric reads.

        Mapping rows are convenient for ordinary stores but expensive for panel
        scans that immediately discard column names and build NumPy arrays.
        """
        cursor = self.raw.cursor(row_factory=tuple_row)
        cursor.execute(translate_sql(sql), params)
        return cursor

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        if not self._closed:
            raw = self._raw
            self._closed = True
            if self._pool is None:
                raw.close()
            else:
                try:
                    if not raw.closed and raw.info.transaction_status:
                        raw.rollback()
                finally:
                    self._pool.putconn(raw)

    def __enter__(self) -> CompatConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)


def _reset_identity_connection(conn: psycopg.Connection) -> None:
    """Restore the session state a freshly opened identity connection has."""
    conn.autocommit = True
    try:
        conn.execute("DISCARD ALL")
    finally:
        conn.autocommit = False


def create_identity_auth_pool() -> ConnectionPool:
    """Keep only short-lived authentication lookups in a small per-app pool."""
    return ConnectionPool(
        database_url(),
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
        min_size=1,
        max_size=4,
        timeout=3,
        check=ConnectionPool.check_connection,
        reset=_reset_identity_connection,
        open=True,
    )


def connect(url: str | None = None, **_: Any) -> CompatConnection:
    """Drop-in replacement for ``sqlite3.connect`` in migrated stores."""
    return CompatConnection(url)


@contextmanager
def connection(url: str | None = None) -> Iterator[CompatConnection]:
    conn = connect(url)
    try:
        yield conn
    finally:
        conn.close()


def ensure_ready() -> None:
    """Fail fast when the production database cannot be reached."""
    with psycopg.connect(database_url(), connect_timeout=3) as conn:
        conn.execute("SELECT 1")


def retryable(exc: BaseException) -> bool:
    return isinstance(exc, (pg_errors.OperationalError, pg_errors.InterfaceError))


__all__ = [
    "CompatConnection",
    "CompatCursor",
    "DEFAULT_DSN",
    "connect",
    "connection",
    "database_url",
    "ensure_ready",
    "postgres_enabled",
    "explicit_postgres_required",
    "retryable",
    "translate_sql",
    "uses_primary_path",
]
