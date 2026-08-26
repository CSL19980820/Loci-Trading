"""喂模历史 auto-compact：超阈值才压；近轮保留；失败确定性回退。"""
from __future__ import annotations

from src.ai.application.context_compact import (
    COMPACT_NOTICE,
    compact_feed_messages,
    compact_threshold_tokens,
    estimate_messages_tokens,
)
from src.ai.infrastructure.client import ChatMessage


def _turns(n: int, *, body: str = "短句") -> list[ChatMessage]:
    rows: list[ChatMessage] = []
    for i in range(n):
        rows.append(ChatMessage(role="user", content=f"用户问{i}：{body}"))
        rows.append(ChatMessage(role="assistant", content=f"助手答{i}：{body}"))
    return rows


def test_below_threshold_does_not_compact() -> None:
    messages = _turns(3, body="你好")
    result = compact_feed_messages(
        messages,
        context_window=128_000,
        reserve_tokens=2_000,
        threshold_ratio=0.70,
        keep_turns=6,
    )
    assert result.compacted is False
    assert result.method == "none"
    assert result.messages is not messages or result.messages == messages
    assert result.tokens_after == result.tokens_before
    assert all(COMPACT_NOTICE not in (m.content or "") for m in result.messages)


def test_above_threshold_reduces_tokens_and_keeps_recent_turns() -> None:
    # 足够长的正文把会话段推过小窗口阈值
    fat = "持仓复盘结论。" * 400
    messages = _turns(10, body=fat)
    before = estimate_messages_tokens(messages)
    threshold = compact_threshold_tokens(context_window=8_000, reserve_tokens=500, threshold_ratio=0.70)
    assert before >= threshold

    result = compact_feed_messages(
        messages,
        context_window=8_000,
        reserve_tokens=500,
        threshold_ratio=0.70,
        keep_turns=6,
        summarizer=None,  # 走确定性回退
    )
    assert result.compacted is True
    assert result.tokens_after < result.tokens_before
    assert result.method == "deterministic"
    assert result.kept_turns == 6
    # 最近一轮原文仍在
    assert result.messages[-1].content == messages[-1].content
    assert result.messages[-2].content == messages[-2].content
    assert COMPACT_NOTICE in result.messages[0].content
    assert "用户问0" not in "".join(m.content for m in result.messages[1:])


def test_summarizer_failure_falls_back_deterministically() -> None:
    fat = "证据链条。" * 500
    messages = _turns(8, body=fat)

    def boom(_transcript: str) -> str:
        raise RuntimeError("llm down")

    result = compact_feed_messages(
        messages,
        context_window=6_000,
        reserve_tokens=200,
        keep_turns=6,
        summarizer=boom,
    )
    assert result.compacted is True
    assert result.method == "deterministic"
    assert result.summary.strip()
    assert result.tokens_after < result.tokens_before


def test_reverse_within_threshold_must_not_compact() -> None:
    """反向：阈值内输入被误压应失败（本断言即红线）。"""
    messages = _turns(4, body="轻量")
    result = compact_feed_messages(
        messages,
        context_window=128_000,
        reserve_tokens=1_000,
        threshold_ratio=0.70,
    )
    assert result.compacted is False
    assert all(COMPACT_NOTICE not in (m.content or "") for m in result.messages)


def test_force_compacts_below_threshold() -> None:
    """手动 /compact：force=True 无视阈值；有实质节省才 compacted。"""
    fat = "持仓复盘结论。" * 40
    messages = _turns(8, body=fat)
    auto = compact_feed_messages(
        messages,
        context_window=128_000,
        reserve_tokens=1_000,
        threshold_ratio=0.70,
        keep_turns=6,
    )
    assert auto.compacted is False

    forced = compact_feed_messages(
        messages,
        context_window=128_000,
        reserve_tokens=1_000,
        threshold_ratio=0.70,
        keep_turns=6,
        force=True,
    )
    assert forced.compacted is True
    assert forced.tokens_after < forced.tokens_before
    assert COMPACT_NOTICE in forced.messages[0].content
    assert forced.messages[-1].content == messages[-1].content


def test_force_short_dialog_without_savings_is_noop() -> None:
    """极短正文强制压无节省 → compacted=False，避免喂模变大。"""
    messages = _turns(8, body="短句")
    forced = compact_feed_messages(
        messages,
        context_window=128_000,
        keep_turns=6,
        force=True,
    )
    assert forced.compacted is False
    assert forced.method == "none"
    assert forced.messages == messages
