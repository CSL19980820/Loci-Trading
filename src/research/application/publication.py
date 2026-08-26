"""人工签署研究回测发布结论。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.research.application.backtest_support import write_terminal_artifacts
from src.research.domain.dag import ResearchStage
from src.research.domain.run_card import ResearchRunCard
from src.research.infrastructure import ResearchRunCardStore, ResearchWorkflowStore


class ResearchPublicationError(ValueError):
    """人工签署不满足审计或状态约束。"""


_TERMINAL_ARTIFACTS = {
    "approved": frozenset({
        "human-review.json",
        "publish.json",
        "workflow-final.json",
        "run_card.md",
    }),
    "rejected": frozenset({
        "human-review.json",
        "rejection.json",
        "workflow-final.json",
        "run_card.md",
    }),
}
_REPLAY_COMPARISON_PATH = "replay-comparison.json"
_REPLAY_COMPARISON_V1 = "research-replay-comparison-v1"
_REPLAY_COMPARISON_V2 = "research-replay-comparison-v2"

def manifest_sha256(card: ResearchRunCard) -> str:
    """返回当前 artifact manifest 的规范 hash，供人工签署绑定。"""
    return _manifest_sha256(card.run_id, [item.to_dict() for item in card.artifact_manifest])


def _manifest_sha256(run_id: str, artifacts: list[Mapping[str, Any]]) -> str:
    payload = {"run_id": run_id, "artifacts": artifacts}
    body = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def publish_research_backtest(
    run_id: str,
    *,
    reviewer: str,
    reason: str,
    manifest_digest: str,
    run_card_store: ResearchRunCardStore,
    workflow_store: ResearchWorkflowStore,
) -> dict[str, Any]:
    """以人工签署完成已通过验证的 run；相同签署可安全重试。"""
    clean_reviewer = str(reviewer).strip()
    clean_reason = str(reason).strip()
    submitted_digest = str(manifest_digest).lower()
    if not clean_reviewer or not clean_reason:
        raise ResearchPublicationError("reviewer 和 reason 不能为空")
    if len(submitted_digest) != 64 or any(char not in "0123456789abcdef" for char in submitted_digest):
        raise ResearchPublicationError("manifest_sha256 无效")

    card = run_card_store.require(run_id)
    existing = _read_receipt(run_card_store, card, "human-review.json")
    if card.status == "completed":
        if _is_idempotent_review_retry(
            run_card_store,
            card,
            existing,
            run_id,
            clean_reviewer,
            clean_reason,
            submitted_digest,
            decision="approved",
        ):
            workflow = workflow_store.load(run_id)
            return {
                "run_card": card.to_dict(),
                "workflow": workflow.to_dict() if workflow else {},
                "reused": True,
            }
        raise ResearchPublicationError("研究 run 已发布，签署内容不一致")
    if card.status != "awaiting_human_review":
        raise ResearchPublicationError("研究 run 当前不等待人工审核")
    if str(card.validation.get("status") or "") != "passed":
        raise ResearchPublicationError("仅 validation passed 的研究 run 可以发布")
    if existing is None and manifest_sha256(card) != submitted_digest:
        raise ResearchPublicationError("manifest_sha256 与当前 artifact manifest 不一致")
    if existing is not None and not _same_review(
        existing, run_id, clean_reviewer, clean_reason, submitted_digest
    ):
        raise ResearchPublicationError("已有人工签署与本次请求不一致")

    workflow = workflow_store.load(run_id)
    if workflow is None or workflow.status != "awaiting_human_review":
        raise ResearchPublicationError("研究工作流不处于等待人工审核状态")

    if existing is None:
        review_entry = run_card_store.write_artifact(
            run_id,
            "human-review.json",
            {
                "status": "approved",
                "run_id": run_id,
                "manifest_sha256": submitted_digest,
                "artifact_manifest_sha256": submitted_digest,
                "signed_artifact_manifest": [
                    item.to_dict() for item in card.artifact_manifest
                ],
                "reviewer": clean_reviewer,
                "reason": clean_reason,
            },
            artifact_type="human_review_receipt",
        )
    else:
        review_entry = next(item for item in card.artifact_manifest if item.path == "human-review.json")

    review_started = workflow.start_stage(ResearchStage.REVIEW)
    workflow_store.save(review_started, expected_event_count=len(workflow.events))
    review_completed = review_started.complete_stage(
        ResearchStage.REVIEW,
        artifact_sha256=review_entry.sha256,
        detail="human review approved",
    )
    workflow_store.save(review_completed, expected_event_count=len(review_started.events))

    publish_started = review_completed.start_stage(ResearchStage.PUBLISH)
    workflow_store.save(publish_started, expected_event_count=len(review_completed.events))
    publish_entry = run_card_store.write_artifact(
        run_id,
        "publish.json",
        {
            "status": "completed",
            "run_id": run_id,
            "review_manifest_sha256": submitted_digest,
            "reviewer": clean_reviewer,
            "reason": clean_reason,
            "default_parameters_changed": False,
        },
        artifact_type="publish_receipt",
    )
    card = run_card_store.require(run_id)
    card = run_card_store.save(
        card.with_updates(
            conclusion={
                "status": "evidence_passed",
                "reviewer": clean_reviewer,
                "reason": clean_reason,
                "default_parameters_changed": False,
            }
        ).with_status("completed")
    )
    completed = publish_started.complete_stage(
        ResearchStage.PUBLISH,
        artifact_sha256=publish_entry.sha256,
        detail="human-signed publication completed",
    )
    workflow_store.save(completed, expected_event_count=len(publish_started.events))
    write_terminal_artifacts(run_card_store, card, completed)
    card = run_card_store.require(run_id)
    return {"run_card": card.to_dict(), "workflow": completed.to_dict(), "reused": False}


def reject_research_backtest(
    run_id: str,
    *,
    reviewer: str,
    reason: str,
    manifest_digest: str,
    run_card_store: ResearchRunCardStore,
    workflow_store: ResearchWorkflowStore,
) -> dict[str, Any]:
    """以人工否决结束等待审核的研究 run，并保留不可变决策回执。"""
    clean_reviewer = str(reviewer).strip()
    clean_reason = str(reason).strip()
    submitted_digest = str(manifest_digest).lower()
    if not clean_reviewer or not clean_reason:
        raise ResearchPublicationError("reviewer 和 reason 不能为空")
    if len(submitted_digest) != 64 or any(char not in "0123456789abcdef" for char in submitted_digest):
        raise ResearchPublicationError("manifest_sha256 无效")

    card = run_card_store.require(run_id)
    existing_review = _read_receipt(run_card_store, card, "human-review.json")
    existing_rejection = _read_receipt(run_card_store, card, "rejection.json")
    if card.status == "rejected":
        if (
            _is_idempotent_review_retry(
                run_card_store,
                card,
                existing_review,
                run_id,
                clean_reviewer,
                clean_reason,
                submitted_digest,
                decision="rejected",
            )
            and _same_rejection_content(
                existing_rejection, run_id, clean_reviewer, clean_reason
            )
        ):
            workflow = workflow_store.load(run_id)
            return {
                "run_card": card.to_dict(),
                "workflow": workflow.to_dict() if workflow else {},
                "reused": True,
            }
        raise ResearchPublicationError("研究 run 已被否决，签署内容不一致或回执不完整")
    if card.status != "awaiting_human_review":
        raise ResearchPublicationError("研究 run 当前不等待人工审核")
    if existing_review is None and manifest_sha256(card) != submitted_digest:
        raise ResearchPublicationError("manifest_sha256 与当前 artifact manifest 不一致")
    if existing_review is not None and not _same_review(
        existing_review,
        run_id,
        clean_reviewer,
        clean_reason,
        submitted_digest,
        decision="rejected",
    ):
        raise ResearchPublicationError("已有人工签署与本次否决不一致")

    workflow = workflow_store.load(run_id)
    if workflow is None or workflow.status != "awaiting_human_review":
        raise ResearchPublicationError("研究工作流不处于等待人工审核状态")

    if existing_review is None:
        review_entry = run_card_store.write_artifact(
            run_id,
            "human-review.json",
            {
                "status": "rejected",
                "run_id": run_id,
                "manifest_sha256": submitted_digest,
                "artifact_manifest_sha256": submitted_digest,
                "signed_artifact_manifest": [
                    item.to_dict() for item in card.artifact_manifest
                ],
                "reviewer": clean_reviewer,
                "reason": clean_reason,
            },
            artifact_type="human_review_receipt",
        )
    else:
        review_entry = next(
            item for item in card.artifact_manifest if item.path == "human-review.json"
        )

    review_started = workflow.start_stage(ResearchStage.REVIEW)
    workflow_store.save(review_started, expected_event_count=len(workflow.events))
    review_completed = review_started.complete_stage(
        ResearchStage.REVIEW,
        artifact_sha256=review_entry.sha256,
        detail="human review rejected",
    )
    workflow_store.save(review_completed, expected_event_count=len(review_started.events))

    publish_started = review_completed.start_stage(ResearchStage.PUBLISH)
    workflow_store.save(publish_started, expected_event_count=len(review_completed.events))
    rejection_entry = run_card_store.write_artifact(
        run_id,
        "rejection.json",
        {
            "status": "rejected",
            "run_id": run_id,
            "review_manifest_sha256": submitted_digest,
            "reviewer": clean_reviewer,
            "reason": clean_reason,
            "default_parameters_changed": False,
        },
        artifact_type="rejection_receipt",
    )
    card = run_card_store.require(run_id)
    card = run_card_store.save(
        card.with_updates(
            conclusion={
                "status": "rejected",
                "reviewer": clean_reviewer,
                "reason": clean_reason,
                "default_parameters_changed": False,
            }
        ).with_status("rejected")
    )
    completed = publish_started.complete_stage(
        ResearchStage.PUBLISH,
        artifact_sha256=rejection_entry.sha256,
        detail="human rejection recorded; publication not performed",
    )
    workflow_store.save(completed, expected_event_count=len(publish_started.events))
    write_terminal_artifacts(run_card_store, card, completed)
    card = run_card_store.require(run_id)
    return {"run_card": card.to_dict(), "workflow": completed.to_dict(), "reused": False}


def _same_review(
    receipt: Mapping[str, Any] | None,
    run_id: str,
    reviewer: str,
    reason: str,
    manifest_digest: str,
    *,
    decision: str = "approved",
) -> bool:
    return bool(
        _same_review_content(receipt, run_id, reviewer, reason, decision=decision)
        and str(receipt.get("manifest_sha256") or "").lower() == manifest_digest
    )


def _same_review_content(
    receipt: Mapping[str, Any] | None,
    run_id: str,
    reviewer: str,
    reason: str,
    *,
    decision: str,
) -> bool:
    return bool(
        receipt
        and receipt.get("status") == decision
        and receipt.get("run_id") == run_id
        and receipt.get("reviewer") == reviewer
        and receipt.get("reason") == reason
    )


def _is_idempotent_review_retry(
    store: ResearchRunCardStore,
    card: ResearchRunCard,
    receipt: Mapping[str, Any] | None,
    run_id: str,
    reviewer: str,
    reason: str,
    manifest_digest: str,
    *,
    decision: str,
) -> bool:
    if not _same_review_content(receipt, run_id, reviewer, reason, decision=decision):
        return False
    # Both the original signing digest and the post-terminal manifest digest
    # are valid retry tokens only while the completed evidence set is intact.
    # Otherwise a stale client could hide an on-disk artifact mutation by
    # reusing the signing digest.
    if not _final_manifest_matches_review(store, card, receipt, decision=decision):
        return False
    signed_digest = str(receipt.get("manifest_sha256") or "").lower()
    return manifest_digest == signed_digest or manifest_digest == manifest_sha256(card)


def _final_manifest_matches_review(
    store: ResearchRunCardStore,
    card: ResearchRunCard,
    receipt: Mapping[str, Any],
    *,
    decision: str,
) -> bool:
    signed = receipt.get("signed_artifact_manifest")
    if not isinstance(signed, list):
        return False
    signed_by_path = {
        str(item.get("path") or ""): item
        for item in signed
        if isinstance(item, Mapping) and item.get("path")
    }
    if len(signed_by_path) != len(signed):
        return False
    current_by_path = {item.path: item for item in card.artifact_manifest}
    expected_paths = set(signed_by_path) | set(_TERMINAL_ARTIFACTS[decision])
    if not expected_paths <= set(current_by_path):
        return False
    post_terminal_paths = set(current_by_path) - expected_paths
    if post_terminal_paths - {_REPLAY_COMPARISON_PATH}:
        return False
    if not _artifact_manifest_is_intact(store, card):
        return False
    if any(
        current_by_path[path].to_dict() != signed_entry
        for path, signed_entry in signed_by_path.items()
    ):
        return False
    if post_terminal_paths == {_REPLAY_COMPARISON_PATH}:
        return _replay_comparison_matches_review(
            store,
            card,
            receipt,
            signed_by_path=signed_by_path,
            current_by_path=current_by_path,
        )
    # 走到这里 post_terminal_paths 必为空：376 行排除了其它路径，385 行处理了
    # 只剩重放对照的情形。
    return True


def _replay_comparison_matches_review(
    store: ResearchRunCardStore,
    card: ResearchRunCard,
    review: Mapping[str, Any],
    *,
    signed_by_path: Mapping[str, Mapping[str, Any]],
    current_by_path: Mapping[str, Any],
) -> bool:
    entry = current_by_path[_REPLAY_COMPARISON_PATH]
    if entry.artifact_type != "replay_comparison":
        return False
    try:
        comparison = _read_receipt(store, card, _REPLAY_COMPARISON_PATH)
    except ResearchPublicationError:
        return False
    if comparison is None or comparison.get("run_id") != card.run_id:
        return False
    frozen = signed_by_path.get("frozen_input.json")
    if frozen is None:
        return False
    signed_digest = str(review.get("manifest_sha256") or "").lower()
    signed_manifest_digest = _manifest_sha256(card.run_id, list(signed_by_path.values()))
    manifest_without_replay = _manifest_sha256(
        card.run_id,
        [
            item.to_dict()
            for path, item in current_by_path.items()
            if path != _REPLAY_COMPARISON_PATH
        ],
    )
    version = comparison.get("contract_version")
    if version == _REPLAY_COMPARISON_V1:
        # v1 错把 frozen input 的 hash 命名为 source_manifest；保留已落盘回执的可重试性。
        return bool(
            signed_digest == signed_manifest_digest
            and str(comparison.get("source_manifest_sha256") or "").lower()
            == frozen.get("sha256")
        )
    if version != _REPLAY_COMPARISON_V2:
        return False
    return bool(
        signed_digest == signed_manifest_digest
        and str(comparison.get("source_manifest_sha256") or "").lower()
        == manifest_without_replay
        and str(comparison.get("source_frozen_input_sha256") or "").lower()
        == frozen.get("sha256")
        and str(comparison.get("source_signed_manifest_sha256") or "").lower()
        == signed_digest
        and entry.metadata.get("source_manifest_sha256") == manifest_without_replay
        and entry.metadata.get("source_frozen_input_sha256") == frozen.get("sha256")
        and entry.metadata.get("source_signed_manifest_sha256") == signed_digest
    )


def _artifact_manifest_is_intact(store: ResearchRunCardStore, card: ResearchRunCard) -> bool:
    root = Path(store.root).resolve()
    for entry in card.artifact_manifest:
        target = (root / card.run_id / entry.path).resolve()
        if root not in target.parents or not target.is_file():
            return False
        if hashlib.sha256(target.read_bytes()).hexdigest() != entry.sha256:
            return False
    return True


def _same_rejection_content(
    receipt: Mapping[str, Any] | None,
    run_id: str,
    reviewer: str,
    reason: str,
) -> bool:
    return bool(
        receipt
        and receipt.get("status") == "rejected"
        and receipt.get("run_id") == run_id
        and receipt.get("reviewer") == reviewer
        and receipt.get("reason") == reason
    )


def _read_receipt(
    store: ResearchRunCardStore, card: ResearchRunCard, path: str
) -> Mapping[str, Any] | None:
    entry = next((item for item in card.artifact_manifest if item.path == path), None)
    if entry is None:
        return None
    root = Path(store.root).resolve()
    target = (root / card.run_id / path).resolve()
    if root not in target.parents or not target.is_file():
        raise ResearchPublicationError("人工签署 artifact 不存在")
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry.sha256:
        raise ResearchPublicationError("人工签署 artifact 完整性校验失败")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchPublicationError("人工签署 artifact 不是有效 JSON") from exc
    if not isinstance(payload, Mapping):
        raise ResearchPublicationError("人工签署 artifact 格式无效")
    return payload


__all__ = [
    "ResearchPublicationError",
    "manifest_sha256",
    "publish_research_backtest",
    "reject_research_backtest",
]
