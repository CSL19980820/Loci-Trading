"""结构化 interval 选股的分钟窗口必须在调度执行点再次收口。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.ops.infrastructure.scheduler import JobScheduler
from src.ops.infrastructure.store import OpsStore


class SchedulerWindowTests(unittest.TestCase):
    def test_interval_job_skips_before_window_and_runs_inside_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "ops.db"
            with OpsStore(db_path) as store:
                job_id = store.create_job(
                    name="盘中选股",
                    kind="sync",
                    cron="*/10 9-14 * * 1-5",
                    config={
                        "schedule": {
                            "mode": "interval",
                            "interval_minutes": 10,
                            "window_start_hour": 9,
                            "window_start_minute": 30,
                            "window_end_hour": 14,
                            "window_end_minute": 50,
                        }
                    },
                )

            scheduler = JobScheduler(db_path=str(db_path))
            with patch("src.ops.infrastructure.scheduler.run_job") as run_job:
                scheduler._run(job_id, now=datetime(2026, 7, 30, 9, 20))
                run_job.assert_not_called()

                scheduler._run(job_id, now=datetime(2026, 7, 30, 9, 30))

            run_job.assert_called_once()
            self.assertEqual(run_job.call_args.args[1]["id"], job_id)

    def test_interval_job_respects_split_market_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "ops.db"
            with OpsStore(db_path) as store:
                job_id = store.create_job(
                    name="龙回头盘中监测",
                    kind="skill_watch",
                    cron="*/10 9-14 * * mon-fri",
                    config={
                        "schedule": {
                            "mode": "interval",
                            "interval_minutes": 10,
                            "window_start_hour": 9,
                            "window_start_minute": 20,
                            "window_end_hour": 14,
                            "window_end_minute": 50,
                            "sessions": [
                                {
                                    "start_hour": 9,
                                    "start_minute": 20,
                                    "end_hour": 11,
                                    "end_minute": 30,
                                },
                                {
                                    "start_hour": 13,
                                    "start_minute": 0,
                                    "end_hour": 14,
                                    "end_minute": 50,
                                },
                            ],
                        }
                    },
                )

            scheduler = JobScheduler(db_path=str(db_path))
            allowed = ((9, 20), (11, 30), (13, 0), (14, 50))
            blocked = ((9, 10), (11, 40), (11, 50), (12, 0), (12, 50), (15, 0))
            with patch("src.ops.infrastructure.scheduler.run_job") as run_job:
                for hour, minute in allowed:
                    scheduler._run(job_id, now=datetime(2026, 7, 30, hour, minute))
                for hour, minute in blocked:
                    scheduler._run(job_id, now=datetime(2026, 7, 30, hour, minute))

            self.assertEqual(run_job.call_count, len(allowed))


if __name__ == "__main__":
    unittest.main()
