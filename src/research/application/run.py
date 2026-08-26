"""研究 run：阶段产物、复用、resume 和 stale 语义。"""
from __future__ import annotations

from typing import Any

from src.research.application.profile import (
    build_research_profile_from_snapshot,
)
from src.research.application.snapshot import (
    Budget,
    capture_research_input,
)
from src.research.domain.contract import ResearchInputSnapshot
from src.research.infrastructure import ResearchArtifactStore


class ResearchRunError(ValueError):
    """研究 run 不存在或阶段产物不可恢复。"""


def _mark_stage(
    state: dict[str, Any],
    stage: str,
    digest: str,
    dependencies: list[str],
) -> None:
    stages = state.setdefault("stages", {})
    stages[stage] = {
        "status": "completed",
        "output_sha256": digest,
        "depends_on": dependencies,
    }


def _current_revision(store: Any) -> str:
    return str(store.market_revision() or "")


def _response(
    state: dict[str, Any],
    profile: dict[str, Any],
    *,
    reused: bool = False,
    stale: bool = False,
) -> dict[str, Any]:
    output_state = dict(state)
    output_state["reused"] = reused
    output_state["stale"] = stale
    if stale:
        profile = {**profile, "artifact_status": "stale"}
    return {"run": output_state, "profile": profile}


def _complete_from_snapshot(
    state: dict[str, Any],
    snapshot: ResearchInputSnapshot,
    artifacts: ResearchArtifactStore,
    *,
    stale: bool,
    only_missing: bool = False,
) -> dict[str, Any]:
    run_id = str(state["id"])
    input_payload = snapshot.to_dict()
    if not only_missing or artifacts.load_stage(run_id, "input") is None:
        digest = artifacts.write_stage(run_id, "input", input_payload)
        _mark_stage(state, "input", digest, [])
    state.update(
        {
            "input_sha256": snapshot.input_sha256,
            "market_revision": snapshot.market_revision,
            "as_of": snapshot.as_of,
            "source_attempts": [item.to_dict() for item in snapshot.source_attempts],
        }
    )

    profile_raw = artifacts.load_stage(run_id, "profile")
    profile_rebuilt = not only_missing or profile_raw is None
    if profile_rebuilt:
        profile = build_research_profile_from_snapshot(
            snapshot,
            artifact_id=run_id,
            artifact_status="stale" if stale else "archived",
        )
        profile_raw = profile.to_dict()
        digest = artifacts.write_stage(run_id, "profile", profile_raw)
        _mark_stage(state, "profile", digest, ["input"])

    review_raw = artifacts.load_stage(run_id, "review")
    if not only_missing or profile_rebuilt or review_raw is None:
        review_raw = {
            "contract_version": "research-review-v2",
            "quality": profile_raw.get("quality", {}),
            "source_attempts": profile_raw.get("source_attempts", []),
        }
        digest = artifacts.write_stage(run_id, "review", review_raw)
        _mark_stage(state, "review", digest, ["input", "profile"])

    state["status"] = "stale" if stale else "completed"
    state["error"] = ""
    artifacts.save_run(state)
    return _response(state, profile_raw, stale=stale)


def create_research_run(
    store: Any,
    code: str,
    *,
    budget: Budget = "standard",
    as_of: str | None = None,
    artifact_store: ResearchArtifactStore | None = None,
) -> dict[str, Any]:
    """创建或复用一个带输入快照的研究 run。"""
    artifacts = artifact_store or ResearchArtifactStore()
    snapshot = capture_research_input(store, code, budget=budget, as_of=as_of)
    existing = artifacts.find_by_input_hash(snapshot.input_sha256)
    if (
        existing
        and existing.get("status") in {"completed", "stale"}
        and artifacts.load_stage(str(existing.get("id") or ""), "profile")
        and artifacts.load_stage(str(existing.get("id") or ""), "review")
    ):
        profile = artifacts.load_stage(str(existing["id"]), "profile")
        if profile is not None:
            stale = existing.get("status") == "stale"
            return _response(existing, profile, reused=True, stale=stale)

    state = artifacts.create_run(
        code=snapshot.code,
        budget=snapshot.budget,
        requested_as_of=snapshot.requested_as_of,
    )
    try:
        return _complete_from_snapshot(state, snapshot, artifacts, stale=False)
    except Exception as exc:
        state["status"] = "error"
        state["error"] = f"{type(exc).__name__}: {exc}"
        artifacts.save_run(state)
        raise ResearchRunError(state["error"]) from exc


def resume_research_run(
    store: Any,
    run_id: str,
    *,
    artifact_store: ResearchArtifactStore | None = None,
) -> dict[str, Any]:
    """从输入阶段恢复；已完成阶段不重写，行情版本变化只标 stale。"""
    artifacts = artifact_store or ResearchArtifactStore()
    state = artifacts.load_run(run_id)
    if state is None:
        raise ResearchRunError(f"找不到研究 run：{run_id}")
    raw_input = artifacts.load_stage(run_id, "input")
    if raw_input is None:
        raise ResearchRunError(f"研究 run 缺少 input 阶段：{run_id}")
    snapshot = ResearchInputSnapshot.from_dict(raw_input)
    stale = bool(snapshot.market_revision) and _current_revision(store) != snapshot.market_revision
    profile = artifacts.load_stage(run_id, "profile")
    review = artifacts.load_stage(run_id, "review")
    if profile is not None and review is not None:
        state["status"] = "stale" if stale else "completed"
        artifacts.save_run(state)
        return _response(state, profile, stale=stale)
    return _complete_from_snapshot(
        state,
        snapshot,
        artifacts,
        stale=stale,
        only_missing=True,
    )


def read_research_run(
    store: Any,
    run_id: str,
    *,
    artifact_store: ResearchArtifactStore | None = None,
) -> dict[str, Any]:
    """读取 run，不因 GET 缺失阶段而重新计算。"""
    artifacts = artifact_store or ResearchArtifactStore()
    state = artifacts.load_run(run_id)
    if state is None:
        raise ResearchRunError(f"找不到研究 run：{run_id}")
    profile = artifacts.load_stage(run_id, "profile")
    if profile is None:
        raise ResearchRunError(f"研究 run 缺少 profile 阶段：{run_id}")
    stale = bool(state.get("market_revision")) and _current_revision(store) != state.get("market_revision")
    return _response(state, profile, stale=stale)
