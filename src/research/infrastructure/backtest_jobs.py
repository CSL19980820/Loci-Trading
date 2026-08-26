"""研究回测的轻量持久化异步 job 适配器。"""
from __future__ import annotations

from src.shared.clock import utc_now as _now
import json
import os
from pathlib import Path
from threading import RLock
import uuid
from typing import Any, Mapping

from src.shared.paths import research_runs_dir


_LOCK = RLock()


class ResearchBacktestJobStore:
    """JSON job 队列状态；运行进程丢失后的 running 记录明确标为 failed。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or research_runs_dir() / "backtest_jobs.json")

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        values = raw.get("jobs", {}) if isinstance(raw, dict) else {}
        return values if isinstance(values, dict) else {}

    def _write(self, jobs: Mapping[str, Mapping[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        target = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        target.write_text(json.dumps({"contract_version": "research-backtest-jobs-v1", "jobs": jobs}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(target, self.path)

    def create(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with _LOCK:
            jobs = self._read()
            job_id = f"RBJ-{uuid.uuid4().hex[:12]}"
            job = {"id": job_id, "status": "queued", "request": dict(request), "run_id": "", "error": "", "created_at": _now(), "updated_at": _now()}
            jobs[job_id] = job
            self._write(jobs)
            return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with _LOCK:
            job = self._read().get(job_id)
            return dict(job) if isinstance(job, dict) else None

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with _LOCK:
            jobs = self._read()
            job = jobs.get(job_id)
            if not isinstance(job, dict):
                raise KeyError(f"研究回测任务不存在：{job_id}")
            job.update(changes, updated_at=_now())
            jobs[job_id] = job
            self._write(jobs)
            return dict(job)

    def recover_interrupted(self) -> list[str]:
        """启动时收敛上个进程遗留的 job，绝不重排队读取新行情。"""
        with _LOCK:
            jobs = self._read()
            recovered: list[str] = []
            for job_id, job in jobs.items():
                if not isinstance(job, dict) or job.get("status") not in {"queued", "running"}:
                    continue
                job.update(
                    status="failed",
                    error="interrupted: 进程重启中断，未重排队以避免读取不同市场数据",
                    interrupted_at=_now(),
                    updated_at=_now(),
                )
                recovered.append(str(job_id))
            if recovered:
                self._write(jobs)
            return recovered


__all__ = ["ResearchBacktestJobStore"]
