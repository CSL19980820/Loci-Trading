"""同步作业的运行记录不许把全市场回执搬进 ops.db。

实测：一条 sync 运行的 `result_json` 曾达 257 MB，258 条运行把 ops.db 撑到
1.7 GB。逐票回执的权威副本在 market.db.source_route_receipts，运维库只需要
够定位问题的失败样本。
"""
from __future__ import annotations

import json

from src.ops.application.jobs.sync import (
    _EVIDENCE_RECEIPT_LIMIT,
    _compact_source_evidence,
)


def _receipt(code: str, *, unresolved: bool) -> dict[str, object]:
    return {
        "code": code,
        "lane": "hist_daily",
        "unresolved": unresolved,
        "state": "failed" if unresolved else "selected",
        "attempts": [
            {"source_id": "tencent", "state": "attempted", "fields": ["date"] * 20}
        ]
        * 4,
        "coverage": {"source_rows": 2600, "rows_written": 2600},
    }


def _payload(total: int, failed: int) -> dict[str, object]:
    receipts = [_receipt(f"{i:06d}", unresolved=i < failed) for i in range(total)]
    return {
        "succeeded": total - failed,
        "failed": failed,
        "source_evidence": {
            "receipts": receipts,
            "selected_sources": {"tencent": total - failed},
            "unresolved_codes": [f"{i:06d}" for i in range(failed)],
        },
    }


def test_whole_market_receipts_do_not_reach_the_run_record() -> None:
    payload = _payload(5539, failed=3)

    _compact_source_evidence(payload)

    evidence = payload["source_evidence"]
    assert evidence["receipts_total"] == 5539
    assert len(evidence["receipts"]) == 3
    assert len(json.dumps(payload)) < 100_000


def test_failure_samples_are_capped_but_counted() -> None:
    payload = _payload(5539, failed=900)

    _compact_source_evidence(payload)

    evidence = payload["source_evidence"]
    assert len(evidence["receipts"]) == _EVIDENCE_RECEIPT_LIMIT
    assert evidence["receipts_failed"] == 900
    assert evidence["receipts_total"] == 5539


def test_the_authoritative_copy_is_named_so_nobody_thinks_it_was_lost() -> None:
    payload = _payload(10, failed=0)

    _compact_source_evidence(payload)

    assert payload["source_evidence"]["receipts_source"] == (
        "market.db:source_route_receipts"
    )


def test_counts_and_selected_sources_survive() -> None:
    payload = _payload(10, failed=2)

    _compact_source_evidence(payload)

    evidence = payload["source_evidence"]
    assert evidence["selected_sources"] == {"tencent": 8}
    assert evidence["unresolved_codes"] == ["000000", "000001"]


def test_a_payload_without_evidence_is_left_alone() -> None:
    payload: dict[str, object] = {"succeeded": 1}

    _compact_source_evidence(payload)

    assert payload == {"succeeded": 1}
