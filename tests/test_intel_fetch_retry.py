from contextlib import nullcontext

import src.intel as intel
from src.ops.application.jobs import intel_fetch


class _Context:
    @staticmethod
    def market():
        return nullcontext(object())


def _payload(text: str, *, is_error: bool) -> dict:
    return {
        "text": text,
        "is_error": is_error,
        "cached": False,
        "structured": None,
    }


def test_retryable_provider_error_retries_without_negative_cache(monkeypatch):
    responses = iter(
        [
            _payload(
                "wudao 返回 MCP 协议错误（-32052）：指数落盘数据暂未更新完成，请稍后重试；可重试",
                is_error=True,
            ),
            _payload('{"ok": true}', is_error=False),
        ]
    )
    cache_flags: list[bool] = []
    delays: list[float] = []

    def fake_call(*args, **kwargs):
        cache_flags.append(bool(kwargs["cache"]))
        return next(responses)

    monkeypatch.setattr(intel, "call_mcp_tool", fake_call)
    monkeypatch.setattr(intel_fetch.time, "sleep", delays.append)

    receipts, prior, stats = intel_fetch._run_call_list(
        [{"tool": "index_market", "arguments": {}, "cache": True}],
        server="wudao",
        context=_Context(),
        cache_max_age_minutes=20,
    )

    assert stats == {"ok": 1, "failed": 0, "cached": 0, "quota_skipped": 0}
    assert receipts == [
        {
            "tool": "index_market",
            "ok": True,
            "cached": False,
            "attempts": 2,
            "error": "",
        }
    ]
    assert cache_flags == [True, False]
    assert delays == [2.0]
    assert "index_market" in prior


def test_retryable_exception_retries_without_cache(monkeypatch):
    cache_flags: list[bool] = []
    delays: list[float] = []
    calls = 0

    def fake_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        cache_flags.append(bool(kwargs["cache"]))
        if calls == 1:
            raise RuntimeError("-32052 指数落盘数据暂未更新完成")
        return _payload('{"ok": true}', is_error=False)

    monkeypatch.setattr(intel, "call_mcp_tool", fake_call)
    monkeypatch.setattr(intel_fetch.time, "sleep", delays.append)

    receipts, prior, stats = intel_fetch._run_call_list(
        [{"tool": "index_market", "arguments": {}, "cache": True}],
        server="wudao",
        context=_Context(),
        cache_max_age_minutes=20,
    )

    assert stats == {"ok": 1, "failed": 0, "cached": 0, "quota_skipped": 0}
    assert receipts[0]["attempts"] == 2
    assert cache_flags == [True, False]
    assert delays == [2.0]
    assert "index_market" in prior


def test_retryable_failure_gets_tail_retry_after_full_recipe(monkeypatch):
    responses = iter(
        [
            _payload("-32052 指数落盘数据暂未更新完成", is_error=True),
            _payload("-32052 指数落盘数据暂未更新完成", is_error=True),
            _payload("-32052 指数落盘数据暂未更新完成", is_error=True),
            _payload('{"ok": true}', is_error=False),
            _payload('{"ok": true}', is_error=False),
        ]
    )
    delays: list[float] = []
    order: list[str] = []

    def fake_call(tool, *args, **kwargs):
        order.append(tool)
        return next(responses)

    monkeypatch.setattr(intel, "call_mcp_tool", fake_call)
    monkeypatch.setattr(intel_fetch.time, "sleep", delays.append)

    receipts, prior, stats = intel_fetch._run_call_list(
        [
            {"tool": "index_market", "arguments": {}, "cache": True},
            {"tool": "news_hotlist", "arguments": {}, "cache": True},
        ],
        server="wudao",
        context=_Context(),
        cache_max_age_minutes=20,
    )

    assert stats == {"ok": 2, "failed": 0, "cached": 0, "quota_skipped": 0}
    assert receipts[0]["ok"] is True
    assert receipts[0]["attempts"] == 4
    assert delays == [2.0, 5.0]
    assert order == ["index_market", "index_market", "index_market", "news_hotlist", "index_market"]
    assert {"index_market", "news_hotlist"} <= prior.keys()


def test_non_retryable_provider_error_is_not_repeated(monkeypatch):
    calls = 0

    def fake_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _payload("invalid arguments", is_error=True)

    monkeypatch.setattr(intel, "call_mcp_tool", fake_call)
    monkeypatch.setattr(intel_fetch.time, "sleep", lambda _delay: None)

    receipts, prior, stats = intel_fetch._run_call_list(
        [{"tool": "stock_screener", "arguments": {}, "cache": True}],
        server="wudao",
        context=_Context(),
        cache_max_age_minutes=20,
    )

    assert calls == 1
    assert not prior
    assert stats["failed"] == 1
    assert receipts[0]["attempts"] == 1


def test_persistent_rate_limit_stops_after_bounded_retries(monkeypatch):
    calls = 0
    delays: list[float] = []

    def fake_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _payload(
            "Rate limit exceeded. Max 50 requests/minute；建议等待 1000 毫秒",
            is_error=True,
        )

    monkeypatch.setattr(intel, "call_mcp_tool", fake_call)
    monkeypatch.setattr(intel_fetch.time, "sleep", delays.append)

    receipts, _prior, stats = intel_fetch._run_call_list(
        [{"tool": "theme_stocks", "arguments": {}, "cache": True}],
        server="wudao",
        context=_Context(),
        cache_max_age_minutes=20,
    )

    assert calls == 6
    assert delays == [2.0, 5.0, 10.0, 30.0]
    assert stats["failed"] == 1
    assert receipts[0]["attempts"] == 6
