"""研究 DAG 运行态的原子文件存储。

``workflow.json`` 是可恢复的运行态，不属于不可变 artifact manifest；工作流
终态会由 application 另写成带 hash 的 final artifact，避免把中间重试事件
误当成研究结论。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import uuid
from typing import Any

from src.research.domain.dag import ResearchWorkflow
from src.research.domain.run_card import validate_run_id
from src.shared.paths import research_runs_dir


class WorkflowStorageError(ValueError):
    """工作流状态无法读取、保存或并发版本不匹配。"""


class WorkflowConcurrencyError(WorkflowStorageError):
    """调用方基于已经被其他执行器更新的事件流保存。"""


_LOCK = threading.RLock()


class ResearchWorkflowStore:
    """按 run 隔离保存可恢复 workflow 状态。"""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or research_runs_dir()).expanduser()

    def _path(self, run_id: str) -> Path:
        safe = validate_run_id(run_id)
        try:
            root = self.root.resolve()
        except OSError:
            root = self.root.absolute()
        candidate = root / safe / "workflow.json"
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        if root not in resolved.parents:
            raise WorkflowStorageError("工作流路径越界")
        return candidate

    def create(self, workflow: ResearchWorkflow) -> ResearchWorkflow:
        """仅创建新的运行态，避免静默覆盖已有工作流。"""
        with _LOCK:
            path = self._path(workflow.run_id)
            if path.exists():
                raise WorkflowStorageError(f"研究工作流已存在：{workflow.run_id}")
            self._write(path, workflow.to_dict())
        return workflow

    def load(self, run_id: str) -> ResearchWorkflow | None:
        with _LOCK:
            path = self._path(run_id)
            if not path.is_file():
                return None
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise TypeError("workflow 不是 object")
                return ResearchWorkflow.from_dict(raw)
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise WorkflowStorageError(f"研究工作流损坏：{run_id}") from exc

    def save(
        self,
        workflow: ResearchWorkflow,
        *,
        expected_event_count: int | None = None,
    ) -> ResearchWorkflow:
        """原子保存，并可按已有事件数做轻量乐观并发校验。"""
        with _LOCK:
            path = self._path(workflow.run_id)
            existing = self.load(workflow.run_id)
            if expected_event_count is not None:
                actual = len(existing.events) if existing is not None else 0
                if actual != int(expected_event_count):
                    raise WorkflowConcurrencyError(
                        f"工作流事件已更新：期望 {expected_event_count}，实际 {actual}"
                    )
            self._write(path, workflow.to_dict())
        return workflow

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


__all__ = [
    "ResearchWorkflowStore",
    "WorkflowConcurrencyError",
    "WorkflowStorageError",
]
