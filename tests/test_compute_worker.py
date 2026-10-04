"""真实 spawn 进程：无限计算、异常和输出超限均退出且后续请求可继续。"""
from __future__ import annotations

from dataclasses import dataclass
from multiprocessing import active_children, get_context
import os
import pickle
import threading
import time

import pandas as pd
import pytest

from src.shared.tenancy import tenant_scope
from src.strategy.application.compute_worker import (
    ComputeWorkerCancelled,
    ComputeWorkerError,
    ComputeWorkerTimedOut,
    compute_in_worker,
    in_compute_worker,
    python_worker_scope,
)
from src.strategy.application.screen_python import build_python_engine
from src.strategy.application.screen_python_load import ScreenPythonError
from src.strategy.domain.base import SignalResult, StrategyError, signal_history_bars


NORMAL_CODE = """
import os
def compute(panels, params):
    close = panels['close']
    return {'signals': close > 1, 'factors': {'PID': close * 0 + os.getpid()}}
"""


def engine(code=NORMAL_CODE, **overrides):
    payload = {
        "slug": "worker-fixture", "name": "worker-fixture", "code": code,
        "manifest": {"entry_timing": "next_open", "min_bars": 1,
                     "data": {"fields": ["close"]}},
    }
    payload.update(overrides)
    return build_python_engine(payload)


@pytest.fixture
def panels():
    return {"close": pd.DataFrame([[1.0, 2.0], [3.0, 0.5]],
                                   index=pd.Index(["2026-09-29", "2026-09-30"], name="trade_date"),
                                   columns=pd.Index(["300001", "300002"], name="code"))}


def assert_next_request_works(panels):
    result = compute_in_worker(engine(), panels, timeout_seconds=8)
    pd.testing.assert_frame_equal(result.signals, panels["close"] > 1)
    assert int(result.factors["PID"].iloc[0, 0]) != os.getpid()


def test_audited_screen_uses_one_child_for_baseline_and_real_probes(tmp_path):
    marker = tmp_path / "audit-calls.txt"
    code = ("import os\nfrom pathlib import Path\n"
            "def compute(panels, params):\n"
            f"    with Path({str(marker)!r}).open('a') as f: f.write(str(os.getpid())+'\\n')\n"
            "    c=panels['close']\n"
            "    return {'signals':c>1,'factors':{'value':c*2}}\n")
    close = pd.DataFrame({"000001": range(10)}, index=pd.bdate_range("2026-09-01", periods=10).strftime("%Y-%m-%d"))
    python = engine(code)
    result = python.compute_audited({"close": close})
    pd.testing.assert_frame_equal(result.signals, (close > 1).iloc[-3:])
    pd.testing.assert_frame_equal(result.factors["value"], (close * 2).iloc[-3:])
    calls = marker.read_text().splitlines()
    assert len(calls) == 3 and len(set(calls)) == 1
    assert calls[0] != str(os.getpid())


def test_audited_screen_blocks_factor_only_future_in_same_child():
    code = ("def compute(panels, params):\n"
            "    c=panels['close']\n"
            "    factor=c*0+c.iloc[-1]\n"
            "    return {'signals':c<0,'factors':{'future':factor}}\n")
    close = pd.DataFrame({"000001": range(10)}, index=pd.bdate_range("2026-09-01", periods=10).strftime("%Y-%m-%d"))
    with pytest.raises(ScreenPythonError, match="截断"):
        engine(code).compute_audited({"close": close})


def test_python_engine_is_rebuilt_without_pickling_its_lock(panels):
    python = engine()
    with pytest.raises(TypeError):
        pickle.dumps(python)
    original = panels["close"].copy(deep=True)
    result = compute_in_worker(python, panels, timeout_seconds=8)
    pd.testing.assert_frame_equal(result.signals, original > 1)
    pd.testing.assert_frame_equal(panels["close"], original)
    assert int(result.factors["PID"].iloc[0, 0]) != os.getpid()
    assert python._callable is None and python._tempdir is None


def test_installed_package_helpers_are_reloaded_in_a_temporary_copy(panels, tmp_path):
    package = tmp_path / "installed"
    package.mkdir()
    (package / "strategy.py").write_text(
        "from helper import threshold\ndef compute(panels, params):\n"
        "    return {'signals': panels['close'] > threshold}\n", encoding="utf-8",
    )
    (package / "helper.py").write_text("threshold = 2\n", encoding="utf-8")
    cache = package / "__pycache__"
    cache.mkdir()
    sentinel = cache / "preserved.pyc"
    sentinel.write_bytes(b"original-cache")
    python = engine((package / "strategy.py").read_text(encoding="utf-8"), install_path=str(package))
    observed = compute_in_worker(python, panels, timeout_seconds=8)
    pd.testing.assert_frame_equal(observed.signals, panels["close"] > 2)
    assert sentinel.read_bytes() == b"original-cache"
    assert sorted(path.name for path in package.iterdir()) == ["__pycache__", "helper.py", "strategy.py"]


@pytest.mark.parametrize("phase", ["compute", "import"])
def test_true_infinite_code_is_terminated_and_a_later_request_runs(panels, tmp_path, phase):
    marker = tmp_path / f"entered-{phase}.txt"
    snippet = f"from pathlib import Path\nimport os\nPath({str(marker)!r}).write_text(str(os.getpid()))\nwhile True:\n    pass\n"
    if phase == "compute":
        code = "def compute(panels, params):\n" + "".join("    " + line + "\n" for line in snippet.splitlines())
    else:
        code = snippet + "\ndef compute(panels, params):\n    return {'signals': panels['close'] > 0}\n"
    before = time.monotonic()
    with pytest.raises(ComputeWorkerTimedOut):
        compute_in_worker(engine(code), panels, timeout_seconds=2.5)
    assert time.monotonic() - before < 6
    assert marker.exists(), "The child must have entered the real infinite loop."
    pid = int(marker.read_text())
    assert pid not in {process.pid for process in active_children()}
    assert_next_request_works(panels)


def test_runtime_error_is_reported_and_the_next_request_runs(panels):
    with pytest.raises(ComputeWorkerError) as raised:
        compute_in_worker(engine("def compute(panels, params):\n    raise ValueError('fixture failure')\n"),
                          panels, timeout_seconds=8)
    assert raised.value.code == "E_PYTHON_EXEC" and "fixture failure" in str(raised.value)
    assert_next_request_works(panels)


def test_oversized_numeric_output_is_rejected_before_ipc_and_next_request_runs(panels):
    code = """
import numpy as np
import pandas as pd
def compute(panels, params):
    return {'signals': panels['close'] > 0,
            'factors': {'BIG': pd.DataFrame(np.ones((400, 400)))}}
"""
    with pytest.raises(ComputeWorkerError) as raised:
        compute_in_worker(engine(code), panels, timeout_seconds=8, max_output_bytes=16_384)
    assert raised.value.code == "E_COMPUTE_OUTPUT_LIMIT"
    assert_next_request_works(panels)


def test_tenant_is_propagated_while_default_application_paths_are_isolated(panels, tmp_path, monkeypatch):
    sentinel = tmp_path / "original"
    sentinel.mkdir()
    monkeypatch.setenv("LOCI_DATA_DIR", str(sentinel))
    monkeypatch.setenv("PALACE_DB", str(sentinel / "protected.db"))
    code = """
from src.shared.tenancy import current_tenant
from src.shared.paths import data_dir
import os
def compute(panels, params):
    assert current_tenant() == 'worker-tenant'
    assert 'loci-compute-' in str(data_dir())
    assert 'PALACE_DB' not in os.environ
    return {'signals': panels['close'] > 1}
"""
    with tenant_scope("worker-tenant"):
        result = compute_in_worker(engine(code), panels, timeout_seconds=8)
    pd.testing.assert_frame_equal(result.signals, panels["close"] > 1)
    assert list(sentinel.iterdir()) == []
    assert os.environ["LOCI_DATA_DIR"] == str(sentinel)


def test_cancellation_terminates_infinite_compute_and_next_request_runs(panels, tmp_path):
    marker = tmp_path / "cancel-started.txt"
    code = f"def compute(panels, params):\n    from pathlib import Path\n    Path({str(marker)!r}).write_text('entered')\n    while True:\n        pass\n"
    with pytest.raises(ComputeWorkerCancelled):
        compute_in_worker(engine(code), panels, timeout_seconds=8, cancel_check=marker.exists)
    assert marker.exists()
    assert_next_request_works(panels)


@dataclass
class PickleEngine:
    def compute(self, panels, params):
        return SignalResult(signals=panels["close"] > 1, watch_signals=panels["close"] <= 1,
                            factors={"same": panels["close"]})


class UnknownScreenEngine:
    slug = "unknown-runtime-screen"
    name = "unknown-runtime-screen"
    entry_timing = "next_open"
    adjust = "none"

    def default_params(self):
        return {}

    def min_bars(self):
        return 1

    def required_fields(self):
        return ("close",)

    def compute(self, panels, params=None):
        close = panels["close"]
        return SignalResult(close > 0, {"PID": close * 0 + os.getpid()})


def test_unknown_custom_screen_engine_also_uses_worker_boundary(tmp_path):
    from src.market import MarketStore
    from src.strategy.application.screener import screen

    dates = pd.bdate_range("2026-09-01", periods=10).strftime("%Y-%m-%d")
    with MarketStore(tmp_path / "unknown-screen.db") as store:
        store.upsert_instruments([{"code": "600000", "name": "fixture", "market": "sh",
                                   "board": "main", "list_date": "2015-01-01"}])
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,source,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            [(day, "600000", 2., 2., 2., 2., 100., "fixture", day) for day in dates],
        )
        store.conn.commit()
        result = screen(store, UnknownScreenEngine(), trade_date=dates[-1], codes=["600000"],
                        health_check=False, live_overlay=False, adjust="none")
        assert len(result.picks) == 1
        assert int(result.picks[0]["factors"]["PID"]) != os.getpid()
        assert not active_children()


def test_picklable_custom_engine_and_watch_signals_round_trip(panels):
    result = compute_in_worker(PickleEngine(), panels, timeout_seconds=8)
    pd.testing.assert_frame_equal(result.signals, panels["close"] > 1)
    pd.testing.assert_frame_equal(result.watch_signals, panels["close"] <= 1)
    pd.testing.assert_frame_equal(result.factors["same"], panels["close"])


def test_unpicklable_generic_engine_fails_without_falling_back_to_thread(panels):
    with pytest.raises(ComputeWorkerError) as raised:
        compute_in_worker(threading.RLock(), panels, timeout_seconds=8)
    assert raised.value.code == "E_COMPUTE_ENGINE"


@pytest.mark.parametrize("budget", [0, -1, float("nan"), float("inf"), True])
def test_invalid_runtime_budget_never_starts_an_unbounded_worker(panels, budget):
    with pytest.raises(ComputeWorkerTimedOut):
        compute_in_worker(engine(), panels, timeout_seconds=budget)


def test_child_created_python_objects_cannot_cross_into_parent(panels):
    code = """
def compute(panels, params):
    return {'signals': panels['close'] > 0,
            'factors': {'OBJECTS': panels['close'].astype(str)}}
"""
    with pytest.raises(ComputeWorkerError) as raised:
        compute_in_worker(engine(code), panels, timeout_seconds=8)
    assert raised.value.code == "E_COMPUTE_OUTPUT"


def test_direct_python_compute_automatically_uses_the_worker(panels):
    python = engine()
    observed = python.compute(panels)
    pd.testing.assert_frame_equal(observed.signals, panels["close"] > 1)
    assert int(observed.factors["PID"].iloc[0, 0]) != os.getpid()
    assert python._callable is None and python._tempdir is None
    with pytest.raises(ScreenPythonError, match="只能在受限计算进程"):
        python._load_callable()


@pytest.mark.parametrize("operation", ["validate", "history_bars"])
def test_infinite_import_in_validate_and_history_is_bounded_and_next_request_runs(
    panels, tmp_path, monkeypatch, operation,
):
    monkeypatch.setenv("LOCI_PYTHON_COMPUTE_TIMEOUT_SECONDS", "2.5")
    marker = tmp_path / f"metadata-import-{operation}.txt"
    code = (f"from pathlib import Path\nPath({str(marker)!r}).write_text('entered')\n"
            "while True:\n    pass\ndef compute(panels, params):\n    return {'signals': panels['close'] > 0}\n")
    python = engine(code)
    before = time.monotonic()
    with pytest.raises(ScreenPythonError) as raised:
        if operation == "validate":
            python.validate()
        else:
            signal_history_bars(python)
    assert raised.value.diagnostics[0].code == "E_COMPUTE_TIMEOUT"
    assert time.monotonic() - before < 6 and marker.exists()
    assert python._callable is None and python._worker_metadata is None
    next_python = engine()
    next_python.validate()
    pd.testing.assert_frame_equal(next_python.compute(panels).signals, panels["close"] > 1)


def test_metadata_declarations_are_cached_by_revision_and_absent_history_stays_none(monkeypatch):
    from src.strategy.application import compute_worker

    calls = []
    original = compute_worker.inspect_python_in_worker
    def inspect(python):
        calls.append(python.strategy_revision)
        return original(python)
    monkeypatch.setattr(compute_worker, "inspect_python_in_worker", inspect)
    python = engine()
    python.validate()
    assert python.history_bars is None and python.live_candidate_codes is None
    assert not python.strict_live_ohlcv and signal_history_bars(python, extra_bars=0) == 1
    assert len(calls) == 1
    python.strategy_revision += ":changed"
    assert python.history_bars is None and len(calls) == 2
    assert python._callable is None


def test_history_and_live_candidate_proxies_evaluate_in_child_with_original_arguments(panels):
    code = """
def compute(panels, params):
    return {'signals': panels['close'] > 0}
def history(params):
    return int(params['N']) * 2
def candidates(panels, today, params):
    assert today == '2026-10-01'
    return list(panels['close'].columns[panels['close'].iloc[-1] > params['N']])
compute.history_bars = history
compute.live_candidate_codes = candidates
compute.strict_live_ohlcv = True
"""
    python = engine(code, manifest={
        "entry_timing": "next_open", "min_bars": 1, "data": {"fields": ["close"]},
        "params": {"N": {"type": "int", "default": 2, "min": 1, "max": 10}},
    })
    assert signal_history_bars(python, extra_bars=0, params={"N": 8}) == 16
    assert python.live_candidate_codes(panels, "2026-10-01", {"N": 2}) == ["300001"]
    assert python.strict_live_ohlcv is True and python._callable is None


def test_infinite_history_attribute_is_terminated_after_bounded_presence_probe(panels, monkeypatch):
    monkeypatch.setenv("LOCI_PYTHON_COMPUTE_TIMEOUT_SECONDS", "2.5")
    python = engine("""
def compute(panels, params):
    return {'signals': panels['close'] > 0}
def history(params):
    while True:
        pass
compute.history_bars = history
""")
    with pytest.raises(ScreenPythonError) as raised:
        signal_history_bars(python)
    assert raised.value.diagnostics[0].code == "E_COMPUTE_TIMEOUT"
    pd.testing.assert_frame_equal(python.compute(panels).signals, panels["close"] > 0)


def test_invalid_history_return_keeps_the_existing_contract():
    python = engine("""
def compute(panels, params):
    return {'signals': panels['close'] > 0}
compute.history_bars = lambda params: True
compute.strict_live_ohlcv = 1
""")
    with pytest.raises(StrategyError, match="必须返回正整数"):
        signal_history_bars(python)
    assert python.strict_live_ohlcv is False


def test_unicode_exception_message_stays_within_error_ipc_budget(panels):
    with pytest.raises(ComputeWorkerError) as raised:
        compute_in_worker(engine("def compute(panels, params):\n    raise ValueError('测试' * 5000)\n"),
                          panels, timeout_seconds=8)
    assert raised.value.code == "E_PYTHON_EXEC"
    assert len(str(raised.value).encode("utf-8")) < 8192


@pytest.mark.parametrize("phase", ["compute", "import"])
def test_real_allocation_above_memory_budget_is_rejected_and_next_request_runs(panels, phase):
    # A 256 MiB allocation is rejected by a 64 MiB headroom before its pages can
    # fill. This exercises the OS limit, rather than substituting MemoryError.
    allocation = "import numpy as np\nbig = np.empty(256 * 1024 * 1024, dtype=np.uint8)\nbig.fill(1)\n"
    if phase == "compute":
        code = "def compute(panels, params):\n" + "".join(
            "    " + line + "\n" for line in allocation.splitlines()
        ) + "    return {'signals': panels['close'] > 0}\n"
    else:
        code = allocation + "\ndef compute(panels, params):\n    return {'signals': panels['close'] > 0}\n"
    with pytest.raises(ComputeWorkerError) as raised:
        compute_in_worker(engine(code), panels, timeout_seconds=8, memory_headroom_bytes=64 * 1024 * 1024)
    assert raised.value.code == "E_COMPUTE_MEMORY"
    assert_next_request_works(panels)


def test_normal_numpy_matrix_succeeds_under_real_memory_limit(panels):
    code = """
import numpy as np
def compute(panels, params):
    matrix = np.empty((1024, 1024), dtype=np.float64)
    matrix.fill(2)
    assert matrix.mean() == 2
    return {'signals': panels['close'] > matrix.mean()}
"""
    result = compute_in_worker(engine(code), panels, timeout_seconds=8,
                               memory_headroom_bytes=64 * 1024 * 1024)
    pd.testing.assert_frame_equal(result.signals, panels["close"] > 2)


@pytest.mark.parametrize("budget", [0, -1, True, "invalid"])
def test_invalid_memory_budget_is_explicit_and_never_starts_worker(panels, monkeypatch, budget):
    from src.strategy.application import compute_worker

    def unexpected(*args, **kwargs):
        pytest.fail("An invalid memory budget must be rejected before staging or spawning.")
    monkeypatch.setattr(compute_worker, "_engine_specification", unexpected)
    with pytest.raises(ComputeWorkerError) as raised:
        compute_in_worker(engine(), panels, timeout_seconds=8, memory_headroom_bytes=budget)
    assert raised.value.code == "E_COMPUTE_MEMORY"


def test_metadata_import_is_also_covered_by_configured_memory_budget(monkeypatch):
    monkeypatch.setenv("LOCI_PYTHON_COMPUTE_MEMORY_HEADROOM_MB", "64")
    python = engine("import numpy as np\nbig = np.ones(256 * 1024 * 1024, dtype=np.uint8)\n"
                    "def compute(panels, params):\n    return {'signals': panels['close'] > 0}\n")
    with pytest.raises(ScreenPythonError) as raised:
        python.validate()
    assert raised.value.diagnostics[0].code == "E_COMPUTE_MEMORY"
    engine().validate()


def test_exhausted_overall_screen_budget_never_stages_or_spawns(panels, monkeypatch):
    from src.strategy.application import compute_runtime, compute_worker

    def unexpected(*args, **kwargs):
        pytest.fail("An exhausted task budget must not stage files or spawn another worker.")
    monkeypatch.setattr(compute_runtime, "remaining_unknown_seconds", lambda: 0)
    monkeypatch.setattr(compute_worker, "_engine_specification", unexpected)
    with pytest.raises(ComputeWorkerTimedOut, match="总时间预算已耗尽"):
        compute_in_worker(engine(), panels, timeout_seconds=8)


def _daemon_compute_and_metadata(sender, panels):
    try:
        with python_worker_scope():
            python = engine(NORMAL_CODE + "\ncompute.history_bars = lambda params: 7\n"
                            "compute.strict_live_ohlcv = True\n")
            python.validate()
            bars = signal_history_bars(python, extra_bars=0)
            strict = python.strict_live_ohlcv
            result = python.compute(panels)
            pid = int(result.factors["PID"].iloc[0, 0])
            del python
        sender.send({"pid": pid, "self_pid": os.getpid(), "bars": bars,
                     "strict": strict, "signals": result.signals.to_numpy().tolist(),
                     "scope_after": in_compute_worker()})
    except BaseException as exc:
        sender.send({"error": f"{type(exc).__name__}: {exc}"})
    finally:
        sender.close()


def test_controlled_daemon_worker_reuses_compute_and_metadata_boundary(panels):
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_daemon_compute_and_metadata, args=(sender, panels), daemon=True)
    try:
        process.start()
        sender.close()
        assert receiver.poll(8), "The real daemon worker must not hang or create a nested process."
        result = receiver.recv()
        process.join(timeout=1)
        assert "error" not in result, result
        assert result["pid"] == result["self_pid"] != os.getpid()
        assert result["bars"] == 7 and result["strict"] is True
        assert result["signals"] == (panels["close"] > 1).to_numpy().tolist()
        assert not result["scope_after"] and not in_compute_worker()
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        process.close()
