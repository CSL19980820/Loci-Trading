"""研究产物编码保持既有hash，同时约束大型Unicode载荷的额外内存。"""
import hashlib
from collections.abc import Mapping
import json
import math
from pathlib import Path
import tracemalloc

import pytest

from src.research.infrastructure.run_cards import ResearchRunCardStore, RunCardImmutableError, _write_json_file


def _previous(value, **kwargs) -> bytes:
    def original_safe(item):
        if isinstance(item, Mapping):
            return {str(key): original_safe(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [original_safe(child) for child in item]
        return None if isinstance(item, float) and not math.isfinite(item) else item
    return (json.dumps(original_safe(value), ensure_ascii=False, indent=2,
                       sort_keys=True, allow_nan=False, **kwargs) + "\n").encode("utf-8")


def test_artifact_json_preserves_existing_bytes_and_nonfinite_policy(tmp_path) -> None:
    value = {"中文😀": [1.25, float("nan"), float("inf"), -0.0], 2: (True, None)}
    target = tmp_path / "result.json"
    _write_json_file(target, value)
    assert target.read_bytes() == _previous(value)
    assert math.isnan(value["中文😀"][1]) and isinstance(value[2], tuple)
    with pytest.raises(TypeError):
        _write_json_file(tmp_path / "unsupported.json", {"unsupported": Path("example")})


def test_atomic_card_json_preserves_default_stringification_and_hash(tmp_path) -> None:
    value = {"路径": Path("example"), "价格": 1.5}
    expected = _previous(value, default=str)
    path = tmp_path / "card.json"
    digest = ResearchRunCardStore._atomic_json_write(path, value)
    assert path.read_bytes() == expected
    assert digest == hashlib.sha256(expected).hexdigest()


def test_large_artifact_encoding_has_bounded_extra_memory(tmp_path) -> None:
    value = {"prices": [float(i) / 100 for i in range(100_000)], "说明": "真实交易😀"}
    expected = _previous(value)
    store = ResearchRunCardStore(tmp_path / "runs")
    card = store.create(run_id="rc-encoding-001")
    tracemalloc.start()
    try:
        entry = store.write_artifact(card.run_id, "backtest.json", value)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert (store.root / card.run_id / "backtest.json").read_bytes() == expected
    assert entry.sha256 == hashlib.sha256(expected).hexdigest()
    assert peak < len(expected) * 4


def test_normalized_trade_rows_do_not_require_a_second_deep_copy(tmp_path) -> None:
    value = {"trades": [{"p": 1.5, "v": 100} for _ in range(20_000)]}
    expected = _previous(value)
    tracemalloc.start()
    try:
        _write_json_file(tmp_path / "rows.json", value)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert (tmp_path / "rows.json").read_bytes() == expected
    assert peak < len(expected) * 3


def test_mapping_artifacts_keep_immutability_and_clean_temporary_files(tmp_path) -> None:
    store = ResearchRunCardStore(tmp_path / "runs")
    card = store.create(run_id="rc-atomic-001")
    entry = store.write_artifact(card.run_id, "nested/result.json", {"price": 1.5})
    assert store.write_artifact(card.run_id, "nested/result.json", {"price": 1.5}) == entry
    with pytest.raises(RunCardImmutableError):
        store.write_artifact(card.run_id, "nested/result.json", {"price": 2.5})
    with pytest.raises(TypeError):
        store.write_artifact(card.run_id, "bad.json", {"value": Path("unsupported")})
    store.update_status(card.run_id, "rejected")
    with pytest.raises(RunCardImmutableError):
        store.write_artifact(card.run_id, "forbidden.json", {"value": 1})
    root = store.root / card.run_id
    assert json.loads((root / "nested/result.json").read_bytes()) == {"price": 1.5}
    assert not (root / "bad.json").exists() and not (root / "forbidden.json").exists()
    assert not list(root.rglob("*.tmp"))


def test_artifact_does_not_reload_large_card_twice_inside_one_lock(tmp_path, monkeypatch) -> None:
    store = ResearchRunCardStore(tmp_path / "runs")
    card = store.create(run_id="rc-read-once-001")
    original = store._load_unlocked
    reads = []
    def observed(run_id):
        reads.append(run_id)
        return original(run_id)
    monkeypatch.setattr(store, "_load_unlocked", observed)
    store.write_artifact(card.run_id, "analysis.json", {"net_pnl": 1.5})
    assert reads == [card.run_id]


def test_file_artifact_preserves_source_and_immutable_target(tmp_path) -> None:
    store = ResearchRunCardStore(tmp_path / "runs")
    card = store.create(run_id="rc-file-001")
    source = tmp_path / "source.json"
    source.write_bytes(b'{"full":true}\n')
    entry = store.write_artifact(card.run_id, "comparison.json", source)
    assert source.read_bytes() == b'{"full":true}\n'
    assert (store.root / card.run_id / "comparison.json").read_bytes() == source.read_bytes()
    assert entry.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_bytes(b'{"full":false}\n')
    with pytest.raises(RunCardImmutableError):
        store.write_artifact(card.run_id, "comparison.json", source)
    assert not list((store.root / card.run_id).glob("*.tmp"))
