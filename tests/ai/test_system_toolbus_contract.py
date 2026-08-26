from __future__ import annotations

from pathlib import Path
import time
from unittest.mock import patch

from src.ai.application.system_toolbus import (
    SystemToolBus,
    ToolSpec,
    _object,
)
from src.ai.application.system_toolbus_mcp import mount_default_mcp
from src.ai.application.tool_schema import invoke_mcp_tool
from src.intel import McpClient, McpTool


def _bus(root: Path, **kwargs: object) -> SystemToolBus:
    return SystemToolBus(
        palace_db=str(root / "palace.db"),
        market_db=str(root / "market.db"),
        ops_db=str(root / "ops.db"),
        attach_mcp=False,
        **kwargs,
    )


def test_schema_validation_runs_before_handler_and_receipt_is_returned(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    bus = _bus(tmp_path, on_event=events.append)
    bus._specs["contract_read"] = ToolSpec(
        "contract_read",
        "contract",
        _object({"code": {"type": "string", "pattern": r"^\d{6}$"}}, ["code"]),
        False,
        lambda args: calls.append(args) or {"text": "ok", "is_error": False},
    )

    invalid = bus.executor("contract_read", {"code": "bad"})
    assert invalid["is_error"]
    assert calls == []
    assert bus.executor("contract_read", {"code": "600519", "extra": 1})["is_error"]
    valid = bus.executor("contract_read", {"code": "600519"})

    assert not valid["is_error"]
    assert valid["tool_receipt_id"]
    assert valid["meta"]["tool_receipt_id"] == valid["tool_receipt_id"]
    assert [event["type"] for event in events[-2:]] == ["tool_start", "tool_end"]
    assert {event["tool_receipt_id"] for event in events[-2:]} == {valid["tool_receipt_id"]}


def test_read_only_bus_exposes_no_write_tools(tmp_path: Path) -> None:
    bus = _bus(tmp_path, read_only=True)
    assert all(item["risk"] == "read" for item in bus.catalog())
    result = bus.executor(
        "ledger_upsert_candidate",
        {"code": "600519", "decision": "观察", "reason": "等待确认"},
    )
    assert result["is_error"]


def test_tool_timeout_is_terminal_error_with_receipt(tmp_path: Path) -> None:
    bus = _bus(tmp_path, tool_timeout_seconds=0.005)
    bus._specs["slow_read"] = ToolSpec(
        "slow_read",
        "slow",
        _object({}),
        False,
        lambda _: (time.sleep(0.03) or {"text": "late", "is_error": False}),
    )

    result = bus.executor("slow_read", {})

    assert result["is_error"]
    assert result["meta"]["timeout"] is True
    assert result["tool_receipt_id"]


def test_mcp_mount_normalizes_schema_timeout_and_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tool = McpTool(
        name="probe",
        description="probe",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
        server="demo",
    )
    monkeypatch.setenv("LOCI_MCP_TOOL_TIMEOUT_SEC", "2")
    with (
        patch("src.intel.collect_tools", return_value=([tool], {"demo__probe": "demo"})),
        patch("src.intel.build_client", return_value=object()),
    ):
        bus = _bus(tmp_path)
        mount_default_mcp(bus)

    spec = bus._specs["demo__probe"]
    assert spec.parameters["additionalProperties"] is False
    assert spec.timeout_seconds == 2
    with patch(
        "src.ai.application.system_toolbus_mcp.invoke_mcp_tool",
        return_value={"text": "ok", "is_error": False},
    ):
        result = bus.executor("demo__probe", {"value": "x"})
    assert not result["is_error"]
    assert result["meta"]["tool_receipt_id"] == result["tool_receipt_id"]


def test_oversized_tool_payload_is_marked_truncated_for_the_model() -> None:
    """模型只看 text；半截 JSON 不标注就等于请它自己脑补剩下的行。"""
    from src.ai.application.system_tool_result import ok

    result = ok({"rows": [{"code": f"60{index:04d}", "note": "x" * 64} for index in range(400)]})

    assert result["truncated"] is True
    assert "已截断" in result["text"]
    assert result["structured"]["rows"], "结构化段仍保留全量，供本机代码使用"

    small = ok({"rows": [{"code": "600519"}]})
    assert small.get("truncated") is False
    assert "已截断" not in small["text"]


def test_mcp_client_path_delegates_to_quota_guard() -> None:
    client = McpClient(name="demo", url="https://example.invalid/mcp")
    with patch(
        "src.intel.guarded_client_call",
        return_value={"text": "quota-ok", "is_error": False},
    ) as guarded:
        result = invoke_mcp_tool(
            client,
            server="demo",
            full_name="demo__probe",
            arguments={"limit": 1},
        )
    assert result["text"] == "quota-ok"
    guarded.assert_called_once()
    assert guarded.call_args.kwargs["pool"] == "skill"
