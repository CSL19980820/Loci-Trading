"""P1-5：助手 MCP 扫池参数裁剪。"""
from __future__ import annotations

from unittest.mock import patch

from src.ai.application.tool_schema import clamp_mcp_arguments


def test_clamp_mcp_arguments_caps_limit_and_codes() -> None:
    out = clamp_mcp_arguments(
        {
            "limit": 9999,
            "codes": [f"{i:06d}" for i in range(120)],
            "pageSize": 0,
        }
    )
    assert out["limit"] == 200
    assert len(out["codes"]) == 50
    assert out["pageSize"] == 1


def test_clamp_mcp_arguments_theme_days_and_spaced_codes() -> None:
    out = clamp_mcp_arguments(
        {
            "theme_top_n": 999,
            "days": 500,
            "codes": "600001 600002 600003 " + " ".join(f"{i:06d}" for i in range(60)),
        }
    )
    assert out["theme_top_n"] == 200
    assert out["days"] == 150
    assert len(str(out["codes"]).split(",")) == 50


class _StubClient:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.seen: dict | None = None

    def call_tool(self, _name: str, arguments: dict) -> dict:
        self.seen = arguments
        return dict(self.result)


def test_model_visible_text_declares_clamped_scope_and_truncation() -> None:
    """模型只读 text：削过的扫池范围和被砍掉的正文必须写在 text 里。"""
    from src.intel.application.fetch import guarded_client_call

    client = _StubClient({"text": '{"rows": [1,2,3]', "is_error": False, "truncated": True})
    with (
        patch("src.intel.application.fetch.acquire_quota"),
        patch("src.intel.application.fetch.record_quota_call"),
        patch("src.intel.application.fetch.quota_snapshot", return_value={}),
    ):
        result = guarded_client_call(client, "limit_up_filter", {"limit": 9999})

    assert client.seen == {"limit": 200}
    assert "limit:9999->200" in result["text"]
    assert "截断" in result["text"]
    assert result["clamped"] == ["limit:9999->200"]


def test_untouched_arguments_leave_tool_text_alone() -> None:
    from src.intel.application.fetch import guarded_client_call

    client = _StubClient({"text": "{}", "is_error": False})
    with (
        patch("src.intel.application.fetch.acquire_quota"),
        patch("src.intel.application.fetch.record_quota_call"),
        patch("src.intel.application.fetch.quota_snapshot", return_value={}),
    ):
        result = guarded_client_call(client, "limit_up_filter", {"limit": 20})

    assert result["text"] == "{}"
