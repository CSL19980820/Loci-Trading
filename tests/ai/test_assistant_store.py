from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.assistant_store import AssistantStore


def test_session_run_events_usage_and_redaction(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session(title="secret sk-abcdefghijkl")
        store.append_message(session_id, role="user", content="Bearer abcdefghijklmnop https://private.example")
        run_id = store.create_run(session_id, provider="p", model="m", user_message="记录 BUY 600000")
        event = store.append_event(run_id, "tool_start", {"api_key": "sk-abcdefghijkl", "url": "https://private.example"})
        store.finish_run(run_id, status="completed", input_tokens=3, output_tokens=5)
        store.record_usage(provider="p", model="m", input_tokens=3, output_tokens=5)

        assert store.get_session(session_id)["status"] == "idle"
        assert "[REDACTED]" in store.list_messages(session_id)[0]["content"]
        assert event["payload"]["api_key"] == "[REDACTED]"
        assert event["payload"]["url"] == "[URL]"
        assert store.get_run(run_id)["input_tokens"] == 3


def test_session_last_error_is_redacted_with_the_run_error(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
        run_id = store.create_run(session_id, user_message="测试")
        store.finish_run(
            run_id,
            status="failed",
            error="Bearer abcdefghijklmnop https://private.example/fail",
        )

        session = store.get_session(session_id)
        assert session is not None
        assert "[REDACTED]" in session["last_error"]
        assert "[URL]" in session["last_error"]


def test_grant_is_bound_single_use_and_rejects_parameter_substitution(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
        message = "请明确记录 BUY 600000 100 股 10 元"
        run_id = store.create_run(session_id, user_message=message)
        params = {"action": "BUY", "code": "600000", "shares": 100, "price": 10.0}
        grant = store.issue_grant(session_id=session_id, run_id=run_id, user_message=message, action="ledger.record_trade", target="600000", parameters=params)

        with pytest.raises(AssistantError, match="不匹配"):
            store.consume_grant(grant_id=grant["id"], session_id=session_id, run_id=run_id, user_message=message, action="ledger.record_trade", target="600000", parameters={**params, "price": 11.0})

        assert store.consume_grant(grant_id=grant["id"], session_id=session_id, run_id=run_id, user_message=message, action="ledger.record_trade", target="600000", parameters=params)
        with pytest.raises(AssistantError, match="已使用"):
            store.consume_grant(grant_id=grant["id"], session_id=session_id, run_id=run_id, user_message=message, action="ledger.record_trade", target="600000", parameters=params)
        with pytest.raises(AssistantError, match="拒绝重复"):
            store.issue_grant(session_id=session_id, run_id=run_id, user_message=message, action="ledger.record_trade", target="600000", parameters=params)


def test_grant_failure_and_archived_session_preserve_auditable_terminal_state(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
        message = "记录一笔成交"
        run_id = store.create_run(session_id, user_message=message)
        params = {"action": "BUY", "code": "600000"}
        grant = store.issue_grant(
            session_id=session_id, run_id=run_id, user_message=message,
            action="ledger.record_trade", target="600000", parameters=params,
        )
        store.consume_grant(
            grant_id=grant["id"], session_id=session_id, run_id=run_id,
            user_message=message, action="ledger.record_trade", target="600000", parameters=params,
        )
        store.complete_grant(grant["id"], {"error": "api_key sk-secret"}, status="failed")
        store.finish_run(run_id, status="failed")
        assert store.delete_session(session_id)

        grant_row = store.conn.execute(
            "SELECT status, result_json FROM ai_execution_grants WHERE id = ?", (grant["id"],)
        ).fetchone()
        assert grant_row is not None
        assert grant_row["status"] == "failed"
        assert "sk-secret" not in grant_row["result_json"]
        assert store.get_session(session_id)["status"] == "archived"
        assert store.list_sessions() == []


def test_cancelled_run_cannot_consume_an_already_issued_grant(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
        message = "请明确记录 BUY 600000 100 股 10 元"
        run_id = store.create_run(session_id, user_message=message)
        params = {"action": "BUY", "code": "600000", "shares": 100, "price": 10.0}
        grant = store.issue_grant(session_id=session_id, run_id=run_id, user_message=message, action="ledger.record_trade", target="600000", parameters=params)
        assert store.cancel_run(run_id)
        with pytest.raises(AssistantError, match="不匹配"):
            store.consume_grant(grant_id=grant["id"], session_id=session_id, run_id=run_id, user_message=message, action="ledger.record_trade", target="600000", parameters=params)


def test_running_session_cannot_be_archived_or_deleted(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
        run_id = store.create_run(session_id, user_message="测试")

        with pytest.raises(AssistantError, match="仍在运行"):
            store.archive_session(session_id)
        with pytest.raises(AssistantError, match="仍在运行"):
            store.delete_session(session_id)
        assert store.get_session(session_id) is not None
        assert store.get_run(run_id) is not None

        store.finish_run(run_id, status="cancelled")
        assert store.archive_session(session_id)["status"] == "archived"
        assert store.delete_session(session_id)


def test_waiting_user_session_cannot_be_archived_or_deleted(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
        run_id = store.create_run(session_id, user_message="请确认")
        store.pause_run_waiting_user(run_id, ask={"prompt": "是否继续？"})

        with pytest.raises(AssistantError, match="等待用户"):
            store.archive_session(session_id)
        with pytest.raises(AssistantError, match="等待用户"):
            store.delete_session(session_id)
        assert store.get_session(session_id)["status"] == "waiting_user"
        assert store.get_active_run(session_id)["id"] == run_id

        assert store.cancel_run(run_id)
        assert store.archive_session(session_id)["status"] == "archived"


def test_get_active_run_prefers_running_and_returns_waiting_user(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        session_id = store.create_session()
        assert store.get_active_run(session_id) is None

        waiting_id = store.create_run(session_id, user_message="先确认")
        store.pause_run_waiting_user(waiting_id, ask={"prompt": "继续？"})
        assert store.get_active_run(session_id)["id"] == waiting_id
        assert store.get_active_run(session_id)["status"] == "waiting_user"

        # store 在 waiting_user 时允许再开 run（manager 会先 resolve）；此处并存以验证优先 running。
        running_id = store.create_run(session_id, user_message="新一轮")
        assert store.get_active_run(session_id)["id"] == running_id
        assert store.get_active_run(session_id)["status"] == "running"

        store.finish_run(running_id, status="completed")
        assert store.get_active_run(session_id)["id"] == waiting_id
        store.resolve_waiting_session(session_id)
        assert store.get_active_run(session_id) is None


def test_monthly_token_usage_excludes_previous_month(tmp_path: Path) -> None:
    with AssistantStore(tmp_path / "ops.db") as store:
        store.record_usage(provider="p", model="m", input_tokens=3, output_tokens=5)
        previous_day = (date.today().replace(day=1) - timedelta(days=1)).isoformat()
        store.conn.execute(
            "INSERT INTO ai_usage_daily(day,provider,model,input_tokens,output_tokens,calls) VALUES(?,?,?,?,?,?)",
            (previous_day, "p", "m", 100, 200, 1),
        )
        store.conn.commit()

        assert store.monthly_token_usage() == 8
