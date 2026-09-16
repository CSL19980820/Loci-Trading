from contextlib import nullcontext
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from src.ops.application.eod_catchup import run_eod_catchup


@pytest.mark.parametrize("status,bucket", [
    ("success", "ran"), ("failed", "errors"), ("skipped", "skipped"),
])
def test_catchup_preserves_target_and_reports_real_outcome(status, bucket):
    job = {"id": "j", "name": "screen:test", "kind": "screen", "enabled": True,
           "cron": "30 15 * * mon-fri", "config": {"strategy": "test"}}
    store = Mock()
    store.list_jobs.return_value = [job]
    store.list_runs.return_value = []
    with patch("src.ops.application.jobs.run_job", return_value={
        "status": status, "error": "missing data",
    }) as run:
        result = run_eod_catchup(
            ops_store_factory=lambda: nullcontext(store), context_factory=lambda: None,
            last_trading_day="2026-09-11", now=datetime(2026, 9, 12, 21),
        )
    assert run.call_args.args[1]["config"]["date"] == "2026-09-11"
    assert job["config"] == {"strategy": "test"}
    assert len(result[bucket]) == 1
    assert sum(len(result[k]) for k in ["ran", "errors", "skipped"]) == 1
