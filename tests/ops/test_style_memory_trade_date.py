"""P1-5：风格记忆只按 started_at ∈ trade_date 计 stance。"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.ai import ProviderConfig
from src.ops.application.paper_style_memory import extract_lessons_from_day, run_eod_learning
from src.ops.infrastructure.store import OpsStore


def test_style_memory_ignores_cross_day_stances() -> None:
    lessons = extract_lessons_from_day(
        slug="demo",
        trade_date="2026-08-07",
        fills=[],
        rejects=[],
        monitor_runs=[
            {
                # 跨日：started_at 不是当日，即使 snapshot 有多条 revise 也不应计入
                "started_at": "2026-08-06T09:20:00+08:00",
                "snapshot": {
                    "auction_stances": [
                        {"stance": "revise", "code": "600001"},
                        {"stance": "revise", "code": "600002"},
                        {"stance": "revise", "code": "600003"},
                    ]
                },
            },
            {
                "started_at": "2026-08-07T10:00:00+08:00",
                "snapshot": {
                    "auction_stances": [
                        {"stance": "follow", "code": "600519"},
                    ]
                },
            },
        ],
    )
    assert not any(x.get("kind") == "revise" for x in lessons)


def test_eod_learning_honors_paper_llm_timeout(tmp_path: Path) -> None:
    """盘后记忆学习与盘中盯盘共用 30 分钟慢推理预算。"""
    captured: list[float] = []

    def fake_resolve(*_args: Any, timeout: float | None = None, **_kwargs: Any) -> ProviderConfig:
        return ProviderConfig(
            name="slow",
            protocol="openai_compatible",
            base_url="https://example.test",
            api_key="test-key",
            model="slow-model",
            timeout=float(timeout or 120.0),
        )

    def fake_chat(config: ProviderConfig, *_args: Any, **_kwargs: Any) -> str:
        captured.append(float(config.timeout))
        return "复盘完成"

    with OpsStore(tmp_path / "ops.db") as store:
        with (
            patch("src.ai.resolve_config", side_effect=fake_resolve),
            patch("src.ai.chat_text_with_thinking_fallback", side_effect=fake_chat),
        ):
            result = run_eod_learning(
                store,
                slug="dragon-return",
                trade_date="2026-08-10",
                positions=[],
                fills_today=[],
                model="slow-model",
                persist_memory=True,
                llm_timeout_sec=1800,
            )

    assert result["persist_memory"] is True
    assert captured == [1800.0]
