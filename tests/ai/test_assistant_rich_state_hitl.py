from __future__ import annotations

from src.ai.application.assistant_rich_state import fold_run_rich_metadata, public_rich_fields


def test_fold_waiting_user_into_hitl() -> None:
    folded = fold_run_rich_metadata(
        [
            {"event_type": "waiting_user", "payload": {"ask": {"prompt": "选路径？", "options": ["A", "B"], "risk": "写库"}}},
        ]
    )
    assert folded["hitl"] == {"prompt": "选路径？", "options": ["A", "B"], "risk": "写库"}
    public = public_rich_fields(folded)
    assert public["hitl"]["options"] == ["A", "B"]


def test_events_after_latest_resume_drops_pre_pause_hitl() -> None:
    from src.ai.application.assistant_rich_state import events_after_latest_resume

    events = [
        {"event_type": "tool_end", "payload": {"name": "qianlong_candidate_pool", "ok": True}},
        {"event_type": "waiting_user", "payload": {"ask": {"prompt": "旧问？", "options": ["是"]}}},
        {"event_type": "resume", "payload": {"reply": "是"}},
        {"event_type": "token", "payload": {"delta": "续写"}},
    ]
    sliced = events_after_latest_resume(events)
    folded = fold_run_rich_metadata(sliced)
    assert "hitl" not in folded
    assert "tool_receipts" not in folded


def test_fold_waiting_user_multi_questions() -> None:
    folded = fold_run_rich_metadata(
        [
            {
                "event_type": "waiting_user",
                "payload": {
                    "ask": {
                        "prompt": "请回答",
                        "questions": [
                            {"id": "q1", "prompt": "选路径？", "options": ["A", "B"]},
                            {"id": "q2", "prompt": "备注？", "allow_free_text": True},
                        ],
                    }
                },
            },
        ]
    )
    assert folded["hitl"]["questions"][0]["id"] == "q1"
    assert folded["hitl"]["questions"][1]["allow_free_text"] is True
    public = public_rich_fields(folded)
    assert public["hitl"]["questions"][1]["prompt"] == "备注？"


def test_fold_ignores_legacy_tool_awaiting_confirmation() -> None:
    folded = fold_run_rich_metadata(
        [
            {
                "event_type": "tool_awaiting_confirmation",
                "payload": {
                    "call_id": "pending-1",
                    "name": "ledger_write",
                    "summary": "确认写入？",
                },
            },
        ]
    )
    assert "tool_receipts" not in folded
    assert "hitl" not in folded
    blob = str(folded)
    assert "awaiting_confirmation" not in blob


def test_fold_keeps_subagent_tool_receipts_through_end() -> None:
    """嵌套工具回执不得被 subagent_end 冲掉。"""
    folded = fold_run_rich_metadata(
        [
            {
                "event_type": "subagent_start",
                "payload": {"id": "ledger", "name": "账本核对", "progress": 5},
            },
            {
                "event_type": "subagent_tool",
                "payload": {
                    "id": "ledger",
                    "call_id": "c1",
                    "tool_name": "qianlong_candidate_pool",
                    "status": "running",
                },
            },
            {
                "event_type": "subagent_tool",
                "payload": {
                    "id": "ledger",
                    "call_id": "c1",
                    "tool_name": "qianlong_candidate_pool",
                    "status": "done",
                    "preview": "3 持仓",
                },
            },
            {
                "event_type": "subagent_end",
                "payload": {"id": "ledger", "ok": True, "detail": "完成"},
            },
        ]
    )
    agents = folded["agents"]
    assert len(agents) == 1
    assert agents[0]["status"] == "done"
    assert agents[0]["tool_receipts"] == [
        {
            "call_id": "c1",
            "name": "qianlong_candidate_pool",
            "status": "done",
            "preview": "3 持仓",
        }
    ]
