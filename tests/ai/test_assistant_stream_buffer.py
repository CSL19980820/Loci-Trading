from __future__ import annotations

from unittest.mock import patch

from src.ai.application.assistant_stream_buffer import StreamEventBuffer


def test_merges_same_type_until_char_threshold() -> None:
    written: list[tuple[str, dict]] = []
    buf = StreamEventBuffer(lambda etype, payload: written.append((etype, payload)))

    buf.emit({"type": "token", "delta": "a" * 60})
    assert written == []
    buf.emit({"type": "token", "delta": "b" * 60})
    assert len(written) == 1
    assert written[0][0] == "token"
    assert written[0][1]["delta"] == "a" * 60 + "b" * 60


def test_flushes_on_interval_and_type_switch() -> None:
    written: list[tuple[str, dict]] = []
    mono = {"t": 1000.0}

    with patch(
        "src.ai.application.assistant_stream_buffer.time.monotonic",
        side_effect=lambda: mono["t"],
    ):
        buf = StreamEventBuffer(lambda etype, payload: written.append((etype, payload)))
        buf.emit({"type": "think", "delta": "abc"})
        assert written == []
        mono["t"] = 1000.13  # 130ms ≥ 120ms 阈值
        buf.emit({"type": "think", "delta": "def"})
        assert len(written) == 1
        assert written[0][1]["delta"] == "abcdef"

        buf.emit({"type": "token", "delta": "x"})
        assert len(written) == 1  # still buffering token
        buf.emit({"type": "think", "delta": "y"})  # type switch flushes token
        assert written[-1] == ("token", {"type": "token", "delta": "x"})
        buf.flush()
        assert written[-1] == ("think", {"type": "think", "delta": "y"})


def test_non_stream_events_flush_then_persist_immediately() -> None:
    written: list[tuple[str, dict]] = []
    buf = StreamEventBuffer(lambda etype, payload: written.append((etype, payload)))

    buf.emit({"type": "token", "delta": "hi"})
    buf.emit({"type": "tool_start", "name": "x", "arguments": {}})
    assert written[0] == ("token", {"type": "token", "delta": "hi"})
    assert written[1][0] == "tool_start"
    assert written[1][1]["name"] == "x"
