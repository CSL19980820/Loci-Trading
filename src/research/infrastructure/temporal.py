"""可追加的 PIT 事实与历史股票池快照存储。

这里不负责联网抓取。接入财报、公告或指数成分供应商时，适配器只能把带
``available_at``/来源/版本的事实写进来；缺少历史快照时 resolve 会保留
degraded，而不会拿今天的名单回填历史。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import uuid
from typing import Any, Iterable

from src.research.domain.temporal import (
    MembershipSnapshot,
    PointInTimeObservation,
    resolve_membership,
    select_point_in_time,
)
from src.shared.paths import research_runs_dir


class TemporalStoreError(ValueError):
    """PIT 产物损坏或试图覆盖同一不可变事实。"""


_LOCK = threading.RLock()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
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


def _read_items(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TemporalStoreError(f"无法读取时点产物：{path}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get(key, []), list):
        raise TemporalStoreError(f"时点产物格式无效：{path}")
    return [item for item in raw[key] if isinstance(item, dict)]


class PointInTimeFactStore:
    """追加式财务/事件事实注册表。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or research_runs_dir() / "point_in_time_facts.json")

    def list(self, *, entity_id: str | None = None) -> list[PointInTimeObservation]:
        with _LOCK:
            items = [PointInTimeObservation.from_dict(raw) for raw in _read_items(self.path, "facts")]
        return [item for item in items if entity_id is None or item.entity_id == entity_id]

    def record(self, observation: PointInTimeObservation) -> PointInTimeObservation:
        """同一 observation_id 仅允许幂等重放，禁止修改已记录事实。"""
        return self.record_many((observation,))[0]

    def record_many(
        self, observations: Iterable[PointInTimeObservation]
    ) -> list[PointInTimeObservation]:
        """原子追加多条 PIT 事实；同 id 仅允许内容完全相同的重放。"""
        incoming = list(observations)
        if not incoming:
            return []
        with _LOCK:
            records = self.list()
            by_id = {item.observation_id: item for item in records}
            accepted: list[PointInTimeObservation] = []
            appended: list[PointInTimeObservation] = []
            for observation in incoming:
                existing = by_id.get(observation.observation_id)
                if existing is not None and existing.to_dict() != observation.to_dict():
                    raise TemporalStoreError(
                        f"PIT 事实已存在且内容不同：{observation.observation_id}"
                    )
                resolved = existing or observation
                if existing is None:
                    by_id[observation.observation_id] = observation
                    appended.append(observation)
                accepted.append(resolved)
            if appended:
                _write_json(
                    self.path,
                    {
                        "contract_version": "research-pit-facts-v2",
                        "facts": [*(item.to_dict() for item in records), *(item.to_dict() for item in appended)],
                    },
                )
        return accepted

    def select(
        self,
        *,
        as_of: str,
        entity_id: str,
        fact_type: str | None = None,
    ) -> PointInTimeObservation | None:
        items = self.list(entity_id=entity_id)
        if fact_type:
            items = [item for item in items if item.fact_type == fact_type]
        return select_point_in_time(items, as_of=as_of, entity_id=entity_id)


class MembershipSnapshotStore:
    """追加式历史成分注册表；读取时保留降级语义。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or research_runs_dir() / "membership_snapshots.json")

    def list(self, *, universe_id: str | None = None) -> list[MembershipSnapshot]:
        with _LOCK:
            items = [MembershipSnapshot.from_dict(raw) for raw in _read_items(self.path, "snapshots")]
        return [item for item in items if universe_id is None or item.universe_id == universe_id]

    def record(self, snapshot: MembershipSnapshot) -> MembershipSnapshot:
        """按 universe/date/revision 追加；同键只能幂等写入。"""
        return self.record_many((snapshot,))[0]

    def record_many(
        self, snapshots: Iterable[MembershipSnapshot]
    ) -> list[MembershipSnapshot]:
        """原子追加多个历史股票池快照，拒绝覆盖或部分导入。"""
        incoming = list(snapshots)
        if not incoming:
            return []
        with _LOCK:
            records = self.list()
            def key_for(item: MembershipSnapshot) -> tuple[str, str, str]:
                return (item.universe_id, item.as_of, item.snapshot_revision)

            by_key = {key_for(item): item for item in records}
            accepted: list[MembershipSnapshot] = []
            appended: list[MembershipSnapshot] = []
            for snapshot in incoming:
                key = key_for(snapshot)
                existing = by_key.get(key)
                if existing is not None and existing.to_dict() != snapshot.to_dict():
                    raise TemporalStoreError(
                        "历史股票池快照已存在且内容不同："
                        f"{snapshot.universe_id}@{snapshot.as_of}"
                    )
                resolved = existing or snapshot
                if existing is None:
                    by_key[key] = snapshot
                    appended.append(snapshot)
                accepted.append(resolved)
            if appended:
                _write_json(
                    self.path,
                    {
                        "contract_version": "research-membership-snapshots-v3",
                        "snapshots": [
                            *(item.to_dict() for item in records),
                            *(item.to_dict() for item in appended),
                        ],
                    },
                )
        return accepted

    def resolve(self, *, universe_id: str, as_of: str) -> MembershipSnapshot:
        return resolve_membership(self.list(universe_id=universe_id), universe_id=universe_id, as_of=as_of)


__all__ = [
    "MembershipSnapshotStore",
    "PointInTimeFactStore",
    "TemporalStoreError",
]
