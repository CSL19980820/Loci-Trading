from __future__ import annotations

import json
import logging

from src.ai.application.toolbus import build_toolbus


def test_toolbus_receipt_and_run_correlation_reach_observation_log(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("LOCI_OBSERVABILITY", "1")
    skill = {"install_path": "", "tool_specs": []}
    bus = build_toolbus(
        skill,
        trace_id="trace-1",
        run_id="run-1",
        job_id="job-1",
    )
    assert bus is not None

    with caplog.at_level(logging.INFO):
        result = bus.executor("ask_user", {"prompt": "选择"})

    assert result["tool_receipt_id"]
    records = [
        json.loads(record.getMessage().split(" ", 1)[1])
        for record in caplog.records
        if "loci_observation" in record.getMessage()
    ]
    invocation = next(item for item in records if item["event"] == "tool_invocation")
    assert invocation["trace_id"] == "trace-1"
    assert invocation["run_id"] == "run-1"
    assert invocation["job_id"] == "job-1"
    assert invocation["source_id"] == "skill:builtin"
    assert invocation["tool_receipt_id"] == result["tool_receipt_id"]
