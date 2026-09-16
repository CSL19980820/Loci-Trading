"""完整JSON工件的有界读取；保留对象内容，避免整份原始字节并驻内存。"""
from decimal import Decimal
from collections.abc import Iterator
import hashlib
from pathlib import Path
from typing import Any, BinaryIO

import ijson


class _DigestReader:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size: int = 65536) -> bytes:
        chunk = self.stream.read(min(size, 65536) if size >= 0 else 65536)
        self.digest.update(chunk)
        return chunk


def _events(reader: _DigestReader) -> Iterator[tuple[str, str, Any]]:
    keys: dict[str, str] = {}
    for prefix, event, value in ijson.parse(reader, buf_size=65536):
        if event == "number" and isinstance(value, Decimal):
            value = float(value)
        elif event == "map_key":
            value = keys.setdefault(value, value)
        yield prefix, event, value


def read_json_file(path: Path, *, expected_sha256: str) -> Any:
    """先验证文件，再分块解析；复核解析期间的字节，拒绝中途变化或尾随数据。"""
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha256:
            raise ValueError("artifact manifest hash 校验失败")
        stream.seek(0)
        reader = _DigestReader(stream)
        try:
            values = ijson.items(_events(reader), "")
            value = next(values)
            sentinel = object()
            if next(values, sentinel) is not sentinel:
                raise ValueError("存在多个JSON值")
        except (ijson.JSONError, StopIteration, ValueError, OverflowError) as exc:
            raise ValueError("artifact 不是有效 JSON") from exc
        if reader.digest.hexdigest() != expected_sha256:
            raise ValueError("artifact 解析期间内容变化，manifest hash 校验失败")
        return value
