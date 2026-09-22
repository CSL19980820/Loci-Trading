"""Administrator/visitor migration; no tenant databases or account content are deleted.

The users CHECK constraint is rebuilt transactionally because SQLite cannot ALTER
an existing CHECK. All columns, indexes and triggers are preserved. Only retired
announcement and personal API-key storage is removed, after a consistent backup.
"""
from __future__ import annotations

import re
from contextlib import closing
import sqlite3
import os
import secrets
from pathlib import Path

from src.identity.domain.models import iso, utc_now

MIGRATION_KEY = "access_model_admin_visitor_v1"


def migrate_access_model(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM meta WHERE key = ?", (MIGRATION_KEY,)).fetchone():
        return
    # A consistent SQLite backup also includes WAL content. Do not copy the .db
    # file directly. Migration refuses to proceed if the backup cannot be made.
    database = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), "")
    if database and conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        directory = Path(database).parent / ".backups"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        backup = directory / f"identity-before-visitor-{stamp}-{secrets.token_hex(3)}.db"
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with closing(sqlite3.connect(backup)) as target:
                conn.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Identity backup integrity check failed")
        except Exception:
            backup.unlink(missing_ok=True)
            raise
    # Re-check under a write lock: two request workers may open the store together.
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM meta WHERE key = ?", (MIGRATION_KEY,)).fetchone():
            return
        definition = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        ).fetchone()[0]
        if "'member'" in definition:
            target = re.sub(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?users[\"`\]]?",
                "CREATE TABLE users__visitor_migration", definition, count=1, flags=re.I,
            ).replace("'member'", "'visitor'")
            if target == definition:
                raise RuntimeError("Cannot safely migrate the users role constraint")
            indexes = conn.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name = 'users' "
                "AND type IN ('index', 'trigger') AND sql IS NOT NULL"
            ).fetchall()
            columns = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
            quoted = [f'"{name.replace(chr(34), chr(34) * 2)}"' for name in columns]
            projection = [
                "CASE WHEN role = 'admin' THEN 'admin' ELSE 'visitor' END"
                if name == "role" else quote for name, quote in zip(columns, quoted)
            ]
            conn.execute(target)
            conn.execute(
                f"INSERT INTO users__visitor_migration ({', '.join(quoted)}) "
                f"SELECT {', '.join(projection)} FROM users"
            )
            conn.execute("DROP TABLE users")
            conn.execute("ALTER TABLE users__visitor_migration RENAME TO users")
            for row in indexes:
                conn.execute(row[0])
        # A visitor has its own identity/tenant, plus an explicitly delegated read
        # workspace. Existing accounts keep their original workspace by default.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if "view_tenant_id" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN view_tenant_id TEXT NOT NULL DEFAULT ''")
        now = iso(utc_now())
        conn.execute(
            "UPDATE users SET view_tenant_id = tenant_id, must_change_password = 0 "
            "WHERE role = 'visitor' AND view_tenant_id = ''"
        )
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE revoked_at IS NULL "
            "AND user_id IN (SELECT id FROM users WHERE role <> 'admin')", (now,),
        )
        # The personal Open API feature is retired; machine integration uses its
        # existing, separate service credential and is unaffected.
        conn.execute("DROP TABLE IF EXISTS api_keys")
        conn.execute("DELETE FROM notifications WHERE kind IN ('announcement', 'announcements')")
        conn.execute("DROP TABLE IF EXISTS announcements")
        conn.execute(
            "INSERT INTO meta(key, value, updated_at) VALUES (?, '1', ?)",
            (MIGRATION_KEY, now),
        )
