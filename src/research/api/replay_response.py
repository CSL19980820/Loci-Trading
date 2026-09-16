"""保留完整回放JSON合同，避免将comparison再次物化成响应字符串。"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from src.research.application import ResearchReplayError
from src.research.domain import validate_run_id


CHUNK_BYTES = 64 * 1024


def json_chunks(value: Any) -> Iterator[bytes]:
    """批量输出UTF-8，不能把JSON编码器的每个小token都变成网络包。"""
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    buffer = bytearray()
    for token in encoder.iterencode(value):
        for offset in range(0, len(token), CHUNK_BYTES // 4):
            buffer.extend(token[offset:offset + CHUNK_BYTES // 4].encode("utf-8"))
            while len(buffer) >= CHUNK_BYTES:
                yield bytes(buffer[:CHUNK_BYTES])
                del buffer[:CHUNK_BYTES]
    if buffer:
        yield bytes(buffer)


def replay_json_response(
    *, root: Path | str, run_id: str, run_card: Mapping[str, Any],
    workflow: Mapping[str, Any] | None, receipt: Mapping[str, Any],
) -> StreamingResponse:
    """所有校验在HTTP 200前完成；同一已校验文件句柄用于发送完整comparison。"""
    base = Path(root).resolve()
    folder = (base / validate_run_id(run_id)).resolve()
    target = (folder / "replay-comparison.json").resolve()
    if base not in target.parents or folder not in target.parents or receipt.get("path") != "replay-comparison.json":
        raise ResearchReplayError("回放comparison artifact路径无效")
    # 小包装中的run_card也可能很大，校验与发送均分块，不构造整份JSON文本。
    for value in (run_card, workflow, receipt):
        for _chunk in json_chunks(value):
            pass
    try:
        handle = target.open("rb")
    except OSError as exc:
        raise ResearchReplayError("回放comparison artifact不可读取") from exc
    try:
        digest = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
            size += len(chunk)
        if digest.hexdigest() != receipt.get("sha256") or (
            receipt.get("size_bytes") is not None and size != receipt["size_bytes"]
        ):
            raise ResearchReplayError("回放comparison artifact完整性校验失败")
        handle.seek(0)
    except BaseException:
        handle.close()
        raise

    def body() -> Iterator[bytes]:
        try:
            yield b'{"run_card":'
            yield from json_chunks(run_card)
            yield b',"workflow":'
            yield from json_chunks(workflow)
            yield b',"comparison":'
            yield from iter(lambda: handle.read(CHUNK_BYTES), b"")
            yield b',"receipt":'
            yield from json_chunks(receipt)
            yield b'}'
        finally:
            handle.close()

    return StreamingResponse(
        body(), media_type="application/json", background=BackgroundTask(handle.close),
    )
