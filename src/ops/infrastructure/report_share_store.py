"""公共分享索引：一份数据库，不保存页面、样式、工具记录或账号配置。"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from src.shared.paths import data_dir

TOKEN_PATTERN = re.compile(r'[A-Za-z0-9_-]{43}')
SCHEMA = '''CREATE TABLE IF NOT EXISTS report_shares (
    token TEXT PRIMARY KEY,
    identity_hash TEXT NOT NULL,
    descriptor_json TEXT NOT NULL,
    registered_at REAL NOT NULL
)'''


def validate_token(token: str) -> None:
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise ValueError('无效分享地址')


def registry_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / 'report_shares.db'


def reject_symlinks(path: Path) -> None:
    # Check ancestors too: a token must not traverse a linked directory.
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('分享存储不允许使用符号链接')


def readable_permissions(path: Path, root: Path) -> None:
    """Root maintenance and the web worker must agree on the data owner's UID."""
    reject_symlinks(path)
    if os.name == 'posix':
        owner = root.stat()
        if os.geteuid() == 0:
            os.chown(path, owner.st_uid, owner.st_gid, follow_symlinks=False)
        path.chmod(0o640)


def readonly_connection(path: Path) -> sqlite3.Connection:
    """GET paths never create a missing ledger, run migrations, or initialize accounts."""
    path = path.absolute()
    reject_symlinks(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise FileNotFoundError('报告数据源不存在')
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def database_locator(path: Path, root: Path) -> dict[str, str]:
    """Source paths come only from an already-open server-side store, never HTTP input."""
    path, root = Path(os.path.abspath(path)), Path(os.path.abspath(root))
    reject_symlinks(path)
    try:
        return {'relative': path.relative_to(root).as_posix()}
    except ValueError:
        # Explicit PALACE_DB and isolated test stores can live outside data_root.
        return {'absolute': str(path)}


def database_path(locator: dict, root: Path) -> Path:
    if set(locator) == {'relative'}:
        relative = Path(locator['relative'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('分享数据源记录无效')
        return root / relative
    if set(locator) == {'absolute'} and Path(locator['absolute']).is_absolute():
        return Path(locator['absolute'])
    raise ValueError('分享数据源记录无效')


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def register_share(token: str, identity: dict, descriptor: dict, *, root: Path | None = None) -> None:
    """Atomically pin the first publication. Another source cannot claim the same token."""
    validate_token(token)
    root = root or data_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = registry_path(root)
    reject_symlinks(path)
    # Restrictive mode from creation, not only after SQLite has written private metadata.
    created = False
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    except FileExistsError:
        pass
    else:
        os.close(fd)
        created = True
    try:
        readable_permissions(path, root)
    except Exception:
        if created and path.stat().st_size == 0:
            path.unlink()
        raise
    key, payload = hashlib.sha256(_json(identity).encode('utf-8')).hexdigest(), _json(descriptor)
    with closing(sqlite3.connect(path, timeout=15)) as conn, conn:
        conn.execute(SCHEMA)
        conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT identity_hash FROM report_shares WHERE token=?', (token,)).fetchone()
        if old:
            if old[0] != key:
                raise ValueError('分享令牌已绑定其他报告，拒绝覆盖')
            return
        conn.execute('INSERT INTO report_shares VALUES(?,?,?,?)', (token, key, payload, time.time()))


def lookup_share(token: str, *, root: Path | None = None) -> dict | None:
    validate_token(token)
    try:
        conn = readonly_connection(registry_path(root))
    except FileNotFoundError:
        return None
    with closing(conn):
        # The very first publication may be creating the schema concurrently.
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_shares'").fetchone():
            return None
        row = conn.execute('SELECT descriptor_json FROM report_shares WHERE token=?', (token,)).fetchone()
    return json.loads(row[0]) if row else None
