"""出站发送队列：串行、失败重试 3 次、三次后再下一条。"""
from __future__ import annotations

import json
import threading
import time
import unittest
from unittest.mock import patch

from src.ops.application.notify import NotifyError, send_wecom_text

_HOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdef1234567890"


def _content_of(body: bytes) -> str:
    return str(json.loads(body.decode("utf-8"))["text"]["content"])


class NotifySendQueueTests(unittest.TestCase):
    def test_retries_twice_then_succeeds(self) -> None:
        calls = {"n": 0}

        def flaky(_url: str, _body: bytes) -> dict[str, object]:
            calls["n"] += 1
            if calls["n"] < 3:
                raise NotifyError("timed out")
            return {"errcode": 0}

        with (
            patch("src.ops.application.notify._post", side_effect=flaky),
            patch("src.ops.application.notify_send_queue.time.sleep"),
        ):
            payload = send_wecom_text(_HOOK, "ok")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(payload.get("errcode"), 0)

    def test_gives_up_after_three_failures(self) -> None:
        calls = {"n": 0}

        def always_fail(_url: str, _body: bytes) -> dict[str, object]:
            calls["n"] += 1
            raise NotifyError("timed out")

        with (
            patch("src.ops.application.notify._post", side_effect=always_fail),
            patch("src.ops.application.notify_send_queue.time.sleep"),
        ):
            with self.assertRaises(NotifyError):
                send_wecom_text(_HOOK, "nope")
        self.assertEqual(calls["n"], 3)

    def test_next_message_runs_after_three_failures(self) -> None:
        seen: list[str] = []

        def post(_url: str, body: bytes) -> dict[str, object]:
            text = _content_of(body)
            seen.append(text)
            if text == "first":
                raise NotifyError("timed out")
            return {"errcode": 0}

        with (
            patch("src.ops.application.notify._post", side_effect=post),
            patch("src.ops.application.notify_send_queue.time.sleep"),
        ):
            with self.assertRaises(NotifyError):
                send_wecom_text(_HOOK, "first")
            send_wecom_text(_HOOK, "second")
        self.assertEqual(seen, ["first", "first", "first", "second"])

    def test_concurrent_posts_never_overlap(self) -> None:
        lock = threading.Lock()
        inflight = {"n": 0, "max": 0}

        def slow_post(_url: str, _body: bytes) -> dict[str, object]:
            with lock:
                inflight["n"] += 1
                inflight["max"] = max(inflight["max"], inflight["n"])
            time.sleep(0.05)
            with lock:
                inflight["n"] -= 1
            return {"errcode": 0}

        with patch("src.ops.application.notify._post", side_effect=slow_post):
            threads = [
                threading.Thread(target=send_wecom_text, args=(_HOOK, f"m{i}"))
                for i in range(5)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
        self.assertEqual(inflight["max"], 1)
        self.assertEqual(inflight["n"], 0)


if __name__ == "__main__":
    unittest.main()
