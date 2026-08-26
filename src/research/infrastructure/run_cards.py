"""research run card 的原子 JSON 存储适配器。"""
from __future__ import annotations

from src.shared.clock import utc_now as _utc_now
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
from threading import RLock
import uuid
from typing import Any, Mapping

from src.research.domain.run_card import (
    ArtifactManifestEntry,
    ResearchRunCard,
    RunCardStatus,
    validate_relative_artifact_path,
    validate_run_id,
)
from src.research.infrastructure.artifacts import ResearchArtifactStore


_CARD_NAME = "run_card.json"
_MANIFEST_NAME = "artifact_manifest.json"
_JSON_LOCK = RLock()
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_TERMINAL_STATUSES = frozenset({"completed", "stale", "failed", "rejected"})
_TERMINAL_ARTIFACT_TYPES = {
    "workflow-final.json": "workflow_final",
    "run_card.md": "run_card_markdown",
    "replay-comparison.json": "replay_comparison",
}


class RunCardError(ValueError):
    """run card 不存在、输入冲突或状态迁移非法。"""


class RunCardNotFoundError(RunCardError):
    """找不到指定 run card。"""


class RunCardImmutableError(RunCardError):
    """已写入 run 的计算输入不可被覆盖。"""


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


class ResearchRunCardStore:
    """按 run 目录保存 ``run_card.json`` 和 manifest。

    ``ResearchArtifactStore`` 仍负责研究 run 的默认根目录与既有阶段文件；本
    适配器只新增 run card 文件，绝不重写 ``run.json``、``input/profile/review``。
    """

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        artifact_store: ResearchArtifactStore | None = None,
    ) -> None:
        self.artifact_store = artifact_store or ResearchArtifactStore(root)
        self.root = Path(root) if root is not None else Path(self.artifact_store.root)
        self.root = self.root.expanduser()

    @staticmethod
    def new_run_id() -> str:
        return ResearchArtifactStore.new_run_id()

    def _root_resolved(self) -> Path:
        try:
            return self.root.resolve()
        except OSError:
            return self.root.absolute()

    def _run_dir(self, run_id: str) -> Path:
        safe_id = validate_run_id(run_id)
        root = self._root_resolved()
        candidate = root / safe_id
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        if resolved != root and root not in resolved.parents:
            raise ValueError("研究 run 路径越界")
        return candidate

    def _card_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / _CARD_NAME

    def _manifest_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / _MANIFEST_NAME

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            json.dumps(
                _json_safe(payload),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
                default=str,
            )
            + "\n"
        ).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return _sha256_bytes(content)

    @staticmethod
    def _atomic_bytes_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _load_unlocked(self, run_id: str) -> ResearchRunCard | None:
        raw = self._read_json(self._card_path(run_id))
        if raw is None:
            return None
        try:
            return ResearchRunCard.from_dict(raw)
        except (TypeError, ValueError, KeyError) as exc:
            raise RunCardError(f"研究 run card 损坏：{run_id}") from exc

    @staticmethod
    def _same_result(left: ResearchRunCard, right: ResearchRunCard) -> bool:
        """比较可变结果部分，忽略更新时间和输入 hash。"""
        fields = (
            "metrics",
            "validation",
            "risk_xray",
            "conclusion",
            "status",
            "error",
            "artifact_manifest",
        )
        return all(getattr(left, key) == getattr(right, key) for key in fields)

    @staticmethod
    def _transition_allowed(current: RunCardStatus, target: RunCardStatus) -> bool:
        if current == target:
            return True
        return (current, target) in {
            ("running", "awaiting_human_review"),
            ("running", "stale"),
            ("running", "failed"),
            ("running", "rejected"),
            ("awaiting_human_review", "completed"),
            ("awaiting_human_review", "stale"),
            ("awaiting_human_review", "failed"),
            ("awaiting_human_review", "rejected"),
            ("completed", "stale"),
        }

    def _write_manifest_unlocked(self, card: ResearchRunCard) -> None:
        payload = {
            "contract_version": "research-artifact-manifest-v1",
            "run_id": card.run_id,
            "created_at": card.created_at,
            "updated_at": card.updated_at,
            "artifacts": [item.to_dict() for item in card.artifact_manifest],
        }
        self._atomic_json_write(self._manifest_path(card.run_id), payload)

    def _save_unlocked(self, card: ResearchRunCard) -> ResearchRunCard:
        existing = self._load_unlocked(card.run_id)
        if existing is not None:
            if existing.input_sha256 != card.input_sha256:
                raise RunCardImmutableError(
                    f"研究 run {card.run_id} 的计算输入已存在，禁止覆盖"
                )
            if not self._transition_allowed(existing.status, card.status):
                raise RunCardError(
                    f"研究 run 状态不能从 {existing.status} 迁移到 {card.status}"
                )
            # 完成/拒绝/失败后的指标和结论是审计结果；只允许 stale 状态或
            # manifest 追加，不接受 UI 通过同一 run_id 改写结果。
            if existing.status in {"completed", "stale", "failed", "rejected"}:
                output_changed = not self._same_result(existing, card)
                allowed_stale = existing.status == "completed" and card.status == "stale"
                manifest_only = (
                    existing.metrics == card.metrics
                    and existing.validation == card.validation
                    and existing.risk_xray == card.risk_xray
                    and existing.conclusion == card.conclusion
                    and existing.error == card.error
                    and existing.status == card.status
                )
                if output_changed and not (allowed_stale or manifest_only):
                    raise RunCardImmutableError(
                        f"研究 run {card.run_id} 已结束，结果不可覆盖"
                    )
                if not output_changed:
                    return existing

        self._atomic_json_write(self._card_path(card.run_id), card.to_dict())
        self._write_manifest_unlocked(card)
        return card

    def save(self, card: ResearchRunCard | Mapping[str, Any]) -> ResearchRunCard:
        """保存或追加一张 run card；同输入重复写是幂等的。"""
        value = card if isinstance(card, ResearchRunCard) else ResearchRunCard.from_dict(card)
        with _JSON_LOCK:
            return self._save_unlocked(value)

    write = save
    append = save

    def create(self, **kwargs: Any) -> ResearchRunCard:
        run_id = str(kwargs.pop("run_id", "") or self.new_run_id())
        card = ResearchRunCard(run_id=run_id, **kwargs)
        return self.save(card)

    create_run_card = create

    def load(
        self,
        run_id: str,
        *,
        current_strategy_revision: str | None = None,
        current_market_revision: str | None = None,
        strategy_revision: str | None = None,
        market_revision: str | None = None,
        mark_stale: bool = False,
    ) -> ResearchRunCard | None:
        """读取 run；版本变化仅返回 stale 投影，显式请求时才持久化。"""
        current_strategy_revision = (
            current_strategy_revision
            if current_strategy_revision is not None
            else strategy_revision
        )
        current_market_revision = (
            current_market_revision if current_market_revision is not None else market_revision
        )
        with _JSON_LOCK:
            card = self._load_unlocked(run_id)
            if card is None:
                return None
            changed = (
                current_strategy_revision is not None
                and bool(card.strategy_revision)
                and str(current_strategy_revision) != card.strategy_revision
            ) or (
                current_market_revision is not None
                and bool(card.market_revision)
                and str(current_market_revision) != card.market_revision
            )
            if changed and card.status == "completed":
                card = card.with_status("stale")
                if mark_stale:
                    card = self._save_unlocked(card)
            return card

    get = load
    read = load
    load_run_card = load

    def require(self, run_id: str, **kwargs: Any) -> ResearchRunCard:
        card = self.load(run_id, **kwargs)
        if card is None:
            raise RunCardNotFoundError(f"找不到研究 run card：{run_id}")
        return card

    def update_status(
        self,
        run_id: str,
        status: RunCardStatus,
        *,
        error: str = "",
    ) -> ResearchRunCard:
        with _JSON_LOCK:
            card = self._load_unlocked(run_id)
            if card is None:
                raise RunCardNotFoundError(f"找不到研究 run card：{run_id}")
            return self._save_unlocked(card.with_status(status, error=error))

    set_status = update_status

    def mark_stale(
        self,
        run_id: str,
        *,
        current_strategy_revision: str | None = None,
        current_market_revision: str | None = None,
    ) -> ResearchRunCard:
        """显式标记旧 run；保留原策略/行情 revision 和全部输入。"""
        with _JSON_LOCK:
            card = self._load_unlocked(run_id)
            if card is None:
                raise RunCardNotFoundError(f"找不到研究 run card：{run_id}")
            if card.status != "completed":
                return card
            if current_strategy_revision is not None and card.strategy_revision == str(current_strategy_revision):
                if current_market_revision is None or card.market_revision == str(current_market_revision):
                    return card
            if current_market_revision is not None and card.market_revision == str(current_market_revision):
                if current_strategy_revision is None or card.strategy_revision == str(current_strategy_revision):
                    return card
            return self._save_unlocked(card.with_status("stale"))

    mark_stale_if_revision_changed = mark_stale

    @staticmethod
    def _artifact_target(run_dir: Path, relative_path: str) -> Path:
        relative = validate_relative_artifact_path(relative_path)
        root = run_dir.resolve()
        target = (root / relative).resolve()
        if target == root or root not in target.parents:
            raise ValueError("artifact 路径越界")
        return target

    @staticmethod
    def _assert_terminal_artifact_allowed(
        card: ResearchRunCard,
        *,
        path: str,
        artifact_type: str,
        sha256: str,
    ) -> None:
        """终态只允许审计收尾 artifact，既有同 hash 写入保持幂等。"""
        if card.status not in _TERMINAL_STATUSES:
            return
        existing = {item.path: item for item in card.artifact_manifest}.get(path)
        if existing is not None:
            if existing.sha256 != sha256:
                raise RunCardImmutableError(f"artifact manifest 已存在且 hash 不同：{path}")
            return
        expected_type = _TERMINAL_ARTIFACT_TYPES.get(path)
        if expected_type != artifact_type:
            raise RunCardImmutableError(
                f"研究 run {card.run_id} 已结束，只允许追加终态审计 artifact"
            )

    def write_artifact(
        self,
        run_id: str,
        path: str,
        content: bytes | str | Mapping[str, Any],
        *,
        artifact_type: str = "",
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> ArtifactManifestEntry:
        """以原子方式写入 run 目录内文件并追加 manifest 条目。"""
        if isinstance(content, bytes):
            body = content
        elif isinstance(content, str):
            body = content.encode("utf-8")
        else:
            body = (
                json.dumps(
                    _json_safe(content),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")

        with _JSON_LOCK:
            card = self._load_unlocked(run_id)
            if card is None:
                raise RunCardNotFoundError(f"找不到研究 run card：{run_id}")
            target = self._artifact_target(self._run_dir(run_id), path)
            digest = _sha256_bytes(body)
            self._assert_terminal_artifact_allowed(
                card,
                path=path,
                artifact_type=artifact_type,
                sha256=digest,
            )
            if target.is_file():
                existing_digest = _sha256_file(target)
                if existing_digest != digest:
                    raise RunCardImmutableError(f"artifact 已存在且内容不同：{path}")
            else:
                self._atomic_bytes_write(target, body)
            entry = ArtifactManifestEntry(
                path=path,
                sha256=digest,
                created_at=created_at or _utc_now(),
                size_bytes=len(body),
                artifact_type=artifact_type,
                metadata=dict(metadata or {}),
            )
            current = {item.path: item for item in card.artifact_manifest}
            previous = current.get(entry.path)
            if previous is not None and previous.sha256 != entry.sha256:
                raise RunCardImmutableError(f"artifact manifest 已存在且 hash 不同：{path}")
            current[entry.path] = previous or entry
            next_card = card.with_updates(
                artifact_manifest=tuple(current[key] for key in sorted(current)),
            )
            self._save_unlocked(next_card)
            return current[entry.path]

    add_artifact = write_artifact

    def record_artifact(
        self,
        run_id: str,
        *,
        path: str,
        sha256: str,
        created_at: str | None = None,
        size_bytes: int | None = None,
        artifact_type: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactManifestEntry:
        """登记已经由其他适配器写好的文件；仍校验路径和内容 hash。"""
        if not _HEX64.fullmatch(str(sha256 or "")):
            raise ValueError("artifact sha256 无效")
        with _JSON_LOCK:
            card = self._load_unlocked(run_id)
            if card is None:
                raise RunCardNotFoundError(f"找不到研究 run card：{run_id}")
            target = self._artifact_target(self._run_dir(run_id), path)
            if not target.is_file():
                raise FileNotFoundError(str(target))
            actual = _sha256_file(target)
            if actual != str(sha256).lower():
                raise RunCardError(f"artifact hash 与文件内容不一致：{path}")
            self._assert_terminal_artifact_allowed(
                card,
                path=path,
                artifact_type=artifact_type,
                sha256=actual,
            )
            entry = ArtifactManifestEntry(
                path=path,
                sha256=actual,
                created_at=created_at or _utc_now(),
                size_bytes=size_bytes if size_bytes is not None else target.stat().st_size,
                artifact_type=artifact_type,
                metadata=dict(metadata or {}),
            )
            current = {item.path: item for item in card.artifact_manifest}
            previous = current.get(entry.path)
            if previous is not None and previous.sha256 != entry.sha256:
                raise RunCardImmutableError(f"artifact manifest 已存在且 hash 不同：{path}")
            current[entry.path] = previous or entry
            self._save_unlocked(card.with_updates(artifact_manifest=tuple(current.values())))
            return current[entry.path]

    def find_by_input_hash(self, input_sha256: str) -> ResearchRunCard | None:
        if not input_sha256 or not self.root.is_dir():
            return None
        with _JSON_LOCK:
            cards: list[ResearchRunCard] = []
            for path in self.root.glob(f"*/{_CARD_NAME}"):
                raw = self._read_json(path)
                if not raw:
                    continue
                try:
                    card = ResearchRunCard.from_dict(raw)
                except (TypeError, ValueError, KeyError):
                    continue
                if card.input_sha256 == input_sha256:
                    cards.append(card)
            cards.sort(key=lambda item: item.updated_at, reverse=True)
            return cards[0] if cards else None

    def list(self) -> list[ResearchRunCard]:
        if not self.root.is_dir():
            return []
        with _JSON_LOCK:
            cards: list[ResearchRunCard] = []
            for path in sorted(self.root.glob(f"*/{_CARD_NAME}")):
                raw = self._read_json(path)
                if raw:
                    cards.append(ResearchRunCard.from_dict(raw))
            return cards


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


RunCardStore = ResearchRunCardStore

__all__ = [
    "ResearchRunCardStore",
    "RunCardError",
    "RunCardImmutableError",
    "RunCardNotFoundError",
    "RunCardStore",
]
