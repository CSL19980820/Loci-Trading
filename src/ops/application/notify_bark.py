"""Bark 推送（plain text，无 Apprise）。"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from src.ops.application.notify_send_queue import run_serialized


class BarkError(RuntimeError):
    """Bark 配置或发送失败。"""


def send_bark_text(
    *,
    device_key: str,
    title: str,
    body: str,
    server_url: str = "",
) -> dict[str, Any]:
    key = (device_key or "").strip()
    if not key:
        raise BarkError("Bark 需要 device_key")
    base = (server_url or "https://api.day.app").strip().rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    # Bark: POST /{key} with JSON {title, body}
    url = f"{base}/{urllib.parse.quote(key)}"
    payload = json.dumps(
        {
            "title": (title or "Loci")[:80],
            "body": (body or "")[:3500],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    def _post() -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise BarkError(f"Bark HTTP {exc.code}: {detail}") from exc
        except TimeoutError as exc:
            raise BarkError("无法连接 Bark：timed out") from exc
        except urllib.error.URLError as exc:
            raise BarkError(f"无法连接 Bark：{exc.reason}") from exc
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {"ok": True, "raw": raw[:120]}
        if isinstance(data, dict) and int(data.get("code") or 200) not in (0, 200):
            raise BarkError(f"Bark 错误：{data}")
        return data if isinstance(data, dict) else {"ok": True}

    return run_serialized(_post)
