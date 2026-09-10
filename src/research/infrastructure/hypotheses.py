"""Hypothesis 的本地 JSON 持久化适配器。

研究假设不是行情或账本事实，因此使用可替换的文件产物保存。写入同时受
进程内锁、短期跨进程锁和原子替换保护，避免并发更新丢失或留下半个 JSON。
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import time
from typing import Iterator

from src.research.domain.hypothesis import (
    EvidenceLink,
    Hypothesis,
    HypothesisConcurrencyError,
    HypothesisError,
    HypothesisStatus,
)
from src.shared.paths import research_runs_dir


class HypothesisStorageError(HypothesisError):
    """假设文件无法读取或格式不合法。"""


_LOCK_TIMEOUT_SECONDS = 5.0
_STALE_LOCK_SECONDS = 300.0
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def default_hypotheses_path() -> Path:
    """返回研究域假设产物的默认路径。"""
    return research_runs_dir() / "hypotheses.json"


def _thread_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """取得同进程及跨进程的短期排他锁。"""
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    local_lock = _thread_lock(path)
    with local_lock:
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(descriptor, str(os.getpid()).encode("ascii", errors="ignore"))
            except FileExistsError as exc:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    if age > _STALE_LOCK_SECONDS:
                        lock_path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise HypothesisConcurrencyError(f"假设文件锁超时：{path}") from exc
                time.sleep(0.01)
        try:
            yield
        finally:
            os.close(descriptor)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


class HypothesisStore:
    """按聚合保存和更新假设的文件 store。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or default_hypotheses_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def create(self, hypothesis: Hypothesis) -> Hypothesis:
        """原子创建假设；重复 ID 不覆盖旧记录。"""
        with _exclusive_lock(self.path):
            records, registry_revision = self._read_unlocked()
            if any(item.hypothesis_id == hypothesis.hypothesis_id for item in records):
                raise HypothesisError(f"假设已存在：{hypothesis.hypothesis_id}")
            self._write_unlocked([*records, hypothesis], registry_revision + 1)
        return hypothesis

    def get(self, hypothesis_id: str) -> Hypothesis | None:
        """读取一个假设的快照。"""
        with _exclusive_lock(self.path):
            records, _ = self._read_unlocked()
        return next((item for item in records if item.hypothesis_id == hypothesis_id), None)

    def list(self, *, status: HypothesisStatus | str | None = None) -> list[Hypothesis]:
        """读取全部假设，可按生命周期状态过滤。"""
        with _exclusive_lock(self.path):
            records, _ = self._read_unlocked()
        if status is None:
            return records
        normalized = status if isinstance(status, HypothesisStatus) else HypothesisStatus(str(status))
        return [item for item in records if item.status is normalized]

    def save(self, hypothesis: Hypothesis, *, expected_revision: int) -> Hypothesis:
        """以乐观版本校验保存领域对象。"""
        with _exclusive_lock(self.path):
            records, registry_revision = self._read_unlocked()
            index = self._index(records, hypothesis.hypothesis_id)
            current = records[index]
            if current.revision != int(expected_revision):
                raise HypothesisConcurrencyError(
                    f"假设 {hypothesis.hypothesis_id} 已更新：期望 revision "
                    f"{expected_revision}，实际 {current.revision}"
                )
            if hypothesis.revision != current.revision + 1:
                raise HypothesisConcurrencyError("保存对象必须是当前版本的下一 revision")
            records[index] = hypothesis
            self._write_unlocked(records, registry_revision + 1)
        return hypothesis

    def attach_evidence(
        self,
        hypothesis_id: str,
        evidence: EvidenceLink,
        *,
        actor: str,
        occurred_at: str | None = None,
    ) -> Hypothesis:
        """在同一锁内追加证据，避免读改写竞态。"""
        with _exclusive_lock(self.path):
            records, registry_revision = self._read_unlocked()
            index = self._index(records, hypothesis_id)
            updated = records[index].attach_evidence(
                evidence,
                actor=actor,
                occurred_at=occurred_at,
            )
            records[index] = updated
            self._write_unlocked(records, registry_revision + 1)
        return updated

    def transition(
        self,
        hypothesis_id: str,
        target: HypothesisStatus | str,
        *,
        actor: str,
        reason: str,
        evidence: tuple[EvidenceLink, ...] = (),
        occurred_at: str | None = None,
    ) -> Hypothesis:
        """在锁内完成状态转换、证据校验和审计写入。"""
        with _exclusive_lock(self.path):
            records, registry_revision = self._read_unlocked()
            index = self._index(records, hypothesis_id)
            updated = records[index].transition(
                target,
                actor=actor,
                reason=reason,
                evidence=evidence,
                occurred_at=occurred_at,
            )
            records[index] = updated
            self._write_unlocked(records, registry_revision + 1)
        return updated

    def _read_unlocked(self) -> tuple[list[Hypothesis], int]:
        if not self.path.exists():
            return [], 0
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HypothesisStorageError(f"无法读取假设文件：{self.path}") from exc
        if isinstance(raw, list):
            # 允许从早期实验性的 bare-list 产物恢复，再以新契约写回。
            items = raw
            registry_revision = 0
        elif isinstance(raw, dict):
            items = raw.get("hypotheses", [])
            registry_revision = int(raw.get("registry_revision") or 0)
        else:
            raise HypothesisStorageError("假设文件必须是 JSON list 或 registry object")
        if not isinstance(items, list):
            raise HypothesisStorageError("假设文件 hypotheses 必须是 JSON list")
        try:
            records = [Hypothesis.from_dict(item) for item in items if isinstance(item, dict)]
        except (TypeError, ValueError) as exc:
            raise HypothesisStorageError("假设文件包含无效领域记录") from exc
        return records, registry_revision

    def _write_unlocked(self, records: list[Hypothesis], registry_revision: int) -> None:
        payload = {
            "contract_version": "research-hypotheses-v1",
            "registry_revision": int(registry_revision),
            "hypotheses": [item.to_dict() for item in records],
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _index(records: list[Hypothesis], hypothesis_id: str) -> int:
        for index, record in enumerate(records):
            if record.hypothesis_id == hypothesis_id:
                return index
        raise KeyError(f"假设不存在：{hypothesis_id}")


__all__ = ["HypothesisStore", "HypothesisStorageError", "default_hypotheses_path"]
