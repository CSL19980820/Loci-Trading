"""研究 run 的状态迁移与输入不可覆盖。

README 把「发布/否决状态机」列为补测第二优先级。这里守的是两条不能绕的规则：

1. **人工签署不可跳过**：`running` 不能直接变 `completed`，必须先进
   `awaiting_human_review`。绕过它就等于研究结论无人签字即生效。
2. **同一 run_id 的计算输入不可覆盖**：`input_sha256` 变了就必须是新 run，
   否则「这份结论是在哪份输入上算的」这个追溯字段就失效了。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.research.domain.run_card import ResearchRunCard
from src.research.infrastructure import (
    ResearchRunCardStore,
    RunCardError,
    RunCardImmutableError,
)


def _store(tmp_path: Path) -> ResearchRunCardStore:
    return ResearchRunCardStore(tmp_path / "research_runs")


def _card(status: str = "running", *, run_id: str = "rc-state-0001") -> ResearchRunCard:
    return ResearchRunCard(run_id=run_id, status=status)  # type: ignore[arg-type]


class TestHumanSignOffCannotBeSkipped:
    def test_running_cannot_jump_straight_to_completed(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        saved = store.save(_card("running"))
        with pytest.raises(RunCardError):
            store.save(saved.with_status("completed"))

    def test_the_legal_path_goes_through_human_review(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        card = store.save(_card("running"))
        card = store.save(card.with_status("awaiting_human_review"))
        card = store.save(card.with_status("completed"))
        assert card.status == "completed"

    def test_a_rejected_run_cannot_be_revived(self, tmp_path: Path) -> None:
        """否决是审计结论，不允许改口翻案。"""
        store = _store(tmp_path)
        card = store.save(_card("running"))
        card = store.save(card.with_status("rejected"))
        for target in ("completed", "awaiting_human_review", "running"):
            with pytest.raises(RunCardError):
                store.save(card.with_status(target))  # type: ignore[arg-type]

    def test_completed_only_degrades_to_stale(self, tmp_path: Path) -> None:
        """行情版本变了只能标 stale，不能退回运行中重算成另一个结论。"""
        store = _store(tmp_path)
        card = store.save(_card("running"))
        card = store.save(card.with_status("awaiting_human_review"))
        card = store.save(card.with_status("completed"))
        assert store.save(card.with_status("stale")).status == "stale"

        fresh = store.save(_card("running", run_id="rc-state-0002"))
        fresh = store.save(fresh.with_status("awaiting_human_review"))
        fresh = store.save(fresh.with_status("completed"))
        with pytest.raises(RunCardError):
            store.save(fresh.with_status("running"))

    def test_saving_the_same_status_twice_is_idempotent(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        card = store.save(_card("running"))
        assert store.save(card.with_status("running")).status == "running"


class TestInputIsImmutable:
    """输入指纹有两道锁，缺哪一道「结论算在哪份输入上」都会失真。"""

    def test_the_hash_cannot_be_hand_set_to_disagree_with_the_inputs(self) -> None:
        """领域层：input_sha256 由输入算出，填一个对不上的值直接拒收。"""
        with pytest.raises(ValueError):
            ResearchRunCard(run_id="rc-state-0101", input_sha256="b" * 64)

    def test_same_run_id_with_different_inputs_is_refused(self, tmp_path: Path) -> None:
        """存储层：换了参数就必须是新 run，不能借同一个 run_id 改写输入。"""
        store = _store(tmp_path)
        card = store.save(
            ResearchRunCard(run_id="rc-state-0102", params={"hold_days": 3})
        )
        rerun = ResearchRunCard(run_id="rc-state-0102", params={"hold_days": 5})
        assert rerun.input_sha256 != card.input_sha256
        with pytest.raises(RunCardImmutableError):
            store.save(rerun)
