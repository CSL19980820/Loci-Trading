"""运维状态库：定时任务、执行历史、LLM 供应商。

与账本 (palace.db)、行情仓 (market.db) 一样物理隔离。

技能正文在 ``data/skills/*/SKILL.md``，MCP 在 ``data/mcp.json``——二者都不进本库。
本库只保留任务状态与 LLM API Key（本机明文存 ``encrypted_key`` 列；旧密文启动时尽量迁明文）。

实现拆分：
- ``store_helpers`` — 常量 / OpsError / new_id / dumps / loads
- ``store_schema`` — DDL 与迁移清单
- ``store_jobs`` / ``store_providers`` / ``store_strategy`` — 领域 mixin
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sqlite3

from src.shared.paths import ops_db as _current_ops_db
from src.ops.infrastructure.store_helpers import (
    DEFAULT_DB,
    JOB_KINDS,
    MANAGED_HOT_REBUILD,
    MANAGED_OUTCOME_CRON,
    MANAGED_OUTCOME_TRACK,
    MANAGED_SYNC_EOD,
    MANAGED_SYNC_INTRADAY,
    OpsError,
    RUN_STATUSES,
    _now,
    dumps,
    loads,
    new_id,
    yaml_safe_dump,
)
from src.ops.infrastructure.store_jobs import OpsJobsMixin
from src.ops.infrastructure.store_runs import OpsRunsMixin
from src.ops.infrastructure.store_providers import OpsProvidersMixin
from src.ops.infrastructure.store_schema import (
    SCHEMA_VERSION,
    _MIGRATIONS,
    _SCHEMA,
    _SCHEMA_READY,
)
from src.ops.infrastructure.store_retention import OpsRetentionMixin
from src.ops.infrastructure.store_strategy import OpsStrategyMixin
from src.ops.infrastructure.store_ai_decisions import OpsAiDecisionsMixin
from src.ops.infrastructure.store_alerts import OpsAlertsMixin
from src.ops.infrastructure.store_paper import OpsPaperMixin
from src.ops.infrastructure.store_paper_mem import OpsPaperMemMixin
from src.ops.infrastructure.store_quota import OpsQuotaMixin
from src.ops.infrastructure.store_signals import OpsSignalsMixin
from src.ops.infrastructure.store_watch import OpsWatchMixin

__all__ = [
    "DEFAULT_DB",
    "JOB_KINDS",
    "MANAGED_HOT_REBUILD",
    "MANAGED_OUTCOME_CRON",
    "MANAGED_OUTCOME_TRACK",
    "MANAGED_SYNC_EOD",
    "MANAGED_SYNC_INTRADAY",
    "OpsError",
    "OpsStore",
    "RUN_STATUSES",
    "SCHEMA_VERSION",
    "dumps",
    "loads",
    "new_id",
    "yaml_safe_dump",
]


class OpsStore(
    OpsJobsMixin,
    OpsRunsMixin,
    OpsProvidersMixin,
    OpsStrategyMixin,
    OpsAlertsMixin,
    OpsPaperMixin,
    OpsPaperMemMixin,
    OpsWatchMixin,
    OpsQuotaMixin,
    OpsAiDecisionsMixin,
    OpsSignalsMixin,
    OpsRetentionMixin,
):
    """任务 / LLM 供应商 / 提醒 / 纸面量化舱 / 记忆图 / 龙头留痕 / 实时信号 的读写。每个请求或任务持有独立连接。"""

    def __init__(self, db_path: Path | str | None = None) -> None:
        # 不传路径 = 用**当前租户**的 ops.db，每次构造重新解析。
        # ``DEFAULT_DB`` 是 import 期求值的常量：多租户下用它等于把全进程钉死在
        # 「最先 import 本模块的那个租户」的库上，供应商 / 会话 / 用量全串味，而且
        # 不报错（``src/community/infrastructure/store.py`` 的注释里点过这个名）。
        # 常量本身保留，只为兼容 ``from src.ops import DEFAULT_DB`` 的旧引用。
        self.db_path = Path(db_path) if db_path else _current_ops_db()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA busy_timeout=30000")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            if not self._schema_is_current():
                # 旧库：CREATE TABLE IF NOT EXISTS 不会补列，但 _SCHEMA 里依赖新列的
                # INDEX 会先于 ADD COLUMN 失败。先尽量建表 → 迁移补列 → 再补索引。
                self._apply_schema_compat()
                with self.conn:
                    self.conn.execute(
                        "INSERT INTO meta(key,value,updated_at) VALUES('schema_fingerprint',?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                        (self._schema_fingerprint(), _now()),
                    )
            # 仅兼容旧测试/诊断；是否迁移以当前连接中的持久化指纹为准，不信任路径缓存。
            _SCHEMA_READY.add(str(self.db_path.resolve()))
        except Exception:
            self.conn.close()
            raise

    def _schema_fingerprint(self) -> str:
        # DDL 内容也入指纹，防止新增迁移时漏改 SCHEMA_VERSION。SQLite 的 schema cookie
        # 检出删表/删索引；普通业务写入不改它，因此读取不会排队等业务写锁。
        digest = sha256((str(SCHEMA_VERSION) + _SCHEMA + "\n".join(_MIGRATIONS)).encode()).hexdigest()
        cookie = self.conn.execute("PRAGMA schema_version").fetchone()[0]
        return f"{digest}:{cookie}"

    def _schema_is_current(self) -> bool:
        try:
            row = self.conn.execute("SELECT value FROM meta WHERE key='schema_fingerprint'").fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table: meta" not in str(exc).lower():
                raise
            return False
        return bool(row and row[0] == self._schema_fingerprint())

    def _apply_schema_compat(self) -> None:
        """兼容已有 ops.db：允许首轮 schema 因缺列失败，迁移后再补齐。"""
        try:
            self.init_schema()
        except sqlite3.OperationalError:
            pass
        self._run_migrations()
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def _now(self) -> str:
        """本库统一时钟。真身在 ``store_helpers._now()``（本地时区 + 偏移 + 微秒）。

        留这个方法是因为各 mixin 已经在用 ``self._now()``；口径只有一处，
        ``job_runs`` 的时间戳与 ``paper_*`` / ``alert_*`` 从此对得上。
        """
        return _now()

    def __enter__(self) -> OpsStore:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Cursor]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield cursor
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    @contextmanager
    def guardian_commit_guard(self, run_id: str) -> Iterator[None]:
        """Serialize final ledger commits with cancellation/configuration writes."""
        with self._transaction(immediate=True):
            if run_id:
                run = self.get_run(run_id)
                if run is None or run["status"] != "running" or run.get("cancel_requested"):
                    raise OpsError("交易员运行已取消或结束，拒绝提交")
            yield

    def init_schema(self) -> None:
        with self._transaction() as cursor:
            cursor.executescript(_SCHEMA)
            cursor.execute(
                "INSERT INTO meta(key, value, updated_at) VALUES('schema_version', ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (str(SCHEMA_VERSION), _now()),
            )

    def _export_legacy_mcp_to_json(self) -> None:
        """旧 ops.db.mcp_servers → data/mcp.json（仅当 json 尚无同名项时）。"""
        try:
            rows = self.conn.execute("SELECT * FROM mcp_servers").fetchall()
        except sqlite3.Error:
            return
        if not rows:
            return
        try:
            from src.intel import load_mcp_json_raw, upsert_mcp_server_json
        except Exception:
            return
        existing = load_mcp_json_raw()
        servers = existing.get("mcpServers") or existing.get("mcp_servers") or {}
        if not isinstance(servers, dict):
            servers = {}
        for row in rows:
            name = str(row["name"])
            if name in servers:
                continue
            tools = loads(row["tools_json"] if "tools_json" in row.keys() else "[]", [])
            upsert_mcp_server_json(
                name=name,
                url=str(row["url"]),
                token=None,
                proxy_url=str(row["proxy_url"] or ""),
                note=str(row["note"] or "migrated-from-ops.db"),
                tools=tools if isinstance(tools, list) else [],
                tools_synced_at=str(row["tools_synced_at"] or ""),
                disabled=not bool(row["is_active"]),
            )

    def _export_legacy_skills_to_disk(self) -> None:
        """旧 ops.db.skills → 若目录缺 SKILL.md 则补写一份。"""
        try:
            rows = self.conn.execute("SELECT * FROM skills").fetchall()
        except sqlite3.Error:
            return
        from src.shared.paths import skill_root

        root = skill_root()
        root.mkdir(parents=True, exist_ok=True)
        for row in rows:
            slug = str(row["slug"])
            folder = root / slug
            folder.mkdir(parents=True, exist_ok=True)
            manifest = folder / "SKILL.md"
            if manifest.is_file():
                continue
            meta = {
                "name": str(row["name"] or slug),
                "slug": slug,
                "version": str(row["version"] or ""),
                "description": str(row["description"] or slug),
                "enabled": bool(row["enabled"]),
            }
            tools = loads(row["allowed_tools"] if "allowed_tools" in row.keys() else "[]", [])
            if tools:
                meta["tools"] = tools
            body = str(row["instructions"] or "").strip() or f"# {slug}\n"
            dumped = yaml_safe_dump(meta)
            manifest.write_text(f"---\n{dumped}\n---\n\n{body}\n", encoding="utf-8")

    def _run_migrations(self) -> None:
        """指纹不匹配时补加表和列；全部成功后才记录指纹，失败可安全重试。"""
        # 先把旧 skills / mcp_servers 迁出，再 DROP
        self._export_legacy_mcp_to_json()
        self._export_legacy_skills_to_disk()

        for sql in _MIGRATIONS:
            try:
                self.conn.execute(sql)
                self.conn.commit()
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "duplicate column name" in message or "already exists" in message:
                    continue
                raise
        self.conn.execute(
            "INSERT INTO meta(key, value, updated_at) VALUES('schema_version', ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (str(SCHEMA_VERSION), _now()),
        )
        self.conn.commit()
