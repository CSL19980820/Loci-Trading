from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import BoundedSemaphore
from types import SimpleNamespace
import time

import pandas as pd
import pytest

import src.market.infrastructure.akshare_catalog as akshare_catalog
import src.market.infrastructure.akshare_probe_worker as akshare_probe_worker
from src.market.infrastructure.akshare_catalog import (
    discover_stock_capabilities,
    probe_stock_capability,
)
from src.market.infrastructure.akshare_catalog_meta import MAX_DOC_SECTION_LENGTH
from src.market.infrastructure.akshare_probe_result import (
    MAX_RESULT_COLUMNS,
    MAX_RESULT_FIELD_BYTES,
    summarize_probe_result,
)


def _stock_catalog(*targets: object) -> SimpleNamespace:
    return SimpleNamespace(**{target.__name__: target for target in targets})


def test_discovery_keeps_real_callable_stock_exports_sorted_and_described() -> None:
    def stock_zeta(symbol: str, date: str) -> list[dict[str, str]]:
        """Zeta source. More implementation detail."""
        return [{"symbol": symbol, "date": date}]

    def stock_alpha(limit: int = 3) -> list[int]:
        return list(range(limit))

    stock_zeta.__module__ = "akshare.stock.feature"
    stock_alpha.__module__ = "akshare.stock.feature"

    ignored = lambda: None
    ignored.__module__ = "akshare.stock.feature"
    catalog = _stock_catalog(stock_zeta, stock_alpha, ignored)

    entries = discover_stock_capabilities(catalog)

    assert [entry["name"] for entry in entries] == ["stock_alpha", "stock_zeta"]
    assert entries[1]["default_params"] == {"symbol": "600519", "date": "20250101"}
    assert entries[0]["module"] == "akshare.stock.feature"
    assert entries[1]["doc"] == "Zeta source. More implementation detail."
    assert entries[0]["status"] == "available"
    assert entries[0]["execution_mode"] == "disabled"


def test_discovery_parses_param_and_return_sections_from_the_full_docstring() -> None:
    def stock_zh_a_hist(symbol: str = "000001", period: str = "daily") -> list[dict[str, str]]:
        """东方财富网-行情首页-沪深京 A 股-每日行情

        https://quote.eastmoney.com/concept/sh603777.html
        :param symbol: 股票代码
            可通过 stock_zh_a_spot_em 获取
        :type symbol: str
        :param period: choice of {'daily', 'weekly', 'monthly'}
        :type period: str
        :return: 每日行情数据
        :rtype: pandas.DataFrame
        """
        return [{"symbol": symbol, "period": period}]

    stock_zh_a_hist.__module__ = "akshare.stock_feature.stock_hist_em"

    entry = discover_stock_capabilities(_stock_catalog(stock_zh_a_hist))[0]

    assert entry["param_docs"] == {
        "symbol": "股票代码 可通过 stock_zh_a_spot_em 获取",
        "period": "choice of {'daily', 'weekly', 'monthly'}",
    }
    assert entry["returns"] == "每日行情数据"
    json.dumps(entry)


def test_discovery_leaves_doc_sections_empty_when_upstream_omits_them() -> None:
    def stock_zh_a_spot_em() -> list[dict[str, str]]:
        """东方财富网-沪深京 A 股-实时行情"""
        return [{"代码": "600519"}]

    def stock_zh_a_undocumented() -> None:
        return None

    for target in (stock_zh_a_spot_em, stock_zh_a_undocumented):
        target.__module__ = "akshare.stock_feature.stock_hist_em"

    entries = discover_stock_capabilities(
        _stock_catalog(stock_zh_a_spot_em, stock_zh_a_undocumented)
    )

    assert [entry["param_docs"] for entry in entries] == [{}, {}]
    assert [entry["returns"] for entry in entries] == ["", ""]


def test_discovery_caps_a_runaway_param_description() -> None:
    def stock_zh_a_hist(symbol: str = "000001") -> None:
        return None

    stock_zh_a_hist.__doc__ = ":param symbol: " + "股" * 500 + "\n:return: " + "表" * 500
    stock_zh_a_hist.__module__ = "akshare.stock_feature.stock_hist_em"

    entry = discover_stock_capabilities(_stock_catalog(stock_zh_a_hist))[0]

    assert len(str(entry["param_docs"]["symbol"])) == MAX_DOC_SECTION_LENGTH
    assert len(str(entry["returns"])) == MAX_DOC_SECTION_LENGTH


def test_probe_columns_carry_a_chinese_english_gloss() -> None:
    def stock_zh_a_hist(symbol: str) -> pd.DataFrame:
        return pd.DataFrame({"日期": ["2026-01-05"], "成交额": [1.0], "融资余额": [2.0]})

    stock_zh_a_hist.__module__ = "akshare.stock.feature"

    result = probe_stock_capability(
        "stock_zh_a_hist", {"symbol": "600519"}, resolver=_stock_catalog(stock_zh_a_hist)
    )

    assert result["columns"] == ["日期", "成交额", "融资余额"]
    assert result["columns_detail"] == [
        {"raw": "日期", "cn": "日期", "en": "date"},
        {"raw": "成交额", "cn": "成交额", "en": "amount"},
        {"raw": "融资余额", "cn": "融资余额", "en": ""},
    ]
    json.dumps(result)


def test_probe_column_gloss_respects_the_column_cap_and_failure_path() -> None:
    def stock_zh_a_hist(fail: bool = False) -> pd.DataFrame:
        if fail:
            raise RuntimeError("provider down")
        return pd.DataFrame({f"列{index}": [index] for index in range(80)})

    stock_zh_a_hist.__module__ = "akshare.stock.feature"
    catalog = _stock_catalog(stock_zh_a_hist)

    result = probe_stock_capability("stock_zh_a_hist", resolver=catalog)
    failed = probe_stock_capability("stock_zh_a_hist", {"fail": True}, resolver=catalog)

    assert len(result["columns"]) == MAX_RESULT_COLUMNS
    assert len(result["columns_detail"]) == MAX_RESULT_COLUMNS
    assert failed["columns_detail"] == []


def test_discovery_accepts_cached_callable_not_only_functions() -> None:
    @lru_cache
    def stock_zh_a_spot_em() -> list[dict[str, str]]:
        return [{"code": "600519"}]

    stock_zh_a_spot_em.__module__ = "akshare.stock.stock_zh_a_spot"

    entries = discover_stock_capabilities(_stock_catalog(stock_zh_a_spot_em))

    assert len(entries) == 1
    assert entries[0]["execution_mode"] == "on_demand"
    assert entries[0]["status"] == "available"


def test_discovery_describes_required_inputs_without_disabling_on_demand_capability() -> None:
    def stock_individual_notice_report(
        security: str, symbol: str = "全部", page: int = 1
    ) -> list[dict[str, str]]:
        return [{"security": security, "symbol": symbol, "page": str(page)}]

    stock_individual_notice_report.__module__ = "akshare.stock_fundamental.stock_notice"

    entry = discover_stock_capabilities(_stock_catalog(stock_individual_notice_report))[0]

    assert entry["execution_mode"] == "on_demand"
    assert entry["status"] == "needs_parameters"
    assert entry["default_params"] == {
        "security": "600519",
        "symbol": "全部",
        "page": 1,
    }
    assert entry["parameters"] == [
        {
            "name": "security",
            "required": True,
            "kind": "positional_or_keyword",
            "annotation": "str",
            "has_default": False,
            "default": None,
            "sample": "600519",
        },
        {
            "name": "symbol",
            "required": False,
            "kind": "positional_or_keyword",
            "annotation": "str",
            "has_default": True,
            "default": "全部",
            "sample": "全部",
        },
        {
            "name": "page",
            "required": False,
            "kind": "positional_or_keyword",
            "annotation": "int",
            "has_default": True,
            "default": 1,
            "sample": 1,
        },
    ]
    json.dumps(entry)

    result = probe_stock_capability(
        "stock_individual_notice_report",
        {"security": "000001"},
        resolver=_stock_catalog(stock_individual_notice_report),
    )
    assert result["sample"] == [{"security": "000001", "symbol": "全部", "page": "1"}]


def test_probe_rejects_unknown_name_unknown_params_and_invalid_json_values() -> None:
    def stock_zh_a_hist(symbol: str) -> str:
        return symbol

    stock_zh_a_hist.__module__ = "akshare.stock.feature"
    catalog = _stock_catalog(stock_zh_a_hist)

    with pytest.raises(ValueError, match="unknown stock capability"):
        probe_stock_capability("__import__", {}, resolver=catalog)
    with pytest.raises(ValueError, match="unknown parameters"):
        probe_stock_capability("stock_zh_a_hist", {"symbol": "600519", "extra": 1}, resolver=catalog)
    with pytest.raises(ValueError, match="JSON primitive"):
        probe_stock_capability("stock_zh_a_hist", {"symbol": {"bad": {1}}}, resolver=catalog)
    with pytest.raises(ValueError, match="missing a required argument"):
        probe_stock_capability("stock_zh_a_hist", {}, resolver=catalog)


def test_probe_rejects_deep_or_oversized_json_before_execution() -> None:
    calls = 0

    def stock_zh_a_hist(filters: object = None) -> str:
        nonlocal calls
        calls += 1
        return str(filters)

    stock_zh_a_hist.__module__ = "akshare.stock.feature"
    catalog = _stock_catalog(stock_zh_a_hist)
    nested: object = "leaf"
    for _ in range(akshare_catalog.MAX_PROBE_JSON_DEPTH + 1):
        nested = [nested]

    with pytest.raises(ValueError, match="nesting"):
        probe_stock_capability("stock_zh_a_hist", {"filters": nested}, resolver=catalog)

    oversized = [["中" * 128 for _ in range(20)] for _ in range(6)]
    with pytest.raises(ValueError, match="serialized size"):
        probe_stock_capability("stock_zh_a_hist", {"filters": oversized}, resolver=catalog)

    assert calls == 0


def test_probe_summary_bounds_deep_and_wide_values() -> None:
    deep: object = "leaf"
    for _ in range(8):
        deep = {"nested": deep}
    wide = {f"field-{index}": "中" * 1000 for index in range(1000)}

    result = summarize_probe_result({"deep": deep, "wide": wide}, max_sample_rows=5)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")

    assert len(encoded) < 256 * 1024
    sample = result["sample"][0]
    assert isinstance(sample, dict)
    assert len(sample["wide"]) == 20
    assert all(
        len(str(value).encode("utf-8")) <= MAX_RESULT_FIELD_BYTES
        for value in sample["wide"].values()
    )
    assert "<truncated>" in json.dumps(sample, ensure_ascii=False)


def test_probe_coerces_annotated_scalars_and_rejects_expensive_pages() -> None:
    captured: dict[str, object] = {}

    def stock_zh_a_hist(page: int, enabled: bool) -> dict[str, object]:
        captured.update(page=page, enabled=enabled)
        return captured

    stock_zh_a_hist.__module__ = "akshare.stock.feature"
    catalog = _stock_catalog(stock_zh_a_hist)

    result = probe_stock_capability(
        "stock_zh_a_hist", {"page": "2", "enabled": "false"}, resolver=catalog
    )

    assert captured == {"page": 2, "enabled": False}
    assert result["sample"] == [captured]
    with pytest.raises(ValueError, match="page.*1.*5"):
        probe_stock_capability(
            "stock_zh_a_hist", {"page": 6, "enabled": True}, resolver=catalog
        )


def test_discovery_uses_a_small_page_sample_for_probe_safety() -> None:
    def stock_zh_a_hist(to_page: int = 100) -> list[int]:
        return list(range(to_page))

    stock_zh_a_hist.__module__ = "akshare.stock.feature"

    entry = discover_stock_capabilities(_stock_catalog(stock_zh_a_hist))[0]

    assert entry["default_params"] == {"to_page": 5}
    assert entry["parameters"][0]["default"] == 100
    assert entry["parameters"][0]["sample"] == 5


def test_probe_accepts_name_resolver_but_still_checks_catalog_membership() -> None:
    def stock_zh_a_hist(symbol: str) -> str:
        return symbol

    stock_zh_a_hist.__module__ = "akshare.stock.feature"

    def resolver(name: str) -> object:
        return {"stock_zh_a_hist": stock_zh_a_hist}[name]

    assert probe_stock_capability("stock_zh_a_hist", {"symbol": "600519"}, resolver=resolver)[
        "sample"
    ] == ["600519"]

    def invalid_resolver(_: str) -> object:
        return lambda: "not catalogued"

    with pytest.raises(ValueError, match="unknown stock capability"):
        probe_stock_capability("stock_not_real", {}, resolver=invalid_resolver)


def test_probe_serializes_dataframe_and_bounds_sample() -> None:
    def stock_zh_a_hist(symbol: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": [symbol] * 6,
                "when": [datetime(2026, 1, day) for day in range(1, 7)],
                "price": [float("nan"), 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        )

    stock_zh_a_hist.__module__ = "akshare.stock.feature"

    result = probe_stock_capability(
        "stock_zh_a_hist", {"symbol": "600519"}, resolver=_stock_catalog(stock_zh_a_hist)
    )

    assert result["rows"] == 6
    assert result["columns"] == ["symbol", "when", "price"]
    assert result["sample"][0] == {
        "symbol": "600519",
        "when": "2026-01-01T00:00:00",
        "price": None,
    }
    assert result["truncated"] is True
    assert result["error"] is None
    json.dumps(result)


def test_probe_serializes_list_dict_scalar_and_runtime_failure() -> None:
    def stock_list() -> list[dict[str, object]]:
        return [{"a": 1}, {"b": float("nan")}]

    def stock_dict() -> dict[str, object]:
        return {"when": datetime(2026, 1, 1), "ok": True}

    def stock_scalar() -> int:
        return 7

    def stock_failure() -> None:
        raise RuntimeError("provider down")

    for target in (stock_list, stock_dict, stock_scalar, stock_failure):
        target.__name__ = "stock_zh_a_hist"
        target.__module__ = "akshare.stock.feature"

    assert probe_stock_capability("stock_zh_a_hist", resolver=_stock_catalog(stock_list))["sample"] == [
        {"a": 1},
        {"b": None},
    ]
    assert probe_stock_capability("stock_zh_a_hist", resolver=_stock_catalog(stock_dict))["sample"] == [
        {"when": "2026-01-01T00:00:00", "ok": True}
    ]
    assert probe_stock_capability("stock_zh_a_hist", resolver=_stock_catalog(stock_scalar))["sample"] == [7]
    failed = probe_stock_capability("stock_zh_a_hist", resolver=_stock_catalog(stock_failure))
    assert failed["rows"] is None
    assert failed["error"] == "RuntimeError: provider down"


def test_probe_executes_every_discovered_stock_callable_through_the_budgeted_worker() -> None:
    def stock_zh_a_spot_em() -> list[dict[str, str]]:
        return [{"code": "600519"}]

    stock_zh_a_spot_em.__module__ = "akshare.stock.feature"
    catalog = _stock_catalog(stock_zh_a_spot_em)

    assert discover_stock_capabilities(catalog)[0]["name"] == "stock_zh_a_spot_em"
    result = probe_stock_capability("stock_zh_a_spot_em", resolver=catalog)
    assert result["sample"] == [{"code": "600519"}]


def test_probe_replaces_expensive_defaults_and_rejects_large_date_ranges() -> None:
    captured: dict[str, object] = {}

    def stock_zh_a_hist(
        symbol: str = "000001",
        start_date: str = "19700101",
        end_date: str = "20500101",
        to_page: int = 100,
        limit: int = 1000,
    ) -> dict[str, object]:
        captured.update(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            to_page=to_page,
            limit=limit,
        )
        return captured

    stock_zh_a_hist.__module__ = "akshare.stock.feature"
    catalog = _stock_catalog(stock_zh_a_hist)
    entry = discover_stock_capabilities(catalog)[0]
    result = probe_stock_capability("stock_zh_a_hist", resolver=catalog)

    assert entry["default_params"]["start_date"] != "19700101"
    assert entry["default_params"]["end_date"] != "20500101"
    parameter_samples = {
        str(item["name"]): item["sample"]
        for item in entry["parameters"]
    }
    assert parameter_samples["start_date"] == entry["default_params"]["start_date"]
    assert parameter_samples["end_date"] == entry["default_params"]["end_date"]
    assert captured["to_page"] == 5
    assert captured["limit"] == 5
    assert datetime.strptime(str(captured["end_date"]), "%Y%m%d") - datetime.strptime(
        str(captured["start_date"]), "%Y%m%d"
    ) <= timedelta(days=31)
    assert result["sample"] == [captured]
    with pytest.raises(ValueError, match="date window"):
        probe_stock_capability(
            "stock_zh_a_hist",
            {"start_date": "20250101", "end_date": "20250215"},
            resolver=catalog,
        )
    with pytest.raises(ValueError, match="exceeds 128"):
        probe_stock_capability("stock_zh_a_hist", {"symbol": "x" * 129}, resolver=catalog)


def test_probe_constrains_begin_date_and_upstream_timeout() -> None:
    captured: dict[str, object] = {}

    def stock_individual_notice_report(
        security: str = "600519",
        begin_date: str | None = None,
        end_date: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        captured.update(
            security=security,
            begin_date=begin_date,
            end_date=end_date,
            timeout=timeout,
        )
        return captured

    stock_individual_notice_report.__module__ = "akshare.stock_feature.stock_notice"
    catalog = _stock_catalog(stock_individual_notice_report)

    entry = discover_stock_capabilities(catalog)[0]
    result = probe_stock_capability("stock_individual_notice_report", resolver=catalog)

    assert entry["default_params"]["begin_date"] is not None
    assert captured["begin_date"] == entry["default_params"]["begin_date"]
    assert captured["end_date"] == entry["default_params"]["end_date"]
    assert captured["timeout"] == akshare_catalog.MAX_PROBE_SECONDS
    assert result["sample"] == [captured]
    with pytest.raises(ValueError, match="timeout.*8"):
        probe_stock_capability(
            "stock_individual_notice_report",
            {"security": "600519", "timeout": 9},
            resolver=catalog,
        )


def test_probe_injected_resolver_runs_locally_without_a_background_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stock_zh_a_hist() -> None:
        time.sleep(0.05)

    stock_zh_a_hist.__module__ = "akshare.stock.feature"
    monkeypatch.setattr(akshare_catalog, "MAX_PROBE_SECONDS", 0.01)

    result = probe_stock_capability(
        "stock_zh_a_hist", resolver=_stock_catalog(stock_zh_a_hist)
    )

    assert result["sample"] == [None]
    assert result["error"] is None


def test_production_probe_terminates_spawn_workers_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """真实 spawn 子进程卡住后必须被杀掉，两个并发槽也必须可再次取得。"""
    package = tmp_path / "akshare"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from .stock import stock_zh_a_hist\n", encoding="utf-8"
    )
    (package / "stock.py").write_text(
        "from pathlib import Path\n"
        "import os\n"
        "import time\n\n"
        "def stock_zh_a_hist(marker: str, block: bool = True, exit_now: bool = False):\n"
        "    if exit_now:\n"
        "        os._exit(0)\n"
        "    if block:\n"
        "        Path(marker).write_text(str(os.getpid()), encoding='utf-8')\n"
        "        time.sleep(60)\n"
        "    return [{'status': 'ok'}]\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "akshare", raising=False)
    monkeypatch.delitem(sys.modules, "akshare.stock", raising=False)
    monkeypatch.setattr(akshare_catalog, "MAX_PROBE_SECONDS", 2.0)
    monkeypatch.chdir(tmp_path)
    markers = [Path("worker-one.pid"), Path("worker-two.pid")]

    def invoke(marker: Path) -> dict[str, object]:
        return probe_stock_capability(
            "stock_zh_a_hist", {"marker": str(marker), "block": True}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invoke, marker) for marker in markers]
        results = [future.result(timeout=5) for future in futures]

    assert [result["error"] for result in results] == [
        "TimeoutError: probe exceeded 2s runtime budget",
        "TimeoutError: probe exceeded 2s runtime budget",
    ]
    worker_pids = [int(marker.read_text(encoding="utf-8")) for marker in markers]
    assert all(not _pid_is_alive(pid) for pid in worker_pids)
    assert not any(child.name == "akshare-probe" for child in multiprocessing.active_children())

    recovered = probe_stock_capability(
        "stock_zh_a_hist", {"marker": "recovered.pid", "block": False}
    )
    assert recovered["error"] is None
    assert recovered["sample"] == [{"status": "ok"}]

    no_result = probe_stock_capability(
        "stock_zh_a_hist",
        {"marker": "no-result.pid", "block": False, "exit_now": True},
    )
    assert no_result["error"] == "RuntimeError: probe worker exited without an IPC result"
    assert not any(child.name == "akshare-probe" for child in multiprocessing.active_children())


def test_probe_start_failure_releases_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    class Endpoint:
        def close(self) -> None:
            return None

    class Process:
        def start(self) -> None:
            raise OSError("spawn unavailable")

        def is_alive(self) -> bool:
            raise AssertionError("unstarted process must not be inspected")

        def join(self, timeout: float | None = None) -> None:
            raise AssertionError("unstarted process must not be joined")

    class Context:
        def __init__(self) -> None:
            self.process = Process()

        def Pipe(self, *, duplex: bool) -> tuple[Endpoint, Endpoint]:
            assert not duplex
            return Endpoint(), Endpoint()

        def Process(self, **_kwargs: object) -> Process:
            return self.process

    context = Context()
    slots = BoundedSemaphore(1)
    monkeypatch.setattr(akshare_probe_worker, "get_context", lambda _method: context)

    with pytest.raises(akshare_probe_worker.ProbeWorkerStartError, match="spawn unavailable"):
        akshare_probe_worker.run_akshare_probe(
            "stock_zh_a_hist",
            {},
            timeout_seconds=1,
            max_sample_rows=1,
            slots=slots,
        )

    assert slots.acquire(blocking=False)
    slots.release()


def _pid_is_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
