r"""全 lane 数据源可用性兵棋盘：每条线路真打一次，看谁活着。

用法（仓库根目录）::

    .\\.venv\\Scripts\\python.exe scripts\\check_lane_readiness.py

只读网络，不写任何库。用来回答「这条线路到底能不能用」，
而不是只看配置里有没有登记。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE = "600519"


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
    args = parser.parse_args()

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
