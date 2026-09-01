"""任务侧 LLM 调用必须计费。

已知缺口：``ai_usage_daily`` 原来只覆盖助手会话。盯盘、复盘、选股、战法监测
摘要、技能任务这五条路径都拿到了 token 数，却一次都没写进用量表——月度配额
因此系统性低估，用户在「还剩很多」的读数下把钱烧完。

这组用例逐条盯这五个调用点：**钱花了就必须留下账**，哪怕这一轮业务失败。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.ai import ChatMessage, chat_text_with_thinking_fallback
from src.ai.infrastructure.assistant_store import AssistantStore
from src.ai.infrastructure.client import ProviderConfig
from src.shared.paths import ops_db


def _cfg() -> ProviderConfig:
    return ProviderConfig(
        name="t",
        protocol="openai_compatible",
        base_url="http://localhost",
        api_key="x",
        model="m",
    )


def _usage() -> tuple[int, int]:
    """(本月 token 总数, 今日调用次数)。"""
    with AssistantStore(str(ops_db())) as store:
        row = store.conn.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS tok,"
            " COALESCE(SUM(calls), 0) AS calls FROM ai_usage_daily"
        ).fetchone()
        return int(row["tok"]), int(row["calls"])


def _response(text: str, *, tin: int = 10, tout: int = 4) -> SimpleNamespace:
    return SimpleNamespace(
        text=text, model="m", input_tokens=tin, output_tokens=tout, raw={}, tool_calls=[]
    )


def test_thinking_fallback_bills_every_attempt() -> None:
    """降级重试是真的调了两次模型，只记最后一次就等于白送一次。"""
    replies = [_response(""), _response("ok")]

    with patch(
        "src.ai.infrastructure.chat_retry.chat", side_effect=lambda *a, **k: replies.pop(0)
    ):
        text = chat_text_with_thinking_fallback(
            _cfg(), [ChatMessage(role="user", content="hi")], thinking="medium"
        )

    assert text == "ok"
    assert _usage() == (28, 2)


def test_screen_ai_pick_bills_even_when_the_answer_is_unparseable() -> None:
    from src.ops.application.jobs import JobContext
    from src.ops.application.jobs.screen import _ai_pick_codes
    from src.ops.infrastructure.store import OpsStore

    candidates = [{"code": "600000", "factors": {}}, {"code": "600001", "factors": {}}]
    with OpsStore() as store:
        context = JobContext(ops_store=store)
        with patch("src.ai.resolve_config", return_value=_cfg()), patch(
            "src.ai.chat", return_value=_response("这不是 JSON")
        ):
            out = _ai_pick_codes(
                candidates,
                top_n=1,
                strategy_slug="demo",
                provider_name="t",
                context=context,
            )

    assert out["fallback"] is True  # 业务上回退了
    assert _usage() == (14, 1)  # 但账照记：钱已经花了


def test_skill_watch_summary_is_billed() -> None:
    from src.ops.application.skill_watch.runner import _ai_summary

    with patch("src.ai.resolve_config", return_value=_cfg()), patch(
        "src.ai.chat", return_value=_response("三行摘要")
    ):
        text = _ai_summary(
            store=object(),
            skill={"slug": "demo", "name": "示例战法"},
            config={"provider": "t"},
            signals=[{"type": "x", "code": "600000", "title": "命中"}],
        )

    assert text == "三行摘要"
    assert _usage() == (14, 1)


def test_skill_job_bills_the_whole_agent_chain(tmp_path: Path) -> None:
    """``run_agent`` 把多轮工具链的 token 加总在 result 上，整条要一次记清。"""
    from src.ops.application.jobs import JobContext
    from src.ops.application.jobs import skill as skill_job
    from src.ops.infrastructure.store import OpsStore

    outcome = SimpleNamespace(
        messages=[],
        invocations=[],
        input_tokens=120,
        output_tokens=30,
        model="m",
        rounds=3,
        stopped_reason="completed",
        pending_ask={},
        to_dict=lambda: {"text": "done"},
    )
    skill = {
        "slug": "demo",
        "name": "示例",
        "version": "1",
        "instructions": "做事",
        "policy": "",
        "enabled": True,
    }

    with OpsStore() as store:
        with patch("src.ops.application.skills.resolve_skill", return_value=skill), patch(
            "src.ai.resolve_config", return_value=_cfg()
        ), patch(
            "src.ai.application.agent.run_agent", return_value=outcome
        ), patch.object(
            skill_job, "_gather_context", return_value={}
        ), patch.object(
            skill_job, "_resolve_tools", return_value=(None, None)
        ):
            payload = skill_job.execute_skill(
                {"skill": "demo", "provider": "t"}, JobContext(ops_store=store)
            )

    assert payload["skill"] == "demo"
    assert _usage() == (150, 1)


def test_billing_writes_into_the_tenant_that_ran_the_job() -> None:
    """任务侧传的是自己那条库路径：别把 A 的用量记到 B 头上。"""
    from src.shared.tenancy import tenant_scope

    with tenant_scope("u_job"):
        tenant_db = str(ops_db())
        with patch(
            "src.ai.infrastructure.chat_retry.chat", return_value=_response("ok")
        ):
            chat_text_with_thinking_fallback(
                _cfg(), [ChatMessage(role="user", content="hi")], ops_db=tenant_db
            )
        with AssistantStore(tenant_db) as store:
            assert store.monthly_token_usage() == 14

    # 主租户那边一分钱都不该多出来
    assert _usage() == (0, 0)
