"""Skill Run 持久化：data/skill_runs/<id>.json + events.jsonl。"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
import uuid

from src.shared.paths import skill_runs_dir

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return f"SR-{uuid.uuid4().hex[:12]}"


def _run_path(run_id: str) -> Path:
    root = skill_runs_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{run_id}.json"


def _events_path(run_id: str) -> Path:
    return skill_runs_dir() / f"{run_id}.events.jsonl"


def save_run(state: dict[str, Any]) -> dict[str, Any]:
    run_id = str(state["id"])
    state["updated_at"] = _now()
    path = _run_path(run_id)
    tmp = path.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    return state


def load_run(run_id: str) -> dict[str, Any] | None:
    path = _run_path(run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def append_event(run_id: str, event: dict[str, Any]) -> None:
    payload = {"ts": _now(), **event}
    path = _events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def list_events(run_id: str, *, after: int = 0) -> list[dict[str, Any]]:
    path = _events_path(run_id)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for index, line in enumerate(lines):
        if index < after:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            item["_seq"] = index
            rows.append(item)
    return rows


def create_run(*, skill: str, provider: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    state = {
        "id": new_run_id(),
        "skill": skill,
        "provider": provider,
        "config": config or {},
        "status": "running",
        "created_at": _now(),
        "updated_at": _now(),
        "messages": [],
        "pending_ask": {},
        "subagents": [],
        "result": {},
        "error": "",
    }
    save_run(state)
    append_event(state["id"], {"type": "created", "skill": skill})
    return state
