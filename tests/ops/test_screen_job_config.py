"""定时选股绑定上的行情范围回落。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.ops.application.screen_job_config import (
    load_screen_job_universe,
    resolve_screen_universe,
)
from src.ops.infrastructure.store import OpsStore


class ScreenJobConfigTests(unittest.TestCase):
    def test_loads_saved_universe_from_bound_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ops.db"
            with OpsStore(str(db)) as store:
                store.create_job(
                    name="screen:sanyuan-tail-v1",
                    kind="screen",
                    cron="30 15 * * 1-5",
                    config={
                        "strategy": "sanyuan-tail-v1",
                        "universe": {
                            "preset": "custom",
                            "boards": ["main"],
                            "exclude_st": True,
                        },
                    },
                    enabled=True,
                )
                self.assertEqual(
                    load_screen_job_universe("sanyuan-tail-v1", store=store),
                    {
                        "preset": "custom",
                        "boards": ["main"],
                        "exclude_st": True,
                    },
                )

    def test_request_universe_wins_over_saved(self) -> None:
        store = MagicMock()
        requested = {"boards": ["chi_next"], "exclude_st": False}
        self.assertEqual(
            resolve_screen_universe("sanyuan-tail-v1", requested, store=store),
            requested,
        )
        store.get_job_by_name.assert_not_called()


if __name__ == "__main__":
    unittest.main()
