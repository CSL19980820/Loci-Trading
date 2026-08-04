from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from src.app.main import create_app
from src.app.screen_skills import _screen_result_dict
from src.formula.domain.screen_formula_catalog import FORMULA_FUNCTIONS
from src.ledger import PalaceStore
from src.market import MarketStore
from src.ops.application.jobs import JobContext
from src.ops.application.jobs.screen import execute_screen
from src.strategy.application.screener import ScreenResult
def _screen_payload(slug: str = "demo-screen") -> dict:
    return {
        "slug": slug,
        "name": "示例战法",
        "description": "放量站上均线",
        "version": "0.1.0",
        "enabled": True,
        "formula": (
            "{示例}\n"
            "BASE:=MA(CLOSE,N);\n"
            "VOLR:=VOL/MA(VOL,3);\n"
            "PICK: CLOSE>BASE AND VOLR>=VOL_MULT;\n"
        ),
        "manifest": {
            "schema_version": 2,
            "entry_timing": "next_open",
            "min_bars": 10,
            "params": {
                "N": {"type": "int", "default": 3, "min": 2, "max": 10, "label": "周期"},
                "VOL_MULT": {"type": "float", "default": 1.2, "min": 0.5, "max": 5.0, "label": "量比"},
            },
            "output": {"signal": "PICK"},
            "factors": ["BASE", "VOLR"],
            "logic": [],
            "references": [],
            "data": {
                "fields": ["close", "volume"],
                "adjust": "qfq",
                "universe": {"codes_include": ["600001"]},
            },
        },
        "ui": {"schema_version": 1, "source_sha256": "x", "tree": {"kind": "logic", "op": "AND", "children": []}},
    }


def _python_payload(slug: str = "python-screen") -> dict:
    return {
        "slug": slug,
        "name": "Python 战法",
        "description": "Python 版放量均线",
        "version": "0.1.0",
        "enabled": True,
        "runtime": "python",
        "dialect": "python",
        "entrypoint": "strategy.py:compute",
        "code": (
            "def compute(panels, params):\n"
            "    close = panels['close']\n"
            "    volume = panels['volume']\n"
            "    base = close.rolling(int(params['N'])).mean()\n"
            "    volr = volume / volume.rolling(3).mean()\n"
            "    signal = (close > base) & (volr >= params['VOL_MULT'])\n"
            "    return {'signals': signal, 'factors': {'BASE': base, 'VOLR': volr}}\n"
        ),
        "manifest": {
            "schema_version": 1,
            "entry_timing": "next_open",
            "min_bars": 10,
            "params": {
                "N": {"type": "int", "default": 3, "min": 2, "max": 10, "label": "周期"},
                "VOL_MULT": {"type": "float", "default": 1.2, "min": 0.5, "max": 5.0, "label": "量比"},
            },
            "output": {"signal": "PICK"},
            "factors": ["BASE", "VOLR"],
            "logic": [],
            "references": [],
            "data": {
                "fields": ["close", "volume"],
                "adjust": "qfq",
                "universe": {"codes_include": ["600001"]},
            },
        },
        "ui": None,
    }


def _screen_zip(
    extra: dict[str, str] | None = None,
    *,
    skill_md: str | None = None,
    screen_yaml: str | None = None,
    formula: str | None = None,
) -> bytes:
    payload = _screen_payload()
    files = {
        "SKILL.md": (
            "---\n"
            "slug: demo-screen\n"
            "name: 示例战法\n"
            "version: 0.1.0\n"
            "description: 放量站上均线\n"
            "capability: screen\n"
            "enabled: true\n"
            "---\n\n"
            "放量站上均线，次日开盘处理。\n"
        ),
        "screen.yaml": (
            "schema_version: 1\n"
            "entry_timing: next_open\n"
            "min_bars: 10\n"
            "params:\n"
            "  N: { type: int, default: 3, min: 2, max: 10, label: 周期 }\n"
            "  VOL_MULT: { type: float, default: 1.2, min: 0.5, max: 5.0, label: 量比 }\n"
            "output:\n"
            "  signal: PICK\n"
            "factors: [BASE, VOLR]\n"
        ),
        "formula.tdx": payload["formula"],
    }
    if skill_md is not None:
        files["SKILL.md"] = skill_md
    if screen_yaml is not None:
        files["screen.yaml"] = screen_yaml
    if formula is not None:
        files["formula.tdx"] = formula
    for name, content in (extra or {}).items():
        files[name] = content
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _quotes(dates: list[str], close_values: list[float], volume_values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "open": close_values,
            "high": [value * 1.01 for value in close_values],
            "low": [value * 0.99 for value in close_values],
            "close": close_values,
            "volume": volume_values,
            "amount": np.array(close_values) * np.array(volume_values),
            "outstanding_share": np.full(len(dates), 1e9),
            "turnover": np.full(len(dates), 0.02),
        }
    )


class ScreenSkillApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        import os

        os.environ["PALACE_MARKET_DB"] = str(base / "market.db")
        os.environ["PALACE_OPS_DB"] = str(base / "ops.db")
        os.environ["PALACE_SKILL_ROOT"] = str(base / "skills")
        (base / "skills").mkdir(parents=True, exist_ok=True)
        self.market_db = base / "market.db"
        self.palace_db = base / "palace.db"
        app = create_app(self.palace_db, base / "no-static")
        self.client = TestClient(app)
        self._seed_market()

    def tearDown(self) -> None:
        self.client.close()
        for thread in threading.enumerate():
            if thread.name == "loci-screen-run":
                thread.join(timeout=10)
        self.temp.cleanup()

    def _seed_market(self) -> None:
        # 用「今天往前 14 个自然日」：当日写入的 api:screen 候选依赖
        # created_at 日期 == occurred_on 才不会被 schema 迁移重标为回填
        from datetime import date, timedelta

        today = date.today()
        dates = [(today - timedelta(days=13 - i)).isoformat() for i in range(14)]
        with MarketStore(self.market_db) as store:
            store.upsert_instruments(
                [
                    {
                        "code": "600001",
                        "name": "上涨样本",
                        "market": "SH",
                        "board": "main",
                        "industry": "测试",
                        "instrument_type": "STOCK",
                        "list_date": "2020-01-01",
                        "status": "normal",
                    },
                    {
                        "code": "600002",
                        "name": "平盘样本",
                        "market": "SH",
                        "board": "main",
                        "industry": "测试",
                        "instrument_type": "STOCK",
                        "list_date": "2020-01-01",
                        "status": "normal",
                    },
                ]
            )
            store.upsert_quotes(
                "600001",
                _quotes(
                    dates,
                    [10.0, 10.02, 10.05, 10.08, 10.1, 10.15, 10.18, 10.22, 10.26, 10.3, 10.36, 10.42, 10.55, 10.8],
                    [1_000_000, 1_000_000, 1_020_000, 1_040_000, 1_050_000, 1_060_000, 1_070_000, 1_080_000, 1_100_000, 1_120_000, 1_150_000, 1_180_000, 1_220_000, 2_000_000],
                ),
                source="test",
            )
            store.upsert_quotes(
                "600002",
                _quotes(
                    dates,
                    [10.0, 9.98, 10.0, 9.99, 10.0, 10.0, 9.99, 10.0, 10.01, 10.0, 9.99, 10.0, 10.0, 10.01],
                    [1_000_000] * len(dates),
                ),
                source="test",
            )

    def test_crud_conflicts_and_screen_execution(self) -> None:
        catalog = self.client.get("/api/screen-skills/catalog")
        self.assertEqual(catalog.status_code, 200, catalog.text)
        self.assertEqual(len(catalog.json()["functions"]), len(FORMULA_FUNCTIONS))
        self.assertTrue(all(item["source"] for item in catalog.json()["functions"]))

        created = self.client.post("/api/screen-skills", json=_screen_payload())
        self.assertEqual(created.status_code, 201, created.text)
        created_body = created.json()
        self.assertTrue(created_body["package_revision"])
        self.assertTrue(created_body["strategy_revision"])
        self.assertEqual(created_body["runtime"], "formula")
        self.assertEqual(created_body["dialect"], "loci")
        self.assertIn("code", created_body)
        self.assertEqual(created_body["manifest"]["output"]["signal"], "PICK")
        self.assertEqual(created_body["manifest"]["entry_timing"], "next_open")
        self.assertEqual(created_body["data"]["adjust"], "qfq")
        self.assertEqual(created_body["data"]["universe"]["codes_include"], ["600001"])
        self.assertTrue(created_body["updated_at"])

        duplicate = self.client.post("/api/screen-skills", json=_screen_payload())
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["detail"], "slug_conflict")

        builtin = self.client.post(
            "/api/screen-skills", json=_screen_payload("qianlong-close-v3")
        )
        self.assertEqual(builtin.status_code, 409)
        self.assertEqual(builtin.json()["detail"], "builtin_slug_conflict")

        listed = self.client.get("/api/strategies").json()
        formula = next(item for item in listed if item["slug"] == "demo-screen")
        self.assertEqual(formula["source_kind"], "formula")
        self.assertTrue(formula["editable"])
        self.assertEqual(formula["strategy_revision"], created_body["strategy_revision"])

        screen_list = self.client.get("/api/screen-skills")
        self.assertEqual(screen_list.status_code, 200, screen_list.text)
        listed_screen = next(
            item for item in screen_list.json() if item["slug"] == "demo-screen"
        )
        self.assertNotIn("code", listed_screen)
        self.assertNotIn("manifest", listed_screen)
        self.assertEqual(listed_screen["required_fields"], ["close", "volume"])

        detail = self.client.get("/api/screen-skills/demo-screen")
        self.assertEqual(detail.status_code, 200, detail.text)
        detail_body = detail.json()
        self.assertEqual(detail_body["slug"], "demo-screen")
        self.assertEqual(detail_body["manifest"]["output"]["signal"], "PICK")
        self.assertEqual(detail_body["strategy_revision"], created_body["strategy_revision"])

        sync = self.client.post(
            "/api/strategies/screen",
            json={
                "strategy": "demo-screen",
                "record_candidates": True,
                "skip_health_check": True,
            },
        )
        self.assertEqual(sync.status_code, 200, sync.text)
        sync_body = sync.json()
        self.assertEqual(sync_body["strategy_revision"], created_body["strategy_revision"])
        self.assertEqual(sync_body["effective_params"]["N"], 3)
        self.assertEqual(sync_body["universe"]["codes_include"], ["600001"])
        self.assertEqual(sync_body["universe_size"], 1)
        self.assertEqual([pick["code"] for pick in sync_body["picks"]], ["600001"])
        self.assertEqual(sync_body["recorded"]["written"], 1)
        self.assertEqual(sync_body["data_snapshot"]["fields"], ["close", "volume"])
        self.assertEqual(sync_body["data_snapshot"]["adjust"], "qfq")
        self.assertTrue(sync_body["data_snapshot"]["market_revision"])

        with PalaceStore(self.palace_db) as palace:
            rows = palace.candidates_payload(sync_body["trade_date"])
        stored = next(
            row for row in rows if row.get("pool_id") == f"demo-screen@{sync_body['trade_date']}"
        )
        self.assertEqual(stored["code"], "600001")
        self.assertTrue(stored["evidence"])

        backtest = self.client.post(
            "/api/backtest",
            json={
                "strategy": "demo-screen",
                "codes": ["600001", "600002"],
                "start": "2026-07-23",
                "end": "2026-07-28",
            },
        )
        self.assertEqual(backtest.status_code, 200, backtest.text)
        self.assertEqual(backtest.json()["config"]["strategy_revision"], created_body["strategy_revision"])

        async_start = self.client.post(
            "/api/screen/run",
            json={
                "strategy": "demo-screen",
                "codes": ["600001", "600002"],
                "record_candidates": False,
            },
        )
        self.assertEqual(async_start.status_code, 202, async_start.text)
        deadline = time.time() + 10
        status = async_start.json()
        while time.time() < deadline:
            status = self.client.get("/api/screen/run").json()
            if status.get("status") in {"done", "error"}:
                break
            time.sleep(0.1)
        self.assertEqual(status["status"], "done", status)
        self.assertEqual(status["result"]["strategy_revision"], created_body["strategy_revision"])

        job_result = execute_screen(
            {
                "strategy": "demo-screen",
                "codes": ["600001", "600002"],
                "record_candidates": False,
                # 测试隔离：不刷当日 spot（真实网络会覆盖夹具行情）
                "refresh_spot": False,
            },
            JobContext(market_db=self.market_db, palace_db=self.palace_db),
        )
        self.assertEqual(job_result["strategy_revision"], created_body["strategy_revision"])
        self.assertEqual(job_result["pick_count"], 1)

        preview = self.client.post(
            "/api/screen-skills/preview",
            json={**_screen_payload(), "run": {"skip_health_check": True}},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        preview_body = preview.json()
        self.assertTrue(preview_body["ok"])
        self.assertEqual(preview_body["derived"]["signal"], "PICK")
        self.assertEqual(preview_body["data"]["universe"]["codes_include"], ["600001"])
        self.assertEqual(preview_body["run_result"]["strategy_revision"], created_body["strategy_revision"])
        self.assertEqual(
            preview_body["run_result"]["universe"]["codes_include"], ["600001"]
        )
        self.assertEqual(preview_body["run_result"]["data_snapshot"]["fields"], ["close", "volume"])
        self.assertEqual(preview_body["run_result"]["data_snapshot"]["adjust"], "qfq")
        self.assertTrue(preview_body["run_result"]["data_snapshot"]["market_revision"])
        self.assertEqual([pick["code"] for pick in preview_body["run_result"]["picks"]], ["600001"])

        updated_payload = _screen_payload()
        updated_payload["formula"] = (
            "{示例}\nBASE:=MA(CLOSE,N);\nVOLR:=VOL/MA(VOL,3);\nPICK: CLOSE>=BASE AND VOLR>=VOL_MULT;\n"
        )
        updated = self.client.put(
            "/api/screen-skills/demo-screen",
            json={**updated_payload, "expected_revision": created_body["package_revision"]},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        stale = self.client.put(
            "/api/screen-skills/demo-screen",
            json={**updated_payload, "expected_revision": created_body["package_revision"]},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"], "revision_conflict")

        removed = self.client.request(
            "DELETE",
            "/api/screen-skills/demo-screen",
            json={"expected_revision": updated.json()["package_revision"]},
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(self.client.get("/api/screen-skills/demo-screen").status_code, 404)

    def test_preview_rejects_unbounded_code_list_and_truncates_pick_payload(self) -> None:
        response = self.client.post(
            "/api/screen-skills/preview",
            json={
                **_screen_payload(),
                "run": {"codes": ["600001"] * 5001, "skip_health_check": True},
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

        result = ScreenResult(
            strategy_slug="demo-screen",
            trade_date="2026-07-28",
            picks=[{"code": f"{index:06d}"} for index in range(501)],
            universe_size=501,
        )
        body = _screen_result_dict(result)
        self.assertEqual(len(body["picks"]), 500)
        self.assertEqual(body["picks_total"], 501)
        self.assertTrue(body["picks_truncated"])

    def test_preview_compile_failure_returns_200_diagnostics(self) -> None:
        payload = _screen_payload()
        payload["formula"] = "{坏公式}\nPICK: CLOSE>MA(CLOSE,LOOKBACK);\n"
        payload["manifest"]["params"] = {}
        preview = self.client.post("/api/screen-skills/preview", json=payload)
        self.assertEqual(preview.status_code, 200, preview.text)
        body = preview.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body.get("run_result"))
        self.assertTrue(body["diagnostics"])
        self.assertEqual(body["diagnostics"][0]["code"], "E_UNDEFINED_IDENTIFIER")

    def test_import_generate_and_skill_endpoint_rejection(self) -> None:
        rejected = self.client.post(
            "/api/screen-skills/import",
            files={"file": ("screen.zip", _screen_zip({"evil.ps1": "Write-Host boom"}), "application/zip")},
        )
        self.assertEqual(rejected.status_code, 422)

        imported = self.client.post(
            "/api/screen-skills/import",
            files={"file": ("screen.zip", _screen_zip(), "application/zip")},
        )
        self.assertEqual(imported.status_code, 201, imported.text)

        via_skills = self.client.post(
            "/api/skills",
            files={"file": ("screen.zip", _screen_zip(), "application/zip")},
        )
        self.assertEqual(via_skills.status_code, 422)
        self.assertIn("/api/screen-skills/import", via_skills.json()["detail"])

        generated_json = {
            **_screen_payload("generated-screen"),
            "runtime": "formula",
            "dialect": "loci",
            "code": _screen_payload("generated-screen")["formula"],
            "manifest": {
                **_screen_payload("generated-screen")["manifest"],
                "schema_version": 2,
                "logic": [
                    {
                        "id": "rule-1",
                        "title": "放量突破",
                        "expression": "CLOSE>BASE AND VOLR>=VOL_MULT",
                        "explanation": "收盘价站上均线且放量。",
                        "citations": ["ref-1"],
                    }
                ],
                "references": [
                    {
                        "id": "ref-1",
                        "title": "策略说明",
                        "kind": "doc",
                        "quote": "模型自行改写的引文",
                    }
                ],
                "data": {
                    "fields": ["close", "volume"],
                    "adjust": "qfq",
                    "universe": {"preset": "default_a_share"},
                },
            },
            "ui": None,
        }

        class _Resp:
            text = json.dumps(generated_json, ensure_ascii=False)

        with patch("src.ai.resolve_config", return_value=object()), patch(
            "src.ai.chat", return_value=_Resp()
        ) as chat_mock:
            response = self.client.post(
                "/api/screen-skills/generate",
                json={
                    "source_type": "description",
                    "source": "生成一个放量站上均线的战法草稿",
                    "slug": "generated-screen",
                    "name": "生成战法",
                    "provider": "demo",
                    "entry_timing": "next_open",
                    "runtime": "formula",
                    "dialect": "loci",
                    "references": [
                        {
                            "id": "ref-1",
                            "title": "策略说明",
                            "kind": "doc",
                            "quote": "放量突破定义",
                        }
                    ],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["draft"]["slug"], "generated-screen")
        self.assertEqual(response.json()["draft"]["manifest"]["output"]["signal"], "PICK")
        self.assertEqual(response.json()["draft"]["runtime"], "formula")
        self.assertEqual(response.json()["draft"]["manifest"]["references"][0]["quote"], "放量突破定义")
        prompt = chat_mock.call_args.args[1][0].content
        self.assertIn("不得虚构资料", prompt)
        self.assertIn('"id": "ref-1"', prompt)

        missing_reference = self.client.post(
            "/api/screen-skills/generate",
            json={"source_type": "description", "source": "生成一个放量站上均线的战法草稿", "provider": "demo"},
        )
        self.assertEqual(missing_reference.status_code, 422)

        bad_json = {
            **generated_json,
            "manifest": {
                **generated_json["manifest"],
                "logic": [],
                "references": [],
            },
        }

        class _BadResp:
            text = json.dumps(bad_json, ensure_ascii=False)

        with patch("src.ai.resolve_config", return_value=object()), patch("src.ai.chat", return_value=_BadResp()):
            bad = self.client.post(
                "/api/screen-skills/generate",
                json={
                    "source_type": "description",
                    "source": "生成一个放量站上均线的战法草稿",
                    "slug": "generated-screen",
                    "name": "生成战法",
                    "provider": "demo",
                    "entry_timing": "next_open",
                    "runtime": "formula",
                    "dialect": "loci",
                    "references": [
                        {
                            "id": "ref-1",
                            "title": "策略说明",
                            "kind": "doc",
                            "quote": "放量突破定义",
                        }
                    ],
                },
            )
        self.assertEqual(bad.status_code, 422, bad.text)

    def test_python_runtime_preview_and_screen_use_skill_defaults(self) -> None:
        created = self.client.post("/api/screen-skills", json=_python_payload())
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["runtime"], "python")
        self.assertEqual(body["dialect"], "python")
        self.assertEqual(body["entrypoint"], "strategy.py:compute")

        listed = self.client.get("/api/strategies").json()
        item = next(row for row in listed if row["slug"] == "python-screen")
        self.assertEqual(item["source_kind"], "python")
        self.assertEqual(item["runtime"], "python")
        self.assertEqual(item["dialect"], "python")

        sentinel = Path(self.temp.name) / "python-preview-executed.txt"
        preview_payload = _python_payload()
        preview_payload["code"] = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')"
        preview = self.client.post(
            "/api/screen-skills/preview",
            json={**preview_payload, "run": {"skip_health_check": True}},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        preview_body = preview.json()
        self.assertFalse(preview_body["ok"])
        self.assertEqual(preview_body["diagnostics"][0]["code"], "E_PYTHON_PREVIEW_DISABLED")
        self.assertFalse(sentinel.exists())

        sync = self.client.post(
            "/api/strategies/screen",
            json={"strategy": "python-screen", "skip_health_check": True},
        )
        self.assertEqual(sync.status_code, 200, sync.text)
        sync_body = sync.json()
        self.assertEqual(sync_body["universe"]["codes_include"], ["600001"])
        self.assertEqual(sync_body["data_snapshot"]["fields"], ["close", "volume"])
        self.assertEqual(sync_body["data_snapshot"]["adjust"], "qfq")
        self.assertEqual([pick["code"] for pick in sync_body["picks"]], ["600001"])

    def test_invalid_screen_archives_return_controlled_422(self) -> None:
        cases = [
            (
                "bad-skill-md",
                {"skill_md": "---\nname: [oops\n---\nbody\n"},
                "SKILL.md",
            ),
            (
                "bad-screen-yaml",
                {"screen_yaml": "schema_version: [oops\n"},
                "screen.yaml",
            ),
            (
                "bad-ui-json",
                {"extra": {"ui.json": "{oops"}},
                "ui.json",
            ),
        ]
        for name, kwargs, token in cases:
            with self.subTest(case=name, endpoint="screen-import"):
                response = self.client.post(
                    "/api/screen-skills/import",
                    files={"file": ("screen.zip", _screen_zip(**kwargs), "application/zip")},
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn(token, json.dumps(response.json(), ensure_ascii=False))
            with self.subTest(case=name, endpoint="skills"):
                response = self.client.post(
                    "/api/skills",
                    files={"file": ("screen.zip", _screen_zip(**kwargs), "application/zip")},
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotEqual(response.text, "Internal Server Error")
                if name == "bad-skill-md":
                    self.assertIn("detail", response.json())
                else:
                    self.assertIn(token, json.dumps(response.json(), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
