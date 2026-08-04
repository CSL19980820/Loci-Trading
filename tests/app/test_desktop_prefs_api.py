from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from src.app.main import create_app


class DesktopPrefsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        import os

        os.environ["LOCI_DATA_DIR"] = str(base / "data")
        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        os.environ["PALACE_SKILL_ROOT"] = str(base / "skills")
        (base / "skills").mkdir(parents=True, exist_ok=True)
        (base / "data").mkdir(parents=True, exist_ok=True)
        os.environ.pop("PALACE_ENABLE_SCHEDULER", None)
        self.client = TestClient(create_app(base / "palace.db", base / "no-static"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_desktop_prefs_default_and_round_trip(self) -> None:
        got = self.client.get("/api/ops/desktop-prefs")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json(), {"minimize_to_tray": True})

        saved = self.client.put("/api/ops/desktop-prefs", json={"minimize_to_tray": False})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json(), {"minimize_to_tray": False})

        again = self.client.get("/api/ops/desktop-prefs")
        self.assertEqual(again.json()["minimize_to_tray"], False)
