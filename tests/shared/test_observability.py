from __future__ import annotations

import json
import logging

import pytest

from src.shared import observability


def test_observability_is_silent_and_has_no_metrics_by_default(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("LOCI_OBSERVABILITY", raising=False)
    observability.reset_metrics()
    with caplog.at_level(logging.INFO):
        observability.metric("test.metric", labels={"code": "600519"})
        observability.event(logging.getLogger("test.observability"), logging.INFO, "test")
    assert observability.metrics_snapshot() == []
    assert "loci_observation" not in caplog.text


def test_enabled_observation_correlates_without_high_cardinality_metrics(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("LOCI_OBSERVABILITY", "1")
    observability.reset_metrics()
    logger = logging.getLogger("test.observability")
    with caplog.at_level(logging.INFO):
        with observability.span(
            "test.operation",
            trace_id="trace-1",
            run_id="run-1",
            job_id="job-1",
            source_id="source-1",
            tool_receipt_id="tool-1",
            labels={"component": "test", "operation": "read", "code": "600519"},
        ):
            observability.event(logger, logging.INFO, "test_event", fields={"status": "ok"})
            observability.metric(
                "test.requests",
                labels={"component": "test", "operation": "read", "code": "600519"},
            )

    payload = json.loads(caplog.records[-1].getMessage().split(" ", 1)[1])
    assert payload["trace_id"] == "trace-1"
    assert payload["run_id"] == "run-1"
    assert "600519" not in json.dumps(observability.metrics_snapshot())
    assert observability.current_dict() == {}


def test_invalid_headers_are_not_admitted_to_correlation() -> None:
    assert observability.header_values(
        {
            "x-loci-trace-id": "trace-ok",
            "x-loci-run-id": "contains whitespace",
            "x-loci-job-id": "a" * 129,
        }
    ) == {"trace_id": "trace-ok"}
