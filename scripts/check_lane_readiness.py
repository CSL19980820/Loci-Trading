r"""全 lane 数据源可用性兵棋盘：每条线路真打一次，看谁活着。

用法（仓库根目录）::

    .\\.venv\\Scripts\\python.exe scripts\\check_lane_readiness.py

只读网络，不写任何库。用来回答「这条线路到底能不能用」，
而不是只看配置里有没有登记。
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE = "600519"


def probe_tdx_servers(*, timeout: float = 2.0) -> list[dict]:
    """逐节点执行真实日 K 请求，保留协议错误；握手成功不算可用。"""
    from src.market.infrastructure.tdx_daily import _api_class, _servers

    api_class = _api_class()

    def one(pair: tuple[str, int]) -> dict:
        host, port = pair
        row = {"server": f"{host}:{port}", "ok": False, "rows": 0, "error": ""}
        began = time.perf_counter()
        try:
            api = api_class(raise_exception=True, auto_retry=False)
            with api.connect(host, port, time_out=timeout):
                bars = api.get_security_bars(9, 1, SAMPLE, 0, 4)
            if bars:
                row.update(ok=True, rows=len(bars), last_date=str(bars[-1]["datetime"])[:10])
            else:
                row["error"] = "握手成功，但日 K 返回空数据"
        except Exception as exc:
            cause = exc.__cause__ or exc.__context__ or exc
            row["error"] = f"{type(cause).__name__}: {cause}"
        row["rtt_ms"] = round((time.perf_counter() - began) * 1000)
        return row

    servers = _servers()
    with ThreadPoolExecutor(max_workers=min(16, len(servers)) or 1) as pool:
        return list(pool.map(one, servers))


def probe_all(lane: str, timeout_note: str = "") -> list:
    from src.market.infrastructure.adapters import adapters_for_lane, probe_lane

    adapters = adapters_for_lane(lane)
    if not adapters:
        return []
    began = time.perf_counter()
    try:
        results = probe_lane(lane, code=SAMPLE)
    except Exception as exc:
        print("  %-18s 整条线路探测异常 %s: %s" % (lane, type(exc).__name__, exc))
        return []
    elapsed = time.perf_counter() - began
    print("  (%.1fs%s)" % (elapsed, timeout_note))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="全 lane 数据源可用性核对")
    parser.add_argument("--lanes", default="", help="只查这些 lane，逗号分隔")
    parser.add_argument("--tdx-servers", action="store_true", help="逐台核验通达信日 K，打印完整失败原因")
    args = parser.parse_args()

    tdx_down = False
    if args.tdx_servers:
        results = probe_tdx_servers()
        alive = sum(bool(row["ok"]) for row in results)
        print("通达信节点：%d / %d 可用（日 K 实取）" % (alive, len(results)))
        for row in results:
            detail = ("%s，%d 根" % (row["last_date"], row["rows"])) if row["ok"] else row["error"]
            print("  %-24s %s  %sms  %s" % (row["server"], "可用" if row["ok"] else "失败", row["rtt_ms"], detail))
        tdx_down = not alive

    from src.market.infrastructure.adapters import ALL_LANES, adapters_for_lane

    only = {x.strip() for x in args.lanes.split(",") if x.strip()}
    lanes = [lane for lane in ALL_LANES if not only or lane in only]

    print("=" * 76)
    print("数据源线路可用性（样本 %s）" % SAMPLE)
    print("=" * 76)

    healthy = 0
    degraded = []
    for lane in lanes:
        adapters = adapters_for_lane(lane)
        if not adapters:
            print("\n[%s] 无注册源" % lane)
            continue
        print("\n[%s] 注册源 %s" % (lane, [a.meta.id for a in adapters]))
        results = probe_all(lane)
        lane_ok = False
        for item in results:
            row = item.to_dict() if hasattr(item, "to_dict") else dict(item)
            state = "unsupported"
            if row.get("unsupported"):
                state = "不支持"
            elif row.get("ok"):
                state = "可用"
                lane_ok = True
            else:
                state = "失败"
            print(
                "    %-12s %-8s %sms  %s"
                % (
                    row.get("adapter_id"),
                    state,
                    row.get("rtt_ms"),
                    str(row.get("error") or "")[:70],
                )
            )
        if lane_ok:
            healthy += 1
        else:
            degraded.append(lane)

    print("\n" + "=" * 76)
    print("可用 lane %d / 有源 lane %d" % (healthy, healthy + len(degraded)))
    if degraded:
        print("无可用源：%s" % ", ".join(degraded))
    return 1 if degraded or tdx_down else 0


if __name__ == "__main__":
    raise SystemExit(main())
