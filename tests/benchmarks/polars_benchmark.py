"""可选的 pandas/DuckDB/Polars 只读 POC。

显式运行：

    python -m pytest -q tests/benchmarks/polars_benchmark.py -s

文件不以 ``test_`` 开头，默认套件不会把它当作常规回归测试；Polars 未安装
时显式运行会跳过。所有数据只写入 pytest 临时目录中的 market.db。
"""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.market import MarketStore
from src.market.infrastructure.polars_panel import polars_available
from src.research.application.readonly_engine import readonly_frame
from tests.benchmarks.baseline_support import measure_case


def _bars() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code_index in range(8):
        code = f"{code_index + 1:06d}"
        for day_index in range(32):
            close = 10.0 + code_index * 0.1 + day_index * 0.02
            trade_date = date(2026, 6, 1) + timedelta(days=day_index)
            rows.append(
                {
                    "code": code,
                    "date": trade_date.isoformat(),
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "volume": 100_000 + day_index,
                    "amount": close * (100_000 + day_index),
                    "turnover": 0.02,
                }
            )
    return rows


def _digest(panels: dict[str, pd.DataFrame]) -> str:
    digest = sha256()
    for field in sorted(panels):
        digest.update(field.encode("utf-8"))
        digest.update(pd.util.hash_pandas_object(panels[field], index=True).values.tobytes())
    return digest.hexdigest()


def _panel_result(panels: dict[str, pd.DataFrame]) -> dict[str, Any]:
    close = panels["close"]
    return {
        "fields": sorted(panels),
        "rows": int(close.shape[0]),
        "codes": int(close.shape[1]),
        "index": [str(value) for value in close.index],
        "missing": int(sum(int(panel.isna().sum().sum()) for panel in panels.values())),
        "sha256": _digest(panels),
    }


@pytest.mark.skipif(
    not polars_available(),
    reason="可选依赖 polars 未安装；跳过只读 POC",
)
def test_readonly_market_and_research_engines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MarketStore(tmp_path / "market.db")
    try:
        store.upsert_quote_bars(_bars(), source="polars-poc")
        engines = ("pandas", "duckdb", "polars")
        measurements: dict[str, dict[str, Any]] = {}
        for engine in engines:
            monkeypatch.setenv("LOCI_MARKET_DUCKDB", "1" if engine == "duckdb" else "0")
            monkeypatch.setenv("LOCI_MARKET_POLARS", "1" if engine == "polars" else "0")
            measurements[engine] = measure_case(
                f"market_panel_{engine}",
                lambda: _panel_result(
                    store.load_panel(
                        fields=("open", "close", "volume", "turnover"),
                        codes=tuple(f"{index + 1:06d}" for index in range(8)),
                        start="2026-06-01",
                        end="2026-07-02",
                        adjust="none",
                    )
                ),
            )

        expected = measurements["pandas"]["result"]["sha256"]
        baseline = measurements["pandas"]["result"]
        assert expected
        assert all(item["error_count"] == 0 for item in measurements.values())
        assert all(item["p95_ms"] is not None for item in measurements.values())
        for item in measurements.values():
            result = item["result"]
            assert result["sha256"] == expected
            assert result["fields"] == baseline["fields"]
            assert result["rows"] == baseline["rows"]
            assert result["codes"] == baseline["codes"]
            assert result["missing"] == baseline["missing"]
            assert result["index"] == baseline["index"]

        source = store.history("000001", adjust="none")
        measurements["research_pandas"] = measure_case(
            "research_pandas",
            lambda: {"rows": len(readonly_frame(source, engine="pandas"))},
        )
        measurements["research_polars"] = measure_case(
            "research_polars",
            lambda: {"rows": len(readonly_frame(source, engine="polars"))},
        )
        assert (
            measurements["research_pandas"]["result"]["rows"]
            == measurements["research_polars"]["result"]["rows"]
        )
        payload = {
            "schema_version": "loci-readonly-engine-poc-v1",
            "fixture": {"codes": 8, "days": 32, "synthetic": True},
            "availability": {
                "duckdb": importlib.util.find_spec("duckdb") is not None,
                "polars": True,
            },
            "measurements": measurements,
        }
        artifact = Path(
            os.environ.get("LOCI_POLARS_BENCHMARK_ARTIFACT", str(tmp_path / "polars-poc.json"))
        )
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        assert artifact.is_file()
        assert not (tmp_path / "palace.db").exists()
    finally:
        store.close()
    assert payload["measurements"]["polars"]["result"]["rows"] == 32
