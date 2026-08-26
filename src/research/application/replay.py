"""基于冻结 artifact 的研究回测重放。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.backtest import build_universe_control, execute_backtest_context
from src.research.application.backtest_run import slice_research_backtest_phase
from src.research.application.backtest_support import backtest_payload, json_safe
from src.research.application.frozen import context_from_payload, payload_sha256
from src.research.application.publication import manifest_sha256
from src.research.infrastructure import ResearchRunCardStore


class ResearchReplayError(ValueError):
    """冻结输入缺失、篡改或重放结果不一致。"""


def replay_research_backtest(
    store: Any,
    run_id: str,
    *,
    run_card_store: ResearchRunCardStore | None = None,
) -> dict[str, Any]:
    cards = run_card_store or ResearchRunCardStore()
    card = cards.require(run_id)
    source_manifest_sha256 = manifest_sha256(card)
    entry, raw = _read_verified_artifact(cards, card, "frozen_input.json")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchReplayError("冻结输入 artifact 不是有效 JSON") from exc
    if not isinstance(payload, dict) or payload_sha256(payload) != entry.sha256:
        raise ResearchReplayError("冻结输入 artifact 内容 hash 校验失败")
    expected_hash = str(card.data_snapshot.get("frozen_input_sha256") or "")
    if expected_hash and expected_hash != entry.sha256:
        raise ResearchReplayError("run card 的冻结输入 hash 与 manifest 不一致")

    context = context_from_payload(payload)
    result = execute_backtest_context(store, context, use_fast=False)
    control = build_universe_control(store, context, use_fast=False)
    phases: dict[str, Any] = {}
    split = payload.get("split")
    if isinstance(split, dict):
        for name in ("train", "oos"):
            start, end = split.get(f"{name}_start"), split.get(f"{name}_end")
            if isinstance(start, str) and isinstance(end, str):
                phase = slice_research_backtest_phase(context, start, end)
                phases[name] = backtest_payload(execute_backtest_context(store, phase, use_fast=False))
    _, execution_raw = _read_verified_artifact(cards, card, "backtest.json")
    try:
        expected_execution = json.loads(execution_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchReplayError("backtest artifact 不是有效 JSON") from exc
    if not isinstance(expected_execution, dict):
        raise ResearchReplayError("backtest artifact 格式无效")

    observed_execution = {
        "result": backtest_payload(result),
        "random_control_events": backtest_payload(control),
        "isolated_train": phases.get("train"),
        "isolated_oos": phases.get("oos"),
    }
    execution_matches = {
        "main": expected_execution.get("result") == observed_execution["result"],
        "control": (
            expected_execution.get("random_control_events")
            == observed_execution["random_control_events"]
        ),
        "train": expected_execution.get("isolated_train") == observed_execution["isolated_train"],
        "oos": expected_execution.get("isolated_oos") == observed_execution["isolated_oos"],
    }
    expected_metrics = json_safe(card.metrics)
    observed_metrics = json_safe(result.metrics)
    metrics_match = expected_metrics == observed_metrics
    comparison = {
        "contract_version": "research-replay-comparison-v2",
        "run_id": run_id,
        "source_manifest_sha256": source_manifest_sha256,
        "source_frozen_input_sha256": entry.sha256,
        "source_signed_manifest_sha256": _review_manifest_sha256(cards, card),
        "input_sha256": card.input_sha256,
        "matches_card_metrics": metrics_match,
        "execution_matches": execution_matches,
        "matches_all_recomputed_execution": metrics_match and all(execution_matches.values()),
        "expected_metrics": expected_metrics,
        "observed_metrics": observed_metrics,
        "expected_execution": expected_execution,
        "observed_execution": observed_execution,
        "analysis_verification": {
            "status": "not_recomputed",
            "reason": "analysis/risk 是主执行结果的派生分析，本回放仅重算执行层并逐项比较。",
        },
        "result": observed_execution["result"],
        "control": observed_execution["random_control_events"],
        "phases": phases,
    }
    receipt = cards.write_artifact(
        run_id,
        "replay-comparison.json",
        comparison,
        artifact_type="replay_comparison",
        metadata={
            "source_manifest_sha256": source_manifest_sha256,
            "source_frozen_input_sha256": entry.sha256,
            "source_signed_manifest_sha256": comparison["source_signed_manifest_sha256"],
        },
    )
    return {"comparison": comparison, "receipt": receipt.to_dict()}


def _read_verified_artifact(
    cards: ResearchRunCardStore, card: Any, path: str
) -> tuple[Any, bytes]:
    entry = next((item for item in card.artifact_manifest if item.path == path), None)
    if entry is None:
        label = "冻结输入" if path == "frozen_input.json" else path
        raise ResearchReplayError(f"旧 run 没有{label} artifact，拒绝重放")
    root = Path(cards.root).resolve()
    target = (root / card.run_id / entry.path).resolve()
    if root not in target.parents or not target.is_file():
        raise ResearchReplayError(f"{path} artifact 文件不存在")
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry.sha256:
        raise ResearchReplayError(f"{path} artifact manifest hash 校验失败")
    return entry, raw


def _review_manifest_sha256(cards: ResearchRunCardStore, card: Any) -> str | None:
    """读取终态回放可绑定的人工签署 manifest；非终态 run 没有该字段。"""
    review = next((item for item in card.artifact_manifest if item.path == "human-review.json"), None)
    if review is None:
        return None
    _, raw = _read_verified_artifact(cards, card, "human-review.json")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchReplayError("人工签署 artifact 不是有效 JSON") from exc
    digest = payload.get("manifest_sha256") if isinstance(payload, dict) else None
    if not isinstance(digest, str) or len(digest) != 64:
        raise ResearchReplayError("人工签署 artifact 缺少 manifest hash")
    return digest.lower()


__all__ = ["ResearchReplayError", "replay_research_backtest"]
