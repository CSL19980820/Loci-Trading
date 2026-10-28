"""Measure the complete authenticated async screen-run HTTP flow."""
from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import json
import os
import time
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


def _json_request(opener, method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    with opener.open(request, timeout=30) as response:
        return int(response.status), json.loads(response.read().decode("utf-8") or "{}")


def _summary(strategy: str, full: dict, *, wall_seconds: float = 0.0, polls: int = 0) -> dict:
    result = full.get("result") or {}
    return {
        "strategy": strategy,
        "wall_seconds": round(wall_seconds, 3),
        "polls": polls,
        "status": full.get("status"),
        "cache_hit": bool(result.get("cache_hit")),
        "server_elapsed_seconds": result.get("elapsed_seconds"),
        "trade_date": result.get("trade_date"),
        "picks": len(result.get("picks") or []),
        "watch_picks": len(result.get("watch_picks") or []),
        "range": result.get("range"),
        "recorded": result.get("recorded"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="实测完整异步选股 HTTP 墙钟")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--strategy", default="yangshi-tail-v1")
    parser.add_argument("--date", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--poll-ms", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--record-candidates", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    username = str(os.environ.get("PALACE_AUTH_USERNAME") or "")
    password = str(os.environ.get("PALACE_AUTH_PASSWORD") or "")
    if not username or not password:
        raise RuntimeError("PALACE_AUTH_USERNAME / PALACE_AUTH_PASSWORD 未设置")
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    status, login = _json_request(
        opener,
        "POST",
        f"{args.base_url}/api/auth/login",
        {"username": username, "password": password},
    )
    if status != 200 or not login.get("authenticated"):
        raise RuntimeError("登录失败")
    if args.read_only:
        query = urlencode({"strategy": args.strategy})
        status, full = _json_request(
            opener, "GET", f"{args.base_url}/api/screen/run?{query}"
        )
        summary = _summary(args.strategy, full)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        if args.report:
            with open(args.report, "w", encoding="utf-8") as output:
                json.dump(summary, output, ensure_ascii=False, indent=2, sort_keys=True)
        return 0
    payload: dict = {
        "strategy": args.strategy,
        "record_candidates": args.record_candidates,
    }
    if args.start or args.end:
        if not args.start or not args.end:
            raise ValueError("start/end 必须同时提供")
        payload.update(start=args.start, end=args.end)
    elif args.date:
        payload["date"] = args.date
    started = time.perf_counter()
    status, first = _json_request(
        opener, "POST", f"{args.base_url}/api/screen/run", payload
    )
    if status != 202:
        raise RuntimeError(f"启动失败 HTTP {status}: {first}")
    if first.get("busy_reason"):
        raise RuntimeError(f"启动被占用：{first.get('busy_reason')}")
    polls = 0
    deadline = started + args.timeout
    current = first
    while current.get("status") == "running":
        if time.perf_counter() >= deadline:
            raise TimeoutError(f"轮询超时：{current.get('message')}")
        time.sleep(max(0.01, args.poll_ms / 1000.0))
        query = urlencode({"strategy": args.strategy, "view": "progress"})
        status, current = _json_request(
            opener, "GET", f"{args.base_url}/api/screen/run?{query}"
        )
        if status != 200:
            raise RuntimeError(f"进度请求 HTTP {status}: {current}")
        polls += 1
    wall_seconds = time.perf_counter() - started
    if current.get("status") != "done":
        raise RuntimeError(
            f"选股失败：{current.get('status')} {current.get('error') or current.get('message')}"
        )
    query = urlencode({"strategy": args.strategy})
    status, full = _json_request(opener, "GET", f"{args.base_url}/api/screen/run?{query}")
    summary = _summary(
        args.strategy, full, wall_seconds=wall_seconds, polls=polls
    )
    summary["request"] = payload
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as output:
            json.dump(summary, output, ensure_ascii=False, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
