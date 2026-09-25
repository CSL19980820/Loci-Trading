"""Skill Run 持久化：data/skill_runs/<id>.json + events.jsonl。"""
from __future__ import annotations

from src.shared.clock import utc_now as _now
import json
import os
from pathlib import Path
import threading
from typing import Any
import uuid
from collections import OrderedDict

from src.shared.paths import skill_runs_dir

_lock = threading.Lock()
_event_indexes: OrderedDict[str, tuple[int, int, list[int], int]] = OrderedDict()


def new_run_id() -> str:
    return f"SR-{uuid.uuid4().hex[:12]}"


def _run_path(run_id: str) -> Path:
    root = skill_runs_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{run_id}.json"


def _events_path(run_id: str) -> Path:
    return skill_runs_dir() / f"{run_id}.events.jsonl"


def _read_run_unlocked(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_run_unlocked(state: dict[str, Any], path: Path) -> dict[str, Any]:
    state["updated_at"] = _now()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return state


def _append_event_unlocked(run_id: str, event: dict[str, Any]) -> None:
    payload = {"ts": _now(), **event}
    path = _events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def save_run(state: dict[str, Any]) -> dict[str, Any]:
    run_id = str(state["id"])
    path = _run_path(run_id)
    with _lock:
        return _write_run_unlocked(state, path)


def load_run(run_id: str) -> dict[str, Any] | None:
    return _read_run_unlocked(_run_path(run_id))


def append_event(run_id: str, event: dict[str, Any]) -> None:
    with _lock:
        _append_event_unlocked(run_id, event)


def claim_user_reply(run_id: str, reply: str) -> dict[str, Any] | None:
    """原子领取一次 waiting_user 回复；已被其他请求领取时返回 None。"""
    path = _run_path(run_id)
    with _lock:
        state = _read_run_unlocked(path)
        if state is None or state.get("status") != "waiting_user":
            return None
        state["status"] = "running"
        state["pending_ask"] = {}
        _write_run_unlocked(state, path)
        _append_event_unlocked(run_id, {"type": "user_reply", "text": str(reply)[:500]})
        return state


def read_events(run_id: str, *, after: int = 0, limit: int = 200) -> tuple[list[dict[str, Any]], int]:
    """Read complete physical lines, preserving cursors across corrupt/partial writes.

    An LRU byte-offset index makes repeated tail polling independent of history size.
    A first read after restart builds the index once; incomplete final lines are retried.
    Replacement/truncation starts a new physical-line generation and resets its cursor.
    """
    path = _events_path(run_id)
    if not path.is_file():
        return [], after
    rows: list[dict[str, Any]] = []
    after = max(0, after)
    limit = max(1, min(limit, 1000))
    try:
        with _lock, path.open('rb') as handle:
            # The pathname may rotate after open; metadata must describe this handle.
            stat = os.fstat(handle.fileno())
            key = str(path.resolve())
            cached = _event_indexes.pop(key, None)
            replaced = cached is not None and (
                cached[0] != stat.st_ino or cached[1] > stat.st_size
                or (cached[1] == stat.st_size and cached[3] != stat.st_mtime_ns)
            )
            offsets = cached[2] if cached and not replaced else [0]
            if replaced:
                after = 0
            handle.seek(offsets[-1])
            while True:
                line = handle.readline()
                if not line or not line.endswith(b'\n'):
                    break
                offsets.append(handle.tell())
            _event_indexes[key] = (stat.st_ino, stat.st_size, offsets, stat.st_mtime_ns)
            while len(_event_indexes) > 128:
                _event_indexes.popitem(last=False)
            if after > len(offsets) - 1:
                after = 0
            cursor = after
            handle.seek(offsets[cursor])
            stop = min(len(offsets) - 1, cursor + limit)
            while cursor < stop:
                line = handle.readline()
                try:
                    item = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    item = None
                if isinstance(item, dict):
                    item['_seq'] = cursor
                    rows.append(item)
                cursor += 1
            return rows, max(after, cursor)
    except OSError:
        return [], after


def list_events(run_id: str, *, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    return read_events(run_id, after=after, limit=limit)[0]


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
