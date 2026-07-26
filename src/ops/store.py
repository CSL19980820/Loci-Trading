"""运维状态库：技能包、定时任务、执行历史、LLM 供应商。

与账本 (qianlong.db)、行情仓 (market.db) 一样物理隔离。这里存的是**配置
与执行痕迹**：改一条 cron、装一个技能包，都不该去碰不可变的交易账本，
也不该和批量行情写入抢锁。

密钥只以密文形式落在这里，主密钥在环境变量里，两者永远不在同一个位置。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Any
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = PROJECT_ROOT / ".ops" / "ops.db"

SCHEMA_VERSION = 1

#: 任务类型。每种对应 src/ops/jobs.py 里的一个执行器。
JOB_KINDS = ("sync", "screen", "backtest", "compare", "optimize", "prune", "skill")

#: 任务与执行状态。
RUN_STATUSES = ("running", "success", "failed", "skipped")


class OpsError(RuntimeError):
    """运维库的可预期错误，应转成 4xx 而不是 500。"""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 技能包：一个 zip 解出来的目录 + 它的元数据。
-- 装一个包 = 多一个"模式"，可以被定时任务按配置的 LLM 反复执行。
CREATE TABLE IF NOT EXISTS skills (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    version         TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    instructions    TEXT NOT NULL DEFAULT '',
    install_path    TEXT NOT NULL,
    source_filename TEXT NOT NULL DEFAULT '',
    content_sha256  TEXT NOT NULL DEFAULT '',
    allowed_tools   TEXT NOT NULL DEFAULT '[]',
    default_cron    TEXT NOT NULL DEFAULT '',
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    enabled         INTEGER NOT NULL DEFAULT 1,
    installed_at    TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- LLM 供应商：名称 + Base URL + 协议 + 密文 Key。
-- 不硬编码厂商枚举，新增一家 = 加一行配置，不改代码。
CREATE TABLE IF NOT EXISTS llm_providers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    protocol        TEXT NOT NULL CHECK (protocol IN ('openai_compatible', 'anthropic')),
    base_url        TEXT NOT NULL,
    encrypted_key   BLOB,
    key_last4       TEXT NOT NULL DEFAULT '',
    default_model   TEXT NOT NULL DEFAULT '',
    models_json     TEXT NOT NULL DEFAULT '[]',
    models_synced_at TEXT NOT NULL DEFAULT '',
    proxy_url       TEXT NOT NULL DEFAULT '',
    is_active       INTEGER NOT NULL DEFAULT 1,
    validated_at    TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- 外部 MCP server。接一个新数据源 = 加一行配置，工具由 tools/list 自动发现，
-- 不需要为每个接口手写一份 schema。token 与 LLM Key 同样只存密文。
CREATE TABLE IF NOT EXISTS mcp_servers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    url             TEXT NOT NULL,
    encrypted_token BLOB,
    token_last4     TEXT NOT NULL DEFAULT '',
    proxy_url       TEXT NOT NULL DEFAULT '',
    tools_json      TEXT NOT NULL DEFAULT '[]',
    tools_synced_at TEXT NOT NULL DEFAULT '',
    is_active       INTEGER NOT NULL DEFAULT 1,
    note            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- 定时任务。cron 表达式 + 类型 + 该类型自己的配置。
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,
    cron         TEXT NOT NULL DEFAULT '',
    config_json  TEXT NOT NULL DEFAULT '{}',
    enabled      INTEGER NOT NULL DEFAULT 1,
    last_run_at  TEXT NOT NULL DEFAULT '',
    last_status  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_enabled ON jobs(enabled, kind);

-- 每次执行的痕迹。定时任务最怕的是"静默地一直失败"，
-- 所以每次都记，且失败要留完整错误文本而不只是一个状态码。
CREATE TABLE IF NOT EXISTS job_runs (
    id           TEXT PRIMARY KEY,
    job_id       TEXT NOT NULL,
    job_name     TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL DEFAULT '',
    trigger      TEXT NOT NULL DEFAULT 'manual',
    status       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT NOT NULL DEFAULT '',
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    result_json  TEXT NOT NULL DEFAULT '{}',
    error_text   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_job ON job_runs(job_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON job_runs(status, started_at DESC);
"""

_SCHEMA_READY: set[str] = set()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {} if fallback is None else fallback


class OpsStore:
    """技能 / 任务 / 供应商的读写。每个请求或任务持有独立连接。"""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        key = str(self.db_path.resolve())
        if key not in _SCHEMA_READY:
            self.init_schema()
            _SCHEMA_READY.add(key)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> OpsStore:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN")
            yield cursor
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def init_schema(self) -> None:
        with self._transaction() as cursor:
            cursor.executescript(_SCHEMA)
            cursor.execute(
                "INSERT INTO meta(key, value, updated_at) VALUES('schema_version', ?, datetime('now'))"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (str(SCHEMA_VERSION),),
            )

    # ---- 技能包 ---------------------------------------------------

    def upsert_skill(self, payload: dict[str, Any]) -> str:
        slug = str(payload["slug"])
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO skills(slug, name, version, description, instructions,
                                   install_path, source_filename, content_sha256,
                                   allowed_tools, default_cron, metadata_json,
                                   enabled, installed_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
                ON CONFLICT(slug) DO UPDATE SET
                    name=excluded.name, version=excluded.version,
                    description=excluded.description, instructions=excluded.instructions,
                    install_path=excluded.install_path,
                    source_filename=excluded.source_filename,
                    content_sha256=excluded.content_sha256,
                    allowed_tools=excluded.allowed_tools,
                    default_cron=excluded.default_cron,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    slug,
                    str(payload.get("name", slug)),
                    str(payload.get("version", "")),
                    str(payload.get("description", "")),
                    str(payload.get("instructions", "")),
                    str(payload["install_path"]),
                    str(payload.get("source_filename", "")),
                    str(payload.get("content_sha256", "")),
                    dumps(payload.get("allowed_tools", [])),
                    str(payload.get("default_cron", "")),
                    dumps(payload.get("metadata", {})),
                ),
            )
        return slug

    def get_skill(self, slug: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM skills WHERE slug = ?", (slug,)).fetchone()
        return self._skill_row(row) if row else None

    def list_skills(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM skills"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY slug"
        return [self._skill_row(row) for row in self.conn.execute(sql)]

    def set_skill_enabled(self, slug: str, enabled: bool) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE skills SET enabled = ?, updated_at = datetime('now') WHERE slug = ?",
                (1 if enabled else 0, slug),
            )

    def delete_skill(self, slug: str) -> bool:
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM skills WHERE slug = ?", (slug,))
            return cursor.rowcount > 0

    @staticmethod
    def _skill_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["allowed_tools"] = loads(data.get("allowed_tools"), [])
        data["metadata"] = loads(data.pop("metadata_json", "{}"), {})
        data["enabled"] = bool(data.get("enabled"))
        return data

    # ---- 定时任务 -------------------------------------------------

    def create_job(
        self, *, name: str, kind: str, cron: str = "", config: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> str:
        if kind not in JOB_KINDS:
            raise OpsError(f"未知任务类型：{kind}（可选 {list(JOB_KINDS)}）")
        job_id = new_id("JOB")
        with self._transaction() as cursor:
            try:
                cursor.execute(
                    "INSERT INTO jobs(id, name, kind, cron, config_json, enabled,"
                    " created_at, updated_at)"
                    " VALUES(?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                    (job_id, name, kind, cron, dumps(config or {}), 1 if enabled else 0),
                )
            except sqlite3.IntegrityError as exc:
                raise OpsError(f"任务名已存在：{name}") from exc
        return job_id

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {"name", "cron", "config", "enabled"}
        unknown = set(fields) - allowed
        if unknown:
            raise OpsError(f"不可更新的字段：{sorted(unknown)}")
        assignments, params = [], []
        for key, value in fields.items():
            if key == "config":
                assignments.append("config_json = ?")
                params.append(dumps(value))
            elif key == "enabled":
                assignments.append("enabled = ?")
                params.append(1 if value else 0)
            else:
                assignments.append(f"{key} = ?")
                params.append(value)
        if not assignments:
            return
        assignments.append("updated_at = datetime('now')")
        params.append(job_id)
        with self._transaction() as cursor:
            cursor.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", params)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_row(row) if row else None

    def get_job_by_name(self, name: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE name = ?", (name,)).fetchone()
        return self._job_row(row) if row else None

    def list_jobs(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name"
        return [self._job_row(row) for row in self.conn.execute(sql)]

    def delete_job(self, job_id: str) -> bool:
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return cursor.rowcount > 0

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["config"] = loads(data.pop("config_json", "{}"), {})
        data["enabled"] = bool(data.get("enabled"))
        return data

    # ---- 执行历史 -------------------------------------------------

    def start_run(self, job: dict[str, Any], *, trigger: str = "manual") -> str:
        run_id = new_id("RUN")
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO job_runs(id, job_id, job_name, kind, trigger, status, started_at)"
                " VALUES(?, ?, ?, ?, ?, 'running', datetime('now'))",
                (run_id, job.get("id", ""), job.get("name", ""), job.get("kind", ""), trigger),
            )
        return run_id

    def finish_run(
        self, run_id: str, *, status: str, result: Any = None, error: str = "",
        duration_ms: int = 0,
    ) -> None:
        if status not in RUN_STATUSES:
            raise OpsError(f"未知执行状态：{status}")
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE job_runs SET status = ?, finished_at = datetime('now'),"
                " duration_ms = ?, result_json = ?, error_text = ? WHERE id = ?",
                (status, int(duration_ms), dumps(result if result is not None else {}),
                 error[:4000], run_id),
            )
            row = cursor.execute(
                "SELECT job_id FROM job_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row and row["job_id"]:
                cursor.execute(
                    "UPDATE jobs SET last_run_at = datetime('now'), last_status = ?,"
                    " updated_at = datetime('now') WHERE id = ?",
                    (status, row["job_id"]),
                )

    def list_runs(
        self, *, job_id: str | None = None, limit: int = 50, status: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM job_runs WHERE 1=1"
        params: list[Any] = []
        if job_id:
            sql += " AND job_id = ?"
            params.append(job_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY started_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        rows = []
        for row in self.conn.execute(sql, params):
            data = dict(row)
            data["result"] = loads(data.pop("result_json", "{}"), {})
            rows.append(data)
        return rows

    def prune_runs(self, keep_per_job: int = 200) -> int:
        """只保留每个任务最近 N 条执行记录。

        定时任务是每天跑的，不清理的话这张表会无限增长，最终把小小的
        运维库撑成几百 MB。
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM job_runs WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY job_id ORDER BY started_at DESC, id DESC
                        ) AS rn FROM job_runs
                    ) ranked WHERE rn > ?
                )
                """,
                (int(keep_per_job),),
            )
            return cursor.rowcount

    # ---- LLM 供应商 -----------------------------------------------

    def upsert_provider(self, payload: dict[str, Any]) -> str:
        provider_id = payload.get("id") or new_id("LLM")
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO llm_providers(id, name, protocol, base_url, encrypted_key,
                                          key_last4, default_model, models_json,
                                          models_synced_at, proxy_url, is_active,
                                          validated_at, note, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    protocol=excluded.protocol, base_url=excluded.base_url,
                    encrypted_key=COALESCE(excluded.encrypted_key, llm_providers.encrypted_key),
                    key_last4=CASE WHEN excluded.encrypted_key IS NOT NULL
                                   THEN excluded.key_last4 ELSE llm_providers.key_last4 END,
                    default_model=excluded.default_model, models_json=excluded.models_json,
                    models_synced_at=excluded.models_synced_at, proxy_url=excluded.proxy_url,
                    is_active=excluded.is_active, validated_at=excluded.validated_at,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (
                    provider_id,
                    str(payload["name"]),
                    str(payload["protocol"]),
                    str(payload["base_url"]).rstrip("/"),
                    payload.get("encrypted_key"),
                    str(payload.get("key_last4", "")),
                    str(payload.get("default_model", "")),
                    dumps(payload.get("models", [])),
                    str(payload.get("models_synced_at", "")),
                    str(payload.get("proxy_url", "")),
                    1 if payload.get("is_active", True) else 0,
                    str(payload.get("validated_at", "")),
                    str(payload.get("note", "")),
                ),
            )
        return provider_id

    def get_provider(self, name_or_id: str, *, include_secret: bool = False) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM llm_providers WHERE name = ? OR id = ?", (name_or_id, name_or_id)
        ).fetchone()
        return self._provider_row(row, include_secret=include_secret) if row else None

    def list_providers(self) -> list[dict[str, Any]]:
        return [
            self._provider_row(row)
            for row in self.conn.execute("SELECT * FROM llm_providers ORDER BY name")
        ]

    def delete_provider(self, name_or_id: str) -> bool:
        with self._transaction() as cursor:
            cursor.execute(
                "DELETE FROM llm_providers WHERE name = ? OR id = ?", (name_or_id, name_or_id)
            )
            return cursor.rowcount > 0

    # ---- MCP server ------------------------------------------------

    def upsert_mcp_server(self, payload: dict[str, Any]) -> str:
        server_id = payload.get("id") or new_id("MCP")
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO mcp_servers(id, name, url, encrypted_token, token_last4,
                                        proxy_url, tools_json, tools_synced_at,
                                        is_active, note, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    url=excluded.url,
                    encrypted_token=COALESCE(excluded.encrypted_token, mcp_servers.encrypted_token),
                    token_last4=CASE WHEN excluded.encrypted_token IS NOT NULL
                                     THEN excluded.token_last4 ELSE mcp_servers.token_last4 END,
                    proxy_url=excluded.proxy_url, tools_json=excluded.tools_json,
                    tools_synced_at=excluded.tools_synced_at, is_active=excluded.is_active,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (
                    server_id,
                    str(payload["name"]),
                    str(payload["url"]).rstrip("/"),
                    payload.get("encrypted_token"),
                    str(payload.get("token_last4", "")),
                    str(payload.get("proxy_url", "")),
                    dumps(payload.get("tools", [])),
                    str(payload.get("tools_synced_at", "")),
                    1 if payload.get("is_active", True) else 0,
                    str(payload.get("note", "")),
                ),
            )
        return server_id

    def get_mcp_server(
        self, name_or_id: str, *, include_secret: bool = False
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM mcp_servers WHERE name = ? OR id = ?", (name_or_id, name_or_id)
        ).fetchone()
        return self._mcp_row(row, include_secret=include_secret) if row else None

    def list_mcp_servers(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM mcp_servers"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY name"
        return [self._mcp_row(row) for row in self.conn.execute(sql)]

    def delete_mcp_server(self, name_or_id: str) -> bool:
        with self._transaction() as cursor:
            cursor.execute(
                "DELETE FROM mcp_servers WHERE name = ? OR id = ?", (name_or_id, name_or_id)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _mcp_row(row: sqlite3.Row, *, include_secret: bool = False) -> dict[str, Any]:
        data = dict(row)
        data["tools"] = loads(data.pop("tools_json", "[]"), [])
        data["is_active"] = bool(data.get("is_active"))
        secret = data.pop("encrypted_token", None)
        data["has_token"] = secret is not None
        if include_secret:
            data["encrypted_token"] = secret
        return data

    @staticmethod
    def _provider_row(row: sqlite3.Row, *, include_secret: bool = False) -> dict[str, Any]:
        data = dict(row)
        data["models"] = loads(data.pop("models_json", "[]"), [])
        data["is_active"] = bool(data.get("is_active"))
        secret = data.pop("encrypted_key", None)
        data["has_key"] = secret is not None
        if include_secret:
            # 只有真正要发起调用时才带上密文，且调用方需立刻解密使用、不得留存。
            data["encrypted_key"] = secret
        return data
