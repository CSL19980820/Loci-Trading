"""研究回测的轻量持久化异步 job 适配器。"""
from __future__ import annotations

from src.shared.clock import utc_now as _now
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import uuid
from typing import Any, Mapping

from src.shared.paths import research_runs_dir, ops_db


_PROCESS_ID = uuid.uuid4().hex


class DuplicateResearchJob(ValueError):
    pass


class ResearchBacktestJobStore:
    """Tenant SQLite job state; legacy JSON is imported once and retained for rollback."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or research_runs_dir() / "backtest_jobs.json")
        self.db_path = ((self.path.parent.parent if self.path.parent.name == "research_runs" else self.path.parent) / "ops.db") if path is not None else Path(ops_db())
        if self.path.parent.resolve() == research_runs_dir().resolve():
            self.db_path = Path(ops_db())
        self.namespace = self.path.name

    def _connect(self):
        # Explicit paths are isolation roots (tests/imports); defaults use the tenant ops DB.
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS research_jobs (namespace TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(namespace,id))")
            conn.execute("CREATE INDEX IF NOT EXISTS research_jobs_status ON research_jobs(namespace,json_extract(payload,'$.status'))")
            conn.execute("CREATE TABLE IF NOT EXISTS research_job_imports (namespace TEXT PRIMARY KEY)")
            imported = conn.execute("SELECT 1 FROM research_job_imports WHERE namespace=?", (self.namespace,)).fetchone()
            if imported:
                return conn
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                imported = conn.execute("SELECT 1 FROM research_job_imports WHERE namespace=?", (self.namespace,)).fetchone()
                if not imported:
                    raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
                    jobs = raw.get("jobs", {}) if isinstance(raw, dict) else {}
                    if not isinstance(jobs, dict):
                        jobs = {}
                    for job_id, job in jobs.items():
                        if not isinstance(job, dict):
                            continue
                        conn.execute("INSERT OR IGNORE INTO research_jobs VALUES(?,?,?)", (self.namespace, job_id, json.dumps(job, ensure_ascii=False)))
                    conn.execute("INSERT INTO research_job_imports VALUES(?)", (self.namespace,))
            return conn
        except BaseException:
            conn.close()
            raise

    def _read(self):
        with closing(self._connect()) as conn:
            return {key: json.loads(value) for key, value in conn.execute("SELECT id,payload FROM research_jobs WHERE namespace=?", (self.namespace,))}

    def _write(self, jobs):
        with closing(self._connect()) as conn, conn:
            conn.executemany("INSERT INTO research_jobs VALUES(?,?,?) ON CONFLICT(namespace,id) DO UPDATE SET payload=excluded.payload", [(self.namespace, key, json.dumps(value, ensure_ascii=False)) for key, value in jobs.items()])

    def create(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            encoded = json.dumps(dict(request), ensure_ascii=False, sort_keys=True)
            pending = conn.execute("SELECT payload FROM research_jobs WHERE namespace=? AND json_extract(payload,'$.status') IN ('queued','running')", (self.namespace,))
            for row in pending:
                previous = json.loads(row[0])
                if json.dumps(previous.get('request', {}), ensure_ascii=False, sort_keys=True) == encoded:
                    raise DuplicateResearchJob(f"相同研究任务仍在处理中：{previous['id']}")
            job_id = f"RBJ-{uuid.uuid4().hex[:12]}"
            job = {"id": job_id, "status": "queued", "process_id": _PROCESS_ID, "request": dict(request), "run_id": "", "error": "", "created_at": _now(), "updated_at": _now()}
            conn.execute("INSERT INTO research_jobs VALUES(?,?,?)", (self.namespace, job_id, json.dumps(job, ensure_ascii=False)))
            return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT payload FROM research_jobs WHERE namespace=? AND id=?", (self.namespace, job_id)).fetchone()
            return json.loads(row[0]) if row else None

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM research_jobs WHERE namespace=? AND id=?", (self.namespace, job_id)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = json.loads(row[0])
            job.update(changes, updated_at=_now())
            conn.execute("UPDATE research_jobs SET payload=? WHERE namespace=? AND id=?", (json.dumps(job, ensure_ascii=False), self.namespace, job_id))
            return job

    def export_legacy(self, destination: Path) -> None:
        """Explicit rollback export; never overwrite the preserved pre-migration JSON."""
        if destination.resolve() == self.path.resolve():
            raise ValueError("原 JSON 是迁移备份，请导出到新文件")
        destination.write_text(json.dumps({"contract_version": "research-backtest-jobs-v1", "jobs": self._read()}, ensure_ascii=False), encoding="utf-8")

    def recover_interrupted(self) -> list[str]:
        """Atomically fail only prior-process pending jobs; never replay market work."""
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id,payload FROM research_jobs WHERE namespace=? "
                "AND json_extract(payload,'$.status') IN ('queued','running') "
                "AND COALESCE(json_extract(payload,'$.process_id'),'') != ?",
                (self.namespace, _PROCESS_ID),
            ).fetchall()
            for job_id, payload in rows:
                job = json.loads(payload)
                job.update(status="failed",
                           error="interrupted: 进程重启中断，未重排队以避免读取不同市场数据",
                           interrupted_at=_now(), updated_at=_now())
                conn.execute("UPDATE research_jobs SET payload=? WHERE namespace=? AND id=?",
                             (json.dumps(job, ensure_ascii=False), self.namespace, job_id))
            return [row[0] for row in rows]


__all__ = ["ResearchBacktestJobStore"]


def recover_research_jobs() -> None:
    """Recover only existing stores, across all tenant roots; never replay market work."""
    from src.shared.paths import data_dir
    from src.shared.tenancy import PRIMARY_TENANT, list_tenant_ids, tenant_paths, tenant_scope
    root = data_dir()
    for tenant in [PRIMARY_TENANT, *list_tenant_ids(root)]:
        paths = tenant_paths(root, tenant)
        for name in ("backtest_jobs.json", "factor_jobs.json"):
            path = paths.research_runs_dir / name
            with tenant_scope(tenant):
                store = ResearchBacktestJobStore(path)
            exists = path.is_file()
            if not exists and store.db_path.is_file():
                with closing(sqlite3.connect(f'{store.db_path.resolve().as_uri()}?mode=ro', uri=True)) as conn:
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_jobs'").fetchone():
                        exists = bool(conn.execute('SELECT 1 FROM research_jobs WHERE namespace=? LIMIT 1', (name,)).fetchone())
            if exists:
                store.recover_interrupted()
