import hashlib
from collections.abc import Iterator
import json
from pathlib import Path
from typing import Any

import pytest

from src.research.infrastructure import json_artifacts as module


def _file(tmp_path: Path, raw: bytes) -> tuple[Path, str]:
    path = tmp_path / "input.json"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_stream_reader_matches_json_numeric_and_unicode_semantics(tmp_path) -> None:
    value = {"中文😀": [True, None, -0.0, 1.2345678901234567, 1e-100, 1e308, 2**100]}
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8") + b" " * 100_000
    path, digest = _file(tmp_path, raw)
    assert module.read_json_file(path, expected_sha256=digest) == json.loads(raw)


@pytest.mark.parametrize("raw", [b'{"x":1', b'{} {}', b'{} trailing', b'{"x":NaN}'])
def test_stream_reader_rejects_incomplete_or_non_json_documents(tmp_path, raw) -> None:
    path, digest = _file(tmp_path, raw)
    with pytest.raises(ValueError, match="有效 JSON"):
        module.read_json_file(path, expected_sha256=digest)


def test_stream_reader_checks_hash_before_and_during_parsing(tmp_path, monkeypatch) -> None:
    path, digest = _file(tmp_path, b'{"x":1}')
    with pytest.raises(ValueError, match="manifest hash"):
        module.read_json_file(path, expected_sha256="0" * 64)
    original = module._events
    def changed(reader: Any) -> Iterator[tuple[str, str, Any]]:
        path.write_bytes(b'{"x":2}')
        yield from original(reader)
    monkeypatch.setattr(module, "_events", changed)
    with pytest.raises(ValueError, match="解析期间内容变化"):
        module.read_json_file(path, expected_sha256=digest)


def test_stream_reader_never_requests_an_unbounded_file_read(tmp_path, monkeypatch) -> None:
    raw = json.dumps({"prices": list(range(30_000))}).encode()
    path, digest = _file(tmp_path, raw)
    original = Path.open
    sizes = []
    class Tracked:
        def __init__(self, handle: Any) -> None:
            self.handle = handle
        def __getattr__(self, name: str) -> Any:
            return getattr(self.handle, name)
        def __enter__(self) -> "Tracked":
            return self
        def __exit__(self, *args: Any) -> Any:
            return self.handle.__exit__(*args)
        def read(self, size: int = -1) -> bytes:
            assert 0 <= size <= 65536
            sizes.append(size)
            return self.handle.read(size)
        def readinto(self, buffer: bytearray) -> int:
            assert len(buffer) <= 262144
            sizes.append(len(buffer))
            return self.handle.readinto(buffer)
    monkeypatch.setattr(Path, "open", lambda self, *a, **kw: Tracked(original(self, *a, **kw))
                        if self == path else original(self, *a, **kw))
    assert module.read_json_file(path, expected_sha256=digest) == json.loads(raw)
    assert len(sizes) > 3
