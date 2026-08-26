"""研究 run 的原子 JSON 产物存储。"""
from __future__ import annotations

from src.shared.clock import utc_now as _now
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
import uuid
from typing import Any

from src.shared.paths import research_runs_dir


_ID_PATTERN = re.compile(r"^RR-[A-Za-z0-9]{12}$")
_lock = RLock()


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ResearchArtifactStore:
    """按 run 隔离的 JSON 文件存储；阶段文件通过替换写入。"""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or research_runs_dir())

    @staticmethod
    def new_run_id() -> str:
        return f"RR-{uuid.uuid4().hex[:12]}"

    def _run_dir(self, run_id: str) -> Path:
        if not _ID_PATTERN.fullmatch(run_id):
            raise ValueError("研究 run id 无效")
        return self.root / run_id

    def _run_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run.json"

    def _stage_path(self, run_id: str, stage: str) -> Path:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,40}", stage):
            raise ValueError("研究阶段名无效")
        return self._run_dir(run_id) / f"{stage}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def create_run(self, *, code: str, budget: str, requested_as_of: str) -> dict[str, Any]:
        run_id = self.new_run_id()
        state = {
            "id": run_id,
            "contract_version": "research-run-v1",
            "status": "running",
            "code": code,
            "budget": budget,
            "requested_as_of": requested_as_of,
            "created_at": _now(),
            "updated_at": _now(),
            "input_sha256": "",
            "market_revision": "",
            "as_of": "",
            "stages": {},
            "error": "",
        }
        with _lock:
            self._write(self._run_path(run_id), state)
        return state

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        with _lock:
            return self._read(self._run_path(run_id))

    def save_run(self, state: dict[str, Any]) -> dict[str, Any]:
        run_id = str(state.get("id") or "")
        state["updated_at"] = _now()
        with _lock:
            self._write(self._run_path(run_id), state)
        return state

    def write_stage(self, run_id: str, stage: str, payload: dict[str, Any]) -> str:
        with _lock:
            return self._write(self._stage_path(run_id, stage), payload)

    def load_stage(self, run_id: str, stage: str) -> dict[str, Any] | None:
        with _lock:
            return self._read(self._stage_path(run_id, stage))

    def find_by_input_hash(self, input_sha256: str) -> dict[str, Any] | None:
        if not input_sha256 or not self.root.is_dir():
            return None
        candidates: list[dict[str, Any]] = []
        with _lock:
            for path in self.root.glob("RR-*/run.json"):
                state = self._read(path)
                if state and state.get("input_sha256") == input_sha256:
                    candidates.append(state)
        candidates.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return candidates[0] if candidates else None

    def stage_digest(self, payload: dict[str, Any]) -> str:
        """公开给 application 记录依赖 hash；不暴露文件路径。"""
        return _digest(payload)
